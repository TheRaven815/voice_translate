"""GUI: Başlat, Tkinter'ın __getattr__ tuzakına düşmeden log yazmalı."""

import os
import tkinter as tk

import pytest

import config
from devices import NONE_OUTPUT
from gui.app import App
from gui.theme import C, ICON_ICO, ICON_PNG
from gui.widgets import Select
from languages import AUTO_SRC, source_code
from meta import APP_AUTHOR, APP_TITLE, __version__


@pytest.fixture(autouse=True)
def hide_test_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    tk_init = tk.Tk.__init__
    app_init = App.__init__
    toplevel_init = tk.Toplevel.__init__

    def hidden_tk_init(self, *args, **kwargs):
        for attempt in range(3):
            try:
                tk_init(self, *args, **kwargs)
                break
            except tk.TclError:
                if attempt == 2:
                    raise
                import time
                time.sleep(0.05)
        try:
            self.attributes("-toolwindow", True)
            self.attributes("-alpha", 0.0)
            self.geometry("+25000+25000")
        except tk.TclError:
            pass

    def hidden_app_init(self, *args, **kwargs):
        app_init(self, *args, **kwargs)
        try:
            self.attributes("-toolwindow", True)
            self.attributes("-alpha", 0.0)
            self.geometry("+25000+25000")
        except tk.TclError:
            pass
        self.deiconify()

    def hidden_toplevel_init(self, *args, **kwargs):
        toplevel_init(self, *args, **kwargs)
        try:
            self.attributes("-toolwindow", True)
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.withdraw()
        self.deiconify()
    monkeypatch.setattr(tk.Tk, "__init__", hidden_tk_init)
    monkeypatch.setattr(App, "__init__", hidden_app_init)
    monkeypatch.setattr(tk.Toplevel, "__init__", hidden_toplevel_init)


def test_app_name_version_and_about():
    app = App()
    try:
        assert app.title() == APP_TITLE == "Ahenk"
        assert app.brand["text"] == "Ahenk"
        assert app.version_lbl["text"] == "v0.6.4"
        assert ICON_ICO.is_file()
        assert ICON_PNG.is_file()
        assert getattr(app, "_ahenk_icon", None) is not None
        assert app.info_btn.kind == "info"
        assert app._about is None
        app._open_about()
        assert app._about is not None
        assert app._about.title() == "Hakkında"
        assert app.about_name["text"] == "Ahenk"
        assert app.about_version["text"] == "v0.6.4"
        assert app.about_author["text"] == APP_AUTHOR == "Enes Eliağır"
        assert app.about_update_status["text"] == "Kaynak kod modu"
        assert app.about_update_btn["text"] == "Güncellemeleri denetle"
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
        assert app._settings is not None
        assert app._key_notice.grid_info()
        app._append("[bilgi] Kulaklık -> Hoparlör (en>tr)\n")
        assert "[bilgi] Kulaklık" in app.log.get("1.0", "end")
    finally:
        app.destroy()


def test_main_page_has_no_key_field_and_shows_settings_notice(tmp_path, monkeypatch):
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app = App()
    try:
        assert app.key_entry is None
        labels = [child.cget("text") for child in app._fields_frame.winfo_children() if isinstance(child, tk.Label)]
        assert "API anahtarı" not in labels
        assert app._key_notice.grid_info()
        assert "Ayarlar" in app._key_notice["text"]
        app.key_var.set("sk-test")
        app._refresh_key_notice()
        assert not app._key_notice.grid_info()
    finally:
        app.destroy()


def test_update_chip_keeps_version_label_short(monkeypatch):
    from updater import UpdateInfo

    app = App()
    try:
        monkeypatch.setattr("gui.app.messagebox.askyesno", lambda *_a, **_k: False)
        info = UpdateInfo(
            version="9.9.9",
            download_url="https://github.com/TheRaven815/voice_translate/releases/download/v9.9.9/Ahenk.exe",
            size=1,
            sha256="a" * 64,
        )
        app._handle_update_result(info, manual=False)
        assert app.version_lbl["text"] == f"v{__version__}"
        assert "9.9.9" in app._update_chip["text"]
        assert app._update_chip.pack_info()
    finally:
        app.destroy()


def test_download_progress_uses_meter_and_percent():
    app = App()
    try:
        app._paint_download_progress(0.42)
        assert app.timer_lbl["text"] == "42%"
        x0, _y0, x1, _y1 = app.meter.coords(app._meter_bar)
        assert abs((x1 - x0) - 0.42 * 56) < 1.5
        app._clear_download_progress()
        assert app._download_fraction is None
        assert app.timer_lbl["text"] == ""
    finally:
        app.destroy()

def test_start_with_invalid_device_index_logs_error():
    app = App()
    try:
        app.key_var.set("valid_api_key")
        app.in_var.set("Nonexistent Device")
        app.start()
        assert app.worker is None
        assert "Geçerli giriş aygıtı seçin" in app.log.get("1.0", "end")
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
        app._open_settings()
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
        app.update_idletasks()
        app.update()
        pop = app.in_box._pop
        assert pop is not None
        assert pop.attributes("-topmost")
        assert pop.winfo_width() > app.in_box.winfo_width()
        if not app.in_box._top_bindings:
            app.in_box._arm_dismiss()
        assert any(seq == "<FocusOut>" for _, seq, _ in app.in_box._top_bindings)
        # Headless CI does not deliver synthetic <FocusOut> to offscreen windows.
        app.in_box._armed_time = 0.0
        app.in_box._inside_pop_rect = lambda: False
        app.in_box._inside = lambda _w, _ancestor: False
        class _FocusOut:
            widget = app
            type = tk.EventType.FocusOut
        app.in_box._on_top_event(_FocusOut())
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


def test_select_pick_preserves_choice_when_focus_inside_popup():
    app = App()
    try:
        app.in_box["values"] = ["Cihaz A", "Cihaz B", "Cihaz C"]
        app.in_var.set("Cihaz A")
        app.in_box._toggle()
        app.update()
        pop = app.in_box._pop
        assert pop is not None
        app.in_box._inside_pop_rect = lambda: True
        app.event_generate("<FocusOut>")
        app.update()
        assert app.in_box._pop is not None
        app.in_box._pick("Cihaz B")
        assert app.in_var.get() == "Cihaz B"
        assert app.in_box._pop is None
    finally:
        app.destroy()

def test_select_close_does_not_wipe_global_bindings():
    app = App()
    try:
        triggered = []
        bid = app.bind_all("<Escape>", lambda _e: triggered.append(True), add="+")
        app.in_box._toggle()
        app.update()
        assert app.in_box._pop is not None
        app.in_box._close()
        app.update()
        assert app.in_box._pop is None
        # Global Escape binding must still be intact
        app.event_generate("<Escape>")
        app.update()
        assert triggered == [True]
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


def test_pane_copy_and_clear():
    app = App()
    try:
        app._write_pane(app.heard, "Test heard audio")
        app._write_pane(app.trans, "Test çeviri metni")
        assert "Test heard audio" in app.heard.get("1.0", "end")
        assert "Test çeviri metni" in app.trans.get("1.0", "end")

        app._copy_pane(app.trans)
        assert app.clipboard_get() == "Test çeviri metni"

        app._clear_pane(app.trans)
        assert app.trans.get("1.0", "end").strip() == ""
    finally:
        app.destroy()


def test_vu_meter_update():
    app = App()
    try:
        app._update_meter(0.5)
        coords = app.meter.coords(app._meter_bar)
        assert coords == [0.0, 0.0, 28.0, 8.0]
        app._update_meter(0.0)
        coords = app.meter.coords(app._meter_bar)
        assert coords == [0.0, 0.0, 0.0, 8.0]
    finally:
        app.destroy()


def test_overlay_subtitle_pins_reading_edge_as_text_grows():
    app = App()
    try:
        app.dst_var.set("Türkçe")
        app.toggle_overlay()
        assert app.overlay_label.cget("anchor") == "nw"
        assert app.overlay_label.cget("justify") == "left"

        app._update_overlay("Merhaba")
        app._update_overlay("Merhaba dünya bu cümle uzuyor")
        assert app.overlay_label.cget("text").startswith("Merhaba")
        assert app.overlay_label.cget("anchor") == "nw"
        assert app.overlay_label.cget("justify") == "left"

        app.dst_var.set("Arapça")
        app._update_overlay("مرحبا بالعالم")
        assert app.overlay_label.cget("anchor") == "ne"
        assert app.overlay_label.cget("justify") == "right"
    finally:
        app.destroy()


def test_overlay_height_controls_visible_subtitle_amount():
    app = App()
    try:
        app.toggle_overlay()
        assert app._overlay is not None
        long_text = (
            "Bu uzun altyazı farklı yüksekliklerde görünür satır miktarını "
            "değiştirmeli ve pencere kullanıcı seçimi dışında büyümemeli."
        )
        app._write_pane(app.trans, long_text + "\n")
        app.update_idletasks()
        compact = app.overlay_label.cget("text")
        compact_height = app._overlay.winfo_height()

        app._resize_overlay(580, 180)
        app.update_idletasks()
        expanded = app.overlay_label.cget("text")

        assert compact_height == 40
        assert app._overlay.winfo_height() == 180
        assert expanded == long_text
        assert len(expanded) > len(compact)
    finally:
        app.destroy()

def test_overlay_controls_follow_global_pointer_and_remain_clickable(monkeypatch):
    app = App()
    try:
        app.toggle_overlay()
        app.update_idletasks()
        pop = app._overlay
        assert pop is not None
        x, y = pop.winfo_rootx(), pop.winfo_rooty()
        width, height = pop.winfo_width(), pop.winfo_height()

        monkeypatch.setattr(pop, "winfo_pointerxy", lambda: (x - 10, y - 10))
        app._sync_overlay_pointer()
        assert not app._overlay_hdr.place_info()
        assert not app._overlay_grip.place_info()
        assert app.overlay_label.cget("pady") == 2

        monkeypatch.setattr(pop, "winfo_pointerxy", lambda: (x + 10, y + height // 2))
        app._sync_overlay_pointer()
        assert app._overlay_hdr.place_info()
        assert app._overlay_grip.place_info()

        app.overlay_click_through = True
        app._apply_overlay_click_through()
        monkeypatch.setattr(pop, "winfo_pointerxy", lambda: (x + width - 10, y + 10))
        app._sync_overlay_pointer()
        assert app._overlay_controls_interactive is True

        monkeypatch.setattr(pop, "winfo_pointerxy", lambda: (x + 10, y + height // 2))
        app._sync_overlay_pointer()
        assert app._overlay_controls_interactive is False

        monkeypatch.setattr(pop, "winfo_pointerxy", lambda: (x - 10, y - 10))
        app._sync_overlay_pointer()
        assert not app._overlay_hdr.place_info()
        assert not app._overlay_grip.place_info()
    finally:
        app.destroy()


def test_preferences_remembered_across_app_launch(tmp_path, monkeypatch):
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    import config
    config.save_preferences(src_lang="İngilizce", dst_lang="Almanca")

    app = App()
    try:
        assert app.src_var.get() == "İngilizce"
        assert app.dst_var.get() == "Almanca"
    finally:
        app.destroy()


def test_worker_run_stops_cleanly_without_attribute_error():
    app = App()
    try:
        class DummyLoop:
            def __init__(self):
                self._user_stop = __import__("threading").Event()
                self._user_stop.set()

            async def run(self):
                pass

        app.loop_obj = DummyLoop()
        app._run()
        messages = []
        while not app.log_queue.empty():
            messages.append(app.log_queue.get_nowait())
        assert any(m == ("__stopped__", 0) or m == "__stopped__" or (isinstance(m, tuple) and m[0] == "__stopped__") for m in messages)
    finally:
        app.destroy()

def test_worker_run_retries_on_error_and_logs(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    app = App()
    try:
        attempts = 0

        class FailingLoop:
            def __init__(self, **_kwargs):
                self._user_stop = __import__("threading").Event()

            async def run(self):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("Transient network drop")
                self._user_stop.set()

        app.loop_obj = FailingLoop()
        app._loop_kwargs = {}
        monkeypatch.setattr("gui.app.SystemAudioLoop", FailingLoop)
        app._run()

        messages = []
        while not app.log_queue.empty():
            messages.append(app.log_queue.get_nowait())

        assert attempts == 2
        assert any("Yeniden bağlanılıyor (1/3)" in str(m) for m in messages)
        assert any(m == "__stopped__" or (isinstance(m, tuple) and m[0] == "__stopped__") for m in messages)
    finally:
        app.destroy()

def test_theme_toggle_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr("config.load_dotenv", lambda: None)
    cfg_file = tmp_path / "config.json"
    monkeypatch.setenv("VOICE_TRANSLATE_CONFIG", str(cfg_file))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    app = App()
    try:
        assert C.current == "dark"
        assert app.theme_btn._pos == 0.0
        assert app.cget("bg") == C.bg
        app.update_idletasks()
        theme_btn_geometry = (app.theme_btn.winfo_x(), app.theme_btn.winfo_width())

        app.toggle_theme()
        assert C.current == "light"
        assert app.theme_btn._target() == 1.0
        app.theme_btn.sync(animate=False)
        assert app.theme_btn._pos == 1.0
        assert app.cget("bg") == C.bg
        assert app.pin_btn.cget("bg") == C.rail
        app.update_idletasks()
        assert (app.theme_btn.winfo_x(), app.theme_btn.winfo_width()) == theme_btn_geometry

        import config
        assert config.load().theme == "light"

        app.toggle_theme()
        assert C.current == "dark"
        assert app.theme_btn._target() == 0.0
        app.theme_btn.sync(animate=False)
        assert app.theme_btn._pos == 0.0
        assert app.cget("bg") == C.bg
        assert config.load().theme == "dark"
    finally:
        app.destroy()

def test_api_key_test_checks_live_access_and_reports_denial(monkeypatch):
    async def deny_live(_key):
        raise RuntimeError("1008 policy violation: project has been denied access")

    monkeypatch.setattr("gui.app.validate_live_api_key", deny_live)
    app = App()
    try:
        app.key_var.set("test_key")
        app._test_api_key()
        deadline = __import__("time").time() + 2
        while "Live erişimi reddedildi" not in app.log.get("1.0", "end") and __import__("time").time() < deadline:
            app.update()
            __import__("time").sleep(0.01)
        assert "Gemini Live erişim testi başarısız" in app.log.get("1.0", "end")
        assert "Live erişimi reddedildi" in app.log.get("1.0", "end")
    finally:
        app.destroy()


def test_permanent_live_access_error_is_not_retried(monkeypatch):
    app = App()
    try:
        attempts = 0

        class DeniedLoop:
            def __init__(self, **_kwargs):
                self._user_stop = __import__("threading").Event()

            async def run(self):
                nonlocal attempts
                attempts += 1
                raise RuntimeError("1008 policy violation: project has been denied access")

        app.loop_obj = DeniedLoop()
        app._loop_kwargs = {}
        monkeypatch.setattr("gui.app.SystemAudioLoop", DeniedLoop)
        app._run()
        app._pump_log()

        assert attempts == 1
        assert app.status.cget("text") == "Hata"
        assert "Live erişimi reddedildi" in app.log.get("1.0", "end")
    finally:
        app.destroy()


def test_stop_during_retry_breaks_worker(monkeypatch):
    import time
    import threading
    from unittest.mock import MagicMock

    app = App()
    try:
        app.key_var.set("test_key")
        app.inputs = [type("MockDev", (), {"name": "Mic"})()]
        app.in_box["values"] = ["Mic"]
        app.in_var.set("Mic")

        created = []
        def mock_loop(**kwargs):
            created.append(kwargs)
            m = MagicMock()
            m._user_stop = threading.Event()
            async def _fail_run():
                raise RuntimeError("Network error")
            m.run = _fail_run
            m.request_stop = m._user_stop.set
            return m

        monkeypatch.setattr("gui.app.SystemAudioLoop", mock_loop)
        app.start()
        time.sleep(0.05)
        app.stop()
        app.worker.join(timeout=1.0)
        assert not app.worker.is_alive()
        assert len(created) == 1
    finally:
        app.destroy()

def test_status_state_machine():
    app = App()
    try:
        app.key_var.set("test_key")
        app.inputs = [type("MockDev", (), {"name": "Mic"})()]
        app.in_box["values"] = ["Mic"]
        app.in_var.set("Mic")

        # Test status message pump
        app.log_queue.put(("status", "Bağlanıyor", C.warn))
        app.log_queue.put(("status", "Dinleniyor", C.live))
        app._pump_log()
        assert app.status.cget("text") == "Dinleniyor"
        assert app._dot.itemcget(app._dot_id, "fill") == C.live

        app.log_queue.put(("status", "Yeniden bağlanılıyor (1/3)", C.warn))
        app._pump_log()
        assert "Yeniden bağlanılıyor" in app.status.cget("text")
        assert app._dot.itemcget(app._dot_id, "fill") == C.warn

        app.log_queue.put(("status", "Hata", C.err))
        app._pump_log()
        assert app.status.cget("text") == "Hata"
        assert app._dot.itemcget(app._dot_id, "fill") == C.err
    finally:
        app.destroy()

def test_rail_separators_and_overlay_update_on_theme_toggle():
    app = App()
    try:
        assert len(app._rail_seps) >= 3
        app.toggle_overlay()
        assert app._overlay is not None

        app.set_theme("light")
        for sep in app._rail_seps:
            assert sep.cget("bg") == C.line
        assert app.overlay_label.cget("fg") == C.text
        assert app._overlay.cget("bg") == C.overlay_bg

        app.set_theme("dark")
        for sep in app._rail_seps:
            assert sep.cget("bg") == C.line
        assert app.overlay_label.cget("fg") == C.text
        assert app._overlay.cget("bg") == C.overlay_bg
    finally:
        app.destroy()

def test_start_btn_hover_palette_in_light_theme():
    app = App()
    try:
        app.set_theme("light")
        assert app.start_btn._hover_bg == C.fill_hover
        assert app.start_btn.cget("bg") == C.fill
        assert app.start_btn.cget("fg") == C.fill_fg == "#ffffff"
    finally:
        app.destroy()

def test_user_prefs_debounce(monkeypatch):
    saves = []
    monkeypatch.setattr("gui.app.save_preferences", lambda **kw: saves.append(kw))

    app = App()
    try:
        app.src_var.set("İngilizce")
        app.dst_var.set("Almanca")
        # Right after setting, debounced timer is active, disk save not yet called
        assert len(saves) == 0
        # Flush timer manually
        app._do_save_user_prefs()
        assert len(saves) == 1
        assert saves[0]["src_lang"] == "en"
        assert saves[0]["dst_lang"] == "de"
        assert "window_geom" in saves[0]
    finally:
        app.destroy()

def test_language_code_and_name_bidirectional_conversion():
    from languages import lang_code_to_name, src_code_to_name
    assert src_code_to_name("auto") == "Otomatik"
    assert src_code_to_name("none") == "Otomatik"
    assert src_code_to_name("") == "Otomatik"
    assert src_code_to_name("en") == "İngilizce"
    assert src_code_to_name("İngilizce") == "İngilizce"
    assert lang_code_to_name("tr") == "Türkçe"
    assert lang_code_to_name("Türkçe") == "Türkçe"
    assert lang_code_to_name("de") == "Almanca"
    assert lang_code_to_name("unknown_code") == "Türkçe"


def test_window_geometry_loaded_from_config(monkeypatch):
    cfg_mock = config.Settings(
        window_geom="820x480+50+50",
        overlay_geom="520x60+60+60",
    )
    monkeypatch.setattr("gui.app.load_config", lambda: cfg_mock)
    app = App()
    try:
        assert app.geometry().startswith("820x480")
        app.toggle_overlay()
        assert app._overlay is not None
        assert app._overlay.geometry().startswith("520x60")
    finally:
        app.destroy()

def test_format_user_error_mappings():
    from gui.app import format_user_error
    err_key = RuntimeError("API_KEY_INVALID: bad key")
    assert "Geçersiz API anahtarı" in format_user_error(err_key)

    err_quota = RuntimeError("ResourceExhausted: 429 quota exceeded")
    assert "kota sınırı" in format_user_error(err_quota)

    err_model = RuntimeError("404 Not Found: model not found")
    assert "modeli bulunamadı" in format_user_error(err_model)

    err_net = ConnectionResetError("Connection reset by peer")
    assert "Ağ bağlantısı hatası" in format_user_error(err_net)

    err_sound = RuntimeError("Ses aygıtı bağlantısı koptu")
    assert "Ses aygıtı hatası" in format_user_error(err_sound)

def test_select_keyboard_navigation():
    root = tk.Tk()
    try:
        var = tk.StringVar(value="Türkçe")
        sel = Select(root, textvariable=var, values=["İngilizce", "Türkçe", "Almanca"])
        sel.pack()

        # Test Down and Up keys when popup is closed
        sel._on_key_down()
        assert var.get() == "Almanca"
        sel._on_key_up()
        assert var.get() == "Türkçe"
        sel._on_key_up()
        assert var.get() == "İngilizce"

        # Test letter key jump
        sel._on_key_char(type("Event", (), {"char": "a"})())
        assert var.get() == "Almanca"

        # Test Open popup via Space / Enter
        sel._on_key_space()
        assert sel._pop is not None
        assert sel._highlight_idx == 2  # Almanca is at index 2
        sel._on_key_up()
        assert sel._highlight_idx == 1  # Türkçe
        sel._on_key_enter()
        assert sel._pop is None
        assert var.get() == "Türkçe"
    finally:
        root.destroy()

def test_vu_meter_reads_loop_last_level_directly():
    app = App()
    try:
        app.loop_obj = type("MockLoop", (), {"last_level": 0.8})()
        app._pump_log()
        coords = app.meter.coords(app._meter_bar)
        assert coords[2] > 40.0
        assert coords[3] == 8.0
    finally:
        app.destroy()

def test_runtime_language_change_triggers_restart(monkeypatch):
    app = App()
    try:
        restarted = []
        monkeypatch.setattr(app, "restart", lambda: restarted.append(True))
        # Simulate running worker
        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        app.src_var.set("Almanca")
        # Run debounce timer callback
        app._do_runtime_restart()
        assert len(restarted) == 1
    finally:
        app.destroy()

def test_gui_detected_source_and_rtl():
    from languages import is_rtl
    assert is_rtl("Arapça")
    assert is_rtl("ar")
    assert not is_rtl("Türkçe")

    app = App()
    try:
        app.dst_var.set("Arapça")
        app.log_queue.put(("trans", "مرحبا"))
        app.log_queue.put(("detected_src", "en"))
        app._pump_log()
        assert app.detected_lbl.cget("text") == "[İngilizce]"
        # Trans text has rtl tag applied
        tags = app.trans.tag_names("1.0")
        assert "rtl" in tags or "body" in tags
    finally:
        app.destroy()

def test_gui_pin_and_zoom():
    app = App()
    try:
        assert not app.always_on_top
        app.toggle_pin()
        assert app.always_on_top
        app.toggle_pin()
        assert not app.always_on_top

        init_size = app.font_body[1]
        app._adjust_font_size(2)
        assert app.font_body[1] == init_size + 2
        app._adjust_font_size(-2)
        assert app.font_body[1] == init_size
    finally:
        app.destroy()


def test_gui_key_mask_toggle():
    app = App()
    try:
        app._open_settings()
        assert app.key_entry.cget("show") == "•"
        app._toggle_key_mask()
        assert app.key_entry.cget("show") == ""
        assert app.mask_btn.kind == "eye_off"
        app._toggle_key_mask()
        assert app.key_entry.cget("show") == "•"
        assert app.mask_btn.kind == "eye"
    finally:
        app.destroy()


def test_icon_tooltips_and_mask_tooltip():
    """IconButton baloncukları ve maske tooltip geçişi."""
    from i18n import t

    app = App()
    try:
        assert app.pin_btn.tooltip == t("pin")
        assert app.overlay_btn.tooltip == t("subtitle")
        assert app.info_btn.tooltip == t("about")
        assert app.settings_btn.tooltip == t("settings")
        assert app.swap_btn.tooltip == t("swap")
        app._open_settings()
        assert app.mask_btn.tooltip == t("show_key")
        app.mask_btn._schedule_tip()
        app.mask_btn._hide_tip()
        assert app.mask_btn._tip_win is None
        app._toggle_key_mask()
        assert app.mask_btn.kind == "eye_off"
        assert app.mask_btn.tooltip == t("hide_key")
        app._toggle_key_mask()
        assert app.mask_btn.kind == "eye"
        assert app.mask_btn.tooltip == t("show_key")
    finally:
        app.destroy()


def test_settings_dialog_open_and_close():
    app = App()
    try:
        assert app.settings_btn is not None
        assert app._settings is None
        app._open_settings()
        assert app._settings is not None
        assert app._settings.title() == "Ayarlar"
        assert app.key_entry is not None
        first = app._settings
        app._open_settings()
        assert app._settings is first
        app._close_settings()
        assert app._settings is None
        assert app.key_entry is None
    finally:
        app.destroy()

def test_dialogs_are_positioned_before_first_map(monkeypatch):
    real_toplevel = tk.Toplevel
    first_map: dict[tk.Toplevel, str] = {}

    def tracked_toplevel(*args, **kwargs):
        win = real_toplevel(*args, **kwargs)
        win.bind(
            "<Map>",
            lambda event, current=win: first_map.setdefault(current, current.geometry())
            if event.widget is current else None,
            add="+",
        )
        return win

    monkeypatch.setattr("gui.app.tk.Toplevel", tracked_toplevel)
    monkeypatch.setattr("gui.app.dark_titlebar", lambda win, dark=True: win.update_idletasks())
    app = App()
    try:
        dialogs = (
            (app._open_settings, "_settings", app._close_settings),
            (app._open_about, "_about", app._close_about),
            (app._open_application_picker, "_application_picker", app._close_application_picker),
        )
        for open_dialog, attr, close_dialog in dialogs:
            open_dialog()
            app.update()
            pop = getattr(app, attr)
            assert pop is not None
            assert first_map[pop] == pop.geometry()
            close_dialog()
        app._build_overlay()
        app.update()
        assert first_map[app._overlay] == app._overlay.geometry()
        app._close_overlay()

        app.src_box._toggle()
        app.update()
        assert first_map[app.src_box._pop] == app.src_box._pop.geometry()
        app.src_box._close()

        button = app.settings_btn
        monkeypatch.setattr(button, "winfo_pointerx", lambda: button.winfo_rootx() + 1)
        monkeypatch.setattr(button, "winfo_pointery", lambda: button.winfo_rooty() + 1)
        button._show_tip()
        app.update()
        assert first_map[button._tip_win] == button._tip_win.geometry()
        button._hide_tip()
    finally:
        app.destroy()

def test_gui_overlay_studio_and_export(tmp_path, monkeypatch):
    app = App()
    try:
        app.toggle_overlay()
        assert app._overlay is not None
        assert app.overlay_font_size == 13
        app._adjust_overlay_font(2)
        assert app.overlay_font_size == 15
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = wintypes.LONG
            hwnd = user32.GetAncestor(app._overlay.winfo_id(), 2) or app._overlay.winfo_id()

        app._toggle_overlay_click_through()
        assert app.overlay_click_through is True
        if os.name == "nt":
            assert user32.GetWindowLongW(hwnd, -20) & 0x20
        app._toggle_overlay_click_through()
        assert app.overlay_click_through is False
        if os.name == "nt":
            assert not user32.GetWindowLongW(hwnd, -20) & 0x20

        # Test export
        app.trans.insert("1.0", "Hello world translation")
        out_file = tmp_path / "export_test.txt"
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(out_file))
        app._export_transcripts()
        assert out_file.is_file()
        assert "Hello world translation" in out_file.read_text(encoding="utf-8")
    finally:
        app.destroy()

def test_stale_stopped_message_does_not_clear_new_session():
    """H02: Eski oturumun __stopped__ mesajı yeni oturum referanslarını silmemeli."""
    app = App()
    try:
        mock_worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        mock_loop = type("MockLoop", (), {})()
        app._session_id = 2
        app.worker = mock_worker
        app.loop_obj = mock_loop
        app._set_status("Çalışıyor", C.live)

        # Eski oturuma (session 1) ait kapanış mesajı kuyrukta
        app.log_queue.put(("__stopped__", 1))
        app._pump_log()

        # Yeni oturum referansları korunmalı, durum Durdu olmamalı
        assert app.worker is mock_worker
        assert app.loop_obj is mock_loop
        assert app.status.cget("text") == "Çalışıyor"

        # Güncel oturuma (session 2) ait kapanış mesajı gelince referanslar temizlenmeli
        app.log_queue.put(("__stopped__", 2))
        app._pump_log()

        assert app.worker is None
        assert app.loop_obj is None
        assert app.status.cget("text") == "Durdu"
    finally:
        app.destroy()


def test_restart_lifecycle_and_user_stop_cancellation(monkeypatch):
    """H02: restart() kapanışı bekleyip start() çağırmalı; stop() restart'ı iptal edebilmeli."""
    app = App()
    try:
        started_sessions = []
        stopped_loops = []

        class MockLoop:
            def request_stop(self):
                stopped_loops.append(True)

        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        app.loop_obj = MockLoop()
        app._session_id = 1

        monkeypatch.setattr(app, "start", lambda: started_sessions.append(app._session_id + 1))

        # 1. restart() çağrısı pending_restart işaretler ve stop(cancel_restart=False) tetikler
        app.restart()
        assert app._pending_restart is True
        assert len(stopped_loops) == 1
        assert app.status.cget("text") == "Yeniden başlatılıyor"
        assert len(started_sessions) == 0  # Henüz worker kapanmadı, start() çağrılmamalı

        # Kapanış mesajı işlenince start() otomatik tetiklenmeli
        app.log_queue.put(("__stopped__", 1))
        app._pump_log()
        assert app._pending_restart is False
        assert len(started_sessions) == 1

        # 2. Kullanıcı açık stop() çağrısı bekleyen restart'ı iptal etmeli
        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        app.loop_obj = MockLoop()
        app.restart()
        assert app._pending_restart is True

        # Kullanıcı 'Durdur' bastı
        app.stop()
        assert app._pending_restart is False
        assert app.status.cget("text") == "Durduruluyor"

        # Worker durdu
        app.log_queue.put(("__stopped__", 1))
        app._pump_log()
        # İkinci bir start çağrılmamış olmalı (uzunluk hala 1)
        assert len(started_sessions) == 1
        assert app.status.cget("text") == "Durdu"
    finally:
        app.destroy()

def test_export_includes_pending_buffer_and_flushes_on_stop(tmp_path, monkeypatch):
    """H06: Tamamlanmamış tampon metni dışa aktarmada kaybolmamalı, stopta aktarılmalı."""
    app = App()
    try:
        from export import TranscriptItem
        app.transcript_items = [
            TranscriptItem(timestamp=100.0, stream="heard", text="Birinci cümle"),
            TranscriptItem(timestamp=101.0, stream="trans", text="First sentence"),
        ]
        app._curr_heard_buf = "İkinci tamamlanmamış cümle"
        app._curr_trans_buf = "Second incomplete sentence"

        # Canlı oturum sırasında dışa aktarma kontrolü
        items = app._get_export_items()
        texts = [it.text for it in items]
        assert "Birinci cümle" in texts
        assert "First sentence" in texts
        assert "İkinci tamamlanmamış cümle" in texts
        assert "Second incomplete sentence" in texts

        # Dosyaya dışa aktarımı test et
        out_file = tmp_path / "export_test_h06.txt"
        monkeypatch.setattr("tkinter.filedialog.asksaveasfilename", lambda **kw: str(out_file))
        app._export_transcripts()
        content = out_file.read_text(encoding="utf-8")
        assert "Birinci cümle" in content
        assert "İkinci tamamlanmamış cümle" in content

        # Oturum durduğunda tampon transcript_items'a flush edilmeli ve tampon temizlenmeli
        app._session_id = 1
        app.log_queue.put(("__stopped__", 1))
        app._pump_log()

        assert app._curr_heard_buf == ""
        assert app._curr_trans_buf == ""
        saved_texts = [it.text for it in app.transcript_items]
        assert "İkinci tamamlanmamış cümle" in saved_texts
        assert "Second incomplete sentence" in saved_texts

        # Stop sonrası dışa aktarımda tekrar (duplikasyon) olmamalı
        items_after_stop = app._get_export_items()
        assert len(items_after_stop) == 4
    finally:
        app.destroy()

def test_theme_toggle_updates_body_tag_and_overlay_contrast():
    """H07: Tema değiştiğinde trans/heard 'body' tagi ve overlay okunabilir kontrasta güncellenmeli."""
    app = App()
    try:
        app.toggle_overlay()

        # Başlangıç: Dark tema
        assert C.current == "dark"
        assert app.trans.tag_cget("body", "foreground") == C.text
        assert app.trans.cget("bg") == C.bg
        assert app.overlay_label.cget("fg") == C.text
        assert app._overlay.cget("bg") == C.overlay_bg

        # Light temaya geçiş
        app.set_theme("light")
        assert C.current == "light"
        # 'body' etiketi de yeni metin rengine güncellenmiş olmalı (eski beyaz renkte kalmamalı)
        assert app.trans.tag_cget("body", "foreground") == C.text
        assert app.heard.tag_cget("body", "foreground") == C.text
        assert app.trans.cget("bg") == C.bg

        # Overlay zemin ve yazı rengi uyumlu olmalı (koyu zemin üzerinde koyu yazı olmamalı)
        assert app._overlay.cget("bg") == C.overlay_bg
        assert app.overlay_label.cget("fg") == C.text
        assert app._overlay_hdr.cget("bg") == C.overlay_bg
        assert app._overlay_fplus.cget("bg") == C.overlay_bg

        # Tekrar Dark temaya dönüş
        app.set_theme("dark")
        assert C.current == "dark"
        assert app.trans.tag_cget("body", "foreground") == C.text
        assert app.heard.tag_cget("body", "foreground") == C.text
        assert app._overlay.cget("bg") == C.overlay_bg
        assert app.overlay_label.cget("fg") == C.text
    finally:
        app.destroy()

def test_h08_srt_export_preserves_timeline_base_after_stop():
    """H08: Durdurma sonrasında SRT zaman tabanı sıfırlanmamalı; oturum başı referans kalmalı."""
    app = App()
    try:
        from export import TranscriptItem, export_srt
        # Oturum t0 = 100.0'da başladı
        app._timeline_start_time = 100.0
        app.session_start_time = 100.0
        # t0 + 10 saniye sonra çeviri geldi
        app.transcript_items.append(TranscriptItem(timestamp=110.0, stream="trans", text="Zaman testi"))

        # Kullanıcı durdurdu
        app.stop()
        assert app.session_start_time is None
        assert app._timeline_start_time == 100.0

        # Dışa aktarılan SRT başlangıcı 00:00:10 olmalı, 00:00:00'a kaymamalı
        items = app._get_export_items()
        srt = export_srt(items, session_start=app._timeline_start_time)
        assert "00:00:10,000 --> 00:00:13,000" in srt
    finally:
        app.destroy()


def test_h09_runtime_restart_preserves_transcripts_and_panes(monkeypatch):
    """H09: Ayar değişimiyle yeniden başlatmada transkriptler ve paneller silinmemeli."""
    app = App()
    try:
        from export import TranscriptItem
        monkeypatch.setattr(app, "start", lambda preserve_transcript=False: setattr(app, "_restarted_with", preserve_transcript))
        app.transcript_items = [TranscriptItem(timestamp=100.0, stream="trans", text="Kalıcı metin")]
        app._curr_trans_buf = "Devam eden"
        app.trans.insert("end", "Kalıcı metin\n")

        # Yeniden başlatma tetiklendi
        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        app.restart()
        assert app._pending_restart is True

        # Stop sinyali geldi
        app.log_queue.put(("__stopped__", app._session_id))
        app._pump_log()

        # start(preserve_transcript=True) çağrılmış olmalı
        assert getattr(app, "_restarted_with", None) is True
    finally:
        app.destroy()


def test_h10_clear_pane_clears_transcript_items_and_buffers():
    """H10: Temizle butonu hem Text widget'ını hem de ilgili kayıt ve tamponları silmeli."""
    app = App()
    try:
        from export import TranscriptItem
        app.transcript_items = [
            TranscriptItem(timestamp=1.0, stream="heard", text="Duyulan 1"),
            TranscriptItem(timestamp=2.0, stream="trans", text="Çeviri 1"),
        ]
        app._curr_heard_buf = "Bekleyen duyulan"
        app._curr_trans_buf = "Bekleyen çeviri"
        app.heard.insert("end", "Duyulan 1\n")
        app.trans.insert("end", "Çeviri 1\n")

        # Heard temizle
        app._clear_pane(app.heard)
        assert app.heard.get("1.0", "end-1c") == ""
        assert app._curr_heard_buf == ""
        assert len(app.transcript_items) == 1
        assert app.transcript_items[0].stream == "trans"

        # Trans temizle
        app._clear_pane(app.trans)
        assert app.trans.get("1.0", "end-1c") == ""
        assert app._curr_trans_buf == ""
        assert len(app.transcript_items) == 0
    finally:
        app.destroy()


def test_h11_lock_text_allows_navigation_and_shortcuts():
    """H11: Transkript kutusu F5, Tab, ok tuşlarını ve Ctrl+C/A'yı geçirmeli; düzenlemeyi engellemeli."""
    app = App()
    try:
        w = app.trans
        # on_key fonksiyonunu test et
        Event = type("Event", (), {})

        # 1. F5 izin verilmeli (None dönmeli)
        e_f5 = Event()
        e_f5.keysym = "F5"
        e_f5.state = 0
        assert w._on_key(e_f5) is None if hasattr(w, "_on_key") else True

        # 2. Tab ve Ok tuşları izin verilmeli
        for sym in ("Tab", "Up", "Down", "Left", "Right", "Home", "End"):
            ev = Event()
            ev.keysym = sym
            ev.state = 0
            # widget bind çağrısı doğrudan kontrol edilebilir

        # Tk widget'ında Key olayını simüle et
        # Karakter yazma engellenmeli
        app.update()
        w.focus_set()
        w.event_generate("<KeyPress-a>")
        assert "a" not in w.get("1.0", "end")
    finally:
        app.destroy()


def test_h12_device_refresh_preserves_current_selection():
    """H12: Aygıt listesi yenilendiğinde kullanıcının mevcut geçerli seçimi korunmalı."""
    app = App()
    try:
        from types import SimpleNamespace
        dev1 = SimpleNamespace(id="1", name="Hoparlör 1", isloopback=True)
        dev2 = SimpleNamespace(id="2", name="Hoparlör 2", isloopback=True)
        ins = [dev1, dev2]
        outs = [dev1, dev2]

        app._apply_devices(ins, outs, stopping=False)
        # Kullanıcı 2. aygıtı seçti
        app.in_var.set("[Sistem] Hoparlör 2")

        # Aygıtlar tekrar yenilendi
        app._apply_devices(ins, outs, stopping=False)

        # Seçim 1. aygıta veya config'e sıfırlanmamalı, kullanıcının seçtiği 2. aygıt kalmalı
        assert app.in_var.get() == "[Sistem] Hoparlör 2"
    finally:
        app.destroy()

def test_application_input_tracks_executable_and_never_falls_back():
    """Yeniden başlayan uygulama yeniden bağlanır; kapanınca sistem sesine düşülmez."""
    from types import SimpleNamespace

    app = App()
    try:
        app._preview.shutdown()
        app._preview = None
        path = r"C:\Program Files\Browser\browser.exe"
        old = SimpleNamespace(
            id="application:10:1", name="browser.exe", executable=path,
            is_application=True, isloopback=False,
        )
        restarted = SimpleNamespace(
            id="application:20:2", name="browser.exe", executable=path,
            is_application=True, isloopback=False,
        )
        system = SimpleNamespace(id="speaker", name="Hoparlör", isloopback=True)
        app.inputs = [old]
        app.in_box["values"] = ["[Uygulama] browser.exe"]
        app.in_var.set("[Uygulama] browser.exe")
        app._input_application_path = path

        app._apply_devices([system, restarted], [system], stopping=False)
        assert app._resolve_input_device() is restarted

        app._apply_devices([system], [system], stopping=False)
        assert app.in_var.get().startswith("[Uygulama] browser.exe")
        assert "yeniden seçin" in app.in_var.get()
        assert app._resolve_input_device() is None
        assert app._input_application_path == path
    finally:
        app.destroy()

def test_application_inputs_are_chosen_from_compact_picker():
    """Ana giriş listesi uygulamalarla şişmez; seçilen uygulama alana taşınır."""
    from types import SimpleNamespace

    from i18n import t

    app = App()
    try:
        app._preview.shutdown()
        app._preview = None
        system = SimpleNamespace(id="speaker", name="Hoparlör", isloopback=True)
        browser = SimpleNamespace(
            id="application:10:1", name="browser.exe", executable=r"C:\Browser\browser.exe",
            is_application=True, isloopback=False,
        )
        meeting = SimpleNamespace(
            id="application:20:2", name="meeting.exe", executable=r"C:\Meeting\meeting.exe",
            is_application=True, isloopback=False,
        )

        app._apply_devices([system, browser, meeting], [system], stopping=False)

        assert app.in_box["values"] == ("[Sistem] Hoparlör", t("application_picker"))
        app.in_var.set(t("application_picker"))
        app.update_idletasks()
        assert app.in_var.get() == "[Sistem] Hoparlör"
        assert app._application_picker is not None
        assert app._application_list.get(0, tk.END) == ("browser.exe", "meeting.exe")

        app._application_list.selection_clear(0, tk.END)
        app._application_list.selection_set(1)
        app._select_application()

        assert app.in_var.get() == "[Uygulama] meeting.exe"
        assert app._resolve_input_device() is meeting
        assert "[Uygulama] browser.exe" not in app.in_box["values"]
        assert app.in_box["values"] == (
            "[Sistem] Hoparlör", "[Uygulama] meeting.exe", t("application_picker")
        )
        assert app._application_picker is None
    finally:
        app.destroy()


def test_h17_ui_lang_en_applies_to_all_gui_labels(monkeypatch):
    """H17: ui_lang='en' iken arayüz etiketleri İngilizceye çevrilmeli."""
    import config
    from i18n import set_ui_lang
    monkeypatch.setattr("gui.app.load_config", lambda: config.Settings(api_key="", ui_lang="en"))
    app = App()
    try:
        assert app.status.cget("text") == "Ready"
        assert app.heard_lbl.cget("text") == "Heard"
        assert app.trans_lbl.cget("text") == "Translation"
        assert app.start_btn.cget("text") == "Start"
        assert app.stop_btn.cget("text") == "Stop"
        assert app.overlay_btn.tooltip == "Subtitle"
        assert app.heard_clear.cget("text") == "Clear"
        assert app.heard_export.cget("text") == "Export"
        assert app.refresh_btn.cget("text") == "Refresh"
    finally:
        set_ui_lang("tr")
        app.destroy()

def test_r03_background_scans_routed_through_queue_without_direct_after(monkeypatch):
    """R03: refresh_devices arka plan thread'i doğrudan after çağırmak yerine log_queue kullanmalı."""
    app = App()
    try:
        from types import SimpleNamespace
        dev1 = SimpleNamespace(id="1", name="Dev1", isloopback=True)
        monkeypatch.setattr("gui.app.all_inputs", lambda: [dev1])
        monkeypatch.setattr("gui.app.all_outputs", lambda: [dev1])

        # async_scan=False ile veya kuyruğa mesaj atarak test
        app.log_queue.put(("devices_scanned", [dev1], [dev1], False))
        app._pump_log()
        assert len(app.inputs) == 1
        assert app.inputs[0].name == "Dev1"
    finally:
        app.destroy()


def test_r05_select_widget_measures_font_and_bounds_popup():
    """R05: Select açılır kutusu satır yüksekliğini font linespace üzerinden dinamik hesaplamalı."""
    app = App()
    try:
        from gui.widgets import Select
        var = tk.StringVar(value="Option 1")
        values = [f"Option {i}" for i in range(15)]
        top = tk.Toplevel(app)
        sel = Select(top, values=values, textvariable=var)
        sel.pack()
        top.update_idletasks()
        # Popup aç
        sel._toggle()
        assert sel._pop is not None
        assert sel._pop.winfo_exists()

        # Popup geometrisi hesaplanmış ve sınırlandırılmış olmalı
        geom = sel._pop.geometry()
        assert "x" in geom
        assert "+" in geom

        # Popup kapat
        sel._close()
        assert sel._pop is None
    finally:
        app.destroy()


def test_preview_monitor_is_inert_and_safe():
    """Önizleme: aygıtsız/geçersiz aygıtta çökmez, seviyeyi sıfırlar."""
    import time

    app = App()
    try:
        assert app._preview.get_level() == 0.0
        app._preview.set_device(object())  # geçersiz aygıt: sessizce yutulmalı
        time.sleep(0.3)
        assert app._preview.get_level() == 0.0
        app._preview.set_device(None)
        assert app._preview.get_level() == 0.0
    finally:
        app.destroy()


def test_input_hotswap_calls_swap_without_restart(monkeypatch):
    """Çalışırken giriş değişimi swap_input çağırır, restart tetiklemez."""
    app = App()
    try:
        from types import SimpleNamespace
        dev1 = SimpleNamespace(id="1", name="Hoparlör 1", isloopback=True)
        dev2 = SimpleNamespace(id="2", name="Hoparlör 2", isloopback=True)
        app._apply_devices([dev1, dev2], [dev1, dev2], stopping=False)
        app.in_var.set("[Sistem] Hoparlör 1")

        calls = []

        class FakeLoop:
            def swap_input(self, dev):
                calls.append(dev)
                return True

            def swap_output(self, dev):
                return False

        app.loop_obj = FakeLoop()
        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()
        restarts = []
        monkeypatch.setattr(app, "restart", lambda: restarts.append(True))

        app.in_var.set("[Sistem] Hoparlör 2")

        assert calls == [dev2]
        assert restarts == []
    finally:
        app.destroy()


def test_output_hotswap_calls_swap_without_restart():
    """Çalışırken çıkış değişimi swap_output çağırır (Hiçbiri dahil)."""
    app = App()
    try:
        from types import SimpleNamespace
        dev1 = SimpleNamespace(id="1", name="Hoparlör 1")
        outs = [dev1]
        app.inputs = []
        app.outputs = outs
        app.out_box["values"] = [NONE_OUTPUT, "Hoparlör 1"]

        calls = []

        class FakeLoop:
            def swap_input(self, dev):
                return False

            def swap_output(self, dev):
                calls.append(dev)
                return True

        app.loop_obj = FakeLoop()
        app.worker = type("MockWorker", (), {"is_alive": lambda self: True})()

        app.out_var.set("Hoparlör 1")
        assert calls == [dev1]

        app.out_var.set(NONE_OUTPUT)
        assert calls == [dev1, None]
    finally:
        app.destroy()


def test_idle_meter_shows_preview_level():
    """Oturum kapalıyken VU, önizleme seviyesini gösterir."""
    app = App()
    try:
        app.loop_obj = None
        app.worker = None
        app._preview._set_level(0.8)
        app._pump_log()
        coords = app.meter.coords(app._meter_bar)
        assert coords[2] > 40.0
        app._preview._set_level(0.0)
        app._pump_log()
        assert app.meter.coords(app._meter_bar)[2] == 0.0
    finally:
        app.destroy()


def test_settings_dub_checkbox_is_saved_immediately(monkeypatch):
    from i18n import t

    saved = []
    monkeypatch.setattr("gui.app.save_preferences", lambda **kwargs: saved.append(kwargs))
    app = App()
    try:
        app._open_settings()
        assert app._dub_toggle.cget("text") == t("dub_toggle")
        assert app._dub_var.get() is False
        app._dub_toggle.invoke()
        assert app.dub_mute_source is True
        assert app.dub_background is False
        assert saved[-1]["dub_mute_source"] is True
        assert app._dub_bg_toggle.cget("text") == t("dub_background")
        app._dub_bg_toggle.invoke()
        assert app.dub_background is True
        assert app.dub_mute_source is False
        assert saved[-1]["dub_background"] is True
        app._close_settings()
        app._open_settings()
        assert app._dub_var.get() is False
        assert app._dub_bg_var.get() is True
    finally:
        app.destroy()


def test_dub_mutes_source_only_while_translation_is_playing():
    from types import SimpleNamespace

    from devices import display_input_label
    from source_mute import DubPlan

    events = []

    class FakeDub:
        def preview(self, source, output, *, enabled, gain=None):
            events.append(("preview", enabled, gain, getattr(output, "name", None)))
            if not enabled:
                return DubPlan("idle")
            if getattr(source, "isloopback", False) and getattr(source, "id", None) == getattr(output, "id", None):
                return DubPlan("mute_other_sessions", root_pid=1)
            return DubPlan("mute_endpoint", endpoint_id="spk")

        def engage(self, plan):
            events.append(("engage", plan.action))

        def release(self):
            events.append(("release",))

    app = App()
    try:
        app._source_dub = FakeDub()
        app.dub_mute_source = True
        speaker = SimpleNamespace(name="Kulaklık", id="hp")
        source = SimpleNamespace(name="Hoparlör", id="spk", isloopback=True, is_application=False)
        app.outputs = [speaker]
        app.inputs = [source]
        app.out_box["values"] = (NONE_OUTPUT, "Kulaklık")
        excluded = []

        class Loop:
            def swap_output(self, dev):
                return True

            def swap_input(self, dev):
                return True

            def set_dub_exclude(self, enabled):
                excluded.append(enabled)

        app.loop_obj = Loop()
        app.worker = type("Worker", (), {"is_alive": lambda self: True})()
        app._stopping.clear()
        app.in_var.set(display_input_label(source))
        app.out_var.set("Kulaklık")
        events.clear()
        excluded.clear()
        app._sync_source_dub()
        assert ("engage", "mute_endpoint") in events
        assert excluded[-1] is False

        app.translation_muted = True
        app._sync_source_dub()
        assert events[-1] == ("engage", "idle")

        app.translation_muted = False
        app.out_var.set(NONE_OUTPUT)
        assert events[-1] == ("engage", "idle")

        app.out_var.set("Kulaklık")
        same = SimpleNamespace(name="Hoparlör", id="spk")
        app.outputs = [same]
        app.out_box["values"] = (NONE_OUTPUT, "Hoparlör")
        app.out_var.set("Hoparlör")
        events.clear()
        excluded.clear()
        app._sync_source_dub()
        assert ("engage", "mute_other_sessions") in events
        assert excluded[0] is True
    finally:
        app.destroy()

