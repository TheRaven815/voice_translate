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
    from single_instance import claim_or_activate

    # pytest App() kurar; kilit yalnızca gerçek masaüstü girişi içindir.
    claimed = claim_or_activate()
    if claimed is None:
        return 0
    lock, slot = claimed
    from gui.app import App

    app = App(activate_slot=slot)
    app.after_idle(cleanup_previous_update)
    try:
        app.mainloop()
    finally:
        slot.clear()
        slot.close()
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
