"""Ahenk masaüstü arayüzü.

Kullanım:
    python main.py
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("Ahenk Python 3.11 veya üzerini gerektirir (asyncio.TaskGroup).")

from gui.app import App

if __name__ == "__main__":
    App().mainloop()
