"""Yüzen, sürüklenebilir ve tıklama-geçirgen altyazı penceresi (OverlayMixin)."""

from __future__ import annotations

import os
import tkinter as tk
import tkinter.font as tkfont

from languages import is_rtl
from .theme import C
from .widgets import IconButton
from .win32 import (
    _clamp_to_bounds,
    _parse_geometry,
    _virtual_screen_bounds,
    _win32_gui_apis,
)


class OverlayMixin:
    """App sınıfı için altyazı overlay yöntemleri."""

    def _get_overlay_font(self) -> tkfont.Font:
        spec = (self.font_brand[0], getattr(self, "overlay_font_size", 13), "bold")
        cached = getattr(self, "_overlay_font_cache", None)
        if cached is not None and cached[0] == spec:
            return cached[1]
        font_obj = tkfont.Font(root=self, font=spec)
        self._overlay_font_cache = (spec, font_obj)
        return font_obj

    def _overlay_line_capacity(self) -> int:
        """Geçerli pencere yüksekliğine sığan altyazı satırı sayısı."""
        pop = self._overlay
        label = getattr(self, "overlay_label", None)
        if pop is None or label is None or not pop.winfo_exists():
            return 1
        font = self._get_overlay_font()
        line_height = max(1, font.metrics("linespace"))
        pad_y = int(float(label.cget("pady")))
        available = pop.winfo_height() - 2 * pad_y - 2
        return max(1, available // line_height)

    def _overlay_tail(self, full_text: str) -> str:
        """Pencere yüksekliğine sığan son görsel satırları döndürür."""
        text = full_text.strip()
        if not text:
            return ""
        max_lines = self._overlay_line_capacity()
        font = self._get_overlay_font()
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

    def _overlay_text_layout(self) -> tuple[str, str]:
        """Akışta okuma kenarı sabit kalsın: LTR sol üst, RTL sağ üst."""
        if is_rtl(self.dst_var.get()):
            return "ne", tk.RIGHT
        return "nw", tk.LEFT

    def _update_overlay(self, full_text: str) -> None:
        if self._overlay is None or not self._overlay.winfo_exists():
            return
        self._overlay_text = full_text.strip()
        tail = self._overlay_tail(full_text)
        if not tail:
            return
        anchor, justify = self._overlay_text_layout()
        self.overlay_label.configure(text=tail, anchor=anchor, justify=justify)

    def _adjust_overlay_font(self, delta: int) -> None:
        self.overlay_font_size = max(10, min(32, getattr(self, "overlay_font_size", 13) + delta))
        if hasattr(self, "overlay_label") and self.overlay_label.winfo_exists():
            self.overlay_label.configure(
                font=(self.font_brand[0], self.overlay_font_size, "bold"),
                text=self._overlay_tail(self._overlay_text) or "...",
            )
            self._fit_overlay()
        self._save_user_prefs()

    def _apply_overlay_click_through(self) -> bool:
        if os.name != "nt" or self._overlay is None or not self._overlay.winfo_exists():
            return True
        api = _win32_gui_apis()
        ctypes = api.ctypes
        user32 = api.user32
        child_hwnd = self._overlay.winfo_id()
        GA_ROOT = 2
        hwnd = user32.GetAncestor(child_hwnd, GA_ROOT) or child_hwnd
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x00000020
        try:
            if self._overlay_click_style is None:
                self._overlay_click_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            base_style = self._overlay_click_style
            click_through = self.overlay_click_through and not self._overlay_controls_interactive
            target_style = base_style | WS_EX_TRANSPARENT if click_through else base_style
            ctypes.set_last_error(0)
            previous = user32.SetWindowLongW(hwnd, GWL_EXSTYLE, target_style)
            if previous == 0 and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            if not user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            ):
                raise ctypes.WinError()
            return True
        except Exception as exc:
            self._append(f"[uyarı] Altyazı tıklama modu değiştirilemedi: {exc}\n")
            return False

    def _toggle_overlay_click_through(self) -> None:
        if self._overlay is None or not self._overlay.winfo_exists():
            return
        previous = getattr(self, "overlay_click_through", False)
        self.overlay_click_through = not previous
        if not self._apply_overlay_click_through():
            self.overlay_click_through = previous
            return
        self._overlay_thru_btn.kind = "target" if self.overlay_click_through else "cursor"
        self._overlay_thru_btn.redraw()
        self._save_user_prefs()

    def _place_overlay(self, x: int, y: int, width: int, height: int) -> None:
        """Altyazıyı gerçek koordinata taşır; negatif eksende Tk referansını düzeltir."""
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        screen_width = pop.winfo_screenwidth()
        screen_height = pop.winfo_screenheight()

        def geometry(dx: int = 0, dy: int = 0) -> str:
            x_part = f"+{x}" if x >= 0 else f"-{screen_width - width - x + dx}"
            y_part = f"+{y}" if y >= 0 else f"-{screen_height - height - y + dy}"
            return f"{width}x{height}{x_part}{y_part}"

        pop.geometry(geometry())
        if x < 0 or y < 0:
            pop.update_idletasks()
            actual_x, actual_y = pop.winfo_x(), pop.winfo_y()
            if (actual_x, actual_y) != (x, y):
                pop.geometry(geometry(actual_x - x, actual_y - y))

    def _overlay_bounds(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        """Verilen dikdörtgenin durduğu monitörün sınırları; yoksa sanal ekran."""
        center_x = int(x) + max(1, int(width)) // 2
        center_y = int(y) + max(1, int(height)) // 2
        work_area = self._deps()._monitor_work_area
        return work_area(center_x, center_y) or _virtual_screen_bounds(self)

    def _fit_overlay(self, anchor: str = "bottom") -> None:
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        pop.update_idletasks()
        cur_x, cur_y = pop.winfo_x(), pop.winfo_y()
        cur_width, cur_height = pop.winfo_width(), pop.winfo_height()
        width = max(220, cur_width)
        height = max(40, cur_height)
        x = cur_x
        y = cur_y if anchor == "top" else cur_y + cur_height - height
        x, y = _clamp_to_bounds(x, y, width, height, self._overlay_bounds(x, y, width, height))
        if (x, y, width, height) != (cur_x, cur_y, width, cur_height):
            self._place_overlay(x, y, width, height)

    def _resize_overlay(self, width: int, height: int) -> None:
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        cur_x, cur_y = pop.winfo_x(), pop.winfo_y()
        bounds = self._overlay_bounds(cur_x, cur_y, max(1, pop.winfo_width()), max(1, pop.winfo_height()))
        _, _, screen_width, screen_height = bounds
        width = max(220, min(screen_width, width))
        height = max(40, min(screen_height, height))
        x, y = _clamp_to_bounds(cur_x, cur_y, width, height, bounds)
        self._place_overlay(x, y, width, height)
        pop.update_idletasks()
        self.overlay_label.configure(
            wraplength=max(120, width - 64),
            text=self._overlay_tail(self._overlay_text) or "...",
        )

    def _set_overlay_controls_visible(self, visible: bool) -> None:
        if visible == self._overlay_controls_visible:
            return
        hdr = getattr(self, "_overlay_hdr", None)
        grip = getattr(self, "_overlay_grip", None)
        if hdr is None or grip is None:
            return
        self._overlay_controls_visible = visible
        if visible:
            hdr.place(relx=1.0, x=-4, y=4, anchor="ne")
            grip.place(relx=1.0, rely=1.0, x=-2, y=-2, anchor="se")
            hdr.lift()
            grip.lift()
        else:
            hdr.place_forget()
            grip.place_forget()

    def _sync_overlay_pointer(self) -> None:
        """Fare geçirgen olsa da global imleç konumundan hover durumunu güncelle."""
        pop = self._overlay
        hdr = getattr(self, "_overlay_hdr", None)
        grip = getattr(self, "_overlay_grip", None)
        if pop is None or hdr is None or grip is None or not pop.winfo_exists():
            return
        pointer_x, pointer_y = pop.winfo_pointerxy()
        rel_x = pointer_x - pop.winfo_rootx()
        rel_y = pointer_y - pop.winfo_rooty()
        width, height = pop.winfo_width(), pop.winfo_height()
        inside = 0 <= rel_x < width and 0 <= rel_y < height
        self._set_overlay_controls_visible(inside)

        over_header = (
            inside
            and width - hdr.winfo_reqwidth() - 4 <= rel_x < width
            and 4 <= rel_y < hdr.winfo_reqheight() + 4
        )
        over_grip = (
            inside
            and width - grip.winfo_reqwidth() - 2 <= rel_x < width
            and height - grip.winfo_reqheight() - 2 <= rel_y < height
        )
        interactive = bool(self.overlay_click_through and (over_header or over_grip))
        if interactive != self._overlay_controls_interactive:
            self._overlay_controls_interactive = interactive
            self._apply_overlay_click_through()

    def _poll_overlay_pointer(self) -> None:
        self._overlay_pointer_after_id = None
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        self._sync_overlay_pointer()
        self._overlay_pointer_after_id = pop.after(50, self._poll_overlay_pointer)

    def _close_overlay(self) -> None:
        pop = self._overlay
        if pop is None or not pop.winfo_exists():
            return
        if self._overlay_pointer_after_id is not None:
            pop.after_cancel(self._overlay_pointer_after_id)
            self._overlay_pointer_after_id = None
        pop.destroy()
        self._overlay = None
        self._overlay_click_style = None
        self._overlay_controls_visible = False
        self._overlay_controls_interactive = False
        self.overlay_btn.set_accent(False)

    def toggle_overlay(self) -> None:
        if self._overlay is not None and self._overlay.winfo_exists():
            if self.overlay_click_through:
                self._toggle_overlay_click_through()
                return
            self._close_overlay()
            return
        self._build_overlay()

    def _build_overlay(self, geom: str | None = None) -> None:
        deps = self._deps()
        pop = deps.tk.Toplevel(self)
        pop.withdraw()
        self._overlay = pop
        self._overlay_click_style = None
        self._overlay_controls_visible = False
        self._overlay_controls_interactive = False
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
            self._place_overlay(x, y, pop.winfo_width(), pop.winfo_height())

        wrap = tk.Frame(pop, bg=C.overlay_bg, highlightthickness=1, highlightbackground=C.line, bd=0)
        wrap.pack(fill=tk.BOTH, expand=True)
        self._overlay_wrap = wrap

        hdr = tk.Frame(wrap, bg=C.overlay_bg)
        self._overlay_hdr = hdr

        close_btn = IconButton(hdr, "close", self._close_overlay, bg=C.overlay_bg)
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
        raw_text = self.trans.get("1.0", "end").strip()
        self._overlay_text = next((line.strip() for line in reversed(raw_text.splitlines()) if line.strip()), "")
        cur_text = self._overlay_text or "..."

        anchor, justify = self._overlay_text_layout()
        self.overlay_label = tk.Label(
            wrap,
            text=cur_text,
            font=(self.font_brand[0], getattr(self, "overlay_font_size", 13), "bold"),
            fg=C.text,
            bg=C.overlay_bg,
            wraplength=520,
            anchor=anchor,
            justify=justify,
            padx=12,
            pady=2,
        )
        self.overlay_label.pack(fill=tk.BOTH, expand=True)

        grip = tk.Label(
            wrap, text="◢", font=(self.font_ui[0], 12), fg=C.dim,
            bg=C.overlay_bg, cursor="size_nw_se", padx=4, pady=2,
        )
        self._overlay_grip = grip

        def start_resize(e):
            pop._resize_x = e.x_root
            pop._resize_y = e.y_root
            pop._resize_w = pop.winfo_width()
            pop._resize_h = pop.winfo_height()
            return "break"

        def do_resize(e):
            self._resize_overlay(
                pop._resize_w + e.x_root - pop._resize_x,
                pop._resize_h + e.y_root - pop._resize_y,
            )
            return "break"

        grip.bind("<ButtonPress-1>", start_resize)
        grip.bind("<B1-Motion>", do_resize)
        grip.bind("<ButtonRelease-1>", lambda _e: self._save_user_prefs())

        for widget in (pop, wrap, self.overlay_label):
            widget.bind("<ButtonPress-1>", start_move)
            widget.bind("<B1-Motion>", do_move)

        def _on_overlay_wheel(e):
            delta = getattr(e, "delta", 0)
            if delta > 0:
                self._adjust_overlay_alpha(0.05)
            elif delta < 0:
                self._adjust_overlay_alpha(-0.05)
            return "break"

        pop.bind("<Control-MouseWheel>", _on_overlay_wheel)

        vx, vy, vw, vh = _virtual_screen_bounds(self)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        w, h = min(580, vw), 40
        work_area = deps._monitor_work_area

        def _clamped_rect(g: str) -> tuple[int, int, int, int] | None:
            rect = _parse_geometry(g, screen_w, screen_h)
            if rect is None:
                return None
            gx, gy, gw, gh = rect
            if gw < 220 or gh < 40:
                return None
            bounds = work_area(gx + gw // 2, gy + gh // 2) or (vx, vy, vw, vh)
            if gw > bounds[2] or gh > bounds[3]:
                bounds = (vx, vy, vw, vh)
                if gw > vw or gh > vh:
                    return None
            gx, gy = _clamp_to_bounds(gx, gy, gw, gh, bounds)
            return gx, gy, gw, gh

        applied = False
        for cand in (geom, getattr(self._cfg, "overlay_geom", "") if getattr(self, "_cfg", None) else ""):
            rect = _clamped_rect(cand) if cand else None
            if rect:
                self._place_overlay(*rect)
                applied = True
                break
        if not applied:
            host = work_area(
                self.winfo_rootx() + self.winfo_width() // 2,
                self.winfo_rooty() + self.winfo_height() // 2,
            ) or (vx, vy, vw, vh)
            hx, hy, hw, hh = host
            w = min(w, hw)
            h = min(h, hh)
            fx = hx + max(0, (hw - w) // 2)
            fy = hy + max(0, hh - h - 100)
            self._place_overlay(fx, fy, w, h)
        pop.update_idletasks()
        self.overlay_label.configure(wraplength=max(120, pop.winfo_width() - 44))
        self.overlay_label.configure(text=self._overlay_tail(self._overlay_text) or "...")
        self._apply_overlay_click_through()
        for w_widget in (pop, wrap, self.overlay_label):
            w_widget.bind("<ButtonRelease-1>", lambda _e: self._save_user_prefs(), add="+")
        self._fit_overlay()
        self._set_overlay_controls_visible(False)
        pop.deiconify()
        self._overlay_pointer_after_id = pop.after(50, self._poll_overlay_pointer)
