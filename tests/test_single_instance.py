"""Tek örnek: ikinci masaüstü başlatması yeni pencere açmaz."""

import os
import sys

import pytest

import single_instance
from single_instance import MUTEX_NAME, SingleInstance, claim_or_activate


@pytest.fixture
def isolated_mutex(monkeypatch):
    name = f"{MUTEX_NAME}.test.{os.getpid()}"
    monkeypatch.setattr(single_instance, "MUTEX_NAME", name)
    monkeypatch.setattr(single_instance.SingleInstance, "name", name, raising=False)
    return name


def test_activate_slot_roundtrip_wakes_thread():
    if os.name != "nt":
        pytest.skip("Windows mapping")
    from single_instance import MAPPING_NAME, ActivateSlot, activate_message_id, kernel32, user32

    name = f"{MAPPING_NAME}.{os.getpid()}"
    slot = ActivateSlot(name)
    assert slot.open()
    try:
        slot.publish(int(kernel32.GetCurrentThreadId()))
        ready, thread_id = slot.read()
        assert ready == 1
        assert thread_id == int(kernel32.GetCurrentThreadId())
        message = activate_message_id()
        assert user32.PostThreadMessageW(thread_id, message, 1, 1)
        import ctypes
        from ctypes import wintypes

        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL
        msg = wintypes.MSG()
        assert user32.PeekMessageW(ctypes.byref(msg), None, message, message, 1)
        assert int(msg.message) == message
        assert int(msg.wParam) == 1
        assert int(msg.lParam) == 1
    finally:
        slot.clear()
        slot.close()


def test_second_acquire_fails_and_release_allows_again():
    if os.name != "nt":
        pytest.skip("Windows mutex")
    name = f"{MUTEX_NAME}.{os.getpid()}"
    first = SingleInstance(name)
    second = SingleInstance(name)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        first.close()
        third = SingleInstance(name)
        assert third.acquire() is True
        third.close()
    finally:
        first.close()
        second.close()


def test_claim_returns_none_when_mutex_held(monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows mutex")
    name = f"{MUTEX_NAME}.claim.{os.getpid()}"

    class _Locked(SingleInstance):
        def __init__(self, mutex_name: str = MUTEX_NAME) -> None:
            super().__init__(name)

    monkeypatch.setattr(single_instance, "SingleInstance", _Locked)
    holder = SingleInstance(name)
    assert holder.acquire() is True
    monkeypatch.setattr(single_instance, "signal_existing", lambda *args, **kwargs: True)
    try:
        assert claim_or_activate() is None
    finally:
        holder.close()


def test_main_exits_without_gui_when_instance_exists(monkeypatch):
    import main

    monkeypatch.setattr("single_instance.claim_or_activate", lambda: None)

    def _boom(*args, **kwargs):
        raise AssertionError("gui")

    monkeypatch.setitem(sys.modules, "gui.app", type(sys)("gui.app"))
    sys.modules["gui.app"].App = _boom
    code = main.main(["Ahenk.exe"])
    assert code == 0


def test_update_helper_skips_single_instance(monkeypatch):
    import main
    from updater import HELPER_ARG

    monkeypatch.setattr(
        "single_instance.claim_or_activate",
        lambda: (_ for _ in ()).throw(AssertionError("kilit")),
    )
    monkeypatch.setattr("main.run_update_helper", lambda *args: 7)
    assert main.main(["Ahenk.exe", HELPER_ARG, "1", "target.exe", "aa" * 32]) == 7


def test_non_windows_always_acquires(monkeypatch):
    monkeypatch.setattr(single_instance.os, "name", "posix")
    lock = SingleInstance("ignored")
    assert lock.acquire() is True
    claimed = claim_or_activate()
    assert claimed is not None
    claimed[0].close()
