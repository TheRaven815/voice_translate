"""Konsol girişi: python cli.py …"""

from __future__ import annotations

import argparse
import asyncio
import sys

from config import resolve_api_key
from devices import default_microphone, default_speaker, list_devices, pick_loopback
from loop import SystemAudioLoop


def main() -> None:
    parser = argparse.ArgumentParser(description="PC sistem sesini canlı çevir")
    parser.add_argument("--src", default="auto", help="kaynak dil kodu veya auto (varsayılan: auto)")
    parser.add_argument("--dst", default="tr", help="hedef dil (varsayılan: tr)")
    parser.add_argument("--device", default=None, help="loopback cihaz adı filtresi")
    parser.add_argument("--mic", action="store_true", help="sistem sesi yerine mikrofon")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--model", default=None, help="Gemini Live model adı")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    api_key = resolve_api_key(args.api_key)
    if not api_key:
        print("GEMINI_API_KEY bulunamadı. Ortama, .env dosyasına ekleyin veya arayüzden kaydedin.")
        print("Alın: https://aistudio.google.com/apikey")
        sys.exit(1)

    if args.mic:
        source = default_microphone()
        print(f"Mikrofon yakalanıyor: {source.name}")
    else:
        source = pick_loopback(args.device)
        print(f"Sistem sesi yakalanıyor (loopback): {source.name}")
    print(f"{args.src} -> {args.dst} çeviri başlıyor. Durdurmak: q + Enter veya Ctrl+C")

    speaker = default_speaker()
    print(f"Çıkış: {speaker.name}")
    src = None if args.src.strip().lower() in ("auto", "") else args.src.strip()
    loop = SystemAudioLoop(
        src, args.dst, source, api_key, output_speaker=speaker, model=args.model
    )
    try:
        asyncio.run(loop.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
