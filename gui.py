"""Canlı çeviri için masaüstü arayüz (tkinter, ek bağımlılık yok).

Kullanım:
    python gui.py
"""

import asyncio
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import soundcard as sc

from live_translate import SystemAudioLoop, pick_loopback

LANGS = {
    "İngilizce": "en",
    "Türkçe": "tr",
    "Almanca": "de",
    "Fransızca": "fr",
    "İspanyolca": "es",
    "İtalyanca": "it",
    "Portekizce": "pt",
    "Rusça": "ru",
    "Arapça": "ar",
    "Felemenkçe": "nl",
    "Japonca": "ja",
    "Çince": "zh",
    "Korece": "ko",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Canlı Çeviri")
        self.geometry("900x560")
        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.loop_obj: SystemAudioLoop | None = None
        self.inputs: list = []
        self.outputs: list = []
        self._build()
        self.refresh_devices()
        self.after(120, self._pump_log)

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.X, **pad)

        ttk.Label(frm, text="Giriş (kaynak):").grid(row=0, column=0, sticky=tk.W)
        self.in_var = tk.StringVar()
        self.in_box = ttk.Combobox(frm, textvariable=self.in_var, state="readonly", width=48)
        self.in_box.grid(row=0, column=1, sticky=tk.EW, **pad)

        ttk.Label(frm, text="Çıkış (hoparlör):").grid(row=1, column=0, sticky=tk.W)
        self.out_var = tk.StringVar()
        self.out_box = ttk.Combobox(frm, textvariable=self.out_var, state="readonly", width=48)
        self.out_box.grid(row=1, column=1, sticky=tk.EW, **pad)
        frm.columnconfigure(1, weight=1)

        lang = ttk.Frame(self)
        lang.pack(fill=tk.X, **pad)
        ttk.Label(lang, text="Kaynak dil:").pack(side=tk.LEFT)
        self.src_var = tk.StringVar(value="İngilizce")
        ttk.Combobox(lang, textvariable=self.src_var, values=list(LANGS), state="readonly", width=12).pack(side=tk.LEFT, padx=4)
        ttk.Label(lang, text="Hedef dil:").pack(side=tk.LEFT, padx=(12, 0))
        self.dst_var = tk.StringVar(value="Türkçe")
        ttk.Combobox(lang, textvariable=self.dst_var, values=list(LANGS), state="readonly", width=12).pack(side=tk.LEFT, padx=4)

        key = ttk.Frame(self)
        key.pack(fill=tk.X, **pad)
        ttk.Label(key, text="API anahtarı:").pack(side=tk.LEFT)
        self.key_var = tk.StringVar(value=os.environ.get("GEMINI_API_KEY", ""))
        ttk.Entry(key, textvariable=self.key_var, show="•", width=44).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, **pad)
        self.start_btn = ttk.Button(btns, text="Başlat", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(btns, text="Durdur", command=self.stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Aygıtları Yenile", command=self.refresh_devices).pack(side=tk.LEFT, padx=4)
        self.status = ttk.Label(btns, text="hazır")
        self.status.pack(side=tk.RIGHT, padx=4)

        panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        heard_f = ttk.Labelframe(panes, text="Duyulan")
        trans_f = ttk.Labelframe(panes, text="Çeviri")
        panes.add(heard_f, weight=1)
        panes.add(trans_f, weight=1)
        self.heard = tk.Text(heard_f, wrap=tk.WORD, height=16, state=tk.DISABLED)
        self.trans = tk.Text(trans_f, wrap=tk.WORD, height=16, state=tk.DISABLED)
        self.heard.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.trans.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log = tk.Text(self, state=tk.DISABLED, wrap=tk.WORD, height=4)
        self.log.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def refresh_devices(self):
        stopping = self.worker is not None and self.worker.is_alive()
        ins = [m for m in sc.all_microphones(include_loopback=True)]
        outs = list(sc.all_speakers())
        self.inputs = ins
        self.outputs = outs
        self.in_box["values"] = [
            ("[Sistem] " if m.isloopback else "[Mikrofon] ") + m.name for m in ins
        ]
        self.out_box["values"] = [s.name for s in outs]
        if not stopping:
            try:
                default_in = pick_loopback(None)
                self.in_var.set(("[Sistem] " if default_in.isloopback else "[Mikrofon] ") + default_in.name)
            except RuntimeError:
                if ins:
                    self.in_var.set(("[Sistem] " if ins[0].isloopback else "[Mikrofon] ") + ins[0].name)
            try:
                self.out_var.set(sc.default_speaker().name)
            except Exception:
                if outs:
                    self.out_var.set(outs[0].name)

    def _append(self, text: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _write_pane(self, widget, text: str):
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, text)
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _clear_pane(self, widget):
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.configure(state=tk.DISABLED)

    def _pump_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__stopped__":
                    self.start_btn.configure(state=tk.NORMAL)
                    self.stop_btn.configure(state=tk.DISABLED)
                    self.status.configure(text="durdu")
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

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        api_key = self.key_var.get().strip()
        if not api_key:
            self._append("[hata] API anahtarı girin (https://aistudio.google.com/apikey)\n")
            return
        try:
            source = self.inputs[self.in_box.current()]
            speaker = self.outputs[self.out_box.current()]
        except (IndexError, tk.TclError):
            self._append("[hata] Geçerli giriş/çıkış aygıtı seçin.\n")
            return
        src, dst = LANGS[self.src_var.get()], LANGS[self.dst_var.get()]
        self._clear_pane(self.heard)
        self._clear_pane(self.trans)
        self.loop_obj = SystemAudioLoop(
            src, dst, source, api_key,
            output_speaker=speaker,
            on_text=self.log_queue.put,
            console_input=False,
        )
        self._append(f"[bilgi] {source.name} -> {speaker.name} ({src}>{dst})\n")
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.status.configure(text="çalışıyor")

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
            self.status.configure(text="durduruluyor…")
            self.stop_btn.configure(state=tk.DISABLED)

    def _on_close(self):
        self.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
