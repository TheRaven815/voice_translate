"""Windows tek örnek kilidi.

İkinci masaüstü başlatması yeni pencere açmaz; açık olanı öne getirir.
Güncelleme yardımcısı ve CLI bu kilidi kullanmaz.
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes

MUTEX_NAME = "Local\\eneseliagir.ahenk.single-instance"
MAPPING_NAME = "Local\\eneseliagir.ahenk.activate"
WINDOW_MESSAGE = "eneseliagir.ahenk.activate"
_ERROR_ALREADY_EXISTS = 183
_GA_ROOT = 2
_SW_RESTORE = 9
_HWND_TOP = 0
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
ASFW_ANY = 0xFFFFFFFF
_FILE_MAP_ALL_ACCESS = 0xF001F

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CreateFileMappingW.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
]
kernel32.CreateFileMappingW.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t,
]
kernel32.MapViewOfFile.restype = wintypes.LPVOID
kernel32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
kernel32.UnmapViewOfFile.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL


class SingleInstance:
    """Named mutex. Sahip süreç kapanınca kilit serbest kalır."""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self.handle: int | None = None
        self.acquired = False

    def acquire(self) -> bool:
        if os.name != "nt":
            self.acquired = True
            return True
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        self.handle = handle
        self.acquired = not already
        if already:
            self.close()
        return self.acquired

    def close(self) -> None:
        handle = self.handle
        self.handle = None
        self.acquired = False
        if handle:
            kernel32.CloseHandle(handle)


class ActivateSlot:
    """İlk sürecin UI thread kimliği. İkinci süreç PostThreadMessage ile uyarır."""

    def __init__(self, name: str = MAPPING_NAME) -> None:
        self.name = name
        self._mapping = None
        self.view = None

    def open(self) -> bool:
        if os.name != "nt":
            return False
        handle = kernel32.CreateFileMappingW(
            wintypes.HANDLE(-1).value, None, 0x04, 0, 8, self.name,
        )
        if not handle:
            return False
        self._mapping = handle
        view = kernel32.MapViewOfFile(handle, _FILE_MAP_ALL_ACCESS, 0, 0, 8)
        if not view:
            kernel32.CloseHandle(handle)
            self._mapping = None
            return False
        self.view = view
        return True

    def publish(self, thread_id: int) -> None:
        if not self.view:
            return
        ctypes.memmove(self.view, struct.pack("<II", 1, int(thread_id)), 8)

    def read(self) -> tuple[int, int]:
        if not self.view:
            return 0, 0
        raw = ctypes.string_at(self.view, 8)
        ready, thread_id = struct.unpack("<II", raw)
        return int(ready), int(thread_id)

    def clear(self) -> None:
        if self.view:
            ctypes.memset(self.view, 0, 8)

    def close(self) -> None:
        if self.view:
            kernel32.UnmapViewOfFile(self.view)
            self.view = None
        if self._mapping:
            kernel32.CloseHandle(self._mapping)
            self._mapping = None


def activate_message_id(name: str = WINDOW_MESSAGE) -> int:
    message = user32.RegisterWindowMessageW(name)
    if not message:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(message)


def root_hwnd(widget_id: int) -> int:
    return int(user32.GetAncestor(widget_id, _GA_ROOT) or widget_id)


def allow_activation() -> None:
    """İkinci süreç, öndeki süreçten gelen etkinleştirme isteğini kabul etsin."""
    if os.name != "nt":
        return
    user32.AllowSetForegroundWindow(ASFW_ANY)


def bring_to_front(hwnd: int) -> bool:
    """Simge durumundan çıkar, Z sırasının tepesine al, odak ver."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)
    user32.ShowWindow(hwnd, _SW_RESTORE)
    user32.SetWindowPos(hwnd, _HWND_TOP, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE)
    user32.BringWindowToTop(hwnd)

    foreground = user32.GetForegroundWindow()
    foreground_thread = wintypes.DWORD()
    if foreground:
        user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_thread))
    current_thread = kernel32.GetCurrentThreadId()
    attached = False
    if foreground and foreground_thread.value and foreground_thread.value != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, foreground_thread.value, True))
    try:
        return bool(user32.SetForegroundWindow(hwnd))
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, foreground_thread.value, False)


def signal_existing(*, attempts: int = 12, pause: float = 0.12) -> bool:
    """Açık örneğin UI thread'ine etkinleştirme mesajı bırak.

    İlk süreç thread kimliğini henüz yazmamış olabilir. Kısa aralıklarla tekrarlanır.
    """
    if os.name != "nt":
        return False
    import time

    slot = ActivateSlot()
    if not slot.open():
        return False
    try:
        message = activate_message_id()
        for attempt in range(max(1, attempts)):
            ready, thread_id = slot.read()
            if ready and thread_id:
                if user32.PostThreadMessageW(thread_id, message, 1, 1):
                    return True
            if attempt + 1 < attempts:
                time.sleep(pause)
        return False
    finally:
        slot.close()


def claim_or_activate() -> tuple[SingleInstance, ActivateSlot] | None:
    """Kilit alındıysa (kilit, slot) döndür. Alınamadıysa mevcut örneği uyar, None dön."""
    if os.name != "nt":
        lock = SingleInstance()
        lock.acquire()
        return lock, ActivateSlot()
    lock = SingleInstance()
    if lock.acquire():
        slot = ActivateSlot()
        slot.open()
        slot.clear()
        allow_activation()
        return lock, slot
    signal_existing()
    return None
