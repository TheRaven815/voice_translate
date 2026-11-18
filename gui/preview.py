"""Oturum kapalıyken seçili girişten canlı VU seviyesi üreten önizleme izleyicisi."""

from __future__ import annotations

import threading
import warnings

import numpy as np

from devices import device_key
from loop import SystemAudioLoop, open_capture_recorder


class _InputPreviewMonitor:
    """Oturum kapalıyken seçili girişten VU seviyesi üretir.

    Kendi daemon thread'inde kısa bloklarla okur; asıl yakalama/çeviri
    hattına dokunmaz. Oturum çalışırken aygıt boşaltılır (set_device(None)),
    böylece ses aygıtı çakışması ve yan etki olmaz. Hatalar sessizce
    yutulur: seviye 0'a düşer, arayüz asla bozulmaz.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._level: float = 0.0
        self._current = None
        self._pending = None
        self._has_pending: bool = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="input-preview", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()

    def set_device(self, dev) -> None:
        with self._lock:
            if device_key(dev) == device_key(self._current) and not self._has_pending:
                return
            self._pending = dev
            self._has_pending = True

    def get_level(self) -> float:
        with self._lock:
            return float(self._level)

    def _set_level(self, val: float) -> None:
        with self._lock:
            try:
                v = float(val)
            except (TypeError, ValueError):
                v = 0.0
            self._level = max(0.0, min(1.0, v))

    def _take_pending(self):
        with self._lock:
            if not self._has_pending:
                return None, False
            dev = self._pending
            self._pending = None
            self._has_pending = False
            self._current = dev
            return dev, True

    def _run(self) -> None:
        from audio import CAPTURE_RATE
        from loop import CAPTURE_BUFFER_BLOCKS

        delay = 0.25
        while not self._stop.is_set():
            dev, changed = self._take_pending()
            if not changed:
                with self._lock:
                    dev = self._current
                if dev is None:
                    self._set_level(0.0)
                    if self._stop.wait(0.1):
                        break
                    continue
            elif dev is None:
                self._set_level(0.0)
                delay = 0.25
                continue
            try:
                self._inner(dev, CAPTURE_RATE, CAPTURE_BUFFER_BLOCKS)
                delay = 0.25
            except Exception:
                self._set_level(0.0)
                if self._stop.wait(min(delay, 2.0)):
                    break
                delay = min(delay * 2.0, 2.0)
                continue
            if self._stop.is_set():
                break

    def _inner(self, dev, samplerate: int, buffer_blocks: int) -> None:
        from loop import ensure_discontinuity_suppressed

        try:
            ensure_discontinuity_suppressed()
        except Exception:
            pass
        with open_capture_recorder(dev, exclude=False) as (
            mic,
            _active_rate,
            block_frames,
            _active_ch,
            _used_fallback,
        ):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*data discontinuity.*")
                while not self._stop.is_set():
                    with self._lock:
                        if self._has_pending:
                            return
                    frame = mic.record(numframes=block_frames)
                    if frame is None or len(frame) == 0:
                        self._set_level(0.0)
                        continue
                    try:
                        arr = np.asarray(frame, dtype=np.float32)
                        mono = arr.mean(axis=1, dtype=np.float32) if arr.ndim > 1 else arr
                        if len(mono) == 0:
                            self._set_level(0.0)
                            continue
                        rms = float(np.sqrt(np.dot(mono, mono) / len(mono)))
                        self._set_level(SystemAudioLoop._rms_to_level(rms))
                    except Exception:
                        self._set_level(0.0)
