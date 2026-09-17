from __future__ import annotations

import asyncio
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
            console_input=True,
        )
        mock_run.assert_called_once()

def test_cli_text_only_flag(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--src", "auto", "--dst", "tr", "--api-key", "test_key", "--text-only", "--mic"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)

    mock_loop_cls = MagicMock()
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run"):
        cli.main()
        mock_loop_cls.assert_called_once()
        assert mock_loop_cls.call_args.kwargs["output_speaker"] is None


def test_cli_speaker_none_falls_back_to_text_only(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--api-key", "test_key", "--mic"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: None)

    mock_loop_cls = MagicMock()
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run"):
        cli.main()
        mock_loop_cls.assert_called_once()
        assert mock_loop_cls.call_args.kwargs["output_speaker"] is None
    out = capsys.readouterr().out
    assert "Hoparlör bulunamadı; metin-only moda geçiliyor." in out


def test_cli_mic_none_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--api-key", "test_key", "--mic"])
    monkeypatch.setattr("cli.default_microphone", lambda: None)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Mikrofon bulunamadı" in err


def test_cli_loopback_error_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--api-key", "test_key"])
    def _fail(_dev):
        raise RuntimeError("Loopback cihaz bulunamadı.")
    monkeypatch.setattr("cli.pick_loopback", _fail)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Loopback cihaz bulunamadı" in err
def test_cli_list_langs(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--list-langs"])
    cli.main()
    out = capsys.readouterr().out
    assert "Desteklenen diller:" in out
    assert "en   : İngilizce" in out
    assert "tr   : Türkçe" in out


def test_cli_invalid_languages_exit(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--src", "xyz", "--mic", "--api-key", "key"])
    monkeypatch.setattr("cli.default_microphone", lambda: MagicMock(name="Mic"))
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Geçersiz kaynak dil 'xyz'" in err


def test_cli_no_interactive_flag(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--api-key", "test_key", "--mic", "--no-interactive"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: MagicMock(name="Spk"))

    mock_loop_cls = MagicMock()
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run"):
        cli.main()
        assert mock_loop_cls.call_args.kwargs["console_input"] is False


def test_cli_custom_output_speaker(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--api-key", "test_key", "--mic", "--output", "Headphones"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    fake_speaker = MagicMock(name="Headphones")
    fake_speaker.name = "Headphones"

    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.pick_speaker", lambda name: fake_speaker)

    mock_loop_cls = MagicMock()
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run"):
        cli.main()
        assert mock_loop_cls.call_args.kwargs["output_speaker"] == fake_speaker


def test_cli_handles_exception_group_cancelled(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--api-key", "test_key", "--mic"])
    fake_source = MagicMock(name="FakeMic")
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: MagicMock())
    monkeypatch.setattr("cli.SystemAudioLoop", MagicMock())

    cancelled = asyncio.CancelledError("Kullanıcı çıkışı")
    eg = BaseExceptionGroup("taskgroup", [cancelled])
    with patch("asyncio.run", side_effect=eg):
        cli.main()
    out = capsys.readouterr().out
    assert "Durduruldu." in out
