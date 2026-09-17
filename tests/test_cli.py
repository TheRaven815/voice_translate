from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import cli


def test_cli_list_devices(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--list-devices"])
    with patch("cli.list_devices") as mock_list:
        cli.main()
        mock_list.assert_called_once()


def test_cli_missing_api_key_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py"])
    monkeypatch.setattr("cli.resolve_api_key", lambda _k: None)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "GEMINI_API_KEY bulunamadı" in out


def test_cli_runs_loop_with_args(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--src", "en", "--dst", "de", "--api-key", "test_key", "--model", "custom-model", "--mic"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    fake_speaker = MagicMock(name="FakeSpeaker")
    fake_speaker.name = "FakeSpeaker"

    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: fake_speaker)

    mock_loop_instance = MagicMock()
    mock_loop_cls = MagicMock(return_value=mock_loop_instance)
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run") as mock_run:
        cli.main()
        mock_loop_cls.assert_called_once_with(
            "en",
            "de",
            fake_source,
            "test_key",
            output_speaker=fake_speaker,
            model="custom-model",
        )
        mock_run.assert_called_once()
