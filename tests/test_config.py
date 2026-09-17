"""Ayar dosyası: anahtar kaydı ve çözüm sırası."""

import json

import config


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
    assert data["api_key"] != "new"  # sifreli saklanmali
    assert config.load().api_key == "new"
    assert data["theme"] == "dark"


def test_api_key_encrypted_on_disk(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    plain = "AIzaSyTestSecret123"
    config.save_api_key(plain)
    path = tmp_path / "config.json"
    raw_content = path.read_text(encoding="utf-8")
    assert plain not in raw_content
    assert config.load().api_key == plain
    assert config.resolve_api_key() == plain


def test_legacy_unencrypted_key_load(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"api_key": "AIzaSyLegacyKey"}), encoding="utf-8")
    assert config.load().api_key == "AIzaSyLegacyKey"


def test_legacy_xor_key_load(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    import base64
    plain = "AIzaSyLegacySecretKey"
    data = plain.encode("utf-8")
    sec = config._SECRET_KEY
    xor_b64 = base64.b64encode(bytes(b ^ sec[i % len(sec)] for i, b in enumerate(data))).decode("ascii")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"api_key": xor_b64}), encoding="utf-8")
    assert config.load().api_key == plain

def test_save_preferences(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    config.save_preferences(
        input_device="Mic 1",
        output_device="Speaker 1",
        src_lang="en",
        dst_lang="tr",
        window_geom="900x500+100+100",
        overlay_geom="500x50+200+200",
    )
    loaded = config.load()
    assert loaded.input_device == "Mic 1"
    assert loaded.output_device == "Speaker 1"
    assert loaded.src_lang == "en"
    assert loaded.dst_lang == "tr"
    assert loaded.window_geom == "900x500+100+100"
    assert loaded.overlay_geom == "500x50+200+200"
