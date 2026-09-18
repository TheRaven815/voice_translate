"""Ahenk masaüstü arayüzü.

Kullanım:
    python main.py
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("Ahenk Python 3.11 veya üzerini gerektirir (asyncio.TaskGroup).")

from updater import HELPER_ARG, cleanup_previous_update, run_update_helper


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == HELPER_ARG:
        sys.exit(run_update_helper(*sys.argv[2:]))
    from gui.app import App

    app = App()
    app.after_idle(cleanup_previous_update)
    app.mainloop()
