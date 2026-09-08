"""Arayüz paleti. Yeni ekranlar C ve font ölçeğini kullanır."""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_ICO = _ASSETS / "ahenk.ico"
ICON_PNG = _ASSETS / "ahenk.png"
APP_ID = "eneseliagir.ahenk"


class C:
    bg = "#111111"
    rail = "#141414"
    panel = "#171717"
    text = "#e8e8e8"
    muted = "#8d8d8d"
    dim = "#5c5c5c"
    line = "#2b2b2b"
    hover = "#222222"
    fill = "#ececec"
    fill_fg = "#111111"
    live = "#7aaf6a"
    warn = "#c4a35a"
    err = "#c97878"


def dark_titlebar(win: tk.Tk) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            hwnd = win.winfo_id()
        val = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        for attr in (20, 19):
            dwm(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def prepare_app_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply_icon(win: tk.Tk) -> None:
    if ICON_ICO.is_file():
        try:
            if os.name == "nt":
                win.iconbitmap(default=str(ICON_ICO))
            else:
                win.iconbitmap(str(ICON_ICO))
        except tk.TclError:
            try:
                win.iconbitmap(str(ICON_ICO))
            except tk.TclError:
                pass
    if ICON_PNG.is_file():
        try:
            img = tk.PhotoImage(file=str(ICON_PNG))
            win._ahenk_icon = img
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
        "brand": (ui, 11),
        "body": (ui, 10),
        "log": (mono, 8),
    }
