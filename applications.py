"""Selectable Windows desktop applications for process-tree audio capture."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import ntpath
import os
import sys
from typing import ClassVar

from process_audio import ProcessRecorder, process_audio_supported


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_TH32CS_SNAPPROCESS = 0x00000002
_ERROR_NO_MORE_FILES = 18
_UNAVAILABLE_PROCESS_ERRORS = {5, 87, 1168}  # Denied, invalid PID, no such process.
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _error(operation: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{operation}: {ctypes.FormatError(code).strip()}")


def _path_key(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


class _WindowsProcesses:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Application audio capture requires Windows build 20348 or newer.")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.window_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        bindings = [
            (self.kernel, "CreateToolhelp32Snapshot", [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel, "Process32FirstW", [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)], wintypes.BOOL),
            (self.kernel, "Process32NextW", [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)], wintypes.BOOL),
            (self.kernel, "OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, "QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.kernel, "GetProcessTimes", [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
            (self.kernel, "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.user, "EnumWindows", [self.window_callback, wintypes.LPARAM], wintypes.BOOL),
            (self.user, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
            (self.user, "GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
            (self.user, "GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ]
        for dll, name, args, result in bindings:
            function = getattr(dll, name)
            function.argtypes = args
            function.restype = result

    def parents(self) -> dict[int, int]:
        handle = self.kernel.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise _error("Cannot enumerate application processes (CreateToolhelp32Snapshot)")
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            parents = {}
            ok = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while ok:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                ok = self.kernel.Process32NextW(handle, ctypes.byref(entry))
            if ctypes.get_last_error() != _ERROR_NO_MORE_FILES:
                raise _error("Cannot enumerate application processes (Process32NextW)")
            return parents
        finally:
            self.kernel.CloseHandle(handle)

    def window_processes(self) -> set[int]:
        pids: set[int] = set()
        callback_errors: list[Exception] = []

        @self.window_callback
        def visit(hwnd, _lparam):
            try:
                # Read title length only; window titles can contain private content.
                if self.user.IsWindowVisible(hwnd) and self.user.GetWindowTextLengthW(hwnd) > 0:
                    pid = wintypes.DWORD()
                    if self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) and pid.value:
                        pids.add(pid.value)
                return True
            except Exception as exc:
                callback_errors.append(exc)
                return False

        ok = self.user.EnumWindows(visit, 0)
        if callback_errors:
            raise OSError("Cannot inspect desktop application windows.") from callback_errors[0]
        if not ok:
            raise _error("Cannot enumerate desktop application windows (EnumWindows)")
        return pids

    def open(self, pid: int):
        handle = self.kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
        if not handle and ctypes.get_last_error() not in _UNAVAILABLE_PROCESS_ERRORS:
            raise _error(f"Cannot inspect application process {pid} (OpenProcess)")
        return handle

    def identity(self, handle, pid: int) -> tuple[str, int] | None:
        state = self.kernel.WaitForSingleObject(handle, 0)
        if state == _WAIT_OBJECT_0:
            return None
        if state != _WAIT_TIMEOUT:
            raise _error(f"Cannot check application process {pid} (WaitForSingleObject)")
        path = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(path))
        if not self.kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            if ctypes.get_last_error() in _UNAVAILABLE_PROCESS_ERRORS:
                return None
            raise _error(f"Cannot inspect application process {pid} (QueryFullProcessImageNameW)")
        creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            if ctypes.get_last_error() in _UNAVAILABLE_PROCESS_ERRORS:
                return None
            raise _error(f"Cannot inspect application process {pid} (GetProcessTimes)")
        if exit_time.dwLowDateTime or exit_time.dwHighDateTime:
            return None
        return path.value, (creation.dwHighDateTime << 32) | creation.dwLowDateTime


@dataclass(frozen=True, slots=True)
class ApplicationAudioSource:
    pid: int
    name: str
    executable: str
    creation_time: int

    is_application: ClassVar[bool] = True
    isloopback: ClassVar[bool] = False
    channels: ClassVar[int] = 2

    @property
    def id(self) -> str:
        return f"application:{self.pid}:{self.creation_time}"

    def recorder(self, **kwargs) -> ProcessRecorder:
        if not process_audio_supported():
            raise OSError("Application audio capture requires Windows build 20348 or newer.")
        native = _WindowsProcesses()
        handle = native.open(self.pid)
        if not handle:
            raise ProcessLookupError(f"Application process {self.pid} closed or is inaccessible; refresh application inputs.")
        try:
            identity = native.identity(handle, self.pid)
            if identity is None or identity[1] != self.creation_time or _path_key(identity[0]) != _path_key(self.executable):
                raise ProcessLookupError(f"Application process {self.pid} changed or closed; refresh application inputs.")
            # Keep original process alive as a kernel object until recorder owns a
            # handle too. Windows cannot recycle its PID in this interval.
            return ProcessRecorder(self.pid, **kwargs)
        finally:
            native.kernel.CloseHandle(handle)


def application_inputs() -> list[ApplicationAudioSource]:
    """List visible desktop app roots, never substituting endpoint loopback."""
    if not process_audio_supported():
        return []
    native = _WindowsProcesses()
    parents = native.parents()
    own_pid = os.getpid()
    children: dict[int, list[int]] = {}
    for pid, parent in parents.items():
        children.setdefault(parent, []).append(pid)
    excluded = {0, 4, own_pid}
    pending = [own_pid]
    while pending:
        for pid in children.get(pending.pop(), ()):
            if pid not in excluded:
                excluded.add(pid)
                pending.append(pid)
    # Capturing an ancestor would include Ahenk's own speech output as well.
    parent = parents.get(own_pid, 0)
    while parent and parent not in excluded:
        excluded.add(parent)
        parent = parents.get(parent, 0)

    identities: dict[int, tuple[str, int] | None] = {}

    def inspect(pid: int) -> tuple[str, int] | None:
        if pid not in identities:
            handle = native.open(pid)
            if not handle:
                identities[pid] = None
            else:
                try:
                    identities[pid] = native.identity(handle, pid)
                finally:
                    native.kernel.CloseHandle(handle)
        return identities[pid]

    roots: dict[int, tuple[str, int]] = {}
    for window_pid in sorted(native.window_processes()):
        if window_pid in excluded or window_pid not in parents:
            continue
        identity = inspect(window_pid)
        if identity is None:
            continue
        pid = window_pid
        seen = {pid}
        while (parent := parents.get(pid, 0)) and parent not in seen:
            if parent in excluded:
                break
            parent_identity = inspect(parent)
            if parent_identity is None or _path_key(parent_identity[0]) != _path_key(identity[0]):
                break
            # Snapshot parent PIDs may refer to a new process after PID reuse.
            if parent_identity[1] > identity[1]:
                break
            seen.add(parent)
            pid, identity = parent, parent_identity
        roots[pid] = identity

    names = Counter(ntpath.basename(identity[0]).casefold() for identity in roots.values())
    sources = []
    for pid, (executable, creation_time) in roots.items():
        name = ntpath.basename(executable)
        if names[name.casefold()] > 1:
            name = f"{name} (PID {pid})"
        sources.append(ApplicationAudioSource(pid, name, executable, creation_time))
    return sorted(sources, key=lambda source: (ntpath.basename(source.executable).casefold(), source.pid))
