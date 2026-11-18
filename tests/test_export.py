"""Birim testleri: çift dilli SRT ve WebVTT dışa aktarma (R06)."""

from __future__ import annotations

from export import (
    TranscriptItem,
    export_bilingual_srt,
    export_srt,
    export_vtt,
    format_srt_time,
    format_vtt_time,
)


def test_format_srt_and_vtt_timestamps():
    assert format_srt_time(0.0) == "00:00:00,000"
    assert format_vtt_time(0.0) == "00:00:00.000"
    assert format_srt_time(3661.29) == "01:01:01,290"
    assert format_vtt_time(3661.29) == "01:01:01.290"
    assert format_vtt_time(-2.5) == "00:00:00.000"


def test_export_bilingual_srt_overlap_preceding_and_missing_heard_fallback():
    items = [
        # 1) Temporally overlapping heard + trans
        TranscriptItem(timestamp=100.0, stream="heard", text="Hello everyone", duration_s=2.2),
        TranscriptItem(timestamp=100.8, stream="trans", text="Herkese merhaba", duration_s=4.0),
        # 2) Missing heard -> graceful single-line trans fallback (must not reuse first heard)
        TranscriptItem(timestamp=103.0, stream="trans", text="İkinci cümle yalnız çeviri", duration_s=2.0),
        # 3) Immediately preceding heard (finished 0.6s before trans started)
        TranscriptItem(timestamp=106.0, stream="heard", text="Let us begin", duration_s=1.4),
        TranscriptItem(timestamp=108.0, stream="trans", text="Hadi başlayalım", duration_s=2.5),
    ]
    srt = export_bilingual_srt(items, session_start=100.0)
    blocks = [blk.strip().splitlines() for blk in srt.strip().split("\n\n")]
    assert len(blocks) == 3

    # Cue 1: clamped before Cue 2 (103.0 -> 00:00:02,960), heard on top + trans below
    assert blocks[0] == [
        "1",
        "00:00:00,800 --> 00:00:02,960",
        "Hello everyone",
        "Herkese merhaba",
    ]
    # Cue 2: no matching heard -> single line trans
    assert blocks[1] == [
        "2",
        "00:00:03,000 --> 00:00:05,000",
        "İkinci cümle yalnız çeviri",
    ]
    # Cue 3: paired with preceding heard
    assert blocks[2] == [
        "3",
        "00:00:08,000 --> 00:00:10,500",
        "Let us begin",
        "Hadi başlayalım",
    ]


def test_export_vtt_single_and_bilingual_with_non_overlapping_cues():
    assert export_vtt([]) == ""
    assert export_bilingual_srt([]) == ""

    items = [
        TranscriptItem(timestamp=50.0, stream="heard", text="Good morning", duration_s=2.0),
        TranscriptItem(timestamp=50.0, stream="trans", text="Günaydın", duration_s=5.0),
        TranscriptItem(timestamp=52.0, stream="heard", text="Welcome back", duration_s=2.0),
        TranscriptItem(timestamp=52.0, stream="trans", text="Tekrar hoş geldiniz", duration_s=2.5),
    ]

    vtt_single = export_vtt(items, session_start=50.0, bilingual=False)
    assert vtt_single.startswith("WEBVTT\n\n")
    single_lines = vtt_single.splitlines()
    assert "00:00:00.000 --> 00:00:01.960" in single_lines
    assert "00:00:02.000 --> 00:00:04.500" in single_lines
    assert "Good morning" not in vtt_single
    assert "Günaydın" in vtt_single

    vtt_bi = export_vtt(items, session_start=50.0, bilingual=True)
    assert vtt_bi.startswith("WEBVTT\n\n")
    assert "Good morning\nGünaydın" in vtt_bi
    assert "Welcome back\nTekrar hoş geldiniz" in vtt_bi
    # Standard SRT must remain single-stream
    srt_single = export_srt(items, session_start=50.0)
    assert "Good morning" not in srt_single
    assert "Günaydın" in srt_single
