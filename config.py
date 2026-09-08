"""Kullanıcı ayarları. Dosya APPDATA / ~/.config altında; git'e düşmez.

Öncelik: CLI argümanı > GEMINI_API_KEY > kayıtlı dosya.
VOICE_TRANSLATE_CONFIG ile yol override edilir (test).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "voice_translate"


@dataclass
class Settings:
    api_key: str = ""


def config_dir() -> Path:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    override = os.environ.get("VOICE_TRANSLATE_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.json"


def _read_raw() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_raw(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path


def load() -> Settings:
    raw = _read_raw()
    return Settings(api_key=str(raw.get("api_key") or ""))


def save(settings: Settings) -> Path:
    raw = _read_raw()
    raw["api_key"] = settings.api_key
    return _write_raw(raw)


def save_api_key(key: str) -> Path:
    settings = load()
    settings.api_key = key.strip()
    return save(settings)


def load_dotenv() -> None:
    try:
        from dotenv import load_dotenv as _load

        _load()
    except ImportError:
        pass


def resolve_api_key(explicit: str | None = None) -> str:
    if explicit is not None and explicit.strip():
        return explicit.strip()
    load_dotenv()
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    return load().api_key.strip()
