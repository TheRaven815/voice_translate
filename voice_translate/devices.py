"""Ses aygıtı seçimi (soundcard)."""

from __future__ import annotations

import soundcard as sc


def list_devices() -> None:
    print("Hoparlörler:")
    for s in sc.all_speakers():
        default = " (varsayılan)" if s == sc.default_speaker() else ""
        print(f"  - {s.name}{default}")
    print("Loopback (sistem sesi) kaynakları:")
    for m in sc.all_microphones(include_loopback=True):
        if m.isloopback:
            print(f"  - {m.name}")
    print("Mikrofonlar:")
    for m in sc.all_microphones(include_loopback=True):
        if not m.isloopback:
            print(f"  - {m.name}")


def pick_loopback(device_substr: str | None):
    loops = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not loops:
        raise RuntimeError("Loopback cihaz bulunamadı.")
    if device_substr:
        for m in loops:
            if device_substr.lower() in m.name.lower():
                return m
        raise RuntimeError(f"'{device_substr}' ile eşleşen loopback cihaz yok.")
    default_sp = sc.default_speaker()
    for m in loops:
        if default_sp.name in m.name or m.name in default_sp.name:
            return m
    return loops[0]


def all_inputs():
    return list(sc.all_microphones(include_loopback=True))


def all_outputs():
    return list(sc.all_speakers())


def default_speaker():
    return sc.default_speaker()


def default_microphone():
    return sc.default_microphone()
