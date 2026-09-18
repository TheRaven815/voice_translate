"""logger.py ve i18n.py birim testleri."""

from __future__ import annotations

from i18n import get_ui_lang, set_ui_lang, t
from logger import append_history, clear_history, get_logger, load_recent_history, log_exception, setup_logging


def test_i18n_translation_and_language_switch():
    set_ui_lang("tr")
    assert get_ui_lang() == "tr"
    assert t("start") == "Başlat"
    assert t("stop") == "Durdur"

    set_ui_lang("en")
    assert get_ui_lang() == "en"
    assert t("start") == "Start"
    assert t("stop") == "Stop"

    # Fallback to key if unknown
    assert t("unknown_key_xyz") == "unknown_key_xyz"
    set_ui_lang("tr")


def test_logger_and_history_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("logger.config_dir", lambda: tmp_path)
    logger = setup_logging(force=True)
    assert logger is not None
    assert get_logger() is logger

    # Log an exception
    try:
        raise ValueError("test error")
    except ValueError as e:
        log_exception(e, "context_test")

    log_file = tmp_path / "logs" / "ahenk.log"
    assert log_file.is_file()
    assert "test error" in log_file.read_text(encoding="utf-8")

    # Append history
    append_history("Hello world", "Merhaba dünya", src="en", dst="tr")
    hist = load_recent_history()
    assert len(hist) == 1
    assert hist[0]["heard"] == "Hello world"
    assert hist[0]["trans"] == "Merhaba dünya"

    # G01: Konuşma geçmişi temizleme ve döndürme
    assert clear_history() is True
    assert load_recent_history() == []

    # 60 kayıt ekleyip son 10 kaydı isteme (limit kontrolü)
    for i in range(60):
        append_history(f"H_{i}", f"T_{i}")
    recent = load_recent_history(limit=10)
    assert len(recent) == 10
    assert recent[-1]["heard"] == "H_59"
    assert recent[0]["heard"] == "H_50"

    clear_history()
    assert load_recent_history() == []
