"""Ahenk arayüz dili yerelleştirme (i18n)."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "tr": {
        "app_title": "Ahenk",
        "device": "Aygıt",
        "input": "Giriş",
        "output": "Çıkış",
        "language": "Dil",
        "api_key": "API anahtarı",
        "save": "Kaydet",
        "test": "Test",
        "start": "Başlat",
        "stop": "Durdur",
        "ready": "Hazır",
        "running": "Çalışıyor",
        "connecting": "Bağlanıyor",
        "stopped": "Durdu",
        "stopping": "Durduruluyor",
        "heard": "Duyulan",
        "trans": "Çeviri",
        "clear": "Temizle",
        "copy": "Kopyala",
        "export": "Dışa Aktar",
        "subtitle": "Altyazı",
        "about": "Hakkında",
        "settings": "Ayarlar",
        "theme": "Tema",
        "pin": "Sabitle",
        "swap": "Dilleri değiştir",
        "show_key": "Anahtarı göster",
        "hide_key": "Anahtarı gizle",
        "refresh": "Yenile",
        "restarting": "Yeniden başlatılıyor",
        "error": "Hata",
        "copied": "Metin panoya kopyalandı.",
        "exported": "Transkript dışa aktarıldı:",
        "none_output": "Hiçbiri (yalnızca metin)",
    },
    "en": {
        "app_title": "Ahenk",
        "device": "Device",
        "input": "Input",
        "output": "Output",
        "language": "Language",
        "api_key": "API Key",
        "save": "Save",
        "test": "Test",
        "start": "Start",
        "stop": "Stop",
        "ready": "Ready",
        "running": "Running",
        "connecting": "Connecting",
        "stopped": "Stopped",
        "stopping": "Stopping",
        "heard": "Heard",
        "trans": "Translation",
        "clear": "Clear",
        "copy": "Copy",
        "export": "Export",
        "subtitle": "Subtitle",
        "about": "About",
        "settings": "Settings",
        "theme": "Theme",
        "pin": "Pin",
        "swap": "Swap languages",
        "show_key": "Show key",
        "hide_key": "Hide key",
        "refresh": "Refresh",
        "restarting": "Restarting",
        "error": "Error",
        "copied": "Text copied to clipboard.",
        "exported": "Transcript exported to:",
        "none_output": "None (text-only)",
    },
}
_current_lang = "tr"


def set_ui_lang(lang: str) -> None:
    global _current_lang
    if lang in STRINGS:
        _current_lang = lang


def get_ui_lang() -> str:
    return _current_lang


def t(key: str, default: str | None = None) -> str:
    return STRINGS.get(_current_lang, {}).get(key) or STRINGS["tr"].get(key) or default or key
