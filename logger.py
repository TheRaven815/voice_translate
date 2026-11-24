"""Ahenk dosya günlüğü ve yerel oturum geçmişi."""

from __future__ import annotations

import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

from config import config_dir

_logger: logging.Logger | None = None
_HISTORY_LOCK = threading.Lock()


def setup_logging(force: bool = False) -> logging.Logger:
    global _logger
    if _logger is not None and not force:
        return _logger

    log_dir = config_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ahenk.log"
        handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
        logger = logging.getLogger("ahenk")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        _logger = logger
    except Exception:
        _logger = logging.getLogger("ahenk")
    return _logger


def get_logger() -> logging.Logger:
    if _logger is None:
        return setup_logging()
    return _logger


def log_exception(e: BaseException, context: str = "") -> None:
    logger = get_logger()
    msg = f"{context}: {e}" if context else str(e)
    logger.exception(msg)


def append_history(
    heard: str, trans: str, src: str = "auto", dst: str = "tr", *, timestamp: float | None = None,
) -> None:
    heard_clean = str(heard or "").strip()
    trans_clean = str(trans or "").strip()
    if not (heard_clean or trans_clean):
        return
    src_code = str(src or "auto")
    dst_code = str(dst or "tr")
    if timestamp is None:
        at = datetime.datetime.now()
    else:
        try:
            at = datetime.datetime.fromtimestamp(timestamp)
        except (OSError, OverflowError, ValueError, TypeError):
            at = datetime.datetime.now()
    with _HISTORY_LOCK:
        history_file = config_dir() / "history.jsonl"
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            if history_file.is_file() and history_file.stat().st_size > 2_000_000:
                bak = history_file.with_name("history.jsonl.1")
                try:
                    history_file.replace(bak)
                except OSError:
                    pass
            record = {
                "timestamp": at.isoformat(),
                "src": src_code,
                "dst": dst_code,
                "heard": heard_clean,
                "trans": trans_clean,
            }
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
        except Exception as exc:
            try:
                get_logger().warning("Konuşma geçmişi yazılamadı: %s", exc)
            except Exception:
                pass


def load_recent_history(limit: int = 50) -> list[dict]:
    if limit <= 0:
        return []
    with _HISTORY_LOCK:
        history_file = config_dir() / "history.jsonl"
        recent = _read_history_tail(history_file, limit)
        if len(recent) < limit:
            older = _read_history_tail(history_file.with_name("history.jsonl.1"), limit - len(recent))
            return older + recent
        return recent


def _parse_history_line(raw_line: bytes) -> dict | None:
    line = raw_line.decode("utf-8", errors="replace").strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    for key in ("heard", "trans"):
        if not isinstance(record.get(key), str):
            record[key] = ""
    if record["heard"].strip() or record["trans"].strip():
        return record
    return None


def _read_history_tail(history_file: Path, limit: int) -> list[dict]:
    if not history_file.is_file() or limit <= 0:
        return []
    try:
        file_size = history_file.stat().st_size
        if file_size == 0:
            return []
        chunk_size = 8192
        records: list[dict] = []
        with open(history_file, "rb") as f:
            pos = file_size
            carry = b""
            while pos > 0 and len(records) < limit:
                read_size = min(pos, chunk_size)
                pos -= read_size
                f.seek(pos)
                buf = f.read(read_size) + carry
                raw_parts = buf.split(b"\n")
                if pos > 0:
                    carry = raw_parts[0]
                    complete = raw_parts[1:]
                else:
                    carry = b""
                    complete = raw_parts
                for raw_line in reversed(complete):
                    record = _parse_history_line(raw_line)
                    if record is not None:
                        records.append(record)
                        if len(records) >= limit:
                            break
        records.reverse()
        return records
    except Exception:
        return []


def clear_history() -> bool:
    """Konuşma geçmişi dosyasını güvenli biçimde siler/temizler."""
    with _HISTORY_LOCK:
        history_file = config_dir() / "history.jsonl"
        try:
            if history_file.is_file():
                history_file.unlink()
            bak = history_file.with_name("history.jsonl.1")
            if bak.is_file():
                bak.unlink()
            return True
        except Exception:
            return False
