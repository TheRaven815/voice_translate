"""GUI: Başlat, Tkinter'ın __getattr__ tuzakına düşmeden log yazmalı."""

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
        assert coords == [0.0, 0.0, 27.0, 6.0]
        app._update_meter(0.0)
        coords = app.meter.coords(app._meter_bar)
        assert coords == [0.0, 0.0, 0.0, 6.0]
    finally:
        app.destroy()


def test_overlay_toggle_and_live_update():
    app = App()
    try:
        assert app._overlay is None
        app.toggle_overlay()
        assert app._overlay is not None
        assert app._overlay.winfo_exists()

        long_text = (
            "Bu uzun altyazı iki satıra taşsa da hiçbir bölümü kesilmeden "
            "okunabilir kalmalı ve pencere yukarı doğru büyümeli."
        )
        app._write_pane(app.trans, long_text + "\n")
        app.update_idletasks()
        assert app.overlay_label.cget("text") == long_text
        assert app._overlay.winfo_height() >= app._overlay.winfo_reqheight()

        app.toggle_overlay()
        assert app._overlay is None
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
        msg = app.log_queue.get_nowait()
        assert msg == "__stopped__"
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
        assert "__stopped__" in messages
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
        assert app.theme_btn.cget("text") == "☀️"
        assert app.cget("bg") == "#111111"

        app.toggle_theme()
        assert C.current == "light"
        assert app.theme_btn.cget("text") == "🌙"
        assert app.cget("bg") == "#f5f6f8"

        import config
        assert config.load().theme == "light"

        app.toggle_theme()
        assert C.current == "dark"
        assert app.theme_btn.cget("text") == "☀️"
        assert app.cget("bg") == "#111111"
        assert config.load().theme == "dark"
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
        assert app.start_btn._hover_bg == C.fill_hover == "#32383f"
        assert app.start_btn.cget("bg") == C.fill == "#1f2328"
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
        assert coords[3] == 6.0
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

