"""Kullanıcı ayarları. Dosya APPDATA / ~/.config altında; git'e düşmez.

Öncelik: CLI argümanı > GEMINI_API_KEY > kayıtlı dosya.
VOICE_TRANSLATE_CONFIG ile yol override edilir (test).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Ahenk"
LEGACY_APP_NAME = "voice_translate"

# Basitce acikta okunmayi onlemek icin gomulu anahtar
_SECRET_KEY = b"Ahenk_Gemini_Secret_Key_v1"


def _encrypt_key(plain: str) -> str:
    if not plain:
        return ""
    data = plain.encode("utf-8")
    xor_bytes = bytes(b ^ _SECRET_KEY[i % len(_SECRET_KEY)] for i, b in enumerate(data))
    return base64.b64encode(xor_bytes).decode("ascii")


def _decrypt_key(cipher: str) -> str:
    if not cipher:
        return ""
    if cipher.startswith("AIza"):
        return cipher
    try:
        data = base64.b64decode(cipher.encode("ascii"), validate=True)
        return bytes(b ^ _SECRET_KEY[i % len(_SECRET_KEY)] for i, b in enumerate(data)).decode("utf-8")
    except Exception:
        return cipher


@dataclass
class Settings:
    api_key: str = ""
    input_device: str = ""
    output_device: str = ""
    src_lang: str = ""
    dst_lang: str = ""

def config_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif os.environ.get("XDG_CONFIG_HOME"):
        root = Path(os.environ["XDG_CONFIG_HOME"])
    else:
        root = Path.home() / ".config"
    return root / APP_NAME


def config_path() -> Path:
    override = os.environ.get("AHENK_CONFIG") or os.environ.get("VOICE_TRANSLATE_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.json"


def _read_raw() -> dict:
    path = config_path()
    if not path.is_file():
        legacy = path.parent.parent / LEGACY_APP_NAME / path.name
        if legacy.is_file():
            path = legacy
        else:
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
    raw_key = str(raw.get("api_key") or "")
    return Settings(
        api_key=_decrypt_key(raw_key),
        input_device=str(raw.get("input_device") or ""),
        output_device=str(raw.get("output_device") or ""),
        src_lang=str(raw.get("src_lang") or ""),
        dst_lang=str(raw.get("dst_lang") or ""),
    )


def save(settings: Settings) -> Path:
    raw = _read_raw()
    raw["api_key"] = _encrypt_key(settings.api_key)
    raw["input_device"] = settings.input_device
    raw["output_device"] = settings.output_device
    raw["src_lang"] = settings.src_lang
    raw["dst_lang"] = settings.dst_lang
    return _write_raw(raw)

def save_api_key(key: str) -> Path:
    settings = load()
    settings.api_key = key.strip()
    return save(settings)


def save_preferences(
    *,
    input_device: str | None = None,
    output_device: str | None = None,
    src_lang: str | None = None,
    dst_lang: str | None = None,
) -> Path:
    settings = load()
    if input_device is not None:
        settings.input_device = input_device
    if output_device is not None:
        settings.output_device = output_device
    if src_lang is not None:
        settings.src_lang = src_lang
    if dst_lang is not None:
        settings.dst_lang = dst_lang
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
