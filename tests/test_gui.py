"""GUI: Başlat, Tkinter'ın __getattr__ tuzakına düşmeden log yazmalı."""

import gui

def test_start_without_key_logs_error_not_crash():
    app = gui.App()
    try:
        app.key_var.set("")
        app.start()  # eski kod: AttributeError '_append'
        text = app.log.get("1.0", "end")
        assert "API anahtarı" in text
        assert app.worker is None
        app._append("[bilgi] Kulaklık -> Hoparlör (en>tr)\n")
        assert "[bilgi] Kulaklık" in app.log.get("1.0", "end")
    finally:
        app.destroy()


def test_transcript_chunks_become_plain_text():
    app = gui.App()
    try:
        app.log_queue.put(("heard", "Onlar da dedi ki, gördüğün gibi"))
        app.log_queue.put(("heard", " başka bir sorun kalmış mıydı?"))
        app.log_queue.put(("heard_end",))
        app.log_queue.put(("trans", "They also asked if anything else remained."))
        app._pump_log()
        heard = app.heard.get("1.0", "end")
        trans = app.trans.get("1.0", "end")
        assert "Onlar da dedi ki, gördüğün gibi başka bir sorun kalmış mıydı?" in heard
        assert "[duyulan]" not in heard
        assert "They also asked if anything else remained." in trans
        assert "[çeviri]" not in trans
    finally:
        app.destroy()
