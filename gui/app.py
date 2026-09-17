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
        super().__init__()
        self.title(APP_TITLE)
        apply_icon(self)
        self.geometry("960x580")
        self.minsize(780, 460)
        self.configure(bg=C.bg)
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.loop_obj: SystemAudioLoop | None = None
        self.inputs: list = []
        self.outputs: list = []
        self._about: tk.Toplevel | None = None
        self._overlay: tk.Toplevel | None = None
        fonts = pick_fonts(self)
        self.font_ui = fonts["ui"]
        self.font_brand = fonts["brand"]
        self.font_body = fonts["body"]
        self.font_log = fonts["log"]
        self._build()
        self.refresh_devices()
        dark_titlebar(self)
        self.after(120, self._pump_log)

    def _build(self):
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)

        rail = tk.Frame(self, bg=C.rail, width=280, bd=0, highlightthickness=0)
        rail.grid(row=0, column=0, sticky="nsw")
        rail.grid_propagate(False)
        rail.columnconfigure(0, weight=1)
        rail.rowconfigure(8, weight=1)

        tk.Frame(self, bg=C.line, width=1, bd=0, highlightthickness=0).grid(
            row=0, column=1, sticky="ns"
        )

        main = tk.Frame(self, bg=C.bg, bd=0, highlightthickness=0)
        main.grid(row=0, column=2, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        self._build_rail(rail)
        self._build_main(main)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _e: self._toggle_start_stop())
        self.bind("<F5>", lambda _e: self._toggle_start_stop())
        self.bind("<Control-o>", lambda _e: self.toggle_overlay())
        self.bind("<Control-O>", lambda _e: self.toggle_overlay())
        self.bind("<F2>", lambda _e: self.toggle_overlay())

    def _build_rail(self, rail: tk.Frame):
        head = tk.Frame(rail, bg=C.rail)
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 12))

        title = tk.Frame(head, bg=C.rail)
        title.pack(fill=tk.X)
        self.brand = tk.Label(
            title, text=APP_TITLE, font=self.font_brand, fg=C.text, bg=C.rail
        )
        self.brand.pack(side=tk.LEFT)
        self.version_lbl = tk.Label(
            title, text=f"v{__version__}", font=self.font_ui, fg=C.dim, bg=C.rail
        )
        self.version_lbl.pack(side=tk.LEFT, padx=(8, 0))
        self.info_btn = self._text_btn(title, "ⓘ", self._open_about)
        self.info_btn.pack(side=tk.RIGHT)
        self.overlay_btn = self._text_btn(title, "Altyazı", self.toggle_overlay)
        self.overlay_btn.pack(side=tk.RIGHT, padx=(0, 8))

        st = tk.Frame(head, bg=C.rail)
        st.pack(anchor="w", pady=(6, 0), fill=tk.X)
        self._dot = tk.Canvas(st, width=8, height=8, bg=C.rail, highlightthickness=0, bd=0)
        self._dot.pack(side=tk.LEFT, pady=1)
        self._dot_id = self._dot.create_oval(1, 1, 7, 7, fill=C.dim, outline="")
        self.status = tk.Label(st, text="Hazır", font=self.font_ui, fg=C.muted, bg=C.rail)
        self.status.pack(side=tk.LEFT, padx=(6, 0))
        self.meter = tk.Canvas(st, width=36, height=4, bg=C.line, highlightthickness=0, bd=0)
        self.meter.pack(side=tk.RIGHT, padx=(0, 2), pady=3)
        self._meter_bar = self.meter.create_rectangle(0, 0, 0, 4, fill=C.live, outline="")

        self._rail_sep(rail, 1)

        devices = tk.Frame(rail, bg=C.rail)
        devices.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 0))
        devices.columnconfigure(0, weight=1)
        tk.Label(devices, text="Aygıt", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_btn = self._text_btn(
            devices, "Yenile", lambda: self.refresh_devices(async_scan=True)
        )
        self.refresh_btn.grid(row=0, column=1, sticky="e")

        fields = tk.Frame(rail, bg=C.rail)
        fields.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        fields.columnconfigure(0, weight=1)

        tk.Label(fields, text="Giriş", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.in_var = tk.StringVar()
        self.in_box = Select(fields, textvariable=self.in_var, font=self.font_ui)
        self.in_box.grid(row=1, column=0, sticky="ew", pady=(3, 10))

        tk.Label(fields, text="Çıkış", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=2, column=0, sticky="w"
        )
        self.out_var = tk.StringVar()
        self.out_box = Select(fields, textvariable=self.out_var, font=self.font_ui)
        self.out_box.grid(row=3, column=0, sticky="ew", pady=(3, 0))

        self._rail_sep(rail, 4)

        lang_h = tk.Frame(rail, bg=C.rail)
        lang_h.grid(row=5, column=0, sticky="ew", padx=16, pady=(12, 0))
        tk.Label(lang_h, text="Dil", font=self.font_ui, fg=C.muted, bg=C.rail).pack(side=tk.LEFT)

        langs = tk.Frame(rail, bg=C.rail)
        langs.grid(row=6, column=0, sticky="ew", padx=16, pady=(8, 0))
        langs.columnconfigure(0, weight=1)
        langs.columnconfigure(2, weight=1)

        cfg = load_config()
        src_val = cfg.src_lang if cfg.src_lang in source_names() else AUTO_SRC
        dst_val = cfg.dst_lang if cfg.dst_lang in LANGS else "Türkçe"

        self.src_var = tk.StringVar(value=src_val)
        self.src_box = Select(
            langs, textvariable=self.src_var, values=source_names(), font=self.font_ui
        )
        self.src_box.grid(row=0, column=0, sticky="ew")

        swap = tk.Label(
            langs, text="→", font=self.font_ui, fg=C.dim, bg=C.rail, cursor="hand2", padx=6
        )
        swap.grid(row=0, column=1)
        swap.bind("<Button-1>", lambda _e: self._swap_langs())
        swap.bind("<Enter>", lambda _e: swap.configure(fg=C.text))
        swap.bind("<Leave>", lambda _e: swap.configure(fg=C.dim))

        self.dst_var = tk.StringVar(value=dst_val)
        self.dst_box = Select(
            langs, textvariable=self.dst_var, values=list(LANGS), font=self.font_ui
        )
        self.dst_box.grid(row=0, column=2, sticky="ew")

        for var in (self.in_var, self.out_var, self.src_var, self.dst_var):
            var.trace_add("write", lambda *_: self._save_user_prefs())

        self._rail_sep(rail, 7)

        key = tk.Frame(rail, bg=C.rail)
        key.grid(row=8, column=0, sticky="new", padx=16, pady=(12, 0))
        key.columnconfigure(0, weight=1)
        tk.Label(key, text="API anahtarı", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.save_key_btn = self._text_btn(key, "Kaydet", self.save_key)
        self.save_key_btn.grid(row=0, column=1, sticky="e")
        self.key_var = tk.StringVar(value=resolve_api_key())
        key_edge = tk.Frame(key, bg=C.line, bd=0, highlightthickness=0)
        key_edge.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.key_entry = tk.Entry(
            key_edge,
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

        btns = tk.Frame(rail, bg=C.rail)
        btns.grid(row=9, column=0, sticky="ew", padx=16, pady=16)
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        self.start_btn = self._btn(btns, "Başlat", self.start)
        self.start_btn._edge.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_btn = self._btn(btns, "Durdur", self.stop)
        self.stop_btn._edge.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self._paint(self.start_btn, filled=True, enabled=True)
        self._paint(self.stop_btn, filled=False, enabled=False)

    def _build_main(self, main: tk.Frame):
        heard_h = tk.Frame(main, bg=C.bg)
        heard_h.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(12, 6))
        tk.Label(heard_h, text="Duyulan", font=self.font_ui, fg=C.muted, bg=C.bg).pack(side=tk.LEFT)
        self._text_btn(heard_h, "Temizle", lambda: self._clear_pane(self.heard)).pack(side=tk.RIGHT)
        self._text_btn(heard_h, "Kopyala", lambda: self._copy_pane(self.heard)).pack(side=tk.RIGHT, padx=(0, 8))

        trans_h = tk.Frame(main, bg=C.bg)
        trans_h.grid(row=0, column=1, sticky="ew", padx=(16, 16), pady=(12, 6))
        tk.Label(trans_h, text="Çeviri", font=self.font_ui, fg=C.muted, bg=C.bg).pack(side=tk.LEFT)
        self._text_btn(trans_h, "Temizle", lambda: self._clear_pane(self.trans)).pack(side=tk.RIGHT)
        self._text_btn(trans_h, "Kopyala", lambda: self._copy_pane(self.trans)).pack(side=tk.RIGHT, padx=(0, 8))

        heard_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        trans_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        heard_wrap.grid(row=1, column=0, sticky="nsew")
        trans_wrap.grid(row=1, column=1, sticky="nsew")
        for wrap in (heard_wrap, trans_wrap):
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)

        tk.Frame(main, bg=C.line, width=1, bd=0, highlightthickness=0).grid(
            row=0, column=0, rowspan=2, sticky="nse", pady=(12, 0)
        )

        self.heard = self._pane(heard_wrap)
        self.trans = self._pane(trans_wrap)

        tk.Frame(main, bg=C.line, height=1, bd=0, highlightthickness=0).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )

        log_wrap = tk.Frame(main, bg=C.bg, bd=0, highlightthickness=0)
        log_wrap.grid(row=3, column=0, columnspan=2, sticky="ew")
        log_wrap.columnconfigure(0, weight=1)

        self.log = tk.Text(
            log_wrap,
            wrap=tk.WORD,
            height=4,
            font=self.font_log,
            bg=C.bg,
            fg=C.dim,
            insertbackground=C.dim,
            selectbackground="#2c2c2c",
            selectforeground=C.muted,
            inactiveselectbackground="#2c2c2c",
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
            selectbackground="#2c2c2c",
            selectforeground=C.text,
            inactiveselectbackground="#2c2c2c",
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
        tk.Frame(parent, bg=C.line, height=1, bd=0, highlightthickness=0).grid(
            row=row, column=0, sticky="ew", padx=16, pady=(12, 0)
        )

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
            bg, fg, edge, hover = C.fill, C.fill_fg, C.fill, "#ffffff"
        elif enabled:
            bg, fg, edge, hover = C.panel, C.text, C.line, C.hover
        else:
            bg, fg, edge, hover = "#1a1a1a", C.dim, C.line, "#1a1a1a"
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

    def refresh_devices(self, async_scan: bool = False):
        stopping = self.worker is not None and self.worker.is_alive()
        if async_scan:
            def _scan():
                try:
                    ins = all_inputs()
                    outs = all_outputs()
                    self.after(0, lambda: self._apply_devices(ins, outs, stopping))
                except Exception as e:
                    self.after(0, lambda: self._append(f"[hata] Aygıt tarama hatası: {e}\n"))
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
            cfg = load_config()
            if cfg.input_device and cfg.input_device in self.in_box["values"]:
                self.in_var.set(cfg.input_device)
            else:
                try:
                    default_in = pick_loopback(None)
                    self.in_var.set(
                        ("[Sistem] " if default_in.isloopback else "[Mikrofon] ") + default_in.name
                    )
                except RuntimeError:
                    if ins:
                        self.in_var.set(
                            ("[Sistem] " if ins[0].isloopback else "[Mikrofon] ") + ins[0].name
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
        try:
            save_preferences(
                input_device=self.in_var.get(),
                output_device=self.out_var.get(),
                src_lang=self.src_var.get(),
                dst_lang=self.dst_var.get(),
            )
        except OSError:
            pass

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
                        continue
                    self._append(str(msg))
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
        self._set_status("Çalışıyor", C.live)

    def _run(self):
        retries = 0
        max_retries = 3
        while self.loop_obj and not getattr(self.loop_obj, "_user_stop", threading.Event()).is_set():
            try:
                asyncio.run(self.loop_obj.run())
                break
            except asyncio.CancelledError:
                break
            except BaseException as e:
                user_stop = getattr(self.loop_obj, "_user_stop", None)
                if user_stop and user_stop.is_set():
                    break
                retries += 1
                root_err = e
                if hasattr(e, "exceptions") and getattr(e, "exceptions"):
                    root_err = getattr(e, "exceptions")[0]
                self.log_queue.put(f"\n[hata] {type(root_err).__name__}: {root_err}\n")
                if retries <= max_retries:
                    self.log_queue.put(f"[bilgi] Yeniden bağlanılıyor ({retries}/{max_retries})...\n")
                    if user_stop:
                        user_stop.wait(2)
                    else:
                        time.sleep(2)
                    if hasattr(self, "_loop_kwargs"):
                        self.loop_obj = SystemAudioLoop(**self._loop_kwargs)
                else:
                    self.log_queue.put("[hata] Bağlantı kurulamadı.\n")
                    break
        self.log_queue.put("__stopped__")

    def stop(self):
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
        dark_titlebar(pop)
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
        pop.configure(bg="#0c0c0c")
        self.overlay_btn.configure(fg=C.live)

        def start_move(e):
            pop._drag_x = e.x_root - pop.winfo_x()
            pop._drag_y = e.y_root - pop.winfo_y()

        def do_move(e):
            x = e.x_root - pop._drag_x
            y = e.y_root - pop._drag_y
            pop.geometry(f"+{x}+{y}")

        wrap = tk.Frame(pop, bg="#0c0c0c", highlightthickness=1, highlightbackground=C.line, bd=0)
        wrap.pack(fill=tk.BOTH, expand=True)

        close_btn = tk.Label(wrap, text="✕", font=self.font_ui, fg=C.dim, bg="#0c0c0c", cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=8, pady=4, anchor="ne")
        close_btn.bind("<Button-1>", lambda _e: self.toggle_overlay())
        close_btn.bind("<Enter>", lambda _e: close_btn.configure(fg=C.text))
        close_btn.bind("<Leave>", lambda _e: close_btn.configure(fg=C.dim))

        lines = [l.strip() for l in self.trans.get("1.0", "end").splitlines() if l.strip()]
        cur_text = lines[-1] if lines else "..."

        self.overlay_label = tk.Label(
            wrap,
            text=cur_text,
            font=(self.font_brand[0], 12, "bold"),
            fg="#ffffff",
            bg="#0c0c0c",
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
        self.destroy()
