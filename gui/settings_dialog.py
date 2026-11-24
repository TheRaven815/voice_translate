"""2-sekmeli Ayarlar diyaloğu, kısayol yakalama, API doğrulama ve sıfırlama."""

from __future__ import annotations

import asyncio
import sys
import time
import tkinter as tk
import webbrowser

from config import reset as reset_config, save_api_key
from hotkeys import ShortcutError, parse_shortcut, shortcut_from_tk_event
from i18n import get_ui_lang, set_ui_lang, t
from languages import display_name, lang_code_to_name, src_code_to_name
from logger import clear_history
from source_mute import DUB_BACKGROUND
from .theme import C, apply_icon
from .widgets import CheckToggle, IconButton, LevelSlider


class SettingsDialogMixin:
    """App sınıfı için Ayarlar penceresi ve tercih denetimleri."""

    def _on_dub_toggle(self) -> None:
        if self._dub_var is None:
            return
        if self._dub_var.get() and self._dub_bg_var is not None:
            self._dub_bg_var.set(False)
        self._commit_dub()

    def _on_dub_background(self) -> None:
        if self._dub_bg_var is None:
            return
        if self._dub_bg_var.get() and self._dub_var is not None:
            self._dub_var.set(False)
        self._commit_dub()

    def _commit_dub(self) -> None:
        self.dub_mute_source = bool(self._dub_var.get()) if self._dub_var is not None else False
        self.dub_background = bool(self._dub_bg_var.get()) if self._dub_bg_var is not None else False
        if self.dub_mute_source:
            self.dub_background = False
            if self._dub_bg_var is not None:
                self._dub_bg_var.set(False)
        self._sync_dub_gain_controls()
        try:
            self._deps().save_preferences(
                dub_mute_source=self.dub_mute_source,
                dub_background=self.dub_background,
                dub_background_gain=self._clamp_bed_gain(
                    getattr(self, "dub_background_gain", DUB_BACKGROUND)
                ),
            )
        except OSError as exc:
            self._append(f"[uyarı] {t('dub_failed')}: {exc}\n")
        self._sync_source_dub()

    def _on_dub_ducking_toggle(self) -> None:
        if self._dub_ducking_var is None:
            return
        self.dub_ducking = bool(self._dub_ducking_var.get())
        try:
            self._deps().save_preferences(dub_ducking=self.dub_ducking)
        except OSError as exc:
            self._append(f"[uyarı] {exc}\n")
        self._sync_source_dub()

    def _refresh_overlay_alpha_label(self) -> None:
        lbl = getattr(self, "_overlay_alpha_pct_lbl", None)
        if lbl is None:
            return
        try:
            if lbl.winfo_exists():
                pct = int(round(self._clamp_overlay_alpha(getattr(self, "overlay_alpha", 0.92)) * 100))
                lbl.configure(text=f"{pct}%")
        except tk.TclError:
            pass

    def _apply_overlay_alpha_live(self) -> None:
        if self._overlay is not None and self._overlay.winfo_exists():
            try:
                self._overlay.attributes("-alpha", self.overlay_alpha)
            except tk.TclError:
                pass

    def _on_overlay_alpha_slider(self, value=None) -> None:
        if not getattr(self, "_overlay_alpha_ui", False):
            return
        if value is None and self._overlay_alpha_var is not None:
            value = self._overlay_alpha_var.get()
        try:
            pct = max(20, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            pct = 92
        self.overlay_alpha = pct / 100.0
        self._refresh_overlay_alpha_label()
        self._apply_overlay_alpha_live()
        timer = getattr(self, "_overlay_alpha_timer", None)
        if timer is not None:
            try:
                self.after_cancel(timer)
            except tk.TclError:
                pass
        try:
            self._overlay_alpha_timer = self.after(120, self._commit_overlay_alpha)
        except tk.TclError:
            self._commit_overlay_alpha()

    def _commit_overlay_alpha(self) -> None:
        self._overlay_alpha_timer = None
        alpha = self._clamp_overlay_alpha(getattr(self, "overlay_alpha", 0.92))
        self.overlay_alpha = alpha
        try:
            self._deps().save_preferences(overlay_alpha=alpha)
        except OSError:
            pass

    def _adjust_overlay_alpha(self, delta: float) -> None:
        self.overlay_alpha = self._clamp_overlay_alpha(getattr(self, "overlay_alpha", 0.92) + delta)
        if self._overlay_alpha_var is not None:
            self._overlay_alpha_ui = False
            self._overlay_alpha_var.set(int(round(self.overlay_alpha * 100)))
            self._overlay_alpha_ui = True
        self._refresh_overlay_alpha_label()
        self._apply_overlay_alpha_live()
        self._save_user_prefs()

    def _on_save_history_toggle(self) -> None:
        if self._save_history_var is None:
            return
        enabled = bool(self._save_history_var.get())
        if not enabled and getattr(self, "save_history", False):
            self._flush_history(time.time(), force=True)
        self.save_history = enabled
        self._history_cutoff = time.time()
        self._history_heard.clear()
        self._history_trans.clear()
        try:
            self._deps().save_preferences(save_history=self.save_history)
        except OSError as exc:
            self._append(f"[uyarı] {exc}\n")

    def _clear_history_action(self) -> None:
        parent = self._settings if self._settings is not None and self._settings.winfo_exists() else self
        if not self._deps().messagebox.askyesno(t("clear_history"), t("history_clear_confirm"), parent=parent):
            return
        self._history_cutoff = time.time()
        self._history_heard.clear()
        self._history_trans.clear()
        # Bekleyen yazma, temizlenen dosyayı yeniden oluşturmamalı.
        self._wait_history_writes()
        if clear_history():
            if self._history_status is not None and self._history_status.winfo_exists():
                self._history_status.configure(text=t("history_cleared"), fg=C.live)
            if self._history_win is not None and self._history_win.winfo_exists():
                self._populate_history_window()
        elif self._history_status is not None and self._history_status.winfo_exists():
            self._history_status.configure(text=t("history_clear_failed"), fg=C.warn)

    def _refresh_dub_gain_label(self) -> None:
        label = getattr(self, "_dub_bg_pct_lbl", None)
        if label is None:
            return
        try:
            if not label.winfo_exists():
                return
        except tk.TclError:
            return
        percent = int(round(self._clamp_bed_gain(getattr(self, "dub_background_gain", DUB_BACKGROUND)) * 100))
        label.configure(text=f"{percent}%")

    def _sync_dub_gain_controls(self) -> None:
        enabled = bool(getattr(self, "dub_background", False)) and not bool(
            getattr(self, "dub_mute_source", False)
        )
        scale = getattr(self, "_dub_bg_scale", None)
        if scale is not None:
            try:
                if scale.winfo_exists():
                    scale.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            except tk.TclError:
                pass
        name = getattr(self, "_dub_bg_gain_lbl", None)
        if name is not None:
            try:
                if name.winfo_exists():
                    name.configure(fg=C.muted if enabled else C.dim)
            except tk.TclError:
                pass
        pct = getattr(self, "_dub_bg_pct_lbl", None)
        if pct is not None:
            try:
                if pct.winfo_exists():
                    pct.configure(fg=C.text if enabled else C.dim)
            except tk.TclError:
                pass

    def _style_dub_scale(self) -> None:
        scale = getattr(self, "_dub_bg_scale", None)
        if scale is None:
            return
        try:
            if not scale.winfo_exists():
                return
            scale.configure(bg=C.panel)
        except tk.TclError:
            pass

    def _on_dub_background_gain(self, value=None) -> None:
        if not getattr(self, "_dub_gain_ui", False):
            return
        if value is None and self._dub_bg_gain_var is not None:
            value = self._dub_bg_gain_var.get()
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            percent = int(round(DUB_BACKGROUND * 100))
        percent = max(0, min(100, percent))
        self.dub_background_gain = percent / 100.0
        self._refresh_dub_gain_label()
        timer = getattr(self, "_dub_gain_timer", None)
        if timer is not None:
            try:
                self.after_cancel(timer)
            except tk.TclError:
                pass
        try:
            self._dub_gain_timer = self.after(80, self._commit_dub_gain)
        except tk.TclError:
            self._commit_dub_gain()

    def _commit_dub_gain(self) -> None:
        self._dub_gain_timer = None
        gain = self._clamp_bed_gain(getattr(self, "dub_background_gain", DUB_BACKGROUND))
        self.dub_background_gain = gain
        try:
            self._deps().save_preferences(dub_background_gain=gain)
        except OSError as exc:
            self._append(f"[uyarı] {t('dub_failed')}: {exc}\n")
        if getattr(self, "dub_background", False) and not getattr(self, "dub_mute_source", False):
            self._sync_source_dub()

    def _suspend_global_hotkeys(self) -> None:
        """Kısayol kaydederken mevcut global kayıtlar tuşu yutmasın."""
        if self._hotkeys is None or self._hotkeys_suspended:
            return
        self._hotkeys_suspended = True
        self._hotkeys.replace({})

    def _resume_global_hotkeys(self) -> None:
        if self._hotkeys is None or not self._hotkeys_suspended:
            return
        self._hotkeys_suspended = False
        error = self._restore_global_hotkeys()
        if error and sys.platform == "win32":
            self._append(f"[uyarı] Genel kısayollar etkinleştirilemedi: {error}\n")

    def _on_push_to_talk_toggle(self) -> None:
        if self._push_to_talk_var is None:
            return
        self.push_to_talk = bool(self._push_to_talk_var.get())
        if self._hotkeys is not None and hasattr(self._hotkeys, "set_push_to_talk"):
            self._hotkeys.set_push_to_talk(self.push_to_talk)
        try:
            self._deps().save_preferences(push_to_talk=self.push_to_talk)
        except OSError as exc:
            self._append(f"[uyarı] {exc}\n")
        if (
            self.push_to_talk
            and getattr(self, "pause_shortcut", "").strip()
            and self._worker_alive()
            and not self._stopping.is_set()
            and not self._paused
        ):
            self.pause_translation(quiet_log=True)

    def _capture_shortcut(self, event, variable: tk.StringVar):
        if event.keysym == "Escape":
            return "break"
        if event.keysym in {"BackSpace", "Delete"}:
            variable.set("")
            self._set_shortcut_status(t("shortcut_cleared"), C.dim)
            return "break"
        try:
            shortcut = shortcut_from_tk_event(event)
        except ShortcutError as exc:
            self._set_shortcut_status(str(exc), C.warn)
            return "break"
        if not shortcut:
            return "break"
        variable.set(shortcut)
        all_vars = (
            self._mute_shortcut_var,
            self._start_stop_shortcut_var,
            self._pause_shortcut_var,
        )
        duplicate = any(
            other is not None and other is not variable and other.get().strip() == shortcut
            for other in all_vars
        )
        if duplicate:
            self._set_shortcut_status(t("shortcut_duplicate"), C.warn)
        else:
            self._set_shortcut_status(
                t("shortcut_captured").format(shortcut=shortcut), C.live
            )
        return "break"

    def _save_shortcuts(self, *, report_success: bool = True) -> bool:
        if self._mute_shortcut_var is None or self._start_stop_shortcut_var is None:
            return True
        raw_pause = (
            self._pause_shortcut_var.get()
            if self._pause_shortcut_var is not None
            else getattr(self, "pause_shortcut", "")
        )
        try:
            mute = parse_shortcut(self._mute_shortcut_var.get())[0] if self._mute_shortcut_var.get().strip() else ""
            start_stop = parse_shortcut(self._start_stop_shortcut_var.get())[0] if self._start_stop_shortcut_var.get().strip() else ""
            pause = parse_shortcut(raw_pause)[0] if raw_pause.strip() else ""
        except ShortcutError as exc:
            self._set_shortcut_status(str(exc), C.warn)
            return False
        non_empty = [sc for sc in (mute, start_stop, pause) if sc]
        if len(non_empty) != len(set(non_empty)):
            self._set_shortcut_status(t("shortcut_duplicate"), C.warn)
            return False
        previous = (self.mute_shortcut, self.start_stop_shortcut, self.pause_shortcut)
        self.mute_shortcut, self.start_stop_shortcut, self.pause_shortcut = mute, start_stop, pause
        self._hotkeys_suspended = False
        error = self._restore_global_hotkeys() if (mute, start_stop, pause) == previous else self._register_global_hotkeys()
        if error:
            self.mute_shortcut, self.start_stop_shortcut, self.pause_shortcut = previous
            self._restore_global_hotkeys()
            self._set_shortcut_status(error, C.warn)
            return False
        try:
            self._deps().save_preferences(
                mute_shortcut=mute,
                start_stop_shortcut=start_stop,
                pause_shortcut=pause,
            )
        except OSError as exc:
            self.mute_shortcut, self.start_stop_shortcut, self.pause_shortcut = previous
            self._restore_global_hotkeys()
            self._set_shortcut_status(
                t("shortcut_save_failed").format(error=exc), C.warn
            )
            return False
        self._mute_shortcut_var.set(mute)
        self._start_stop_shortcut_var.set(start_stop)
        if self._pause_shortcut_var is not None:
            self._pause_shortcut_var.set(pause)
        if report_success:
            self._set_shortcut_status(t("shortcuts_saved"), C.live)
        return True

    def _set_shortcut_status(self, text: str, color: str) -> None:
        status = getattr(self, "_shortcut_status", None)
        if status is not None and status.winfo_exists():
            status.configure(text=text, fg=color)

    def _toggle_key_mask(self) -> None:
        if self.key_entry is None or not self.key_entry.winfo_exists():
            return
        if self.key_entry.cget("show") == "•":
            self.key_entry.configure(show="")
            if self.mask_btn is not None and self.mask_btn.winfo_exists():
                self.mask_btn.kind = "eye_off"
                self.mask_btn.redraw()
                self.mask_btn.set_tooltip(t("hide_key", "Gizle"))
        else:
            self.key_entry.configure(show="•")
            if self.mask_btn is not None and self.mask_btn.winfo_exists():
                self.mask_btn.kind = "eye"
                self.mask_btn.redraw()
                self.mask_btn.set_tooltip(t("show_key", "Göster"))

    def _test_api_key(self) -> None:
        deps = self._deps()
        key = self.key_var.get().strip()
        if not key:
            message = t("test_key_empty")
            self._append(f"[hata] {message}\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text=message, fg=C.warn)
            return
        self._append(f"[bilgi] {t('testing_key')}\n")
        if self._settings_status is not None and self._settings_status.winfo_exists():
            self._settings_status.configure(text=t("testing_key"), fg=C.dim)

        def _bg():
            try:
                asyncio.run(deps.validate_live_api_key(key))
                self.log_queue.put(f"[bilgi] {t('key_valid')}\n")
                self.log_queue.put(("key_test_result", True, t("key_valid"), C.live))
            except Exception as e:
                err_msg = deps.format_user_error(e)
                self.log_queue.put(f"[hata] {t('key_test_failed_log').format(error=err_msg)}\n")
                self.log_queue.put(
                    ("key_test_result", False, t("key_invalid").format(error=err_msg), C.warn)
                )

        deps.threading.Thread(target=_bg, daemon=True).start()

    def save_key(self, *, report_success: bool = True) -> bool:
        key = self.key_var.get().strip()
        try:
            save_api_key(key)
        except OSError as e:
            self._append(f"[hata] Anahtar kaydedilemedi: {e}\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(
                    text=t("key_save_failed").format(error=e), fg=C.warn
                )
            return False
        if report_success:
            if key:
                self._append("[bilgi] API anahtarı kaydedildi.\n")
                if self._settings_status is not None and self._settings_status.winfo_exists():
                    self._settings_status.configure(text=t("key_saved"), fg=C.live)
            else:
                self._append("[bilgi] Kayıtlı anahtar silindi.\n")
                if self._settings_status is not None and self._settings_status.winfo_exists():
                    self._settings_status.configure(text=t("key_deleted"), fg=C.dim)
        if self.key_entry is not None and self.key_entry.winfo_exists():
            self.key_entry.selection_clear()
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.focus_set()
        else:
            self.focus_set()
        self._refresh_key_notice()
        return True

    def _show_save_status(self, key: str | None) -> None:
        self._save_status_key = key or None
        label = getattr(self, "_save_status", None)
        if label is None or not label.winfo_exists():
            return
        label.configure(text=t(key) if key else "", fg=C.live)

    def _save_settings(self) -> None:
        self._show_save_status(None)
        if not self._save_shortcuts(report_success=False):
            return
        if not self.save_key(report_success=False):
            return
        glossary_changed = False
        if self._glossary_text is not None and self._glossary_text.winfo_exists():
            new_glossary = self._glossary_text.get("1.0", "end-1c").strip()
            glossary_changed = new_glossary != getattr(self, "glossary", "")
            self.glossary = new_glossary
            try:
                self._deps().save_preferences(glossary=new_glossary)
            except OSError as exc:
                self._append(f"[hata] {exc}\n")
                return
        self._show_save_status("settings_saved")
        if glossary_changed:
            self._on_runtime_pref_change()

    def _open_settings(self):
        if self._settings is not None and self._settings.winfo_exists():
            self._settings.deiconify()
            self._settings.lift()
            self._settings.focus_set()
            return
        self._drain_window_events()
        deps = self._deps()
        pop = deps.tk.Toplevel(self)
        pop.withdraw()
        self._settings = pop
        pop.title(t("settings", "Ayarlar"))
        pop.configure(bg=C.panel)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        deps.dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_settings)
        pop.bind("<Escape>", lambda _e: self._close_settings())

        footer = tk.Frame(pop, bg=C.panel, padx=22, pady=10)
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        host = tk.Frame(pop, bg=C.panel)
        host.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(
            host, bg=C.panel, highlightthickness=0, bd=0, takefocus=0
        )
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = tk.Scrollbar(
            host,
            orient=tk.VERTICAL,
            command=canvas.yview,
            width=10,
            bg=C.panel,
            troughcolor=C.rail,
            activebackground=C.hover,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        canvas.configure(yscrollcommand=scroll.set)
        self._settings_canvas = canvas
        self._settings_scroll = scroll
        main = tk.Frame(canvas, bg=C.panel, padx=22, pady=8)
        main_id = canvas.create_window((0, 0), window=main, anchor="nw")
        main.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>", lambda event: canvas.itemconfigure(main_id, width=event.width)
        )

        def _on_settings_wheel(event):
            if event.widget is getattr(self, "_glossary_text", None):
                return
            if canvas.bbox("all") is None:
                return
            canvas.yview_scroll(int(-event.delta / 120), "units")

        pop.bind("<MouseWheel>", _on_settings_wheel)

        def _dialog_btn(
            parent,
            label: str,
            command,
            *,
            primary: bool = False,
            side: str = tk.LEFT,
            padx: tuple = (0, 0),
        ) -> tk.Button:
            wrap = tk.Frame(parent, bg=C.fill if primary else C.line, bd=0, highlightthickness=0)
            wrap.pack(side=side, padx=padx)
            btn = tk.Button(
                wrap,
                text=label,
                font=self.font_ui,
                bg=C.fill if primary else C.panel,
                fg=C.fill_fg if primary else C.text,
                activebackground=C.fill_hover if primary else C.hover,
                activeforeground=C.fill_fg if primary else C.text,
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=14,
                pady=4,
                cursor="hand2",
                command=command,
            )
            btn.pack(padx=1, pady=1)
            btn._rest_bg = C.fill if primary else C.panel
            btn._hover_bg = C.fill_hover if primary else C.hover
            btn._primary = primary
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=b._hover_bg))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=b._rest_bg))
            return btn

        self._settings_refs = {}
        self._ui_lang_btns = {}
        self._settings_tab_btns = {}

        tab_bar = tk.Frame(main, bg=C.panel)
        tab_bar.pack(fill=tk.X, pady=(0, 6))
        for tab_key, label_key in (("general", "tab_general"), ("translation", "tab_translation")):
            t_btn = tk.Button(
                tab_bar,
                text=t(label_key),
                font=self.font_ui,
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=12,
                pady=3,
                cursor="hand2",
                command=lambda target=tab_key: self._switch_settings_tab(target),
            )
            t_btn.pack(side=tk.LEFT, padx=(0, 6))
            self._settings_tab_btns[tab_key] = t_btn

        tab_general = tk.Frame(main, bg=C.panel)
        tab_translation = tk.Frame(main, bg=C.panel)
        self._settings_tab_frames = {
            "general": tab_general,
            "translation": tab_translation,
        }
        self._settings_active_tab = "general"
        tab_general.pack(fill=tk.X)
        self._style_settings_tabs()

        # -- Sekme 1: Genel ----------------------------------------------
        lang_row = tk.Frame(tab_general, bg=C.panel)
        lang_row.pack(fill=tk.X)
        self._settings_refs["ui_title"] = tk.Label(
            lang_row,
            text=t("ui_language"),
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
            anchor="w",
        )
        self._settings_refs["ui_title"].pack(side=tk.LEFT, expand=True, fill=tk.X)

        for code, label in (("tr", "Türkçe"), ("en", "English")):
            lang_btn = tk.Button(
                lang_row,
                text=label,
                font=self.font_ui,
                relief="flat",
                bd=0,
                highlightthickness=0,
                padx=14,
                pady=3,
                cursor="hand2",
                command=lambda value=code: self._set_ui_language(value),
            )
            lang_btn.pack(side=tk.LEFT, padx=(6, 0))
            self._ui_lang_btns[code] = lang_btn
        self._style_lang_buttons()

        tk.Frame(tab_general, bg=C.line, height=1).pack(fill=tk.X, pady=(6, 5))

        # -- API anahtarı ------------------------------------------------
        sec_h = tk.Frame(tab_general, bg=C.panel)
        sec_h.pack(fill=tk.X, pady=(1, 0))
        self._settings_refs["api_title"] = tk.Label(
            sec_h,
            text=t("api_key_section"),
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
        )
        self._settings_refs["api_title"].pack(side=tk.LEFT)

        link_lbl = tk.Label(
            sec_h, text=t("get_key"), font=self.font_ui, fg=C.dim, bg=C.panel, cursor="hand2"
        )
        link_lbl.pack(side=tk.RIGHT)
        link_lbl.bind("<Button-1>", lambda _e: webbrowser.open("https://aistudio.google.com/apikey"))
        link_lbl.bind("<Enter>", lambda _e: link_lbl.configure(fg=C.text))
        link_lbl.bind("<Leave>", lambda _e: link_lbl.configure(fg=C.dim))
        self._settings_refs["link"] = link_lbl

        key_row = tk.Frame(tab_general, bg=C.panel)
        key_row.pack(fill=tk.X, pady=(6, 0))
        self.key_edge = tk.Frame(key_row, bg=C.line, bd=0, highlightthickness=0)
        self.key_edge.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.key_entry = tk.Entry(
            self.key_edge,
            textvariable=self.key_var,
            show="•",
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            insertbackground=C.text,
            disabledbackground=C.rail,
            disabledforeground=C.dim,
            relief="flat",
            highlightthickness=0,
            bd=0,
        )
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(1, 0), pady=1, ipady=4)
        self.key_entry.bind("<Return>", lambda _e: self.save_key())

        self.mask_btn = IconButton(
            self.key_edge, "eye", self._toggle_key_mask, bg=C.panel,
            tooltip=t("show_key", "Göster"),
        )
        self.mask_btn.pack(side=tk.RIGHT, fill=tk.Y, pady=1, padx=(0, 1))

        running = self.worker is not None and self.worker.is_alive()
        if running:
            self.key_entry.configure(state=tk.DISABLED)

        self._settings_status = tk.Label(
            tab_general, text="", font=self.font_ui, fg=C.dim, bg=C.panel, anchor="w"
        )
        self._settings_status.pack(anchor="w", fill=tk.X, pady=(3, 0))
        tk.Frame(tab_general, bg=C.line, height=1).pack(fill=tk.X, pady=(5, 5))
        self._settings_refs["dub_title"] = tk.Label(
            tab_general, text=t("dub_section"), font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text, bg=C.panel, anchor="w",
        )
        self._settings_refs["dub_title"].pack(fill=tk.X)
        self._settings_refs["dub_desc"] = tk.Label(
            tab_general, text=t("dub_summary"), font=self.font_ui, fg=C.muted, bg=C.panel,
            anchor="w", justify="left", wraplength=440,
        )
        self._settings_refs["dub_desc"].pack(fill=tk.X, pady=(2, 5))
        self._dub_var = tk.BooleanVar(value=bool(self.dub_mute_source))
        self._dub_toggle = CheckToggle(
            tab_general,
            text=t("dub_toggle"),
            variable=self._dub_var,
            command=self._on_dub_toggle,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
        )
        self._dub_toggle.pack(fill=tk.X)
        self._dub_bg_var = tk.BooleanVar(value=bool(self.dub_background) and not self.dub_mute_source)
        self._dub_bg_toggle = CheckToggle(
            tab_general,
            text=t("dub_background"),
            variable=self._dub_bg_var,
            command=self._on_dub_background,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
        )
        self._dub_bg_toggle.pack(fill=tk.X, pady=(2, 0))
        gain_row = tk.Frame(tab_general, bg=C.panel)
        gain_row.pack(fill=tk.X, pady=(4, 0))
        self._dub_bg_gain_lbl = tk.Label(
            gain_row, text=t("dub_background_level"), anchor="w",
            font=self.font_ui, fg=C.muted, bg=C.panel,
        )
        self._dub_bg_gain_lbl.pack(side=tk.LEFT)
        self._settings_refs["dub_level"] = self._dub_bg_gain_lbl
        self._dub_bg_pct_lbl = tk.Label(
            gain_row, text="", width=5, anchor="e",
            font=self.font_ui, fg=C.text, bg=C.panel,
        )
        self._dub_bg_pct_lbl.pack(side=tk.RIGHT)
        percent = int(round(self._clamp_bed_gain(self.dub_background_gain) * 100))
        self._dub_bg_gain_var = tk.IntVar(value=max(0, min(100, percent)))
        self._dub_gain_ui = False
        self._dub_bg_scale = LevelSlider(
            gain_row,
            variable=self._dub_bg_gain_var,
            command=self._on_dub_background_gain,
            from_=0,
            to=100,
            bg=C.panel,
        )
        self._dub_bg_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 8))
        self._style_dub_scale()
        self._refresh_dub_gain_label()
        self._sync_dub_gain_controls()
        self._dub_gain_ui = True
        tk.Frame(tab_general, bg=C.line, height=1).pack(fill=tk.X, pady=(6, 5))
        self._settings_refs["shortcuts_title"] = tk.Label(
            tab_general, text=t("shortcuts"), font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text, bg=C.panel, anchor="w",
        )
        self._settings_refs["shortcuts_title"].pack(fill=tk.X)
        self._settings_refs["shortcuts_title"].pack_configure(pady=(0, 4))

        self._mute_shortcut_var = tk.StringVar(value=self.mute_shortcut)
        self._start_stop_shortcut_var = tk.StringVar(value=self.start_stop_shortcut)
        self._pause_shortcut_var = tk.StringVar(value=getattr(self, "pause_shortcut", ""))
        self._settings_refs["shortcut_labels"] = []

        def _shortcut_row(label_key: str, variable: tk.StringVar) -> tk.Entry:
            row = tk.Frame(tab_general, bg=C.panel)
            row.pack(fill=tk.X, pady=1)
            label = tk.Label(
                row, text=t(label_key), width=25, anchor="w", font=self.font_ui, fg=C.muted,
                bg=C.panel,
            )
            label.pack(side=tk.LEFT)
            self._settings_refs["shortcut_labels"].append((label, label_key))
            edge = tk.Frame(row, bg=C.line)
            edge.pack(side=tk.RIGHT, fill=tk.X, expand=True)
            entry = tk.Entry(
                edge, textvariable=variable, font=self.font_ui, bg=C.panel, fg=C.text,
                insertbackground=C.text, justify=tk.CENTER, relief="flat", bd=0,
                highlightthickness=0, cursor="hand2",
            )
            entry.pack(fill=tk.X, padx=1, pady=1, ipady=2)
            entry.bind("<KeyPress>", lambda event, var=variable: self._capture_shortcut(event, var))
            entry.bind("<FocusIn>", lambda _e: self._suspend_global_hotkeys())
            entry.bind("<FocusOut>", lambda _e: self._resume_global_hotkeys())
            return entry

        self._mute_shortcut_entry = _shortcut_row("mute_shortcut", self._mute_shortcut_var)
        self._start_stop_shortcut_entry = _shortcut_row("start_stop_shortcut", self._start_stop_shortcut_var)
        self._pause_shortcut_entry = _shortcut_row("pause_shortcut", self._pause_shortcut_var)
        self._push_to_talk_var = tk.BooleanVar(value=bool(getattr(self, "push_to_talk", False)))
        self._push_to_talk_toggle = CheckToggle(
            tab_general,
            text=t("push_to_talk_toggle"),
            variable=self._push_to_talk_var,
            command=self._on_push_to_talk_toggle,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
        )
        self._push_to_talk_toggle.pack(fill=tk.X, pady=(3, 0))
        self._shortcut_status = tk.Label(
            tab_general, text=t("shortcut_hint"), font=self.font_ui, fg=C.muted, bg=C.panel, anchor="w",
        )
        self._shortcut_status.pack(fill=tk.X, pady=(2, 0))

        # -- Sekme 2: Ses, Sözlük & Geçmiş -------------------------------
        self._settings_refs["audio_overlay_title"] = tk.Label(
            tab_translation,
            text=t("audio_overlay_section"),
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
            anchor="w",
        )
        self._settings_refs["audio_overlay_title"].pack(fill=tk.X)

        alpha_row = tk.Frame(tab_translation, bg=C.panel)
        alpha_row.pack(fill=tk.X, pady=(5, 0))
        self._settings_refs["opacity_lbl"] = tk.Label(
            alpha_row, text=t("overlay_opacity"), anchor="w",
            font=self.font_ui, fg=C.muted, bg=C.panel,
        )
        self._settings_refs["opacity_lbl"].pack(side=tk.LEFT)
        self._overlay_alpha_pct_lbl = tk.Label(
            alpha_row, text="", width=5, anchor="e",
            font=self.font_ui, fg=C.text, bg=C.panel,
        )
        self._overlay_alpha_pct_lbl.pack(side=tk.RIGHT)
        alpha_pct = max(20, min(100, int(round(self._clamp_overlay_alpha(getattr(self, "overlay_alpha", 0.92)) * 100))))
        self._overlay_alpha_var = tk.IntVar(value=alpha_pct)
        self._overlay_alpha_ui = False
        self._overlay_alpha_scale = LevelSlider(
            alpha_row,
            variable=self._overlay_alpha_var,
            command=self._on_overlay_alpha_slider,
            from_=20,
            to=100,
            bg=C.panel,
        )
        self._overlay_alpha_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 8))
        self._refresh_overlay_alpha_label()
        self._overlay_alpha_ui = True

        self._dub_ducking_var = tk.BooleanVar(value=bool(getattr(self, "dub_ducking", True)))
        self._dub_ducking_toggle = CheckToggle(
            tab_translation,
            text=t("dub_ducking_toggle"),
            variable=self._dub_ducking_var,
            command=self._on_dub_ducking_toggle,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
        )
        self._dub_ducking_toggle.pack(fill=tk.X, pady=(6, 0))

        tk.Frame(tab_translation, bg=C.line, height=1).pack(fill=tk.X, pady=(8, 7))

        self._settings_refs["glossary_title"] = tk.Label(
            tab_translation,
            text=t("glossary_section"),
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
            anchor="w",
        )
        self._settings_refs["glossary_title"].pack(fill=tk.X)
        self._settings_refs["glossary_hint"] = tk.Label(
            tab_translation,
            text=t("glossary_hint"),
            font=self.font_ui,
            fg=C.muted,
            bg=C.panel,
            anchor="w",
            justify="left",
            wraplength=410,
        )
        self._settings_refs["glossary_hint"].pack(fill=tk.X, pady=(2, 5))
        self._glossary_edge = tk.Frame(tab_translation, bg=C.line, bd=0, highlightthickness=0)
        self._glossary_edge.pack(fill=tk.X)
        self._glossary_text = tk.Text(
            self._glossary_edge,
            height=4,
            wrap=tk.WORD,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            insertbackground=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=6,
            pady=4,
            undo=True,
        )
        self._glossary_text.pack(fill=tk.X, padx=1, pady=1)
        if getattr(self, "glossary", ""):
            self._glossary_text.insert("1.0", self.glossary)

        tk.Frame(tab_translation, bg=C.line, height=1).pack(fill=tk.X, pady=(8, 7))

        self._settings_refs["history_title"] = tk.Label(
            tab_translation,
            text=t("history_section"),
            font=(self.font_ui[0], self.font_ui[1], "bold"),
            fg=C.text,
            bg=C.panel,
            anchor="w",
        )
        self._settings_refs["history_title"].pack(fill=tk.X)
        self._settings_refs["history_hint"] = tk.Label(
            tab_translation, text=t("history_hint"), anchor="w", justify="left",
            font=self.font_ui, fg=C.muted, bg=C.panel, wraplength=410,
        )
        self._settings_refs["history_hint"].pack(fill=tk.X, pady=(2, 0))
        self._save_history_var = tk.BooleanVar(value=bool(getattr(self, "save_history", False)))
        self._save_history_toggle = CheckToggle(
            tab_translation,
            text=t("save_history_toggle"),
            variable=self._save_history_var,
            command=self._on_save_history_toggle,
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
        )
        self._save_history_toggle.pack(fill=tk.X, pady=(4, 0))

        hist_actions = tk.Frame(tab_translation, bg=C.panel)
        hist_actions.pack(fill=tk.X, pady=(8, 0))
        self._view_history_btn = _dialog_btn(hist_actions, t("view_history"), self._open_history, side=tk.LEFT)
        self._clear_history_btn = _dialog_btn(
            hist_actions, t("clear_history"), self._clear_history_action, side=tk.LEFT, padx=(8, 0)
        )
        self._history_status = tk.Label(
            tab_translation, text="", font=self.font_ui, fg=C.live, bg=C.panel, anchor="w"
        )
        self._history_status.pack(fill=tk.X, pady=(4, 0))

        btn_row = footer

        self._reset_btn = _dialog_btn(btn_row, t("reset_settings"), self._reset_settings)
        self.test_key_btn = _dialog_btn(key_row, t("test"), self._test_api_key, side=tk.RIGHT, padx=(8, 0))
        self.save_key_btn = _dialog_btn(btn_row, t("save"), self._save_settings, primary=True, side=tk.RIGHT, padx=(8, 0))
        self._save_status = tk.Label(
            btn_row, text="", font=self.font_ui, fg=C.live, bg=C.panel, anchor="w"
        )
        self._save_status.pack(side=tk.LEFT, padx=(10, 0))
        self._save_status_key = None
        self._settings_close_btn = _dialog_btn(
            btn_row, t("close"), self._close_settings, side=tk.RIGHT
        )

        pop.update_idletasks()
        content_w = max(460, main.winfo_reqwidth() + 2, footer.winfo_reqwidth())
        content_h = main.winfo_reqheight()
        footer_h = footer.winfo_reqheight()
        screen_w = pop.winfo_screenwidth()
        screen_h = pop.winfo_screenheight()
        max_h = max(360, screen_h - 140)
        scrolls = content_h + footer_h > max_h
        if scrolls:
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            content_w += 12
        h = min(content_h + footer_h, max_h)
        w = min(content_w, max(320, screen_w - 40))
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        x = max(0, min(x, max(0, screen_w - w)))
        y = max(0, min(y, max(0, screen_h - h - 48)))
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        pop.update_idletasks()
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        self.key_entry.focus_set()

    def _style_settings_tabs(self) -> None:
        active = getattr(self, "_settings_active_tab", "general")
        for key, btn in getattr(self, "_settings_tab_btns", {}).items():
            if not btn.winfo_exists():
                continue
            selected = key == active
            btn._rest_bg = C.fill if selected else C.panel
            btn._hover_bg = C.fill_hover if selected else C.hover
            btn.configure(
                bg=btn._rest_bg,
                fg=C.fill_fg if selected else C.muted,
                activebackground=btn._hover_bg,
                activeforeground=C.fill_fg if selected else C.text,
            )
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=b._hover_bg))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=b._rest_bg))

    def _switch_settings_tab(self, tab: str) -> None:
        frames = getattr(self, "_settings_tab_frames", {})
        if tab not in frames:
            return
        self._settings_active_tab = tab
        for key, frame in frames.items():
            if key != tab and frame.winfo_exists():
                frame.pack_forget()
        target = frames[tab]
        if target.winfo_exists():
            target.pack(fill=tk.X)
        self._style_settings_tabs()
        pop = self._settings
        canvas = self._settings_canvas
        scroll = self._settings_scroll
        if pop is not None and canvas is not None and pop.winfo_exists():
            pop.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(0.0)
            if scroll is not None and scroll.winfo_exists():
                bbox = canvas.bbox("all")
                need_scroll = bool(bbox and (bbox[3] - bbox[1]) > canvas.winfo_height() + 2)
                if need_scroll and scroll.winfo_manager() != "pack":
                    scroll.pack(side=tk.RIGHT, fill=tk.Y)
                elif not need_scroll and scroll.winfo_manager() == "pack":
                    scroll.pack_forget()

    def _style_lang_buttons(self) -> None:
        current = get_ui_lang()
        for code, btn in self._ui_lang_btns.items():
            if not btn.winfo_exists():
                continue
            selected = code == current
            btn._rest_bg = C.fill if selected else C.panel
            btn._hover_bg = C.fill_hover if selected else C.hover
            btn.configure(
                bg=btn._rest_bg,
                fg=C.fill_fg if selected else C.text,
                activebackground=btn._hover_bg,
                activeforeground=C.fill_fg if selected else C.text,
            )
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg=b._hover_bg))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=b._rest_bg))

    def _set_ui_language(self, lang: str) -> None:
        lang = "en" if lang == "en" else "tr"
        if lang == get_ui_lang():
            self._style_lang_buttons()
            return
        set_ui_lang(lang)
        try:
            self._deps().save_preferences(ui_lang=lang)
        except OSError as exc:
            self._append(f"[uyarı] {exc}\n")
        self._retranslate_ui()
        self._retranslate_settings()

    def _retranslate_settings(self) -> None:
        pop = self._settings
        if pop is None or not pop.winfo_exists():
            return
        pop.title(t("settings", "Ayarlar"))
        for tab_key, label_key in (("general", "tab_general"), ("translation", "tab_translation")):
            t_btn = self._settings_tab_btns.get(tab_key)
            if t_btn is not None and t_btn.winfo_exists():
                t_btn.configure(text=t(label_key))
        refs = self._settings_refs
        for key, value in (
            ("ui_title", t("ui_language")),
            ("api_title", t("api_key_section")),
            ("link", t("get_key")),
            ("dub_title", t("dub_section")),
            ("dub_desc", t("dub_summary")),
            ("dub_level", t("dub_background_level")),
            ("shortcuts_title", t("shortcuts")),
            ("audio_overlay_title", t("audio_overlay_section")),
            ("opacity_lbl", t("overlay_opacity")),
            ("glossary_title", t("glossary_section")),
            ("glossary_hint", t("glossary_hint")),
            ("history_title", t("history_section")),
            ("history_hint", t("history_hint")),
        ):
            widget = refs.get(key)
            if widget is not None and widget.winfo_exists():
                widget.configure(text=value)
        for label, key in refs.get("shortcut_labels", []):
            if label.winfo_exists():
                label.configure(text=t(key))
        if self._dub_toggle is not None and self._dub_toggle.winfo_exists():
            self._dub_toggle.configure(text=t("dub_toggle"))
        if self._dub_bg_toggle is not None and self._dub_bg_toggle.winfo_exists():
            self._dub_bg_toggle.configure(text=t("dub_background"))
        if self._dub_ducking_toggle is not None and self._dub_ducking_toggle.winfo_exists():
            self._dub_ducking_toggle.configure(text=t("dub_ducking_toggle"))
        if self._save_history_toggle is not None and self._save_history_toggle.winfo_exists():
            self._save_history_toggle.configure(text=t("save_history_toggle"))
        if self._push_to_talk_toggle is not None and self._push_to_talk_toggle.winfo_exists():
            self._push_to_talk_toggle.configure(text=t("push_to_talk_toggle"))
        if self._shortcut_status is not None and self._shortcut_status.winfo_exists():
            self._shortcut_status.configure(text=t("shortcut_hint"), fg=C.muted)
        for btn, key in (
            (self.test_key_btn, "test"),
            (self.save_key_btn, "save"),
            (self._settings_close_btn, "close"),
            (self._reset_btn, "reset_settings"),
            (self._view_history_btn, "view_history"),
            (self._clear_history_btn, "clear_history"),
        ):
            if btn is not None and btn.winfo_exists():
                btn.configure(text=t(key))
        if self._save_status_key:
            self._show_save_status(self._save_status_key)
        self._style_lang_buttons()
        self._style_settings_tabs()

    def _reset_settings(self) -> None:
        deps = self._deps()
        parent = self._settings if self._settings is not None and self._settings.winfo_exists() else self
        if not deps.messagebox.askyesno(
            t("reset_settings"), t("reset_settings_confirm"), parent=parent
        ):
            return
        try:
            reset_config()
        except OSError as exc:
            message = t("reset_settings_failed").format(error=exc)
            self._append(f"[hata] {message}\n")
            if self._settings_status is not None and self._settings_status.winfo_exists():
                self._settings_status.configure(text=message, fg=C.warn)
            return
        cfg = deps.load_config()
        self._adopt_reset_settings(cfg)
        self._show_save_status("reset_settings_done")
        self._append(f"[bilgi] {t('reset_settings_done')}\n")

    def _adopt_reset_settings(self, cfg) -> None:
        """Sıfırlanan config'i canlı arayüze uygular (API anahtarı korunur)."""
        deps = self._deps()
        self._resetting_settings = True
        try:
            if getattr(self, "_save_prefs_timer", None) is not None:
                try:
                    self.after_cancel(self._save_prefs_timer)
                except Exception:
                    pass
                self._save_prefs_timer = None
            self._cfg = cfg
            self._theme = cfg.theme
            C.apply_theme(cfg.theme)
            deps.dark_titlebar(self, dark=(cfg.theme != "light"))
            set_ui_lang(cfg.ui_lang)
            self.mute_shortcut = cfg.mute_shortcut
            self.start_stop_shortcut = cfg.start_stop_shortcut
            self.pause_shortcut = cfg.pause_shortcut
            self.push_to_talk = bool(getattr(cfg, "push_to_talk", False))
            self.always_on_top = cfg.always_on_top
            self.overlay_font_size = cfg.overlay_font_size
            self.overlay_alpha = cfg.overlay_alpha
            self.overlay_click_through = cfg.overlay_click_through
            self.dub_mute_source = cfg.dub_mute_source
            self.dub_background = cfg.dub_background
            self.dub_background_gain = self._clamp_bed_gain(
                getattr(cfg, "dub_background_gain", DUB_BACKGROUND)
            )
            self.dub_ducking = bool(getattr(cfg, "dub_ducking", True))
            self.glossary = str(getattr(cfg, "glossary", "") or "")
            self.save_history = bool(getattr(cfg, "save_history", False))
            self._history_cutoff = time.time()
            self._history_heard.clear()
            self._history_trans.clear()
            self._input_application_path = cfg.input_application
            try:
                self.attributes("-topmost", self.always_on_top)
            except tk.TclError:
                pass
            if hasattr(self, "pin_btn"):
                self.pin_btn.set_accent(self.always_on_top)
            if self._mute_shortcut_var is not None:
                self._mute_shortcut_var.set(self.mute_shortcut)
            if self._start_stop_shortcut_var is not None:
                self._start_stop_shortcut_var.set(self.start_stop_shortcut)
            if self._pause_shortcut_var is not None:
                self._pause_shortcut_var.set(self.pause_shortcut)
            if self._push_to_talk_var is not None:
                self._push_to_talk_var.set(self.push_to_talk)
            if self._dub_var is not None:
                self._dub_var.set(False)
            if self._dub_bg_var is not None:
                self._dub_bg_var.set(False)
            if self._dub_ducking_var is not None:
                self._dub_ducking_var.set(self.dub_ducking)
            if self._dub_bg_gain_var is not None:
                self._dub_gain_ui = False
                self._dub_bg_gain_var.set(
                    int(round(self._clamp_bed_gain(self.dub_background_gain) * 100))
                )
                self._dub_gain_ui = True
            if self._overlay_alpha_var is not None:
                self._overlay_alpha_ui = False
                self._overlay_alpha_var.set(int(round(self.overlay_alpha * 100)))
                self._overlay_alpha_ui = True
            self._refresh_overlay_alpha_label()
            if self._glossary_text is not None and self._glossary_text.winfo_exists():
                self._glossary_text.delete("1.0", tk.END)
                if self.glossary:
                    self._glossary_text.insert("1.0", self.glossary)
            if self._save_history_var is not None:
                self._save_history_var.set(self.save_history)
            self._refresh_dub_gain_label()
            self._sync_dub_gain_controls()
            self.src_var.set(display_name(src_code_to_name(cfg.src_lang)))
            self.dst_var.set(display_name(lang_code_to_name(cfg.dst_lang)))
            if not self._worker_alive():
                self.in_var.set("")
                self.out_var.set("")
            try:
                self.refresh_devices(async_scan=False)
            except Exception as exc:
                self._append(f"[uyarı] Aygıtlar yenilenemedi: {exc}\n")
            self._hotkeys_suspended = False
            self._restore_global_hotkeys()
            self._refresh_theme()
            self._retranslate_ui()
            self._retranslate_settings()
            self._sync_source_dub()
            if self._overlay is not None and self._overlay.winfo_exists():
                try:
                    self._overlay.attributes("-alpha", self.overlay_alpha)
                    self.overlay_label.configure(
                        font=(self.font_brand[0], self.overlay_font_size, "bold")
                    )
                    self._apply_overlay_click_through()
                except Exception:
                    pass
        finally:
            self._resetting_settings = False
            self._save_user_prefs()

    def _close_settings(self) -> None:
        if self._settings is None:
            return
        self._resume_global_hotkeys()
        for timer_attr, commit_fn in (
            ("_dub_gain_timer", self._commit_dub_gain),
            ("_overlay_alpha_timer", self._commit_overlay_alpha),
        ):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, timer_attr, None)
                commit_fn()
        try:
            self._settings.grab_release()
        except tk.TclError:
            pass
        self._settings.destroy()
        self._settings = None
        self.key_entry = None
        self.mask_btn = None
        self.key_edge = None
        self._settings_status = None
        self._settings_close_btn = None
        self._mute_shortcut_var = None
        self._start_stop_shortcut_var = None
        self._pause_shortcut_var = None
        self._mute_shortcut_entry = None
        self._start_stop_shortcut_entry = None
        self._pause_shortcut_entry = None
        self._push_to_talk_var = None
        self._push_to_talk_toggle = None
        self._shortcut_status = None
        self._dub_var = None
        self._dub_toggle = None
        self._dub_bg_var = None
        self._dub_bg_toggle = None
        self._dub_ducking_var = None
        self._dub_ducking_toggle = None
        self._dub_bg_gain_var = None
        self._dub_bg_scale = None
        self._dub_bg_gain_lbl = None
        self._dub_bg_pct_lbl = None
        self._dub_gain_ui = False
        self._overlay_alpha_var = None
        self._overlay_alpha_scale = None
        self._overlay_alpha_pct_lbl = None
        self._overlay_alpha_ui = False
        self._glossary_edge = None
        self._glossary_text = None
        self._save_history_var = None
        self._save_history_toggle = None
        self._view_history_btn = None
        self._clear_history_btn = None
        self._history_status = None
        self._settings_refs = {}
        self._ui_lang_btns = {}
        self._settings_tab_btns = {}
        self._settings_tab_frames = {}
        self._reset_btn = None
        self._save_status = None
        self._save_status_key = None
        self._settings_canvas = None
        self._settings_scroll = None
        self._refresh_key_notice()
