"""Win32 ekran/pencere yardımcıları, tek-örnek etkinleştirme ve ikon çıkarma."""

from __future__ import annotations

import functools
import os
import re
import struct
import tkinter as tk
from types import SimpleNamespace
import zlib


@functools.lru_cache(maxsize=1)
def _win32_gui_apis():
    """Win32 user32 arayüz imzalarını süreç başına bir kez hazırlar."""
    import ctypes
    from ctypes import wintypes

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG), wintypes.HWND,
        wintypes.UINT, wintypes.UINT, wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    return SimpleNamespace(
        ctypes=ctypes,
        wintypes=wintypes,
        user32=user32,
        MONITORINFO=_MONITORINFO,
    )


@functools.lru_cache(maxsize=1)
def _win32_icon_apis():
    """Uygulama ikonu çıkarmak için shell32/gdi32/user32 imzalarını bir kez hazırlar."""
    import ctypes
    from ctypes import wintypes

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = wintypes.UINT

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(_BITMAPINFOHEADER),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    user32.DrawIconEx.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.HBRUSH,
        wintypes.UINT,
    ]
    user32.DrawIconEx.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [wintypes.HANDLE]
    user32.DestroyIcon.restype = wintypes.BOOL

    return SimpleNamespace(
        ctypes=ctypes,
        wintypes=wintypes,
        shell32=shell32,
        gdi32=gdi32,
        user32=user32,
        BITMAPINFOHEADER=_BITMAPINFOHEADER,
    )


def _encode_rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    """Saf standart kütüphane ile 8-bit RGBA PNG bayt dizisi üretir."""
    stride = width * 4
    raw_rows = bytearray()
    for y in range(height):
        raw_rows.append(0)  # Filtre yok (None)
        row_start = y * stride
        raw_rows.extend(rgba[row_start : row_start + stride])

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    compressed = zlib.compress(bytes(raw_rows), level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


@functools.lru_cache(maxsize=128)
def _cached_exe_icon_png(_norm_key: str, raw_path: str, size: int) -> bytes | None:
    if os.name != "nt" or not raw_path or size <= 0:
        return None
    try:
        api = _win32_icon_apis()
        ctypes = api.ctypes
        wintypes = api.wintypes
        small = wintypes.HANDLE()
        large = wintypes.HANDLE()
        hicon = None
        hdc = None
        hbmp = None
        old_obj = None
        try:
            count = int(api.shell32.ExtractIconExW(raw_path, 0, None, ctypes.byref(small), 1))
            if count > 0 and small.value:
                hicon = small
            else:
                count = int(api.shell32.ExtractIconExW(raw_path, 0, ctypes.byref(large), None, 1))
                if count > 0 and large.value:
                    hicon = large
            if hicon is None or not hicon.value:
                return None

            hdc = api.gdi32.CreateCompatibleDC(None)
            if not hdc:
                return None

            bmi = api.BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(bmi)
            bmi.biWidth = size
            bmi.biHeight = -size  # Yukarıdan aşağıya (top-down) DIB
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0  # BI_RGB

            bits = ctypes.c_void_p()
            hbmp = api.gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            if not hbmp or not bits.value:
                return None

            old_obj = api.gdi32.SelectObject(hdc, hbmp)
            buf_len = size * size * 4
            ctypes.memset(bits.value, 0, buf_len)
            if not api.user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, 0x0003):
                return None

            bgra = ctypes.string_at(bits.value, buf_len)
        finally:
            if hdc and old_obj:
                api.gdi32.SelectObject(hdc, old_obj)
            if hbmp:
                api.gdi32.DeleteObject(hbmp)
            if hdc:
                api.gdi32.DeleteDC(hdc)
            if small.value:
                api.user32.DestroyIcon(small)
            if large.value:
                api.user32.DestroyIcon(large)

        has_alpha = any(bgra[i + 3] != 0 for i in range(0, len(bgra), 4))
        has_color = any((bgra[i] | bgra[i + 1] | bgra[i + 2]) != 0 for i in range(0, len(bgra), 4))
        if not has_alpha and not has_color:
            return None

        rgba = bytearray(len(bgra))
        for i in range(0, len(bgra), 4):
            b, g, r, a = bgra[i], bgra[i + 1], bgra[i + 2], bgra[i + 3]
            if not has_alpha:
                a = 255 if (r | g | b) else 0
            if a == 0:
                rgba[i : i + 4] = b"\x00\x00\x00\x00"
            else:
                rgba[i] = r
                rgba[i + 1] = g
                rgba[i + 2] = b
                rgba[i + 3] = a
        return _encode_rgba_png(size, size, bytes(rgba))
    except Exception:
        return None


def extract_exe_icon_png(executable: str, size: int = 16) -> bytes | None:
    """Yürütülebilir dosyadan 16x16 RGBA PNG baytları çıkarır (önbellekli, sıfır sızıntı)."""
    if not executable:
        return None
    norm_key = os.path.normcase(os.path.normpath(str(executable)))
    return _cached_exe_icon_png(norm_key, str(executable), int(size))


def _virtual_screen_bounds(widget) -> tuple[int, int, int, int]:
    """Tüm monitörleri kapsayan sanal ekranın (x, y, genişlik, yükseklik) sınırları.

    Tk'nin winfo_screenwidth/height yalnızca birincil monitörü verir; ikinci
    ekrana taşınan altyazı bu yüzden birinci ekrana geri sıçrıyordu.
    """
    if os.name == "nt":
        try:
            metrics = _win32_gui_apis().user32.GetSystemMetrics
            x, y = int(metrics(76)), int(metrics(77))  # SM_X/YVIRTUALSCREEN
            width, height = int(metrics(78)), int(metrics(79))  # SM_CX/CYVIRTUALSCREEN
            if width > 0 and height > 0:
                return x, y, width, height
        except Exception:
            pass
    try:
        return 0, 0, int(widget.winfo_screenwidth()), int(widget.winfo_screenheight())
    except (AttributeError, tk.TclError):
        return 0, 0, 1920, 1080


def _monitor_work_area(x: int, y: int) -> tuple[int, int, int, int] | None:
    """Noktayı içeren (yoksa en yakın) monitörün görev çubuğu hariç alanı."""
    if os.name != "nt":
        return None
    try:
        api = _win32_gui_apis()
        monitor = api.user32.MonitorFromPoint(api.wintypes.POINT(int(x), int(y)), 2)  # NEAREST
        if not monitor:
            return None
        info = api.MONITORINFO()
        info.cbSize = api.ctypes.sizeof(api.MONITORINFO)
        if not api.user32.GetMonitorInfoW(monitor, api.ctypes.byref(info)):
            return None
        work = info.rcWork
        width, height = work.right - work.left, work.bottom - work.top
        if width <= 0 or height <= 0:
            return None
        return int(work.left), int(work.top), int(width), int(height)
    except Exception:
        return None


_GEOMETRY_RE = re.compile(r"^=?(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def _parse_geometry(
    g: str, screen_width: int, screen_height: int
) -> tuple[int, int, int, int] | None:
    """Tk geometri dizgesini gerçek (sanal masaüstü) koordinatlara çözer.

    Tk'de ``-N`` sağ/alt kenardan ölçülür; bu yüzden negatif konumlar ekran
    genişliği üzerinden geri hesaplanır.
    """
    match = _GEOMETRY_RE.match((g or "").strip())
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    x_token, y_token = match.group(3), match.group(4)
    x = int(x_token[1:]) if x_token[0] == "+" else screen_width - width - int(x_token[1:])
    y = int(y_token[1:]) if y_token[0] == "+" else screen_height - height - int(y_token[1:])
    return x, y, width, height


def _clamp_to_bounds(
    x: int, y: int, width: int, height: int, bounds: tuple[int, int, int, int]
) -> tuple[int, int]:
    bx, by, bw, bh = bounds
    x = min(max(bx, int(x)), max(bx, bx + bw - int(width)))
    y = min(max(by, int(y)), max(by, by + bh - int(height)))
    return x, y


class SingleInstanceMixin:
    """İkinci başlatmada mevcut pencereyi simgeden çıkarıp öne getiren dinleyici."""

    def _install_single_instance_activate(self) -> None:
        slot = getattr(self, "_activate_slot", None)
        if slot is None or os.name != "nt":
            return
        try:
            from single_instance import activate_message_id, allow_activation, kernel32
        except Exception:
            return
        try:
            message = activate_message_id()
        except OSError:
            return
        allow_activation()
        slot.publish(int(kernel32.GetCurrentThreadId()))
        self._single_instance_message = message
        self._poll_activate_message()

    def _poll_activate_message(self) -> None:
        message = getattr(self, "_single_instance_message", 0)
        if not message or os.name != "nt":
            return
        try:
            api = _win32_gui_apis()
            ctypes = api.ctypes
            wintypes = api.wintypes
            user32 = api.user32
            PM_REMOVE = 0x0001
            msg = wintypes.MSG()
            while user32.PeekMessageW(ctypes.byref(msg), None, message, message, PM_REMOVE):
                if int(msg.message) == message and int(msg.wParam) == 1 and int(msg.lParam) == 1:
                    self._raise_existing_window()
        except Exception:
            pass
        try:
            self._activate_after_id = self.after(200, self._poll_activate_message)
        except tk.TclError:
            self._activate_after_id = None

    def _stop_activate_listener(self) -> None:
        after_id = getattr(self, "_activate_after_id", None)
        self._activate_after_id = None
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        slot = getattr(self, "_activate_slot", None)
        if slot is not None:
            try:
                slot.clear()
            except Exception:
                pass

    def _raise_existing_window(self) -> None:
        from single_instance import allow_activation, bring_to_front, root_hwnd

        try:
            if self.state() in {"iconic", "withdrawn"} or not self.winfo_viewable():
                self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(80, lambda: self.attributes("-topmost", bool(getattr(self, "always_on_top", False))))
            self.focus_force()
            bring_to_front(root_hwnd(self.winfo_id()))
            allow_activation()
        except tk.TclError:
            pass
