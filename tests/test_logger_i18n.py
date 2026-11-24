"""logger.py ve i18n.py birim testleri."""

from __future__ import annotations

from i18n import get_ui_lang, set_ui_lang, t
from logger import append_history, clear_history, get_logger, load_recent_history, log_exception, setup_logging


def test_i18n_translation_and_language_switch():
    set_ui_lang("tr")
    assert get_ui_lang() == "tr"
    assert t("start") == "Başlat"
    assert t("stop") == "Durdur"

    set_ui_lang("en")
    assert get_ui_lang() == "en"
    assert t("start") == "Start"
    assert t("stop") == "Stop"

    # Fallback to key if unknown
    assert t("unknown_key_xyz") == "unknown_key_xyz"
    set_ui_lang("tr")


def test_logger_and_history_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("logger.config_dir", lambda: tmp_path)
    logger = setup_logging(force=True)
    assert logger is not None
    assert get_logger() is logger

    # Log an exception
    try:
        raise ValueError("test error")
    except ValueError as e:
        log_exception(e, "context_test")

    log_file = tmp_path / "logs" / "ahenk.log"
    assert log_file.is_file()
    assert "test error" in log_file.read_text(encoding="utf-8")

    # Append history
    append_history("Hello world", "Merhaba dünya", src="en", dst="tr")
    hist = load_recent_history()
    assert len(hist) == 1
    assert hist[0]["heard"] == "Hello world"
    assert hist[0]["trans"] == "Merhaba dünya"

    # G01: Konuşma geçmişi temizleme ve döndürme
    assert clear_history() is True
    assert load_recent_history() == []

    # 60 kayıt ekleyip son 10 kaydı isteme (limit kontrolü)
    for i in range(60):
        append_history(f"H_{i}", f"T_{i}")
    recent = load_recent_history(limit=10)
    assert len(recent) == 10
    assert recent[-1]["heard"] == "H_59"
    assert recent[0]["heard"] == "H_50"

    clear_history()
    assert load_recent_history() == []


def test_history_reads_rotated_entries_and_skips_invalid_records(tmp_path, monkeypatch):
    monkeypatch.setattr("logger.config_dir", lambda: tmp_path)
    append_history("Old source", "Old translation", timestamp=1.0)
    path = tmp_path / "history.jsonl"
    path.rename(tmp_path / "history.jsonl.1")
    path.write_text('null\n{"unrelated": true}\n', encoding="utf-8")
    append_history("", "New translation", timestamp=2.0)

    assert [record["trans"] for record in load_recent_history(10)] == ["Old translation", "New translation"]
    assert [record["trans"] for record in load_recent_history(1)] == ["New translation"]
    assert load_recent_history(0) == []
    assert clear_history()
    assert load_recent_history() == []


def test_history_multichunk_newline_boundary_and_corrupt_tail(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr("logger.config_dir", lambda: tmp_path)
    path = tmp_path / "history.jsonl"

    def _rec(idx: int, heard: str, trans: str) -> bytes:
        return (
            json.dumps(
                {
                    "timestamp": f"2026-01-01T00:00:{idx % 60:02d}",
                    "src": "en",
                    "dst": "tr",
                    "heard": heard,
                    "trans": trans,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )

    prefix_lines = [_rec(i, f"PreH_{i}", f"PreT_{i}") for i in range(10)]
    prefix_no_nl = b"".join(prefix_lines)[:-1]  # Son '\n' hariç; '\n' tam 8192 bayt sınırına düşer

    tail_valid = [_rec(k, f"TailH_{k}", f"TailT_{k}") for k in range(5)]
    corrupt_tail = b'not-json\nnull\n{"heard": "", "trans": "   "}\n'
    rest = b"".join(tail_valid) + corrupt_tail

    # Durum 1: İlk parça sınırı (file_size - 8192) tam '\n' karakterinin üstüne düşsün (8191 bayt rest+pad)
    base_pad = _rec(99, "B", "B")
    pad_len = 8191 - len(rest) - len(base_pad)
    assert pad_len > 0
    pad_line = _rec(99, "B" + ("a" * pad_len), "B")
    assert len(b"\n" + pad_line + rest) == 8192

    path.write_bytes(prefix_no_nl + b"\n" + pad_line + rest)
    loaded = load_recent_history(limit=8)
    assert len(loaded) == 8
    assert [r["trans"] for r in loaded] == [
        "PreT_8",
        "PreT_9",
        "B",
        "TailT_0",
        "TailT_1",
        "TailT_2",
        "TailT_3",
        "TailT_4",
    ]

    # Durum 2: İlk parça sınırı '\n' hemen sonrasına (yeni satırın ilk baytına) düşsün (8192 bayt pad+rest)
    pad_len_exact = 8192 - len(rest) - len(base_pad)
    pad_line_exact = _rec(99, "B" + ("a" * pad_len_exact), "B")
    assert len(pad_line_exact + rest) == 8192

    path.write_bytes(b"".join(prefix_lines) + pad_line_exact + rest)
    loaded_exact = load_recent_history(limit=8)
    assert [r["trans"] for r in loaded_exact] == [r["trans"] for r in loaded]


def test_history_invalid_timestamp_and_concurrent_access(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr("logger.config_dir", lambda: tmp_path)
    append_history("Bad negative ts", "Geçersiz negatif", timestamp=-999999999999.0)
    append_history("Bad nan ts", "Geçersiz NaN", timestamp=float("nan"))
    loaded = load_recent_history(limit=10)
    assert [r["trans"] for r in loaded] == ["Geçersiz negatif", "Geçersiz NaN"]

    errors: list[BaseException] = []

    def writer(tid: int) -> None:
        try:
            for i in range(15):
                append_history(f"src-{tid}-{i}", f"dst-{tid}-{i}", src="en", dst="tr")
        except BaseException as exc:
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(15):
                res = load_recent_history(limit=20)
                assert all(isinstance(r, dict) for r in res)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)] + [
        threading.Thread(target=reader) for _ in range(2)
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert errors == []
    assert len(load_recent_history(limit=100)) == 2 + 4 * 15
