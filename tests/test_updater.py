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
