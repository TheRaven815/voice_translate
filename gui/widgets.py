"""Paylaşılan Tk widget'ları."""

from __future__ import annotations

import base64
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

_ICON_FAMILY: str | None = None
_ICON_FAMILY_PROBED = False


def _icon_family(root: tk.Misc) -> str | None:
    """En iyi yerel Windows ikon fontunu bir kez seçer."""
    global _ICON_FAMILY, _ICON_FAMILY_PROBED
    if not _ICON_FAMILY_PROBED:
        families = {name.casefold(): name for name in tkfont.families(root)}
        for candidate in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
            if match := families.get(candidate.casefold()):
                _ICON_FAMILY = match
                break
        _ICON_FAMILY_PROBED = True
    return _ICON_FAMILY


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
    """Font bağımsız yedek çizimli, net sistem ikonlu düğme."""

    SIZE = 28
    GLYPH_SIZE = 16
    _GLYPHS = {
        "pin": "\ue718",
        "close": "\ue8bb",
        "eye": "\ue890",
        "eye_off": "\ued1a",
        "target": "\uf272",
        "cursor": "\ue7c9",
        "gear": "\ue713",
        "info": "\ue946",
        "swap": "\ue8ab",
        "subtitle": "\ue8ba",
    }

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
        self._icon_font = _icon_family(self)
        self._command = command
        self._enabled = True
        self._hover = False
        self._accent = False
        self.tooltip = tooltip
        self._tip_after: str | None = None
        self._tip_win: tk.Toplevel | None = None
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
        self._hide_tip()
        if self._enabled:
            self._command()

    def _on_enter(self, _e):
        self._hover = True
        self.redraw()
        self._schedule_tip()

    def _on_leave(self, _e):
        self._hover = False
        self.redraw()
        self._hide_tip()

    def set_tooltip(self, text: str) -> None:
        """Baloncuk metnini günceller (boşsa baloncuk gösterilmez)."""
        self.tooltip = text or ""
        if not self.tooltip:
            self._hide_tip()

    # -- Hover baloncuğu (tooltip) -------------------------------------
    _TIP_DELAY_MS = 450

    def _schedule_tip(self) -> None:
        self._hide_tip()
        if not (self.tooltip or "").strip():
            return
        try:
            self._tip_after = self.after(self._TIP_DELAY_MS, self._show_tip)
        except (tk.TclError, RuntimeError):
            self._tip_after = None

    def _show_tip(self) -> None:
        self._tip_after = None
        text = (self.tooltip or "").strip()
        if not text:
            return
        try:
            if not self.winfo_exists():
                return
            # Fare hızlıca geçip gittiyse baloncuğu gösterme.
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            px, py = self.winfo_pointerx(), self.winfo_pointery()
            if not (x0 <= px <= x0 + self.winfo_width() and y0 <= py <= y0 + self.winfo_height()):
                return
        except tk.TclError:
            return
        try:
            win = tk.Toplevel(self)
            win.withdraw()
            win.wm_overrideredirect(True)
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
            win.configure(bg=C.line)
            lbl = tk.Label(
                win, text=text, bg=C.panel, fg=C.text,
                font=("Segoe UI", 8), padx=8, pady=3, justify="left",
            )
            lbl.pack(padx=1, pady=1)
            self._tip_win = win
            tx, ty = px + 12, py + 16
            win.update_idletasks()
            tw, th = win.winfo_reqwidth(), win.winfo_reqheight()
            try:
                sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
                if tx + tw > sw:
                    tx = max(0, sw - tw - 4)
                if ty + th > sh:
                    ty = max(0, py - th - 12)
            except tk.TclError:
                pass
            win.geometry(f"+{tx}+{ty}")
            win.deiconify()
        except (tk.TclError, RuntimeError):
            self._tip_win = None

    def _hide_tip(self) -> None:
        if self._tip_after is not None:
            try:
                self.after_cancel(self._tip_after)
            except (tk.TclError, RuntimeError):
                pass
            self._tip_after = None
        win, self._tip_win = self._tip_win, None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def redraw(self) -> None:
        self.delete("all")
        if not self._enabled:
            fg = C.dim
        elif self._accent:
            fg = C.accent if not self._hover else mix(C.accent, C.text, 0.3)
        elif self._hover:
            fg = C.text
        else:
            fg = C.muted
        self._draw_icon(fg)

    def update_theme(self) -> None:
        self.configure(bg=self._bg)

    def _draw_icon(self, fg: str) -> None:
        if self._icon_font and (glyph := self._GLYPHS.get(self.kind)):
            self.create_text(
                self.SIZE / 2,
                self.SIZE / 2,
                text=glyph,
                fill=fg,
                font=(self._icon_font, -self.GLYPH_SIZE),
            )
            return
        getattr(self, f"_glyph_{self.kind}", self._glyph_info)(fg)
        offset = (self.SIZE - 24) / 2
        self.move("all", offset, offset)

    # -- 24x24 yedek çizimler (IconButton içinde otomatik ortalanır) ------

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
        # Badem formu: kapalı eğri + iris. (İki ayrı yay köşelerde açık
        # kalıp bozuk görünüyordu.)
        self.create_polygon(
            4.5, 12.0, 7.5, 8.4, 12.0, 7.2, 16.5, 8.4, 19.5, 12.0,
            16.5, 15.6, 12.0, 16.8, 7.5, 15.6,
            fill="", outline=fg, width=1.6, smooth=True,
        )
        self.create_oval(10.1, 10.1, 13.9, 13.9, fill=fg, outline="")

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
    """Kenar yumuşatmalı güneş/ay tema anahtarı."""

    W, H = 44, 24
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
        self._image: tk.PhotoImage | None = None
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

    @staticmethod
    def _blend(base: tuple[int, int, int], color: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
        alpha = max(0.0, min(1.0, alpha))
        return tuple(round(a + (b - a) * alpha) for a, b in zip(base, color))

    @staticmethod
    def _circle_coverage(x: float, y: float, cx: float, cy: float, radius: float) -> float:
        return max(0.0, min(1.0, radius + 0.5 - math.hypot(x - cx, y - cy)))

    @staticmethod
    def _rounded_rect_coverage(
        x: float, y: float, x1: float, y1: float, x2: float, y2: float, radius: float
    ) -> float:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        qx = abs(x - cx) - (x2 - x1) / 2 + radius
        qy = abs(y - cy) - (y2 - y1) / 2 + radius
        distance = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius
        return max(0.0, min(1.0, 0.5 - distance))

    @staticmethod
    def _capsule_coverage(
        x: float, y: float, x1: float, y1: float, x2: float, y2: float, radius: float
    ) -> float:
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
        distance = math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))
        return max(0.0, min(1.0, radius + 0.5 - distance))

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        w, h = self.W, self.H
        track = mix(C.hover, C.text, 0.10 if hover else 0.03)
        colors = {
            "bg": _hex_rgb(self._bg),
            "line": _hex_rgb(C.line),
            "track": _hex_rgb(track),
            "shadow": _hex_rgb("#000000"),
            "knob": _hex_rgb(C.panel if C.current == "light" else C.fill),
            "glyph": _hex_rgb(C.accent if C.current == "light" else "#202226"),
        }
        knob_r = 8.5
        x_min, x_max = 12.0, w - 12.0
        cx = x_min + (x_max - x_min) * self._pos
        cy = h / 2
        moon_alpha, sun_alpha = 1.0 - self._pos, self._pos
        rows: list[str] = []

        for py in range(h):
            row: list[str] = []
            y = py + 0.5
            for px in range(w):
                x = px + 0.5
                color = colors["bg"]
                outer = self._rounded_rect_coverage(x, y, 1.0, 1.0, w - 1.0, h - 1.0, 11.0)
                color = self._blend(color, colors["line"], outer)
                inner = self._rounded_rect_coverage(x, y, 2.0, 2.0, w - 2.0, h - 2.0, 10.0)
                color = self._blend(color, colors["track"], inner)
                shadow = self._circle_coverage(x, y, cx, cy + 0.8, knob_r + 0.4)
                color = self._blend(color, colors["shadow"], shadow * (0.12 if C.current == "light" else 0.22))
                knob = self._circle_coverage(x, y, cx, cy, knob_r)
                color = self._blend(color, colors["knob"], knob)

                moon_outer = self._circle_coverage(x, y, cx - 0.4, cy, 5.0)
                moon_bite = self._circle_coverage(x, y, cx + 2.1, cy - 1.4, 4.5)
                moon = moon_outer * (1.0 - moon_bite) * moon_alpha
                color = self._blend(color, colors["glyph"], moon)

                sun = self._circle_coverage(x, y, cx, cy, 2.35)
                for i in range(8):
                    angle = math.radians(i * 45.0)
                    ray = self._capsule_coverage(
                        x,
                        y,
                        cx + 4.1 * math.cos(angle),
                        cy + 4.1 * math.sin(angle),
                        cx + 6.1 * math.cos(angle),
                        cy + 6.1 * math.sin(angle),
                        0.6,
                    )
                    sun = max(sun, ray)
                color = self._blend(color, colors["glyph"], sun * sun_alpha)
                row.append(f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}")
            rows.append("{" + " ".join(row) + "}")

        image = tk.PhotoImage(master=self, width=w, height=h)
        image.put(" ".join(rows))
        self._image = image
        self.create_image(0, 0, image=image, anchor=tk.NW)


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
        pop.withdraw()
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
        # Satır etiketi varsayılan 2 px kenarlık ve 3 px dikey iç boşluk taşır;
        # yükseklik yalnızca linespace'e göre hesaplanırsa son satır kırpılır.
        row_h = max(24, linespace + 10)

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
        pop.deiconify()
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


class CheckToggle(tk.Frame):
    """Kutu her zaman görünür.

    Windows temalı Checkbutton, özel zeminde normal halde kutuyu çizmez;
    kare yalnız hover'da çıkar. Tik de sistemin siyah boyasıyla koyu selectcolor'da kaybolur.
    """

    BOX = 14

    def __init__(self, master, text, variable, command, *, font, bg, fg):
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._text = text
        self._var = variable
        self._command = command
        self._fg = fg
        self._bg = bg
        self._hover = False
        self._box = tk.Canvas(
            self,
            width=self.BOX + 4,
            height=self.BOX + 4,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._box.pack(side=tk.LEFT, padx=(0, 8), pady=3)
        self._label = tk.Label(
            self, text=text, font=font, fg=fg, bg=bg, anchor="w", justify="left", cursor="hand2",
        )
        self._label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for widget in (self, self._box, self._label):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
        self.bind("<space>", self._on_click)
        self._trace = variable.trace_add("write", self._on_var)
        self._draw()

    def destroy(self):
        try:
            self._var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass
        super().destroy()

    def invoke(self):
        self._var.set(not bool(self._var.get()))
        if self._command:
            self._command()

    def indicator_outline(self) -> str:
        return self._outline_color()

    def indicator_fill(self) -> str:
        return C.accent if self._checked() else self._bg

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "bg":
            return self._bg
        if key == "fg":
            return self._fg
        return super().cget(key)

    def configure(self, cnf=None, **kw):  # noqa: A003
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        text = kw.pop("text", None)
        fg = kw.pop("fg", None)
        bg = kw.pop("bg", None)
        if text is not None:
            self._text = text
            self._label.configure(text=text)
        if fg is not None:
            self._fg = fg
        if bg is not None:
            self._bg = bg
            self._fg = C.text
            super().configure(bg=bg)
            self._box.configure(bg=bg)
            self._label.configure(bg=bg)
        if text is not None or fg is not None or bg is not None:
            self._draw()
        if kw:
            super().configure(**kw)

    config = configure

    def _checked(self) -> bool:
        try:
            return bool(self._var.get())
        except tk.TclError:
            return False

    def _outline_color(self) -> str:
        # Hover yalnız koyulaştırır. Kutu dinlenirken de panelden ayrılır.
        return mix(self._bg, C.text, 0.78 if self._hover else 0.55)

    def _on_click(self, _event=None):
        try:
            self.focus_set()
        except tk.TclError:
            pass
        self.invoke()
        return "break"

    def _on_enter(self, _event=None):
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None):
        if self._pointer_inside():
            return
        self._hover = False
        self._draw()

    def _pointer_inside(self) -> bool:
        try:
            widget = self.winfo_containing(*self.winfo_pointerxy())
        except tk.TclError:
            return False
        while widget is not None:
            if widget == self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_var(self, *_args):
        try:
            if self.winfo_exists():
                self._draw()
        except tk.TclError:
            pass

    def _draw(self) -> None:
        box = self._box
        box.delete("all")
        box.configure(bg=self._bg)
        self._label.configure(fg=self._fg, bg=self._bg)
        x1, y1, x2, y2 = 1.5, 1.5, self.BOX + 1.5, self.BOX + 1.5
        if self._checked():
            fill = C.accent
            box.create_rectangle(x1, y1, x2, y2, outline=fill, fill=fill, width=1)
            ink = C.fill_fg
            box.create_line(
                4.2, 8.0, 6.7, 10.7, fill=ink, width=1.8, capstyle=tk.ROUND, joinstyle=tk.ROUND,
            )
            box.create_line(
                6.7, 10.7, 11.6, 4.8, fill=ink, width=1.8, capstyle=tk.ROUND, joinstyle=tk.ROUND,
            )
            return
        box.create_rectangle(
            x1, y1, x2, y2, outline=self._outline_color(), fill=self._bg, width=1.4,
        )


class LevelSlider(tk.Canvas):
    """İnce yuvarlak yüzde kaydırıcı. Windows Scale oluğu temayı ezer."""

    H = 22

    def __init__(self, master, variable, command, *, from_=0, to=100, bg=None):
        self._bg = bg or C.panel
        self._var = variable
        self._command = command
        self._from = int(from_)
        self._to = int(to)
        self._state = tk.NORMAL
        self._hover = False
        super().__init__(
            master,
            width=160,
            height=self.H,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self._trace = variable.trace_add("write", self._on_var)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _e: self._release_drag())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Left>", lambda _e: self._nudge(-1))
        self.bind("<Right>", lambda _e: self._nudge(1))
        self._draw()

    def destroy(self):
        try:
            self._var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass
        super().destroy()

    def track_color(self) -> str:
        return self._track_color()

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "bg":
            return self._bg
        return super().cget(key)

    def configure(self, cnf=None, **kw):  # noqa: A003
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        state = kw.pop("state", None)
        bg = kw.pop("bg", None)
        if state is not None:
            self._state = tk.DISABLED if str(state) == str(tk.DISABLED) else tk.NORMAL
            super().configure(cursor="hand2" if self._enabled() else "arrow")
        if bg is not None:
            self._bg = bg
            super().configure(bg=bg)
        if kw:
            super().configure(**kw)
        if state is not None or bg is not None:
            self._draw()

    config = configure

    def _enabled(self) -> bool:
        return str(self._state) != str(tk.DISABLED)

    def _value(self) -> int:
        try:
            value = int(round(float(self._var.get())))
        except (tk.TclError, TypeError, ValueError):
            value = self._from
        return max(self._from, min(self._to, value))

    def _span(self) -> tuple[int, float, float]:
        width = self.winfo_width()
        if width <= 1:
            try:
                width = int(float(super().cget("width")))
            except (tk.TclError, TypeError, ValueError):
                width = 160
        pad = 9.0
        return width, pad, max(pad + 1.0, width - pad)

    def _x_for(self, value: int) -> float:
        _width, left, right = self._span()
        span = self._to - self._from
        t = 0.0 if span == 0 else (value - self._from) / span
        return left + max(0.0, min(1.0, t)) * (right - left)

    def _value_for(self, x: float) -> int:
        _width, left, right = self._span()
        t = 0.0 if right <= left else (x - left) / (right - left)
        t = max(0.0, min(1.0, t))
        return int(round(self._from + t * (self._to - self._from)))

    def _track_color(self) -> str:
        amount = 0.12 if not self._enabled() else (0.34 if self._hover else 0.26)
        return mix(self._bg, C.text, amount)

    def _fill_color(self) -> str:
        if not self._enabled():
            return mix(C.accent, self._bg, 0.62)
        return C.accent

    def _knob_fill(self) -> str:
        if not self._enabled():
            return mix(self._bg, C.text, 0.28)
        return C.panel if C.current == "light" else C.fill

    def _apply(self, value: int, *, notify: bool) -> None:
        value = max(self._from, min(self._to, int(value)))
        if self._value() != value:
            self._var.set(value)
        else:
            self._draw()
        if notify and self._command is not None:
            self._command(value)

    def _on_press(self, event):
        if not self._enabled():
            return "break"
        try:
            self.focus_set()
        except tk.TclError:
            pass
        self._apply(self._value_for(event.x), notify=True)
        return "break"

    def _on_drag(self, event):
        if not self._enabled():
            return "break"
        self._apply(self._value_for(event.x), notify=True)
        return "break"

    def _release_drag(self) -> None:
        self._draw()

    def _nudge(self, delta: int):
        if not self._enabled():
            return "break"
        self._apply(self._value() + delta, notify=True)
        return "break"

    def _set_hover(self, hover: bool) -> None:
        if self._hover == hover:
            return
        self._hover = hover
        self._draw()

    def _on_configure(self, event):
        if event.width > 1:
            self._draw()

    def _on_var(self, *_args):
        try:
            if self.winfo_exists():
                self._draw()
        except tk.TclError:
            pass

    def _draw(self) -> None:
        self.delete("all")
        width, left, right = self._span()
        if width <= 1 or right <= left:
            return
        cy = self.H / 2
        knob_x = self._x_for(self._value())
        track = self._track_color()
        fill = self._fill_color()
        self.create_line(left, cy, right, cy, fill=track, width=4, capstyle=tk.ROUND)
        if knob_x > left + 0.6:
            self.create_line(left, cy, knob_x, cy, fill=fill, width=4, capstyle=tk.ROUND)
        radius = 6.5
        self.create_oval(
            knob_x - radius,
            cy - radius,
            knob_x + radius,
            cy + radius,
            fill=self._knob_fill(),
            outline=fill,
            width=1.6,
        )


class TranscriptSearchBar(tk.Frame):
    """Transkript ve geçmiş panelleri için ince satır içi arama çubuğu (Ctrl+F)."""

    def __init__(
        self,
        master,
        *,
        get_targets,
        font,
        on_show=None,
        on_hide=None,
        label_text: str = "",
        prev_tip: str = "",
        next_tip: str = "",
        close_tip: str = "",
    ):
        super().__init__(master, bg=C.panel, bd=0, highlightthickness=0)
        self._get_targets = get_targets
        self._on_show = on_show
        self._on_hide = on_hide
        self._font = font
        self.is_open = False
        self.matches: list[tuple[tk.Text, str, str]] = []
        self.current_index = -1

        self._inner = tk.Frame(self, bg=C.panel, padx=12, pady=5)
        self._inner.pack(fill=tk.X)
        self._sep = tk.Frame(self, bg=C.line, height=1, bd=0, highlightthickness=0)
        self._sep.pack(fill=tk.X, side=tk.BOTTOM)

        self.close_btn = IconButton(
            self._inner, "close", self.close, bg=C.panel, tooltip=close_tip
        )
        self.close_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.next_btn = tk.Button(
            self._inner,
            text="↓",
            command=self.next_match,
            font=font,
            bg=C.panel,
            fg=C.muted,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=7,
            pady=1,
            cursor="hand2",
            takefocus=0,
        )
        self.next_btn.pack(side=tk.RIGHT, padx=(2, 0))

        self.prev_btn = tk.Button(
            self._inner,
            text="↑",
            command=self.prev_match,
            font=font,
            bg=C.panel,
            fg=C.muted,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=7,
            pady=1,
            cursor="hand2",
            takefocus=0,
        )
        self.prev_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.count_lbl = tk.Label(
            self._inner,
            text="",
            width=7,
            anchor="e",
            font=font,
            fg=C.muted,
            bg=C.panel,
        )
        self.count_lbl.pack(side=tk.RIGHT, padx=(8, 0))

        self._label = tk.Label(
            self._inner,
            text=label_text,
            font=font,
            fg=C.dim,
            bg=C.panel,
        )
        if label_text:
            self._label.pack(side=tk.LEFT, padx=(0, 8))

        self._entry_edge = tk.Frame(self._inner, bg=C.line, bd=0, highlightthickness=0)
        self._entry_edge.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.query_var = tk.StringVar(master=self, value="")
        self._search_count_var = tk.IntVar(master=self, value=0)
        self.entry = tk.Entry(
            self._entry_edge,
            textvariable=self.query_var,
            font=font,
            bg=C.bg,
            fg=C.text,
            insertbackground=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.entry.pack(fill=tk.X, padx=1, pady=1, ipady=3, ipadx=6)
        self._trace = self.query_var.trace_add("write", lambda *_: self.refresh(scroll=True))
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<KP_Enter>", self._on_return)
        self.entry.bind("<Shift-Return>", self.prev_match)
        self.entry.bind("<Escape>", self.close)
        self.entry.bind("<FocusIn>", lambda _e: self._entry_edge.configure(bg=C.accent))
        self.entry.bind("<FocusOut>", lambda _e: self._entry_edge.configure(bg=C.line))
        for btn in (self.prev_btn, self.next_btn):
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=C.hover, fg=C.text))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=C.panel, fg=C.muted))
        self._prev_tip = prev_tip
        self._next_tip = next_tip

    def destroy(self):
        try:
            self.query_var.trace_remove("write", self._trace)
        except (tk.TclError, ValueError):
            pass
        self.query_var = None  # type: ignore[assignment]
        self._search_count_var = None  # type: ignore[assignment]
        super().destroy()

    @staticmethod
    def style_text_tags(widget: tk.Text) -> None:
        hit_bg = mix(C.bg, C.accent, 0.34 if C.current == "dark" else 0.28)
        widget.tag_configure("search_hit", background=hit_bg, foreground=C.text)
        widget.tag_configure("search_current", background=C.accent, foreground=C.fill_fg)
        widget.tag_raise("search_current", "search_hit")

    def _targets(self) -> list[tk.Text]:
        result: list[tk.Text] = []
        for w in self._get_targets() or ():
            if w is None:
                continue
            try:
                if w.winfo_exists():
                    result.append(w)
            except tk.TclError:
                pass
        return result

    def _on_return(self, event=None):
        state = int(getattr(event, "state", 0) or 0)
        if state & 0x0001:
            return self.prev_match()
        return self.next_match()

    def open(self) -> str:
        if not self.is_open:
            self.is_open = True
            if self._on_show is not None:
                self._on_show()
        self.refresh(scroll=True)
        try:
            self.entry.focus_set()
            self.entry.selection_range(0, tk.END)
            self.entry.icursor(tk.END)
        except tk.TclError:
            pass
        return "break"

    def close(self, _event=None) -> str:
        if not self.is_open:
            return "break"
        self.is_open = False
        self.clear_highlights()
        if self._on_hide is not None:
            self._on_hide()
        return "break"

    def toggle(self, _event=None) -> str:
        if self.is_open:
            return self.close()
        return self.open()

    def clear_highlights(self) -> None:
        for w in self._targets():
            try:
                w.tag_remove("search_hit", "1.0", tk.END)
                w.tag_remove("search_current", "1.0", tk.END)
            except tk.TclError:
                pass
        self.matches = []
        self.current_index = -1
        try:
            if self.count_lbl.winfo_exists():
                self.count_lbl.configure(text="", fg=C.muted)
        except tk.TclError:
            pass

    def refresh(self, *, scroll: bool = True, preserve_index: bool = False) -> None:
        if not self.is_open or self.query_var is None:
            return
        query = self.query_var.get()
        targets = self._targets()
        for w in targets:
            self.style_text_tags(w)
            w.tag_remove("search_hit", "1.0", tk.END)
            w.tag_remove("search_current", "1.0", tk.END)
        if not query:
            self.matches = []
            self.current_index = -1
            self.count_lbl.configure(text="", fg=C.muted)
            return
        prev_idx = self.current_index
        found: list[tuple[tk.Text, str, str]] = []
        count_var = self._search_count_var
        for w in targets:
            pos = "1.0"
            while True:
                idx = w.search(query, pos, stopindex="end-1c", nocase=True, count=count_var)
                if not idx:
                    break
                mlen = max(1, int(count_var.get() if count_var is not None else len(query)) or len(query))
                end_idx = f"{idx}+{mlen}c"
                w.tag_add("search_hit", idx, end_idx)
                found.append((w, idx, end_idx))
                pos = end_idx
        self.matches = found
        if not found:
            self.current_index = -1
            self.count_lbl.configure(text="0/0", fg=C.warn)
            return
        if preserve_index and 0 <= prev_idx < len(found):
            self.current_index = prev_idx
        else:
            self.current_index = 0
        self._apply_current(scroll=scroll)

    def _apply_current(self, *, scroll: bool = True) -> None:
        for w in self._targets():
            w.tag_remove("search_current", "1.0", tk.END)
        if not self.matches or not (0 <= self.current_index < len(self.matches)):
            return
        w, start_idx, end_idx = self.matches[self.current_index]
        w.tag_add("search_current", start_idx, end_idx)
        w.tag_raise("search_current", "search_hit")
        self.count_lbl.configure(
            text=f"{self.current_index + 1}/{len(self.matches)}",
            fg=C.muted,
        )
        if scroll:
            w.see(start_idx)

    def next_match(self, _event=None) -> str:
        if self.matches:
            self.current_index = (self.current_index + 1) % len(self.matches)
            self._apply_current(scroll=True)
        return "break"

    def prev_match(self, _event=None) -> str:
        if self.matches:
            self.current_index = (self.current_index - 1) % len(self.matches)
            self._apply_current(scroll=True)
        return "break"

    def set_labels(self, *, label_text: str = "", close_tip: str = "") -> None:
        self._label.configure(text=label_text)
        if label_text and not self._label.winfo_manager():
            self._label.pack(side=tk.LEFT, padx=(0, 8), before=self._entry_edge)
        elif not label_text and self._label.winfo_manager():
            self._label.pack_forget()
        self.close_btn.set_tooltip(close_tip)

    def update_theme(self) -> None:
        super().configure(bg=C.panel)
        self._inner.configure(bg=C.panel)
        self._sep.configure(bg=C.line)
        self._label.configure(bg=C.panel, fg=C.dim)
        focused = False
        try:
            focused = self.focus_get() is self.entry
        except (KeyError, tk.TclError):
            focused = False
        self._entry_edge.configure(bg=C.accent if focused else C.line)
        self.entry.configure(
            bg=C.bg,
            fg=C.text,
            insertbackground=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
        )
        self.count_lbl.configure(
            bg=C.panel,
            fg=C.warn if (self.query_var is not None and self.query_var.get() and not self.matches) else C.muted,
        )
        for btn in (self.prev_btn, self.next_btn):
            btn.configure(bg=C.panel, fg=C.muted, activebackground=C.hover, activeforeground=C.text)
        self.close_btn.configure(bg=C.panel)
        for w in self._targets():
            self.style_text_tags(w)


class AppPickerList(tk.Frame):
    """Uygulama seçici için 16x16 ikon destekli, tema uyumlu ve Listbox API'siyle uyumlu liste."""

    def __init__(
        self,
        master,
        *,
        height: int = 6,
        font=None,
        bg: str | None = None,
        fg: str | None = None,
        selectbackground: str | None = None,
        selectforeground: str | None = None,
        cursor: str = "hand2",
        **_unused,
    ):
        self._bg = bg or C.panel
        self._fg = fg or C.text
        self._select_bg = selectbackground or C.select
        self._select_fg = selectforeground or C.text
        self._font = font or ("Segoe UI", 10)
        self._visible_rows = max(1, int(height))
        self._state = tk.NORMAL
        self._items: list[tuple[str, tk.PhotoImage | None]] = []
        self._icon_refs: list[tk.PhotoImage] = []
        self._selected: int = -1
        self._active: int = 0
        self._hover: int = -1

        super().__init__(master, bg=self._bg, bd=0, highlightthickness=0, takefocus=1)
        f_obj = tkfont.Font(self, font=self._font)
        self._row_h = max(26, int(f_obj.metrics("linespace")) + 10)

        self._canvas = tk.Canvas(
            self,
            bg=self._bg,
            bd=0,
            highlightthickness=0,
            width=340,
            height=self._visible_rows * self._row_h,
            cursor=cursor,
            takefocus=1,
        )
        self._scroll = tk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self._canvas.yview,
            width=10,
            bg=self._bg,
            troughcolor=C.rail,
            activebackground=C.hover,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self._canvas.configure(yscrollcommand=self._scroll.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas.bind("<Configure>", lambda _e: self._redraw())
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)
        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Leave>", self._on_leave)
        self._canvas.bind("<MouseWheel>", self._on_wheel)
        for seq, handler in (
            ("<Up>", lambda _e: self._move_selection(-1)),
            ("<Down>", lambda _e: self._move_selection(1)),
            ("<Home>", lambda _e: self._set_selection_from_user(0)),
            ("<End>", lambda _e: self._set_selection_from_user(max(0, len(self._items) - 1))),
            ("<Return>", self._on_return),
            ("<KP_Enter>", self._on_return),
        ):
            self.bind(seq, handler)
            self._canvas.bind(seq, handler)

    def focus_set(self) -> None:
        self._canvas.focus_set()

    def _resolve_index(self, index) -> int:
        if index == tk.END or str(index) == "end":
            return len(self._items)
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return 0
        if idx < 0:
            idx = max(0, len(self._items) + idx)
        return idx

    def size(self) -> int:
        return len(self._items)

    def icon_count(self) -> int:
        return sum(1 for _label, img in self._items if img is not None)

    def insert(self, index, *elements, icon: tk.PhotoImage | None = None) -> None:
        pos = min(len(self._items), max(0, self._resolve_index(index)))
        if icon is not None:
            self._icon_refs.append(icon)
        for offset, elem in enumerate(elements):
            self._items.insert(pos + offset, (str(elem), icon if offset == 0 else None))
        self._sync_height_and_scroll()
        self._redraw()

    def insert_with_icon(self, text: str, png_bytes: bytes | None = None) -> None:
        icon_img: tk.PhotoImage | None = None
        if png_bytes:
            try:
                encoded = base64.b64encode(png_bytes).decode("ascii")
                icon_img = tk.PhotoImage(master=self, data=encoded)
            except tk.TclError:
                icon_img = None
        self.insert(tk.END, text, icon=icon_img)

    def delete(self, first, last=None) -> None:
        if not self._items:
            return
        start = max(0, self._resolve_index(first))
        if last is None:
            if start < len(self._items):
                self._items.pop(start)
        else:
            end = len(self._items) if (last == tk.END or str(last) == "end") else self._resolve_index(last) + 1
            del self._items[start:max(start, end)]
        if not self._items:
            self._icon_refs.clear()
            self._selected = -1
            self._hover = -1
            self._active = 0
        elif self._selected >= len(self._items):
            self._selected = len(self._items) - 1
        self._sync_height_and_scroll()
        self._redraw()

    def get(self, first, last=None):
        start = max(0, self._resolve_index(first))
        if last is None:
            return self._items[start][0] if 0 <= start < len(self._items) else ""
        if last == tk.END or str(last) == "end":
            end = len(self._items)
        else:
            end = min(len(self._items), self._resolve_index(last) + 1)
        return tuple(label for label, _img in self._items[start:max(start, end)])

    def curselection(self) -> tuple[int, ...]:
        if self._state != tk.DISABLED and 0 <= self._selected < len(self._items):
            return (self._selected,)
        return ()

    def selection_clear(self, first=0, last=None) -> None:
        if self._selected < 0:
            return
        start = self._resolve_index(first)
        end = len(self._items) if (last in (None, tk.END) or str(last) == "end") else self._resolve_index(last)
        if start <= self._selected <= end:
            self._selected = -1
            self._redraw()

    def selection_set(self, first, last=None) -> None:
        if not self._items or self._state == tk.DISABLED:
            return
        idx = self._resolve_index(first)
        if 0 <= idx < len(self._items):
            self._selected = idx
            self._active = idx
            self._redraw()

    def activate(self, index) -> None:
        idx = self._resolve_index(index)
        if 0 <= idx < len(self._items):
            self._active = idx

    def see(self, index) -> None:
        if not self._items:
            return
        idx = min(len(self._items) - 1, max(0, self._resolve_index(index)))
        total_h = max(1, len(self._items) * self._row_h)
        view_h = self._visible_rows * self._row_h
        if total_h <= view_h:
            self._canvas.yview_moveto(0.0)
            return
        first_frac, last_frac = self._canvas.yview()
        row_top = (idx * self._row_h) / total_h
        row_bot = ((idx + 1) * self._row_h) / total_h
        if row_top < first_frac:
            self._canvas.yview_moveto(row_top)
        elif row_bot > last_frac:
            self._canvas.yview_moveto(max(0.0, row_bot - (view_h / total_h)))

    def _sync_height_and_scroll(self) -> None:
        rows = min(8, max(4, len(self._items) or self._visible_rows))
        self._visible_rows = rows
        f_obj = tkfont.Font(self, font=self._font)
        has_any_icon = any(img is not None for _lbl, img in self._items)
        pad_x = 40 if has_any_icon else 24
        max_w = max((f_obj.measure(lbl) + pad_x for lbl, _img in self._items), default=320)
        req_w = max(340, min(520, max_w))
        total_h = max(1, len(self._items)) * self._row_h
        view_h = self._visible_rows * self._row_h
        self._canvas.configure(
            width=req_w,
            height=view_h,
            scrollregion=(0, 0, req_w, total_h),
        )
        if len(self._items) > self._visible_rows:
            if self._scroll.winfo_manager() != "pack":
                self._scroll.pack(side=tk.RIGHT, fill=tk.Y)
        elif self._scroll.winfo_manager() == "pack":
            self._scroll.pack_forget()

    def _redraw(self) -> None:
        self._canvas.delete("all")
        if not self._items:
            return
        w = max(int(self._canvas.winfo_width()), int(self._canvas.cget("width")), 320)
        total_h = len(self._items) * self._row_h
        self._canvas.configure(scrollregion=(0, 0, w, total_h))
        has_any_icon = any(img is not None for _lbl, img in self._items)
        text_x = 34 if has_any_icon else 12
        for idx, (label, icon) in enumerate(self._items):
            y0 = idx * self._row_h
            y1 = y0 + self._row_h
            selected = self._state != tk.DISABLED and idx == self._selected
            hovered = self._state != tk.DISABLED and idx == self._hover
            row_bg = self._select_bg if selected else (C.hover if hovered else self._bg)
            row_fg = self._select_fg if selected else (C.dim if self._state == tk.DISABLED else self._fg)
            self._canvas.create_rectangle(0, y0, w, y1, fill=row_bg, outline="")
            cy = (y0 + y1) // 2
            if icon is not None:
                self._canvas.create_image(17, cy, image=icon, anchor="center")
            self._canvas.create_text(
                text_x,
                cy,
                text=label,
                fill=row_fg,
                font=self._font,
                anchor="w",
            )

    def _row_at_event(self, event) -> int:
        cy = self._canvas.canvasy(event.y)
        idx = int(cy // self._row_h)
        return idx if 0 <= idx < len(self._items) else -1

    def _set_selection_from_user(self, idx: int) -> str:
        if self._state == tk.DISABLED or not (0 <= idx < len(self._items)):
            return "break"
        self._selected = idx
        self._active = idx
        self.see(idx)
        self._redraw()
        self.event_generate("<<ListboxSelect>>")
        return "break"

    def _move_selection(self, delta: int) -> str:
        if self._state == tk.DISABLED or not self._items:
            return "break"
        base = self._selected if self._selected >= 0 else 0
        nxt = max(0, min(len(self._items) - 1, base + delta))
        return self._set_selection_from_user(nxt)

    def _on_click(self, event) -> None:
        self._canvas.focus_set()
        idx = self._row_at_event(event)
        if idx >= 0:
            self._set_selection_from_user(idx)

    def _on_double_click(self, event):
        if self._state == tk.DISABLED:
            return "break"
        idx = self._row_at_event(event)
        if idx >= 0:
            self._selected = idx
            self._active = idx
            self._redraw()
            self.event_generate("<<ListboxSelect>>")
            if self._double_cb is not None:
                self._double_cb(event)
        return "break"

    def _on_return(self, event):
        if self._state == tk.DISABLED:
            return "break"
        if self._return_cb is not None and 0 <= self._selected < len(self._items):
            self._return_cb(event)
        return "break"

    def _on_motion(self, event) -> None:
        if self._state == tk.DISABLED:
            return
        idx = self._row_at_event(event)
        if idx != self._hover:
            self._hover = idx
            self._redraw()

    def _on_leave(self, _event) -> None:
        if self._hover != -1:
            self._hover = -1
            self._redraw()

    def _on_wheel(self, event):
        if len(self._items) > self._visible_rows:
            self._canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    _double_cb = None
    _return_cb = None

    def bind(self, sequence=None, func=None, add=None):
        if sequence == "<Double-Button-1>":
            self._double_cb = func
            return ""
        if sequence in ("<Return>", "<KP_Enter>"):
            self._return_cb = func
            return ""
        return super().bind(sequence, func, add)

    def configure(self, cnf=None, **kw):
        opts = dict(cnf or {}, **kw)
        if "state" in opts:
            self._state = opts.pop("state")
            self._canvas.configure(cursor="arrow" if self._state == tk.DISABLED else "hand2")
        if "bg" in opts:
            self._bg = opts.pop("bg")
            super().configure(bg=self._bg)
            self._canvas.configure(bg=self._bg)
            self._scroll.configure(bg=self._bg, troughcolor=C.rail, activebackground=C.hover)
        if "fg" in opts:
            self._fg = opts.pop("fg")
        if "selectbackground" in opts:
            self._select_bg = opts.pop("selectbackground")
        if "selectforeground" in opts:
            self._select_fg = opts.pop("selectforeground")
        if "height" in opts:
            self._visible_rows = max(1, int(opts.pop("height")))
            self._sync_height_and_scroll()
        if "cursor" in opts:
            self._canvas.configure(cursor=opts.pop("cursor"))
        if opts:
            super().configure(**opts)
        self._redraw()

    config = configure

    def update_theme(self) -> None:
        self.configure(
            bg=C.panel,
            fg=C.dim if self._state == tk.DISABLED else C.text,
            selectbackground=C.select,
            selectforeground=C.text,
        )
