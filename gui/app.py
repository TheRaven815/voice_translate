"""Ana pencere."""

from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import messagebox

from applications import application_inputs, format_application_name
from process_audio import process_audio_supported
from config import (
    load as load_config,
    parse_glossary,
    reset as reset_config,
    resolve_api_key,
    save_api_key,
    save_preferences,
)
from devices import (
    NONE_OUTPUT,
    all_inputs,
    all_outputs,
    application_input_prefix,
    default_speaker,
    device_key,
    display_input_label,
    find_input_by_label,
    find_output_by_label,
    is_application_input_label,
    is_none_output,
    none_output_label,
    pick_loopback,
)
from export import (
    TranscriptItem,
    export_bilingual_srt,
    export_jsonl,
    export_srt,
    export_txt,
    export_vtt,
)
from languages import (
    AUTO_SRC,
    LANGS,
    canonical_name,
    display_language_names,
    display_name,
    display_source_names,
    is_rtl,
    lang_code_to_name,
    source_code,
    src_code_to_name,
)
from i18n import get_ui_lang, set_ui_lang, t
from hotkeys import GlobalHotkeys
from logger import append_history, get_logger, log_exception, setup_logging
from loop import SystemAudioLoop, open_capture_recorder, validate_live_api_key
from reconnect import (
    _PERMANENT_LIVE_ERRORS,
    _is_planned_renewal,
    _is_retryable_error,
    _live_error_code,
    _worker_error,
    clone_loop_for_retry,
    format_user_error,
    run_with_retries,
)
from source_mute import DUB_BACKGROUND, DubPlan, SourceDub, source_capture_gain
from meta import APP_TITLE, __version__
from notifications import WindowsNotifier
from updater import UpdateInfo, can_self_update, consume_update_error
from .dialogs import DialogsMixin
from .overlay import OverlayMixin
from .preview import _InputPreviewMonitor
from .settings_dialog import SettingsDialogMixin
from .theme import C, apply_icon, dark_titlebar, pick_fonts, prepare_app_id
from .widgets import CheckToggle, IconButton, LevelSlider, Select, ThemeSwitch, TranscriptSearchBar
from .win32 import (
    SingleInstanceMixin,
    _GEOMETRY_RE,
    _clamp_to_bounds,
    _monitor_work_area,
    _parse_geometry,
    _virtual_screen_bounds,
    _win32_gui_apis,
    extract_exe_icon_png,
)


class App(OverlayMixin, SettingsDialogMixin, DialogsMixin, SingleInstanceMixin, tk.Tk):
    MAX_LOG_LINES = 500
    LOG_TRIM_BATCH = 100
    MAX_PANE_LINES = 2000
    PANE_TRIM_BATCH = 200
    MAX_TRANSCRIPT_ITEMS = 5000
    TRANSCRIPT_SPILL_BATCH = 1000

    @staticmethod
    def _deps():
        return sys.modules[__name__]

    def __init__(self, activate_slot=None):
        prepare_app_id()
        cfg = load_config()
        self._cfg = cfg
        self._input_application_path = getattr(cfg, "input_application", "")
        self._theme = getattr(cfg, "theme", "dark") or "dark"
        C.apply_theme(self._theme)
        set_ui_lang(getattr(cfg, "ui_lang", "tr"))
        super().__init__()
        self._activate_slot = activate_slot
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
        self._application_picker: tk.Toplevel | None = None
        self._application_picker_sources: list = []
        self._application_list: tk.Listbox | None = None
        self._application_select_btn: tk.Button | None = None
        self._applications: list = []
        self._last_input_label = ""
        self._handling_input_selection = False
        self.key_var: tk.StringVar = tk.StringVar(value=resolve_api_key())
        self.key_entry: tk.Entry | None = None
        self.mask_btn: tk.Label | None = None
        self.key_edge: tk.Frame | None = None
        self._settings_status: tk.Label | None = None
        self._settings_close_btn: tk.Button | None = None
        self._update_info: UpdateInfo | None = None
        self._update_check_running = False
        self._update_installing = False
        self._update_cancel: threading.Event | None = None
        self._download_fraction: float | None = None
        self._hotkeys: GlobalHotkeys | None = None
        self._hotkeys_suspended = False
        self._paused = False
        self.translation_muted = False
        self.mute_shortcut = getattr(self._cfg, "mute_shortcut", "Ctrl+Shift+M")
        self.start_stop_shortcut = getattr(self._cfg, "start_stop_shortcut", "Ctrl+Shift+Space")
        self.pause_shortcut = getattr(self._cfg, "pause_shortcut", "") or ""
        self.push_to_talk = bool(getattr(self._cfg, "push_to_talk", False))
        self._mute_shortcut_var: tk.StringVar | None = None
        self._start_stop_shortcut_var: tk.StringVar | None = None
        self._pause_shortcut_var: tk.StringVar | None = None
        self._mute_shortcut_entry: tk.Entry | None = None
        self._start_stop_shortcut_entry: tk.Entry | None = None
        self._pause_shortcut_entry: tk.Entry | None = None
        self._push_to_talk_var: tk.BooleanVar | None = None
        self._push_to_talk_toggle: CheckToggle | None = None
        self._status_raw = "Hazır"
        self._status_color = C.dim
        self._ui_lang_btns: dict[str, tk.Button] = {}
        self._settings_refs: dict[str, tk.Widget] = {}
        self._reset_btn: tk.Button | None = None
        self._save_status: tk.Label | None = None
        self._save_status_key: str | None = None
        self._overlay: tk.Toplevel | None = None
        self._overlay_click_style: int | None = None
        self._overlay_pointer_after_id: str | None = None
        self._overlay_controls_visible = False
        self._overlay_controls_interactive = False
        self._rail_seps: list[tk.Frame] = []
        self.always_on_top = getattr(self._cfg, "always_on_top", False)
        self.overlay_font_size = getattr(self._cfg, "overlay_font_size", 13)
        self.overlay_alpha = getattr(self._cfg, "overlay_alpha", 0.92)
        self.overlay_click_through = getattr(self._cfg, "overlay_click_through", False)
        self.dub_mute_source = bool(getattr(self._cfg, "dub_mute_source", False))
        self.dub_background = bool(getattr(self._cfg, "dub_background", False))
        if self.dub_mute_source and self.dub_background:
            self.dub_background = False
        self.dub_background_gain = self._clamp_bed_gain(
            getattr(self._cfg, "dub_background_gain", DUB_BACKGROUND)
        )
        self.dub_ducking = bool(getattr(self._cfg, "dub_ducking", True))
        self.translation_volume = self._clamp_volume(
            getattr(self._cfg, "translation_volume", 1.0)
        )
        self.glossary = str(getattr(self._cfg, "glossary", "") or "")
        self.save_history = bool(getattr(self._cfg, "save_history", True))
        self._source_dub = SourceDub()
        self._dub_logged: tuple | None = None
        self._dub_was_active = False
        self._dub_speech_active = False
        self._dub_var: tk.BooleanVar | None = None
        self._dub_toggle: CheckToggle | None = None
        self._dub_bg_var: tk.BooleanVar | None = None
        self._dub_bg_toggle: CheckToggle | None = None
        self._dub_ducking_var: tk.BooleanVar | None = None
        self._dub_ducking_toggle: CheckToggle | None = None
        self._dub_bg_gain_var: tk.IntVar | None = None
        self._dub_bg_scale: LevelSlider | None = None
        self._dub_bg_gain_lbl: tk.Label | None = None
        self._dub_bg_pct_lbl: tk.Label | None = None
        self._dub_gain_timer: str | None = None
        self._dub_gain_ui = False
        self._volume_var: tk.IntVar | None = None
        self._volume_scale: LevelSlider | None = None
        self._volume_pct_lbl: tk.Label | None = None
        self._volume_timer: str | None = None
        self._volume_ui = False
        self._overlay_alpha_var: tk.IntVar | None = None
        self._overlay_alpha_scale: LevelSlider | None = None
        self._overlay_alpha_pct_lbl: tk.Label | None = None
        self._overlay_alpha_timer: str | None = None
        self._overlay_alpha_ui = False
        self._glossary_edge: tk.Frame | None = None
        self._glossary_text: tk.Text | None = None
        self._save_history_var: tk.BooleanVar | None = None
        self._save_history_toggle: CheckToggle | None = None
        self._view_history_btn: tk.Button | None = None
        self._clear_history_btn: tk.Button | None = None
        self._history_status: tk.Label | None = None
        self._history_win: tk.Toplevel | None = None
        self._history_text: tk.Text | None = None
        self._history_find_bar: TranscriptSearchBar | None = None
        self._find_bar: TranscriptSearchBar | None = None
        self._jump_pills: dict[tk.Text, tk.Button] = {}
        self._settings_active_tab = "general"
        self._settings_tab_btns: dict[str, tk.Button] = {}
        self._settings_tab_frames: dict[str, tk.Frame] = {}
        self._overlay_font_cache: tuple[tuple, tkfont.Font] | None = None
        self._overlay_text = ""
        self.transcript_items: list[TranscriptItem] = []
        self._transcript_spill_path: Path | None = None
        self.session_start_time: float | None = None
        self._timeline_start_time: float | None = None
        self._curr_heard_buf = ""
        self._curr_trans_buf = ""
        self._curr_heard_start: float | None = None
        self._curr_trans_start: float | None = None
        self._last_heard_completed = ""
        self._history_write_q: queue.Queue = queue.Queue()
        self._history_writer_started = False
        # Başlatmadan önce girişten VU besleyen bağımsız önizleme izleyicisi.
        # Oturum çalışırken durdurulur; yakalama/çeviri hattına dokunmaz.
        self._preview = _InputPreviewMonitor()
        self._preview.start()
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
        self._hotkeys = GlobalHotkeys(
            lambda action: self.log_queue.put(("hotkey", action)),
            push_to_talk=self.push_to_talk,
        )
        hotkey_error = self._register_global_hotkeys()
        if hotkey_error and sys.platform == "win32":
            self._append(f"[uyarı] Genel kısayollar etkinleştirilemedi: {hotkey_error}\n")
        self.refresh_devices(async_scan=True)
        dark_titlebar(self, dark=(self._theme != "light"))
        self._pump_after_id = self.after(120, self._pump_log)
        update_error = consume_update_error()
        if update_error:
            self._append(f"[hata] {update_error}\n")
            self.after(250, lambda msg=update_error: messagebox.showerror(t("update_title_short"), msg, parent=self))
        if can_self_update():
            self.after(1500, self._check_for_updates)

    def _build(self):
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self.rail = tk.Frame(self, bg=C.rail, width=296, bd=0, highlightthickness=0)
        self.rail.grid(row=0, column=0, sticky="nsw")
        self.rail.grid_propagate(False)
        self.rail.columnconfigure(0, weight=1)
        self.rail.rowconfigure(1, weight=1)

        self._v_sep = tk.Frame(self, bg=C.line, width=1, bd=0, highlightthickness=0)
        self._v_sep.grid(row=0, column=1, sticky="ns")

        self.main = tk.Frame(self, bg=C.bg, bd=0, highlightthickness=0)
        self.main.grid(row=0, column=2, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.columnconfigure(1, weight=1)
        self.main.rowconfigure(2, weight=1)

        self._build_rail(self.rail)
        self._build_main(self.main)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._install_single_instance_activate()
        self.bind("<Control-Return>", lambda _e: self._toggle_start_stop())
        self.bind("<F5>", lambda _e: self._toggle_start_stop())
        self.bind("<Control-p>", lambda _e: self.toggle_pause())
        self.bind("<Control-P>", lambda _e: self.toggle_pause())
        self.bind("<Control-f>", self._toggle_find_bar)
        self.bind("<Control-F>", self._toggle_find_bar)
        self.bind("<Escape>", self._on_root_escape, add="+")
        self.bind("<Control-o>", lambda _e: self.toggle_overlay())
        self.bind("<Control-O>", lambda _e: self.toggle_overlay())
        self.bind("<F2>", lambda _e: self.toggle_overlay())
        self.bind("<Control-t>", lambda _e: self.toggle_theme())
        self.bind("<Control-T>", lambda _e: self.toggle_theme())
        self.bind("<F6>", lambda _e: self.toggle_theme())
        self.bind("<Control-comma>", lambda _e: self._open_settings())
    def _build_rail(self, rail: tk.Frame):
        self._rail_head = tk.Frame(rail, bg=C.rail)
        self._rail_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 8))

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
        self._update_chip = tk.Button(
            self._rail_title,
            text="",
            font=self.font_ui,
            fg=C.live,
            bg=C.rail,
            activeforeground=C.text,
            activebackground=C.hover,
            disabledforeground=C.muted,
            cursor="hand2",
            command=self._on_update_chip,
            relief="flat", bd=0, highlightthickness=0, padx=6, pady=0,
            takefocus=1,
        )
        # The brand determines the title row height, with or without the update button.
        self._update_chip.bind("<Return>", lambda _e: self._update_chip.invoke())
        self._update_chip.bind("<FocusIn>", lambda _e: self._update_chip.configure(bg=C.hover))
        self._update_chip.bind("<FocusOut>", lambda _e: self._update_chip.configure(bg=C.rail))

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

        # Only device/language settings scroll; session controls stay in the footer.
        self._rail_canvas = canvas = tk.Canvas(rail, bg=C.rail, bd=0, highlightthickness=0)
        canvas.grid(row=1, column=0, sticky="nsew")
        self._rail_scroll = scroll = tk.Scrollbar(
            canvas, command=canvas.yview, width=10, bg=C.hover, troughcolor=C.rail,
            activebackground=C.dim, bd=0, highlightthickness=0, relief="flat",
        )
        canvas.configure(yscrollcommand=self._sync_rail_scroll)
        self._rail_body = body = tk.Frame(canvas, bg=C.rail)
        body.columnconfigure(0, weight=1)
        body_id = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox(body_id)))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_id, width=e.width))
        self.bind("<MouseWheel>", self._on_rail_wheel, add="+")
        self.bind("<FocusIn>", self._reveal_rail_focus, add="+")

        self._rail_sep(body, 1)

        self._devices_frame = tk.Frame(body, bg=C.rail)
        self._devices_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._devices_frame.columnconfigure(0, weight=1)
        self._device_lbl = tk.Label(
            self._devices_frame, text=t("device"), font=self.font_ui, fg=C.muted, bg=C.rail
        )
        self._device_lbl.grid(row=0, column=0, sticky="w")
        self.refresh_btn = self._text_btn(
            self._devices_frame, t("refresh"), lambda: self.refresh_devices(async_scan=True)
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        self._fields_frame = tk.Frame(body, bg=C.rail)
        self._fields_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._fields_frame.columnconfigure(0, weight=1)

        self._input_lbl = tk.Label(
            self._fields_frame, text=t("input"), font=self.font_ui, fg=C.muted, bg=C.rail
        )
        self._input_lbl.grid(row=0, column=0, sticky="w")
        self.in_var = tk.StringVar()
        self.in_box = Select(self._fields_frame, textvariable=self.in_var, values=["[Sistem]"], font=self.font_ui)
        self.in_box.grid(row=1, column=0, sticky="ew", pady=(3, 4))
        self.input_hint = tk.Label(
            self._fields_frame, text="", font=self.font_ui, fg=C.muted,
            bg=C.rail, anchor="w", justify=tk.LEFT, wraplength=250,
        )
        self.input_hint.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self._fields_frame.bind(
            "<Configure>", lambda event: self.input_hint.configure(wraplength=max(100, event.width))
        )
        self._update_input_hint()

        self._output_lbl = tk.Label(
            self._fields_frame, text=t("output"), font=self.font_ui, fg=C.muted, bg=C.rail
        )
        self._output_lbl.grid(row=3, column=0, sticky="w")
        self.out_var = tk.StringVar()
        self.out_box = Select(
            self._fields_frame, textvariable=self.out_var, values=[none_output_label()],
            font=self.font_ui,
        )
        self.out_box.grid(row=4, column=0, sticky="ew", pady=(3, 0))

        self._rail_sep(body, 4)

        self._lang_h = tk.Frame(body, bg=C.rail)
        self._lang_h.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._language_lbl = tk.Label(
            self._lang_h, text=t("language"), font=self.font_ui, fg=C.muted, bg=C.rail
        )
        self._language_lbl.pack(side=tk.LEFT)

        self._langs_frame = tk.Frame(body, bg=C.rail)
        self._langs_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._langs_frame.columnconfigure(0, weight=1)
        self._langs_frame.columnconfigure(2, weight=1)

        cfg = getattr(self, "_cfg", None) or load_config()
        src_val = display_name(src_code_to_name(cfg.src_lang))
        dst_val = display_name(lang_code_to_name(cfg.dst_lang))
        self.src_var = tk.StringVar(value=src_val)
        self.src_box = Select(
            self._langs_frame, textvariable=self.src_var, values=display_source_names(),
            font=self.font_ui,
        )
        self.src_box.grid(row=0, column=0, sticky="ew")

        self.swap_btn = IconButton(
            self._langs_frame, "swap", self._swap_langs, bg=C.rail, tooltip=t("swap")
        )
        self.swap_btn.grid(row=0, column=1, padx=2)

        self.dst_var = tk.StringVar(value=dst_val)
        self.dst_box = Select(
            self._langs_frame, textvariable=self.dst_var, values=display_language_names(),
            font=self.font_ui,
        )
        self.dst_box.grid(row=0, column=2, sticky="ew")

        for var in (self.src_var, self.dst_var):
            var.trace_add("write", self._on_runtime_pref_change)
        # Aygıt değişimi oturumu öldürmez: çalışırken hot-swap yapılır,
        # boşta iken VU önizlemesi yeni cihaza geçer; seçim diske yazılır.
        self.in_var.trace_add("write", lambda *_: self._on_input_selected())
        self.out_var.trace_add("write", lambda *_: self._on_output_selected())

        self._rail_footer = tk.Frame(rail, bg=C.rail)
        self._rail_footer.grid(row=2, column=0, sticky="ew")
        self._rail_footer.columnconfigure(0, weight=1)
        self._rail_sep(self._rail_footer, 0)
        self._btns_frame = tk.Frame(self._rail_footer, bg=C.rail)
        self._btns_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 16))
        self._btns_frame.columnconfigure(0, weight=1)
        self._btns_frame.columnconfigure(1, weight=1)
        self._btns_frame.columnconfigure(2, weight=1)

        self._key_notice = tk.Label(
            self._btns_frame,
            text=t("api_key_missing"),
            font=self.font_ui,
            fg=C.warn,
            bg=C.rail,
            anchor="w",
            justify=tk.LEFT,
            wraplength=250,
            cursor="hand2",
        )
        self._key_notice.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self._key_notice.bind("<Button-1>", lambda _e: self._open_settings())
        self._key_notice.bind("<Enter>", lambda _e: self._key_notice.configure(fg=C.accent))
        self._key_notice.bind("<Leave>", lambda _e: self._key_notice.configure(fg=C.warn))

        self.start_btn = self._btn(self._btns_frame, t("start"), self.start)
        self.start_btn._edge.grid(row=1, column=0, sticky="ew", padx=(0, 3), ipady=4)
        self.pause_btn = self._btn(self._btns_frame, t("pause"), self.toggle_pause)
        self.pause_btn._edge.grid(row=1, column=1, sticky="ew", padx=3, ipady=4)
        self.stop_btn = self._btn(self._btns_frame, t("stop"), self.stop)
        self.stop_btn._edge.grid(row=1, column=2, sticky="ew", padx=(3, 0), ipady=4)
        self._sync_action_buttons(running=False)
        self._refresh_key_notice()

    def _sync_rail_scroll(self, first, last):
        self._rail_scroll.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._rail_scroll.place_forget()
        elif not self._rail_scroll.winfo_manager():
            self._rail_scroll.place(relx=1, anchor="ne", relheight=1)

    def _on_rail_wheel(self, event):
        if str(event.widget).startswith(str(self._rail_canvas)):
            steps = int(event.delta / 120)
            if steps:
                self._rail_canvas.yview_scroll(-steps, "units")
            return "break"

    def _reveal_rail_focus(self, event):
        if not str(event.widget).startswith(f"{self._rail_body}."):
            return
        canvas = self._rail_canvas
        top = event.widget.winfo_rooty() - canvas.winfo_rooty()
        height = canvas.winfo_height()
        bottom = top + event.widget.winfo_height()
        if top < 0 or bottom > height:
            offset = top if top < 0 else bottom - height
            canvas.yview_moveto((canvas.canvasy(0) + offset) / self._rail_body.winfo_height())

    def _worker_alive(self) -> bool:
        try:
            return self.worker is not None and self.worker.is_alive()
        except Exception:
            return False

    def _resolve_input_device(self):
        try:
            return find_input_by_label(getattr(self, "inputs", []), self.in_var.get())
        except Exception:
            return None

    def _visible_input_values(self, selected=None) -> list[str]:
        values = [
            display_input_label(source)
            for source in getattr(self, "inputs", [])
            if not getattr(source, "is_application", False)
        ]
        if selected is not None:
            values.append(display_input_label(selected))
        elif is_application_input_label(self.in_var.get()):
            values.append(self.in_var.get())
        if process_audio_supported():
            values.append(t("application_picker"))
        return values

    def _resolve_output_device(self):
        try:
            return find_output_by_label(getattr(self, "outputs", []), self.out_var.get())
        except Exception:
            return None

    def _sync_preview_device(self) -> None:
        """Boşta iken önizlemeyi seçili girişe bağla; çalışırken boşalt."""
        preview = getattr(self, "_preview", None)
        if preview is None:
            return
        try:
            if self._worker_alive():
                preview.set_device(None)
            else:
                preview.set_device(self._resolve_input_device())
        except Exception:
            pass

    def _update_input_hint(self) -> None:
        if not process_audio_supported():
            key = "application_unsupported"
        elif is_application_input_label(self.in_var.get()):
            key = "application_input_hint" if self._resolve_input_device() else "application_unavailable"
        else:
            key = "application_picker_hint"
        self.input_hint.configure(text=t(key))

    def _on_input_selected(self) -> None:
        if getattr(self, "_translating_ui", False):
            return
        if self._handling_input_selection:
            return
        if self.in_var.get() == t("application_picker"):
            self._handling_input_selection = True
            self.in_var.set(self._last_input_label)
            self._handling_input_selection = False
            self.after_idle(self._open_application_picker)
            return
        dev = self._resolve_input_device()
        if dev is not None:
            self._last_input_label = self.in_var.get()
            if getattr(dev, "is_application", False):
                self._input_application_path = getattr(dev, "executable", "")
                self.in_box["values"] = self._visible_input_values(dev)
            else:
                self._input_application_path = ""
                self.in_box["values"] = self._visible_input_values()
        elif is_application_input_label(self.in_var.get()):
            self._last_input_label = self.in_var.get()
        else:
            self._last_input_label = self.in_var.get()
            self._input_application_path = ""
        self._update_input_hint()
        self._save_user_prefs()
        self._sync_source_dub()
        if dev is None:
            self._sync_preview_device()
            return
        loop_obj = getattr(self, "loop_obj", None)
        if self._worker_alive() and loop_obj is not None:
            loop_obj.swap_input(dev)
            if hasattr(self, "_loop_kwargs"):
                self._loop_kwargs["source_mic"] = dev
        elif getattr(self, "_preview", None) is not None:
            self._preview.set_device(dev)

    def _on_output_selected(self) -> None:
        if getattr(self, "_translating_ui", False):
            return
        try:
            self._save_user_prefs()
        except Exception:
            pass
        try:
            loop_obj = getattr(self, "loop_obj", None)
            if self._worker_alive() and loop_obj is not None:
                # None (Hiçbiri) dahildir: oynatma hattı text-only'e geçer.
                try:
                    loop_obj.swap_output(self._resolve_output_device())
                    if hasattr(self, "_loop_kwargs"):
                        self._loop_kwargs["output_speaker"] = self._resolve_output_device()
                except Exception:
                    pass
            self._sync_source_dub()
        except Exception:
            pass

    def _build_main(self, main: tk.Frame):
        self._find_bar = TranscriptSearchBar(
            main,
            get_targets=lambda: (getattr(self, "heard", None), getattr(self, "trans", None)),
            font=self.font_ui,
            on_show=lambda: self._find_bar.grid() if self._find_bar is not None else None,
            on_hide=self._on_main_find_hide,
            label_text=t("find_placeholder"),
            close_tip=t("close"),
        )
        self._find_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._find_bar.grid_remove()

        self.heard_h = tk.Frame(main, bg=C.bg)
        self.heard_h.grid(row=1, column=0, sticky="ew", padx=(16, 8), pady=(12, 6))
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
        self.trans_h.grid(row=1, column=1, sticky="ew", padx=(16, 16), pady=(12, 6))
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
        self.heard_wrap.grid(row=2, column=0, sticky="nsew")
        self.trans_wrap.grid(row=2, column=1, sticky="nsew")
        for wrap in (self.heard_wrap, self.trans_wrap):
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)

        self._main_v_sep = tk.Frame(main, bg=C.line, width=1, bd=0, highlightthickness=0)
        self._main_v_sep.grid(row=1, column=0, rowspan=2, sticky="nse", pady=(12, 0))

        self.heard = self._pane(self.heard_wrap)
        self.trans = self._pane(self.trans_wrap)
        self.heard_jump_btn = self._jump_pills[self.heard]
        self.trans_jump_btn = self._jump_pills[self.trans]

        self._main_h_sep = tk.Frame(main, bg=C.line, height=1, bd=0, highlightthickness=0)
        self._main_h_sep.grid(row=3, column=0, columnspan=2, sticky="ew")

        self.log_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        self.log_wrap.grid(row=4, column=0, columnspan=2, sticky="ew")
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
        text._unmapped_pinned = True
        text.configure(yscrollcommand=lambda first, last, w=text: self._on_pane_yscroll(w, first, last))
        text.bind("<Configure>", lambda event, w=text: self._on_pane_configure(w, event))
        text.tag_configure("body", foreground=C.text)
        text.tag_configure("rtl", justify="right")
        text.tag_configure("ltr", justify="left")
        TranscriptSearchBar.style_text_tags(text)
        self._lock_text(text)
        self._bind_zoom(text)

        pill_edge = tk.Frame(parent, bg=C.accent, bd=0, highlightthickness=0)
        pill_btn = tk.Button(
            pill_edge,
            text=t("jump_to_live"),
            command=lambda w=text: self._jump_to_live(w),
            font=self.font_ui,
            bg=C.panel,
            fg=C.accent,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=3,
            cursor="hand2",
            takefocus=0,
        )
        pill_btn.pack(padx=1, pady=1)
        pill_btn.bind("<Enter>", lambda _e, b=pill_btn: b.configure(bg=C.hover, fg=C.text))
        pill_btn.bind("<Leave>", lambda _e, b=pill_btn: b.configure(bg=C.panel, fg=C.accent))
        pill_btn._edge = pill_edge
        self._jump_pills[text] = pill_btn
        return text

    def _toggle_find_bar(self, _event=None):
        if self._find_bar is None:
            return None
        return self._find_bar.toggle()

    def _on_main_find_hide(self) -> None:
        if self._find_bar is not None and self._find_bar.winfo_exists():
            self._find_bar.grid_remove()
            try:
                self.focus_set()
            except tk.TclError:
                pass

    def _on_root_escape(self, _event=None):
        if Select._open is not None:
            return None
        if self._find_bar is not None and self._find_bar.is_open:
            return self._find_bar.close()
        return None

    @staticmethod
    def _is_pane_pinned(widget: tk.Text) -> bool:
        try:
            if widget.winfo_height() <= 1:
                return bool(getattr(widget, "_unmapped_pinned", True))
            return float(widget.yview()[1]) >= 0.98
        except (tk.TclError, IndexError, TypeError, ValueError):
            return True

    def _on_pane_configure(self, widget: tk.Text, event) -> None:
        if getattr(event, "height", 0) > 1 and getattr(widget, "_unmapped_pinned", False):
            widget._unmapped_pinned = False
            try:
                widget.see(tk.END)
            except tk.TclError:
                pass

    def _on_pane_yscroll(self, widget: tk.Text, _first, last) -> None:
        try:
            if float(last) >= 0.98:
                self._hide_jump_pill(widget)
        except (TypeError, ValueError):
            pass

    def _show_jump_pill(self, widget: tk.Text) -> None:
        pill = self._jump_pills.get(widget)
        if pill is None:
            return
        edge = getattr(pill, "_edge", None)
        if edge is not None and edge.winfo_exists() and not edge.place_info():
            edge.place(relx=1.0, rely=1.0, x=-14, y=-10, anchor="se")
            edge.lift()

    def _hide_jump_pill(self, widget: tk.Text) -> None:
        pill = self._jump_pills.get(widget)
        if pill is None:
            return
        edge = getattr(pill, "_edge", None)
        if edge is not None and edge.winfo_exists() and edge.place_info():
            edge.place_forget()

    def _is_jump_pill_visible(self, widget: tk.Text) -> bool:
        pill = self._jump_pills.get(widget)
        if pill is None:
            return False
        edge = getattr(pill, "_edge", None)
        return bool(edge is not None and edge.winfo_exists() and edge.place_info())

    def _jump_to_live(self, widget: tk.Text) -> None:
        try:
            widget.see(tk.END)
        except tk.TclError:
            pass
        self._hide_jump_pill(widget)

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
            padx=8,
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
            "Dinleniyor": "listening",
            "Duraklatıldı": "paused",
            "Bağlanıyor": "connecting",
            "Durdu": "stopped",
            "Durduruluyor": "stopping",
            "Yeniden başlatılıyor": "restarting",
            "Hata": "error",
            "Güncelleme denetleniyor": "checking_updates",
            "Güncelleme indiriliyor": "downloading_update",
            "Güncelleme kuruluyor": "installing_update",
        }
        key = status_map.get(text)
        self._status_raw = text
        self._status_color = color
        if key:
            translated = t(key, text)
        elif text.startswith("Çalışıyor (") and text.endswith(" ms)"):
            ms_part = text[len("Çalışıyor ("):-len(" ms)")]
            translated = t("running_latency").format(ms=ms_part)
        elif text.startswith("Yeniden bağlanılıyor (") and text.endswith(")"):
            inner = text[len("Yeniden bağlanılıyor ("):-1]
            if "/" in inner:
                n_str, max_str = inner.split("/", 1)
                translated = t("reconnecting_n").format(n=n_str, max=max_str)
            else:
                translated = text
        else:
            translated = text
        self.status.configure(text=translated)
        self._dot.itemconfigure(self._dot_id, fill=color)
    @property
    def is_paused(self) -> bool:
        return bool(getattr(self, "_paused", False))

    def _sync_action_buttons(self, running: bool) -> None:
        paused = bool(running and getattr(self, "_paused", False))
        if hasattr(self, "pause_btn") and self.pause_btn.winfo_exists():
            self.pause_btn.configure(text=t("resume" if paused else "pause"))
            self._paint(self.pause_btn, filled=paused, enabled=running)
        self._paint(self.start_btn, filled=not running, enabled=not running)
        self._paint(self.stop_btn, filled=running and not paused, enabled=running)

    def _set_running(self, running: bool) -> None:
        if not running:
            self._paused = False
        if self.key_entry is not None and self.key_entry.winfo_exists():
            self.key_entry.configure(state=tk.DISABLED if running else tk.NORMAL)
        self._sync_action_buttons(running)
        dot_color = C.warn if (running and self._paused) else (C.live if running else C.dim)
        self._dot.itemconfigure(self._dot_id, fill=dot_color)
        if not running:
            self._update_meter(0.0)

    def pause_translation(self, *, quiet_log: bool = False) -> None:
        if not self._worker_alive() or self._stopping.is_set():
            return
        if self._paused:
            return
        self._paused = True
        if self.loop_obj is not None and hasattr(self.loop_obj, "pause"):
            self.loop_obj.pause()
        self._sync_action_buttons(True)
        self._set_status("Duraklatıldı", C.warn)
        self._sync_source_dub(quiet_log=True)
        if not quiet_log:
            self._append(f"[bilgi] {t('paused_log')}\n")

    def resume_translation(self, *, quiet_log: bool = False) -> None:
        if not self._worker_alive() or self._stopping.is_set():
            return
        if not self._paused:
            return
        self._paused = False
        if self.loop_obj is not None and hasattr(self.loop_obj, "resume"):
            self.loop_obj.resume()
        self._sync_action_buttons(True)
        self._set_status("Dinleniyor", C.live)
        self._sync_source_dub(quiet_log=True)
        if not quiet_log:
            self._append(f"[bilgi] {t('resumed_log')}\n")

    def toggle_pause(self) -> None:
        if not self._worker_alive() or self._stopping.is_set():
            return
        if self._paused:
            self.resume_translation()
        else:
            self.pause_translation()

    def _swap_langs(self) -> None:
        if canonical_name(self.src_var.get()) == AUTO_SRC:
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
                    ins.extend(application_inputs())
                    outs = all_outputs()
                    self.log_queue.put(("devices_scanned", ins, outs, stopping))
                except Exception as e:
                    self.log_queue.put(("device_scan_error", str(e)))
            threading.Thread(target=_scan, daemon=True).start()
            return

        ins = all_inputs()
        ins.extend(application_inputs())
        outs = all_outputs()
        self._apply_devices(ins, outs, stopping)

    def _apply_devices(self, ins, outs, stopping: bool):
        previous_input = self._resolve_input_device()
        stopping = self._worker_alive()
        self.inputs = list(ins)
        self._applications = [source for source in self.inputs if getattr(source, "is_application", False)]
        physical_inputs = [source for source in self.inputs if not getattr(source, "is_application", False)]
        self.outputs = outs
        self.out_box["values"] = [none_output_label()] + [s.name for s in outs]

        cfg = getattr(self, "_cfg", None) or load_config()
        cur_in = self.in_var.get()
        application_path = (
            getattr(previous_input, "executable", "")
            or (self._input_application_path if not cur_in or is_application_input_label(cur_in) else "")
        )
        selected_application = None
        if application_path:
            candidates = [
                source for source in self._applications
                if os.path.normcase(source.executable) == os.path.normcase(application_path)
            ]
            selected_application = next(
                (source for source in candidates if device_key(source) == device_key(previous_input)),
                None,
            )
            if selected_application is None and len(candidates) == 1:
                selected_application = candidates[0]

        if application_path:
            label = display_input_label(selected_application) if selected_application else (
                application_input_prefix() + " " + Path(application_path).name + " — " + t("input_unavailable")
            )
            self.in_box["values"] = [display_input_label(source) for source in physical_inputs] + [label, t("application_picker")]
            self.in_var.set(label)
        else:
            self.in_box["values"] = [display_input_label(source) for source in physical_inputs]
            if process_audio_supported():
                self.in_box["values"] = [*self.in_box["values"], t("application_picker")]
            if cur_in and cur_in in self.in_box["values"] and cur_in != t("application_picker"):
                pass
            elif not stopping and cfg.input_device != t("application_picker") and (
                cfg.input_device in self.in_box["values"]
                or find_input_by_label(physical_inputs, cfg.input_device) is not None
            ):
                saved_dev = find_input_by_label(physical_inputs, cfg.input_device)
                self.in_var.set(
                    display_input_label(saved_dev) if saved_dev is not None else cfg.input_device
                )
            elif not stopping:
                loops = [source for source in physical_inputs if getattr(source, "isloopback", False)]
                default_in = None
                if loops:
                    try:
                        default_sp = default_speaker()
                        if default_sp is not None:
                            default_in = next(
                                (source for source in loops if default_sp.name in source.name or source.name in default_sp.name),
                                None,
                            )
                    except Exception:
                        pass
                    if default_in is None:
                        default_in = loops[0]
                elif physical_inputs:
                    default_in = physical_inputs[0]
                if default_in is not None:
                    self.in_var.set(display_input_label(default_in))

        if not stopping:
            cur_out = self.out_var.get()
            if cur_out and cur_out in self.out_box["values"]:
                pass
            elif cfg.output_device and is_none_output(cfg.output_device):
                self.out_var.set(none_output_label())
            elif cfg.output_device and cfg.output_device in self.out_box["values"]:
                self.out_var.set(cfg.output_device)
            else:
                try:
                    self.out_var.set(default_speaker().name)
                except Exception:
                    self.out_var.set(none_output_label())
        self._update_input_hint()
        try:
            self._sync_preview_device()
        except Exception:
            pass
    def _selected_speaker(self):
        i = self.out_box.current()
        if i <= 0:
            return None
        try:
            return self.outputs[i - 1]
        except IndexError:
            return None

    def _append(self, text: str):
        if text.startswith(("[hata]", "[error]")):
            tag = "err"
        elif text.startswith(("[bilgi]", "[info]")):
            tag = "info"
        else:
            tag = "body"
        self.log.insert(tk.END, text, (tag,))
        try:
            line_count = int(self.log.index("end-1c").split(".")[0])
            if line_count > self.MAX_LOG_LINES:
                trim = max(1, line_count - self.MAX_LOG_LINES + self.LOG_TRIM_BATCH)
                self.log.delete("1.0", f"{trim + 1}.0")
        except Exception:
            pass
        self.log.see(tk.END)

    def _enqueue_history_write(self, heard: str, trans: str, *, src: str, dst: str) -> None:
        """Konuşma geçmişini arka planda diske yazar; UI thread'ini bloklamaz."""
        if not (heard.strip() or trans.strip()):
            return
        q = getattr(self, "_history_write_q", None)
        if q is None:
            append_history(heard, trans, src=src, dst=dst)
            return
        q.put((heard, trans, src, dst))
        if not getattr(self, "_history_writer_started", False):
            self._history_writer_started = True

            def _writer():
                while True:
                    item = q.get()
                    try:
                        if item is None:
                            break
                        h_txt, t_txt, s_code, d_code = item
                        try:
                            append_history(h_txt, t_txt, src=s_code, dst=d_code)
                        except Exception:
                            pass
                    finally:
                        q.task_done()

            threading.Thread(target=_writer, name="ahenk-history", daemon=True).start()

    def _toggle_start_stop(self):
        if self.worker is not None and self.worker.is_alive():
            self.stop()
        else:
            self.start()
    def _register_global_hotkeys(self) -> str | None:
        if self._hotkeys is None:
            return None
        if hasattr(self._hotkeys, "set_push_to_talk"):
            self._hotkeys.set_push_to_talk(bool(getattr(self, "push_to_talk", False)))
        shortcuts = {
            "mute": self.mute_shortcut,
            "start_stop": self.start_stop_shortcut,
        }
        if getattr(self, "pause_shortcut", "").strip():
            shortcuts["pause"] = self.pause_shortcut
        return self._hotkeys.replace(shortcuts)

    def _handle_hotkey(self, action: str) -> None:
        if action == "mute":
            self._toggle_translation_mute()
        elif action == "start_stop":
            self._toggle_start_stop()
        elif action == "pause":
            self.toggle_pause()
        elif action == "pause_press":
            self.resume_translation(quiet_log=True)
        elif action == "pause_release":
            self.pause_translation(quiet_log=True)

    def _toggle_translation_mute(self) -> None:
        self.translation_muted = not self.translation_muted
        if self.loop_obj is not None:
            self.loop_obj.set_muted(self.translation_muted)
        message = t("translation_muted") if self.translation_muted else t("translation_unmuted")
        self._append(f"[bilgi] {message}\n")
        self._sync_source_dub()

    def _sync_source_dub(self, *, quiet_log: bool = False) -> None:
        """Çeviri sesi duyulurken kaynağı sustur; aksi halde eski haline döndür."""
        dub = getattr(self, "_source_dub", None)
        if dub is None:
            return
        running = self._worker_alive() and not self._stopping.is_set()
        output = source = None
        if running:
            try:
                output = self._resolve_output_device()
                source = self._resolve_input_device()
            except Exception:
                output = source = None
        mute = bool(getattr(self, "dub_mute_source", False))
        bed_gain = self._clamp_bed_gain(getattr(self, "dub_background_gain", DUB_BACKGROUND))
        # %100 katı 1: dokunmamak ile aynı. Tutmak, kullanıcının kendi sesini geri çeker.
        background = (
            bool(getattr(self, "dub_background", False)) and not mute and bed_gain < 0.995
        )
        enabled = bool(
            (mute or background)
            and running
            and output is not None
            and not getattr(self, "translation_muted", False)
        )
        try:
            armed_plan = dub.preview(
                source, output, enabled=enabled, gain=bed_gain if background else None,
            )
        except Exception as exc:
            self._announce_dub_failure(exc)
            return
        loop_obj = getattr(self, "loop_obj", None)
        set_exclude = getattr(loop_obj, "set_dub_exclude", None)
        set_capture_gain = getattr(loop_obj, "set_capture_gain", None)
        is_playing_fn = getattr(loop_obj, "is_playing_audio", None)
        paused = bool(getattr(self, "_paused", False)) or bool(
            getattr(loop_obj, "is_paused", False)
        )
        dynamic = bool(getattr(self, "dub_ducking", True)) and callable(is_playing_fn)
        if paused:
            active_now = False
        elif enabled and dynamic:
            try:
                active_now = bool(is_playing_fn())
            except Exception:
                active_now = False
        else:
            active_now = enabled
        self._dub_speech_active = bool(active_now)
        effective_plan = (
            armed_plan if active_now else DubPlan("idle", note=armed_plan.note)
        )
        try:
            # Aynı hoparlörde kendi sürecimizi dışlayan yakalama tüm oturum boyunca
            # açık kalır; cümle aralarında kayıt akışı yeniden başlatılmaz.
            if armed_plan.action == "mute_other_sessions" and set_exclude is not None:
                set_exclude(True)
            dub.engage(effective_plan)
            if set_capture_gain is not None:
                set_capture_gain(source_capture_gain(effective_plan))
            if armed_plan.action != "mute_other_sessions" and set_exclude is not None:
                set_exclude(False)
        except Exception as exc:
            if set_capture_gain is not None:
                try:
                    set_capture_gain(1.0)
                except Exception:
                    pass
            if set_exclude is not None:
                try:
                    set_exclude(False)
                except Exception:
                    pass
            try:
                dub.release()
            except Exception:
                pass
            self._announce_dub_failure(exc)
            return
        if not quiet_log:
            self._announce_dub(armed_plan)

    def _release_source_dub(self) -> None:
        loop_obj = getattr(self, "loop_obj", None)
        set_capture_gain = getattr(loop_obj, "set_capture_gain", None)
        if set_capture_gain is not None:
            try:
                set_capture_gain(1.0)
            except Exception:
                pass
        set_exclude = getattr(loop_obj, "set_dub_exclude", None)
        if set_exclude is not None:
            try:
                set_exclude(False)
            except Exception:
                pass
        dub = getattr(self, "_source_dub", None)
        if dub is not None:
            try:
                dub.release()
            except Exception:
                pass
        self._announce_dub(DubPlan())

    def _announce_dub(self, plan: DubPlan) -> None:
        log = getattr(self, "log", None)
        if log is None:
            return
        try:
            if not int(log.winfo_exists()):
                return
        except tk.TclError:
            return
        signature = (
            plan.action, plan.note, plan.root_pid, plan.endpoint_id, plan.gain is not None,
        )
        if signature == getattr(self, "_dub_logged", None):
            return
        self._dub_logged = signature
        if plan.action == "idle":
            if getattr(self, "_dub_was_active", False):
                self._append(f"[bilgi] {t('dub_restored')}\n")
            self._dub_was_active = False
            if plan.note == "same_speakers" and (
                getattr(self, "dub_mute_source", False) or getattr(self, "dub_background", False)
            ):
                self._append(f"[bilgi] {t('dub_same_speakers')}\n")
            return
        self._dub_was_active = True
        bed = plan.gain is not None
        key = {
            "mute_process": "dub_bed_app" if bed else "dub_muted_app",
            "mute_endpoint": "dub_bed_endpoint" if bed else "dub_muted_endpoint",
            "mute_other_sessions": "dub_bed_sessions" if bed else "dub_muted_sessions",
        }.get(plan.action)
        if key:
            extra = ""
            if bed and plan.gain is not None:
                extra = f" ({int(round(float(plan.gain) * 100))}%)"
            self._append(f"[bilgi] {t(key)}{extra}\n")

    def _announce_dub_failure(self, exc: BaseException) -> None:
        log_exception(exc, "source dub")
        if hasattr(self, "log"):
            self._append(f"[uyarı] {t('dub_failed')}: {exc}\n")

    @staticmethod
    def _clamp_bed_gain(value) -> float:
        try:
            gain = float(value)
        except (TypeError, ValueError):
            return DUB_BACKGROUND
        if gain != gain:
            return DUB_BACKGROUND
        return max(0.0, min(1.0, gain))

    @staticmethod
    def _clamp_volume(value) -> float:
        try:
            vol = float(value)
        except (TypeError, ValueError):
            return 1.0
        if vol != vol:
            return 1.0
        return max(0.0, min(2.0, vol))

    @staticmethod
    def _clamp_overlay_alpha(value) -> float:
        try:
            alpha = float(value)
        except (TypeError, ValueError):
            return 0.92
        if alpha != alpha:
            return 0.92
        return max(0.2, min(1.0, alpha))

    def _write_pane(self, widget, text: str):
        pinned = self._is_pane_pinned(widget)
        # Akış en alttayken eski seçim gri blok gibi görünmesin diye kaldır;
        # yukarı kaydırıp metin seçen kullanıcının seçimini ise koru.
        if pinned and widget.tag_ranges("sel"):
            widget.tag_remove("sel", "1.0", tk.END)
        lang = self.src_var.get() if widget is self.heard else self.dst_var.get()
        tag = "rtl" if is_rtl(lang) else "ltr"
        widget.insert(tk.END, text, ("body", tag))
        try:
            line_count = int(widget.index("end-1c").split(".")[0])
            if line_count > self.MAX_PANE_LINES:
                trim = max(1, line_count - self.MAX_PANE_LINES + self.PANE_TRIM_BATCH)
                if not pinned:
                    top_line = int(widget.index("@0,0").split(".")[0])
                    widget.delete("1.0", f"{trim + 1}.0")
                    widget.yview(f"{max(1, top_line - trim)}.0")
                else:
                    widget.delete("1.0", f"{trim + 1}.0")
        except Exception:
            pass
        if pinned:
            widget.see(tk.END)
            self._hide_jump_pill(widget)
        elif text.strip():
            self._show_jump_pill(widget)
        if self._find_bar is not None and self._find_bar.is_open:
            self._find_bar.refresh(scroll=False, preserve_index=True)
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

    def _append_transcript_item(self, item: TranscriptItem) -> None:
        self.transcript_items.append(item)
        if len(self.transcript_items) <= self.MAX_TRANSCRIPT_ITEMS:
            return
        batch = min(self.TRANSCRIPT_SPILL_BATCH, max(1, self.MAX_TRANSCRIPT_ITEMS // 2))
        spill_count = max(1, len(self.transcript_items) - self.MAX_TRANSCRIPT_ITEMS + batch)
        spill_count = min(spill_count, len(self.transcript_items))
        to_spill = self.transcript_items[:spill_count]
        del self.transcript_items[:spill_count]
        spill_path = getattr(self, "_transcript_spill_path", None)
        if spill_path is None:
            tmp = tempfile.NamedTemporaryFile(
                prefix="ahenk_spill_", suffix=".jsonl", delete=False
            )
            tmp.close()
            spill_path = Path(tmp.name)
            self._transcript_spill_path = spill_path
        with spill_path.open("a", encoding="utf-8") as fh:
            for it in to_spill:
                fh.write(
                    json.dumps(
                        {
                            "timestamp": it.timestamp,
                            "stream": it.stream,
                            "text": it.text,
                            "duration_s": it.duration_s,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _load_spilled_transcript_items(self) -> list[TranscriptItem]:
        spill_path = getattr(self, "_transcript_spill_path", None)
        if spill_path is None or not spill_path.is_file():
            return []
        loaded: list[TranscriptItem] = []
        try:
            with spill_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    raw = line.strip()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    loaded.append(
                        TranscriptItem(
                            timestamp=float(data["timestamp"]),
                            stream=str(data["stream"]),
                            text=str(data["text"]),
                            duration_s=float(data.get("duration_s", 0.0)),
                        )
                    )
        except Exception:
            pass
        return loaded

    def _clear_pane(self, widget):
        widget.delete("1.0", tk.END)
        self._hide_jump_pill(widget)
        target_stream = None
        if widget is self.heard:
            target_stream = "heard"
            self.detected_lbl.configure(text="")
            self._curr_heard_buf = ""
            self._curr_heard_start = None
            self._last_heard_completed = ""
            self.transcript_items = [it for it in self.transcript_items if it.stream != "heard"]
        elif widget is self.trans:
            target_stream = "trans"
            self._curr_trans_buf = ""
            self._curr_trans_start = None
            if self._overlay is not None and self._overlay.winfo_exists():
                self._overlay_text = ""
                self.overlay_label.configure(text="...")
            self.transcript_items = [it for it in self.transcript_items if it.stream != "trans"]
        spill_path = getattr(self, "_transcript_spill_path", None)
        if target_stream is not None and spill_path is not None and spill_path.is_file():
            kept = [
                it for it in self._load_spilled_transcript_items()
                if it.stream != target_stream
            ]
            if kept:
                with spill_path.open("w", encoding="utf-8") as fh:
                    for it in kept:
                        fh.write(
                            json.dumps(
                                {
                                    "timestamp": it.timestamp,
                                    "stream": it.stream,
                                    "text": it.text,
                                    "duration_s": it.duration_s,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
            else:
                try:
                    spill_path.unlink(missing_ok=True)
                except OSError:
                    pass
                self._transcript_spill_path = None
        if self._find_bar is not None and self._find_bar.is_open:
            self._find_bar.refresh(scroll=False)
        if (
            not self.transcript_items
            and not self._load_spilled_transcript_items()
            and (self.worker is None or not self.worker.is_alive())
        ):
            self._timeline_start_time = None
    def _copy_pane(self, pane: tk.Text):
        content = pane.get("1.0", "end-1c").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._append(f"[bilgi] {t('copied')}\n")

    def _update_meter(self, level: float, *, fill: str | None = None) -> None:
        w = int(max(0.0, min(1.0, level)) * 56)
        self.meter.coords(self._meter_bar, 0, 0, w, 8)
        if fill is not None:
            self.meter.itemconfigure(self._meter_bar, fill=fill)

    def _refresh_key_notice(self) -> None:
        notice = getattr(self, "_key_notice", None)
        if notice is None:
            return
        has_key = bool(self.key_var.get().strip())
        if has_key:
            notice.grid_remove()
            return
        notice.configure(text=t("api_key_missing"), fg=C.warn, bg=C.rail)
        if notice.winfo_manager() != "grid":
            notice.grid()

    def _save_user_prefs(self):
        if getattr(self, "_save_prefs_timer", None) is not None:
            try:
                self.after_cancel(self._save_prefs_timer)
            except Exception:
                pass
        self._save_prefs_timer = self.after(400, self._do_save_user_prefs)

    def _do_save_user_prefs(self):
        self._save_prefs_timer = None
        src_raw = canonical_name(self.src_var.get())
        src_code = "auto" if src_raw == AUTO_SRC else LANGS.get(src_raw, src_raw)
        dst_raw = canonical_name(self.dst_var.get())
        dst_code = LANGS.get(dst_raw, dst_raw)
        out_label = self.out_var.get()
        if is_none_output(out_label):
            out_label = NONE_OUTPUT
        overlay_geom = None
        if self._overlay is not None and self._overlay.winfo_exists():
            overlay_geom = self._overlay.geometry()
        try:
            save_preferences(
                input_device=self.in_var.get(),
                input_application=self._input_application_path,
                output_device=out_label,
                src_lang=src_code,
                dst_lang=dst_code,
                theme=getattr(self, "_theme", "dark"),
                window_geom=self.geometry(),
                overlay_geom=overlay_geom,
                always_on_top=getattr(self, "always_on_top", False),
                overlay_font_size=getattr(self, "overlay_font_size", 13),
                overlay_alpha=getattr(self, "overlay_alpha", 0.92),
                overlay_click_through=getattr(self, "overlay_click_through", False),
                dub_mute_source=getattr(self, "dub_mute_source", False),
                dub_background=getattr(self, "dub_background", False),
                dub_background_gain=self._clamp_bed_gain(
                    getattr(self, "dub_background_gain", DUB_BACKGROUND)
                ),
                dub_ducking=getattr(self, "dub_ducking", True),
                translation_volume=self._clamp_volume(
                    getattr(self, "translation_volume", 1.0)
                ),
                save_history=getattr(self, "save_history", True),
                push_to_talk=getattr(self, "push_to_talk", False),
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

    def _get_export_items(self) -> list[TranscriptItem]:
        items = self._load_spilled_transcript_items() + list(getattr(self, "transcript_items", []))
        now = time.time()
        heard_buf = getattr(self, "_curr_heard_buf", "").strip()
        trans_buf = getattr(self, "_curr_trans_buf", "").strip()
        if heard_buf:
            h_start = getattr(self, "_curr_heard_start", None) or now
            items.append(
                TranscriptItem(
                    timestamp=h_start,
                    stream="heard",
                    text=heard_buf,
                    duration_s=max(1.5, now - h_start),
                )
            )
        if trans_buf:
            t_start = getattr(self, "_curr_trans_start", None) or (now + 0.5)
            items.append(
                TranscriptItem(
                    timestamp=t_start,
                    stream="trans",
                    text=trans_buf,
                    duration_s=max(1.5, max(now, t_start) - t_start),
                )
            )
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
        items = self._get_export_items()
        if not items:
            self._append(f"[bilgi] {t('export_empty')}\n")
            return

        selected_type = tk.StringVar(master=self, value="")
        try:
            file_path = filedialog.asksaveasfilename(
                parent=self,
                title=t("export_dialog_title"),
                defaultextension=".txt",
                typevariable=selected_type,
                filetypes=[
                    (t("filetype_txt"), "*.txt"),
                    (t("filetype_srt"), "*.srt"),
                    (t("filetype_bilingual_srt"), "*.bilingual.srt"),
                    (t("filetype_vtt"), "*.vtt"),
                    (t("filetype_jsonl"), "*.jsonl"),
                ],
            )
            chosen_filter = selected_type.get()
        finally:
            selected_type = None  # type: ignore[assignment]
        if not file_path:
            return
        try:
            session_base = getattr(self, "_timeline_start_time", None) or getattr(
                self, "session_start_time", None
            )
            lower = file_path.lower()
            if lower.endswith(".bilingual.srt") or (
                lower.endswith(".srt") and chosen_filter == t("filetype_bilingual_srt")
            ):
                content = export_bilingual_srt(items, session_start=session_base)
            elif lower.endswith(".srt"):
                content = export_srt(items, session_start=session_base)
            elif lower.endswith(".bilingual.vtt"):
                content = export_vtt(items, session_start=session_base, bilingual=True)
            elif lower.endswith(".vtt"):
                content = export_vtt(items, session_start=session_base, bilingual=False)
            elif lower.endswith(".jsonl"):
                content = export_jsonl(items)
            else:
                content = export_txt(items)
            Path(file_path).write_text(content, encoding="utf-8")
            self._append(f"[bilgi] {t('exported')} {file_path}\n")
        except Exception as e:
            self._append(f"[hata] {t('export_failed').format(error=e)}\n")

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

    def restart(self) -> None:
        """Çalışırken ayarları nazikçe yeniden başlatarak uygular."""
        if self.worker is not None and self.worker.is_alive():
            self._pending_restart = True
            self.stop(cancel_restart=False)
        else:
            self._pending_restart = False
            self.start()

    def _on_runtime_pref_change(self, *args):
        if getattr(self, "_resetting_settings", False) or getattr(self, "_translating_ui", False):
            return
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
            self._append(f"[bilgi] {t('runtime_restarting_log')}\n")
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
        self._rail_body.configure(bg=C.rail)
        self._rail_canvas.configure(bg=C.rail)
        self._rail_footer.configure(bg=C.rail)
        self._rail_scroll.configure(bg=C.hover, troughcolor=C.rail, activebackground=C.dim)
        self._v_sep.configure(bg=C.line)
        self.main.configure(bg=C.bg)

        # Rail header
        for f in (self._rail_head, self._rail_title, self._rail_actions, self._rail_st):
            f.configure(bg=C.rail)
        self.brand.configure(fg=C.text, bg=C.rail)
        self.version_lbl.configure(fg=C.dim, bg=C.rail)
        if hasattr(self, "_update_chip"):
            self._update_chip.configure(fg=C.live, bg=C.rail, activeforeground=C.text,
                                        activebackground=C.hover, disabledforeground=C.muted)
        self.status.configure(fg=C.muted, bg=C.rail)
        self.timer_lbl.configure(fg=C.dim, bg=C.rail)
        self._dot.configure(bg=C.rail)
        running = self.worker is not None and self.worker.is_alive()
        dot_color = C.warn if (running and self._paused) else (C.live if running else C.dim)
        self._status_color = dot_color
        self._dot.itemconfigure(self._dot_id, fill=dot_color)
        self.meter.configure(bg=C.line)
        downloading = self._download_fraction is not None
        self.meter.itemconfigure(self._meter_bar, fill=C.warn if downloading else C.live)
        if downloading:
            self._paint_download_progress(self._download_fraction or 0.0)

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
        self._sync_action_buttons(running)
        self._refresh_key_notice()

        # Main panes
        for f in (self.heard_h, self.trans_h, self.heard_wrap, self.trans_wrap, self.log_wrap):
            f.configure(bg=C.bg)
        if self._find_bar is not None and self._find_bar.winfo_exists():
            self._find_bar.update_theme()
        for lbl in (self.heard_lbl, self.trans_lbl, self.detected_lbl):
            lbl.configure(fg=C.muted, bg=C.bg)
        self.detected_lbl.configure(fg=C.dim)
        for btn in (
            self.heard_clear, self.heard_copy, self.heard_export,
            self.trans_clear, self.trans_copy, self.trans_export,
        ):
            btn._rest_fg = C.dim
            btn.configure(fg=C.dim, bg=C.bg)
        for pill in self._jump_pills.values():
            if pill.winfo_exists():
                pill.configure(
                    bg=C.panel,
                    fg=C.accent,
                    activebackground=C.hover,
                    activeforeground=C.text,
                )
                edge = getattr(pill, "_edge", None)
                if edge is not None and edge.winfo_exists():
                    edge.configure(bg=C.accent)

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
            TranscriptSearchBar.style_text_tags(pane)

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
            canvas = getattr(self, "_settings_canvas", None)
            if canvas is not None and canvas.winfo_exists():
                canvas.configure(bg=C.panel)
            scroll = getattr(self, "_settings_scroll", None)
            if scroll is not None and scroll.winfo_exists():
                scroll.configure(
                    bg=C.panel, troughcolor=C.rail, activebackground=C.hover
                )
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
            for entry in (
                self._mute_shortcut_entry,
                self._start_stop_shortcut_entry,
                self._pause_shortcut_entry,
            ):
                if entry is not None and entry.winfo_exists():
                    entry.configure(bg=C.panel, fg=C.text, insertbackground=C.text)
            for child in self._settings.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=C.panel)
                self._retint_frame(child, bg=C.panel)
            for key, widget in self._settings_refs.items():
                if isinstance(widget, tk.Label) and widget.winfo_exists():
                    widget.configure(fg=C.text if key.endswith("title") else C.muted)
            for label, _key in self._settings_refs.get("shortcut_labels", []):
                label.configure(fg=C.muted)
            if self._shortcut_status is not None and self._shortcut_status.winfo_exists():
                self._shortcut_status.configure(fg=C.muted)
            self._style_dub_scale()
            self._sync_dub_gain_controls()
            for scale in (self._volume_scale, self._overlay_alpha_scale):
                if scale is not None and scale.winfo_exists():
                    scale.configure(bg=C.panel)
            for pct_lbl in (self._volume_pct_lbl, self._overlay_alpha_pct_lbl):
                if pct_lbl is not None and pct_lbl.winfo_exists():
                    pct_lbl.configure(fg=C.text, bg=C.panel)
            for chk in (
                self._dub_toggle,
                self._dub_bg_toggle,
                self._dub_ducking_toggle,
                self._save_history_toggle,
                self._push_to_talk_toggle,
            ):
                if chk is not None and chk.winfo_exists():
                    chk.configure(bg=C.panel, fg=C.text)
            if self._glossary_edge is not None and self._glossary_edge.winfo_exists():
                self._glossary_edge.configure(bg=C.line)
            if self._glossary_text is not None and self._glossary_text.winfo_exists():
                self._glossary_text.configure(
                    bg=C.panel,
                    fg=C.text,
                    insertbackground=C.text,
                    selectbackground=C.select,
                    selectforeground=C.text,
                )
            # Ayarlar diyalog butonlarının (özellikle birincil Kaydet) stilini koru.
            for attr in (
                "test_key_btn",
                "save_key_btn",
                "_settings_close_btn",
                "_reset_btn",
                "_view_history_btn",
                "_clear_history_btn",
            ):
                btn = getattr(self, attr, None)
                try:
                    if btn is not None and btn.winfo_exists():
                        primary = bool(getattr(btn, "_primary", False))
                        btn._rest_bg = C.fill if primary else C.panel
                        btn._hover_bg = C.fill_hover if primary else C.hover
                        btn.configure(
                            bg=btn._rest_bg,
                            fg=C.fill_fg if primary else C.text,
                            activebackground=btn._hover_bg,
                            activeforeground=C.fill_fg if primary else C.text,
                        )
                        try:
                            btn.master.configure(bg=C.fill if primary else C.line)
                        except tk.TclError:
                            pass
                except tk.TclError:
                    pass
            self._style_lang_buttons()
            self._style_settings_tabs()
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
        if self._application_picker is not None and self._application_picker.winfo_exists():
            self._application_picker.configure(bg=C.panel)
            dark_titlebar(self._application_picker, dark=(C.current != "light"))
            for child in self._application_picker.winfo_children():
                self._retint_frame(child, bg=C.panel)
            if self._application_list is not None and self._application_list.winfo_exists():
                if hasattr(self._application_list, "update_theme"):
                    self._application_list.update_theme()
                else:
                    self._application_list.configure(
                        bg=C.panel, fg=C.text, selectbackground=C.select, selectforeground=C.text
                    )
            self._update_application_select_state()
        if self._about is not None and self._about.winfo_exists():
            self._about.configure(bg=C.panel)
            dark_titlebar(self._about, dark=(C.current != "light"))
            for child in self._about.winfo_children():
                self._retint_frame(child, bg=C.panel)
        if self._history_win is not None and self._history_win.winfo_exists():
            self._history_win.configure(bg=C.panel)
            dark_titlebar(self._history_win, dark=(C.current != "light"))
            for child in self._history_win.winfo_children():
                self._retint_frame(child, bg=C.panel)
            if self._history_find_bar is not None and self._history_find_bar.winfo_exists():
                self._history_find_bar.update_theme()
            if self._history_text is not None and self._history_text.winfo_exists():
                self._history_text.configure(
                    bg=C.bg,
                    fg=C.text,
                    insertbackground=C.text,
                    selectbackground=C.select,
                    selectforeground=C.text,
                )
                self._history_text.tag_configure("meta", foreground=C.dim)
                self._history_text.tag_configure("heard", foreground=C.muted)
                self._history_text.tag_configure("trans", foreground=C.text)
                TranscriptSearchBar.style_text_tags(self._history_text)

    def _retint_frame(self, widget, *, bg: str) -> None:
        """Açık diyaloglarda (Ayarlar/Hakkında) tema geçişini tüm içeriğe uygular."""
        for child in widget.winfo_children():
            if child in (
                self.key_edge,
                self.key_entry,
                self.mask_btn,
                getattr(self, "_glossary_edge", None),
                getattr(self, "_glossary_text", None),
                getattr(self, "_history_text", None),
                getattr(self, "_history_find_bar", None),
                getattr(self, "_application_list", None),
            ):
                continue
            if isinstance(child, (tk.Frame, tk.Canvas)):
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
            elif isinstance(child, tk.Scale):
                try:
                    child.configure(
                        bg=bg, fg=C.text, troughcolor=C.line, activebackground=C.accent,
                        highlightbackground=bg,
                    )
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
                            now_ts = time.time()
                            h_start = getattr(self, "_curr_heard_start", None) or now_ts
                            self._append_transcript_item(
                                TranscriptItem(
                                    timestamp=h_start,
                                    stream="heard",
                                    text=self._curr_heard_buf.strip(),
                                    duration_s=max(1.5, now_ts - h_start),
                                )
                            )
                            self._curr_heard_buf = ""
                            self._curr_heard_start = None
                        if getattr(self, "_curr_trans_buf", "").strip():
                            now_ts = time.time()
                            t_start = getattr(self, "_curr_trans_start", None) or now_ts
                            self._append_transcript_item(
                                TranscriptItem(
                                    timestamp=t_start,
                                    stream="trans",
                                    text=self._curr_trans_buf.strip(),
                                    duration_s=max(1.5, now_ts - t_start),
                                )
                            )
                            self._curr_trans_buf = ""
                            self._curr_trans_start = None
                        if getattr(self, "_pending_restart", False):
                            was_paused = bool(getattr(self, "_paused", False))
                            self._set_running(False)
                            self.worker = None
                            self._release_source_dub()
                            self.loop_obj = None
                            try:
                                self._sync_preview_device()
                            except Exception:
                                pass
                            self._pending_restart = False
                            self._paused = was_paused
                            try:
                                self.start(preserve_transcript=True)
                            except TypeError:
                                self.start()
                        else:
                            self._set_running(False)
                            self.worker = None
                            self._release_source_dub()
                            self.loop_obj = None
                            try:
                                self._sync_preview_device()
                            except Exception:
                                pass
                            if self.status.cget("text") not in ("Hata", "Error"):
                                self._set_status("Durdu", C.dim)
                        continue
                    if isinstance(msg, tuple):
                        kind = msg[0]
                        payload = msg[1] if len(msg) > 1 else ""
                        if kind == "heard":
                            if not self._curr_heard_buf:
                                self._curr_heard_start = time.time()
                            self._curr_heard_buf += payload
                            self._write_pane(self.heard, payload)
                        elif kind == "trans":
                            if not self._curr_trans_buf:
                                self._curr_trans_start = time.time()
                            self._curr_trans_buf += payload
                            self._write_pane(self.trans, payload)
                        elif kind == "heard_end":
                            if self._curr_heard_buf.strip():
                                now_ts = time.time()
                                h_start = self._curr_heard_start or now_ts
                                text_heard = self._curr_heard_buf.strip()
                                self._last_heard_completed = text_heard
                                self._append_transcript_item(
                                    TranscriptItem(
                                        timestamp=h_start,
                                        stream="heard",
                                        text=text_heard,
                                        duration_s=max(1.2, now_ts - h_start),
                                    )
                                )
                                self._curr_heard_buf = ""
                                self._curr_heard_start = None
                            self._write_pane(self.heard, "\n")
                        elif kind == "trans_end":
                            if self._curr_trans_buf.strip():
                                now_ts = time.time()
                                t_start = self._curr_trans_start or now_ts
                                text_trans = self._curr_trans_buf.strip()
                                self._append_transcript_item(
                                    TranscriptItem(
                                        timestamp=t_start,
                                        stream="trans",
                                        text=text_trans,
                                        duration_s=max(1.5, now_ts - t_start),
                                    )
                                )
                                if getattr(self, "save_history", getattr(self._cfg, "save_history", True)):
                                    paired_heard = (
                                        self._curr_heard_buf.strip()
                                        or getattr(self, "_last_heard_completed", "").strip()
                                    )
                                    self._last_heard_completed = ""
                                    src_c = source_code(canonical_name(self.src_var.get())) or "auto"
                                    dst_c = LANGS.get(canonical_name(self.dst_var.get()), self.dst_var.get())
                                    self._enqueue_history_write(
                                        paired_heard,
                                        text_trans,
                                        src=src_c,
                                        dst=dst_c,
                                    )
                                else:
                                    self._last_heard_completed = ""
                                self._curr_trans_buf = ""
                                self._curr_trans_start = None
                            self._write_pane(self.trans, "\n")
                        elif kind == "playback_active":
                            if getattr(self, "dub_ducking", True):
                                self._sync_source_dub(quiet_log=True)
                        elif kind == "log":
                            self._append(payload)
                        elif kind == "level":
                            pass
                        elif kind == "hotkey":
                            self._handle_hotkey(str(payload))
                        elif kind == "status":
                            status_text = payload
                            color = msg[2] if len(msg) > 2 else C.live
                            if getattr(self, "_paused", False) and status_text in ("Dinleniyor", "Çalışıyor"):
                                self._set_status("Duraklatıldı", C.warn)
                            else:
                                self._set_status(status_text, color)
                        elif kind == "connection_failed":
                            if payload == self._session_id and not self._stopping.is_set():
                                self._notify_connection_failure()
                        elif kind == "detected_src":
                            detected_name = display_name(
                                lang_code_to_name(payload, default=payload)
                            )
                            self.detected_lbl.configure(text=f"[{detected_name}]")
                        elif kind == "latency":
                            if (
                                self.worker is not None
                                and self.worker.is_alive()
                                and not getattr(self, "_paused", False)
                            ):
                                self._set_status(f"Çalışıyor ({int(payload)} ms)", C.live)
                        elif kind == "update_result":
                            self._handle_update_result(payload, manual=bool(msg[2]))
                        elif kind == "update_error":
                            self._handle_update_error(str(payload), manual=bool(msg[2]))
                        elif kind == "update_ready":
                            self._apply_downloaded_update(payload, msg[2])
                        elif kind == "update_cancelled":
                            self._reset_update_download()
                        elif kind == "update_progress":
                            if self._update_cancel is not None and not self._update_cancel.is_set():
                                self._paint_download_progress(float(payload))
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
            downloading = self._download_fraction is not None
            if downloading:
                pass
            elif self.worker is not None and self.worker.is_alive() and self.session_start_time:
                elapsed = int(time.time() - self.session_start_time)
                m, s = divmod(elapsed, 60)
                if hasattr(self, "timer_lbl"):
                    self.timer_lbl.configure(text=f"{m:02d}:{s:02d}")
            elif hasattr(self, "timer_lbl"):
                self.timer_lbl.configure(text="")
            if downloading:
                pass
            elif self.loop_obj is not None:
                try:
                    self._update_meter(getattr(self.loop_obj, "last_level", 0.0) or 0.0)
                    if (
                        getattr(self, "dub_ducking", True)
                        and (getattr(self, "dub_mute_source", False) or getattr(self, "dub_background", False))
                        and callable(getattr(self.loop_obj, "is_playing_audio", None))
                    ):
                        now_playing = (
                            False
                            if getattr(self, "_paused", False)
                            else bool(self.loop_obj.is_playing_audio())
                        )
                        if now_playing != getattr(self, "_dub_speech_active", False):
                            self._sync_source_dub(quiet_log=True)
                except Exception:
                    pass
            elif not (self.worker is not None and self.worker.is_alive()):
                try:
                    preview = getattr(self, "_preview", None)
                    self._update_meter(preview.get_level() if preview is not None else 0.0)
                except Exception:
                    pass
            try:
                self._pump_after_id = self.after(120, self._pump_log)
            except tk.TclError:
                self._pump_after_id = None

    def start(self, preserve_transcript: bool = False):
        if self.worker is not None and self.worker.is_alive():
            return
        self._pending_restart = False
        api_key = self.key_var.get().strip()
        if not api_key:
            self._refresh_key_notice()
            self._append(f"[hata] {t('enter_api_key_log')}\n")
            self._open_settings()
            if self.status.cget("text") not in ("Hata", "Error"):
                self._set_status("Durdu", C.dim)
            return
        source = self._resolve_input_device()
        if source is None:
            if is_application_input_label(self.in_var.get()):
                self._append(f"[hata] {t('application_unavailable')}\n")
                self._set_status("Durdu", C.dim)
                return
            self._append(f"[hata] {t('select_valid_input')}\n")
            if self.status.cget("text") not in ("Hata", "Error"):
                self._set_status("Durdu", C.dim)
            return
        speaker = self._selected_speaker()
        try:
            save_api_key(api_key)
        except OSError as e:
            self._append(f"[uyarı] API anahtarı diske güvenli kaydedilemedi: {e}\n")
        src = source_code(canonical_name(self.src_var.get()))
        dst = LANGS[canonical_name(self.dst_var.get())]
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
        # Önizleme aygıtı bırakır; asıl yakalama tek sahip olarak açılır.
        try:
            if getattr(self, "_preview", None) is not None:
                self._preview.set_device(None)
        except Exception:
            pass
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
            "muted": self.translation_muted,
            "volume": self._clamp_volume(getattr(self, "translation_volume", 1.0)),
            "glossary": parse_glossary(getattr(self, "glossary", "")),
        }
        self.loop_obj = SystemAudioLoop(**self._loop_kwargs)
        start_paused = (
            bool(getattr(self, "_paused", False))
            if preserve_transcript
            else (bool(getattr(self, "push_to_talk", False)) and bool(getattr(self, "pause_shortcut", "").strip()))
        )
        self._paused = start_paused
        if start_paused and hasattr(self.loop_obj, "pause"):
            self.loop_obj.pause()
        dest = speaker.name if speaker is not None else NONE_OUTPUT
        src_disp = "auto" if src is None else src
        self._append(f"[bilgi] {source.name} -> {dest} ({src_disp}>{dst})\n")
        self.worker = threading.Thread(target=self._run, args=(current_session_id,), daemon=True)
        self.worker.start()
        self._sync_source_dub()
        self._set_running(True)
        self._set_status("Duraklatıldı" if start_paused else "Bağlanıyor", C.warn)

    def _run(self, session_id: int | None = None):
        if session_id is None:
            session_id = getattr(self, "_session_id", 0)

        def _on_error(root_err: BaseException, renewal: bool) -> None:
            if renewal:
                try:
                    get_logger().info("Gemini Live bağlantısı planlı yenileniyor: %s", root_err)
                except Exception:
                    pass
            else:
                log_exception(root_err, "Worker loop error")
                self.log_queue.put(f"\n[hata] {format_user_error(root_err)}\n")

        def _on_permanent(_root_err: BaseException) -> None:
            self.log_queue.put(("status", "Hata", C.err))
            self.log_queue.put(f"[hata] {t('connection_cannot_establish')}\n")

        def _on_reconnecting(attempt: int, total: int) -> None:
            self.log_queue.put(("status", f"Yeniden bağlanılıyor ({attempt}/{total})", C.warn))
            self.log_queue.put(f"[bilgi] {t('reconnecting_log').format(n=attempt, max=total)}\n")

        def _rebuild() -> None:
            if hasattr(self, "_loop_kwargs") and not self._stopping.is_set():
                new_loop = clone_loop_for_retry(
                    self.loop_obj,
                    self._loop_kwargs,
                    lambda **kw: SystemAudioLoop(**kw),
                )
                self.loop_obj = new_loop
                if self._stopping.is_set():
                    new_loop.request_stop()

        def _on_exhausted(_root_err: BaseException) -> None:
            self.log_queue.put(("status", "Hata", C.err))
            self.log_queue.put(f"[hata] {t('connection_failed_message')}\n")
            self.log_queue.put(("connection_failed", session_id))

        run_with_retries(
            lambda: self.loop_obj,
            rebuild_loop=_rebuild,
            stopping=self._stopping,
            on_error=_on_error,
            on_permanent=_on_permanent,
            on_reconnecting=_on_reconnecting,
            on_exhausted=_on_exhausted,
        )
        self.log_queue.put(("__stopped__", session_id))

    def _notify_connection_failure(self) -> None:
        if sys.platform != "win32":
            return
        try:
            notifier = self.__dict__.get("_connection_notifier")
            if notifier is None:
                notifier = WindowsNotifier(self.winfo_id())
                self._connection_notifier = notifier
            if not notifier.show(t("connection_failed_title"), t("connection_failed_message")):
                self._append("[uyarı] Windows bildirimi gösterilemedi; bağlantı hatası günlüğe yazıldı.\n")
        except Exception as exc:
            log_exception(exc, "Windows connection notification error")
            self._append("[uyarı] Windows bildirimi gösterilemedi; bağlantı hatası günlüğe yazıldı.\n")

    def stop(self, *args, cancel_restart: bool = True):
        if cancel_restart:
            self._pending_restart = False
            self._paused = False
        if getattr(self, "_restart_timer", None) is not None:
            try:
                self.after_cancel(self._restart_timer)
            except Exception:
                pass
            self._restart_timer = None
        self._stopping.set()
        self._release_source_dub()
        self.session_start_time = None
        if hasattr(self, "timer_lbl"):
            self.timer_lbl.configure(text="")
        if self.loop_obj is not None:
            self.loop_obj.request_stop()
        if getattr(self, "_pending_restart", False):
            self._set_status("Yeniden başlatılıyor", C.warn)
        else:
            self._set_status("Durduruluyor", C.warn)

    def _retranslate_ui(self) -> None:
        """Motor çalışırken arayüz dilini yeniden uygular."""
        self._translating_ui = True
        for attr, key in (
            ("_device_lbl", "device"),
            ("_input_lbl", "input"),
            ("_output_lbl", "output"),
            ("_language_lbl", "language"),
            ("heard_lbl", "heard"),
            ("trans_lbl", "trans"),
            ("refresh_btn", "refresh"),
            ("start_btn", "start"),
            ("stop_btn", "stop"),
        ):
            widget = getattr(self, attr, None)
            if widget is not None and widget.winfo_exists():
                widget.configure(text=t(key))
        if hasattr(self, "pause_btn") and self.pause_btn.winfo_exists():
            self.pause_btn.configure(text=t("resume" if getattr(self, "_paused", False) else "pause"))
        for pill in self._jump_pills.values():
            if pill.winfo_exists():
                pill.configure(text=t("jump_to_live"))
        if self._find_bar is not None and self._find_bar.winfo_exists():
            self._find_bar.set_labels(label_text=t("find_placeholder"), close_tip=t("close"))
        for attr, key in (
            ("heard_clear", "clear"),
            ("heard_copy", "copy"),
            ("heard_export", "export"),
            ("trans_clear", "clear"),
            ("trans_copy", "copy"),
            ("trans_export", "export"),
        ):
            widget = getattr(self, attr, None)
            if widget is not None and widget.winfo_exists():
                widget.configure(text=t(key))
        for attr, key in (
            ("info_btn", "about"),
            ("settings_btn", "settings"),
            ("pin_btn", "pin"),
            ("overlay_btn", "subtitle"),
            ("swap_btn", "swap"),
        ):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "set_tooltip"):
                widget.set_tooltip(t(key))
        if self.mask_btn is not None and self.mask_btn.winfo_exists():
            shown = str(self.mask_btn.kind) == "eye_off"
            self.mask_btn.set_tooltip(t("hide_key" if shown else "show_key"))
        if self._about is not None and self._about.winfo_exists():
            self._about.title(t("about"))
            self.about_tagline.configure(text=t("about_tagline"))
            self.about_update_btn.configure(text=t("check_updates"))
            if getattr(self, "about_ok_btn", None) is not None:
                self.about_ok_btn.configure(text=t("ok"))
            if self._update_info is None:
                self.about_update_status.configure(
                    text=t("update_auto_status") if can_self_update() else t("source_mode_status")
                )
            else:
                self.about_update_status.configure(text=t("update_ready_status").format(version=self._update_info.version))
        self._sync_update_chip()
        if self._history_win is not None and self._history_win.winfo_exists():
            self._history_win.title(t("history_title"))
            if getattr(self, "_history_close_btn", None) is not None and self._history_close_btn.winfo_exists():
                self._history_close_btn.configure(text=t("close"))
            if self._history_find_bar is not None and self._history_find_bar.winfo_exists():
                self._history_find_bar.set_labels(label_text=t("find_placeholder"), close_tip=t("close"))
            self._populate_history_window()
        self._update_input_hint()
        self._refresh_key_notice()
        if hasattr(self, "src_box"):
            src_current = canonical_name(self.src_var.get())
            dst_current = canonical_name(self.dst_var.get())
            self.src_box["values"] = display_source_names()
            self.dst_box["values"] = display_language_names()
            self.src_var.set(display_name(src_current))
            self.dst_var.set(display_name(dst_current))
        if hasattr(self, "out_box"):
            current_out = self.out_var.get()
            self.out_box["values"] = [none_output_label()] + [
                s.name for s in getattr(self, "outputs", []) or []
            ]
            if is_none_output(current_out):
                self.out_var.set(none_output_label())
        if hasattr(self, "in_box"):
            self.in_box["values"] = self._visible_input_values()
            current_in = self._resolve_input_device()
            if current_in is not None:
                self.in_var.set(display_input_label(current_in))
                self._last_input_label = self.in_var.get()
        self._update_input_hint()
        if hasattr(self, "status"):
            self._set_status(self._status_raw, self._status_color)
        self._translating_ui = False

    def _on_close(self):
        if getattr(self, "_pump_after_id", None) is not None:
            try:
                self.after_cancel(self._pump_after_id)
            except Exception:
                pass
            self._pump_after_id = None
        try:
            if getattr(self, "_preview", None) is not None:
                self._preview.shutdown()
        except Exception:
            pass
        self.stop()
        self._release_source_dub()
        self._close_history()
        self._close_about()
        self._close_settings()
        self._close_application_picker()
        if self._overlay is not None and self._overlay.winfo_exists():
            self._close_overlay()
        self._overlay_click_style = None
        if self._hotkeys is not None:
            self._hotkeys.close()
            self._hotkeys = None
        for box in (self.in_box, self.out_box, self.src_box, self.dst_box):
            box._close()
        if getattr(self, "_overlay_pointer_after_id", None) is not None:
            try:
                self.after_cancel(self._overlay_pointer_after_id)
            except Exception:
                pass
            self._overlay_pointer_after_id = None
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
        if self._update_cancel is not None:
            self._update_cancel.set()
        self._stop_activate_listener()
        try:
            if getattr(self, "_preview", None) is not None:
                self._preview.shutdown()
        except Exception:
            pass
        try:
            self._close_history()
        except Exception:
            pass
        for timer_attr in ("_dub_gain_timer", "_volume_timer", "_overlay_alpha_timer"):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    self.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, timer_attr, None)
        if getattr(self, "_history_writer_started", False):
            self._history_writer_started = False
            try:
                self._history_write_q.put(None)
            except Exception:
                pass
        self._overlay_font_cache = None
        notifier = self.__dict__.get("_connection_notifier")
        if notifier is not None:
            notifier.close()
        try:
            self._release_source_dub()
        except Exception:
            pass
        if getattr(self, "_pump_after_id", None) is not None:
            try:
                self.after_cancel(self._pump_after_id)
            except Exception:
                pass
            self._pump_after_id = None
        if getattr(self, "_hotkeys", None) is not None:
            self._hotkeys.close()
            self._hotkeys = None
        spill_path = getattr(self, "_transcript_spill_path", None)
        if spill_path is not None:
            try:
                spill_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._transcript_spill_path = None
        for var_attr in (
            "_dub_var",
            "_dub_bg_var",
            "_dub_ducking_var",
            "_dub_bg_gain_var",
            "_volume_var",
            "_overlay_alpha_var",
            "_save_history_var",
            "_mute_shortcut_var",
            "_start_stop_shortcut_var",
            "_pause_shortcut_var",
            "_push_to_talk_var",
        ):
            setattr(self, var_attr, None)
        super().destroy()
