"""Ahenk dosya günlüğü ve yerel oturum geçmişi."""

from __future__ import annotations

import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import config_dir

_logger: logging.Logger | None = None


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


def append_history(heard: str, trans: str, src: str = "auto", dst: str = "tr") -> None:
    if not (heard.strip() or trans.strip()):
        return
    history_file = config_dir() / "history.jsonl"
    try:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        if history_file.is_file() and history_file.stat().st_size > 2_000_000:
            bak = history_file.with_name("history.jsonl.1")
            try:
                if bak.is_file():
                    bak.unlink()
                history_file.replace(bak)
            except OSError:
                pass
        record = {
            "timestamp": datetime.datetime.now().isoformat(),
            "src": src,
            "dst": dst,
            "heard": heard.strip(),
            "trans": trans.strip(),
        }
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_recent_history(limit: int = 50) -> list[dict]:
    history_file = config_dir() / "history.jsonl"
    if not history_file.is_file():
        return []
    try:
        file_size = history_file.stat().st_size
        if file_size == 0:
            return []
        chunk_size = 8192
        records: list[dict] = []
        with open(history_file, "rb") as f:
            lines: list[bytes] = []
            pos = file_size
            buf = b""
            while pos > 0 and len(lines) <= limit + 1:
                read_size = min(pos, chunk_size)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                buf = chunk + buf
                lines = [l for l in buf.split(b"\n") if l.strip()]
            if pos > 0 and lines:
                lines = lines[1:]
            for raw_line in lines[-limit:]:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
        return records
    except Exception:
        return []


def clear_history() -> bool:
    """Konuşma geçmişi dosyasını güvenli biçimde siler/temizler."""
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
