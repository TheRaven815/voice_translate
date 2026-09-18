"""Global pytest fixtures for test isolation."""

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """G02: Tüm testlerde gerçek kullanıcı config ve API anahtarı ortamını izole et."""
    sandbox_config = tmp_path / "sandbox_config.json"
    monkeypatch.setenv("AHENK_CONFIG", str(sandbox_config))
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(sandbox_config))
