"""Hakkında, Uygulama Seçici, Konuşma Geçmişi ve Otomatik Güncelleme pencereleri."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk

from devices import device_key, display_input_label
from i18n import t
from logger import load_recent_history
from meta import APP_AUTHOR, APP_TITLE, __version__
from updater import (
    UpdateError,
    UpdateInfo,
    can_self_update,
    check_for_update,
    download_update,
    launch_update_helper,
)
from .theme import ABOUT_LOGO_PNG, C, apply_icon
from .widgets import AppPickerList, TranscriptSearchBar
from .win32 import extract_exe_icon_png


class DialogsMixin:
    """App sınıfı için yan diyaloglar (Uygulama Seçici, Geçmiş, Hakkında, Güncelleme)."""

    def _drain_window_events(self) -> None:
        """Ebeveyn penceredeki bekleyen Unmap/Map olaylarını transient öncesinde boşaltır."""
        try:
            import _tkinter

            flags = _tkinter.DONT_WAIT | _tkinter.WINDOW_EVENTS
            while self.tk.dooneevent(flags):
                pass
        except Exception:
            pass

    # --- Uygulama Seçici (R08 dost adlar + 16x16 ikonlar) -------------------

    def _open_application_picker(self) -> None:
        if self._application_picker is not None and self._application_picker.winfo_exists():
            self._application_picker.deiconify()
            self._application_picker.lift()
            self._application_picker.focus_set()
            return
        self._drain_window_events()
        deps = self._deps()
        pop = deps.tk.Toplevel(self)
        pop.withdraw()
        self._application_picker = pop
        pop.title(t("application_picker_title"))
        pop.configure(bg=C.panel)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        deps.dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_application_picker)
        pop.bind("<Escape>", lambda _e: self._close_application_picker())

        main = tk.Frame(pop, bg=C.panel, padx=18, pady=16)
        main.pack(fill=tk.BOTH, expand=True)
        tk.Label(
            main, text=t("application_picker_title"),
            font=(self.font_ui[0], self.font_ui[1] + 1, "bold"),
            fg=C.text, bg=C.panel, anchor="w",
        ).pack(fill=tk.X)
        tk.Label(
            main, text=t("application_picker_description"), font=self.font_ui,
            fg=C.dim, bg=C.panel, anchor="w", justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(4, 10))

        list_edge = tk.Frame(main, bg=C.line, bd=0, highlightthickness=0)
        list_edge.pack(fill=tk.BOTH, expand=True)
        self._application_list = AppPickerList(
            list_edge,
            height=min(8, max(4, len(self._applications))),
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
            cursor="hand2",
        )
        self._application_list.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._application_list.bind("<Double-Button-1>", lambda _e: self._select_application())
        self._application_list.bind("<Return>", lambda _e: self._select_application())
        self._application_list.bind("<<ListboxSelect>>", lambda _e: self._update_application_select_state())
        self._fill_application_picker(self._applications)

        actions = tk.Frame(main, bg=C.panel)
        actions.pack(fill=tk.X, pady=(12, 0))
        refresh = tk.Button(
            actions, text=t("refresh"), command=self._refresh_application_picker,
            font=self.font_ui, bg=C.panel, fg=C.text,
            activebackground=C.hover, activeforeground=C.text,
            relief="flat", bd=0, highlightthickness=0, padx=8, pady=5,
            cursor="hand2", takefocus=1,
        )
        refresh.pack(side=tk.LEFT)
        cancel = tk.Button(
            actions, text=t("cancel"), command=self._close_application_picker,
            font=self.font_ui, bg=C.panel, fg=C.text,
            activebackground=C.hover, activeforeground=C.text,
            relief="flat", bd=0, highlightthickness=0, padx=12, pady=5,
            cursor="hand2", takefocus=1,
        )
        cancel.pack(side=tk.RIGHT, padx=(8, 0))
        self._application_select_btn = tk.Button(
            actions, text=t("application_picker_select"), command=self._select_application,
            font=self.font_ui, bg=C.disabled_bg, fg=C.dim,
            activebackground=C.disabled_bg, activeforeground=C.dim,
            disabledforeground=C.dim, relief="flat", bd=0, highlightthickness=0,
            padx=14, pady=5, cursor="arrow", takefocus=1, state=tk.DISABLED,
        )
        self._application_select_btn.pack(side=tk.RIGHT)

        pop.update_idletasks()
        w, h = max(360, pop.winfo_reqwidth()), pop.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        if self._application_list.size() and self._application_picker_sources:
            current = self._resolve_input_device()
            index = next(
                (i for i, source in enumerate(self._application_picker_sources)
                 if device_key(source) == device_key(current)), 0,
            )
            self._application_list.selection_set(index)
            self._application_list.activate(index)
            self._application_list.see(index)
            self._update_application_select_state()
            self._application_list.focus_set()
        else:
            cancel.focus_set()

    def _fill_application_picker(self, sources) -> None:
        if self._application_list is None:
            return
        self._application_picker_sources = list(sources)
        self._application_list.delete(0, tk.END)
        if not self._application_picker_sources:
            self._application_list.insert(tk.END, t("application_picker_empty"))
            self._application_list.configure(state=tk.DISABLED, fg=C.dim)
            self._update_application_select_state()
            return
        self._application_list.configure(state=tk.NORMAL, fg=C.text)
        for source in self._application_picker_sources:
            exe_path = getattr(source, "executable", "") or ""
            png_bytes = extract_exe_icon_png(exe_path) if exe_path else None
            self._application_list.insert_with_icon(str(source.name), png_bytes)

    def _refresh_application_picker(self) -> None:
        deps = self._deps()
        try:
            self._applications = deps.application_inputs()
            physical = [source for source in self.inputs if not getattr(source, "is_application", False)]
            self.inputs = physical + self._applications
            self._fill_application_picker(self._applications)
            if self._application_list is not None and self._applications:
                self._application_list.selection_set(0)
                self._application_list.activate(0)
        except OSError as err:
            self._append(f"[hata] {deps.format_user_error(err)}\n")
        self._update_application_select_state()

    def _update_application_select_state(self) -> None:
        if self._application_select_btn is None:
            return
        selected = bool(
            self._application_list is not None
            and self._application_list.curselection()
            and self._application_picker_sources
        )
        self._application_select_btn.configure(
            state=tk.NORMAL if selected else tk.DISABLED,
            bg=C.fill if selected else C.disabled_bg,
            fg=C.fill_fg if selected else C.dim,
            activebackground=C.fill_hover if selected else C.disabled_bg,
            activeforeground=C.fill_fg if selected else C.dim,
            cursor="hand2" if selected else "arrow",
        )

    def _select_application(self) -> None:
        if self._application_list is None or not self._application_list.curselection():
            return
        index = self._application_list.curselection()[0]
        if index >= len(self._application_picker_sources):
            return
        source = self._application_picker_sources[index]
        self.in_box["values"] = self._visible_input_values(source)
        self.in_var.set(display_input_label(source))
        self._close_application_picker()

    def _close_application_picker(self) -> None:
        pop, self._application_picker = self._application_picker, None
        self._application_list = None
        self._application_select_btn = None
        self._application_picker_sources = []
        if pop is None:
            return
        try:
            pop.grab_release()
        except tk.TclError:
            pass
        try:
            pop.destroy()
        except tk.TclError:
            pass

    # --- Hakkında & Otomatik Güncelleme -------------------------------------

    def _show_update_chip(self, version: str) -> None:
        chip = getattr(self, "_update_chip", None)
        if chip is None:
            return
        chip.configure(text=t("update_available").format(version=version), fg=C.live, bg=C.rail)
        if chip.winfo_manager() != "pack":
            chip.pack(anchor="w", fill=tk.X, pady=(6, 0), before=self._rail_actions)

    def _on_update_chip(self) -> None:
        info = self._update_info
        if info is None or self._update_installing:
            return
        install = self._deps().messagebox.askyesno(
            t("update_dialog_title"),
            t("update_prompt").format(version=info.version),
            parent=self,
        )
        if install:
            self._download_and_install_update(info)

    def _paint_download_progress(self, fraction: float) -> None:
        frac = max(0.0, min(1.0, fraction))
        self._download_fraction = frac
        pct = int(round(frac * 100))
        if hasattr(self, "timer_lbl"):
            self.timer_lbl.configure(text=f"{pct}%")
        self._update_meter(frac, fill=C.warn)

    def _clear_download_progress(self) -> None:
        self._download_fraction = None
        if hasattr(self, "timer_lbl") and not (
            self.worker is not None and self.worker.is_alive() and self.session_start_time
        ):
            self.timer_lbl.configure(text="")
        if hasattr(self, "meter"):
            self.meter.itemconfigure(self._meter_bar, fill=C.live)

    def _check_for_updates(self, manual: bool = False) -> None:
        deps = self._deps()
        if self._update_check_running or self._update_installing:
            if manual:
                deps.messagebox.showinfo(t("update_title_short"), t("update_already_running"), parent=self)
            return
        if not can_self_update():
            if manual:
                deps.messagebox.showinfo(
                    t("update_title_short"),
                    t("update_onefile_only"),
                    parent=self,
                )
            return
        self._update_check_running = True
        if manual and not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Güncelleme denetleniyor", C.warn)

        def check() -> None:
            try:
                self.log_queue.put(("update_result", check_for_update(), manual))
            except UpdateError as exc:
                self.log_queue.put(("update_error", str(exc), manual))
            except Exception as exc:
                deps.log_exception(exc, "Update check error")
                self.log_queue.put(("update_error", "Beklenmeyen güncelleme denetimi hatası.", manual))

        deps.threading.Thread(target=check, name="update-check", daemon=True).start()

    def _handle_update_result(self, info: UpdateInfo | None, *, manual: bool) -> None:
        deps = self._deps()
        self._update_check_running = False
        self._update_info = info
        if info is None:
            if manual:
                deps.messagebox.showinfo(
                    t("update_title_short"),
                    t("update_up_to_date").format(version=__version__),
                    parent=self,
                )
            if not (self.worker is not None and self.worker.is_alive()):
                self._set_status("Hazır", C.dim)
            return
        self.version_lbl.configure(text=f"v{__version__}", fg=C.dim)
        self._show_update_chip(info.version)
        if hasattr(self, "about_update_status") and self.about_update_status.winfo_exists():
            self.about_update_status.configure(
                text=t("update_ready_status").format(version=info.version), fg=C.live
            )
        install = deps.messagebox.askyesno(
            t("update_dialog_title"),
            t("update_prompt").format(version=info.version),
            parent=self,
        )
        if install:
            self._download_and_install_update(info)
        elif not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Hazır", C.dim)

    def _handle_update_error(self, error: str, *, manual: bool) -> None:
        self._update_check_running = False
        self._update_installing = False
        self._clear_download_progress()
        self._append(f"[hata] {t('update_title_short')}: {error}\n")
        if not (self.worker is not None and self.worker.is_alive()):
            self._set_status("Hazır", C.dim)
        if manual:
            self._deps().messagebox.showerror(t("update_check_failed_title"), error, parent=self)

    def _download_and_install_update(self, info: UpdateInfo) -> None:
        if self._update_installing:
            return
        deps = self._deps()
        self._update_installing = True
        self._paint_download_progress(0.0)
        self._set_status("Güncelleme indiriliyor", C.warn)
        self._append(f"[bilgi] {t('update_downloading_log').format(version=info.version)}\n")

        def on_progress(got: int, total: int) -> None:
            frac = 0.0 if total <= 0 else min(1.0, got / total)
            self.log_queue.put(("update_progress", frac, total))

        def download() -> None:
            try:
                staged = download_update(info, on_progress=on_progress)
                self.log_queue.put(("update_ready", staged, info))
            except UpdateError as exc:
                self.log_queue.put(("update_error", str(exc), True))
            except Exception as exc:
                deps.log_exception(exc, "Update download error")
                self.log_queue.put(("update_error", "Beklenmeyen güncelleme indirme hatası.", True))

        deps.threading.Thread(target=download, name="update-download", daemon=True).start()

    def _apply_downloaded_update(self, staged: Path, info: UpdateInfo) -> None:
        try:
            launch_update_helper(staged, info)
        except UpdateError as exc:
            self._handle_update_error(str(exc), manual=True)
            return
        self._paint_download_progress(1.0)
        self._append(f"[bilgi] {t('update_verified_restarting')}\n")
        self._set_status("Güncelleme kuruluyor", C.warn)
        self.after(100, self._on_close)

    def _open_about(self):
        if self._about is not None and self._about.winfo_exists():
            self._about.deiconify()
            self._about.lift()
            self._about.focus_set()
            return
        self._drain_window_events()
        deps = self._deps()
        pop = deps.tk.Toplevel(self)
        pop.withdraw()
        self._about = pop
        pop.title(t("about"))
        pop.configure(bg=C.panel)
        pop.resizable(False, False)
        pop.transient(self)
        apply_icon(pop)
        deps.dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_about)
        for key in ("<Escape>", "<Return>", "<KP_Enter>", "<space>"):
            pop.bind(key, lambda _e: self._close_about())

        main = tk.Frame(pop, bg=C.panel, padx=20, pady=16)
        main.pack(fill=tk.BOTH, expand=True)

        header = tk.Frame(main, bg=C.panel)
        header.pack(fill=tk.X)

        if ABOUT_LOGO_PNG.is_file():
            try:
                logo_img = tk.PhotoImage(file=str(ABOUT_LOGO_PNG))
                logo = tk.Label(header, image=logo_img, bg=C.panel)
                logo.image = logo_img
                logo.pack(side=tk.LEFT, padx=(0, 14), anchor="n")
            except Exception:
                pass

        info = tk.Frame(header, bg=C.panel)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_row = tk.Frame(info, bg=C.panel)
        title_row.pack(anchor="w")

        self.about_name = tk.Label(
            title_row,
            text=APP_TITLE,
            font=(self.font_brand[0], 12, "bold"),
            fg=C.text,
            bg=C.panel,
        )
        self.about_name.pack(side=tk.LEFT)

        self.about_version = tk.Label(
            title_row,
            text=f"v{__version__}",
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_version.pack(side=tk.LEFT, padx=(6, 0))

        desc = tk.Label(
            info,
            text=t("about_tagline"),
            font=self.font_ui,
            fg=C.muted,
            bg=C.panel,
        )
        desc.pack(anchor="w", pady=(3, 0))
        self.about_tagline = desc
        self.about_update_status = tk.Label(
            info,
            text=t("update_auto_status") if can_self_update() else t("source_mode_status"),
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_update_status.pack(anchor="w", pady=(5, 0))

        div = tk.Frame(main, bg=C.line, height=1)
        div.pack(fill=tk.X, pady=(14, 12))

        bottom = tk.Frame(main, bg=C.panel)
        bottom.pack(fill=tk.X)

        self.about_author = tk.Label(
            bottom,
            text=APP_AUTHOR,
            font=self.font_ui,
            fg=C.dim,
            bg=C.panel,
        )
        self.about_author.pack(side=tk.LEFT)
        self.about_update_btn = tk.Button(
            bottom,
            text=t("check_updates"),
            command=lambda: self._check_for_updates(manual=True),
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=8,
            pady=3,
            cursor="hand2",
        )
        self.about_update_btn.pack(side=tk.LEFT, padx=(12, 0))

        btn_wrap = tk.Frame(bottom, bg=C.line, bd=0, highlightthickness=0)
        btn_wrap.pack(side=tk.RIGHT)
        btn = tk.Button(
            btn_wrap,
            text=t("ok"),
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=16,
            pady=3,
            cursor="hand2",
            takefocus=0,
            command=self._close_about,
        )
        btn.pack(padx=1, pady=1)
        self.about_ok_btn = btn
        btn.bind("<Enter>", lambda _e: btn.configure(bg=C.hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=C.panel))

        pop.update_idletasks()
        w = max(290, pop.winfo_reqwidth())
        h = pop.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        pop.focus_set()

    def _close_about(self) -> None:
        if self._about is None:
            return
        try:
            self._about.grab_release()
        except tk.TclError:
            pass
        self._about.destroy()
        self._about = None

    # --- Konuşma Geçmişi (History) ------------------------------------------

    def _open_history(self) -> None:
        if self._history_win is not None and self._history_win.winfo_exists():
            self._populate_history_window()
            self._history_win.deiconify()
            self._history_win.lift()
            self._history_win.focus_set()
            return
        self._drain_window_events()
        deps = self._deps()
        parent = self._settings if (self._settings is not None and self._settings.winfo_exists()) else self
        pop = deps.tk.Toplevel(self)
        pop.withdraw()
        self._history_win = pop
        pop.title(t("history_title"))
        pop.configure(bg=C.panel)
        pop.resizable(True, True)
        pop.transient(parent)
        apply_icon(pop)
        deps.dark_titlebar(pop, dark=(self._theme != "light"))
        pop.protocol("WM_DELETE_WINDOW", self._close_history)
        pop.bind("<Escape>", self._on_history_escape)
        pop.bind("<Control-f>", self._toggle_history_find_bar)
        pop.bind("<Control-F>", self._toggle_history_find_bar)

        main = tk.Frame(pop, bg=C.panel, padx=18, pady=14)
        main.pack(fill=tk.BOTH, expand=True)

        text_edge = tk.Frame(main, bg=C.line, bd=0, highlightthickness=0)
        self._history_find_bar = TranscriptSearchBar(
            main,
            get_targets=lambda: (getattr(self, "_history_text", None),),
            font=self.font_ui,
            on_show=lambda edge=text_edge: (
                self._history_find_bar.pack(fill=tk.X, pady=(0, 8), before=edge)
                if self._history_find_bar is not None and not self._history_find_bar.winfo_manager()
                else None
            ),
            on_hide=self._on_history_find_hide,
            label_text=t("find_placeholder"),
            close_tip=t("close"),
        )
        text_edge.pack(fill=tk.BOTH, expand=True)
        txt = tk.Text(
            text_edge,
            wrap=tk.WORD,
            font=self.font_body,
            bg=C.bg,
            fg=C.text,
            insertbackground=C.text,
            selectbackground=C.select,
            selectforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=10,
        )
        h_scroll = tk.Scrollbar(
            text_edge,
            orient=tk.VERTICAL,
            command=txt.yview,
            width=10,
            bg=C.panel,
            troughcolor=C.rail,
            activebackground=C.hover,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        txt.configure(yscrollcommand=h_scroll.set)
        h_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(1, 0), pady=1)
        txt.tag_configure("meta", foreground=C.dim, font=self.font_log)
        txt.tag_configure("heard", foreground=C.muted)
        txt.tag_configure("trans", foreground=C.text)
        TranscriptSearchBar.style_text_tags(txt)
        self._lock_text(txt)
        self._history_text = txt

        bottom = tk.Frame(main, bg=C.panel)
        bottom.pack(fill=tk.X, pady=(10, 0))
        close_wrap = tk.Frame(bottom, bg=C.line, bd=0, highlightthickness=0)
        close_wrap.pack(side=tk.RIGHT)
        self._history_close_btn = tk.Button(
            close_wrap,
            text=t("close"),
            font=self.font_ui,
            bg=C.panel,
            fg=C.text,
            activebackground=C.hover,
            activeforeground=C.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=14,
            pady=4,
            cursor="hand2",
            command=self._close_history,
        )
        self._history_close_btn.pack(padx=1, pady=1)

        self._populate_history_window()

        pop.update_idletasks()
        w, h = 560, 420
        screen_w = pop.winfo_screenwidth()
        screen_h = pop.winfo_screenheight()
        w = min(w, max(340, screen_w - 40))
        h = min(h, max(260, screen_h - 80))
        x = max(0, min(self.winfo_rootx() + (self.winfo_width() - w) // 2, max(0, screen_w - w)))
        y = max(0, min(self.winfo_rooty() + (self.winfo_height() - h) // 2, max(0, screen_h - h - 48)))
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        pop.update_idletasks()
        try:
            pop.grab_set()
        except tk.TclError:
            pass
        pop.focus_set()

    def _populate_history_window(self) -> None:
        txt = getattr(self, "_history_text", None)
        if txt is None or not txt.winfo_exists():
            return
        txt.delete("1.0", tk.END)
        records = load_recent_history(limit=100)
        if not records:
            txt.insert(tk.END, t("history_empty"), ("meta",))
            return
        for idx, rec in enumerate(records):
            if idx > 0:
                txt.insert(tk.END, "\n")
            raw_ts = str(rec.get("timestamp", "")).replace("T", " ")
            if "." in raw_ts:
                raw_ts = raw_ts.split(".", 1)[0]
            src_c = rec.get("src", "auto")
            dst_c = rec.get("dst", "")
            txt.insert(tk.END, f"[{raw_ts}]  ({src_c} → {dst_c})\n", ("meta",))
            heard_line = str(rec.get("heard", "")).strip()
            trans_line = str(rec.get("trans", "")).strip()
            if heard_line:
                txt.insert(tk.END, f"• {heard_line}\n", ("heard",))
            if trans_line:
                txt.insert(tk.END, f"→ {trans_line}\n", ("trans",))
        txt.see(tk.END)
        if self._history_find_bar is not None and self._history_find_bar.is_open:
            self._history_find_bar.refresh(scroll=False)

    def _toggle_history_find_bar(self, _event=None):
        if self._history_find_bar is None or not self._history_find_bar.winfo_exists():
            return None
        return self._history_find_bar.toggle()

    def _on_history_find_hide(self) -> None:
        if self._history_find_bar is not None and self._history_find_bar.winfo_exists():
            self._history_find_bar.pack_forget()
        if self._history_win is not None and self._history_win.winfo_exists():
            try:
                self._history_win.focus_set()
            except tk.TclError:
                pass

    def _on_history_escape(self, _event=None):
        if self._history_find_bar is not None and self._history_find_bar.is_open:
            return self._history_find_bar.close()
        self._close_history()
        return "break"

    def _close_history(self) -> None:
        pop, self._history_win = self._history_win, None
        self._history_text = None
        self._history_find_bar = None
        self._history_close_btn = None
        if pop is None:
            return
        try:
            pop.grab_release()
        except tk.TclError:
            pass
        try:
            pop.destroy()
        except tk.TclError:
            pass
        if self._settings is not None and self._settings.winfo_exists():
            try:
                self._settings.grab_set()
                self._settings.focus_set()
            except tk.TclError:
                pass
