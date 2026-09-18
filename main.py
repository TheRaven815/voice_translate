"""Ahenk masaüstü arayüzü.

Kullanım:
    python main.py
"""

import sys

if sys.version_info < (3, 11):
    sys.exit("Ahenk Python 3.11 veya üzerini gerektirir (asyncio.TaskGroup).")

from updater import HELPER_ARG, cleanup_previous_update, run_update_helper


def main(argv: list[str] | None = None) -> int:
    args = sys.argv if argv is None else argv
    if len(args) == 5 and args[1] == HELPER_ARG:
        return run_update_helper(*args[2:])
    from gui.app import App

    app = App()
    app.after_idle(cleanup_previous_update)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
