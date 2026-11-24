"""Transkript dışa aktarma: TXT, SRT, çift dilli SRT, WebVTT, JSONL."""

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


def _split_time_ms(seconds: float) -> tuple[int, int, int, int]:
    clamped = max(0.0, float(seconds))
    total_ms = int(round(clamped * 1000))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return hours, minutes, secs, millis


def format_srt_time(seconds: float) -> str:
    hours, minutes, secs, millis = _split_time_ms(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_time(seconds: float) -> str:
    hours, minutes, secs, millis = _split_time_ms(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def export_txt(items: list[TranscriptItem]) -> str:
    from i18n import t

    heard_label = t("heard", "Duyulan")
    trans_label = t("trans", "Çeviri")
    lines = []
    for item in items:
        dt = datetime.datetime.fromtimestamp(item.timestamp).strftime("%H:%M:%S")
        label = heard_label if item.stream == "heard" else trans_label
        lines.append(f"[{dt}] {label}: {item.text.strip()}")
    return "\n".join(lines)


def _pair_heard_for_trans(
    trans_items: list[TranscriptItem],
    heard_items: list[TranscriptItem],
) -> list[str | None]:
    if not trans_items or not heard_items:
        return [None] * len(trans_items)
    used_heard: set[int] = set()
    paired: list[str | None] = []
    for idx, t_it in enumerate(trans_items):
        t_start = t_it.timestamp
        t_end = t_start + max(1.2, t_it.duration_s)
        next_t_start = trans_items[idx + 1].timestamp if idx + 1 < len(trans_items) else None
        prev_t_start = trans_items[idx - 1].timestamp if idx > 0 else None
        candidates: list[tuple[int, float, int]] = []
        for j, h_it in enumerate(heard_items):
            if j in used_heard:
                continue
            h_start = h_it.timestamp
            h_end = h_start + max(1.2, h_it.duration_s)
            if (
                next_t_start is not None
                and next_t_start > t_start
                and h_start > t_start
                and abs(h_start - t_start) > abs(h_start - next_t_start)
            ):
                continue
            if prev_t_start is not None and h_end < prev_t_start:
                continue
            overlaps = h_start <= t_end and h_end >= t_start
            precedes = h_start <= t_start and (t_start - h_end) <= 15.0
            if not (overlaps or precedes):
                continue
            gap = max(0.0, t_start - h_end)
            candidates.append((0 if overlaps else 1, gap, j))
        if candidates:
            candidates.sort()
            best_j = candidates[0][2]
            used_heard.add(best_j)
            paired.append(heard_items[best_j].text.strip())
        else:
            paired.append(None)
    return paired


def _build_subtitle_cues(
    items: list[TranscriptItem],
    session_start: float | None = None,
    *,
    bilingual: bool = False,
) -> list[tuple[float, float, str]]:
    ordered = sorted((it for it in items if it.text.strip()), key=lambda it: it.timestamp)
    trans_items = [it for it in ordered if it.stream == "trans"]
    heard_items = [it for it in ordered if it.stream == "heard"]
    has_trans = bool(trans_items)
    cues_source = trans_items if has_trans else ordered
    if not cues_source:
        return []
    paired_heard = (
        _pair_heard_for_trans(cues_source, heard_items)
        if (bilingual and has_trans and heard_items)
        else [None] * len(cues_source)
    )
    start_base = session_start if session_start is not None else cues_source[0].timestamp
    starts = [max(0, round((it.timestamp - start_base) * 1000)) for it in cues_source]
    # Bir pakette birden fazla cümle gelebilir. Eşit zaman damgalarını
    # sonraki gerçek zaman damgasına kadar, yoksa sırayla göster.
    i = 0
    while i < len(starts):
        j = i + 1
        while j < len(starts) and starts[j] == starts[i]:
            j += 1
        interval = max(1200, round(cues_source[i].duration_s * 1000))
        if j < len(starts):
            interval = min(interval, (starts[j] - starts[i]) // (j - i))
        for k in range(i + 1, j):
            starts[k] = starts[i] + (k - i) * interval
        i = j
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + 1)

    cues: list[tuple[float, float, str]] = []
    for i, it in enumerate(cues_source):
        rel_start = starts[i]
        rel_end = rel_start + max(1200, round(it.duration_s * 1000))
        if i + 1 < len(cues_source):
            next_start = starts[i + 1]
            if rel_end > next_start:
                rel_end = max(rel_start + 1, next_start - 40)
        body = "\n".join(line.strip() for line in it.text.splitlines() if line.strip())
        heard_text = paired_heard[i]
        if heard_text and heard_text != body:
            heard_lines = "\n".join(line.strip() for line in heard_text.splitlines() if line.strip())
            body = f"{heard_lines}\n{body}"
        cues.append((rel_start / 1000, rel_end / 1000, body))
    return cues


def export_srt(items: list[TranscriptItem], session_start: float | None = None) -> str:
    cues = _build_subtitle_cues(items, session_start=session_start, bilingual=False)
    if not cues:
        return ""
    blocks = []
    for i, (rel_start, rel_end, body) in enumerate(cues, 1):
        time_str = f"{format_srt_time(rel_start)} --> {format_srt_time(rel_end)}"
        blocks.append(f"{i}\n{time_str}\n{body}\n")
    return "\n".join(blocks)


def export_bilingual_srt(items: list[TranscriptItem], session_start: float | None = None) -> str:
    cues = _build_subtitle_cues(items, session_start=session_start, bilingual=True)
    if not cues:
        return ""
    blocks = []
    for i, (rel_start, rel_end, body) in enumerate(cues, 1):
        time_str = f"{format_srt_time(rel_start)} --> {format_srt_time(rel_end)}"
        blocks.append(f"{i}\n{time_str}\n{body}\n")
    return "\n".join(blocks)


def export_vtt(
    items: list[TranscriptItem],
    session_start: float | None = None,
    *,
    bilingual: bool = False,
) -> str:
    cues = _build_subtitle_cues(items, session_start=session_start, bilingual=bilingual)
    if not cues:
        return ""
    blocks = []
    for i, (rel_start, rel_end, body) in enumerate(cues, 1):
        time_str = f"{format_vtt_time(rel_start)} --> {format_vtt_time(rel_end)}"
        blocks.append(f"{i}\n{time_str}\n{body}\n")
    return "WEBVTT\n\n" + "\n".join(blocks)


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
