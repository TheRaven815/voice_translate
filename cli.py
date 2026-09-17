"""Konsol girişi: python cli.py …"""

from __future__ import annotations

import argparse
import asyncio
import sys

if sys.version_info < (3, 11):
    sys.exit("Ahenk Python 3.11 veya üzerini gerektirir (asyncio.TaskGroup).")

from config import resolve_api_key
from devices import default_microphone, default_speaker, list_devices, pick_loopback, pick_speaker
from languages import LANGS
from gui.app import format_user_error
from loop import SystemAudioLoop
from meta import APP_TITLE, __version__
def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_TITLE} - PC sistem sesini veya mikrofonu canlı çevir")
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {__version__}")
    parser.add_argument("--src", default="auto", help="kaynak dil kodu veya auto (varsayılan: auto)")
    parser.add_argument("--dst", default="tr", help="hedef dil kodu (varsayılan: tr)")
    parser.add_argument("--device", default=None, help="loopback cihaz adı filtresi")
    parser.add_argument("--output", default=None, help="çıkış hoparlör cihaz adı filtresi")
    parser.add_argument("--mic", action="store_true", help="sistem sesi yerine mikrofon")
    parser.add_argument("--text-only", action="store_true", help="hoparlör çıkışı olmadan yalnızca metin çevirisi")
    parser.add_argument("--no-interactive", action="store_true", help="konsoldan metin girişi almadan yalnızca Ctrl+C ile çalış")
    parser.add_argument("--list-devices", action="store_true", help="ses aygıtlarını listele ve çık")
    parser.add_argument("--list-langs", action="store_true", help="desteklenen dilleri ve kodlarını listele ve çık")
    parser.add_argument("--api-key", default=None, help="Gemini API anahtarı")
    parser.add_argument("--model", default=None, help="Gemini Live model adı")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    if args.list_langs:
        print("Desteklenen diller:")
        print("  auto : Otomatik kaynak dil algılama (yalnızca --src)")
        for name, code in LANGS.items():
            print(f"  {code:<5}: {name}")
        return

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print("GEMINI_API_KEY bulunamadı. Ortama, .env dosyasına ekleyin veya arayüzden kaydedin.")
        print("Alın: https://aistudio.google.com/apikey")
        sys.exit(1)

    if args.mic:
        source = default_microphone()
        if source is None:
            print("Hata: Mikrofon bulunamadı.", file=sys.stderr)
            sys.exit(1)
        print(f"Mikrofon yakalanıyor: {source.name}")
    else:
        try:
            source = pick_loopback(args.device)
        except RuntimeError as e:
            print(f"Hata: {e}", file=sys.stderr)
            sys.exit(1)
        if source is None:
            print("Hata: Loopback ses aygıtı bulunamadı.", file=sys.stderr)
            sys.exit(1)
        print(f"Sistem sesi yakalanıyor (loopback): {source.name}")
    valid_codes = set(LANGS.values())
    src_clean = args.src.strip().lower()
    if src_clean != "auto" and src_clean not in valid_codes:
        print(f"Hata: Geçersiz kaynak dil '{args.src}'. Desteklenen kodlar için --list-langs kullanın.", file=sys.stderr)
        sys.exit(1)
    dst_clean = args.dst.strip().lower()
    if dst_clean not in valid_codes:
        print(f"Hata: Geçersiz hedef dil '{args.dst}'. Desteklenen kodlar için --list-langs kullanın.", file=sys.stderr)
        sys.exit(1)

    if args.text_only:
        speaker = None
        print("Çıkış: Yok (metin-only)")
    else:
        try:
            speaker = pick_speaker(args.output) if args.output else default_speaker()
        except RuntimeError as e:
            print(f"Hata: {e}", file=sys.stderr)
            sys.exit(1)
        if speaker is None:
            print("Hoparlör bulunamadı; metin-only moda geçiliyor.")
        else:
            print(f"Çıkış: {speaker.name}")

    stop_hint = "Ctrl+C" if args.no_interactive else "q + Enter veya Ctrl+C"
    print(f"{args.src} -> {args.dst} çeviri başlıyor. Durdurmak: {stop_hint}")

    src = None if src_clean in ("auto", "") else src_clean
    loop = SystemAudioLoop(
        src,
        dst_clean,
        source,
        api_key,
        output_speaker=speaker,
        model=args.model,
        console_input=not args.no_interactive,
    )
    try:
        asyncio.run(loop.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nDurduruldu.")
    except BaseException as e:
        root: BaseException = e
        while hasattr(root, "exceptions") and getattr(root, "exceptions"):
            root = getattr(root, "exceptions")[0]
        if isinstance(root, (KeyboardInterrupt, asyncio.CancelledError)):
            print("\nDurduruldu.")
        else:
            print(f"\nHata: {format_user_error(root)}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
