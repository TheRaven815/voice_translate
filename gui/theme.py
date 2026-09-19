"""Arayüz paleti. Yeni ekranlar C ve font ölçeğini kullanır."""

from __future__ import annotations

import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path


def _root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


_ASSETS = _root() / "assets"
ICON_ICO = _ASSETS / "ahenk.ico"
ICON_PNG = _ASSETS / "ahenk.png"
APP_ID = "eneseliagir.ahenk"


DARK = {
    "bg": "#111113",
    "rail": "#151517",
    "panel": "#1a1a1d",
    "text": "#ececec",
    "muted": "#9a9aa0",
    "dim": "#63636a",
    "line": "#2a2a2e",
    "hover": "#232327",
    "fill": "#ededed",
    "fill_fg": "#131315",
    "fill_hover": "#ffffff",
    "live": "#6fbf73",
    "warn": "#d0a94f",
    "err": "#d47b7b",
    "select": "#2e2e33",
    "overlay_bg": "#0d0d0f",
    "disabled_bg": "#1c1c1f",
    "accent": "#d4a94e",
}

LIGHT = {
    "bg": "#f6f6f4",
    "rail": "#eeeeeb",
    "panel": "#ffffff",
    "text": "#1b1d20",
    "muted": "#41474e",
    "dim": "#616b76",
    "line": "#d8dce1",
    "hover": "#e4e7ea",
    "fill": "#22262b",
    "fill_fg": "#ffffff",
    "fill_hover": "#363c43",
    "live": "#22753c",
    "warn": "#9a6700",
    "err": "#cf222e",
    "select": "#d9dee4",
    "overlay_bg": "#ffffff",
    "disabled_bg": "#e9ecef",
    "accent": "#8a6414",
}


class C:
    current = "dark"
    bg = DARK["bg"]
    rail = DARK["rail"]
    panel = DARK["panel"]
    text = DARK["text"]
    muted = DARK["muted"]
    dim = DARK["dim"]
    line = DARK["line"]
    hover = DARK["hover"]
    fill = DARK["fill"]
    fill_fg = DARK["fill_fg"]
    fill_hover = DARK["fill_hover"]
    live = DARK["live"]
    warn = DARK["warn"]
    err = DARK["err"]
    select = DARK["select"]
    overlay_bg = DARK["overlay_bg"]
    disabled_bg = DARK["disabled_bg"]
    accent = DARK["accent"]

    @classmethod
    def apply_theme(cls, name: str = "dark"):
        theme_name = "light" if name == "light" else "dark"
        cls.current = theme_name
        palette = LIGHT if theme_name == "light" else DARK
        for k, v in palette.items():
            setattr(cls, k, v)


def dark_titlebar(win: tk.Tk, dark: bool = True) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            hwnd = win.winfo_id()
        val = ctypes.c_int(1 if dark else 0)
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        for attr in (20, 19):
            dwm(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


_app_id_prepared = False

def prepare_app_id() -> None:
    global _app_id_prepared
    if _app_id_prepared or os.name != "nt":
        return
    _app_id_prepared = True
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def apply_icon(win: tk.Tk) -> None:
    has_ico = False
    if ICON_ICO.is_file():
        try:
            if os.name == "nt":
                win.iconbitmap(default=str(ICON_ICO))
                has_ico = True
            else:
                win.iconbitmap(str(ICON_ICO))
                has_ico = True
        except tk.TclError:
            pass
    if ICON_PNG.is_file():
        try:
            img = tk.PhotoImage(file=str(ICON_PNG))
            win._ahenk_icon = img
            if not has_ico or os.name != "nt":
                win.iconphoto(True, img)
        except tk.TclError:
            pass


def pick_fonts(root: tk.Tk) -> dict[str, tuple]:
    fams = {f.lower() for f in tkfont.families()}
    ui = "Segoe UI" if "segoe ui" in fams else "Arial"
    mono = next(
        (n for n in ("Cascadia Mono", "Consolas", "Courier New") if n.lower() in fams),
        "Courier",
    )
    return {
        "ui": (ui, 9),
        "brand": (ui, 12, "bold"),
        "body": (ui, 10),
        "log": (mono, 8),
    }
