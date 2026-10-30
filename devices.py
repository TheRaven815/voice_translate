"""Ses aygıtı seçimi (soundcard)."""

from __future__ import annotations

import soundcard as sc


NONE_OUTPUT = "Hiçbiri"


def none_output_label() -> str:
    """Çıkış listesinde gösterilen yerelleştirilmiş “Hiçbiri” etiketi."""
    from i18n import t

    return t("none_output_short", NONE_OUTPUT)


def none_output_labels() -> set[str]:
    from i18n import STRINGS

    labels = {NONE_OUTPUT}
    for strings in STRINGS.values():
        value = strings.get("none_output_short")
        if value:
            labels.add(value)
    return labels


def is_none_output(label: str | None) -> bool:
    return not label or label in none_output_labels()


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


def _all_label_values(key: str, default: str) -> set[str]:
    """Bir etiketin tüm dillerdeki değerleri (eski kayıtları eşlemek için)."""
    from i18n import STRINGS

    values = {default}
    for strings in STRINGS.values():
        value = strings.get(key)
        if value:
            values.add(value)
    return values


def application_input_prefix() -> str:
    from i18n import t

    return t("label_application", "[Uygulama]")


def is_application_input_label(label: str | None) -> bool:
    text = str(label or "")
    return any(
        text.startswith(prefix + " ")
        for prefix in _all_label_values("label_application", "[Uygulama]")
    )


def display_input_label(dev) -> str:
    """GUI giriş etiketi; uygulamalar sistem sesinden ayrı gösterilir."""
    from i18n import t

    if getattr(dev, "is_application", False):
        return application_input_prefix() + " " + str(dev.name)
    key = "label_system" if getattr(dev, "isloopback", False) else "label_microphone"
    return t(key) + " " + str(getattr(dev, "name", "?"))


def _strip_input_prefix(text: str) -> str:
    for prefixes in (
        _all_label_values("label_application", "[Uygulama]"),
        _all_label_values("label_system", "[Sistem]"),
        _all_label_values("label_microphone", "[Mikrofon]"),
    ):
        for prefix in prefixes:
            if text.startswith(prefix + " "):
                return text[len(prefix) + 1:]
    return text


def find_input_by_label(devices, label: str | None):
    """Görünen ada göre giriş aygıtını bulur (önekli ya da çıplak ad)."""
    if not label or not devices:
        return None
    text = str(label).strip()
    bare = _strip_input_prefix(text)
    application_prefixes = _all_label_values("label_application", "[Uygulama]")
    if any(text.startswith(prefix + " ") for prefix in application_prefixes):
        return next((dev for dev in devices if getattr(dev, "is_application", False)
                     and str(getattr(dev, "name", "")) == bare), None)
    for dev in devices:
        if text == display_input_label(dev) or text == str(getattr(dev, "name", "")):
            return dev
    for dev in devices:
        if str(getattr(dev, "name", "")) == bare:
            return dev
    return None


def find_output_by_label(devices, label: str | None):
    """Görünen ada göre çıkış aygıtını bulur (NONE_OUTPUT -> None)."""
    if is_none_output(label):
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
