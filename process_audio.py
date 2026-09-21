"""Windows process-tree loopback capture, without a system-mix fallback.

Activation follows Microsoft's ApplicationLoopback sample. Audio interfaces stay
on the context-manager thread; only activation notification crosses threads.
"""

from __future__ import annotations

import ctypes as ct
import functools
import math
import operator
import os
import sys
import threading
import time
import uuid
import weakref

import numpy as np


_HRESULT = ct.c_int32
_DWORD = ct.c_uint32
_CALL = getattr(ct, "WINFUNCTYPE", ct.CFUNCTYPE)
_WAIT_TIMEOUT = 258
_WAIT_FAILED = 0xFFFFFFFF
_ACTIVATION_TIMEOUT = 5.0


class _GUID(ct.Structure):
    _fields_ = [
        ("Data1", ct.c_uint32),
        ("Data2", ct.c_uint16),
        ("Data3", ct.c_uint16),
        ("Data4", ct.c_ubyte * 8),
    ]


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


_IID_IUNKNOWN = _guid("00000000-0000-0000-C000-000000000046")
_IID_IAGILEOBJECT = _guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
_IID_IMARSHAL = _guid("00000003-0000-0000-C000-000000000046")
_IID_COMPLETION = _guid("41D949AB-9862-444A-80F6-C261334DA5EB")
_IID_AUDIOCLIENT = _guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
_IID_CAPTURECLIENT = _guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
_CALLBACK_IIDS = {bytes(iid) for iid in (_IID_IUNKNOWN, _IID_IAGILEOBJECT, _IID_COMPLETION)}


class _ProcessLoopbackParams(ct.Structure):
    _fields_ = [("TargetProcessId", _DWORD), ("ProcessLoopbackMode", ct.c_int32)]


class _ActivationParams(ct.Structure):
    _fields_ = [("ActivationType", ct.c_int32), ("ProcessLoopbackParams", _ProcessLoopbackParams)]


class _Blob(ct.Structure):
    _fields_ = [("cbSize", _DWORD), ("pBlobData", ct.c_void_p)]


class _VariantValue(ct.Union):
    _fields_ = [("blob", _Blob), ("alignment", ct.c_uint64)]


class _PropVariant(ct.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", ct.c_uint16),
        ("reserved1", ct.c_uint16),
        ("reserved2", ct.c_uint16),
        ("reserved3", ct.c_uint16),
        ("value", _VariantValue),
    ]


class _WaveFormat(ct.Structure):
    # WAVEFORMATEX comes from the byte-packed mmreg.h, not native struct packing.
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", ct.c_uint16),
        ("nChannels", ct.c_uint16),
        ("nSamplesPerSec", _DWORD),
        ("nAvgBytesPerSec", _DWORD),
        ("nBlockAlign", ct.c_uint16),
        ("wBitsPerSample", ct.c_uint16),
        ("cbSize", ct.c_uint16),
    ]


def process_audio_supported() -> bool:
    """Process loopback requires Windows build 20348 or newer."""
    return sys.platform == "win32" and sys.getwindowsversion().build >= 20348


def _check(result: int, operation: str) -> None:
    if result < 0:
        code = result & 0xFFFFFFFF
        raise OSError(f"{operation} failed (HRESULT 0x{code:08X}): {ct.FormatError(code).strip()}")


def _method(pointer, index: int, result, *arguments):
    vtable = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return _CALL(result, ct.c_void_p, *arguments)(vtable[index])


def _release(pointer) -> None:
    if pointer:
        _method(pointer, 2, _DWORD)(pointer)


class _WindowsAudio:
    def __init__(self):
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.ole = ct.WinDLL("ole32")
        self.mmdev = ct.WinDLL("mmdevapi")
        signatures = (
            (self.kernel.OpenProcess, ct.c_void_p, (_DWORD, ct.c_int32, _DWORD)),
            (self.kernel.CloseHandle, ct.c_int32, (ct.c_void_p,)),
            (self.kernel.WaitForSingleObject, _DWORD, (ct.c_void_p, _DWORD)),
            (self.kernel.WaitForMultipleObjects, _DWORD, (_DWORD, ct.POINTER(ct.c_void_p), ct.c_int32, _DWORD)),
            (self.kernel.CreateEventW, ct.c_void_p, (ct.c_void_p, ct.c_int32, ct.c_int32, ct.c_wchar_p)),
            (self.ole.CoInitializeEx, _HRESULT, (ct.c_void_p, _DWORD)),
            (self.ole.CoUninitialize, None, ()),
            (self.ole.CoCreateFreeThreadedMarshaler, _HRESULT, (ct.c_void_p, ct.POINTER(ct.c_void_p))),
            (self.mmdev.ActivateAudioInterfaceAsync, _HRESULT, (
                ct.c_wchar_p, ct.POINTER(_GUID), ct.POINTER(_PropVariant),
                ct.c_void_p, ct.POINTER(ct.c_void_p),
            )),
        )
        for function, result, arguments in signatures:
            function.restype = result
            function.argtypes = arguments


@functools.lru_cache(maxsize=1)
def _windows_audio() -> _WindowsAudio:
    return _WindowsAudio()


# These trampolines and their vtable live for the module's lifetime. In particular,
# native Release must never free its own ctypes callback while it is executing.
_QueryInterface = _CALL(_HRESULT, ct.c_void_p, ct.POINTER(_GUID), ct.POINTER(ct.c_void_p))
_AddRef = _CALL(_DWORD, ct.c_void_p)
_Release = _CALL(_DWORD, ct.c_void_p)
_ActivateCompleted = _CALL(_HRESULT, ct.c_void_p, ct.c_void_p)
_activations: dict[int, _Activation] = {}
_activation_lock = threading.Lock()


@_QueryInterface
def _query_interface(this, iid, output):
    if not output:
        return -2147467261  # E_POINTER
    output[0] = None
    if not iid:
        return -2147467261
    try:
        with _activation_lock:
            activation = _activations[this]
        requested = bytes(iid.contents)
        if requested in _CALLBACK_IIDS:
            _add_ref(this)
            output[0] = this
            return 0
        if requested == bytes(_IID_IMARSHAL) and activation.marshaler:
            return _method(activation.marshaler, 0, _HRESULT,
                           ct.POINTER(_GUID), ct.POINTER(ct.c_void_p))(
                activation.marshaler, iid, output)
        return -2147467262  # E_NOINTERFACE
    except BaseException:
        return -2147467259  # E_FAIL; Python exceptions cannot cross a COM callback.


@_AddRef
def _add_ref(this):
    with _activation_lock:
        activation = _activations[this]
        activation.references += 1
        return activation.references


@_Release
def _release_callback(this):
    with _activation_lock:
        activation = _activations[this]
        activation.references -= 1
        remaining = activation.references
        if not remaining:
            del _activations[this]
    if not remaining:
        _release(activation.marshaler)
        activation.marshaler = ct.c_void_p()
    return remaining


@_ActivateCompleted
def _activate_completed(this, operation):
    try:
        with _activation_lock:
            activation = _activations[this]
        # GetActivateResult runs on the owning MTA thread, not this callback.
        activation.completed.set()
        return 0
    except BaseException:
        return -2147467259


class _CompletionVTable(ct.Structure):
    _fields_ = [
        ("QueryInterface", _QueryInterface), ("AddRef", _AddRef),
        ("Release", _Release), ("ActivateCompleted", _ActivateCompleted),
    ]


class _CompletionObject(ct.Structure):
    _fields_ = [("vtable", ct.POINTER(_CompletionVTable))]


_completion_vtable = _CompletionVTable(_query_interface, _add_ref, _release_callback, _activate_completed)


# PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE / EXCLUDE_TARGET_PROCESS_TREE.
PROCESS_LOOPBACK_INCLUDE = 0
PROCESS_LOOPBACK_EXCLUDE = 1


class _Activation:
    def __init__(self, api: _WindowsAudio, pid: int, loopback_mode: int = PROCESS_LOOPBACK_INCLUDE):
        self.completed = threading.Event()
        self.references = 1
        self.marshaler = ct.c_void_p()
        self.interface = _CompletionObject(ct.pointer(_completion_vtable))
        self.address = ct.addressof(self.interface)
        # ActivationType=PROCESS_LOOPBACK. Exclude keeps every other process's
        # stream, which is how same-speaker dubbing still hears the source.
        self.params = _ActivationParams(1, _ProcessLoopbackParams(pid, int(loopback_mode)))
        self.variant = _PropVariant()
        self.variant.vt = 65  # VT_BLOB
        self.variant.blob = _Blob(ct.sizeof(self.params), ct.addressof(self.params))
        with _activation_lock:
            _activations[self.address] = self
        try:
            _check(api.ole.CoCreateFreeThreadedMarshaler(self.address, ct.byref(self.marshaler)),
                   "CoCreateFreeThreadedMarshaler")
        except BaseException:
            _release_callback(self.address)
            raise


class ProcessRecorder:
    """Capture one process incarnation and its descendants at 48 kHz.

    Constructing pins the process identity with a live handle. Enter, record and
    close on one thread. WASAPI chooses the event-driven native buffer size;
    blocksize is the caller's preferred read size, not a device-period request.
    """

    def __init__(self, pid: int, *, samplerate: int, channels: int, blocksize: int,
                 loopback_mode: int = PROCESS_LOOPBACK_INCLUDE):
        if not process_audio_supported():
            raise RuntimeError("Application audio capture requires Windows build 20348 or newer.")
        self.pid = operator.index(pid)
        self._loopback_mode = int(loopback_mode)
        if self._loopback_mode not in (PROCESS_LOOPBACK_INCLUDE, PROCESS_LOOPBACK_EXCLUDE):
            raise ValueError("loopback_mode must be include (0) or exclude (1)")
        self.samplerate = operator.index(samplerate)
        self.channels = operator.index(channels)
        self.blocksize = operator.index(blocksize)
        if not 0 < self.pid <= 0xFFFFFFFF:
            raise ValueError("pid must be a positive Windows process ID")
        if self.samplerate != 48000 or self.channels not in (1, 2):
            raise ValueError("Application audio capture supports only 48000 Hz mono or stereo")
        if not 0 < self.blocksize <= 0xFFFFFFFF:
            raise ValueError("blocksize must be a positive 32-bit frame count")
        self._api = _windows_audio()
        self._thread = None
        self._closed = False
        self._com_initialized = False
        self._started = False
        self._client = ct.c_void_p()
        self._capture = ct.c_void_p()
        self._sample_event = None
        self._pending = None
        self._pending_offset = 0
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION. A held process handle
        # also prevents its PID being recycled while activation is in flight.
        self._process = self._api.kernel.OpenProcess(0x00101000, False, self.pid)
        if not self._process:
            error = ct.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process no longer exists.
                raise ProcessLookupError(f"Application process {self.pid} has exited")
            raise ct.WinError(error)
        # Also handles a recorder constructed but never entered, without releasing
        # COM interfaces from an arbitrary garbage-collector thread.
        self._process_finalizer = weakref.finalize(self, self._api.kernel.CloseHandle, self._process)
        try:
            self._check_process()
        except BaseException:
            self._process_finalizer()
            self._closed = True
            raise

    def _check_process(self) -> None:
        result = self._api.kernel.WaitForSingleObject(self._process, 0)
        if result == 0:
            raise ProcessLookupError(f"Application process {self.pid} has exited")
        if result == _WAIT_FAILED:
            raise ct.WinError(ct.get_last_error())
        if result != _WAIT_TIMEOUT:
            raise OSError(f"Unexpected process wait result: {result}")

    def _check_thread(self) -> None:
        if self._thread is not None and self._thread is not threading.current_thread():
            raise RuntimeError("ProcessRecorder must be used and closed on its opening thread")

    def _activate(self) -> None:
        activation = _Activation(self._api, self.pid, self._loopback_mode)
        operation = ct.c_void_p()
        unknown = ct.c_void_p()
        try:
            _check(self._api.mmdev.ActivateAudioInterfaceAsync(
                "VAD\\Process_Loopback", ct.byref(_IID_AUDIOCLIENT),
                ct.byref(activation.variant), activation.address, ct.byref(operation)),
                "ActivateAudioInterfaceAsync")
            deadline = time.monotonic() + _ACTIVATION_TIMEOUT
            while not activation.completed.wait(min(0.05, max(0.0, deadline - time.monotonic()))):
                self._check_process()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Application audio activation timed out")
            self._check_process()
            result = _HRESULT()
            _check(_method(operation, 3, _HRESULT, ct.POINTER(_HRESULT), ct.POINTER(ct.c_void_p))(
                operation, ct.byref(result), ct.byref(unknown)), "GetActivateResult")
            _check(result.value, "Application audio activation")
            if not unknown:
                raise OSError("Application audio activation returned no interface")
            _check(_method(unknown, 0, _HRESULT, ct.POINTER(_GUID), ct.POINTER(ct.c_void_p))(
                unknown, ct.byref(_IID_AUDIOCLIENT), ct.byref(self._client)), "QueryInterface(IAudioClient)")
        finally:
            _release(unknown)
            _release(operation)
            # Windows retains its own callback reference until completion, even
            # after timeout. The registry keeps callback/parameters/marshaler alive
            # until native Release; the async operation owns any unclaimed result.
            _release_callback(activation.address)

    def __enter__(self) -> ProcessRecorder:
        if self._closed or self._thread is not None:
            raise RuntimeError("ProcessRecorder cannot be entered more than once")
        self._thread = threading.current_thread()
        try:
            self._check_process()
            _check(self._api.ole.CoInitializeEx(None, 0), "CoInitializeEx(MTA)")
            self._com_initialized = True
            self._activate()
            self._sample_event = self._api.kernel.CreateEventW(None, False, False, None)
            if not self._sample_event:
                raise ct.WinError(ct.get_last_error())
            audio_format = _WaveFormat(3, self.channels, self.samplerate,
                                       self.samplerate * self.channels * 4, self.channels * 4, 32, 0)
            # SHARED, LOOPBACK | EVENTCALLBACK | AUTOCONVERTPCM. Float samples
            # avoid an extra PCM conversion and preserve WASAPI's dynamic range.
            _check(_method(self._client, 3, _HRESULT, ct.c_int32, _DWORD, ct.c_int64,
                           ct.c_int64, ct.POINTER(_WaveFormat), ct.POINTER(_GUID))(
                self._client, 0, 0x88060000, 0, 0, ct.byref(audio_format), None), "IAudioClient.Initialize")
            _check(_method(self._client, 13, _HRESULT, ct.c_void_p)(
                self._client, self._sample_event), "IAudioClient.SetEventHandle")
            _check(_method(self._client, 14, _HRESULT, ct.POINTER(_GUID), ct.POINTER(ct.c_void_p))(
                self._client, ct.byref(_IID_CAPTURECLIENT), ct.byref(self._capture)), "IAudioClient.GetService")
            self._next_packet = _method(self._capture, 5, _HRESULT, ct.POINTER(_DWORD))
            self._get_buffer = _method(self._capture, 3, _HRESULT, ct.POINTER(ct.c_void_p),
                                       ct.POINTER(_DWORD), ct.POINTER(_DWORD),
                                       ct.POINTER(ct.c_uint64), ct.POINTER(ct.c_uint64))
            self._release_buffer = _method(self._capture, 4, _HRESULT, _DWORD)
            self._packet_size = _DWORD()
            self._data = ct.c_void_p()
            self._frames = _DWORD()
            self._flags = _DWORD()
            self._wait_handles = (ct.c_void_p * 2)(self._process, self._sample_event)
            self._check_process()
            _check(_method(self._client, 10, _HRESULT)(self._client), "IAudioClient.Start")
            self._started = True
            return self
        except BaseException:
            self.close()
            raise

    def record(self, numframes: int) -> np.ndarray:
        """Return ordered float32 frames; an idle source yields paced zeros."""
        self._check_thread()
        if not self._started or self._closed:
            raise RuntimeError("ProcessRecorder is not open")
        numframes = operator.index(numframes)
        if not 0 < numframes <= 0xFFFFFFFF:
            raise ValueError("numframes must be a positive 32-bit frame count")
        self._check_process()
        output = np.empty((numframes, self.channels), dtype=np.float32)
        address = output.ctypes.data
        frame_bytes = self.channels * 4
        written = 0
        deadline = time.monotonic() + numframes / self.samplerate
        if self._pending is not None:
            count = min(numframes, len(self._pending) - self._pending_offset)
            output[:count] = self._pending[self._pending_offset:self._pending_offset + count]
            written = count
            self._pending_offset += count
            if self._pending_offset == len(self._pending):
                self._pending = None
                self._pending_offset = 0
        while written < numframes:
            self._check_process()
            _check(self._next_packet(self._capture, ct.byref(self._packet_size)), "GetNextPacketSize")
            if self._packet_size.value:
                _check(self._get_buffer(self._capture, ct.byref(self._data), ct.byref(self._frames),
                                        ct.byref(self._flags), None, None), "IAudioCaptureClient.GetBuffer")
                frames = self._frames.value
                try:
                    if not frames:
                        continue
                    count = min(numframes - written, frames)
                    silent = bool(self._flags.value & 2)  # AUDCLNT_BUFFERFLAGS_SILENT
                    if silent:
                        output[written:written + count].fill(0)
                    elif self._data.value:
                        ct.memmove(address + written * frame_bytes, self._data, count * frame_bytes)
                    else:
                        raise OSError("WASAPI returned a null non-silent audio packet")
                    if count < frames:
                        self._pending = np.empty((frames - count, self.channels), dtype=np.float32)
                        self._pending_offset = 0
                        if silent:
                            self._pending.fill(0)
                        else:
                            ct.memmove(self._pending.ctypes.data, self._data.value + count * frame_bytes,
                                       (frames - count) * frame_bytes)
                    written += count
                finally:
                    _check(self._release_buffer(self._capture, frames), "IAudioCaptureClient.ReleaseBuffer")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                output[written:].fill(0)
                break
            # Auto-reset audio event, process-exit signal, or read deadline. No
            # polling spin and no indefinite wait when the selected app is idle.
            result = self._api.kernel.WaitForMultipleObjects(
                2, self._wait_handles, False, min(0xFFFFFFFE, max(1, math.ceil(remaining * 1000))))
            if result == 0:
                raise ProcessLookupError(f"Application process {self.pid} has exited")
            if result == _WAIT_FAILED:
                raise ct.WinError(ct.get_last_error())
            if result not in (1, _WAIT_TIMEOUT):
                raise OSError(f"Unexpected audio wait result: {result}")
        self._check_process()
        return output

    def close(self) -> None:
        self._check_thread()
        if self._closed:
            return
        self._closed = True
        stop_result = 0
        try:
            if self._started:
                stop_result = _method(self._client, 11, _HRESULT)(self._client)
                self._started = False
        finally:
            _release(self._capture)
            self._capture = ct.c_void_p()
            _release(self._client)
            self._client = ct.c_void_p()
            if self._sample_event:
                self._api.kernel.CloseHandle(self._sample_event)
                self._sample_event = None
            self._process_finalizer()
            self._pending = None
            if self._com_initialized:
                self._api.ole.CoUninitialize()
                self._com_initialized = False
        _check(stop_result, "IAudioClient.Stop")

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self.close()
        except OSError:
            if exc_type is None:
                raise


def exclude_self_recorder(*, samplerate: int, channels: int, blocksize: int, pid: int | None = None) -> ProcessRecorder:
    """Sistemdeki diğer süreçlerin sesi; bu sürecin çaldığı çeviri karışmaz."""
    return ProcessRecorder(
        os.getpid() if pid is None else pid,
        samplerate=samplerate,
        channels=channels,
        blocksize=blocksize,
        loopback_mode=PROCESS_LOOPBACK_EXCLUDE,
    )
