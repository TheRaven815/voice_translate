from __future__ import annotations

import asyncio
import io
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
        mock_loop_cls.assert_called_once()
        kwargs = mock_loop_cls.call_args.kwargs
        args_called = mock_loop_cls.call_args.args
        assert args_called == ("en", "de", fake_source, "test_key")
        assert kwargs["output_speaker"] == fake_speaker
        assert kwargs["model"] == "custom-model"
        assert kwargs["console_input"] is True
        mock_run.assert_called_once()

def test_cli_uses_default_languages_from_config(monkeypatch):
    from config import Settings
    monkeypatch.setattr("cli.load_config", lambda: Settings(src_lang="Fransızca", dst_lang="Almanca"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--api-key", "test_key", "--text-only", "--mic"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    mock_loop_cls = MagicMock()
    monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)

    with patch("asyncio.run"):
        cli.main()
        mock_loop_cls.assert_called_once()
        args_called = mock_loop_cls.call_args.args
        assert args_called[0] == "fr"
        assert args_called[1] == "de"

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
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Mikrofon bulunamadı" in err

def test_cli_loopback_error_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli.py", "--api-key", "test_key"])
    def _fail(_dev):
        raise RuntimeError("Loopback cihaz bulunamadı.")
    monkeypatch.setattr("cli.pick_loopback", _fail)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Loopback cihaz bulunamadı" in err
    monkeypatch.setattr(sys, "argv", ["cli.py", "--list-langs"])
    cli.main()
    out = capsys.readouterr().out
    assert "Desteklenen diller:" in out
    assert "en   : İngilizce" in out
    assert "tr   : Türkçe" in out


def test_cli_list_langs_survives_cp1252_stdout(monkeypatch):
    buf = io.BytesIO()
    stream = io.TextIOWrapper(buf, encoding="cp1252", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "argv", ["cli.py", "--list-langs"])
    assert cli.main() == 0
    stream.flush()
    text = buf.getvalue().decode("utf-8")
    assert "Desteklenen diller:" in text
    assert "algılama" in text
    assert "Türkçe" in text


def test_cli_json_mode(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli.py", "--src", "en", "--dst", "tr", "--api-key", "test_key", "--mic", "--json"],
    )
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: None)

    captured_on_text = []
    def mock_init(*args, **kwargs):
        captured_on_text.append(kwargs.get("on_text"))
        return MagicMock()

    monkeypatch.setattr("cli.SystemAudioLoop", mock_init)

    with patch("asyncio.run"):
        cli.main()

    assert len(captured_on_text) == 1
    emit_fn = captured_on_text[0]
    assert emit_fn is not None
    # Emit a tuple
    emit_fn(("heard", "Hello world"))
    out = capsys.readouterr().out
    assert '"type": "heard"' in out
    assert '"text": "Hello world"' in out

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

def test_h18_main_entrypoint_exists_and_routes_helper(monkeypatch):
    """H18: main.py içinde main() fonksiyonu bulunmalı ve CLI helper'a yönlendirebilmeli."""
    import main
    from updater import HELPER_ARG
    assert callable(main.main)
    with patch("main.run_update_helper", return_value=42) as mock_helper:
        code = main.main(["main.py", HELPER_ARG, "123", "target.exe", "sha256"])
        assert code == 42
        mock_helper.assert_called_once_with("123", "target.exe", "sha256")

def test_h22_chinese_language_codes_accepted(monkeypatch):
    """H22: zh-CN ve zh-TW dil kodları (büyük/küçük harf duyarsız) kabul edilmeli."""
    for code in ("zh-CN", "zh-cn", "zh-TW", "zh-tw"):
        monkeypatch.setattr(sys, "argv", ["cli.py", "--src", code, "--dst", code, "--mic", "--api-key", "key"])
        monkeypatch.setattr("cli.default_microphone", lambda: MagicMock(name="Mic"))
        monkeypatch.setattr("cli.default_speaker", lambda: MagicMock(name="Spk"))
        mock_loop_cls = MagicMock()
        monkeypatch.setattr("cli.SystemAudioLoop", mock_loop_cls)
        with patch("asyncio.run"):
            cli.main()
            mock_loop_cls.assert_called_once()
            src_arg, dst_arg = mock_loop_cls.call_args.args[0], mock_loop_cls.call_args.args[1]
            # Canonical BCP-47 kodlarına eşlenmiş olmalı
            expected = "zh-CN" if "cn" in code.lower() else "zh-TW"
            assert src_arg == expected
            assert dst_arg == expected


def test_h23_json_mode_routes_stop_message_to_stderr(monkeypatch, capsys):
    """H23: --json modunda normal duruş mesajı stdout'a değil stderr'e gitmeli (JSON akışı bozulmamalı)."""
    monkeypatch.setattr(sys, "argv", ["cli.py", "--api-key", "test_key", "--mic", "--json"])
    fake_source = MagicMock(name="FakeMic")
    fake_source.name = "FakeMic"
    monkeypatch.setattr("cli.default_microphone", lambda: fake_source)
    monkeypatch.setattr("cli.default_speaker", lambda: MagicMock())
    monkeypatch.setattr("cli.SystemAudioLoop", MagicMock())

    with patch("asyncio.run", side_effect=KeyboardInterrupt()):
        cli.main()
    captured = capsys.readouterr()
    # stdout tamamen JSON veya boş olmalı, "Durduruldu." içermemeli
    assert "Durduruldu." not in captured.out
    assert "Durduruldu." in captured.err

def test_h20_h21_batch_launcher_preserves_exit_code_and_arguments():
    """H20 & H21: ahenk.bat alt işlem hata kodunu kaybetmemeli ve 9'dan fazla argümanı kesmemeli."""
    import subprocess
    import os
    if os.name != "nt":
        pytest.skip("Windows batch test")

    # H20: Hata kodu (örneğin argparse bilinmeyen argümanda 2 döner) sıfırlanmamalı
    res = subprocess.run(
        ["cmd.exe", "/c", "ahenk.bat", "cli", "--nonexistent-flag-for-testing"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 2

    # H21: 9'dan fazla argüman verildiğinde (%2-%9 sınırı) tüm argümanlar aktarılmalı
    args = [f"--test-arg-{i}" for i in range(12)]
    res = subprocess.run(
        ["cmd.exe", "/c", "ahenk.bat", "cli", *args],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 2
    assert "--test-arg-11" in res.stderr
