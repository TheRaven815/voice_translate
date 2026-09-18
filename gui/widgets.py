"""Paylaşılan Tk widget'ları."""

from __future__ import annotations

import time
import tkinter as tk
import tkinter.font as tkfont

from .theme import C

class Select(tk.Frame):
    """Tek satırlık seçici; ttk.Combobox'un native çerçevesini taşımıyor."""

    _open: Select | None = None

    def __init__(self, master, *, textvariable, values=(), font=None, **_):
        super().__init__(master, bg=C.line, highlightthickness=1, highlightbackground=C.line, highlightcolor=C.fill, bd=0, takefocus=1)
        self.var = textvariable
        self._values = list(values)
        self._state = "readonly"
        self._font = font
        self._top_bindings: list[tuple[tk.Misc, str, str]] = []
        self._last_top_geom: tuple[int, int, int, int] | None = None
        self._pop: tk.Toplevel | None = None
        self._rows: list[tk.Label] = []
        self._highlight_idx: int = -1
        self._canvas: tk.Canvas | None = None
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

        self.bind("<FocusIn>", lambda _e: self._on_focus_in())
        self.bind("<FocusOut>", lambda _e: self._on_focus_out())
        self.bind("<Up>", self._on_key_up)
        self.bind("<Down>", self._on_key_down)
        self.bind("<Return>", self._on_key_enter)
        self.bind("<KP_Enter>", self._on_key_enter)
        self.bind("<space>", self._on_key_space)
        self.bind("<Escape>", lambda _e: self._close())
        self.bind("<Key>", self._on_key_char)
    def current(self) -> int:
        try:
            return self._values.index(self.var.get())
        except ValueError:
            return -1

    def __setitem__(self, key, value):
        if key == "values":
            self._values = list(value)
            return
        if key == "state":
            self.configure(state=value)
            return
        super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == "state":
            return self._state
        if key == "values":
            return tuple(self._values)
        return super().__getitem__(key)

    def configure(self, cnf=None, **kw):  # noqa: A003
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "values" in kw:
            self._values = list(kw.pop("values"))
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

    def update_theme(self) -> None:
        super().configure(bg=C.line)
        off = self._state == "disabled"
        bg = C.rail if off else C.panel
        fg = C.dim if off else C.text
        self._inner.configure(bg=bg)
        self._lbl.configure(bg=bg, fg=fg)
        self._arr.configure(bg=bg, fg=C.dim)

    def _pick(self, val: str) -> None:
        self.var.set(val)
        self._close()

    def _on_focus_in(self):
        self.configure(bg=C.fill)

    def _on_focus_out(self):
        self.configure(bg=C.line)

    def _set_popup_highlight(self, idx: int) -> None:
        if not self._rows:
            return
        idx = max(0, min(len(self._rows) - 1, idx))
        if 0 <= self._highlight_idx < len(self._rows):
            self._rows[self._highlight_idx].configure(bg=C.panel)
        self._highlight_idx = idx
        self._rows[idx].configure(bg=C.hover)
        if self._canvas is not None and len(self._rows) > 1:
            self._canvas.yview_moveto(idx / len(self._rows))

    def _on_key_down(self, _e=None):
        if self._state == "disabled" or not self._values:
            return "break"
        if self._pop is not None:
            self._set_popup_highlight(self._highlight_idx + 1)
        else:
            cur = self.current()
            next_idx = min(len(self._values) - 1, cur + 1) if cur >= 0 else 0
            self.var.set(self._values[next_idx])
        return "break"

    def _on_key_up(self, _e=None):
        if self._state == "disabled" or not self._values:
            return "break"
        if self._pop is not None:
            self._set_popup_highlight(self._highlight_idx - 1)
        else:
            cur = self.current()
            prev_idx = max(0, cur - 1) if cur >= 0 else 0
            self.var.set(self._values[prev_idx])
        return "break"

    def _on_key_enter(self, _e=None):
        if self._state == "disabled":
            return "break"
        if self._pop is not None:
            if 0 <= self._highlight_idx < len(self._values):
                self._pick(self._values[self._highlight_idx])
            else:
                self._close()
        else:
            self._toggle()
        return "break"

    def _on_key_space(self, _e=None):
        if self._state == "disabled":
            return "break"
        if self._pop is None:
            self._toggle()
            return "break"
        return None

    def _on_key_char(self, e):
        if self._state == "disabled" or not e.char or not self._values:
            return
        ch = e.char.lower()
        if not ch.isalnum():
            return
        for i, val in enumerate(self._values):
            if str(val).lower().startswith(ch):
                if self._pop is not None:
                    self._set_popup_highlight(i)
                else:
                    self.var.set(val)
                break

    def _toggle(self, _e=None):
        if self._state == "disabled":
            return
        if self._pop is not None:
            self._close()
            return
        if Select._open is not None:
            Select._open._close()
        if not self._values:
            return
        pop = tk.Toplevel(self)
        pop.wm_overrideredirect(True)
        pop.configure(bg=C.line)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        inner = tk.Frame(pop, bg=C.panel, bd=0, highlightthickness=0)
        inner.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        font_obj = tkfont.Font(self, font=self._font)
        linespace = font_obj.metrics("linespace")
        row_h = max(24, linespace + 8)

        screen_h = self.winfo_screenheight()
        btn_y = self.winfo_rooty()
        btn_h = max(1, self.winfo_height())
        space_below = screen_h - (btn_y + btn_h) if screen_h > 0 else 500
        space_above = btn_y if screen_h > 0 else 500
        max_visible_below = max(2, int((space_below - 20) / row_h)) if space_below > 0 else 2
        max_visible_above = max(2, int((space_above - 20) / row_h)) if space_above > 0 else 2

        if space_below < (min(8, len(self._values)) * row_h + 10) and space_above > space_below:
            max_visible = max_visible_above
            open_above = True
        else:
            max_visible = max_visible_below
            open_above = False

        visible = min(8, max_visible, max(1, len(self._values)))
        needs_scroll = len(self._values) > visible
        host = inner
        if needs_scroll:
            canvas = tk.Canvas(
                inner, bg=C.panel, highlightthickness=0, bd=0, height=visible * row_h
            )
            self._canvas = canvas
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
        self._rows.clear()
        self._highlight_idx = cur if cur >= 0 else 0
        for i, v in enumerate(self._values):
            base = C.hover if i == self._highlight_idx else C.panel
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
            self._rows.append(row)
            row.bind("<Button-1>", lambda _e, val=v: self._pick(val))
            row.bind("<Enter>", lambda _e, idx=i: self._set_popup_highlight(idx))
            if needs_scroll:
                row.bind("<MouseWheel>", _wheel)
        x = self.winfo_rootx()
        y = (btn_y - (row_h * visible + 2) + 1) if open_above else (btn_y + btn_h - 1)
        text_w = max((font_obj.measure(str(v)) for v in self._values), default=0) + 24
        w = max(self.winfo_width(), text_w)
        screen_w = self.winfo_screenwidth()
        if screen_w > 0 and x + w > screen_w and self.winfo_rootx() >= 0:
            x = self.winfo_rootx() + self.winfo_width() - w
        elif self.winfo_rootx() < 0 and (x + w) > 0:
            x = self.winfo_rootx() + self.winfo_width() - w
        h = row_h * visible + 2
        if screen_h > 0:
            if y + h > screen_h:
                y = max(0, screen_h - h - 8)
            if y < 0:
                y = 0
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.bind("<Escape>", lambda _e: self._close())
        pop.bind("<Up>", self._on_key_up)
        pop.bind("<Down>", self._on_key_down)
        pop.bind("<Return>", self._on_key_enter)
        pop.bind("<KP_Enter>", self._on_key_enter)
        pop.bind("<Key>", self._on_key_char)
        self._pop = pop
        Select._open = self
        pop.after_idle(self._arm_dismiss)

    def _arm_dismiss(self) -> None:
        if self._pop is None:
            return
        top = self.winfo_toplevel()
        self._armed_time = time.monotonic()
        self._last_top_geom = (top.winfo_x(), top.winfo_y(), top.winfo_width(), top.winfo_height())
        for seq, cb in (
            ("<Button-1>", self._on_global_click),
            ("<Escape>", self._on_escape),
            ("<FocusOut>", self._on_top_event),
            ("<Unmap>", self._on_top_event),
            ("<Configure>", self._on_top_event),
        ):
            bid = top.bind(seq, cb, add="+")
            self._top_bindings.append((top, seq, bid))
    def _inside_pop_rect(self) -> bool:
        if self._pop is None:
            return False
        try:
            px, py = self._pop.winfo_rootx(), self._pop.winfo_rooty()
            pw, ph = self._pop.winfo_width(), self._pop.winfo_height()
            mx, my = self.winfo_pointerx(), self.winfo_pointery()
            return px - 2 <= mx <= px + pw + 2 and py - 2 <= my <= py + ph + 2
        except tk.TclError:
            return False

    def _on_top_event(self, e) -> None:
        if self._pop is None:
            return
        top = self.winfo_toplevel()
        if e.widget == top:
            if e.type == tk.EventType.Configure:
                geom = (top.winfo_x(), top.winfo_y(), top.winfo_width(), top.winfo_height())
                if geom != self._last_top_geom:
                    self._close()
            elif e.type == tk.EventType.FocusOut:
                if time.monotonic() - getattr(self, "_armed_time", 0.0) < 0.05:
                    return
                try:
                    focused = self.focus_get()
                except (KeyError, tk.TclError):
                    focused = None
                if focused is not None and self._inside(focused, self._pop):
                    return
                if self._inside_pop_rect():
                    return
                self._close()
            else:
                self._close()
    def _on_escape(self, _e=None):
        self._close()
        return "break"

    def _on_global_click(self, e):
        if self._pop is None:
            return
        w = e.widget
        if isinstance(w, str):
            try:
                w = self.nametowidget(w)
            except tk.TclError:
                self._close()
                return
        if self._inside(w, self._pop) or self._inside(w, self):
            return
        self._close()

    def _inside(self, widget, ancestor) -> bool:
        w = widget
        while w:
            if w == ancestor:
                return True
            try:
                parent = w.nametowidget(w.winfo_parent())
            except (tk.TclError, KeyError, AttributeError):
                break
            if parent is w:
                break
            w = parent
        return False

    def _close(self):
        if self._pop is None:
            return
        for top, seq, bid in self._top_bindings:
            try:
                top.unbind(seq, bid)
            except tk.TclError:
                pass
        self._top_bindings.clear()
        self._rows.clear()
        self._canvas = None
        self._highlight_idx = -1
        pop = self._pop
        self._pop = None
        if Select._open is self:
            Select._open = None
        if pop is not None:
            try:
                pop.destroy()
            except tk.TclError:
                pass
