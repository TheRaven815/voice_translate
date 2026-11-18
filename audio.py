"""Yakalama/oynatma PCM dönüşümleri. Ağ ve aygıt yok."""

from __future__ import annotations

import numpy as np

from numpy.lib.stride_tricks import sliding_window_view

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
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self._leftover = np.empty(0, dtype=np.float32)
        self._phase = 0.0
        self._int_offset = 0
        self._decim_factor: int | None = (
            self.in_rate // self.out_rate
            if self.in_rate > self.out_rate and self.in_rate % self.out_rate == 0
            else None
        )
        if self.in_rate > self.out_rate:
            m = 41
            cutoff = self.out_rate * 0.45
            fc = cutoff / self.in_rate
            n = np.arange(m) - (m - 1) / 2.0
            h = 2.0 * fc * np.sinc(2.0 * fc * n) * np.hamming(m)
            taps = (h / np.sum(h)).astype(np.float32)
            self._taps: np.ndarray | None = taps
            self._taps_rev: np.ndarray | None = np.ascontiguousarray(taps[::-1], dtype=np.float32)
            self._filter_state = np.zeros(m - 1, dtype=np.float32)
            self._work_buf = np.empty((m - 1) + 1024, dtype=np.float32)
            self._filt_buf = np.empty(1024, dtype=np.float32)
        else:
            self._taps = None
            self._taps_rev = None
            self._filter_state = np.empty(0, dtype=np.float32)
            self._work_buf = np.empty(0, dtype=np.float32)
            self._filt_buf = np.empty(0, dtype=np.float32)
        self._out_f32 = np.empty(512, dtype=np.float32)
        self._pcm_buf = np.empty(512, dtype=np.int16)
        self._idx_ramp = np.arange(512, dtype=np.float64)

    def _ensure_out_capacity(self, n_out: int) -> None:
        if n_out > self._pcm_buf.size:
            cap = max(n_out, self._pcm_buf.size * 2)
            self._pcm_buf = np.empty(cap, dtype=np.int16)
            self._out_f32 = np.empty(cap, dtype=np.float32)

    def _to_pcm_bytes(self, samples_f32: np.ndarray, *, in_place: bool = False) -> bytes:
        n_out = int(samples_f32.size)
        if n_out <= 0:
            return b""
        self._ensure_out_capacity(n_out)
        scaled = samples_f32 if in_place else self._out_f32[:n_out]
        np.multiply(samples_f32, 32767.0, out=scaled)
        np.clip(scaled, -32768.0, 32767.0, out=scaled)
        pcm_slice = self._pcm_buf[:n_out]
        np.copyto(pcm_slice, scaled, casting="unsafe")
        return pcm_slice.tobytes()

    def process(self, frame: np.ndarray) -> bytes:
        if frame is None or frame.size == 0:
            return b""
        mono = (
            frame.mean(axis=1, dtype=np.float32)
            if frame.ndim > 1
            else np.asarray(frame, dtype=np.float32)
        )
        n_in = int(mono.size)
        if n_in == 0:
            return b""

        if self.in_rate == self.out_rate:
            return self._to_pcm_bytes(mono, in_place=False)

        # Tam sayılı indirme hızlı yolu (48000 -> 16000 = 3:1, 32000 -> 16000 = 2:1):
        # Yalnızca çıkışa düşecek FIR pencereleri hesaplanır; ara dizi kopyası üretilmez.
        if self._decim_factor is not None and self._taps_rev is not None:
            ratio = self._decim_factor
            state_len = self._filter_state.size
            needed = state_len + n_in
            if needed > self._work_buf.size:
                self._work_buf = np.empty(max(needed, self._work_buf.size * 2), dtype=np.float32)
            work = self._work_buf[:needed]
            work[:state_len] = self._filter_state
            work[state_len:] = mono
            self._filter_state[:] = work[n_in:needed]

            offset = self._int_offset
            if n_in <= offset:
                self._int_offset = offset - n_in
                return b""

            windows = sliding_window_view(work, state_len + 1)[offset::ratio]
            n_out = int(windows.shape[0])
            self._ensure_out_capacity(n_out)
            out_f32 = self._out_f32[:n_out]
            np.dot(windows, self._taps_rev, out=out_f32)
            self._int_offset = (offset + n_out * ratio) - n_in
            return self._to_pcm_bytes(out_f32, in_place=True)

        if self._taps_rev is not None:
            state_len = self._filter_state.size
            needed = state_len + n_in
            if needed > self._work_buf.size:
                self._work_buf = np.empty(max(needed, self._work_buf.size * 2), dtype=np.float32)
            if n_in > self._filt_buf.size:
                self._filt_buf = np.empty(max(n_in, self._filt_buf.size * 2), dtype=np.float32)
            work = self._work_buf[:needed]
            work[:state_len] = self._filter_state
            work[state_len:] = mono
            self._filter_state[:] = work[n_in:needed]
            filtered = self._filt_buf[:n_in]
            np.dot(sliding_window_view(work, state_len + 1), self._taps_rev, out=filtered)
            mono = filtered

        if self._leftover.size > 0:
            mono = np.concatenate([self._leftover, mono])
        total_in = int(mono.size)
        if total_in < 2:
            self._leftover = mono.copy()
            return b""

        step = self.in_rate / self.out_rate
        max_idx = total_in - 1.0001
        if self._phase >= max_idx:
            self._phase -= total_in
            self._leftover = np.empty(0, dtype=np.float32)
            return b""

        n_out = int((max_idx - self._phase) / step) + 1
        if n_out <= 0:
            self._leftover = mono.copy()
            return b""

        if n_out > self._idx_ramp.size:
            self._idx_ramp = np.arange(max(n_out, self._idx_ramp.size * 2), dtype=np.float64)
        in_indices = self._phase + self._idx_ramp[:n_out] * step
        idx_floor = in_indices.astype(np.int32)
        idx_ceil = idx_floor + 1
        frac = (in_indices - idx_floor).astype(np.float32)

        self._ensure_out_capacity(n_out)
        out_samples = self._out_f32[:n_out]
        np.multiply(mono[idx_floor], 1.0 - frac, out=out_samples)
        out_samples += mono[idx_ceil] * frac

        next_idx = float(in_indices[-1] + step)
        consumed = int(np.floor(in_indices[-1]))
        self._leftover = mono[consumed:].copy()
        self._phase = float(next_idx - consumed)

        return self._to_pcm_bytes(out_samples, in_place=True)

    def reset(self) -> None:
        self._leftover = np.empty(0, dtype=np.float32)
        self._phase = 0.0
        self._int_offset = 0
        if self._taps is not None:
            self._filter_state.fill(0.0)

def to_16k_mono(frame: np.ndarray, in_rate: int = CAPTURE_RATE) -> bytes:
    """float32 (n, ch) yakalamayı 16 kHz mono int16 PCM'e çevirir."""
    mono = frame.mean(axis=1) if frame.ndim > 1 else frame
    if in_rate == SEND_SAMPLE_RATE:
        pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
        return pcm.tobytes()
    conv = AudioConverter(in_rate, SEND_SAMPLE_RATE)
    return conv.process(mono)
