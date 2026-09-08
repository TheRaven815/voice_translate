"""Ana pencere."""

from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk

from config import resolve_api_key, save_api_key
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

        rail = tk.Frame(self, bg=C.rail, width=248, bd=0, highlightthickness=0)
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

        st = tk.Frame(head, bg=C.rail)
        st.pack(anchor="w", pady=(6, 0))
        self._dot = tk.Canvas(st, width=8, height=8, bg=C.rail, highlightthickness=0, bd=0)
        self._dot.pack(side=tk.LEFT, pady=1)
        self._dot_id = self._dot.create_oval(1, 1, 7, 7, fill=C.dim, outline="")
        self.status = tk.Label(st, text="Hazır", font=self.font_ui, fg=C.muted, bg=C.rail)
        self.status.pack(side=tk.LEFT, padx=(6, 0))

        self._rail_sep(rail, 1)

        devices = tk.Frame(rail, bg=C.rail)
        devices.grid(row=2, column=0, sticky="ew", padx=16, pady=(12, 0))
        devices.columnconfigure(0, weight=1)
        tk.Label(devices, text="Aygıt", font=self.font_ui, fg=C.muted, bg=C.rail).grid(
            row=0, column=0, sticky="w"
        )
        self.refresh_btn = self._text_btn(devices, "Yenile", self.refresh_devices)
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

        self.src_var = tk.StringVar(value=AUTO_SRC)
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

        self.dst_var = tk.StringVar(value="Türkçe")
        self.dst_box = Select(
            langs, textvariable=self.dst_var, values=list(LANGS), font=self.font_ui
        )
        self.dst_box.grid(row=0, column=2, sticky="ew")

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
        tk.Label(main, text="Duyulan", font=self.font_ui, fg=C.muted, bg=C.bg).grid(
            row=0, column=0, sticky="w", padx=(16, 8), pady=(12, 6)
        )
        tk.Label(main, text="Çeviri", font=self.font_ui, fg=C.muted, bg=C.bg).grid(
            row=0, column=1, sticky="w", padx=(16, 16), pady=(12, 6)
        )

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

    def _text_btn(self, parent, label: str, command) -> tk.Label:
        w = tk.Label(parent, text=label, font=self.font_ui, fg=C.dim, bg=C.rail, cursor="hand2")
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

    def _swap_langs(self) -> None:
        if self.src_box["state"] == "disabled":
            return
        if self.src_var.get() == AUTO_SRC:
            return
        a, b = self.src_var.get(), self.dst_var.get()
        self.src_var.set(b)
        self.dst_var.set(a)

    def refresh_devices(self):
        stopping = self.worker is not None and self.worker.is_alive()
        ins = all_inputs()
        outs = all_outputs()
        self.inputs = ins
        self.outputs = outs
        self.in_box["values"] = [
            ("[Sistem] " if m.isloopback else "[Mikrofon] ") + m.name for m in ins
        ]
        self.out_box["values"] = [NONE_OUTPUT] + [s.name for s in outs]
        if not stopping:
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

    def _write_pane(self, widget, text: str):
        widget.insert(tk.END, text, ("body",))
        widget.see(tk.END)

    def _clear_pane(self, widget):
        widget.delete("1.0", tk.END)

    def _pump_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
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
                    continue
                self._append(str(msg))
        except queue.Empty:
            pass
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
        try:
            source = self.inputs[self.in_box.current()]
        except (IndexError, tk.TclError):
            self._append("[hata] Geçerli giriş aygıtı seçin.\n")
            return
        speaker = self._selected_speaker()
        try:
            save_api_key(api_key)
        except OSError:
            pass
        src, dst = source_code(self.src_var.get()), LANGS[self.dst_var.get()]
        self._clear_pane(self.heard)
        self._clear_pane(self.trans)
        self.loop_obj = SystemAudioLoop(
            src,
            dst,
            source,
            api_key,
            output_speaker=speaker,
            on_text=self.log_queue.put,
            console_input=False,
        )
        dest = speaker.name if speaker is not None else NONE_OUTPUT
        src_disp = "auto" if src is None else src
        self._append(f"[bilgi] {source.name} -> {dest} ({src_disp}>{dst})\n")
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()
        self._set_running(True)
        self._set_status("Çalışıyor", C.live)

    def _run(self):
        try:
            asyncio.run(self.loop_obj.run())
        except asyncio.CancelledError:
            pass  # normal durdurma
        except Exception as e:  # bağlantı/anahtar hatası arayüze düşsün
            self.log_queue.put(f"\n[hata] {type(e).__name__}: {e}\n")
        finally:
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
        pop.configure(bg=C.bg)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        dark_titlebar(pop)
        pop.protocol("WM_DELETE_WINDOW", self._close_about)
        for key in ("<Escape>", "<Return>", "<KP_Enter>", "<space>"):
            pop.bind(key, lambda _e: self._close_about())

        card = tk.Frame(
            pop,
            bg=C.panel,
            highlightthickness=1,
            highlightbackground=C.line,
            bd=0,
        )
        card.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        if ICON_PNG.is_file():
            try:
                raw = tk.PhotoImage(file=str(ICON_PNG))
                logo_img = raw.subsample(16, 16)
                logo = tk.Label(card, image=logo_img, bg=C.panel)
                logo.image = logo_img
                logo.pack(pady=(18, 10))
            except Exception:
                pass

        self.about_name = tk.Label(
            card,
            text=APP_TITLE,
            font=(self.font_brand[0], 15, "bold"),
            fg=C.text,
            bg=C.panel,
        )
        self.about_name.pack()

        v_frame = tk.Frame(card, bg=C.bg, highlightthickness=1, highlightbackground=C.line)
        v_frame.pack(pady=(4, 10))
        self.about_version = tk.Label(
            v_frame,
            text=f"v{__version__}",
            font=(self.font_ui[0], 8),
            fg=C.muted,
            bg=C.bg,
            padx=8,
            pady=1,
        )
        self.about_version.pack()

        desc = tk.Label(
            card,
            text="Canlı sistem-sesi çevirisi",
            font=self.font_ui,
            fg=C.muted,
            bg=C.panel,
        )
        desc.pack(pady=(0, 16))

        div = tk.Frame(card, bg=C.line, height=1)
        div.pack(fill=tk.X, padx=20, pady=(0, 14))

        dev_row = tk.Frame(card, bg=C.panel)
        dev_row.pack(pady=(0, 18))
        tk.Label(
            dev_row,
            text="Geliştirici:",
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        ).pack(side=tk.LEFT, padx=(0, 5))
        self.about_author = tk.Label(
            dev_row,
            text=APP_AUTHOR,
            font=self.font_ui,
            fg=C.text,
            bg=C.panel,
        )
        self.about_author.pack(side=tk.LEFT)

        btn_wrap = tk.Frame(card, bg=C.line, bd=0, highlightthickness=0)
        btn_wrap.pack(pady=(0, 18))
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
            padx=28,
            pady=5,
            cursor="hand2",
            takefocus=0,
            command=self._close_about,
        )
        btn.pack(padx=1, pady=1)
        btn.bind("<Enter>", lambda _e: btn.configure(bg=C.hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=C.panel))

        pop.update_idletasks()
        w = max(300, pop.winfo_reqwidth())
        h = pop.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        pop.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
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

    def _on_close(self):
        self.stop()
        self._close_about()
        for box in (self.in_box, self.out_box, self.src_box, self.dst_box):
            box._close()
        self.destroy()
