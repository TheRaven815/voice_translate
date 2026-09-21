"""Windows genelinde çalışan, bağımlılıksız klavye kısayolları."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import sys
import threading
from collections.abc import Callable

_MODIFIERS = {
    "Alt": 0x0001,
    "Ctrl": 0x0002,
    "Shift": 0x0004,
}
_MOD_NOREPEAT = 0x4000
_NAMED_KEYS = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Escape": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    "Insert": 0x2D,
    "Delete": 0x2E,
}
_KEY_ALIASES = {
    "RETURN": "Enter",
    "ESC": "Escape",
    "PRIOR": "PageUp",
    "NEXT": "PageDown",
    "CAPITAL": "CapsLock",
}
_MODIFIER_ALIASES = {
    "CONTROL": "Ctrl",
    "CTRL": "Ctrl",
    "ALT": "Alt",
    "SHIFT": "Shift",
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")


class ShortcutError(ValueError):
    pass


def _normal_key_name(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ShortcutError("Kısayol tuşu eksik.")
    upper = raw.upper()
    if upper in _KEY_ALIASES:
        return _KEY_ALIASES[upper]
    if len(raw) == 1 and raw.isascii() and raw.isalnum():
        return raw.upper()
    if upper.startswith("F") and upper[1:].isdigit() and 1 <= int(upper[1:]) <= 24:
        return upper
    for name in _NAMED_KEYS:
        if upper == name.upper():
            return name
    raise ShortcutError(f"Desteklenmeyen tuş: {raw}")


def parse_shortcut(shortcut: str) -> tuple[str, int, int]:
    """Kısayolu kanonik metin, Windows modifier ve virtual-key değerine çevirir."""
    parts = [part.strip() for part in shortcut.split("+") if part.strip()]
    if not parts:
        raise ShortcutError("Kısayol boş.")
    modifiers: set[str] = set()
    for part in parts[:-1]:
        modifier = _MODIFIER_ALIASES.get(part.upper())
        if modifier is None or modifier in modifiers:
            raise ShortcutError(f"Geçersiz değiştirici: {part}")
        modifiers.add(modifier)
    key = _normal_key_name(parts[-1])
    if not modifiers and not (key.startswith("F") and key[1:].isdigit()):
        raise ShortcutError("Genel kısayol Ctrl, Alt veya Shift içermeli.")
    modifier_value = _MOD_NOREPEAT
    for modifier in modifiers:
        modifier_value |= _MODIFIERS[modifier]
    if len(key) == 1:
        virtual_key = ord(key)
    elif key.startswith("F") and key[1:].isdigit():
        virtual_key = 0x70 + int(key[1:]) - 1
    else:
        virtual_key = _NAMED_KEYS[key]
    canonical = "+".join([*(name for name in _MODIFIER_ORDER if name in modifiers), key])
    return canonical, modifier_value, virtual_key


def shortcut_from_tk_event(event) -> str:
    """Tk KeyPress olayını güvenli bir genel kısayola çevirir."""
    keysym = str(getattr(event, "keysym", ""))
    if keysym in {"Control_L", "Control_R", "Alt_L", "Alt_R", "Shift_L", "Shift_R"}:
        return ""
    state = int(getattr(event, "state", 0))
    modifiers = []
    if state & 0x0004:
        modifiers.append("Ctrl")
    if state & 0x0008 or state & 0x20000:
        modifiers.append("Alt")
    if state & 0x0001:
        modifiers.append("Shift")
    canonical, _, _ = parse_shortcut("+".join([*modifiers, _normal_key_name(keysym)]))
    return canonical


class GlobalHotkeys:
    """RegisterHotKey kayıtlarını kendi Windows mesaj thread'inde yönetir."""

    _IDS = {"mute": 1, "start_stop": 2}
    _WM_HOTKEY = 0x0312
    _WM_COMMAND = 0x8001
    _PM_NOREMOVE = 0x0000

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback
        self._commands: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._startup_error = ""
        self._closed = False
        if sys.platform != "win32":
            self._startup_error = "Genel kısayollar yalnızca Windows üzerinde kullanılabilir."
            self._ready.set()
            return
        self._thread = threading.Thread(target=self._run, name="global-hotkeys", daemon=True)
        self._thread.start()
        if not self._ready.wait(2.0):
            self._startup_error = "Genel kısayol mesaj thread'i başlatılamadı."

    def bind(self, action: str, shortcut: str) -> str | None:
        """Kısayolu kaydeder; başarıda None, hatada kullanıcı mesajı döndürür."""
        if action not in self._IDS:
            return f"Bilinmeyen kısayol eylemi: {action}"
        if self._closed:
            return "Genel kısayol yöneticisi kapalı."
        if self._startup_error:
            return self._startup_error
        combo = None
        if shortcut.strip():
            try:
                combo = parse_shortcut(shortcut)
            except ShortcutError as exc:
                return str(exc)
        response: queue.Queue = queue.Queue(maxsize=1)
        self._commands.put(("bind", action, combo, response))
        error = self._wake()
        if error:
            return error
        try:
            return response.get(timeout=2.0)
        except queue.Empty:
            return "Genel kısayol kaydı zaman aşımına uğradı."
    def replace(self, shortcuts: dict[str, str]) -> str | None:
        """Tüm kayıtları atomik değiştirir; hata olursa eski kayıtları geri yükler."""
        if self._closed:
            return "Genel kısayol yöneticisi kapalı."
        if self._startup_error:
            return self._startup_error
        parsed: dict[str, tuple[str, int, int]] = {}
        for action, shortcut in shortcuts.items():
            if action not in self._IDS:
                return f"Bilinmeyen kısayol eylemi: {action}"
            if shortcut.strip():
                try:
                    parsed[action] = parse_shortcut(shortcut)
                except ShortcutError as exc:
                    return str(exc)
        combos = [combo[0] for combo in parsed.values()]
        if len(combos) != len(set(combos)):
            return "İki eyleme aynı kısayol atanamaz."
        response: queue.Queue = queue.Queue(maxsize=1)
        self._commands.put(("replace", parsed, None, response))
        error = self._wake()
        if error:
            return error
        try:
            return response.get(timeout=2.0)
        except queue.Empty:
            return "Genel kısayol kaydı zaman aşımına uğradı."


    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._commands.put(("close", None, None, None))
        self._wake()
        thread.join(timeout=1.0)

    def _wake(self) -> str | None:
        if not self._thread_id:
            return "Genel kısayol mesaj thread'i hazır değil."
        if self._user32.PostThreadMessageW(self._thread_id, self._WM_COMMAND, 0, 0):
            return None
        return self._windows_error("Genel kısayol mesajı gönderilemedi")

    def _run(self) -> None:
        try:
            self._configure_winapi()
            self._thread_id = int(self._kernel32.GetCurrentThreadId())
            msg = wintypes.MSG()
            self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, self._PM_NOREMOVE)
            self._ready.set()
            registered: dict[str, tuple[str, int, int]] = {}
            while True:
                result = self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == self._WM_HOTKEY:
                    action = next((name for name, ident in self._IDS.items() if ident == msg.wParam), None)
                    if action is not None:
                        try:
                            self._callback(action)
                        except Exception:
                            pass
                elif msg.message == self._WM_COMMAND and self._drain_commands(registered):
                    break
        except Exception as exc:
            self._startup_error = f"Genel kısayol sistemi başlatılamadı: {exc}"
            self._ready.set()
        finally:
            user32 = getattr(self, "_user32", None)
            if user32 is not None:
                for ident in self._IDS.values():
                    user32.UnregisterHotKey(None, ident)

    def _drain_commands(self, registered: dict[str, tuple[str, int, int]]) -> bool:
        while True:
            try:
                command, action, combo, response = self._commands.get_nowait()
            except queue.Empty:
                return False
            if command == "close":
                return True
            if command == "replace":
                previous = dict(registered)
                for ident in self._IDS.values():
                    self._user32.UnregisterHotKey(None, ident)
                registered.clear()
                error = None
                for name, new_combo in action.items():
                    _, modifiers, virtual_key = new_combo
                    if self._user32.RegisterHotKey(None, self._IDS[name], modifiers, virtual_key):
                        registered[name] = new_combo
                        continue
                    error = self._windows_error(f"{new_combo[0]} başka bir uygulama tarafından kullanılıyor")
                    break
                if error:
                    for ident in self._IDS.values():
                        self._user32.UnregisterHotKey(None, ident)
                    registered.clear()
                    for name, old_combo in previous.items():
                        _, modifiers, virtual_key = old_combo
                        if self._user32.RegisterHotKey(None, self._IDS[name], modifiers, virtual_key):
                            registered[name] = old_combo
                response.put(error)
                continue
            ident = self._IDS[action]
            previous = registered.pop(action, None)
            if previous is not None:
                self._user32.UnregisterHotKey(None, ident)
            error = None
            if combo is not None:
                _, modifiers, virtual_key = combo
                if self._user32.RegisterHotKey(None, ident, modifiers, virtual_key):
                    registered[action] = combo
                else:
                    error = self._windows_error(f"{combo[0]} başka bir uygulama tarafından kullanılıyor")
                    if previous is not None:
                        _, old_modifiers, old_key = previous
                        if self._user32.RegisterHotKey(None, ident, old_modifiers, old_key):
                            registered[action] = previous
            response.put(error)

    def _configure_winapi(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL
        self._user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._user32.GetMessageW.restype = wintypes.BOOL
        self._user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        self._user32.PeekMessageW.restype = wintypes.BOOL
        self._user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.PostThreadMessageW.restype = wintypes.BOOL
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    @staticmethod
    def _windows_error(prefix: str) -> str:
        code = ctypes.get_last_error()
        detail = ctypes.FormatError(code).strip() if code else "bilinmeyen Windows hatası"
        return f"{prefix}: {detail}"
