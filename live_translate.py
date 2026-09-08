"""PC sistem sesini Gemini Live Translate ile canlı çevirir.

Kurulum:
    pip install -r requirements.txt

Kullanım:
    python live_translate.py --list-devices
    python live_translate.py
    python live_translate.py --src en --dst tr --device Kulaklık
    python live_translate.py --mic
"""

from voice_translate.cli import main

if __name__ == "__main__":
    main()
