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

# Windows harici ortamlarda geriye dönük uyumluluk için gömülü anahtar
_SECRET_KEY = b"Ahenk_Gemini_Secret_Key_v1"
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _CryptProtectData = ctypes.windll.crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    _CryptUnprotectData.restype = wintypes.BOOL

    def _dpapi_protect(data: bytes) -> bytes:
        in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if not _CryptProtectData(ctypes.byref(in_blob), "AhenkKey", None, None, None, 0, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _dpapi_unprotect(cipher: bytes) -> bytes:
        in_blob = _DATA_BLOB(len(cipher), ctypes.cast(ctypes.create_string_buffer(cipher), ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        if not _CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _encrypt_key(plain: str) -> str:
    if not plain:
        return ""
    if os.name == "nt":
        try:
            enc = _dpapi_protect(plain.encode("utf-8"))
            return "dpapi:" + base64.b64encode(enc).decode("ascii")
        except Exception as exc:
            raise OSError(f"DPAPI anahtar şifreleme başarısız: {exc}") from exc
    # Windows harici ise düz metin (0600 izni ile)
    return plain

def _decrypt_key(stored: str) -> str:
    if not stored:
        return ""
    if stored.startswith("dpapi:") and os.name == "nt":
        try:
            raw = base64.b64decode(stored[6:].encode("ascii"), validate=True)
            return _dpapi_unprotect(raw).decode("utf-8")
        except Exception:
            return ""
    if stored.startswith("AIza"):
        return stored
    # Eski XOR sifreli kayitlar icin geriye donuk cozumleme
    try:
        data = base64.b64decode(stored.encode("ascii"), validate=True)
        return bytes(b ^ _SECRET_KEY[i % len(_SECRET_KEY)] for i, b in enumerate(data)).decode("utf-8")
    except Exception:
        return stored

@dataclass
class Settings:
    api_key: str = ""
    input_device: str = ""
    input_application: str = ""
    output_device: str = ""
    src_lang: str = ""
    dst_lang: str = ""
    theme: str = "dark"
    window_geom: str = ""
    overlay_geom: str = ""
    always_on_top: bool = False
    overlay_font_size: int = 13
    overlay_alpha: float = 0.92
    overlay_click_through: bool = False
    ui_lang: str = "tr"
    save_history: bool = True
    mute_shortcut: str = "Ctrl+Shift+M"
    start_stop_shortcut: str = "Ctrl+Shift+Space"

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
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # Eski dosyayı yeni Ahenk konumuna otomatik taşı
                    try:
                        _write_raw(data)
                    except OSError:
                        pass
                    return data
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass

    bak = path.with_suffix(".json.bak")
    try:
        if not bak.exists():
            bak.write_bytes(path.read_bytes())
    except OSError:
        pass

    recovered: dict = {}
    try:
        import re
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        m_key = re.search(r'"api_key"\s*:\s*"([^"]+)"', raw_text)
        if m_key:
            recovered["api_key"] = m_key.group(1)
        for fld in ("theme", "src_lang", "dst_lang", "input_device", "input_application", "output_device", "window_geom", "overlay_geom", "ui_lang"):
            m = re.search(rf'"{fld}"\s*:\s*"([^"]+)"', raw_text)
            if m:
                recovered[fld] = m.group(1)
    except Exception:
        pass
    return recovered

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


def _safe_int(val, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    try:
        res = int(val)
        if min_val is not None and res < min_val:
            return default
        if max_val is not None and res > max_val:
            return default
        return res
    except (ValueError, TypeError):
        return default


def _safe_float(val, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    try:
        res = float(val)
        if min_val is not None and res < min_val:
            return default
        if max_val is not None and res > max_val:
            return default
        return res
    except (ValueError, TypeError):
        return default


def load() -> Settings:
    raw = _read_raw()
    raw_key = str(raw.get("api_key") or "")
    theme = str(raw.get("theme") or "dark").lower().strip()
    if theme not in ("dark", "light"):
        theme = "dark"
    ui_lang = str(raw.get("ui_lang") or "tr").lower().strip()
    if ui_lang not in ("tr", "en"):
        ui_lang = "tr"
    always_on_top = bool(raw.get("always_on_top")) if isinstance(raw.get("always_on_top"), (bool, int)) else False
    overlay_click_through = bool(raw.get("overlay_click_through")) if isinstance(raw.get("overlay_click_through"), (bool, int)) else False
    overlay_font_size = _safe_int(raw.get("overlay_font_size"), default=13, min_val=8, max_val=72)
    overlay_alpha = _safe_float(raw.get("overlay_alpha"), default=0.92, min_val=0.1, max_val=1.0)

    return Settings(
        api_key=_decrypt_key(raw_key),
        input_device=str(raw.get("input_device") or ""),
        input_application=str(raw.get("input_application") or ""),
        output_device=str(raw.get("output_device") or ""),
        src_lang=str(raw.get("src_lang") or ""),
        dst_lang=str(raw.get("dst_lang") or ""),
        theme=theme,
        window_geom=str(raw.get("window_geom") or ""),
        overlay_geom=str(raw.get("overlay_geom") or ""),
        always_on_top=always_on_top,
        overlay_font_size=overlay_font_size,
        overlay_alpha=overlay_alpha,
        overlay_click_through=overlay_click_through,
        ui_lang=ui_lang,
        save_history=bool(raw.get("save_history", True)),
        mute_shortcut=str(raw.get("mute_shortcut") or "Ctrl+Shift+M"),
        start_stop_shortcut=str(raw.get("start_stop_shortcut") or "Ctrl+Shift+Space"),
    )
def save(settings: Settings) -> Path:
    raw = _read_raw()
    raw["api_key"] = _encrypt_key(settings.api_key)
    raw["input_device"] = settings.input_device
    raw["input_application"] = settings.input_application
    raw["output_device"] = settings.output_device
    raw["src_lang"] = settings.src_lang
    raw["dst_lang"] = settings.dst_lang
    raw["theme"] = settings.theme
    raw["window_geom"] = settings.window_geom
    raw["overlay_geom"] = settings.overlay_geom
    raw["always_on_top"] = settings.always_on_top
    raw["overlay_font_size"] = settings.overlay_font_size
    raw["overlay_alpha"] = settings.overlay_alpha
    raw["overlay_click_through"] = settings.overlay_click_through
    raw["ui_lang"] = settings.ui_lang
    raw["save_history"] = settings.save_history
    raw["mute_shortcut"] = settings.mute_shortcut
    raw["start_stop_shortcut"] = settings.start_stop_shortcut
    return _write_raw(raw)

def save_api_key(key: str) -> Path:
    raw = _read_raw()
    raw["api_key"] = _encrypt_key(key.strip())
    return _write_raw(raw)


def save_preferences(
    *,
    input_device: str | None = None,
    input_application: str | None = None,
    output_device: str | None = None,
    src_lang: str | None = None,
    dst_lang: str | None = None,
    theme: str | None = None,
    window_geom: str | None = None,
    overlay_geom: str | None = None,
    always_on_top: bool | None = None,
    overlay_font_size: int | None = None,
    overlay_alpha: float | None = None,
    overlay_click_through: bool | None = None,
    ui_lang: str | None = None,
    save_history: bool | None = None,
    mute_shortcut: str | None = None,
    start_stop_shortcut: str | None = None,
) -> Path:
    raw = _read_raw()
    if input_device is not None:
        raw["input_device"] = input_device
    if input_application is not None:
        raw["input_application"] = input_application
    if output_device is not None:
        raw["output_device"] = output_device
    if src_lang is not None:
        raw["src_lang"] = src_lang
    if dst_lang is not None:
        raw["dst_lang"] = dst_lang
    if theme is not None:
        raw["theme"] = theme
    if window_geom is not None:
        raw["window_geom"] = window_geom
    if overlay_geom is not None:
        raw["overlay_geom"] = overlay_geom
    if always_on_top is not None:
        raw["always_on_top"] = always_on_top
    if overlay_font_size is not None:
        raw["overlay_font_size"] = overlay_font_size
    if overlay_alpha is not None:
        raw["overlay_alpha"] = overlay_alpha
    if overlay_click_through is not None:
        raw["overlay_click_through"] = overlay_click_through
    if ui_lang is not None:
        raw["ui_lang"] = ui_lang
    if save_history is not None:
        raw["save_history"] = save_history
    if mute_shortcut is not None:
        raw["mute_shortcut"] = mute_shortcut
    if start_stop_shortcut is not None:
        raw["start_stop_shortcut"] = start_stop_shortcut
    return _write_raw(raw)


def load_dotenv() -> None:
    try:
        import sys
        from dotenv import load_dotenv as _load

        _load()
        if getattr(sys, "frozen", False):
            exe_env = Path(sys.executable).resolve().parent / ".env"
            if exe_env.is_file():
                _load(exe_env)
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
