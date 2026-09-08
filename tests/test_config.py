"""Ayar dosyası: anahtar kaydı ve çözüm sırası."""

import json

from voice_translate import config


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_save_load_roundtrip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.save_api_key("  sk-live-1  ")
    assert config.load().api_key == "sk-live-1"
    assert config.resolve_api_key() == "sk-live-1"


def test_empty_save_clears_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.save_api_key("sk-live-1")
    config.save_api_key("  ")
    assert config.resolve_api_key() == ""


def test_resolve_prefers_cli_then_env_then_file(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.save_api_key("from-file")
    assert config.resolve_api_key() == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert config.resolve_api_key() == "from-env"
    assert config.resolve_api_key("from-cli") == "from-cli"


def test_corrupt_file_is_empty_settings(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert config.load().api_key == ""
    assert config.resolve_api_key() == ""


def test_save_preserves_unknown_fields(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"api_key": "old", "theme": "dark"}), encoding="utf-8")
    config.save_api_key("new")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["api_key"] == "new"
    assert data["theme"] == "dark"
