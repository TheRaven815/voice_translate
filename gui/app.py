"""Ana pencere."""

from __future__ import annotations

import asyncio
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox
import webbrowser

from config import load as load_config, resolve_api_key, save_api_key, save_preferences
from devices import NONE_OUTPUT, all_inputs, all_outputs, default_speaker, pick_loopback
from export import TranscriptItem, export_jsonl, export_srt, export_txt
from languages import AUTO_SRC, LANGS, is_rtl, lang_code_to_name, source_code, source_names, src_code_to_name
from i18n import get_ui_lang, set_ui_lang, t
from logger import append_history, log_exception, setup_logging
from loop import SystemAudioLoop, validate_live_api_key
from meta import APP_AUTHOR, APP_TITLE, __version__
from updater import (
    UpdateError,
    UpdateInfo,
    can_self_update,
    check_for_update,
    consume_update_error,
    download_update,
    launch_update_helper,
)
from .theme import C, ICON_PNG, apply_icon, dark_titlebar, pick_fonts, prepare_app_id
from .widgets import IconButton, Select, ThemeSwitch

_PERMANENT_LIVE_ERRORS = (
    "api_key_invalid",
    "api key not valid",
    "permission_denied",
    "forbidden",
    "denied access",
    "policy violation",
    "resource_exhausted",
    "quota",
    "not_found",
)


def _is_retryable_error(err: BaseException) -> bool:
    code = getattr(err, "code", None)
    msg = str(err).lower()
    if code in {400, 401, 403, 404, 429, 1008} or any(token in msg for token in _PERMANENT_LIVE_ERRORS):
        return False
    if isinstance(code, int) and code >= 500:
        return True
    kind = type(err).__name__.lower()
    return any(token in kind or token in msg for token in ("connection", "socket", "timeout", "gaierror", "network"))


def format_user_error(err: BaseException) -> str:
    """Teknik istisnaları kullanıcı dostu Türkçe açıklamaya dönüştürür."""
    msg = str(err)
    err_type = type(err).__name__
    msg_lower = msg.lower()
    if "denied access" in msg_lower or "policy violation" in msg_lower or "1008" in msg:
        return "Google projesinin Gemini Live erişimi reddedildi (1008). Google AI Studio'da başka bir proje/anahtar oluşturun veya proje erişimi için Google desteğe başvurun."

    if "api_key_invalid" in msg_lower or "api key not valid" in msg_lower:
        return "Geçersiz API anahtarı. Lütfen Google AI Studio anahtarınızı kontrol edin (https://aistudio.google.com/apikey)."
    if "429" in msg or "resource_exhausted" in msg_lower or "quota" in msg_lower:
        return "Gemini API kota sınırı aşıldı (429 Resource Exhausted). Lütfen biraz bekleyin veya kotanızı kontrol edin."
    if "404" in msg or "not_found" in msg_lower:
        return "Belirtilen Gemini modeli bulunamadı (404 Not Found). Model adını kontrol edin."
    if "403" in msg or "permission_denied" in msg_lower or "forbidden" in msg_lower:
        return "Gemini API erişim izni reddedildi (403). Anahtarınızın Gemini Live API yetkisini kontrol edin."
    if any(k in err_type.lower() or k in msg_lower for k in ("connection", "socket", "timeout", "gaierror", "network")):
        return f"Ağ bağlantısı hatası ({err_type}): İnternet bağlantınızı ve güvenlik duvarınızı kontrol edin."
    if "ses aygıtı" in msg_lower or "soundcard" in msg_lower:
        return f"Ses aygıtı hatası: {msg}"
    return f"{err_type}: {msg}"


class App(tk.Tk):
    def __init__(self):
        prepare_app_id()
        cfg = load_config()
        self._cfg = cfg
        self._theme = getattr(cfg, "theme", "dark") or "dark"
        C.apply_theme(self._theme)
        set_ui_lang(getattr(cfg, "ui_lang", "tr"))
        super().__init__()
        self.title(APP_TITLE)
        apply_icon(self)
        if getattr(self, "_cfg", None) and self._cfg.window_geom:
            try:
                self.geometry(self._cfg.window_geom)
            except tk.TclError:
                self.geometry("960x580")
        else:
            self.geometry("960x580")
        self.minsize(780, 460)
        self.configure(bg=C.bg)
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.loop_obj: SystemAudioLoop | None = None
        self._stopping = threading.Event()
        self._session_id: int = 0
        self._pending_restart: bool = False
        self.inputs: list = []
        self.outputs: list = []
        self._about: tk.Toplevel | None = None
        self._settings: tk.Toplevel | None = None
        self.key_var: tk.StringVar = tk.StringVar(value=resolve_api_key())
        self.key_entry: tk.Entry | None = None
        self.mask_btn: tk.Label | None = None
        self.key_edge: tk.Frame | None = None
        self._settings_status: tk.Label | None = None
        self._settings_close_btn: tk.Button | None = None
        self._update_info: UpdateInfo | None = None
        self._update_check_running = False
        self._update_installing = False
        self._overlay: tk.Toplevel | None = None
        self._rail_seps: list[tk.Frame] = []
        self.always_on_top = getattr(self._cfg, "always_on_top", False)
        self.overlay_font_size = getattr(self._cfg, "overlay_font_size", 13)
        self.overlay_alpha = getattr(self._cfg, "overlay_alpha", 0.92)
        self.overlay_click_through = getattr(self._cfg, "overlay_click_through", False)
        self.overlay_history_lines = 2
        self.transcript_items: list[TranscriptItem] = []
        self.session_start_time: float | None = None
        self._timeline_start_time: float | None = None
        self._curr_heard_buf = ""
        self._curr_trans_buf = ""
        setup_logging()
        if self.always_on_top:
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
        fonts = pick_fonts(self)
        self.font_ui = fonts["ui"]
        self.font_brand = fonts["brand"]
        self.font_body = fonts["body"]
        self.font_log = fonts["log"]
        self._build()
        self.refresh_devices(async_scan=True)
        dark_titlebar(self, dark=(self._theme != "light"))
        self._pump_after_id = self.after(120, self._pump_log)
        update_error = consume_update_error()
        if update_error:
            self._append(f"[hata] {update_error}\n")
            self.after(250, lambda msg=update_error: messagebox.showerror("Güncelleme", msg, parent=self))
        if can_self_update():
            self.after(1500, self._check_for_updates)

    def _build(self):
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self.rail = tk.Frame(self, bg=C.rail, width=296, bd=0, highlightthickness=0)
        self.rail.grid(row=0, column=0, sticky="nsw")
        self.rail.grid_propagate(False)
        self.rail.columnconfigure(0, weight=1)
        self.rail.rowconfigure(8, weight=1)

        self._v_sep = tk.Frame(self, bg=C.line, width=1, bd=0, highlightthickness=0)
        self._v_sep.grid(row=0, column=1, sticky="ns")

        self.main = tk.Frame(self, bg=C.bg, bd=0, highlightthickness=0)
        self.main.grid(row=0, column=2, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(1, weight=1)

        self._build_rail(self.rail)
        self._build_main(self.main)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _e: self._toggle_start_stop())
        self.bind("<F5>", lambda _e: self._toggle_start_stop())
        self.bind("<Control-o>", lambda _e: self.toggle_overlay())
        self.bind("<Control-O>", lambda _e: self.toggle_overlay())
        self.bind("<F2>", lambda _e: self.toggle_overlay())
        self.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.bind("<Control-T>", lambda _e: self.toggle_theme())
        self.bind("<F6>", lambda _e: self.toggle_theme())
        self.bind("<Control-comma>", lambda _e: self._open_settings())
    def _build_rail(self, rail: tk.Frame):
        self._rail_head = tk.Frame(rail, bg=C.rail)
        self._rail_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 14))

        self._rail_title = tk.Frame(self._rail_head, bg=C.rail)
        self._rail_title.pack(fill=tk.X)
        self.brand = tk.Label(
            self._rail_title, text=APP_TITLE, font=self.font_brand, fg=C.text, bg=C.rail
        )
        self.brand.pack(side=tk.LEFT)
        self.version_lbl = tk.Label(
            self._rail_title, text=f"v{__version__}", font=self.font_ui, fg=C.dim, bg=C.rail
        )
        self.version_lbl.pack(side=tk.LEFT, padx=(8, 0), pady=(2, 0))

        self._rail_actions = tk.Frame(self._rail_head, bg=C.rail)
        self._rail_actions.pack(fill=tk.X, pady=(10, 0))

        self.theme_btn = ThemeSwitch(self._rail_actions, self.toggle_theme)
        self.theme_btn.pack(side=tk.LEFT)
        self.info_btn = IconButton(self._rail_actions, "info", self._open_about, tooltip=t("about"))
        self.info_btn.pack(side=tk.RIGHT)
        self.settings_btn = IconButton(
            self._rail_actions, "gear", self._open_settings, tooltip=t("settings")
        )
        self.settings_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.pin_btn = IconButton(self._rail_actions, "pin", self.toggle_pin, tooltip=t("pin"))
        self.pin_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.pin_btn.set_accent(self.always_on_top)
        self.overlay_btn = IconButton(
            self._rail_actions, "subtitle", self.toggle_overlay, tooltip=t("subtitle")
        )
        self.overlay_btn.pack(side=tk.RIGHT, padx=(0, 6))

        self._rail_st = tk.Frame(self._rail_head, bg=C.rail)
        self._rail_st.pack(anchor="w", pady=(10, 0), fill=tk.X)
        self._dot = tk.Canvas(self._rail_st, width=10, height=10, bg=C.rail, highlightthickness=0, bd=0)
        self._dot.pack(side=tk.LEFT, pady=1)
        self._dot_id = self._dot.create_oval(1, 1, 9, 9, fill=C.dim, outline="")
        self.status = tk.Label(self._rail_st, text=t("ready"), font=self.font_ui, fg=C.muted, bg=C.rail)
        self.status.pack(side=tk.LEFT, padx=(7, 0))
        self.timer_lbl = tk.Label(
            self._rail_st, text="", width=5, anchor="e", font=self.font_ui, fg=C.dim, bg=C.rail
        )
        self.timer_lbl.pack(side=tk.RIGHT, padx=(8, 0))
        self.meter = tk.Canvas(self._rail_st, width=56, height=8, bg=C.line, highlightthickness=0, bd=0)
        self.meter.pack(side=tk.RIGHT, pady=2)
        self._meter_bar = self.meter.create_rectangle(0, 0, 0, 8, fill=C.live, outline="")

        self._rail_sep(rail, 1)

        self._devices_frame = tk.Frame(rail, bg=C.rail)
        self._devices_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._devices_frame.columnconfigure(0, weight=1)
        tk.Label(self._devices_frame, text=t("device"), font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_btn = self._text_btn(
            self._devices_frame, t("refresh"), lambda: self.refresh_devices(async_scan=True)
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        self._fields_frame = tk.Frame(rail, bg=C.rail)
        self._fields_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._fields_frame.columnconfigure(0, weight=1)

        tk.Label(self._fields_frame, text=t("input"), font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.in_var = tk.StringVar()
        self.in_box = Select(self._fields_frame, textvariable=self.in_var, values=["[Sistem]"], font=self.font_ui)
        self.in_box.grid(row=1, column=0, sticky="ew", pady=(3, 10))

        tk.Label(self._fields_frame, text=t("output"), font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=2, column=0, sticky="w"
        )
        self.out_var = tk.StringVar()
        self.out_box = Select(self._fields_frame, textvariable=self.out_var, values=[NONE_OUTPUT], font=self.font_ui)
        self.out_box.grid(row=3, column=0, sticky="ew", pady=(3, 0))

        self._rail_sep(rail, 4)

        self._lang_h = tk.Frame(rail, bg=C.rail)
        self._lang_h.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 0))
        tk.Label(self._lang_h, text=t("language"), font=self.font_ui, fg=C.muted, bg=C.rail).pack(side=tk.LEFT)

        self._langs_frame = tk.Frame(rail, bg=C.rail)
        self._langs_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._langs_frame.columnconfigure(0, weight=1)
        self._langs_frame.columnconfigure(2, weight=1)

        cfg = getattr(self, "_cfg", None) or load_config()
        src_val = src_code_to_name(cfg.src_lang)
        dst_val = lang_code_to_name(cfg.dst_lang)
        self.src_var = tk.StringVar(value=src_val)
        self.src_box = Select(
            self._langs_frame, textvariable=self.src_var, values=source_names(), font=self.font_ui
        )
        self.src_box.grid(row=0, column=0, sticky="ew")

        self.swap_btn = IconButton(self._langs_frame, "swap", self._swap_langs, bg=C.rail)
        self.swap_btn.grid(row=0, column=1, padx=2)

        self.dst_var = tk.StringVar(value=dst_val)
        self.dst_box = Select(
            self._langs_frame, textvariable=self.dst_var, values=list(LANGS), font=self.font_ui
        )
        self.dst_box.grid(row=0, column=2, sticky="ew")

        for var in (self.src_var, self.dst_var):
            var.trace_add("write", self._on_runtime_pref_change)
        for var in (self.in_var, self.out_var):
            # Aygıt değişimi çalışan oturumu durdurup yeniden başlatmaz;
            # yalnızca kaydedilir, bir sonraki başlatmada geçerli olur.
            var.trace_add("write", lambda *_: self._save_user_prefs())

        self._rail_sep(rail, 7)

        self._btns_frame = tk.Frame(rail, bg=C.rail)
        self._btns_frame.grid(row=8, column=0, sticky="ews", padx=16, pady=(0, 16))
        self._btns_frame.columnconfigure(0, weight=1)
        self._btns_frame.columnconfigure(1, weight=1)

        self.start_btn = self._btn(self._btns_frame, t("start"), self.start)
        self.start_btn._edge.grid(row=0, column=0, sticky="ew", padx=(0, 4), ipady=4)
        self.stop_btn = self._btn(self._btns_frame, t("stop"), self.stop)
        self.stop_btn._edge.grid(row=0, column=1, sticky="ew", padx=(4, 0), ipady=4)
        self._paint(self.start_btn, filled=True, enabled=True)
        self._paint(self.stop_btn, filled=False, enabled=False)

    def _build_main(self, main: tk.Frame):
        self.heard_h = tk.Frame(main, bg=C.bg)
        self.heard_h.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(12, 6))
        self.heard_lbl = tk.Label(self.heard_h, text=t("heard"), font=self.font_ui, fg=C.muted, bg=C.bg)
        self.heard_lbl.pack(side=tk.LEFT)
        self.detected_lbl = tk.Label(self.heard_h, text="", font=self.font_ui, fg=C.dim, bg=C.bg)
        self.detected_lbl.pack(side=tk.LEFT, padx=(6, 0))
        self.heard_clear = self._text_btn(self.heard_h, t("clear"), lambda: self._clear_pane(self.heard))
        self.heard_clear.pack(side=tk.RIGHT)
        self.heard_export = self._text_btn(self.heard_h, t("export"), self._export_transcripts)
        self.heard_export.pack(side=tk.RIGHT, padx=(0, 6))
        self.heard_copy = self._text_btn(self.heard_h, t("copy"), lambda: self._copy_pane(self.heard))
        self.heard_copy.pack(side=tk.RIGHT, padx=(0, 6))
        self.trans_h = tk.Frame(main, bg=C.bg)
        self.trans_h.grid(row=0, column=1, sticky="ew", padx=(16, 16), pady=(12, 6))
        self.trans_lbl = tk.Label(self.trans_h, text=t("trans"), font=self.font_ui, fg=C.muted, bg=C.bg)
        self.trans_lbl.pack(side=tk.LEFT)
        self.trans_clear = self._text_btn(self.trans_h, t("clear"), lambda: self._clear_pane(self.trans))
        self.trans_clear.pack(side=tk.RIGHT)
        self.trans_export = self._text_btn(self.trans_h, t("export"), self._export_transcripts)
        self.trans_export.pack(side=tk.RIGHT, padx=(0, 6))
        self.trans_copy = self._text_btn(self.trans_h, t("copy"), lambda: self._copy_pane(self.trans))
        self.trans_copy.pack(side=tk.RIGHT, padx=(0, 6))

        self.heard_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        self.trans_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        self.heard_wrap.grid(row=1, column=0, sticky="nsew")
        self.trans_wrap.grid(row=1, column=1, sticky="nsew")
        for wrap in (self.heard_wrap, self.trans_wrap):
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)

        self._main_v_sep = tk.Frame(main, bg=C.line, width=1, bd=0, highlightthickness=0)
        self._main_v_sep.grid(row=0, column=0, rowspan=2, sticky="nse", pady=(12, 0))

        self.heard = self._pane(self.heard_wrap)
        self.trans = self._pane(self.trans_wrap)

        self._main_h_sep = tk.Frame(main, bg=C.line, height=1, bd=0, highlightthickness=0)
        self._main_h_sep.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.log_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        self.log_wrap.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.log_wrap.columnconfigure(0, weight=1)

        self.log = tk.Text(
            self.log_wrap,
            wrap=tk.WORD,
            height=3,
            font=self.font_log,
            bg=C.bg,
            fg=C.dim,
            insertbackground=C.dim,
            selectbackground=C.select,
            selectforeground=C.muted,
            inactiveselectbackground=C.select,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=8,
            cursor="arrow",
            takefocus=0,
        )
        self.log.grid(row=0, column=0, sticky="ew")
        self.log.tag_configure("body", foreground=C.dim)
        self.log.tag_configure("info", foreground=C.muted)
        self.log.tag_configure("err", foreground=C.err)
        self._lock_text(self.log)

    def _pane(self, parent: tk.Frame) -> tk.Text:
        text = tk.Text(
            parent,
            wrap=tk.WORD,
            font=self.font_body,
            bg=C.bg,
            fg=C.text,
            insertbackground=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
            inactiveselectbackground=C.select,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=4,
            spacing1=1,
            spacing3=8,
            cursor="arrow",
            takefocus=0,
        )
        text.grid(row=0, column=0, sticky="nsew")
        text.tag_configure("body", foreground=C.text)
        text.tag_configure("rtl", justify="right")
        text.tag_configure("ltr", justify="left")
        self._lock_text(text)
        self._bind_zoom(text)
        return text

    def _lock_text(self, w: tk.Text) -> None:
        def on_key(e):
            if e.keysym in (
                "Up", "Down", "Left", "Right", "Home", "End",
                "Prior", "Next", "Tab", "ISO_Left_Tab",
                "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                "Caps_Lock", "Escape"
            ) or (e.keysym.startswith("F") and e.keysym[1:].isdigit()):
                return
            if e.state & 0x4:
                if e.keysym.lower() not in ("v", "x"):
                    return
            return "break"

        w.bind("<Key>", on_key)
        w.bind("<<Paste>>", lambda _e: "break")
        w.bind("<<Cut>>", lambda _e: "break")
        w.bind("<Button-2>", lambda _e: "break")
    def _rail_sep(self, parent: tk.Frame, row: int) -> None:
        sep = tk.Frame(parent, bg=C.line, height=1, bd=0, highlightthickness=0)
        sep.grid(row=row, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._rail_seps.append(sep)
    def _text_btn(self, parent, label: str, command, bg: str | None = None) -> tk.Label:
        color_bg = bg or (parent["bg"] if "bg" in parent.keys() else C.rail)
        w = tk.Label(parent, text=label, font=self.font_ui, fg=C.dim, bg=color_bg, cursor="hand2")
        w._rest_fg = C.dim
        w.bind("<Button-1>", lambda _e: command())
        w.bind("<Enter>", lambda _e: w.configure(fg=C.text))
        w.bind("<Leave>", lambda _e: w.configure(fg=w._rest_fg))
        return w

    def _btn(self, parent, label: str, command) -> tk.Button:
        wrap = tk.Frame(parent, bg=C.line, bd=0, highlightthickness=0)
        btn = tk.Button(
            wrap,
            text=label,
            command=command,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            disabledforeground=C.dim,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=5,
            cursor="hand2",
            takefocus=1,
        )
        btn.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        btn._rest_bg = C.panel
        btn._hover_bg = C.hover
        btn._edge = wrap

        def on_enter(_e, b=btn):
            if str(b["state"]) != tk.DISABLED:
                b.configure(bg=b._hover_bg)

        def on_leave(_e, b=btn):
            if str(b["state"]) != tk.DISABLED:
                b.configure(bg=b._rest_bg)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    def _paint(self, btn: tk.Button, *, filled: bool, enabled: bool) -> None:
        if filled and enabled:
            bg, fg, edge, hover = C.fill, C.fill_fg, C.fill, getattr(C, "fill_hover", "#ffffff")
        elif enabled:
            bg, fg, edge, hover = C.panel, C.text, C.line, C.hover
        else:
            bg, fg, edge, hover = C.disabled_bg, C.dim, C.line, C.disabled_bg
        btn._rest_bg = bg
        btn._hover_bg = hover
        btn.configure(
            state=tk.NORMAL if enabled else tk.DISABLED,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=C.dim,
        )
        btn._edge.configure(bg=edge)

    def _set_status(self, text: str, color: str = C.dim) -> None:
        status_map = {
            "Hazır": "ready",
            "Çalışıyor": "running",
            "Bağlanıyor": "connecting",
            "Durdu": "stopped",
            "Durduruluyor": "stopping",
            "Yeniden başlatılıyor": "restarting",
            "Hata": "error",
        }
        key = status_map.get(text)
        translated = t(key, text) if key else text
        self.status.configure(text=translated)
        self._dot.itemconfigure(self._dot_id, fill=color)
    def _set_running(self, running: bool) -> None:
        if self.key_entry is not None and self.key_entry.winfo_exists():
            self.key_entry.configure(state=tk.DISABLED if running else tk.NORMAL)
        self._paint(self.start_btn, filled=not running, enabled=not running)
        self._paint(self.stop_btn, filled=running, enabled=running)
        self._dot.itemconfigure(self._dot_id, fill=C.live if running else C.dim)
        if not running:
            self._update_meter(0.0)

    def _swap_langs(self) -> None:
        if self.src_var.get() == AUTO_SRC:
            return
        a, b = self.src_var.get(), self.dst_var.get()
        self.src_var.set(b)
        self.dst_var.set(a)

    def refresh_devices(self, async_scan: bool = True):
        stopping = self.worker is not None and self.worker.is_alive()
        if async_scan:
            def _scan():
                try:
                    ins = all_inputs()
                    outs = all_outputs()
                    self.log_queue.put(("devices_scanned", ins, outs, stopping))
                except Exception as e:
                    self.log_queue.put(("device_scan_error", str(e)))
            threading.Thread(target=_scan, daemon=True).start()
            return

        ins = all_inputs()
        outs = all_outputs()
        self._apply_devices(ins, outs, stopping)

    def _apply_devices(self, ins, outs, stopping: bool):
        self.inputs = ins
        self.outputs = outs
        self.in_box["values"] = [
            ("[Sistem] " if m.isloopback else "[Mikrofon] ") + m.name for m in ins
        ]
        self.out_box["values"] = [NONE_OUTPUT] + [s.name for s in outs]
        if not stopping:
            cfg = getattr(self, "_cfg", None) or load_config()
            cur_in = self.in_var.get()
            if cur_in and cur_in in self.in_box["values"]:
                pass
            elif cfg.input_device and cfg.input_device in self.in_box["values"]:
                self.in_var.set(cfg.input_device)
            else:
                loops = [m for m in ins if getattr(m, "isloopback", False)]
                default_in = None
                if loops:
                    try:
                        default_sp = default_speaker()
                        if default_sp is not None:
                            for m in loops:
                                if default_sp.name in m.name or m.name in default_sp.name:
                                    default_in = m
                                    break
                    except Exception:
                        pass
                    if default_in is None:
                        default_in = loops[0]
                elif ins:
                    default_in = ins[0]

                if default_in is not None:
                    self.in_var.set(
                        ("[Sistem] " if getattr(default_in, "isloopback", False) else "[Mikrofon] ") + default_in.name
                    )

            cur_out = self.out_var.get()
            if cur_out and cur_out in self.out_box["values"]:
                pass
            elif cfg.output_device and cfg.output_device in self.out_box["values"]:
                self.out_var.set(cfg.output_device)
            else:
                try:
                    self.out_var.set(default_speaker().name)
                except Exception:
                    self.out_var.set(NONE_OUTPUT)
    def _selected_speaker(self):
        i = self.out_box.current()
        if i <= 0:
            return None
        try:
            return self.outputs[i - 1]
        except IndexError:
            return None

    def _append(self, text: str):
        if text.startswith("[hata]"):
            tag = "err"
        elif text.startswith("[bilgi]"):
            tag = "info"
        else:
            tag = "body"
        self.log.insert(tk.END, text, (tag,))
        self.log.see(tk.END)

    def _toggle_start_stop(self):
        if self.worker is not None and self.worker.is_alive():
            self.stop()
        else:
            self.start()

    def _overlay_tail(self, full_text: str) -> str:
        """Overlay için son N görsel satırı döndürür.

        Tk 'end - N lines' mantıksal satır saydığı için uzun paragrafların
        tamamı ekrana taşıyordu; burada wraplength genişliğine göre gerçek
        kelime kaydırması ölçülür.
        """
        text = full_text.strip()
        if not text:
            return ""
        max_lines = max(1, getattr(self, "overlay_history_lines", 2))
        font = tkfont.Font(font=(self.font_brand[0], getattr(self, "overlay_font_size", 13), "bold"))
        try:
            avail = 520
            if getattr(self, "overlay_label", None) is not None and self.overlay_label.winfo_exists():
                avail = max(120, int(str(self.overlay_label.cget("wraplength"))))
            lines: list[str] = []
            cur = ""
            for word in text.split():
                cand = f"{cur} {word}".strip()
                if cur and font.measure(cand) > avail:
                    lines.append(cur)
                    cur = word
                else:
                    cur = cand
            if cur:
                lines.append(cur)
            if len(lines) <= max_lines:
                return text
            return "\n".join(lines[-max_lines:])
        finally:
            del font

    def _update_overlay(self, full_text: str) -> None:
        if self._overlay is None or not self._overlay.winfo_exists():
            return
        tail = self._overlay_tail(full_text)
        if not tail:
            return
        self.overlay_label.configure(
            text=tail,
            justify="right" if is_rtl(self.dst_var.get()) else "center",
        )
        self._fit_overlay()

    def _write_pane(self, widget, text: str):
        # Akış sırasında eski bir seçim gri blok gibi görünmesin diye kaldır.
        if widget.tag_ranges("sel"):
            widget.tag_remove("sel", "1.0", tk.END)
        lang = self.src_var.get() if widget is self.heard else self.dst_var.get()
        tag = "rtl" if is_rtl(lang) else "ltr"
        widget.insert(tk.END, text, ("body", tag))
        widget.see(tk.END)
        if widget is self.trans and self._overlay is not None and self._overlay.winfo_exists():
            last = widget.get("end - 2 lines linestart", "end - 1 chars").strip()
            if not last:
                lines = [
                    l.strip()
                    for l in widget.get("end - 4 lines linestart", "end - 1 chars").splitlines()
                    if l.strip()
                ]
                last = lines[-1] if lines else ""
            if last:
                self._update_overlay(last)
    def _clear_pane(self, widget):
        widget.delete("1.0", tk.END)
        if widget is self.heard:
            self.detected_lbl.configure(text="")
            self._curr_heard_buf = ""
            self.transcript_items = [it for it in self.transcript_items if it.stream != "heard"]
        elif widget is self.trans:
            if self._overlay is not None and self._overlay.winfo_exists():
                self.overlay_label.configure(text="...")
            self._curr_trans_buf = ""
            self.transcript_items = [it for it in self.transcript_items if it.stream != "trans"]
        if not self.transcript_items and (self.worker is None or not self.worker.is_alive()):
            self._timeline_start_time = None
    def _copy_pane(self, pane: tk.Text):
        content = pane.get("1.0", "end-1c").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._append("[bilgi] Metin panoya kopyalandı.\n")

    def _update_meter(self, level: float) -> None:
        w = int(max(0.0, min(1.0, level)) * 56)
        self.meter.coords(self._meter_bar, 0, 0, w, 8)

    def _save_user_prefs(self):
        if getattr(self, "_save_prefs_timer", None) is not None:
            try:
                self.after_cancel(self._save_prefs_timer)
            except Exception:
                pass
        self._save_prefs_timer = self.after(400, self._do_save_user_prefs)

    def _do_save_user_prefs(self):
        self._save_prefs_timer = None
        src_raw = self.src_var.get()
        src_code = "auto" if src_raw == AUTO_SRC else LANGS.get(src_raw, src_raw)
        dst_code = LANGS.get(self.dst_var.get(), self.dst_var.get())
        overlay_geom = None
        if self._overlay is not None and self._overlay.winfo_exists():
            overlay_geom = self._overlay.geometry()
        try:
            save_preferences(
                input_device=self.in_var.get(),
                output_device=self.out_var.get(),
                src_lang=src_code,
                dst_lang=dst_code,
                theme=getattr(self, "_theme", "dark"),
                window_geom=self.geometry(),
                overlay_geom=overlay_geom,
                always_on_top=getattr(self, "always_on_top", False),
                overlay_font_size=getattr(self, "overlay_font_size", 13),
                overlay_alpha=getattr(self, "overlay_alpha", 0.92),
                overlay_click_through=getattr(self, "overlay_click_through", False),
            )
        except OSError:
            pass

    def toggle_pin(self) -> None:
        self.always_on_top = not getattr(self, "always_on_top", False)
        try:
            self.attributes("-topmost", self.always_on_top)
        except tk.TclError:
            pass
        if hasattr(self, "pin_btn"):
            self.pin_btn.set_accent(self.always_on_top)
        self._save_user_prefs()

    def _toggle_key_mask(self) -> None:
        if self.key_entry is None or not self.key_entry.winfo_exists():
            return
        if self.key_entry.cget("show") == "•":
            self.key_entry.configure(show="")
            if self.mask_btn is not None and self.mask_btn.winfo_exists():
                self.mask_btn.kind = "eye_off"
                self.mask_btn.redraw()
        else:
            self.key_entry.configure(show="•")
            if self.mask_btn is not None and self.mask_btn.winfo_exists():
                self.mask_btn.kind = "eye"
                self.mask_btn.redraw()

    def _test_api_key(self) -> None:
        key = self.key_var.get().strip()
        if not key:
            self._append("[hata] Test için önce bir API anahtarı girin.\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text="Test için önce bir anahtar girin.", fg=C.warn)
            return
        self._append("[bilgi] API anahtarı test ediliyor...\n")
        if self._settings_status is not None and self._settings_status.winfo_exists():
            self._settings_status.configure(text="API anahtarı test ediliyor...", fg=C.dim)
        def _bg():
            try:
                asyncio.run(validate_live_api_key(key))
                self.log_queue.put("[bilgi] ✓ API anahtarı geçerli; Gemini Live erişimi açık.\n")
                self.log_queue.put(("key_test_result", True, "✓ API anahtarı geçerli; Gemini Live açık.", C.live))
            except Exception as e:
                err_msg = format_user_error(e)
                self.log_queue.put(f"[hata] ✕ Gemini Live erişim testi başarısız: {err_msg}\n")
                self.log_queue.put(("key_test_result", False, f"✕ Test başarısız: {err_msg}", C.warn))
        threading.Thread(target=_bg, daemon=True).start()

    def _get_export_items(self) -> list[TranscriptItem]:
        items = list(getattr(self, "transcript_items", []))
        now = time.time()
        heard_buf = getattr(self, "_curr_heard_buf", "").strip()
        trans_buf = getattr(self, "_curr_trans_buf", "").strip()
        if heard_buf:
            items.append(TranscriptItem(timestamp=now, stream="heard", text=heard_buf))
        if trans_buf:
            items.append(TranscriptItem(timestamp=now + 0.5, stream="trans", text=trans_buf))
        if not items:
            heard_text = self.heard.get("1.0", "end-1c").strip()
            trans_text = self.trans.get("1.0", "end-1c").strip()
            if heard_text:
                for line in heard_text.splitlines():
                    if line.strip():
                        items.append(TranscriptItem(timestamp=now, stream="heard", text=line.strip()))
            if trans_text:
                for line in trans_text.splitlines():
                    if line.strip():
                        items.append(TranscriptItem(timestamp=now + 1.0, stream="trans", text=line.strip()))
        return items

    def _export_transcripts(self) -> None:
        from tkinter import filedialog
        from export import export_txt, export_srt, export_jsonl
        items = self._get_export_items()
        if not items:
            self._append("[bilgi] Dışa aktarılacak transkript yok.\n")
            return

        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="Transkripti Dışa Aktar",
            defaultextension=".txt",
            filetypes=[
                ("Metin Dosyası (*.txt)", "*.txt"),
                ("Altyazı Dosyası (*.srt)", "*.srt"),
                ("JSON Lines (*.jsonl)", "*.jsonl"),
            ],
        )
        if not file_path:
            return
        try:
            if file_path.lower().endswith(".srt"):
                content = export_srt(items, session_start=getattr(self, "_timeline_start_time", None) or getattr(self, "session_start_time", None))
            elif file_path.lower().endswith(".jsonl"):
                content = export_jsonl(items)
            else:
                content = export_txt(items)
            Path(file_path).write_text(content, encoding="utf-8")
            self._append(f"[bilgi] Transkript dışa aktarıldı: {file_path}\n")
        except Exception as e:
            self._append(f"[hata] Dışa aktarma başarısız: {e}\n")

    def _bind_zoom(self, widget: tk.Text) -> None:
        def _on_wheel(e):
            if getattr(e, "state", 0) & 0x4:
                if e.delta > 0:
                    self._adjust_font_size(1)
                elif e.delta < 0:
                    self._adjust_font_size(-1)
                return "break"
        widget.bind("<MouseWheel>", _on_wheel)

    def _adjust_font_size(self, delta: int) -> None:
        family, size = self.font_body[0], self.font_body[1]
        new_size = max(8, min(32, size + delta))
        self.font_body = (family, new_size)
        self.heard.configure(font=self.font_body)
        self.trans.configure(font=self.font_body)

    def _adjust_overlay_font(self, delta: int) -> None:
        self.overlay_font_size = max(10, min(32, getattr(self, "overlay_font_size", 13) + delta))
        if hasattr(self, "overlay_label") and self.overlay_label.winfo_exists():
            self.overlay_label.configure(font=(self.font_brand[0], self.overlay_font_size, "bold"))
            self._fit_overlay()
        self._save_user_prefs()

    def _apply_overlay_click_through(self) -> None:
        if os.name != "nt" or self._overlay is None or not self._overlay.winfo_exists():
            return
        import ctypes
        hwnd = self._overlay.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_LAYERED = 0x00080000
        try:
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if self.overlay_click_through:
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
            else:
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
        except Exception:
            pass

    def _toggle_overlay_click_through(self) -> None:
        if self._overlay is None or not self._overlay.winfo_exists():
            return
        self.overlay_click_through = not getattr(self, "overlay_click_through", False)
        # Tk'nin pencere bayraklariyla karismamasi icin pencereyi yeniden kur;
        # boylece geri almak da garantili calisir.
        geom = self._overlay.geometry()
        self._overlay.destroy()
        self._overlay = None
        self._build_overlay(geom=geom)
        if hasattr(self, "_overlay_thru_btn"):
            self._overlay_thru_btn.kind = "target" if self.overlay_click_through else "cursor"
            self._overlay_thru_btn.redraw()
        self._save_user_prefs()
    def restart(self) -> None:
        """Çalışırken ayarları nazikçe yeniden başlatarak uygular."""
        if self.worker is not None and self.worker.is_alive():
            self._pending_restart = True
            self.stop(cancel_restart=False)
        else:
            self._pending_restart = False
            self.start()

    def _on_runtime_pref_change(self, *args):
        self._save_user_prefs()
        if self.worker is not None and self.worker.is_alive() and not self._stopping.is_set():
            if getattr(self, "_restart_timer", None) is not None:
                try:
                    self.after_cancel(self._restart_timer)
                except Exception:
                    pass
            self._restart_timer = self.after(300, self._do_runtime_restart)

    def _do_runtime_restart(self):
        self._restart_timer = None
        if self.worker is not None and self.worker.is_alive() and not self._stopping.is_set():
            self._append("[bilgi] Ayarlar güncellendi, yeni parametrelerle yeniden başlatılıyor...\n")
            self.restart()
    def toggle_theme(self) -> None:
        new_theme = "light" if C.current == "dark" else "dark"
        self.set_theme(new_theme)

    def set_theme(self, name: str) -> None:
        self._theme = name
        C.apply_theme(name)
        dark_titlebar(self, dark=(name != "light"))
        try:
            save_preferences(theme=name)
        except OSError:
            pass
        self._refresh_theme()

    def _refresh_theme(self) -> None:
        self.configure(bg=C.bg)
        self.rail.configure(bg=C.rail)
        self._v_sep.configure(bg=C.line)
        self.main.configure(bg=C.bg)

        # Rail header
        for f in (self._rail_head, self._rail_title, self._rail_actions, self._rail_st):
            f.configure(bg=C.rail)
        self.brand.configure(fg=C.text, bg=C.rail)
        self.version_lbl.configure(fg=C.dim, bg=C.rail)
        self.status.configure(fg=C.muted, bg=C.rail)
        self.timer_lbl.configure(fg=C.dim, bg=C.rail)
        self._dot.configure(bg=C.rail)
        running = self.worker is not None and self.worker.is_alive()
        self._dot.itemconfigure(self._dot_id, fill=C.live if running else C.dim)
        self.meter.configure(bg=C.line)
        self.meter.itemconfigure(self._meter_bar, fill=C.live)

        # Rail icon buttons + theme switch
        for btn in (self.info_btn, self.settings_btn, self.pin_btn, self.overlay_btn):
            btn.configure(bg=C.rail)
        self.pin_btn.set_accent(self.always_on_top)
        self.overlay_btn.set_accent(
            self._overlay is not None and self._overlay.winfo_exists()
        )
        self.swap_btn.configure(bg=C.rail)
        self.theme_btn.configure(bg=C.rail)
        self.theme_btn.sync(animate=True)
        self.refresh_btn._rest_fg = C.dim
        self.refresh_btn.configure(fg=C.dim, bg=C.rail)

        # Rail frames and labels
        for f in (
            self._devices_frame,
            self._fields_frame,
            self._lang_h,
            self._langs_frame,
            self._btns_frame,
        ):
            f.configure(bg=C.rail)
            for child in f.winfo_children():
                if isinstance(child, tk.Label) and child is not self.swap_btn and child is not self.refresh_btn:
                    child.configure(fg=C.muted, bg=C.rail)

        for sep in self._rail_seps:
            sep.configure(bg=C.line)

        # Dropdowns
        for box in (self.in_box, self.out_box, self.src_box, self.dst_box):
            box.update_theme()

        # Swap button
        self.swap_btn.configure(bg=C.rail)
        # Action buttons
        self._paint(self.start_btn, filled=not running, enabled=not running)
        self._paint(self.stop_btn, filled=running, enabled=running)

        # Main panes
        for f in (self.heard_h, self.trans_h, self.heard_wrap, self.trans_wrap, self.log_wrap):
            f.configure(bg=C.bg)
        for lbl in (self.heard_lbl, self.trans_lbl, self.detected_lbl):
            lbl.configure(fg=C.muted, bg=C.bg)
        self.detected_lbl.configure(fg=C.dim)
        for btn in (
            self.heard_clear, self.heard_copy, self.heard_export,
            self.trans_clear, self.trans_copy, self.trans_export,
        ):
            btn._rest_fg = C.dim
            btn.configure(fg=C.dim, bg=C.bg)

        for sep in (self._main_h_sep, self._main_v_sep):
            sep.configure(bg=C.line)

        for pane in (self.heard, self.trans):
            pane.configure(
                bg=C.bg,
                fg=C.text,
                insertbackground=C.text,
                selectbackground=C.select,
                selectforeground=C.text,
                inactiveselectbackground=C.select,
            )
            pane.tag_configure("body", foreground=C.text)

        self.log.configure(
            bg=C.bg,
            fg=C.dim,
            insertbackground=C.dim,
            selectbackground=C.select,
            selectforeground=C.muted,
            inactiveselectbackground=C.select,
        )
        self.log.tag_configure("body", foreground=C.dim)
        self.log.tag_configure("info", foreground=C.muted)
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.configure(bg=C.panel)
            dark_titlebar(self._settings, dark=(C.current != "light"))
            if self.key_edge is not None and self.key_edge.winfo_exists():
                self.key_edge.configure(bg=C.line)
            if self.key_entry is not None and self.key_entry.winfo_exists():
                self.key_entry.configure(
                    bg=C.panel,
                    fg=C.text,
                    insertbackground=C.text,
                    disabledbackground=C.rail,
                    disabledforeground=C.dim,
                )
            if self.mask_btn is not None and self.mask_btn.winfo_exists():
                self.mask_btn.configure(bg=C.panel)
            for child in self._settings.winfo_children():
                self._retint_frame(child, bg=C.panel)
        self.log.tag_configure("err", foreground=C.err)
        dark_titlebar(self, dark=(C.current != "light"))
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.configure(bg=C.overlay_bg)
            if hasattr(self, "_overlay_wrap") and self._overlay_wrap.winfo_exists():
                self._overlay_wrap.configure(bg=C.overlay_bg, highlightbackground=C.line)
            if hasattr(self, "_overlay_hdr") and self._overlay_hdr.winfo_exists():
                self._overlay_hdr.configure(bg=C.overlay_bg)
            if hasattr(self, "overlay_label") and self.overlay_label.winfo_exists():
                self.overlay_label.configure(bg=C.overlay_bg, fg=C.text)
            if hasattr(self, "_overlay_close") and self._overlay_close.winfo_exists():
                self._overlay_close.configure(bg=C.overlay_bg)
            if hasattr(self, "_overlay_thru_btn") and self._overlay_thru_btn.winfo_exists():
                self._overlay_thru_btn.configure(bg=C.overlay_bg)
            if hasattr(self, "_overlay_fplus") and self._overlay_fplus.winfo_exists():
                self._overlay_fplus.configure(bg=C.overlay_bg, fg=C.dim)
            if hasattr(self, "_overlay_fminus") and self._overlay_fminus.winfo_exists():
                self._overlay_fminus.configure(bg=C.overlay_bg, fg=C.dim)
            if hasattr(self, "_overlay_grip") and self._overlay_grip.winfo_exists():
                self._overlay_grip.configure(bg=C.overlay_bg, fg=C.dim)
        if self._about is not None and self._about.winfo_exists():
            self._about.configure(bg=C.panel)
            dark_titlebar(self._about, dark=(C.current != "light"))
            for child in self._about.winfo_children():
                self._retint_frame(child, bg=C.panel)

    def _retint_frame(self, widget, *, bg: str) -> None:
        """Açık diyaloglarda (Ayarlar/Hakkında) tema geçişini tüm içeriğe uygular."""
        for child in widget.winfo_children():
            if child in (self.key_edge, self.key_entry, self.mask_btn):
                continue
            if isinstance(child, tk.Frame):
                try:
                    if child.cget("bg") != C.line:
                        child.configure(bg=bg)
                except tk.TclError:
                    pass
                self._retint_frame(child, bg=bg)
            elif isinstance(child, tk.Label):
                try:
                    child.configure(bg=bg)
                except tk.TclError:
                    pass
            elif isinstance(child, tk.Button):
                try:
                    child.configure(bg=bg, fg=C.text, activebackground=C.hover, activeforeground=C.text)
                except tk.TclError:
                    pass
    def _pump_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                try:
                    if msg == "__stopped__" or (isinstance(msg, tuple) and len(msg) > 0 and msg[0] == "__stopped__"):
                        sid = msg[1] if isinstance(msg, tuple) and len(msg) > 1 else None
                        if sid is not None and sid != self._session_id:
                            continue
                        if getattr(self, "_curr_heard_buf", "").strip():
                            self.transcript_items.append(
                                TranscriptItem(timestamp=time.time(), stream="heard", text=self._curr_heard_buf.strip())
                            )
                            self._curr_heard_buf = ""
                        if getattr(self, "_curr_trans_buf", "").strip():
                            self.transcript_items.append(
                                TranscriptItem(timestamp=time.time(), stream="trans", text=self._curr_trans_buf.strip())
                            )
                            self._curr_trans_buf = ""
                        self._set_running(False)
                        self.worker = None
                        self.loop_obj = None
                        if getattr(self, "_pending_restart", False):
                            self._pending_restart = False
                            try:
                                self.start(preserve_transcript=True)
                            except TypeError:
                                self.start()
                        else:
                            if self.status.cget("text") not in ("Hata", "Error"):
                                self._set_status("Durdu", C.dim)
                        continue
                    if isinstance(msg, tuple):
                        kind = msg[0]
                        payload = msg[1] if len(msg) > 1 else ""
                        if kind == "heard":
                            self._curr_heard_buf += payload
                            self._write_pane(self.heard, payload)
                        elif kind == "trans":
                            self._curr_trans_buf += payload
                            self._write_pane(self.trans, payload)
                        elif kind == "heard_end":
                            if self._curr_heard_buf.strip():
                                self.transcript_items.append(
                                    TranscriptItem(timestamp=time.time(), stream="heard", text=self._curr_heard_buf.strip())
                                )
                                self._curr_heard_buf = ""
                            self._write_pane(self.heard, "\n")
                        elif kind == "trans_end":
                            if self._curr_trans_buf.strip():
                                text_trans = self._curr_trans_buf.strip()
                                self.transcript_items.append(
                                    TranscriptItem(timestamp=time.time(), stream="trans", text=text_trans)
                                )
                                if getattr(self._cfg, "save_history", True):
                                    append_history(
                                        self.heard.get("end - 2 lines linestart", "end - 1 chars").strip(),
                                        text_trans,
                                        src=self.src_var.get(),
                                        dst=self.dst_var.get(),
                                    )
                                self._curr_trans_buf = ""
                            self._write_pane(self.trans, "\n")
                        elif kind == "log":
                            self._append(payload)
                        elif kind == "level":
                            pass
                        elif kind == "status":
                            status_text = payload
                            color = msg[2] if len(msg) > 2 else C.live
                            self._set_status(status_text, color)
                        elif kind == "detected_src":
                            detected_name = lang_code_to_name(payload, default=payload)
                            self.detected_lbl.configure(text=f"[{detected_name}]")
                        elif kind == "latency":
                            if self.worker is not None and self.worker.is_alive():
                                self._set_status(f"Çalışıyor ({int(payload)} ms)", C.live)
                        elif kind == "update_result":
                            self._handle_update_result(payload, manual=bool(msg[2]))
                        elif kind == "update_error":
                            self._handle_update_error(str(payload), manual=bool(msg[2]))
                        elif kind == "update_ready":
                            self._apply_downloaded_update(payload, msg[2])
                        elif kind == "devices_scanned":
                            if self.winfo_exists():
                                self._apply_devices(payload, msg[2], msg[3])
                        elif kind == "device_scan_error":
                            self._append(f"[hata] Aygıt tarama hatası: {payload}\n")
                        elif kind == "key_test_result":
                            if getattr(self, "_settings_status", None) is not None and self._settings_status.winfo_exists():
                                self._settings_status.configure(text=msg[2], fg=msg[3])
                    else:
                        self._append(str(msg))
                except Exception as e:
                    self._append(f"[hata] Arayüz kuyruk hatası: {e}\n")
        except queue.Empty:
            pass
        finally:
            if self.worker is not None and self.worker.is_alive() and self.session_start_time:
                elapsed = int(time.time() - self.session_start_time)
                m, s = divmod(elapsed, 60)
                if hasattr(self, "timer_lbl"):
                    self.timer_lbl.configure(text=f"{m:02d}:{s:02d}")
            elif hasattr(self, "timer_lbl"):
                self.timer_lbl.configure(text="")
            if self.loop_obj is not None:
                self._update_meter(getattr(self.loop_obj, "last_level", 0.0))
            elif not (self.worker is not None and self.worker.is_alive()):
                self._update_meter(0.0)
            try:
                self._pump_after_id = self.after(120, self._pump_log)
            except tk.TclError:
                self._pump_after_id = None

    def _check_for_updates(self, manual: bool = False) -> None:
        if self._update_check_running or self._update_installing:
            if manual:
                messagebox.showinfo("Güncelleme", "Güncelleme işlemi zaten çalışıyor.", parent=self)
            return
        if not can_self_update():
            if manual:
                messagebox.showinfo(
                    "Güncelleme",
                    "Otomatik güncelleme yalnız Ahenk.exe onefile sürümünde kullanılabilir.",
                    parent=self,
                )
            return
        self._update_check_running = True
        if manual and not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Güncelleme denetleniyor", C.warn)

        def check() -> None:
            try:
                self.log_queue.put(("update_result", check_for_update(), manual))
            except UpdateError as exc:
                self.log_queue.put(("update_error", str(exc), manual))
            except Exception as exc:
                log_exception(exc, "Update check error")
                self.log_queue.put(("update_error", "Beklenmeyen güncelleme denetimi hatası.", manual))

        threading.Thread(target=check, name="update-check", daemon=True).start()

    def _handle_update_result(self, info: UpdateInfo | None, *, manual: bool) -> None:
        self._update_check_running = False
        self._update_info = info
        if info is None:
            if manual:
                messagebox.showinfo("Güncelleme", f"Ahenk v{__version__} güncel.", parent=self)
            if not (self.worker is not None and self.worker.is_alive()):
                self._set_status("Hazır", C.dim)
            return
        self.version_lbl.configure(text=f"v{__version__}  •  v{info.version} hazır", fg=C.live)
        if hasattr(self, "about_update_status") and self.about_update_status.winfo_exists():
            self.about_update_status.configure(text=f"v{info.version} indirilmeye hazır", fg=C.live)
        install = messagebox.askyesno(
            "Ahenk güncellemesi",
            f"Ahenk v{info.version} yayımlandı.\n\nGüncelleme şimdi indirilip kurulsun mu?\n"
            "Uygulama kurulumdan sonra yeniden başlayacak.",
            parent=self,
        )
        if install:
            self._download_and_install_update(info)
        elif not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Hazır", C.dim)

    def _handle_update_error(self, error: str, *, manual: bool) -> None:
        self._update_check_running = False
        self._update_installing = False
        self._append(f"[hata] Güncelleme: {error}\n")
        if not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Hazır", C.dim)
        if manual:
            messagebox.showerror("Güncelleme denetlenemedi", error, parent=self)

    def _download_and_install_update(self, info: UpdateInfo) -> None:
        if self._update_installing:
            return
        self._update_installing = True
        self._set_status("Güncelleme indiriliyor", C.warn)
        self._append(f"[bilgi] Ahenk v{info.version} indiriliyor...\n")

        def download() -> None:
            try:
                staged = download_update(info)
                self.log_queue.put(("update_ready", staged, info))
            except UpdateError as exc:
                self.log_queue.put(("update_error", str(exc), True))
            except Exception as exc:
                log_exception(exc, "Update download error")
                self.log_queue.put(("update_error", "Beklenmeyen güncelleme indirme hatası.", True))

        threading.Thread(target=download, name="update-download", daemon=True).start()

    def _apply_downloaded_update(self, staged: Path, info: UpdateInfo) -> None:
        try:
            launch_update_helper(staged, info)
        except UpdateError as exc:
            self._handle_update_error(str(exc), manual=True)
            return
        self._append("[bilgi] Güncelleme doğrulandı. Ahenk yeniden başlatılıyor...\n")
        self._set_status("Güncelleme kuruluyor", C.warn)
        self.after(100, self._on_close)

    def save_key(self):
        key = self.key_var.get().strip()
        try:
            save_api_key(key)
        except OSError as e:
            self._append(f"[hata] Anahtar kaydedilemedi: {e}\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text=f"Kaydedilemedi: {e}", fg=C.warn)
            return
        if key:
            self._append("[bilgi] API anahtarı kaydedildi.\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text="✓ API anahtarı kaydedildi.", fg=C.live)
        else:
            self._append("[bilgi] Kayıtlı anahtar silindi.\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text="Kayıtlı anahtar silindi.", fg=C.dim)
        if self.key_entry is not None and self.key_entry.winfo_exists():
            self.key_entry.selection_clear()
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.focus_set()
        else:
            self.focus_set()

    def start(self, preserve_transcript: bool = False):
        if self.worker is not None and self.worker.is_alive():
            return
        self._pending_restart = False
        api_key = self.key_var.get().strip()
        if not api_key:
            self._append("[hata] API anahtarı girin (Ayarlar veya https://aistudio.google.com/apikey)\n")
            self._open_settings()
            if self.status.cget("text") not in ("Hata", "Error"):
                self._set_status("Durdu", C.dim)
            return
        idx = self.in_box.current()
        if idx < 0 or idx >= len(self.inputs):
            self._append("[hata] Geçerli giriş aygıtı seçin.\n")
            if self.status.cget("text") not in ("Hata", "Error"):
                self._set_status("Durdu", C.dim)
            return
        source = self.inputs[idx]
        speaker = self._selected_speaker()
        try:
            save_api_key(api_key)
        except OSError as e:
            self._append(f"[uyarı] API anahtarı diske güvenli kaydedilemedi: {e}\n")
        src, dst = source_code(self.src_var.get()), LANGS[self.dst_var.get()]
        if not preserve_transcript:
            # Geçmişi silme; yeni oturum paragraf olarak aşağıdan devam etsin.
            for widget in (self.heard, self.trans):
                if widget.get("1.0", "end-1c").strip():
                    widget.insert(tk.END, "\n", ("body", "ltr"))
                    widget.see(tk.END)
            if getattr(self, "_timeline_start_time", None) is None:
                self._timeline_start_time = time.time()
        else:
            if getattr(self, "_timeline_start_time", None) is None:
                self._timeline_start_time = time.time()
        self._stopping.clear()
        self.session_start_time = time.time()
        current_session_id = self._session_id
        self._loop_kwargs = {
            "src": src,
            "dst": dst,
            "source_mic": source,
            "api_key": api_key,
            "output_speaker": speaker,
            "on_text": self.log_queue.put,
            "console_input": False,
        }
        self.loop_obj = SystemAudioLoop(**self._loop_kwargs)
        dest = speaker.name if speaker is not None else NONE_OUTPUT
        src_disp = "auto" if src is None else src
        self._append(f"[bilgi] {source.name} -> {dest} ({src_disp}>{dst})\n")
        self.worker = threading.Thread(target=self._run, args=(current_session_id,), daemon=True)
        self.worker.start()
        self._set_running(True)
        self._set_status("Bağlanıyor", C.warn)
    def _run(self, session_id: int | None = None):
        if session_id is None:
            session_id = getattr(self, "_session_id", 0)
        retries = 0
        max_retries = 3
        while not self._stopping.is_set():
            try:
                asyncio.run(self.loop_obj.run())
                break
            except asyncio.CancelledError:
                break
            except BaseException as e:
                if self._stopping.is_set():
                    break
                root_err = e
                if hasattr(e, "exceptions") and getattr(e, "exceptions"):
                    root_err = getattr(e, "exceptions")[0]
                if isinstance(root_err, asyncio.CancelledError):
                    break
                log_exception(root_err, "Worker loop error")
                self.log_queue.put(f"\n[hata] {format_user_error(root_err)}\n")
                if not _is_retryable_error(root_err):
                    self.log_queue.put(("status", "Hata", C.err))
                    self.log_queue.put("[hata] Bağlantı kurulamadı.\n")
                    break
                retries += 1
                if retries <= max_retries:
                    self.log_queue.put(("status", f"Yeniden bağlanılıyor ({retries}/{max_retries})", C.warn))
                    self.log_queue.put(f"[bilgi] Yeniden bağlanılıyor ({retries}/{max_retries})...\n")
                    if self._stopping.wait(2) or self._stopping.is_set():
                        break
                    if hasattr(self, "_loop_kwargs") and not self._stopping.is_set():
                        self.loop_obj = SystemAudioLoop(**self._loop_kwargs)
                else:
                    self.log_queue.put(("status", "Hata", C.err))
                    self.log_queue.put("[hata] Bağlantı kurulamadı.\n")
                    break
        self.log_queue.put(("__stopped__", session_id))

    def stop(self, *args, cancel_restart: bool = True):
        if cancel_restart:
            self._pending_restart = False
        if getattr(self, "_restart_timer", None) is not None:
            try:
                self.after_cancel(self._restart_timer)
            except Exception:
                pass
            self._restart_timer = None
        self._stopping.set()
        self.session_start_time = None
        if hasattr(self, "timer_lbl"):
            self.timer_lbl.configure(text="")
        if self.loop_obj is not None:
            self.loop_obj.request_stop()
        if getattr(self, "_pending_restart", False):
            self._set_status("Yeniden başlatılıyor", C.warn)
        else:
            self._set_status("Durduruluyor", C.warn)
    def _open_about(self):
        if self._about is not None and self._about.winfo_exists():
            self._about.deiconify()
            self._about.lift()
            self._about.focus_set()
            return
        pop = tk.Toplevel(self)
        self._about = pop
        pop.title("Hakkında")
        pop.configure(bg=C.panel)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_about)
        for key in ("<Escape>", "<Return>", "<KP_Enter>", "<space>"):
            pop.bind(key, lambda _e: self._close_about())

        main = tk.Frame(pop, bg=C.panel, padx=20, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(main, bg=C.panel)
        header.pack(fill=tk.X)

        if ICON_PNG.is_file():
            try:
                raw = tk.PhotoImage(file=str(ICON_PNG))
                logo_img = raw.subsample(21, 21)
                logo = tk.Label(header, image=logo_img, bg=C.panel)
                logo.image = logo_img
                logo.pack(side=tk.LEFT, padx=(0, 14), anchor="n")
            except Exception:
                pass

        info = tk.Frame(header, bg=C.panel)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_row = tk.Frame(info, bg=C.panel)
        title_row.pack(anchor="w")

        self.about_name = tk.Label(
            title_row,
            text=APP_TITLE,
            font=(self.font_brand[0], 12, "bold"),
            fg=C.text,
            bg=C.panel,
        )
        self.about_name.pack(side=tk.LEFT)

        self.about_version = tk.Label(
            title_row,
            text=f"v{__version__}",
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_version.pack(side=tk.LEFT, padx=(6, 0))

        desc = tk.Label(
            info,
            text="Canlı sistem-sesi çevirisi",
            font=self.font_ui,
            fg=C.muted,
            bg=C.panel,
        )
        desc.pack(anchor="w", pady=(3, 0))
        self.about_update_status = tk.Label(
            info,
            text="Güncellemeler otomatik denetlenir" if can_self_update() else "Kaynak kod modu",
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_update_status.pack(anchor="w", pady=(5, 0))

        div = tk.Frame(main, bg=C.line, height=1)
        div.pack(fill=tk.X, pady=(14, 12))

        bottom = tk.Frame(main, bg=C.panel)
        bottom.pack(fill=tk.X)

        self.about_author = tk.Label(
            bottom,
            text=APP_AUTHOR,
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_author.pack(side=tk.LEFT)
        self.about_update_btn = tk.Button(
            bottom,
            text="Güncellemeleri denetle",
            command=lambda: self._check_for_updates(manual=True),
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        self.about_update_btn.pack(side=tk.LEFT, padx=(12, 0))

        btn_wrap = tk.Frame(bottom, bg=C.line, bd=0, highlightthickness=0)
        btn_wrap.pack(side=tk.RIGHT)
        btn = tk.Button(
            btn_wrap,
            text="Tamam",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=3,
            cursor="hand2",
            takefocus=0,
            command=self._close_about,
        )
        btn.pack(padx=1, pady=1)
        btn.bind("<Enter>", lambda _e: btn.configure(bg=C.hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=C.panel))

        pop.update_idletasks()
        w = max(290, pop.winfo_reqwidth())
        h = pop.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        pop.geometry(f"{w}x{h}+{x}+{y}")
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        pop.focus_set()
    def _close_about(self) -> None:
        if self._about is None:
            return
        try:
            self._about.grab_release()
        except tk.TclError:
            pass
        self._about.destroy()
        self._about = None

    def _open_settings(self):
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.deiconify()
            self._settings.lift()
            self._settings.focus_set()
            return
        pop = tk.Toplevel(self)
        self._settings = pop
        pop.title("Ayarlar")
        pop.configure(bg=C.panel)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_settings)
        pop.bind("<Escape>", lambda _e: self._close_settings())

        main = tk.Frame(pop, bg=C.panel, padx=20, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        title_lbl = tk.Label(
            main, text="Ayarlar", font=(self.font_brand[0], 12, "bold"), fg=C.text, bg=C.panel
        )
        title_lbl.pack(anchor="w")

        sep = tk.Frame(main, bg=C.line, height=1)
        sep.pack(fill=tk.X, pady=(8, 14))

        sec_h = tk.Frame(main, bg=C.panel)
        sec_h.pack(fill=tk.X)
        tk.Label(
            sec_h,
            text="Gemini API Anahtarı",
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
        ).pack(side=tk.LEFT)

        link_lbl = tk.Label(
            sec_h, text="Anahtar Al ↗", font=self.font_ui, fg=C.dim, bg=C.panel, cursor="hand2"
        )
        link_lbl.pack(side=tk.RIGHT)
        link_lbl.bind("<Button-1>", lambda _e: webbrowser.open("https://aistudio.google.com/apikey"))
        link_lbl.bind("<Enter>", lambda _e: link_lbl.configure(fg=C.text))
        link_lbl.bind("<Leave>", lambda _e: link_lbl.configure(fg=C.dim))

        desc_lbl = tk.Label(
            main,
            text="Canlı ses çevirisi için Gemini Live erişimine sahip bir API anahtarı gereklidir.",
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
            anchor="w",
            justify="left",
        )
        desc_lbl.pack(anchor="w", pady=(4, 8))

        self.key_edge = tk.Frame(main, bg=C.line, bd=0, highlightthickness=0)
        self.key_edge.pack(fill=tk.X)

        self.key_entry = tk.Entry(
            self.key_edge,
            textvariable=self.key_var,
            show="•",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            insertbackground=C.text,
            disabledbackground=C.rail,
            disabledforeground=C.dim,
            relief="flat",
            highlightthickness=0,
            bd=0,
        )
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(1, 0), pady=1, ipady=4)
        self.key_entry.bind("<Return>", lambda _e: self.save_key())

        self.mask_btn = IconButton(self.key_edge, "eye", self._toggle_key_mask, bg=C.panel)
        self.mask_btn.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0, 1))

        running = self.worker is not None and self.worker.is_alive()
        if running:
            self.key_entry.configure(state=tk.DISABLED)

        self._settings_status = tk.Label(
            main, text="", font=self.font_ui, fg=C.dim, bg=C.panel, anchor="w"
        )
        self._settings_status.pack(anchor="w", pady=(6, 0))

        btn_row = tk.Frame(main, bg=C.panel)
        btn_row.pack(fill=tk.X, pady=(14, 0))

        test_wrap = tk.Frame(btn_row, bg=C.line, bd=0, highlightthickness=0)
        test_wrap.pack(side=tk.LEFT)
        self.test_key_btn = tk.Button(
            test_wrap,
            text="Test Et",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=3,
            cursor="hand2",
            command=self._test_api_key,
        )
        self.test_key_btn.pack(padx=1, pady=1)
        self.test_key_btn.bind("<Enter>", lambda _e: self.test_key_btn.configure(bg=C.hover))
        self.test_key_btn.bind("<Leave>", lambda _e: self.test_key_btn.configure(bg=C.panel))

        save_wrap = tk.Frame(btn_row, bg=C.line, bd=0, highlightthickness=0)
        save_wrap.pack(side=tk.LEFT, padx=(8, 0))
        self.save_key_btn = tk.Button(
            save_wrap,
            text="Kaydet",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=3,
            cursor="hand2",
            command=self.save_key,
        )
        self.save_key_btn.pack(padx=1, pady=1)
        self.save_key_btn.bind("<Enter>", lambda _e: self.save_key_btn.configure(bg=C.hover))
        self.save_key_btn.bind("<Leave>", lambda _e: self.save_key_btn.configure(bg=C.panel))

        close_wrap = tk.Frame(btn_row, bg=C.line, bd=0, highlightthickness=0)
        close_wrap.pack(side=tk.RIGHT)
        self._settings_close_btn = tk.Button(
            close_wrap,
            text="Kapat",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=3,
            cursor="hand2",
            command=self._close_settings,
        )
        self._settings_close_btn.pack(padx=1, pady=1)
        self._settings_close_btn.bind("<Enter>", lambda _e: self._settings_close_btn.configure(bg=C.hover))
        self._settings_close_btn.bind("<Leave>", lambda _e: self._settings_close_btn.configure(bg=C.panel))

        pop.update_idletasks()
        w = max(420, pop.winfo_reqwidth())
        h = pop.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        pop.geometry(f"{w}x{h}+{x}+{y}")
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        self.key_entry.focus_set()

    def _close_settings(self) -> None:
        if self._settings is None:
            return
        try:
            self._settings.grab_release()
        except tk.TclError:
            pass
        self._settings.destroy()
        self._settings = None
        self.key_entry = None
        self.mask_btn = None
        self.key_edge = None
        self._settings_status = None
        self._settings_close_btn = None

    def _fit_overlay(self) -> None:
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        pop.update_idletasks()
        width = pop.winfo_width()
        height = max(56, pop.winfo_reqheight())
        x = pop.winfo_x()
        bottom = pop.winfo_y() + pop.winfo_height()
        y = bottom - height
        pop.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def toggle_overlay(self) -> None:
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.destroy()
            self._overlay = None
            self.overlay_btn.set_accent(False)
            return
        self._build_overlay()

    def _build_overlay(self, geom: str | None = None) -> None:
        pop = tk.Toplevel(self)
        self._overlay = pop
        pop.title("Altyazı")
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
            pop.attributes("-alpha", getattr(self, "overlay_alpha", 0.92))
        except tk.TclError:
            pass
        pop.configure(bg=C.overlay_bg)
        self.overlay_btn.set_accent(True)

        def start_move(e):
            pop._drag_x = e.x_root - pop.winfo_x()
            pop._drag_y = e.y_root - pop.winfo_y()

        def do_move(e):
            x = e.x_root - pop._drag_x
            y = e.y_root - pop._drag_y
            pop.geometry(f"+{x}+{y}")

        wrap = tk.Frame(pop, bg=C.overlay_bg, highlightthickness=1, highlightbackground=C.line, bd=0)
        wrap.pack(fill=tk.BOTH, expand=True)
        self._overlay_wrap = wrap

        hdr = tk.Frame(wrap, bg=C.overlay_bg)
        hdr.pack(fill=tk.X, padx=6, pady=(3, 0))
        self._overlay_hdr = hdr

        close_btn = IconButton(hdr, "close", self.toggle_overlay, bg=C.overlay_bg)
        close_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self._overlay_close = close_btn

        thru_kind = "target" if getattr(self, "overlay_click_through", False) else "cursor"
        self._overlay_thru_btn = IconButton(hdr, thru_kind, self._toggle_overlay_click_through, bg=C.overlay_bg)
        self._overlay_thru_btn.pack(side=tk.RIGHT, padx=(4, 0))

        fplus = tk.Label(hdr, text="A+", font=self.font_ui, fg=C.dim, bg=C.overlay_bg, cursor="hand2")
        fplus.pack(side=tk.RIGHT, padx=(4, 0))
        fplus.bind("<Button-1>", lambda _e: self._adjust_overlay_font(1))
        self._overlay_fplus = fplus

        fminus = tk.Label(hdr, text="A-", font=self.font_ui, fg=C.dim, bg=C.overlay_bg, cursor="hand2")
        fminus.pack(side=tk.RIGHT, padx=(4, 0))
        fminus.bind("<Button-1>", lambda _e: self._adjust_overlay_font(-1))
        self._overlay_fminus = fminus
        cur_text = self._overlay_tail(self.trans.get("1.0", "end")) or "..."

        self.overlay_label = tk.Label(
            wrap,
            text=cur_text,
            font=(self.font_brand[0], getattr(self, "overlay_font_size", 13), "bold"),
            fg=C.text,
            bg=C.overlay_bg,
            wraplength=520,
            justify=tk.CENTER,
            padx=16,
            pady=8,
        )
        self.overlay_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Sağ kenar: genişlik tutamacı
        grip = tk.Label(wrap, text="⋮⋮", font=(self.font_ui[0], 7), fg=C.dim, bg=C.overlay_bg, cursor="size_we", padx=2)
        grip.pack(side=tk.RIGHT, fill=tk.Y)
        self._overlay_grip = grip

        def start_resize(e):
            pop._resize_x = e.x_root
            pop._resize_w = pop.winfo_width()

        def do_resize(e):
            dx = e.x_root - pop._resize_x
            new_w = max(220, min(self.winfo_screenwidth() - 40, pop._resize_w + dx))
            if new_w != pop.winfo_width():
                pop.geometry(f"{new_w}x{pop.winfo_height()}")
                self.overlay_label.configure(wraplength=max(120, new_w - 44))
                self._fit_overlay()

        grip.bind("<ButtonPress-1>", start_resize)
        grip.bind("<B1-Motion>", do_resize)
        grip.bind("<ButtonRelease-1>", lambda _e: self._save_user_prefs())

        for w in (pop, wrap, self.overlay_label):
            w.bind("<ButtonPress-1>", start_move)
            w.bind("<B1-Motion>", do_move)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 580, 56
        if geom:
            try:
                pop.geometry(geom)
            except tk.TclError:
                pop.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 100}")
        elif getattr(self, "_cfg", None) and self._cfg.overlay_geom:
            try:
                pop.geometry(self._cfg.overlay_geom)
            except tk.TclError:
                pop.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 100}")
        else:
            pop.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh - h - 100}")
        pop.update_idletasks()
        self.overlay_label.configure(wraplength=max(120, pop.winfo_width() - 44))
        self._apply_overlay_click_through()
        for w_widget in (pop, wrap, self.overlay_label):
            w_widget.bind("<ButtonRelease-1>", lambda _e: self._save_user_prefs(), add="+")
        self._fit_overlay()
    def _on_close(self):
        if getattr(self, "_pump_after_id", None) is not None:
            try:
                self.after_cancel(self._pump_after_id)
            except Exception:
                pass
            self._pump_after_id = None
        self.stop()
        self._close_about()
        self._close_settings()
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.destroy()
            self._overlay = None
        for box in (self.in_box, self.out_box, self.src_box, self.dst_box):
            box._close()
        if getattr(self, "_save_prefs_timer", None) is not None:
            try:
                self.after_cancel(self._save_prefs_timer)
            except Exception:
                pass
            self._do_save_user_prefs()
        if self.worker is not None and self.worker.is_alive():
            try:
                self.withdraw()
            except tk.TclError:
                pass
            self.worker.join(timeout=1.0)
        self.destroy()

    def destroy(self):
        if getattr(self, "_pump_after_id", None) is not None:
            try:
                self.after_cancel(self._pump_after_id)
            except Exception:
                pass
            self._pump_after_id = None
        super().destroy()
