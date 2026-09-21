"""Yakalama/oynatma PCM dönüşümleri. Ağ ve aygıt yok."""

from __future__ import annotations

import numpy as np

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CAPTURE_RATE = 48000  # Windows mix format; yakalanıp 16k'ya indirilir
CAPTURE_BLOCK = 960  # 48000 Hz'de 20 ms


def pcm16_to_float(pcm: bytes, leftover: bytearray | None = None) -> np.ndarray:
    """Gemini PCM16 (24 kHz) → soundcard'ın beklediği [-1, 1] float32.

    leftover verilirse tek kalan bayt sonraki pakete taşınır; aksi halde
    (eski davranış) tek bayt atılır. Tek bayt kaybı sonraki paketi kaydırır
    ve tıkırtı üretir.
    """
    if leftover:
        pcm = bytes(leftover) + pcm
        leftover.clear()
    if len(pcm) < 2:
        if leftover is not None and pcm:
            leftover.extend(pcm)
        return np.empty(0, dtype=np.float32)
    if len(pcm) % 2 != 0:
        if leftover is not None:
            leftover.extend(pcm[-1:])
        pcm = pcm[:-1]
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)
    return samples.astype(np.float32) * (1.0 / 32768.0)


def soften_join(previous: float, audio: np.ndarray, fade_n: int = 48) -> np.ndarray:
    """Paket sınırındaki büyük sıçramayı ~2 ms'lik rampaya yayar.

    Normal dalga bu eşiğin altında kalır. Eşik aşılırsa sınır bir çıt üretir;
    rampa yalnız yeni paketin başını, bir önceki örneğe bağlar.
    """
    if audio.size == 0:
        return audio
    if abs(float(audio[0]) - float(previous)) < 0.5:
        return audio
    n = min(max(int(fade_n), 2), int(audio.size))
    out = np.array(audio, dtype=np.float32, copy=True)
    w = np.linspace(0.0, 1.0, n, dtype=np.float32)
    anchor = np.float32(previous)
    out[:n] = anchor + (out[:n] - anchor) * w
    return out


def cosine_fade(audio: np.ndarray, fade_n: int, *, fade_in: bool) -> np.ndarray:
    """Sessizlik sınırında kosinüs rampa; sıfır olmayan örnek tıkırtısını keser."""
    if audio.size == 0:
        return audio
    n = min(max(int(fade_n), 0), int(audio.size))
    if n <= 1:
        return audio
    out = np.array(audio, dtype=np.float32, copy=True)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    w = (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32, copy=False)
    if fade_in:
        out[:n] *= w
    else:
        out[-n:] *= w[::-1]
    return out

class AudioConverter:
    """Yakalama örneklerini 16 kHz mono PCM16'ya dönüştürür.
    Artan örnekleri bloklar arasında saklayarak faz kayması, tıkırtı ve perde bozulmasını önler.
    """

    def __init__(self, in_rate: int = CAPTURE_RATE, out_rate: int = SEND_SAMPLE_RATE):
        self.in_rate = in_rate
        self.out_rate = out_rate
        self._leftover = np.empty(0, dtype=np.float32)
        self._phase = 0.0
        if in_rate > out_rate:
            m = 41
            cutoff = out_rate * 0.45
            fc = cutoff / in_rate
            n = np.arange(m) - (m - 1) / 2.0
            h = 2.0 * fc * np.sinc(2.0 * fc * n) * np.hamming(m)
            self._taps: np.ndarray | None = (h / np.sum(h)).astype(np.float32)
            self._filter_state = np.zeros(m - 1, dtype=np.float32)
        else:
            self._taps = None
            self._filter_state = np.empty(0, dtype=np.float32)
    def process(self, frame: np.ndarray) -> bytes:
        mono = frame.mean(axis=1) if frame.ndim > 1 else frame
        if self._taps is not None and len(mono) > 0:
            full_mono = np.concatenate([self._filter_state, mono])
            mono = np.convolve(full_mono, self._taps, mode="valid").astype(np.float32)
            self._filter_state = full_mono[-(len(self._taps) - 1):].astype(np.float32)
        if len(self._leftover) > 0:
            mono = np.concatenate([self._leftover, mono])
        total_in = len(mono)
        if total_in < 2:
            self._leftover = mono.astype(np.float32)
            return b""

        if self.in_rate == self.out_rate:
            pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
            self._leftover = np.empty(0, dtype=np.float32)
            return pcm.tobytes()

        step = self.in_rate / self.out_rate
        max_idx = total_in - 1.0001
        if self._phase >= max_idx:
            self._phase -= total_in
            self._leftover = np.empty(0, dtype=np.float32)
            return b""

        n_out = int((max_idx - self._phase) / step) + 1
        if n_out <= 0:
            self._leftover = mono.astype(np.float32)
            return b""

        in_indices = self._phase + np.arange(n_out) * step
        idx_floor = in_indices.astype(np.int32)
        idx_ceil = idx_floor + 1
        frac = (in_indices - idx_floor).astype(np.float32)

        out_samples = mono[idx_floor] * (1.0 - frac) + mono[idx_ceil] * frac

        next_idx = in_indices[-1] + step
        consumed = int(np.floor(in_indices[-1]))
        self._leftover = mono[consumed:].astype(np.float32)
        self._phase = float(next_idx - consumed)

        pcm = np.clip(out_samples * 32767.0, -32768, 32767).astype(np.int16)
        return pcm.tobytes()

    def reset(self) -> None:
        self._leftover = np.empty(0, dtype=np.float32)
        self._phase = 0.0
        if self._taps is not None:
            self._filter_state = np.zeros(len(self._taps) - 1, dtype=np.float32)

def to_16k_mono(frame: np.ndarray, in_rate: int = CAPTURE_RATE) -> bytes:
    """float32 (n, ch) yakalamayı 16 kHz mono int16 PCM'e çevirir."""
    mono = frame.mean(axis=1) if frame.ndim > 1 else frame
    if in_rate == SEND_SAMPLE_RATE:
        pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
        return pcm.tobytes()
    conv = AudioConverter(in_rate, SEND_SAMPLE_RATE)
    return conv.process(mono)
