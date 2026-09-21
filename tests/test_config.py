"""Ayar dosyası: anahtar kaydı ve çözüm sırası."""

import json

import config


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("AHENK_CONFIG", str(tmp_path / "config.json"))
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
        input_application=r"C:\Program Files\Browser\browser.exe",
        output_device="Speaker 1",
        src_lang="en",
        dst_lang="tr",
        window_geom="900x500+100+100",
        overlay_geom="500x50+200+200",
        mute_shortcut="Ctrl+Alt+M",
        start_stop_shortcut="F9",
    )
    loaded = config.load()
    assert loaded.input_device == "Mic 1"
    assert loaded.input_application == r"C:\Program Files\Browser\browser.exe"
    assert loaded.output_device == "Speaker 1"
    assert loaded.src_lang == "en"
    assert loaded.dst_lang == "tr"
    assert loaded.window_geom == "900x500+100+100"
    assert loaded.overlay_geom == "500x50+200+200"
    assert loaded.mute_shortcut == "Ctrl+Alt+M"
    assert loaded.start_stop_shortcut == "F9"

def test_dpapi_failure_raises_oserror_and_does_not_save_plaintext(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config.os, "name", "nt")

    def failing_dpapi_protect(_data):
        raise RuntimeError("Simulated DPAPI failure")

    monkeypatch.setattr(config, "_dpapi_protect", failing_dpapi_protect, raising=False)

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"api_key": "safe_existing"}), encoding="utf-8")

    import pytest
    with pytest.raises(OSError, match="DPAPI"):
        config.save_api_key("AIzaSyDangerousPlainKey")

    # File content must still be safe_existing, not overwritten with plaintext key
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["api_key"] == "safe_existing"
    assert "AIzaSyDangerousPlainKey" not in cfg_file.read_text(encoding="utf-8")

def test_h15_malformed_config_values_fall_back_safely(tmp_path, monkeypatch):
    """H15: JSON geçerli ama alan değerleri bozukken ValueError atmamalı, varsayılanlara düşmeli."""
    _isolate(tmp_path, monkeypatch)
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({
            "overlay_font_size": "bad_font_size",
            "overlay_alpha": "not_a_float",
            "theme": "unsupported_neon_theme",
            "ui_lang": "invalid_lang",
            "always_on_top": "not_a_bool",
        }),
        encoding="utf-8",
    )
    loaded = config.load()
    assert loaded.overlay_font_size == 13
    assert loaded.overlay_alpha == 0.92
    assert loaded.theme == "dark"
    assert loaded.ui_lang == "tr"
    assert loaded.always_on_top is False


def test_h16_corrupt_config_is_backed_up_and_salvages_keys(tmp_path, monkeypatch):
    """H16: Bozuk config dosyası save_preferences sırasında yok edilmemeli, yedeklenmeli ve kurtarılmalı."""
    _isolate(tmp_path, monkeypatch)
    cfg_file = tmp_path / "config.json"
    # api_key içeren ancak sonradan sözdizimi bozulan bir dosya
    cfg_file.write_text('{\n  "api_key": "safe_encrypted_key",\n  "broken_syntax": [,\n', encoding="utf-8")

    # save_preferences çağrıldığında
    config.save_preferences(theme="light")

    # 1. Orijinal bozuk dosya .bak olarak korunmuş olmalı
    bak_file = tmp_path / "config.json.bak"
    assert bak_file.is_file()
    assert "broken_syntax" in bak_file.read_text(encoding="utf-8")

    # 2. Kurtarılabilen api_key yeni dosyada korunmuş olmalı (kaybolmamalı)
    new_data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert new_data.get("api_key") == "safe_encrypted_key"
    assert new_data.get("theme") == "light"

def test_g02_ahenk_config_priority_and_isolation(tmp_path, monkeypatch):
    """G02: AHENK_CONFIG ortam değişkeni varsa VOICE_TRANSLATE_CONFIG yerine öncelikli olmalı ve izole edilmeli."""
    ahenk_cfg = tmp_path / "ahenk_custom.json"
    vt_cfg = tmp_path / "vt_custom.json"
    monkeypatch.setenv("AHENK_CONFIG", str(ahenk_cfg))
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(vt_cfg))

    assert config.config_path() == ahenk_cfg

    # AHENK_CONFIG kaldırıldığında VOICE_TRANSLATE_CONFIG'e düşmeli
    monkeypatch.delenv("AHENK_CONFIG", raising=False)
    assert config.config_path() == vt_cfg
