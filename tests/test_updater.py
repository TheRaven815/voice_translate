from __future__ import annotations

import hashlib
import json
from pathlib import Path

import updater


class Response:
    def __init__(self, data: bytes, url: str = updater.LATEST_RELEASE_API):
        self._data = data
        self._url = url
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._data) - self._offset
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._url


def test_newer_release_requires_expected_executable_and_digest(monkeypatch):
    digest = "a" * 64
    payload = {
        "tag_name": "v0.6.0",
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/TheRaven815/voice_translate/releases/tag/v0.6.0",
        "assets": [
            {
                "name": "Ahenk.exe",
                "state": "uploaded",
                "size": 123,
                "digest": f"sha256:{digest}",
                "browser_download_url": "https://github.com/TheRaven815/voice_translate/releases/download/v0.6.0/Ahenk.exe",
            }
        ],
    }
    monkeypatch.setattr(updater, "_request", lambda _url: Response(json.dumps(payload).encode()))

    info = updater.check_for_update("0.5.0")

    assert info == updater.UpdateInfo(
        version="0.6.0",
        download_url=payload["assets"][0]["browser_download_url"],
        size=123,
        sha256=digest,
    )



def test_can_self_update_accepts_renamed_gui_exe(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    exe = dist / "Ceviri.exe"
    exe.write_bytes(b"gui")
    meipass = tmp_path / "extract" / "_MEI123"
    meipass.mkdir(parents=True)
    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater.can_self_update()


def test_can_self_update_rejects_cli_exe(tmp_path, monkeypatch):
    exe = tmp_path / "Ahenk-cli.exe"
    exe.write_bytes(b"cli")
    meipass = tmp_path / "extract" / "_MEI123"
    meipass.mkdir(parents=True)
    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert not updater.can_self_update()


def test_download_update_reports_progress(tmp_path, monkeypatch):
    data = b"abcdefghij"
    digest = hashlib.sha256(data).hexdigest()
    url = "https://github.com/TheRaven815/voice_translate/releases/download/v0.6.2/Ahenk.exe"
    info = updater.UpdateInfo(version="0.6.2", download_url=url, size=len(data), sha256=digest)
    target = tmp_path / "Ceviri.exe"
    target.write_bytes(b"old")
    monkeypatch.setattr(updater, "_current_executable", lambda: target)
    monkeypatch.setattr(updater, "_request", lambda _url, timeout=30: Response(data, url=url))
    seen: list[tuple[int, int]] = []
    staged = updater.download_update(info, on_progress=lambda got, total: seen.append((got, total)))
    assert seen[0] == (0, 10)
    assert seen[-1] == (10, 10)
    assert staged.name == ".Ceviri.update-0-6-2.exe"
    assert staged.read_bytes() == data


def test_update_helper_replaces_executable_only_after_startup_handshake(tmp_path, monkeypatch):
    target = tmp_path / "Ahenk.exe"
    source = tmp_path / ".Ahenk.update-0-6-0.exe"
    target.write_bytes(b"old executable")
    source.write_bytes(b"new executable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    monkeypatch.setattr(updater.sys, "executable", str(source))
    monkeypatch.setattr(updater, "_wait_for_process", lambda _pid: None)
    monkeypatch.setattr(updater, "_start_target", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(updater, "_wait_until_started", lambda _process, ready: ready.touch() or True)

    assert updater.run_update_helper("123", str(target), digest) == 0
    assert target.read_bytes() == b"new executable"
    assert not Path(f"{target}.old").exists()


def test_update_helper_replaces_renamed_executable(tmp_path, monkeypatch):
    target = tmp_path / "Ceviri.exe"
    source = tmp_path / ".Ceviri.update-0-6-2.exe"
    target.write_bytes(b"old executable")
    source.write_bytes(b"new executable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()

    monkeypatch.setattr(updater.sys, "executable", str(source))
    monkeypatch.setattr(updater, "_wait_for_process", lambda _pid: None)
    monkeypatch.setattr(updater, "_start_target", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(updater, "_wait_until_started", lambda _process, ready: ready.touch() or True)

    assert updater.run_update_helper("123", str(target), digest) == 0
    assert target.read_bytes() == b"new executable"
    assert target.name == "Ceviri.exe"


def test_update_helper_rolls_back_when_new_executable_does_not_start(tmp_path, monkeypatch):
    target = tmp_path / "Ahenk.exe"
    source = tmp_path / ".Ahenk.update-0-6-0.exe"
    target.write_bytes(b"old executable")
    source.write_bytes(b"broken executable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    starts = []

    monkeypatch.setattr(updater.sys, "executable", str(source))
    monkeypatch.setattr(updater, "_wait_for_process", lambda _pid: None)
    monkeypatch.setattr(updater, "_start_target", lambda *args, **kwargs: starts.append((args, kwargs)) or object())
    monkeypatch.setattr(updater, "_wait_until_started", lambda _process, _ready: False)

    assert updater.run_update_helper("123", str(target), digest) == 1
    assert target.read_bytes() == b"old executable"
    assert len(starts) == 2
    assert "geri yüklendi" in starts[-1][1]["error"]

def test_update_helper_does_not_delete_target_if_backup_is_missing_on_failed_start(tmp_path, monkeypatch):
    target = tmp_path / "Ahenk.exe"
    source = tmp_path / ".Ahenk.update-0-6-0.exe"
    target.write_bytes(b"target executable")
    source.write_bytes(b"broken executable")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    starts = []

    monkeypatch.setattr(updater.sys, "executable", str(source))
    monkeypatch.setattr(updater, "_wait_for_process", lambda _pid: None)
    monkeypatch.setattr(updater, "_start_target", lambda *args, **kwargs: starts.append((args, kwargs)) or object())
    monkeypatch.setattr(updater, "_wait_until_started", lambda _process, _ready: False)

    # Simulate missing backup file by ensuring no .old file exists right before rollback check
    backup = target.with_suffix(target.suffix + ".old")
    orig_replace = updater.os.replace

    def fake_replace(src, dst):
        orig_replace(src, dst)
        if Path(dst) == backup:
            backup.unlink(missing_ok=True)

    monkeypatch.setattr(updater.os, "replace", fake_replace)

    assert updater.run_update_helper("123", str(target), digest) == 1
    # Target must not have been deleted!
    assert target.exists()
    assert "korundu" in starts[-1][1]["error"]


def test_cleanup_previous_update_touches_ready_without_deleting_backup_or_ready(tmp_path, monkeypatch):
    target = tmp_path / "Ahenk.exe"
    target.write_bytes(b"target binary")
    backup = target.with_suffix(target.suffix + ".old")
    backup.write_bytes(b"old binary")
    ready = target.with_name(f".{target.stem}.update-ready-test")
    new_file = target.with_suffix(target.suffix + ".new")
    new_file.write_bytes(b"new leftover")

    monkeypatch.setattr(updater, "can_self_update", lambda: True)
    monkeypatch.setattr(updater.sys, "executable", str(target))
    monkeypatch.setenv(updater._READY_ENV, str(ready))

    deleted_paths = []
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)

    orig_unlink = Path.unlink

    def spy_unlink(self, missing_ok=False):
        deleted_paths.append(self)
        return orig_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", spy_unlink)

    updater.cleanup_previous_update()

    # ready file should have been touched
    assert ready.exists()
    # Let any background cleanup finish
    import time
    time.sleep(0.1)

    # backup (.old) and ready files must NOT be deleted by cleanup_previous_update
    assert backup.exists()
    assert ready.exists()
    assert backup not in deleted_paths
    assert ready not in deleted_paths
