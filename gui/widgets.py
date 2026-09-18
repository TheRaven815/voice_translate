"""Paylaşılan Tk widget'ları."""

from __future__ import annotations

import math
import time
import tkinter as tk
import tkinter.font as tkfont

from .theme import C


def _hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def mix(a: str, b: str, t: float) -> str:
    """İki hex rengi karıştırır (t=0 -> a, t=1 -> b)."""
    ar, ag, ab = _hex_rgb(a)
    br, bg, bb = _hex_rgb(b)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    bl = round(ab + (bb - ab) * t)
    return f"#{r:02x}{g:02x}{bl:02x}"


def _rounded_rect_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    """Saat yönünde yumuşatılmış köşe noktaları (smooth polygon için)."""
    pts: list[float] = []
    corners = (
        (x2 - r, y1 + r, -90.0),   # ust sag
        (x2 - r, y2 - r, 0.0),     # alt sag
        (x1 + r, y2 - r, 90.0),    # alt sol
        (x1 + r, y1 + r, 180.0),   # ust sol
    )
    for cx, cy, start in corners:
        for i in range(5):
            ang = math.radians(start + i * 22.5)
            pts.extend((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


class IconButton(tk.Canvas):
    """Vektör ikonlu, uniform 24px kare basma alanlı düğme.

    Unicode/emoji glyph'lerin fonta ve platforma göre kaymasını önlemek için
    tüm ikonlar Canvas üzerinde çizilir.
    """

    SIZE = 24

    def __init__(self, master, kind: str, command, *, tooltip: str = "", bg: str | None = None):
        self._bg = bg or C.rail
        super().__init__(
            master,
            width=self.SIZE,
            height=self.SIZE,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=0,
        )
        self.kind = kind
        self._command = command
        self._enabled = True
        self._hover = False
        self._accent = False
        self.tooltip = tooltip
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.redraw()

    def configure(self, cnf=None, **kw):  # noqa: A003
        bg = kw.pop("bg", None)
        if isinstance(cnf, dict):
            bg = cnf.pop("bg", bg)
            kw = {**cnf, **kw}
        if bg is not None:
            self._bg = bg
            super().configure(bg=bg)
            self.redraw()
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):
        if key == "bg":
            return self._bg
        return super().cget(key)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.redraw()

    def set_accent(self, accent: bool) -> None:
        """Aktif/etkin durum göstergesi (ör. sabitlenmiş pencere)."""
        self._accent = accent
        self.redraw()

    def _on_click(self, _e):
        if self._enabled:
            self._command()

    def _on_enter(self, _e):
        self._hover = True
        self.redraw()

    def _on_leave(self, _e):
        self._hover = False
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        if not self._enabled:
            fg = C.dim
        elif self._accent:
            fg = C.accent if not self._hover else mix(C.accent, C.text, 0.3)
        elif self._hover:
            fg = C.text
        else:
            fg = C.dim
        self._draw_icon(fg)

    def update_theme(self) -> None:
        self.configure(bg=self._bg)

    def _draw_icon(self, fg: str) -> None:
        getattr(self, f"_glyph_{self.kind}", self._glyph_info)(fg)

    # -- 24x24 icerisinde izdusumlu ikonlar (merkez 12,12) ----------------

    def _glyph_pin(self, fg: str) -> None:
        # Harita pini: yuvarlak bas + sivri alt uc + ic delik
        cx, cy, r = 12.0, 9.6, 5.0
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fg, outline="")
        self.create_polygon(
            cx - 3.4, cy + r * 0.72, cx + 3.4, cy + r * 0.72, cx, 20.0,
            fill=fg, outline="",
        )
        hole = mix(fg, self._bg, 0.85)
        self.create_oval(cx - 1.8, cy - 1.8, cx + 1.8, cy + 1.8, fill=hole, outline="")

    def _glyph_close(self, fg: str) -> None:
        self.create_line(7.5, 7.5, 16.5, 16.5, fill=fg, width=1.7, capstyle=tk.ROUND)
        self.create_line(16.5, 7.5, 7.5, 16.5, fill=fg, width=1.7, capstyle=tk.ROUND)

    def _glyph_eye(self, fg: str) -> None:
        # Goz: iki yaydan lens + iris
        self.create_arc(4.5, 5.5, 19.5, 18.5, start=25, extent=130, style=tk.ARC, outline=fg, width=1.5)
        self.create_arc(4.5, 5.5, 19.5, 18.5, start=205, extent=130, style=tk.ARC, outline=fg, width=1.5)
        self.create_oval(10.3, 10.3, 13.7, 13.7, fill=fg, outline="")

    def _glyph_eye_off(self, fg: str) -> None:
        self._glyph_eye(fg)
        self.create_line(5.5, 18.5, 18.5, 5.5, fill=fg, width=1.6, capstyle=tk.ROUND)

    def _glyph_target(self, fg: str) -> None:
        self.create_oval(5.5, 5.5, 18.5, 18.5, outline=fg, width=1.5)
        self.create_oval(10.4, 10.4, 13.6, 13.6, fill=fg, outline="")

    def _glyph_cursor(self, fg: str) -> None:
        self.create_polygon(
            7.0, 4.5, 7.0, 18.5, 10.6, 15.4, 13.0, 19.6, 15.2, 18.3, 12.8, 14.2, 17.6, 14.2,
            fill=fg, outline="",
        )

    def _glyph_gear(self, fg: str) -> None:
        cx = cy = 12.0
        teeth = 8
        r_out, r_in = 7.6, 5.6
        half_out, half_in = math.radians(11.0), math.radians(12.5)
        pts: list[float] = []
        for i in range(teeth):
            ang = math.radians(i * (360.0 / teeth) - 90.0)
            pts.extend((cx + r_in * math.cos(ang - half_in), cy + r_in * math.sin(ang - half_in)))
            pts.extend((cx + r_out * math.cos(ang - half_out), cy + r_out * math.sin(ang - half_out)))
            pts.extend((cx + r_out * math.cos(ang + half_out), cy + r_out * math.sin(ang + half_out)))
            pts.extend((cx + r_in * math.cos(ang + half_in), cy + r_in * math.sin(ang + half_in)))
        self.create_polygon(*pts, fill="", outline=fg, width=1.4, joinstyle=tk.MITER)
        self.create_oval(cx - 2.8, cy - 2.8, cx + 2.8, cy + 2.8, outline=fg, width=1.4)

    def _glyph_info(self, fg: str) -> None:
        self.create_oval(5, 5, 19, 19, outline=fg, width=1.5)
        self.create_oval(11.2, 8.2, 12.8, 9.8, fill=fg, outline="")
        self.create_line(12, 12.4, 12, 15.6, fill=fg, width=1.8, capstyle=tk.ROUND)

    def _glyph_swap(self, fg: str) -> None:
        # Iki yonlu ok (ust saga, alt sola)
        self.create_line(6, 9, 18, 9, fill=fg, width=1.6, capstyle=tk.ROUND)
        self.create_line(15, 6, 18, 9, fill=fg, width=1.6, capstyle=tk.ROUND)
        self.create_line(15, 12, 18, 9, fill=fg, width=1.6, capstyle=tk.ROUND)
        self.create_line(18, 15, 6, 15, fill=fg, width=1.6, capstyle=tk.ROUND)
        self.create_line(9, 12, 6, 15, fill=fg, width=1.6, capstyle=tk.ROUND)
        self.create_line(9, 18, 6, 15, fill=fg, width=1.6, capstyle=tk.ROUND)

    def _glyph_subtitle(self, fg: str) -> None:
        # Altyazi balonu: konusma balonu + iki satir
        self.create_polygon(
            *_rounded_rect_points(4.0, 5.5, 20.0, 16.5, 3.0),
            fill="", outline=fg, width=1.5, smooth=True,
        )
        self.create_polygon(9.0, 16.2, 13.5, 16.2, 9.0, 20.0, fill=fg, outline="")
        self.create_line(7.6, 9.3, 16.4, 9.3, fill=fg, width=1.5, capstyle=tk.ROUND)
        self.create_line(7.6, 12.7, 13.2, 12.7, fill=fg, width=1.5, capstyle=tk.ROUND)


class ThemeSwitch(tk.Canvas):
    """Güneş/ay teması için hap şeklinde kayar düğme.

    Konum, font bağımsız vektör çizimle belirlenir: koyu temada top solda
    (hilal), açık temada sağda (güneş). Geçişte top kısa bir animasyonla kayar.
    """

    W, H = 40, 22
    _STEPS = 6
    _DELAY_MS = 16

    def __init__(self, master, command, *, bg: str | None = None):
        self._bg = bg or C.rail
        super().__init__(
            master,
            width=self.W,
            height=self.H,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=0,
        )
        self._command = command
        self._anim_after: str | None = None
        # 0.0 = koyu (top solda), 1.0 = açık (top sağda)
        self._pos = 1.0 if C.current == "light" else 0.0
        self.bind("<Button-1>", lambda _e: self._command())
        self.bind("<Enter>", lambda _e: self._draw(hover=True))
        self.bind("<Leave>", lambda _e: self._draw(hover=False))
        self._draw()

    def configure(self, cnf=None, **kw):  # noqa: A003
        bg = kw.pop("bg", None)
        if isinstance(cnf, dict):
            bg = cnf.pop("bg", bg)
            kw = {**cnf, **kw}
        if bg is not None:
            self._bg = bg
            super().configure(bg=bg)
            self._draw()
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):
        if key == "bg":
            return self._bg
        return super().cget(key)

    def _target(self) -> float:
        return 1.0 if C.current == "light" else 0.0

    def sync(self, animate: bool = True) -> None:
        """Mevcut tema konumuna getirir; tema değişiminde animasyonla kayar."""
        target = self._target()
        if self._anim_after is not None:
            try:
                self.after_cancel(self._anim_after)
            except tk.TclError:
                pass
            self._anim_after = None
        if not animate or abs(target - self._pos) < 1e-6:
            self._pos = target
            self._draw()
            return
        step = (target - self._pos) / self._STEPS

        def _tick(remaining: int) -> None:
            self._anim_after = None
            if remaining <= 1:
                self._pos = self._target()
                self._draw()
                return
            self._pos += step
            self._draw()
            self._anim_after = self.after(self._DELAY_MS, lambda: _tick(remaining - 1))

        self._anim_after = self.after(self._DELAY_MS, lambda: _tick(self._STEPS))

    def update_theme(self) -> None:
        super().configure(bg=self._bg)
        self._draw()

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        w, h = self.W, self.H
        r = h / 2 - 1.5
        track = C.hover if not hover else mix(C.hover, C.text, 0.08)
        self.create_polygon(
            *_rounded_rect_points(1.5, 1.5, w - 1.5, h - 1.5, r),
            fill=track, outline=C.line, width=1, smooth=True,
        )
        pad = 4.0
        knob_r = h / 2 - pad - 0.5
        x_min, x_max = pad + knob_r, w - pad - knob_r
        cx = x_min + (x_max - x_min) * self._pos
        cy = h / 2
        self.create_oval(cx - knob_r, cy - knob_r, cx + knob_r, cy + knob_r, fill=C.fill, outline="")
        glyph = C.fill_fg
        # pos=1 (açık) -> güneş, pos=0 (koyu) -> hilal
        self._draw_moon(cx, cy, knob_r, glyph, alpha=1.0 - self._pos)
        self._draw_sun(cx, cy, knob_r, glyph, alpha=self._pos)

    def _draw_moon(self, cx: float, cy: float, knob_r: float, color: str, alpha: float) -> None:
        if alpha <= 0.0:
            return
        col = mix(C.fill, color, alpha)
        r = knob_r * 0.62
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="")
        bite = r * 0.88
        bx = cx + r * 0.95
        by = cy - r * 0.28
        self.create_oval(bx - bite, by - bite, bx + bite, by + bite, fill=C.fill, outline="")

    def _draw_sun(self, cx: float, cy: float, knob_r: float, color: str, alpha: float) -> None:
        if alpha <= 0.0:
            return
        col = mix(C.fill, color, alpha)
        r = knob_r * 0.30
        self.create_oval(cx - r, cy - r, cx + r, cy + r, fill=col, outline="")
        for i in range(8):
            ang = math.radians(i * 45.0)
            r1, r2 = knob_r * 0.58, knob_r * 0.80
            self.create_line(
                cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                cx + r2 * math.cos(ang), cy + r2 * math.sin(ang),
                fill=col, width=1.3, capstyle=tk.ROUND,
            )


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

    def _set_popup_highlight(self, idx: int, scroll: bool = False) -> None:
        if not self._rows:
            return
        idx = max(0, min(len(self._rows) - 1, idx))
        if 0 <= self._highlight_idx < len(self._rows):
            self._rows[self._highlight_idx].configure(bg=C.panel)
        self._highlight_idx = idx
        self._rows[idx].configure(bg=C.hover)
        # Yalnızca klavye gezintisinde görünürlüğü koru; fare hover'ında
        # listeyi asla kaydırma (eskiden yview_moveto en alta zıplatıyordu).
        if scroll and self._canvas is not None:
            row_h = max(1, self._rows[0].winfo_reqheight())
            top_f, bot_f = self._canvas.yview()
            total = len(self._rows) * row_h
            row_top = idx * row_h / total
            row_bot = (idx + 1) * row_h / total
            view = bot_f - top_f
            if row_top < top_f:
                self._canvas.yview_moveto(row_top)
            elif row_bot > bot_f:
                self._canvas.yview_moveto(max(0.0, row_bot - view))

    def _on_key_down(self, _e=None):
        if self._state == "disabled" or not self._values:
            return "break"
        if self._pop is not None:
            self._set_popup_highlight(self._highlight_idx + 1, scroll=True)
        else:
            cur = self.current()
            next_idx = min(len(self._values) - 1, cur + 1) if cur >= 0 else 0
            self.var.set(self._values[next_idx])
        return "break"

    def _on_key_up(self, _e=None):
        if self._state == "disabled" or not self._values:
            return "break"
        if self._pop is not None:
            self._set_popup_highlight(self._highlight_idx - 1, scroll=True)
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
        if self._canvas is not None and len(self._rows) > visible and self._highlight_idx >= 0:
            # Acilista secili oge gorunsun; listeyi en alta ziplatmadan
            row_top = self._highlight_idx / len(self._rows)
            self._canvas.yview_moveto(min(row_top, 1.0 - visible / len(self._rows)))
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
