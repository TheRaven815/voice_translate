"""Ahenk dosya günlüğü ve yerel oturum geçmişi."""

from __future__ import annotations

import datetime
import json
import logging
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
        handler = logging.FileHandler(log_file, encoding="utf-8")
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
        lines = history_file.read_text(encoding="utf-8").splitlines()
        records = []
        for line in lines[-limit:]:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
        return records
    except Exception:
        return []
