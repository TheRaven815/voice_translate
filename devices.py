"""Ses aygıtı seçimi (soundcard)."""

from __future__ import annotations

import soundcard as sc


NONE_OUTPUT = "Hiçbiri"


def list_devices() -> None:
    print("Hoparlörler:")
    def_sp = sc.default_speaker()
    for s in sc.all_speakers():
        default = " (varsayılan)" if def_sp is not None and s == def_sp else ""
        print(f"  - {s.name}{default}")
    mics = sc.all_microphones(include_loopback=True)
    print("Loopback (sistem sesi) kaynakları:")
    for m in mics:
        if m.isloopback:
            print(f"  - {m.name}")
    print("Mikrofonlar:")
    for m in mics:
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
    if default_sp is not None:
        for m in loops:
            if default_sp.name in m.name or m.name in default_sp.name:
                return m
    return loops[0]


def device_key(dev) -> tuple:
    """Aygıt kimliği: hot-swap karşılaştırmalarında yeniden taramada bile stabil."""
    if dev is None:
        return (None, None, None)
    return (
        getattr(dev, "id", None),
        getattr(dev, "name", None),
        bool(getattr(dev, "isloopback", False)),
    )


def display_input_label(dev) -> str:
    """GUI listesindeki görünen ad: '[Sistem] X' ya da '[Mikrofon] X'."""
    prefix = "[Sistem] " if getattr(dev, "isloopback", False) else "[Mikrofon] "
    return prefix + str(getattr(dev, "name", "?"))


def find_input_by_label(devices, label: str | None):
    """Görünen ada göre giriş aygıtını bulur (önekli ya da çıplak ad)."""
    if not label or not devices:
        return None
    text = str(label).strip()
    for dev in devices:
        if text == display_input_label(dev) or text == str(getattr(dev, "name", "")):
            return dev
    # Önek değişmiş olabilir; ada göre gevşek eşleşme.
    bare = text
    for prefix in ("[Sistem] ", "[Mikrofon] "):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    for dev in devices:
        if str(getattr(dev, "name", "")) == bare:
            return dev
    return None


def find_output_by_label(devices, label: str | None):
    """Görünen ada göre çıkış aygıtını bulur (NONE_OUTPUT -> None)."""
    if not label or label == NONE_OUTPUT:
        return None
    text = str(label).strip()
    for dev in (devices or []):
        if str(getattr(dev, "name", "")) == text:
            return dev
    return None


def all_inputs():
    return list(sc.all_microphones(include_loopback=True))


def all_outputs():
    return list(sc.all_speakers())


def default_speaker():
    return sc.default_speaker()

def pick_speaker(device_substr: str | None = None):
    speakers = list(sc.all_speakers())
    if not speakers:
        return None
    if device_substr:
        for s in speakers:
            if device_substr.lower() in s.name.lower():
                return s
        raise RuntimeError(f"'{device_substr}' ile eşleşen hoparlör yok.")
    return default_speaker()


def default_microphone():
    return sc.default_microphone()
