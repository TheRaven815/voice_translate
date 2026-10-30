"""UI dil adları → BCP-47 kodları. Yeni dil buraya eklenir.

Kaynakta AUTO_SRC: language_codes boş bırakılır, model dili algılar.
"""

AUTO_SRC = "Otomatik"

LANGS = {
    "İngilizce": "en",
    "Türkçe": "tr",
    "Almanca": "de",
    "Fransızca": "fr",
    "İspanyolca": "es",
    "İtalyanca": "it",
    "Portekizce": "pt",
    "Rusça": "ru",
    "Arapça": "ar",
    "Felemenkçe": "nl",
    "Japonca": "ja",
    "Çince (Basitleştirilmiş)": "zh-CN",
    "Çince (Geleneksel)": "zh-TW",
    "Korece": "ko",
    "Hintçe": "hi",
    "Lehçe": "pl",
    "Ukraynaca": "uk",
    "Endonezce": "id",
    "Vietnamca": "vi",
    "İsveççe": "sv",
}

RTL_CODES = {"ar", "fa", "he", "ur"}


def is_rtl(code_or_name: str | None) -> bool:
    if not code_or_name:
        return False
    code = LANGS.get(code_or_name, code_or_name).lower()
    return any(code == rtl or code.startswith(f"{rtl}-") for rtl in RTL_CODES)

def source_code(name: str | None) -> str | None:
    if not name or name in (AUTO_SRC, "auto", ""):
        return None
    return LANGS.get(name, name)


def dest_code(name: str | None, default: str = "tr") -> str:
    if not name:
        return default
    return LANGS.get(name, name)


def source_names() -> list[str]:
    return [AUTO_SRC, *LANGS]

CODE_TO_NAME = {v: k for k, v in LANGS.items()}
CODE_TO_NAME["zh"] = "Çince (Basitleştirilmiş)"
CODE_TO_NAME["zh-cn"] = "Çince (Basitleştirilmiş)"
CODE_TO_NAME["zh-tw"] = "Çince (Geleneksel)"

# Arayüz diline göre görünen adlar. Kanonik anahtarlar (LANGS) Türkçe kalır.
_EN_NAMES = {
    AUTO_SRC: "Automatic",
    "Türkçe": "Turkish",
    "İngilizce": "English",
    "Almanca": "German",
    "Fransızca": "French",
    "İspanyolca": "Spanish",
    "İtalyanca": "Italian",
    "Portekizce": "Portuguese",
    "Rusça": "Russian",
    "Arapça": "Arabic",
    "Felemenkçe": "Dutch",
    "Japonca": "Japanese",
    "Çince (Basitleştirilmiş)": "Chinese (Simplified)",
    "Çince (Geleneksel)": "Chinese (Traditional)",
    "Korece": "Korean",
    "Hintçe": "Hindi",
    "Lehçe": "Polish",
    "Ukraynaca": "Ukrainian",
    "Endonezce": "Indonesian",
    "Vietnamca": "Vietnamese",
    "İsveççe": "Swedish",
}
_EN_TO_CANONICAL = {english: canonical for canonical, english in _EN_NAMES.items()}


def canonical_name(name: str | None) -> str | None:
    """Görünen (TR/EN) dil adını kanonik Türkçe ada çevirir."""
    if not name:
        return name
    if name in _EN_NAMES:
        return name
    return _EN_TO_CANONICAL.get(name, name)


def display_name(name: str | None) -> str | None:
    """Kanonik dil adını geçerli arayüz dilinde gösterir."""
    if not name:
        return name
    canonical = canonical_name(name)
    from i18n import get_ui_lang

    if get_ui_lang() == "en":
        return _EN_NAMES.get(canonical, canonical)
    return canonical


def display_source_names() -> list[str]:
    return [display_name(name) for name in source_names()]


def display_language_names() -> list[str]:
    return [display_name(name) for name in LANGS]

def lang_code_to_name(code: str, default: str = "Türkçe") -> str:
    if not code:
        return default
    if code in LANGS:
        return code
    if code == "Çince":
        return "Çince (Basitleştirilmiş)"
    return CODE_TO_NAME.get(code.lower(), default)

def src_code_to_name(code: str, default: str = AUTO_SRC) -> str:
    if not code or code.lower() in ("auto", "none"):
        return AUTO_SRC
    if code == AUTO_SRC or code in LANGS:
        return code
    if code == "Çince":
        return "Çince (Basitleştirilmiş)"
    return CODE_TO_NAME.get(code.lower(), default)
