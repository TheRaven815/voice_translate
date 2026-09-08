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
    "Çince": "zh",
    "Korece": "ko",
}


def source_code(name: str) -> str | None:
    if name == AUTO_SRC:
        return None
    return LANGS[name]


def source_names() -> list[str]:
    return [AUTO_SRC, *LANGS]
