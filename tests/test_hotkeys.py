from types import SimpleNamespace

import pytest

from hotkeys import ShortcutError, parse_shortcut, shortcut_from_tk_event


def test_shortcut_normalization_and_virtual_keys():
    assert parse_shortcut("shift+ctrl+m") == ("Ctrl+Shift+M", 0x4006, ord("M"))
    assert parse_shortcut("F24") == ("F24", 0x4000, 0x87)
    assert parse_shortcut("Alt+PageDown") == ("Alt+PageDown", 0x4001, 0x22)


def test_shortcut_requires_modifier_except_function_keys():
    with pytest.raises(ShortcutError, match="Ctrl, Alt veya Shift"):
        parse_shortcut("M")
    with pytest.raises(ShortcutError, match="Desteklenmeyen"):
        parse_shortcut("Ctrl+Question")


def test_tk_event_capture_and_modifier_only_key():
    event = SimpleNamespace(keysym="m", state=0x0004 | 0x0001)
    assert shortcut_from_tk_event(event) == "Ctrl+Shift+M"
    modifier = SimpleNamespace(keysym="Control_L", state=0x0004)
    assert shortcut_from_tk_event(modifier) == ""


def test_punctuation_and_numpad_shortcuts_parse():
    assert parse_shortcut("ctrl+Plus") == ("Ctrl+Plus", 0x4002, 0xBB)
    assert parse_shortcut("Alt+Num5") == ("Alt+Num5", 0x4001, 0x65)
    assert parse_shortcut("Ctrl+Semicolon") == ("Ctrl+Semicolon", 0x4002, 0xBA)


def test_keycode_capture_handles_shifted_digit(monkeypatch):
    import hotkeys

    monkeypatch.setattr(hotkeys.sys, "platform", "win32")
    event = SimpleNamespace(keysym="exclam", keycode=0x31, state=0x0004 | 0x0001)
    assert shortcut_from_tk_event(event) == "Ctrl+Shift+1"

    numpad = SimpleNamespace(keysym="KP_End", keycode=0x61, state=0x0004)
    assert shortcut_from_tk_event(numpad) == "Ctrl+Num1"


def test_numlock_mod1_bit_is_not_captured_as_alt_on_windows(monkeypatch):
    import hotkeys

    monkeypatch.setattr(hotkeys.sys, "platform", "win32")
    # NumLock açıkken Tk state'te Mod1Mask (0x0008) görünür; Alt sanılmamalı.
    ctrl_numlock = SimpleNamespace(keysym="m", keycode=0x4D, state=0x0004 | 0x0008)
    assert shortcut_from_tk_event(ctrl_numlock) == "Ctrl+M"

    ctrl_shift_numlock = SimpleNamespace(
        keysym="m", keycode=0x4D, state=0x0004 | 0x0001 | 0x0008
    )
    assert shortcut_from_tk_event(ctrl_shift_numlock) == "Ctrl+Shift+M"

    ctrl_alt = SimpleNamespace(keysym="m", keycode=0x4D, state=0x0004 | 0x0008 | 0x20000)
    assert shortcut_from_tk_event(ctrl_alt) == "Ctrl+Alt+M"
