"""Windows bildirim alanı üzerinden yerel, engellemeyen bildirimler."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
        ("uTimeout", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD), ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WindowsNotifier:
    """Tk ana thread'inde kullanılır; pencere kapanırken close çağrılır."""

    def __init__(self, hwnd: int):
        self._data = _NOTIFYICONDATAW()
        self._data.cbSize = ctypes.sizeof(self._data)
        self._data.hWnd = hwnd
        self._data.uID = 1
        self._added = False
        self._notify = None
        if sys.platform == "win32":
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            self._notify = shell32.Shell_NotifyIconW
            self._notify.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
            self._notify.restype = wintypes.BOOL
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            user32.LoadIconW.restype = wintypes.HICON
            self._data.hIcon = user32.LoadIconW(None, ctypes.c_void_p(32515))  # IDI_WARNING

    def show(self, title: str, message: str) -> bool:
        if self._notify is None:
            return False
        self._data.uFlags = 0x02 | 0x04  # NIF_ICON | NIF_TIP
        self._data.szTip = title[:127]
        if not self._added:
            self._added = bool(self._notify(0, ctypes.byref(self._data)))  # NIM_ADD
            if not self._added:
                return False
        self._data.uFlags = 0x10  # NIF_INFO
        self._data.szInfoTitle = title[:63]
        self._data.szInfo = message[:255]
        self._data.dwInfoFlags = 0x02  # NIIF_WARNING
        self._data.uTimeout = 10000
        if self._notify(1, ctypes.byref(self._data)):  # NIM_MODIFY
            return True
        self.close()
        return False

    def close(self) -> None:
        if self._added and self._notify is not None:
            self._notify(2, ctypes.byref(self._data))  # NIM_DELETE
            self._added = False
