"""Konsol girişi: python cli.py …"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

if sys.version_info < (3, 11):
    sys.exit("Ahenk Python 3.11 veya üzerini gerektirir (asyncio.TaskGroup).")

from config import load as load_config, resolve_api_key
from devices import default_microphone, default_speaker, list_devices, pick_loopback, pick_speaker
from languages import LANGS, dest_code, source_code
from gui.app import format_user_error
from loop import SystemAudioLoop
from meta import APP_TITLE, __version__
def main(argv: list[str] | None = None) -> int:
    try:
        cfg = load_config()
        default_src = source_code(cfg.src_lang) or "auto"
        default_dst = dest_code(cfg.dst_lang, default="tr")
    except Exception:
        default_src = "auto"
        default_dst = "tr"

    parser = argparse.ArgumentParser(description=f"{APP_TITLE} - PC sistem sesini veya mikrofonu canlı çevir")
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    parser.add_argument("--src", default=default_src, help=f"kaynak dil kodu veya auto (varsayılan: {default_src})")
    parser.add_argument("--dst", default=default_dst, help=f"hedef dil kodu (varsayılan: {default_dst})")
    parser.add_argument("--device", default=None, help="loopback cihaz adı filtresi")
    parser.add_argument("--output", default=None, help="çıkış hoparlör cihaz adı filtresi")
    parser.add_argument("--mic", action="store_true", help="sistem sesi yerine mikrofon")
    parser.add_argument("--text-only", action="store_true", help="hoparlör çıkışı olmadan yalnızca metin çevirisi")
    parser.add_argument("--no-interactive", action="store_true", help="konsoldan metin girişi almadan yalnızca Ctrl+C ile çalış")
    parser.add_argument("--list-devices", action="store_true", help="ses aygıtlarını listele ve çık")
    parser.add_argument("--list-langs", action="store_true", help="desteklenen dilleri ve kodlarını listele ve çık")
    parser.add_argument("--json", action="store_true", help="satır satır JSON akışı üret (betikleme için)")
    parser.add_argument("--log", default=None, metavar="FILE", help="tüm çıktıyı belirtilen log dosyasına kaydet")
    parser.add_argument("--vad", type=float, default=0.0, help="sessizlik kapısı RMS eşiği (örn: 0.01)")
    parser.add_argument("--volume", type=float, default=1.0, help="çeviri ses seviyesi (0.0 - 2.0)")
    parser.add_argument("--api-key", default=None, help="Gemini API anahtarı")
    parser.add_argument("--model", default=None, help="Gemini Live model adı")
    args = parser.parse_args(argv)

    if args.list_devices:
        list_devices()
        return 0

    if args.list_langs:
        print("Desteklenen diller:")
        print("  auto : Otomatik kaynak dil algılama (yalnızca --src)")
        for name, code in LANGS.items():
            print(f"  {code:<5}: {name}")
        return 0

    def info(msg: str) -> None:
        print(msg, file=sys.stderr if args.json else sys.stdout, flush=True)

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        out_dest = sys.stderr if args.json else sys.stdout
        print("GEMINI_API_KEY bulunamadı. Ortama, .env dosyasına ekleyin veya arayüzden kaydedin.", file=out_dest)
        print("Alın: https://aistudio.google.com/apikey", file=out_dest)
        sys.exit(1)
    if args.mic:
        source = default_microphone()
        if source is None:
            print("Hata: Mikrofon bulunamadı.", file=sys.stderr)
            sys.exit(2)
        info(f"Mikrofon yakalanıyor: {source.name}")
    else:
        try:
            source = pick_loopback(args.device)
        except RuntimeError as e:
            print(f"Hata: {e}", file=sys.stderr)
            sys.exit(2)
        if source is None:
            print("Hata: Loopback ses aygıtı bulunamadı.", file=sys.stderr)
            sys.exit(2)
        info(f"Sistem sesi yakalanıyor (loopback): {source.name}")
    code_map = {v.lower(): v for v in LANGS.values()}
    src_raw = args.src.strip()
    if src_raw.lower() in ("auto", ""):
        src = None
    elif src_raw.lower() in code_map:
        src = code_map[src_raw.lower()]
    else:
        print(f"Hata: Geçersiz kaynak dil '{args.src}'. Desteklenen kodlar için --list-langs kullanın.", file=sys.stderr)
        sys.exit(1)
    dst_raw = args.dst.strip()
    if dst_raw.lower() in code_map:
        dst_clean = code_map[dst_raw.lower()]
    else:
        print(f"Hata: Geçersiz hedef dil '{args.dst}'. Desteklenen kodlar için --list-langs kullanın.", file=sys.stderr)
        sys.exit(1)
    if args.text_only:
        speaker = None
        info("Çıkış: Yok (metin-only)")
    else:
        try:
            speaker = pick_speaker(args.output) if args.output else default_speaker()
        except RuntimeError as e:
            print(f"Hata: {e}", file=sys.stderr)
            sys.exit(2)
        if speaker is None:
            info("Hoparlör bulunamadı; metin-only moda geçiliyor.")
        else:
            info(f"Çıkış: {speaker.name}")

    stop_hint = "Ctrl+C" if args.no_interactive else "q + Enter veya Ctrl+C"
    info(f"{args.src} -> {args.dst} çeviri başlıyor. Durdurmak: {stop_hint}")

    log_file = open(args.log, "a", encoding="utf-8") if args.log else None

    loop_holder: list[SystemAudioLoop | None] = [None]

    def cli_emit(msg) -> None:
        if args.json:
            payload = None
            if isinstance(msg, tuple) and len(msg) > 0:
                kind = msg[0]
                if kind in ("heard", "trans"):
                    payload = {"type": kind, "text": msg[1], "time": round(time.time(), 3)}
                elif kind in ("heard_end", "trans_end"):
                    payload = {"type": kind, "time": round(time.time(), 3)}
                elif kind == "latency":
                    payload = {"type": "latency", "ms": msg[1], "time": round(time.time(), 3)}
                elif kind == "detected_src":
                    payload = {"type": "detected_src", "lang": msg[1], "time": round(time.time(), 3)}
            elif isinstance(msg, str):
                payload = {"type": "log", "message": msg, "time": round(time.time(), 3)}
            if payload is not None:
                raw = json.dumps(payload, ensure_ascii=False)
                print(raw, flush=True)
                if log_file:
                    log_file.write(raw + "\n")
                    log_file.flush()
        else:
            curr = loop_holder[0]
            if curr is not None:
                curr._console_emit(msg)
            if log_file:
                if isinstance(msg, tuple) and len(msg) > 1:
                    log_file.write(f"[{msg[0]}] {msg[1]}\n")
                elif isinstance(msg, str):
                    log_file.write(msg)
                log_file.flush()

    loop = SystemAudioLoop(
        src,
        dst_clean,
        source,
        api_key,
        output_speaker=speaker,
        model=args.model,
        console_input=not args.no_interactive,
        on_text=cli_emit,
        vad_threshold=args.vad,
        volume=args.volume,
    )
    loop_holder[0] = loop
    try:
        asyncio.run(loop.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        info("\nDurduruldu.")
    except BaseException as e:
        root: BaseException = e
        while hasattr(root, "exceptions") and getattr(root, "exceptions"):
            root = getattr(root, "exceptions")[0]
        if isinstance(root, (KeyboardInterrupt, asyncio.CancelledError)):
            info("\nDurduruldu.")
        else:
            print(f"\nHata: {format_user_error(root)}", file=sys.stderr)
            return 1
    finally:
        if log_file:
            log_file.close()
    return 0
if __name__ == "__main__":
    sys.exit(main())
