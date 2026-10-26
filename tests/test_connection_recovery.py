"""API kopmaları: sınırlı yeniden deneme, iptal ve Windows bildirimi."""

import asyncio
import ctypes
import queue
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gui.app import App, _is_retryable_error, _worker_error, format_user_error
from notifications import WindowsNotifier, _NOTIFYICONDATAW


@pytest.mark.parametrize("error", [
    ConnectionResetError("peer reset"),
    TimeoutError(),
    RuntimeError("keepalive ping timeout"),
    RuntimeError("Service unavailable"),
    type("RemoteProtocolError", (Exception,), {})("peer closed"),
    type("Closed", (Exception,), {"rcvd": SimpleNamespace(code=1011)})("internal error"),
    type("Closed", (Exception,), {"code": 1000})("normal closure"),
    type("ServerError", (Exception,), {"code": 503})("unavailable"),
])
def test_transient_errors_are_retryable(error):
    assert _is_retryable_error(error)


@pytest.mark.parametrize("error", [
    RuntimeError("API_KEY_INVALID"),
    RuntimeError("quota exceeded"),
    type("Closed", (Exception,), {"rcvd": SimpleNamespace(code=1008)})("policy violation"),
    RuntimeError("Giriş ses aygıtı hatası"),
    type("ClientError", (Exception,), {"code": 401})("unauthorized"),
])
def test_permanent_errors_are_not_retried(error):
    assert not _is_retryable_error(error)


def test_nested_task_group_errors_are_unwrapped():
    network = ConnectionResetError("reset")
    error = ExceptionGroup("outer", [ExceptionGroup("inner", [network])])
    assert _worker_error(error) is network
    permanent = RuntimeError("API_KEY_INVALID")
    assert _worker_error(ExceptionGroup("mixed", [network, permanent])) is permanent


@pytest.mark.parametrize("reason", [
    "1008 (policy violation) Maximum session duration exceeded",
    "1008 (policy violation) Session has expired",
    "1008 (policy violation) Session time limit exceeded",
])
def test_session_limits_are_not_misreported_as_access_denied(reason):
    error = RuntimeError(reason)
    assert _is_retryable_error(error)
    message = format_user_error(error)
    assert "Google projesinin Gemini Live erişimi reddedildi" not in message
    assert reason in message


def test_generic_1008_retries_only_after_session_was_established():
    error = RuntimeError("1008 (policy violation)")
    assert not _is_retryable_error(error)
    assert _is_retryable_error(error, session_established=True)


def test_explicit_access_denial_stays_permanent_in_long_sessions():
    error = RuntimeError("1008 (policy violation) Your project has been denied access. Please contact support.")
    assert not _is_retryable_error(error, session_established=True)
    assert "Live erişimi reddedildi" in format_user_error(error)


def test_invalid_key_takes_priority_over_generic_1008_message():
    message = format_user_error(RuntimeError("1008 policy violation: API_KEY_INVALID"))
    assert "Geçersiz API anahtarı" in message


def run_worker(monkeypatch, outcomes, *, stop_during_wait=False, stable=False, established=False):
    made = []
    waits = []
    stopping = threading.Event()

    class FakeLoop:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.connected_at = 0.0
            made.append(self)

        async def run(self):
            result = outcomes[len(made) - 1]
            if established and len(made) == 1:
                self.connected_at = time.monotonic()
            if stable and len(made) == 3:
                self.connected_at = time.monotonic() - 60
            if isinstance(result, BaseException):
                raise result

        def pause(self):
            self.is_paused = True

        def set_dub_exclude(self, enabled):
            self._dub_exclude = enabled

    def wait(delay):
        waits.append(delay)
        if stop_during_wait:
            stopping.set()
        return stopping.is_set()

    monkeypatch.setattr(stopping, "wait", wait)
    monkeypatch.setattr("gui.app.SystemAudioLoop", FakeLoop)
    monkeypatch.setattr("gui.app.log_exception", lambda *_: None)
    first = FakeLoop(source_mic="current input", output_speaker="current output", volume=0.5,
                     muted=True, vad_threshold=0.01, is_paused=True, _dub_exclude=True)
    app = SimpleNamespace(_session_id=7, _stopping=stopping, loop_obj=first,
                          _loop_kwargs={}, log_queue=queue.Queue())
    App._run(app)
    return list(app.log_queue.queue), made, waits


def test_exactly_three_retries_then_one_notification(monkeypatch):
    messages, made, waits = run_worker(monkeypatch, [ConnectionError("network")] * 4)
    assert len(made) == 4  # İlk kopma + üç yeniden bağlanma.
    assert waits == [2, 2, 2]
    assert messages.count(("connection_failed", 7)) == 1
    assert messages[-1] == ("__stopped__", 7)
    for loop in made[1:]:
        assert loop.source_mic == "current input"
        assert loop.output_speaker == "current output"
        assert loop.volume == 0.5
        assert loop.muted and loop.is_paused and loop._dub_exclude


def test_worker_retries_1008_after_active_session_then_notifies(monkeypatch):
    messages, made, waits = run_worker(monkeypatch, [
        RuntimeError("1008 policy violation"),
        ConnectionError("network"), ConnectionError("network"), ConnectionError("network"),
    ], established=True)
    assert len(made) == 4
    assert waits == [2, 2, 2]
    assert messages.count(("connection_failed", 7)) == 1


def test_worker_does_not_retry_explicit_access_denial_after_active_session(monkeypatch):
    messages, made, waits = run_worker(monkeypatch, [
        RuntimeError("1008 policy violation: Your project has been denied access."),
    ], established=True)
    assert len(made) == 1
    assert not waits
    assert not any(isinstance(msg, tuple) and msg[0] == "connection_failed" for msg in messages)


def test_successful_reconnect_does_not_notify(monkeypatch):
    messages, made, _ = run_worker(monkeypatch, [ConnectionError("network"), None])
    assert len(made) == 2
    assert not any(isinstance(msg, tuple) and msg[0] == "connection_failed" for msg in messages)


def test_manual_stop_during_retry_does_not_notify(monkeypatch):
    messages, made, _ = run_worker(monkeypatch, [ConnectionError("network")], stop_during_wait=True)
    assert len(made) == 1
    assert not any(isinstance(msg, tuple) and msg[0] == "connection_failed" for msg in messages)


def test_stable_connection_resets_retry_budget(monkeypatch):
    messages, made, waits = run_worker(monkeypatch, [ConnectionError("network")] * 6, stable=True)
    assert len(made) == 6
    assert len(waits) == 5
    assert messages.count(("connection_failed", 7)) == 1


def test_cancellation_does_not_retry_or_notify(monkeypatch):
    messages, made, waits = run_worker(monkeypatch, [asyncio.CancelledError()])
    assert len(made) == 1 and not waits
    assert messages == [("__stopped__", 7)]


def fake_notifier():
    notifier = WindowsNotifier.__new__(WindowsNotifier)
    notifier._data = _NOTIFYICONDATAW()
    notifier._data.cbSize = ctypes.sizeof(notifier._data)
    notifier._added = False
    notifier._notify = Mock(return_value=True)
    return notifier


def test_native_notification_add_modify_and_cleanup():
    notifier = fake_notifier()
    assert notifier.show("Ahenk — bağlantı kesildi", "İnternet bağlantınızı kontrol edin.")
    assert notifier._data.szInfoTitle == "Ahenk — bağlantı kesildi"
    assert notifier._data.szInfo == "İnternet bağlantınızı kontrol edin."
    assert notifier._data.dwInfoFlags == 2
    assert notifier.show("Again", "Message")
    notifier.close()
    notifier.close()
    assert [call.args[0] for call in notifier._notify.call_args_list] == [0, 1, 1, 2]


def test_notification_failure_is_reported_and_cleaned_up():
    notifier = fake_notifier()
    notifier._notify.side_effect = [True, False, True]
    assert not notifier.show("Failure", "Message")
    assert not notifier._added
    assert [call.args[0] for call in notifier._notify.call_args_list] == [0, 1, 2]


def test_no_notification_when_icon_cannot_be_added():
    notifier = fake_notifier()
    notifier._notify.return_value = False
    assert not notifier.show("Failure", "Message")
    assert notifier._notify.call_count == 1
