"""Canlı çeviri masaüstü arayüzü.

Kullanım:
    python gui.py
    python -m voice_translate
"""

from voice_translate.gui.app import App

__all__ = ["App"]

if __name__ == "__main__":
    App().mainloop()
