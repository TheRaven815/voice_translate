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
