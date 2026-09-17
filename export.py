"""Transkript dışa aktarma: TXT, SRT, JSONL."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass


@dataclass
class TranscriptItem:
    timestamp: float
    stream: str  # "heard" veya "trans"
    text: str
    duration_s: float = 3.0


def format_srt_time(seconds: float) -> str:
    total_seconds = int(max(0.0, seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def export_txt(items: list[TranscriptItem]) -> str:
    lines = []
    for item in items:
        dt = datetime.datetime.fromtimestamp(item.timestamp).strftime("%H:%M:%S")
        label = "Duyulan" if item.stream == "heard" else "Çeviri"
        lines.append(f"[{dt}] {label}: {item.text.strip()}")
    return "\n".join(lines)


def export_srt(items: list[TranscriptItem], session_start: float | None = None) -> str:
    trans_items = [it for it in items if it.stream == "trans" and it.text.strip()]
    if not trans_items:
        trans_items = [it for it in items if it.text.strip()]
    if not trans_items:
        return ""
    start_base = session_start if session_start is not None else trans_items[0].timestamp
    blocks = []
    for i, it in enumerate(trans_items, 1):
        rel_start = max(0.0, it.timestamp - start_base)
        rel_end = rel_start + max(1.5, it.duration_s)
        time_str = f"{format_srt_time(rel_start)} --> {format_srt_time(rel_end)}"
        blocks.append(f"{i}\n{time_str}\n{it.text.strip()}\n")
    return "\n".join(blocks)


def export_jsonl(items: list[TranscriptItem]) -> str:
    lines = []
    for it in items:
        row = {
            "timestamp": round(it.timestamp, 3),
            "stream": it.stream,
            "text": it.text.strip(),
        }
        lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines)
