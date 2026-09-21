"""Dublaj: çeviri çalarken kaynaktaki sesi kıs ya da sustur, bitince eski haline döndür.

Kaynak ya tamamen susar ya da dublajdaki gibi hafif bir yatak olarak kalır.
İkisi de yalnızca kullanıcının duyduğu çıkışı etkiler. Süreç döngüsü ve uç
noktası döngüsü bu kısmanın öncesinden akar, çeviri kaynağı dolu kalır.

* Uygulama girişi: o sürecin oturumları.
* Sistem döngüsü, çeviri başka aygıta gidiyorsa: kaynak hoparlör.
* Sistem döngüsü, çeviri aynı hoparlördeyse: diğer oturumlar. Ucun kendisi
  kısılırsa çeviri de kısılır; yakalama kendi sürecimizi hariç tutar.
"""

from __future__ import annotations

import atexit
import ctypes as ct
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field

from applications import process_tree_pids
from process_audio import process_audio_supported


# Doğrusal 0.18 ≈ −15 dB: çevirinin altında duyulan, sözü örtmeden kalan yatak.
DUB_BACKGROUND = 0.18


@dataclass(frozen=True, slots=True)
class DubPlan:
    """Ne susturulacağı. action: idle | mute_process | mute_endpoint | mute_other_sessions.

    gain None ise kaynak tamamen susar. Sayı ise duyulan düzeyin tavanıdır.
    """

    action: str = "idle"
    root_pid: int = 0
    endpoint_id: str = ""
    note: str = ""
    gain: float | None = None


def same_render_endpoint(source, output) -> bool:
    """Döngü girişi ile hoparlör aynı fiziksel çıkış ucu mu.

    soundcard döngü mikrofonuna, karşılık gelen hoparlörün WASAPI kimliğini verir.
    Ad parçası eşlemesi kulaklığı da 'hoparlör' sanıp yanlış ucu susturabilir.
    """
    if source is None or output is None:
        return False
    src_id = getattr(source, "id", None)
    dst_id = getattr(output, "id", None)
    if src_id not in (None, "") and dst_id not in (None, ""):
        return str(src_id).casefold() == str(dst_id).casefold()
    src_name = getattr(source, "name", None)
    dst_name = getattr(output, "name", None)
    if src_name and dst_name:
        return str(src_name).strip().casefold() == str(dst_name).strip().casefold()
    return False


def plan_dub(
    source, output, *, enabled: bool, own_pid: int, exclude_supported: bool, gain: float | None = None,
) -> DubPlan:
    """Saf karar. COM'a dokunmaz. gain verilirse kısma, yoksa tam susturma."""
    bed = None if gain is None else max(0.0, min(1.0, float(gain)))
    if not enabled or output is None or source is None:
        return DubPlan("idle")
    if getattr(source, "is_application", False):
        pid = int(getattr(source, "pid", 0) or 0)
        if pid <= 0:
            return DubPlan("idle", note="microphone")
        return DubPlan("mute_process", root_pid=pid, gain=bed)
    if getattr(source, "isloopback", False):
        if same_render_endpoint(source, output):
            if not exclude_supported:
                return DubPlan("idle", note="same_speakers")
            return DubPlan("mute_other_sessions", root_pid=int(own_pid), gain=bed)
        endpoint = str(getattr(source, "id", "") or "")
        if not endpoint:
            return DubPlan("idle", note="same_speakers")
        return DubPlan("mute_endpoint", endpoint_id=endpoint, gain=bed)
    return DubPlan("idle", note="microphone")


def _plan_key(plan: DubPlan) -> tuple:
    return (plan.action, plan.root_pid, plan.endpoint_id, plan.gain)


@dataclass(frozen=True, slots=True)
class PriorLevel:
    """Dokunmadan önceki susturma biti ve ana ses (0–1)."""

    muted: bool
    volume: float


@dataclass
class MuteHold:
    """Bizim değiştirdiğimiz uç ve oturumların önceki düzeyi."""

    plan: DubPlan
    endpoints: dict[str, PriorLevel] = field(default_factory=dict)
    sessions: dict[tuple[str, str], PriorLevel] = field(default_factory=dict)


class SourceDub:
    """Planı uygular, yeni oturumları izler, bırakınca yalnızca kendi değişikliğini geri alır."""

    def __init__(self, backend=None, *, own_pid: int | None = None, tree=None, exclude_supported=None):
        self._backend = backend
        self._own_pid = os.getpid() if own_pid is None else int(own_pid)
        self._tree = process_tree_pids if tree is None else tree
        self._exclude_supported = process_audio_supported if exclude_supported is None else exclude_supported
        self._lock = threading.Lock()
        self._active = DubPlan()
        self._token: MuteHold | None = None
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._atexit = False

    def preview(self, source, output, *, enabled: bool, gain: float | None = None) -> DubPlan:
        supported = self._exclude_supported() if callable(self._exclude_supported) else bool(self._exclude_supported)
        return plan_dub(
            source, output,
            enabled=enabled, own_pid=self._own_pid, exclude_supported=supported,
            gain=gain if enabled else None,
        )

    def engage(self, plan: DubPlan) -> None:
        with self._lock:
            if _plan_key(plan) == _plan_key(self._active):
                self._active = plan
                if plan.action != "idle" and self._token is not None and self._backend is not None:
                    self._backend.refresh(self._token)
                return
            self._restore_locked()
            self._active = DubPlan()
            if plan.action == "idle":
                self._active = plan
                return
            backend = self._backend_get()
            self._token = backend.apply(plan)
            self._active = plan
            self._ensure_watch_locked()
            self._ensure_atexit()

    def release(self) -> None:
        thread = None
        with self._lock:
            self._restore_locked()
            self._active = DubPlan()
            self._watch_stop.set()
            thread = self._watch_thread
            self._watch_thread = None
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=1.5)

    def _backend_get(self):
        if self._backend is None:
            self._backend = WindowsRenderMute(tree=self._tree)
        return self._backend

    def _restore_locked(self) -> None:
        token, self._token = self._token, None
        if token is not None and self._backend is not None:
            self._backend.restore(token)

    def _ensure_watch_locked(self) -> None:
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(target=self._watch, name="ahenk-dub", daemon=True)
        self._watch_thread.start()

    def _ensure_atexit(self) -> None:
        if self._atexit:
            return
        self._atexit = True
        atexit.register(self.release)

    def _watch(self) -> None:
        while not self._watch_stop.wait(0.5):
            with self._lock:
                if self._watch_stop.is_set() or self._token is None or self._active.action == "idle":
                    continue
                backend = self._backend
                token = self._token
            if backend is None:
                continue
            try:
                with self._lock:
                    if token is self._token and not self._watch_stop.is_set():
                        backend.refresh(token)
            except Exception:
                pass


# --- WASAPI oturum / uç susturma --------------------------------------------

_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
_CLSCTX_ALL = 23
_DEVICE_STATE_ACTIVE = 0x1
_E_RENDER = 0

_CLSID_ENUMERATOR = "BCDE0395-E52F-467C-8E3D-C4579291692E"
_IID_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
_IID_SESSION_MANAGER = "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"
_IID_SESSION_CONTROL2 = "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"
_IID_SIMPLE_VOLUME = "87CE5498-68D6-44E5-9215-6DA47EF883D8"
_IID_ENDPOINT_VOLUME = "5CDF2C82-841E-4546-9722-0CF74078229A"


class _GUID(ct.Structure):
    _fields_ = [
        ("Data1", ct.c_uint32),
        ("Data2", ct.c_uint16),
        ("Data3", ct.c_uint16),
        ("Data4", ct.c_ubyte * 8),
    ]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(pointer, index: int, result, *arguments):
    vtable = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(result, ct.c_void_p, *arguments)(vtable[index])


def _release(pointer) -> None:
    if pointer:
        try:
            _method(pointer, 2, ct.c_uint32)(pointer)
        except Exception:
            pass


def _check(result: int, operation: str) -> None:
    if result < 0:
        code = result & 0xFFFFFFFF
        raise OSError(f"{operation} failed (HRESULT 0x{code:08X}): {ct.FormatError(code).strip()}")


class _Com:
    def __enter__(self):
        if sys.platform != "win32":
            raise OSError("Source mute requires Windows")
        self.ole = ct.WinDLL("ole32")
        self.ole.CoInitializeEx.argtypes = [ct.c_void_p, ct.c_uint32]
        self.ole.CoInitializeEx.restype = ct.c_int32
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [
            ct.POINTER(_GUID), ct.c_void_p, ct.c_uint32, ct.POINTER(_GUID), ct.POINTER(ct.c_void_p),
        ]
        self.ole.CoCreateInstance.restype = ct.c_int32
        self.ole.CoTaskMemFree.argtypes = [ct.c_void_p]
        self.ole.CoTaskMemFree.restype = None
        hr = self.ole.CoInitializeEx(None, 2)  # STA; Tk ile aynı apartman
        self._uninit = hr != _RPC_E_CHANGED_MODE
        if hr < 0 and hr != _RPC_E_CHANGED_MODE:
            _check(hr, "CoInitializeEx")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._uninit:
            self.ole.CoUninitialize()

    def enumerator(self):
        pointer = ct.c_void_p()
        _check(self.ole.CoCreateInstance(
            ct.byref(_guid(_CLSID_ENUMERATOR)), None, _CLSCTX_ALL,
            ct.byref(_guid(_IID_ENUMERATOR)), ct.byref(pointer),
        ), "CoCreateInstance(MMDeviceEnumerator)")
        return pointer

    def task_string(self, raw: ct.c_void_p) -> str:
        if not raw or not raw.value:
            return ""
        try:
            return ct.wstring_at(raw.value) or ""
        finally:
            self.ole.CoTaskMemFree(raw)


def _activate(device, iid: str):
    out = ct.c_void_p()
    _check(_method(device, 3, ct.c_int32, ct.POINTER(_GUID), ct.c_uint32, ct.c_void_p, ct.POINTER(ct.c_void_p))(
        device, ct.byref(_guid(iid)), _CLSCTX_ALL, None, ct.byref(out),
    ), "IMMDevice.Activate")
    if not out:
        raise OSError("IMMDevice.Activate returned no interface")
    return out


def _device_id(com: _Com, device) -> str:
    raw = ct.c_void_p()
    _check(_method(device, 5, ct.c_int32, ct.POINTER(ct.c_void_p))(device, ct.byref(raw)), "IMMDevice.GetId")
    return com.task_string(raw)


# IAudioEndpointVolume: SetMasterVolumeLevelScalar=7, Get=9, SetMute=14, GetMute=15.
# ISimpleAudioVolume: SetMasterVolume=3, Get=4, SetMute=5, GetMute=6.
_ENDPOINT_SET_VOLUME = 7
_ENDPOINT_GET_VOLUME = 9
_ENDPOINT_SET_MUTE = 14
_ENDPOINT_GET_MUTE = 15
_SESSION_SET_VOLUME = 3
_SESSION_GET_VOLUME = 4
_SESSION_SET_MUTE = 5
_SESSION_GET_MUTE = 6


def _volume_indices(kind: str) -> tuple[int, int, int, int]:
    if kind == "endpoint":
        return (_ENDPOINT_GET_MUTE, _ENDPOINT_SET_MUTE, _ENDPOINT_GET_VOLUME, _ENDPOINT_SET_VOLUME)
    return (_SESSION_GET_MUTE, _SESSION_SET_MUTE, _SESSION_GET_VOLUME, _SESSION_SET_VOLUME)


def _get_mute(volume, index: int) -> bool:
    flag = ct.c_int32()
    _check(_method(volume, index, ct.c_int32, ct.POINTER(ct.c_int32))(volume, ct.byref(flag)), "GetMute")
    return bool(flag.value)


def _set_mute(volume, index: int, muted: bool) -> None:
    _check(_method(volume, index, ct.c_int32, ct.c_int32, ct.c_void_p)(
        volume, 1 if muted else 0, None,
    ), "SetMute")


def _get_scalar(volume, index: int) -> float:
    level = ct.c_float()
    _check(_method(volume, index, ct.c_int32, ct.POINTER(ct.c_float))(volume, ct.byref(level)), "GetVolume")
    return max(0.0, min(1.0, float(level.value)))


def _set_scalar(volume, index: int, level: float) -> None:
    _check(_method(volume, index, ct.c_int32, ct.c_float, ct.c_void_p)(
        volume, ct.c_float(max(0.0, min(1.0, level))), None,
    ), "SetVolume")


def _read_level(volume, kind: str) -> PriorLevel:
    get_mute, _set_mute_i, get_volume, _set_volume_i = _volume_indices(kind)
    return PriorLevel(_get_mute(volume, get_mute), _get_scalar(volume, get_volume))


def _shape_level(volume, kind: str, prior: PriorLevel, gain: float | None) -> None:
    """gain yoksa sustur. Sayıysa önceki düzeyin üstüne çıkmadan o tavana indir."""
    get_mute, set_mute, get_volume, set_volume = _volume_indices(kind)
    if gain is None:
        if not _get_mute(volume, get_mute):
            _set_mute(volume, set_mute, True)
        return
    target = min(prior.volume, max(0.0, min(1.0, gain)))
    if _get_mute(volume, get_mute):
        _set_mute(volume, set_mute, False)
    if abs(_get_scalar(volume, get_volume) - target) > 0.02:
        _set_scalar(volume, set_volume, target)


def _restore_level(volume, kind: str, prior: PriorLevel) -> None:
    _get_mute_i, set_mute, _get_volume_i, set_volume = _volume_indices(kind)
    if prior.muted:
        _set_mute(volume, set_mute, True)
        _set_scalar(volume, set_volume, prior.volume)
        return
    _set_scalar(volume, set_volume, prior.volume)
    if _get_mute(volume, _get_mute_i):
        _set_mute(volume, set_mute, False)


def _qi(pointer, iid: str):
    out = ct.c_void_p()
    result = _method(pointer, 0, ct.c_int32, ct.POINTER(_GUID), ct.POINTER(ct.c_void_p))(
        pointer, ct.byref(_guid(iid)), ct.byref(out),
    )
    if result < 0 or not out:
        _release(out)
        return None
    return out


class WindowsRenderMute:
    """Render uçlarını ve oturumlarını önceki bitlerine dönecek şekilde susturur."""

    def __init__(self, tree=None):
        self._tree = process_tree_pids if tree is None else tree

    def endpoint_level(self, endpoint_id: str) -> PriorLevel:
        with _Com() as com:
            enumerator = com.enumerator()
            try:
                device = self._device(enumerator, endpoint_id)
                try:
                    volume = _activate(device, _IID_ENDPOINT_VOLUME)
                    try:
                        return _read_level(volume, "endpoint")
                    finally:
                        _release(volume)
                finally:
                    _release(device)
            finally:
                _release(enumerator)

    def endpoint_muted(self, endpoint_id: str) -> bool:
        return self.endpoint_level(endpoint_id).muted

    def first_session_muted(self) -> bool | None:
        """İlk oturumun susturma bitini okur ve aynı değeri geri yazar."""
        found: list[bool] = []
        with _Com() as com:
            enumerator = com.enumerator()
            try:
                for device in self._render_devices(com, enumerator):
                    try:
                        def _peek(pid, instance, simple):
                            if found:
                                return
                            current = _get_mute(simple, _SESSION_GET_MUTE)
                            _set_mute(simple, _SESSION_SET_MUTE, current)
                            if _get_mute(simple, _SESSION_GET_MUTE) != current:
                                raise OSError("session mute bit did not round-trip")
                            found.append(current)

                        self._each_session(com, device, _peek)
                        if found:
                            break
                    finally:
                        _release(device)
            finally:
                _release(enumerator)
        return found[0] if found else None

    def session_pids(self) -> list[int]:
        found: list[int] = []
        with _Com() as com:
            enumerator = com.enumerator()
            try:
                for device in self._render_devices(com, enumerator):
                    try:
                        self._each_session(com, device, lambda pid, _instance, _simple: found.append(pid))
                    finally:
                        _release(device)
            finally:
                _release(enumerator)
        return found

    def apply(self, plan: DubPlan) -> MuteHold:
        hold = MuteHold(plan)
        try:
            with _Com() as com:
                enumerator = com.enumerator()
                try:
                    if plan.action == "mute_endpoint":
                        self._touch_endpoint(com, enumerator, plan.endpoint_id, hold)
                    elif plan.action in ("mute_process", "mute_other_sessions"):
                        self._touch_sessions(com, enumerator, plan, hold)
                    else:
                        return hold
                finally:
                    _release(enumerator)
            return hold
        except Exception:
            self.restore(hold)
            raise

    def refresh(self, hold: MuteHold) -> None:
        if hold is None or hold.plan.action == "idle":
            return
        with _Com() as com:
            enumerator = com.enumerator()
            try:
                if hold.plan.action == "mute_endpoint":
                    self._touch_endpoint(com, enumerator, hold.plan.endpoint_id, hold)
                elif hold.plan.action in ("mute_process", "mute_other_sessions"):
                    self._touch_sessions(com, enumerator, hold.plan, hold)
            finally:
                _release(enumerator)

    def restore(self, hold: MuteHold | None) -> None:
        if hold is None or (not hold.endpoints and not hold.sessions):
            if hold is not None:
                hold.endpoints.clear()
                hold.sessions.clear()
            return
        try:
            with _Com() as com:
                enumerator = com.enumerator()
                try:
                    for endpoint_id, previous in list(hold.endpoints.items()):
                        device = None
                        try:
                            device = self._device(enumerator, endpoint_id)
                            volume = _activate(device, _IID_ENDPOINT_VOLUME)
                            try:
                                _restore_level(volume, "endpoint", previous)
                            finally:
                                _release(volume)
                        except OSError:
                            pass
                        finally:
                            _release(device)
                    if hold.sessions:
                        wanted = dict(hold.sessions)
                        for device in self._render_devices(com, enumerator):
                            try:
                                endpoint_id = _device_id(com, device).casefold()

                                def _restore_one(pid, instance, simple, endpoint_id=endpoint_id):
                                    key = (endpoint_id, instance)
                                    if key in wanted:
                                        _restore_level(simple, "session", wanted[key])

                                try:
                                    self._each_session(com, device, _restore_one)
                                except OSError:
                                    pass
                            finally:
                                _release(device)
                finally:
                    _release(enumerator)
        finally:
            hold.endpoints.clear()
            hold.sessions.clear()

    def _tree_of(self, plan: DubPlan) -> set[int]:
        try:
            tree = set(self._tree(plan.root_pid))
        except Exception:
            tree = set()
        tree.add(int(plan.root_pid))
        return tree

    def _device(self, enumerator, endpoint_id: str):
        device = ct.c_void_p()
        _check(_method(enumerator, 5, ct.c_int32, ct.c_wchar_p, ct.POINTER(ct.c_void_p))(
            enumerator, endpoint_id, ct.byref(device),
        ), "IMMDeviceEnumerator.GetDevice")
        if not device:
            raise OSError(f"Audio endpoint not found: {endpoint_id}")
        return device

    def _render_devices(self, com: _Com, enumerator):
        collection = ct.c_void_p()
        _check(_method(enumerator, 3, ct.c_int32, ct.c_int32, ct.c_uint32, ct.POINTER(ct.c_void_p))(
            enumerator, _E_RENDER, _DEVICE_STATE_ACTIVE, ct.byref(collection),
        ), "EnumAudioEndpoints")
        try:
            count = ct.c_uint32()
            _check(_method(collection, 3, ct.c_int32, ct.POINTER(ct.c_uint32))(
                collection, ct.byref(count),
            ), "IMMDeviceCollection.GetCount")
            for index in range(count.value):
                device = ct.c_void_p()
                _check(_method(collection, 4, ct.c_int32, ct.c_uint32, ct.POINTER(ct.c_void_p))(
                    collection, index, ct.byref(device),
                ), "IMMDeviceCollection.Item")
                if device:
                    yield device
        finally:
            _release(collection)

    def _each_session(self, com: _Com, device, visitor) -> None:
        manager = _activate(device, _IID_SESSION_MANAGER)
        enumerator = ct.c_void_p()
        try:
            _check(_method(manager, 5, ct.c_int32, ct.POINTER(ct.c_void_p))(
                manager, ct.byref(enumerator),
            ), "IAudioSessionManager2.GetSessionEnumerator")
            count = ct.c_int()
            _check(_method(enumerator, 3, ct.c_int32, ct.POINTER(ct.c_int))(
                enumerator, ct.byref(count),
            ), "IAudioSessionEnumerator.GetCount")
            for index in range(max(0, count.value)):
                control = ct.c_void_p()
                result = _method(enumerator, 4, ct.c_int32, ct.c_int, ct.POINTER(ct.c_void_p))(
                    enumerator, index, ct.byref(control),
                )
                if result < 0 or not control:
                    _release(control)
                    continue
                control2 = simple = None
                try:
                    control2 = _qi(control, _IID_SESSION_CONTROL2)
                    simple = _qi(control, _IID_SIMPLE_VOLUME)
                    if control2 is None or simple is None:
                        continue
                    pid = ct.c_uint32()
                    if _method(control2, 14, ct.c_int32, ct.POINTER(ct.c_uint32))(
                        control2, ct.byref(pid),
                    ) < 0:
                        continue
                    raw = ct.c_void_p()
                    if _method(control2, 13, ct.c_int32, ct.POINTER(ct.c_void_p))(
                        control2, ct.byref(raw),
                    ) < 0:
                        instance = f"pid:{int(pid.value)}:{index}"
                    else:
                        instance = com.task_string(raw) or f"pid:{int(pid.value)}:{index}"
                    visitor(int(pid.value), instance, simple)
                finally:
                    _release(simple)
                    _release(control2)
                    _release(control)
        finally:
            _release(enumerator)
            _release(manager)

    def _touch_endpoint(self, com: _Com, enumerator, endpoint_id: str, hold: MuteHold) -> None:
        device = self._device(enumerator, endpoint_id)
        try:
            volume = _activate(device, _IID_ENDPOINT_VOLUME)
            try:
                existing = next(
                    (key for key in hold.endpoints if key.casefold() == endpoint_id.casefold()),
                    None,
                )
                if existing is None:
                    hold.endpoints[endpoint_id] = _read_level(volume, "endpoint")
                    existing = endpoint_id
                _shape_level(volume, "endpoint", hold.endpoints[existing], hold.plan.gain)
            finally:
                _release(volume)
        finally:
            _release(device)

    def _touch_sessions(self, com: _Com, enumerator, plan: DubPlan, hold: MuteHold) -> None:
        # Ağaç her turda yeniden okunur; tarayıcı çeviri sırasında yeni süreç açar.
        tree = self._tree_of(plan)

        def _wanted(pid: int) -> bool:
            if plan.action == "mute_process":
                return pid in tree
            if plan.action == "mute_other_sessions":
                return pid not in tree
            return False

        for device in self._render_devices(com, enumerator):
            try:
                endpoint_id = _device_id(com, device).casefold()

                def _touch(pid, instance, simple, endpoint_id=endpoint_id):
                    if not _wanted(pid):
                        return
                    key = (endpoint_id, instance)
                    if key not in hold.sessions:
                        hold.sessions[key] = _read_level(simple, "session")
                    _shape_level(simple, "session", hold.sessions[key], plan.gain)

                self._each_session(com, device, _touch)
            finally:
                _release(device)
