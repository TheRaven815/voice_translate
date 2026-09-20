"""GitHub Releases tabanlı güvenli Ahenk güncelleyicisi."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from meta import __version__

REPOSITORY = "TheRaven815/voice_translate"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_NAME = "Ahenk.exe"
CHECKSUM_NAME = f"{ASSET_NAME}.sha256"
HELPER_ARG = "--ahenk-apply-update"
_CLEANUP_ENV = "AHENK_UPDATE_CLEANUP"
_READY_ENV = "AHENK_UPDATE_READY"
_ERROR_ENV = "AHENK_UPDATE_ERROR"
_MAX_METADATA_BYTES = 2 * 1024 * 1024
_MAX_ASSET_BYTES = 1024 * 1024 * 1024
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
}
_VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UpdateError(RuntimeError):
    """Kullanıcıya gösterilebilecek güncelleme hatası."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    download_url: str
    size: int
    sha256: str


def _is_gui_executable(path: Path) -> bool:
    """GUI onefile. CLI ve .exe olmayan hedefler güncellenmez."""
    name = path.name.lower()
    return path.suffix.lower() == ".exe" and not name.endswith("-cli.exe")


def can_self_update() -> bool:
    """Yalnız Windows PyInstaller onefile GUI dağıtımı kendi dosyasını güncelleyebilir.

    Yerel exe adı Ahenk.exe olmak zorunda değil; GitHub varlığı yine Ahenk.exe'dir.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return False
    executable = Path(sys.executable)
    if not _is_gui_executable(executable):
        return False
    executable_dir = executable.resolve().parent
    bundle_dir = Path(sys._MEIPASS).resolve()
    return bundle_dir.parent != executable_dir


def _version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        raise UpdateError(f"Geçersiz sürüm: {value!r}")
    return tuple(map(int, match.groups()))


def _request(url: str, *, timeout: float = 12):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Ahenk/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 404 and url == LATEST_RELEASE_API:
            raise UpdateError(
                "GitHub'da yayımlanmış sürüm bulunamadı. Depo public olmalı ve en az bir Release yayımlanmalı."
            ) from exc
        raise UpdateError(f"GitHub güncelleme servisi HTTP {exc.code} döndürdü.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"GitHub güncelleme servisine bağlanılamadı: {exc}") from exc


def _read_limited(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("GitHub yanıtı izin verilen boyutu aştı.")
    return data


def _validate_download_url(url: str, *, exact_asset: str) -> None:
    parsed = urlparse(url)
    expected_prefix = f"/{REPOSITORY}/releases/download/"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or not parsed.path.startswith(expected_prefix)
        or not parsed.path.endswith(f"/{exact_asset}")
    ):
        raise UpdateError("GitHub sürüm dosyası adresi doğrulanamadı.")


def _asset_digest(assets: list[dict]) -> str:
    executable = next(
        (item for item in assets if isinstance(item, dict) and item.get("name") == ASSET_NAME),
        None,
    )
    if executable is None:
        raise UpdateError(f"GitHub Release içinde {ASSET_NAME} bulunamadı.")

    digest = str(executable.get("digest") or "").lower()
    if digest.startswith("sha256:") and _SHA256_RE.fullmatch(digest[7:]):
        return digest[7:]

    checksum = next(
        (item for item in assets if isinstance(item, dict) and item.get("name") == CHECKSUM_NAME),
        None,
    )
    if checksum is None:
        raise UpdateError(f"{ASSET_NAME} için SHA-256 özeti bulunamadı.")
    checksum_url = str(checksum.get("browser_download_url") or "")
    _validate_download_url(checksum_url, exact_asset=CHECKSUM_NAME)
    try:
        with _request(checksum_url) as response:
            final_host = urlparse(response.geturl()).hostname
            if final_host not in _ALLOWED_DOWNLOAD_HOSTS:
                raise UpdateError("SHA-256 dosyası güvenilmeyen bir adrese yönlendirildi.")
            line = _read_limited(response, 512).decode("ascii", errors="strict").strip().lower()
    except UnicodeDecodeError as exc:
        raise UpdateError("SHA-256 dosyasının biçimi geçersiz.") from exc
    match = re.fullmatch(r"([0-9a-f]{64})\s+\*?ahenk\.exe", line)
    if not match:
        raise UpdateError("SHA-256 dosyasının biçimi geçersiz.")
    return match.group(1)


def check_for_update(current_version: str = __version__) -> UpdateInfo | None:
    """Son kararlı GitHub Release sürümünü denetler."""
    try:
        with _request(LATEST_RELEASE_API) as response:
            payload = json.loads(_read_limited(response, _MAX_METADATA_BYTES))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise UpdateError("GitHub sürüm bilgisi okunamadı.") from exc

    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise UpdateError("GitHub son sürüm yanıtı geçersiz.")
    tag = str(payload.get("tag_name") or "")
    latest = _version(tag)
    if latest <= _version(current_version):
        return None

    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub sürüm dosyaları okunamadı.")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == ASSET_NAME), None)
    if asset is None or asset.get("state") != "uploaded":
        raise UpdateError(f"GitHub Release içinde hazır {ASSET_NAME} bulunamadı.")

    url = str(asset.get("browser_download_url") or "")
    _validate_download_url(url, exact_asset=ASSET_NAME)
    try:
        size = int(asset.get("size"))
    except (TypeError, ValueError) as exc:
        raise UpdateError("Güncelleme dosyasının boyutu geçersiz.") from exc
    if not 0 < size <= _MAX_ASSET_BYTES:
        raise UpdateError("Güncelleme dosyasının boyutu güvenli sınırın dışında.")

    return UpdateInfo(
        version=".".join(map(str, latest)),
        download_url=url,
        size=size,
        sha256=_asset_digest(assets),
    )


def _current_executable() -> Path:
    if not can_self_update():
        raise UpdateError("Otomatik güncelleme yalnız Windows onefile dağıtımında kullanılabilir.")
    return Path(sys.executable).resolve()


def download_update(
    info: UpdateInfo,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Güncellemeyi çalışmakta olan exe ile aynı diske indirip doğrular."""
    target = _current_executable()
    safe_version = info.version.replace(".", "-")
    staged = target.with_name(f".{target.stem}.update-{safe_version}.exe")
    partial = staged.with_suffix(".part")
    for path in (partial, staged):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise UpdateError(f"Eski güncelleme dosyası temizlenemedi: {exc}") from exc

    digest = hashlib.sha256()
    downloaded = 0
    if on_progress is not None:
        try:
            on_progress(0, info.size)
        except Exception:
            pass
    try:
        with _request(info.download_url, timeout=30) as response, partial.open("xb") as output:
            final_host = urlparse(response.geturl()).hostname
            if final_host not in _ALLOWED_DOWNLOAD_HOSTS:
                raise UpdateError("Güncelleme güvenilmeyen bir adrese yönlendirildi.")
            while chunk := response.read(1024 * 1024):
                downloaded += len(chunk)
                if downloaded > info.size or downloaded > _MAX_ASSET_BYTES:
                    raise UpdateError("İndirilen güncellemenin boyutu beklenenden büyük.")
                output.write(chunk)
                digest.update(chunk)
                if on_progress is not None:
                    try:
                        on_progress(downloaded, info.size)
                    except Exception:
                        pass
            output.flush()
            os.fsync(output.fileno())
        if downloaded != info.size:
            raise UpdateError("İndirilen güncellemenin boyutu eksik.")
        if digest.hexdigest() != info.sha256:
            raise UpdateError("Güncellemenin SHA-256 doğrulaması başarısız.")
        os.replace(partial, staged)
        return staged
    except UpdateError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Güncelleme indirilemedi: {exc}") from exc
    finally:
        try:
            partial.unlink()
        except OSError:
            pass


def launch_update_helper(staged: Path, info: UpdateInfo) -> None:
    """Yeni exe'yi yardımcı modda başlatır; çağıran uygulama ardından kapanmalıdır."""
    target = _current_executable()
    try:
        subprocess.Popen(
            [str(staged), HELPER_ARG, str(os.getpid()), str(target), info.sha256],
            cwd=str(target.parent),
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        raise UpdateError(f"Güncelleme işlemi başlatılamadı: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _wait_for_process(pid: int, timeout_seconds: int = 60) -> None:
    if os.name != "nt":
        raise UpdateError("Güncelleme yardımcısı yalnız Windows üzerinde çalışır.")
    from ctypes import wintypes

    synchronize = 0x00100000
    open_process = ctypes.windll.kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    close_handle = ctypes.windll.kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    wait = ctypes.windll.kernel32.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    handle = open_process(synchronize, False, pid)
    if not handle:
        return
    try:
        result = wait(handle, timeout_seconds * 1000)
        if result == 0x00000102:
            raise UpdateError("Çalışan Ahenk zamanında kapanmadı.")
        if result == 0xFFFFFFFF:
            raise UpdateError("Çalışan Ahenk işlemi beklenemedi.")
    finally:
        close_handle(handle)


def _start_target(
    target: Path,
    *,
    cleanup: Path | None = None,
    error: str | None = None,
    ready: Path | None = None,
):
    env = os.environ.copy()
    if cleanup is not None:
        env[_CLEANUP_ENV] = str(cleanup)
    if error:
        env[_ERROR_ENV] = error[:1000]
    if ready is not None:
        env[_READY_ENV] = str(ready)
    return subprocess.Popen([str(target)], cwd=str(target.parent), env=env, close_fds=True)


def _wait_until_started(process, ready: Path, timeout_seconds: int = 30) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready.exists():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.1)
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return False


def run_update_helper(pid_text: str, target_text: str, expected_sha256: str) -> int:
    """İndirilen yeni exe içinde çalışır; eski exe'yi atomik olarak değiştirir."""
    source = Path(sys.executable).resolve()
    target = Path(target_text).resolve()
    backup = target.with_suffix(target.suffix + ".old")
    replacement = target.with_suffix(target.suffix + ".new")
    ready = target.with_name(f".{target.stem}.update-ready-{os.urandom(8).hex()}")
    updated = False
    try:
        pid = int(pid_text)
        if (
            not _is_gui_executable(target)
            or source.parent != target.parent
            or source.suffix.lower() != ".exe"
            or not source.name.startswith(f".{target.stem}.update-")
        ):
            raise UpdateError("Güncelleme yardımcısı yolları doğrulanamadı.")
        expected_sha256 = expected_sha256.lower()
        if not _SHA256_RE.fullmatch(expected_sha256) or _sha256(source) != expected_sha256:
            raise UpdateError("Güncelleme yardımcısının SHA-256 doğrulaması başarısız.")

        _wait_for_process(pid)
        shutil.copyfile(source, replacement)
        if _sha256(replacement) != expected_sha256:
            raise UpdateError("Kopyalanan güncellemenin SHA-256 doğrulaması başarısız.")

        backup.unlink(missing_ok=True)
        for attempt in range(30):
            try:
                os.replace(target, backup)
                break
            except OSError:
                if attempt == 29:
                    raise UpdateError("Çalışan uygulama dosyası değiştirilemedi.")
                time.sleep(0.25)
        try:
            os.replace(replacement, target)
        except OSError as exc:
            os.replace(backup, target)
            raise UpdateError("Yeni uygulama dosyası etkinleştirilemedi.") from exc
        updated = True

        process = _start_target(target, cleanup=source, ready=ready)
        if not _wait_until_started(process, ready):
            if backup.exists():
                try:
                    os.replace(backup, target)
                except OSError:
                    target.unlink(missing_ok=True)
                    os.replace(backup, target)
                updated = False
                _start_target(target, cleanup=source, error="Yeni sürüm başlatılamadı; önceki sürüm geri yüklendi.")
            else:
                _start_target(target, cleanup=source, error="Yeni sürüm doğrulanamadı ve geri dönüş yedeği bulunamadı; mevcut dosya korundu.")
            return 1
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        return 0
    except Exception as exc:
        try:
            replacement.unlink(missing_ok=True)
            if backup.exists() and (updated or not target.exists()):
                try:
                    os.replace(backup, target)
                except OSError:
                    target.unlink(missing_ok=True)
                    os.replace(backup, target)
            if target.exists():
                _start_target(target, cleanup=source, error=f"Güncelleme uygulanamadı: {exc}")
        except OSError:
            pass
        return 1
    finally:
        try:
            ready.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_previous_update() -> None:
    """Yardımcı exe kapandıktan sonra yalnız ona ait geçici dosyaları siler."""
    cleanup_text = os.environ.pop(_CLEANUP_ENV, "")
    ready_text = os.environ.pop(_READY_ENV, "")
    if not can_self_update():
        return
    target = Path(sys.executable).resolve()
    candidates: list[Path] = [target.with_suffix(target.suffix + ".new")]
    if ready_text:
        ready = Path(ready_text).resolve()
        if ready.parent == target.parent and ready.name.startswith(f".{target.stem}.update-ready-"):
            try:
                ready.touch()
            except OSError:
                pass
    if cleanup_text:
        cleanup = Path(cleanup_text).resolve()
        if cleanup.parent == target.parent and cleanup.name.startswith(f".{target.stem}.update-"):
            candidates.append(cleanup)

    def remove_files() -> None:
        time.sleep(3)
        for path in candidates:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    threading.Thread(target=remove_files, name="update-cleanup", daemon=True).start()

def consume_update_error() -> str:
    return os.environ.pop(_ERROR_ENV, "")
