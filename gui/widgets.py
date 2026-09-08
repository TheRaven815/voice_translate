"""Paylaşılan Tk widget'ları."""

from __future__ import annotations

import tkinter as tk

from .theme import C


class Select(tk.Frame):
    """Tek satırlık seçici; ttk.Combobox'un native çerçevesini taşımıyor."""

    def __init__(self, master, *, textvariable, values=(), font=None, **_):
        super().__init__(master, bg=C.line, highlightthickness=0, bd=0)
        self.var = textvariable
        self._values = list(values)
        self._state = "readonly"
        self._font = font
        self._pop: tk.Toplevel | None = None
        self._inner = tk.Frame(self, bg=C.panel, bd=0, highlightthickness=0)
        self._inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._arr = tk.Label(
            self._inner, text="▾", bg=C.panel, fg=C.dim, padx=7, pady=4, font=font
        )
        self._arr.pack(side=tk.RIGHT)
        self._lbl = tk.Label(
            self._inner,
            textvariable=self.var,
            bg=C.panel,
            fg=C.text,
            anchor="w",
            padx=7,
            pady=4,
            font=font,
            width=1,
        )
        self._lbl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for w in (self, self._inner, self._lbl, self._arr):
            w.bind("<Button-1>", self._toggle)

    def current(self) -> int:
        try:
            return self._values.index(self.var.get())
        except ValueError:
            return -1

    def __setitem__(self, key, value):
        if key == "values":
            self._values = list(value)
            return
        raise KeyError(key)

    def __getitem__(self, key):
        if key == "state":
            return self._state
        if key == "values":
            return tuple(self._values)
        return super().__getitem__(key)

    def configure(self, cnf=None, **kw):  # noqa: A003
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "state" in kw:
            self._state = kw.pop("state")
            off = self._state == "disabled"
            bg = C.rail if off else C.panel
            fg = C.dim if off else C.text
            self._inner.configure(bg=bg)
            self._lbl.configure(bg=bg, fg=fg)
            self._arr.configure(bg=bg, fg=C.dim)
            if off:
                self._close()
        if kw:
            super().configure(**kw)

    def _pick(self, val: str) -> None:
        self.var.set(val)
        self._close()

    def _toggle(self, _e=None):
        if self._state == "disabled":
            return
        if self._pop is not None:
            self._close()
            return
        if not self._values:
            return
        self.update_idletasks()
        pop = tk.Toplevel(self)
        pop.wm_overrideredirect(True)
        pop.configure(bg=C.line)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        inner = tk.Frame(pop, bg=C.panel, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        row_h = 24
        visible = min(8, max(1, len(self._values)))
        host = inner
        if len(self._values) > 8:
            canvas = tk.Canvas(
                inner, bg=C.panel, highlightthickness=0, bd=0, height=visible * row_h
            )
            host = tk.Frame(canvas, bg=C.panel)
            win = canvas.create_window((0, 0), window=host, anchor="nw")
            canvas.pack(fill=tk.BOTH, expand=True)

            def _sync(_e=None):
                canvas.configure(scrollregion=canvas.bbox("all"))
                canvas.itemconfigure(win, width=max(1, canvas.winfo_width()))

            host.bind("<Configure>", _sync)
            canvas.bind("<Configure>", _sync)

            def _wheel(e):
                canvas.yview_scroll(int(-e.delta / 120), "units")
                return "break"

            canvas.bind("<MouseWheel>", _wheel)
            host.bind("<MouseWheel>", _wheel)

        cur = self.current()
        for i, v in enumerate(self._values):
            base = C.hover if i == cur else C.panel
            row = tk.Label(
                host,
                text=v,
                bg=base,
                fg=C.text,
                anchor="w",
                padx=8,
                pady=3,
                font=self._font,
            )
            row.pack(fill=tk.X)
            row.bind("<Button-1>", lambda _e, val=v: self._pick(val))
            row.bind("<Enter>", lambda _e, r=row: r.configure(bg=C.hover))
            row.bind("<Leave>", lambda _e, r=row, b=base: r.configure(bg=b))
            if len(self._values) > 8:
                row.bind("<MouseWheel>", _wheel)

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() - 1
        w = self.winfo_width()
        h = row_h * visible + 2
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.bind("<Escape>", lambda _e: self._close())
        self._pop = pop
        pop.focus_set()
        pop.grab_set()
        pop.after(80, lambda: pop.bind("<FocusOut>", lambda _e: self._close()))

    def _close(self):
        if self._pop is None:
            return
        pop = self._pop
        self._pop = None
        try:
            pop.grab_release()
        except tk.TclError:
            pass
        try:
            pop.destroy()
        except tk.TclError:
            pass
