"""Ana pencere."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import tkinter as tk

from config import load as load_config, resolve_api_key, save_api_key, save_preferences
from devices import NONE_OUTPUT, all_inputs, all_outputs, default_speaker, pick_loopback
from languages import AUTO_SRC, LANGS, source_code, source_names
from loop import SystemAudioLoop
from meta import APP_AUTHOR, APP_TITLE, __version__

from .theme import C, ICON_PNG, apply_icon, dark_titlebar, pick_fonts, prepare_app_id
from .widgets import Select


class App(tk.Tk):
    def __init__(self):
        prepare_app_id()
        cfg = load_config()
        self._cfg = cfg
        self._theme = getattr(cfg, "theme", "dark") or "dark"
        C.apply_theme(self._theme)
        super().__init__()
        self.title(APP_TITLE)
        apply_icon(self)
        self.geometry("960x580")
        self.minsize(780, 460)
        self.configure(bg=C.bg)
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.loop_obj: SystemAudioLoop | None = None
        self._stopping = threading.Event()
        self.inputs: list = []
        self.outputs: list = []
        self._about: tk.Toplevel | None = None
        self._overlay: tk.Toplevel | None = None
        self._rail_seps: list[tk.Frame] = []
        fonts = pick_fonts(self)
        self.font_ui = fonts["ui"]
        self.font_brand = fonts["brand"]
        self.font_body = fonts["body"]
        self.font_log = fonts["log"]
        self._build()
        self.refresh_devices(async_scan=True)
        dark_titlebar(self, dark=(self._theme != "light"))
        self.after(120, self._pump_log)

    def _build(self):
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        self.rail = tk.Frame(self, bg=C.rail, width=280, bd=0, highlightthickness=0)
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
    def _build_rail(self, rail: tk.Frame):
        self._rail_head = tk.Frame(rail, bg=C.rail)
        self._rail_head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 12))

        self._rail_title = tk.Frame(self._rail_head, bg=C.rail)
        self._rail_title.pack(fill=tk.X)
        self.brand = tk.Label(
            self._rail_title, text=APP_TITLE, font=self.font_brand, fg=C.text, bg=C.rail
        )
        self.brand.pack(side=tk.LEFT)
        self.version_lbl = tk.Label(
            self._rail_title, text=f"v{__version__}", font=self.font_ui, fg=C.dim, bg=C.rail
        )
        self.version_lbl.pack(side=tk.LEFT, padx=(8, 0))
        self.info_btn = self._text_btn(self._rail_title, "ⓘ", self._open_about)
        self.info_btn.pack(side=tk.RIGHT)
        self.theme_btn = self._text_btn(
            self._rail_title, "☀️" if C.current == "dark" else "🌙", self.toggle_theme
        )
        self.theme_btn.pack(side=tk.RIGHT, padx=(0, 6))
        self.overlay_btn = self._text_btn(self._rail_title, "Altyazı", self.toggle_overlay)
        self.overlay_btn.pack(side=tk.RIGHT, padx=(0, 6))

        self._rail_st = tk.Frame(self._rail_head, bg=C.rail)
        self._rail_st.pack(anchor="w", pady=(6, 0), fill=tk.X)
        self._dot = tk.Canvas(self._rail_st, width=8, height=8, bg=C.rail, highlightthickness=0, bd=0)
        self._dot.pack(side=tk.LEFT, pady=1)
        self._dot_id = self._dot.create_oval(1, 1, 7, 7, fill=C.dim, outline="")
        self.status = tk.Label(self._rail_st, text="Hazır", font=self.font_ui, fg=C.muted, bg=C.rail)
        self.status.pack(side=tk.LEFT, padx=(6, 0))
        self.meter = tk.Canvas(self._rail_st, width=36, height=4, bg=C.line, highlightthickness=0, bd=0)
        self.meter.pack(side=tk.RIGHT, padx=(0, 2), pady=3)
        self._meter_bar = self.meter.create_rectangle(0, 0, 0, 4, fill=C.live, outline="")

        self._rail_sep(rail, 1)

        self._devices_frame = tk.Frame(rail, bg=C.rail)
        self._devices_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._devices_frame.columnconfigure(0, weight=1)
        tk.Label(self._devices_frame, text="Aygıt", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_btn = self._text_btn(
            self._devices_frame, "Yenile", lambda: self.refresh_devices(async_scan=True)
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        self._fields_frame = tk.Frame(rail, bg=C.rail)
        self._fields_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._fields_frame.columnconfigure(0, weight=1)

        tk.Label(self._fields_frame, text="Giriş", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.in_var = tk.StringVar()
        self.in_box = Select(self._fields_frame, textvariable=self.in_var, values=["[Sistem]"], font=self.font_ui)
        self.in_box.grid(row=1, column=0, sticky="ew", pady=(3, 10))

        tk.Label(self._fields_frame, text="Çıkış", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=2, column=0, sticky="w"
        )
        self.out_var = tk.StringVar()
        self.out_box = Select(self._fields_frame, textvariable=self.out_var, values=[NONE_OUTPUT], font=self.font_ui)
        self.out_box.grid(row=3, column=0, sticky="ew", pady=(3, 0))

        self._rail_sep(rail, 4)

        self._lang_h = tk.Frame(rail, bg=C.rail)
        self._lang_h.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 0))
        tk.Label(self._lang_h, text="Dil", font=self.font_ui, fg=C.muted, bg=C.rail).pack(side=tk.LEFT)

        self._langs_frame = tk.Frame(rail, bg=C.rail)
        self._langs_frame.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 0))
        self._langs_frame.columnconfigure(0, weight=1)
        self._langs_frame.columnconfigure(2, weight=1)

        cfg = getattr(self, "_cfg", None) or load_config()
        src_val = cfg.src_lang if cfg.src_lang in source_names() else AUTO_SRC
        dst_val = cfg.dst_lang if cfg.dst_lang in LANGS else "Türkçe"
        self.src_var = tk.StringVar(value=src_val)
        self.src_box = Select(
            self._langs_frame, textvariable=self.src_var, values=source_names(), font=self.font_ui
        )
        self.src_box.grid(row=0, column=0, sticky="ew")

        self.swap_btn = tk.Label(
            self._langs_frame, text="→", font=self.font_ui, fg=C.dim, bg=C.rail, cursor="hand2", padx=6
        )
        self.swap_btn.grid(row=0, column=1)
        self.swap_btn.bind("<Button-1>", lambda _e: self._swap_langs())
        self.swap_btn.bind("<Enter>", lambda _e: self.swap_btn.configure(fg=C.text))
        self.swap_btn.bind("<Leave>", lambda _e: self.swap_btn.configure(fg=C.dim))

        self.dst_var = tk.StringVar(value=dst_val)
        self.dst_box = Select(
            self._langs_frame, textvariable=self.dst_var, values=list(LANGS), font=self.font_ui
        )
        self.dst_box.grid(row=0, column=2, sticky="ew")

        for var in (self.in_var, self.out_var, self.src_var, self.dst_var):
            var.trace_add("write", lambda *_: self._save_user_prefs())

        self._rail_sep(rail, 7)

        self._key_frame = tk.Frame(rail, bg=C.rail)
        self._key_frame.grid(row=8, column=0, sticky="new", padx=16, pady=(12, 0))
        self._key_frame.columnconfigure(0, weight=1)
        tk.Label(self._key_frame, text="API anahtarı", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.save_key_btn = self._text_btn(self._key_frame, "Kaydet", self.save_key)
        self.save_key_btn.grid(row=0, column=1, sticky="e")
        self.key_var = tk.StringVar(value=resolve_api_key())
        self.key_edge = tk.Frame(self._key_frame, bg=C.line, bd=0, highlightthickness=0)
        self.key_edge.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
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
        self.key_entry.pack(fill=tk.X, padx=1, pady=1, ipady=4)
        self.key_entry.bind("<Return>", lambda _e: self.save_key())

        self._btns_frame = tk.Frame(rail, bg=C.rail)
        self._btns_frame.grid(row=9, column=0, sticky="ew", padx=16, pady=16)
        self._btns_frame.columnconfigure(0, weight=1)
        self._btns_frame.columnconfigure(1, weight=1)

        self.start_btn = self._btn(self._btns_frame, "Başlat", self.start)
        self.start_btn._edge.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_btn = self._btn(self._btns_frame, "Durdur", self.stop)
        self.stop_btn._edge.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._paint(self.start_btn, filled=True, enabled=True)
        self._paint(self.stop_btn, filled=False, enabled=False)

    def _build_main(self, main: tk.Frame):
        self.heard_h = tk.Frame(main, bg=C.bg)
        self.heard_h.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(12, 6))
        self.heard_lbl = tk.Label(self.heard_h, text="Duyulan", font=self.font_ui, fg=C.muted, bg=C.bg)
        self.heard_lbl.pack(side=tk.LEFT)
        self.heard_clear = self._text_btn(self.heard_h, "Temizle", lambda: self._clear_pane(self.heard))
        self.heard_clear.pack(side=tk.RIGHT)
        self.heard_copy = self._text_btn(self.heard_h, "Kopyala", lambda: self._copy_pane(self.heard))
        self.heard_copy.pack(side=tk.RIGHT, padx=(0, 8))

        self.trans_h = tk.Frame(main, bg=C.bg)
        self.trans_h.grid(row=0, column=1, sticky="ew", padx=(16, 16), pady=(12, 6))
        self.trans_lbl = tk.Label(self.trans_h, text="Çeviri", font=self.font_ui, fg=C.muted, bg=C.bg)
        self.trans_lbl.pack(side=tk.LEFT)
        self.trans_clear = self._text_btn(self.trans_h, "Temizle", lambda: self._clear_pane(self.trans))
        self.trans_clear.pack(side=tk.RIGHT)
        self.trans_copy = self._text_btn(self.trans_h, "Kopyala", lambda: self._copy_pane(self.trans))
        self.trans_copy.pack(side=tk.RIGHT, padx=(0, 8))

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
            height=4,
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
        self._lock_text(text)
        return text

    def _lock_text(self, w: tk.Text) -> None:
        def on_key(e):
            if (e.state & 0x4) and e.keysym.lower() in ("c", "a"):
                return
            return "break"

        w.bind("<Key>", on_key)
        w.bind("<<Paste>>", lambda _e: "break")
        w.bind("<Button-2>", lambda _e: "break")

    def _rail_sep(self, parent: tk.Frame, row: int) -> None:
        sep = tk.Frame(parent, bg=C.line, height=1, bd=0, highlightthickness=0)
        sep.grid(row=row, column=0, sticky="ew", padx=16, pady=(12, 0))
        self._rail_seps.append(sep)
    def _text_btn(self, parent, label: str, command, bg: str | None = None) -> tk.Label:
        color_bg = bg or (parent["bg"] if "bg" in parent.keys() else C.rail)
        w = tk.Label(parent, text=label, font=self.font_ui, fg=C.dim, bg=color_bg, cursor="hand2")
        w.bind("<Button-1>", lambda _e: command())
        w.bind("<Enter>", lambda _e: w.configure(fg=C.text))
        w.bind("<Leave>", lambda _e: w.configure(fg=C.dim))
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
            takefocus=0,
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
        self.status.configure(text=text)
        self._dot.itemconfigure(self._dot_id, fill=color)

    def _set_running(self, running: bool) -> None:
        box = "disabled" if running else "readonly"
        self.in_box.configure(state=box)
        self.out_box.configure(state=box)
        self.src_box.configure(state=box)
        self.dst_box.configure(state=box)
        self.key_entry.configure(state=tk.DISABLED if running else tk.NORMAL)
        self._paint(self.start_btn, filled=not running, enabled=not running)
        self._paint(self.stop_btn, filled=running, enabled=running)
        self._dot.itemconfigure(self._dot_id, fill=C.live if running else C.dim)
        if not running:
            self._update_meter(0.0)

    def _swap_langs(self) -> None:
        if self.src_box["state"] == "disabled":
            return
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
                    try:
                        self.after(0, lambda i=ins, o=outs, s=stopping: self._apply_devices(i, o, s) if self.winfo_exists() else None)
                    except (tk.TclError, RuntimeError):
                        pass
                except Exception as e:
                    err_msg = str(e)
                    try:
                        self.after(0, lambda msg=err_msg: self._append(f"[hata] Aygıt tarama hatası: {msg}\n") if self.winfo_exists() else None)
                    except (tk.TclError, RuntimeError):
                        pass
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
            if cfg.input_device and cfg.input_device in self.in_box["values"]:
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
            if cfg.output_device and cfg.output_device in self.out_box["values"]:
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

    def _write_pane(self, widget, text: str):
        widget.insert(tk.END, text, ("body",))
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
                self.overlay_label.configure(text=last)
                self._fit_overlay()

    def _clear_pane(self, widget):
        widget.delete("1.0", tk.END)
        if widget is self.trans and self._overlay is not None and self._overlay.winfo_exists():
            self.overlay_label.configure(text="...")

    def _copy_pane(self, pane: tk.Text):
        content = pane.get("1.0", "end-1c").strip()
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._append("[bilgi] Metin panoya kopyalandı.\n")

    def _update_meter(self, level: float) -> None:
        w = int(max(0.0, min(1.0, level)) * 36)
        self.meter.coords(self._meter_bar, 0, 0, w, 4)

    def _save_user_prefs(self):
        if getattr(self, "_save_prefs_timer", None) is not None:
            try:
                self.after_cancel(self._save_prefs_timer)
            except Exception:
                pass
        self._save_prefs_timer = self.after(400, self._do_save_user_prefs)

    def _do_save_user_prefs(self):
        self._save_prefs_timer = None
        try:
            save_preferences(
                input_device=self.in_var.get(),
                output_device=self.out_var.get(),
                src_lang=self.src_var.get(),
                dst_lang=self.dst_var.get(),
                theme=getattr(self, "_theme", "dark"),
            )
        except OSError:
            pass

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
        for f in (self._rail_head, self._rail_title, self._rail_st):
            f.configure(bg=C.rail)
        self.brand.configure(fg=C.text, bg=C.rail)
        self.version_lbl.configure(fg=C.dim, bg=C.rail)
        self.status.configure(fg=C.muted, bg=C.rail)
        self._dot.configure(bg=C.rail)
        running = self.worker is not None and self.worker.is_alive()
        self._dot.itemconfigure(self._dot_id, fill=C.live if running else C.dim)
        self.meter.configure(bg=C.line)
        self.meter.itemconfigure(self._meter_bar, fill=C.live)
        self.theme_btn.configure(text="☀️" if C.current == "dark" else "🌙")

        # Rail text buttons
        for btn in (
            self.info_btn,
            self.theme_btn,
            self.overlay_btn,
            self.refresh_btn,
            self.save_key_btn,
        ):
            btn.configure(fg=C.dim, bg=C.rail)

        # Rail frames and labels
        for f in (
            self._devices_frame,
            self._fields_frame,
            self._lang_h,
            self._langs_frame,
            self._key_frame,
            self._btns_frame,
        ):
            f.configure(bg=C.rail)
            for child in f.winfo_children():
                if isinstance(child, tk.Label) and child is not self.swap_btn and child not in (
                    self.refresh_btn,
                    self.save_key_btn,
                ):
                    child.configure(fg=C.muted, bg=C.rail)

        for sep in self._rail_seps:
            sep.configure(bg=C.line)

        # Dropdowns
        for box in (self.in_box, self.out_box, self.src_box, self.dst_box):
            box.update_theme()

        # Swap button
        self.swap_btn.configure(fg=C.dim, bg=C.rail)

        # Key entry
        self.key_edge.configure(bg=C.line)
        self.key_entry.configure(
            bg=C.panel,
            fg=C.text,
            insertbackground=C.text,
            disabledbackground=C.rail,
            disabledforeground=C.dim,
        )

        # Action buttons
        self._paint(self.start_btn, filled=not running, enabled=not running)
        self._paint(self.stop_btn, filled=running, enabled=running)

        # Main panes
        for f in (self.heard_h, self.trans_h, self.heard_wrap, self.trans_wrap, self.log_wrap):
            f.configure(bg=C.bg)
        for lbl in (self.heard_lbl, self.trans_lbl):
            lbl.configure(fg=C.muted, bg=C.bg)
        for btn in (self.heard_clear, self.heard_copy, self.trans_clear, self.trans_copy):
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
        self.log.tag_configure("err", foreground=C.err)
        dark_titlebar(self, dark=(C.current != "light"))
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.configure(bg=C.overlay_bg)
            if hasattr(self, "_overlay_wrap") and self._overlay_wrap.winfo_exists():
                self._overlay_wrap.configure(bg=C.overlay_bg, highlightbackground=C.line)
            if hasattr(self, "overlay_label") and self.overlay_label.winfo_exists():
                self.overlay_label.configure(bg=C.overlay_bg, fg=C.text)
            if hasattr(self, "_overlay_close") and self._overlay_close.winfo_exists():
                self._overlay_close.configure(bg=C.overlay_bg, fg=C.dim)
        if self._about is not None and self._about.winfo_exists():
            self._about.configure(bg=C.panel)
            dark_titlebar(self._about, dark=(C.current != "light"))
    def _pump_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                try:
                    if msg == "__stopped__":
                        self._set_running(False)
                        self._set_status("Durdu", C.dim)
                        self.worker = None
                        self.loop_obj = None
                        continue
                    if isinstance(msg, tuple):
                        kind = msg[0]
                        payload = msg[1] if len(msg) > 1 else ""
                        if kind == "heard":
                            self._write_pane(self.heard, payload)
                        elif kind == "trans":
                            self._write_pane(self.trans, payload)
                        elif kind == "heard_end":
                            self._write_pane(self.heard, "\n")
                        elif kind == "trans_end":
                            self._write_pane(self.trans, "\n")
                        elif kind == "log":
                            self._append(payload)
                        elif kind == "level":
                            self._update_meter(float(payload))
                        elif kind == "status":
                            status_text = payload
                            color = msg[2] if len(msg) > 2 else C.live
                            self._set_status(status_text, color)
                        continue
                except Exception as e:
                    self._append(f"[hata] Arayüz kuyruk hatası: {e}\n")
        except queue.Empty:
            pass
        finally:
            self.after(120, self._pump_log)

    def save_key(self):
        key = self.key_var.get().strip()
        try:
            save_api_key(key)
        except OSError as e:
            self._append(f"[hata] Anahtar kaydedilemedi: {e}\n")
            return
        if key:
            self._append("[bilgi] API anahtarı kaydedildi.\n")
        else:
            self._append("[bilgi] Kayıtlı anahtar silindi.\n")
        self.key_entry.selection_clear()
        self.focus_set()

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        api_key = self.key_var.get().strip()
        if not api_key:
            self._append("[hata] API anahtarı girin (https://aistudio.google.com/apikey)\n")
            return
        idx = self.in_box.current()
        if idx < 0 or idx >= len(self.inputs):
            self._append("[hata] Geçerli giriş aygıtı seçin.\n")
            return
        source = self.inputs[idx]
        speaker = self._selected_speaker()
        try:
            save_api_key(api_key)
        except OSError:
            pass
        src, dst = source_code(self.src_var.get()), LANGS[self.dst_var.get()]
        self._clear_pane(self.heard)
        self._clear_pane(self.trans)
        self._stopping.clear()
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
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()
        self._set_running(True)
        self._set_status("Bağlanıyor", C.warn)

    def _run(self):
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
                retries += 1
                self.log_queue.put(f"\n[hata] {type(root_err).__name__}: {root_err}\n")
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
        self.log_queue.put("__stopped__")

    def stop(self):
        self._stopping.set()
        if self.loop_obj is not None:
            self.loop_obj.request_stop()
            self._set_status("Durduruluyor", C.warn)
            self._paint(self.stop_btn, filled=False, enabled=False)
    def _open_about(self) -> None:
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

    def _fit_overlay(self) -> None:
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        pop.update_idletasks()
        width = pop.winfo_width()
        height = min(max(56, pop.winfo_reqheight()), pop.winfo_screenheight())
        x = pop.winfo_x()
        bottom = pop.winfo_y() + pop.winfo_height()
        y = min(max(0, bottom - height), pop.winfo_screenheight() - height)
        pop.geometry(f"{width}x{height}{x:+d}{y:+d}")

    def toggle_overlay(self) -> None:
        if self._overlay is not None and self._overlay.winfo_exists():
            self._overlay.destroy()
            self._overlay = None
            self.overlay_btn.configure(fg=C.dim)
            return

        pop = tk.Toplevel(self)
        self._overlay = pop
        pop.title("Altyazı")
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        pop.configure(bg=C.overlay_bg)
        self.overlay_btn.configure(fg=C.live)

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

        close_btn = tk.Label(wrap, text="✕", font=self.font_ui, fg=C.dim, bg=C.overlay_bg, cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=8, pady=4, anchor="ne")
        self._overlay_close = close_btn
        close_btn.bind("<Button-1>", lambda _e: self.toggle_overlay())
        close_btn.bind("<Enter>", lambda _e: close_btn.configure(fg=C.text))
        close_btn.bind("<Leave>", lambda _e: close_btn.configure(fg=C.dim))

        lines = [l.strip() for l in self.trans.get("1.0", "end").splitlines() if l.strip()]
        cur_text = lines[-1] if lines else "..."

        self.overlay_label = tk.Label(
            wrap,
            text=cur_text,
            font=(self.font_brand[0], 12, "bold"),
            fg=C.text,
            bg=C.overlay_bg,
            wraplength=520,
            justify=tk.CENTER,
            padx=16,
            pady=10,
        )
        self.overlay_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for w in (pop, wrap, self.overlay_label):
            w.bind("<ButtonPress-1>", start_move)
            w.bind("<B1-Motion>", do_move)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 580, 56
        x = max(0, (sw - w) // 2)
        y = max(0, sh - h - 100)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        self._fit_overlay()
    def _on_close(self):
        self.stop()
        self._close_about()
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
