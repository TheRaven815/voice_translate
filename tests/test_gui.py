"""GUI: Başlat, Tkinter'ın __getattr__ tuzakına düşmeden log yazmalı."""

import tkinter as tk

from devices import NONE_OUTPUT
from gui.app import App
from gui.theme import C, ICON_ICO, ICON_PNG
from languages import AUTO_SRC, source_code
from meta import APP_AUTHOR, APP_TITLE, __version__


def test_app_name_version_and_about():
    app = App()
    try:
        assert app.title() == APP_TITLE == "Ahenk"
        assert app.brand["text"] == "Ahenk"
        assert app.version_lbl["text"] == "v0.1.0"
        assert ICON_ICO.is_file()
        assert ICON_PNG.is_file()
        assert getattr(app, "_ahenk_icon", None) is not None
        assert app.info_btn["text"] == "ⓘ"
        assert app._about is None
        app._open_about()
        assert app._about is not None
        assert app._about.title() == "Hakkında"
        assert app.about_name["text"] == "Ahenk"
        assert app.about_version["text"] == "v0.1.0"
        assert app.about_author["text"] == APP_AUTHOR == "Enes Eliağır"
        first = app._about
        app._open_about()
        assert app._about is first
        app._close_about()
        assert app._about is None
    finally:
        app.destroy()


def test_start_without_key_logs_error_not_crash():
    app = App()
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
    app = App()
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


def test_none_output_means_text_only():
    app = App()
    try:
        assert app.out_box["values"][0] == NONE_OUTPUT
        app.out_var.set(NONE_OUTPUT)
        assert app._selected_speaker() is None
    finally:
        app.destroy()


def test_auto_source_is_selectable_not_a_target():
    app = App()
    try:
        assert app.src_box["values"][0] == AUTO_SRC
        assert AUTO_SRC not in app.dst_box["values"]
        assert app.src_var.get() == AUTO_SRC
        assert source_code(app.src_var.get()) is None
        app.dst_var.set("Türkçe")
        app._swap_langs()
        assert app.src_var.get() == AUTO_SRC
        assert app.dst_var.get() == "Türkçe"
    finally:
        app.destroy()


def test_save_key_clears_selection_and_focus(tmp_path, monkeypatch):
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app = App()
    try:
        app.key_var.set("sk-test")
        app.key_entry.focus_force()
        app.key_entry.selection_range(0, tk.END)
        app.update()
        assert app.key_entry.selection_present()
        app.save_key()
        app.update()
        assert not app.key_entry.selection_present()
        assert app.focus_get() is not app.key_entry
        assert "kaydedildi" in app.log.get("1.0", "end")
    finally:
        app.destroy()


def test_select_closes_on_second_toggle_without_pick():
    app = App()
    try:
        box = app.src_box
        box._toggle()
        app.update()
        assert box._pop is not None
        box._toggle()
        app.update()
        assert box._pop is None
    finally:
        app.destroy()


def test_select_popup_expands_for_long_text_and_is_transient():
    app = App()
    try:
        long_val = "Çok Uzun Aygıt Adı (HDMI High Definition Audio Device Extra Long Text)"
        app.in_box["values"] = [long_val]
        app.in_box._toggle()
        app.update()
        pop = app.in_box._pop
        assert pop is not None
        assert pop.attributes("-topmost")
        assert pop.winfo_width() > app.in_box.winfo_width()
        app.event_generate("<FocusOut>")
        app.update()
        assert app.in_box._pop is None
    finally:
        app.destroy()


def test_select_popup_closes_on_window_move():
    app = App()
    try:
        app.in_box._toggle()
        app.update()
        assert app.in_box._pop is not None
        app.geometry("+450+350")
        app.update()
        assert app.in_box._pop is None
    finally:
        app.destroy()


def test_running_paints_status_dot_green():
    app = App()
    try:
        assert app._dot.itemcget(app._dot_id, "fill") == C.dim
        app._set_running(True)
        assert app._dot.itemcget(app._dot_id, "fill") == C.live
        app._set_running(False)
        assert app._dot.itemcget(app._dot_id, "fill") == C.dim
    finally:
        app.destroy()
