"""Yakalama/oynatma PCM dönüşümleri. Ağ ve aygıt yok."""

from __future__ import annotations

import numpy as np

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CAPTURE_RATE = 48000  # Windows mix format; yakalanıp 16k'ya indirilir
CAPTURE_BLOCK = 960  # 48000 Hz'de 20 ms


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    """Gemini PCM16 (24 kHz) → soundcard'ın beklediği [-1, 1] float32."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)
    return samples.astype(np.float32) * (1.0 / 32768.0)


def to_16k_mono(frame: np.ndarray) -> bytes:
    """float32 (n, ch) yakalamayı 16 kHz mono int16 PCM'e çevirir."""
    mono = frame.mean(axis=1).astype(np.float32)
    n_out = int(len(mono) * SEND_SAMPLE_RATE / CAPTURE_RATE)
    if n_out != len(mono):
        idx = np.linspace(0, len(mono) - 1, n_out).astype(np.float32)
        mono = np.interp(idx, np.arange(len(mono), dtype=np.float32), mono).astype(np.float32)
    pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
    return pcm.tobytes()
