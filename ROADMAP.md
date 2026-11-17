# Ahenk — Remaining Feature & Optimization Roadmap

**Document Date:** November 2026  
**Baseline:** Post-Phase-1 (`v0.7.6+` working tree, 245 passing unit/GUI/CLI tests)  
**Scope:** Detailed technical specification for the **13 remaining backlog items** identified during the full-repository architecture, UX, audio-pipeline, and packaging audit.

---

## Background: Completed in Phase 1

For context, the first wave of high-priority improvements has already been implemented and verified:
- **GUI & CLI Exposure of Core Controls:** Two-tab Settings dialog (`General` and `Audio, Glossary & History`), live translation volume slider (`0%–200%`), live subtitle opacity slider (`20%–100%` + `Ctrl+MouseWheel`), custom glossary (`glossary`, `--glossary`, `--prompt`), conversation history viewer/clear/toggle, and off-thread history writing with accurate utterance pairing.
- **Automatic Microphone Sample-Rate & Channel Fallback:** `open_capture_recorder` (`48000 → 44100 → 32000 → 24000 → 16000 Hz`, stereo → mono) across both live capture and idle VU preview.
- **Dynamic Dubbing (Audio Ducking):** Speech-gated source attenuation (`is_playing_audio` + `playback_active` transitions with `400 ms` hold-off) while keeping `set_dub_exclude(True)` steady across the session.
- **Zero-Tkinter CLI & Shared Reconnection Layer:** Extracted `reconnect.py`, removed `gui`/`tkinter` imports and PyInstaller bundle bloat from `Ahenk-cli`, and enabled automatic CLI session recovery.
- **Overlay, SRT & Localization Polish:** Cached `tkfont.Font` on the subtitle overlay, deduplicated `WinDLL("user32")` bindings via `_win32_gui_apis`, skipped redundant FIR work during echo suppression, prevented SRT cue timestamp overlaps using real utterance durations, and completed missing English (`en`) UI/error strings.

---

## Overview Matrix of Remaining Items

| ID | Title | Category | Impact | Effort | Primary Files |
|---|---|---|---|---|---|
| **R01** | Live Pause / Resume & Push-to-Talk | Ready Backend → GUI | High | Low | `loop.py`, `gui/app.py`, `hotkeys.py`, `config.py` |
| **R02** | GUI Controls for `vad_threshold` & `system_instruction` | Ready Backend → GUI | Medium-High | Low | `loop.py`, `config.py`, `gui/app.py`, `i18n.py` |
| **R03** | System Tray Mode & Context Menu | Product Feature | High | Medium | `notifications.py`, `gui/app.py`, `config.py`, `i18n.py` |
| **R04** | Transcript Auto-Scroll Lock & Search (`Ctrl+F`) | Product Feature | High | Low-Medium | `gui/app.py`, `gui/widgets.py`, `i18n.py` |
| **R05** | Output Voice Character (`voice_name`) Selection | Product Feature | Medium-High | Low-Medium | `loop.py`, `config.py`, `cli.py`, `gui/app.py` |
| **R06** | Bilingual Subtitles (`.srt`) & WebVTT (`.vtt`) Export | Product Feature | Medium | Low | `export.py`, `gui/app.py`, `i18n.py` |
| **R07** | CLI Feature Parity (`--app`, `--dub`) & Two-Way Meeting Mode | Product Feature | High | Medium-High | `cli.py`, `applications.py`, `source_mute.py`, `loop.py` |
| **R08** | Friendly App Names (`FileDescription`) & Icons in Picker | UX Polish | Medium | Medium | `applications.py`, `gui/app.py` |
| **R09** | Event-Driven Overlay Hover (Conditional `50 ms` Polling) | Performance | Low-Medium | Low | `gui/app.py` |
| **R10** | `SourceDub` Background Watcher Optimization | Performance | Medium | Low-Medium | `source_mute.py` |
| **R11** | Bounded Transcript Buffers & Zero-Copy `AudioConverter` | Performance & Memory | Medium | Medium | `gui/app.py`, `audio.py`, `loop.py` |
| **R12** | Modularize `gui/app.py` into Focused Submodules | Architecture | High | Medium-High | `gui/app.py`, `gui/settings.py`, `gui/overlay.py`, `gui/dialogs.py` |
| **R13** | Documentation Sync (`README`), CI Matrix & Release Signing | Docs, CI & Packaging | Medium | Low | `README.md`, `README.en.md`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` |

---

## 1. Existing Backend Capabilities Not Yet Exposed in GUI

### R01 — Live Pause / Resume (`pause` / `resume`) & Push-to-Talk

#### Current State & Evidence
- `SystemAudioLoop` in `loop.py` (lines `524–533`) already implements `pause()`, `resume()`, and the `is_paused` property backed by `self._paused = threading.Event()`.
- When `_paused` is set, `_capture_inner` stops forwarding audio frames to Gemini Live **without tearing down** the active WebSocket session, WASAPI capture stream, or playback thread (`tests/test_live_translate.py::test_pause_resume_and_volume_controls`).
- In `gui/app.py`, the user only has **Start** and **Stop**, which tears down the entire Gemini Live connection and COM audio streams and requires a full handshake to resume.

#### Proposed Design & Implementation
1. **Rail Control:** Add a compact **Pause / Resume** button (or convert the secondary action state while running) in `_btns_frame` (`gui/app.py:724–730`), updating the status indicator to `Paused` (`Duraklatıldı` / `Paused` in `i18n.py`) with `C.warn` dot color.
2. **Global Hotkey & Push-to-Talk:**
   - Extend `Settings` (`config.py`) with `pause_shortcut: str = ""` and `push_to_talk: bool = False`.
   - Register `"pause"` in `GlobalHotkeys` (`hotkeys.py` and `gui/app.py:_register_global_hotkeys`).
   - When `paused` is active, force `_sync_source_dub` to release source attenuation (`idle`) so original desktop audio returns to 100% immediately while paused.
3. **Reconnect Preservation:** Preserve `is_paused` across `clone_loop_for_retry` in `reconnect.py` so a background socket renewal does not unexpectedly unpause a paused microphone.

#### Verification Plan
- Unit tests verifying `App` pause/resume state transitions, status badge localization (`tr`/`en`), global hotkey dispatch, dubbing release while paused, and state preservation across `clone_loop_for_retry`.

---

### R02 — GUI Controls for Noise Gate (`vad_threshold`) & Custom System Instruction (`system_instruction`)

#### Current State & Evidence
- `SystemAudioLoop.__init__` accepts `vad_threshold: float = 0.0` (used as an RMS noise gate in `_capture_inner` before sending PCM frames) and `system_instruction: str | None = None` (`loop.py:375–420`).
- `cli.py` exposes both via `--vad` and `--prompt`, but desktop GUI users have no way to configure them in `config.json` or the Settings dialog.
- Users with noisy mechanical keyboards, fans, or open-back headphones benefit heavily from a configurable RMS gate on physical microphones, while domain users (legal, medical, gaming, lectures) benefit from persistent tone/context instructions (e.g., *"Translate formally and keep code identifiers untranslated"*).

#### Proposed Design & Implementation
1. **Configuration (`config.py`):**
   - Add `vad_threshold: float = 0.0` (clamped `0.0–0.05`) and `system_instruction: str = ""` to `Settings`, `load()`, `save()`, `save_preferences()`, and `reset()`.
2. **GUI (`gui/app.py` — Tab 2 `Audio, Glossary & History`):**
   - Add a **Microphone Noise Gate** `LevelSlider` (`0%–100%` mapped non-linearly to `0.0–0.03` RMS, with live visual feedback against the current input meter) and live update support (`loop_obj.vad_threshold = ...`).
   - Add a compact 2-line **Translation Style / Context** input above or alongside the Custom Glossary box; trigger `_on_runtime_pref_change()` on save when modified during an active session.

#### Verification Plan
- Config round-trip + malformed/NaN fallback tests in `tests/test_config.py`.
- GUI tests verifying live `vad_threshold` mutation without session restart and `system_instruction` propagation to `SystemAudioLoop` on `start()` / `restart()`.

---

## 2. New Product Features

### R03 — System Tray Mode & Quick-Action Context Menu

#### Current State & Evidence
- `notifications.py` (`lines 17–72`) already defines `_NOTIFYICONDATAW` and wraps Win32 `Shell_NotifyIconW` (`NIM_ADD`, `NIM_MODIFY`, `NIM_DELETE`) to display connection-failure balloon notifications.
- Users watching fullscreen movies, lectures, or playing games with the floating **Subtitle Overlay** enabled currently have to keep the main Ahenk window on the taskbar; closing the main window terminates translation.

#### Proposed Design & Implementation
1. **Tray Controller (`tray.py` or extended `notifications.py`):**
   - Register a custom `uCallbackMessage` (`WM_APP + 1`) on a dedicated hidden message window or the root HWND subclass/message pump, using `assets/ahenk.ico` via `LoadImageW(..., IMAGE_ICON, ..., LR_LOADFROMFILE)`.
   - Handle `WM_LBUTTONUP` / `WM_LBUTTONDBLCLK` (toggle/restore main window via `_raise_existing_window`) and `WM_RBUTTONUP` (open a native Win32 `CreatePopupMenu` / `TrackPopupMenu` or themed Tk popup).
2. **Tray Menu Actions:**
   - *Show / Hide Ahenk*
   - *Start / Stop Translation* (reflecting live state)
   - *Toggle Subtitle Overlay*
   - *Mute / Unmute Translation Audio*
   - *Quit Ahenk* (explicit full exit)
3. **Preference (`config.py`):**
   - Add `minimize_to_tray: bool = False` toggle in Settings (`General` tab). When enabled, `WM_DELETE_WINDOW` withdraws the main window to the tray (showing a one-time hint balloon) while keeping the subtitle overlay and audio loop running; *Quit* from the tray menu performs full `_on_close()`.

#### Verification Plan
- Isolated Win32 mock tests (mirroring `tests/test_single_instance.py`) testing `NIM_ADD`/`NIM_DELETE` lifecycle, close-to-tray vs. explicit quit behavior, and clean icon removal on `destroy()`.

---

### R04 — Transcript Auto-Scroll Lock & In-Pane Search (`Ctrl+F`)

#### Current State & Evidence
- In `gui/app.py:_write_pane` (`line 2002`), every incoming transcript delta unconditionally executes `widget.see(tk.END)`.
- During long meetings or lectures, if a user scrolls up in **Heard** or **Translation** to re-read an earlier sentence or copy a paragraph, the next incoming word immediately yanks the viewport back to the bottom.
- Neither the live transcript panes (`self.heard`, `self.trans`) nor the **Conversation History** viewer (`self._history_text`) support `Ctrl+F` keyword search.

#### Proposed Design & Implementation
1. **Smart Auto-Scroll Lock:**
   - Before inserting text in `_write_pane`, inspect `widget.yview()[1]`. Consider the pane "pinned to bottom" only when `yview()[1] >= 0.98`.
   - Only call `widget.see(tk.END)` when pinned to bottom.
   - When unpinned and new text arrives, display a subtle floating pill button at the bottom-right of that pane (`"↓ Canlı akışa dön"` / `"↓ Jump to live"`), which scrolls to `tk.END` and hides itself; scrolling manually back to the bottom also auto-hides the pill.
2. **Inline Find Bar (`Ctrl+F`):**
   - Bind `<Control-f>` / `<Control-F>` on `App` and `_history_win` to toggle a slim search bar (`Entry` + match counter `3/12` + Next/Prev `Enter`/`Shift+Enter` + `Escape` to close).
   - Highlight matches using `tk.Text.search(..., nocase=True)` and a dedicated `"search_hit"` / `"search_current"` tag styled from `gui/theme.py` (`C.accent`).

#### Verification Plan
- GUI test scrolling `app.trans.yview_moveto(0.0)`, pumping new `("trans", ...)` chunks, asserting `yview()[0] == 0.0` is preserved and the jump-to-live indicator appears, then invoking it to confirm `yview()[1] == 1.0`.
- GUI test verifying `Ctrl+F` match counting, tag highlighting, and `Escape` dismissal.

---

### R05 — Output Voice Character (`voice_name`) Selection

#### Current State & Evidence
- `build_config` in `loop.py` (`lines 240–267`) constructs `types.LiveConnectConfig` with `response_modalities` and `translation_config`, without specifying `speech_config`.
- Gemini Live supports `types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=...)))` (e.g., `Puck`, `Charon`, `Kore`, `Fenrir`, `Aoede`), allowing users to choose a preferred vocal timbre/register that is easier to distinguish from the original speaker—especially valuable when using background dubbing (`dub_background`).

#### Proposed Design & Implementation
1. **Engine (`loop.py`):**
   - Add `voice_name: str | None = None` to `build_config(...)` and `SystemAudioLoop.__init__(...)`.
   - When `voice_name` is set (and `"AUDIO"` is in `modalities`), attach `speech_config` to `LiveConnectConfig`. Guard gracefully if a future preview model rejects `speech_config` (log warning once and retry with default voice, similar to session resumption fallback).
2. **Config, CLI & GUI:**
   - Persist `voice_name: str = ""` (empty = model default) in `config.py`.
   - Add `--voice` flag to `cli.py`.
   - Add a **Voice** `Select` dropdown in Settings Tab 2 (`Default`, `Kore`, `Puck`, `Charon`, `Fenrir`, `Aoede`), triggering `_on_runtime_pref_change()` if changed while running.

#### Verification Plan
- Unit test on `build_config` asserting `speech_config.voice_config.prebuilt_voice_config.voice_name` is populated when specified and omitted when empty/text-only.
- CLI and GUI persistence tests.

---

### R06 — Bilingual Subtitles (`.srt`) & WebVTT (`.vtt`) Export

#### Current State & Evidence
- `export.py` currently supports `.txt`, single-stream `.srt` (preferring `trans`), and `.jsonl`.
- Language learners, lecture reviewers, and content editors frequently want **Bilingual SRT** (original `heard` line on top, `trans` line underneath in each cue) or **WebVTT (`.vtt`)** for browser/HTML5 video players.

#### Proposed Design & Implementation
1. **Exporter Functions (`export.py`):**
   - Add `export_bilingual_srt(items: list[TranscriptItem], session_start: float | None = None) -> str` that pairs each `trans` cue with its temporally overlapping or immediately preceding `heard` cue (using the same non-overlapping end-time clamping already implemented in `export_srt`).
   - Add `export_vtt(items: list[TranscriptItem], session_start: float | None = None, *, bilingual: bool = False) -> str` emitting `WEBVTT\n\n` with `HH:MM:SS.mmm --> HH:MM:SS.mmm` timestamps.
2. **GUI Export Dialog (`gui/app.py:_export_transcripts`):**
   - Add file type filters in `asksaveasfilename` for **Bilingual Subtitle (`*.bilingual.srt`)** and **WebVTT (`*.vtt`)** (localized in `i18n.py`).

#### Verification Plan
- Deterministic unit tests in `tests/test_gui.py` (or dedicated `tests/test_export.py`) covering bilingual pairing, missing-heard graceful fallback, WebVTT header/millisecond dot formatting, and non-overlapping timestamps.

---

### R07 — CLI Feature Parity (`--app`, `--dub`) & Two-Way Meeting Mode

#### Current State & Evidence
- Desktop GUI supports per-application WASAPI process-loopback capture (`applications.py`, `process_audio.py`) and automatic source muting/ducking (`source_mute.py`), whereas `cli.py` only supports `--mic`, `--loopback`, and `--device`.
- Furthermore, online meeting users (Zoom, Teams, Discord, Meet) often want **simultaneous bi-directional translation**:
  - *Inbound:* Meeting app audio → translated into user's native language on headphones.
  - *Outbound:* User's physical microphone → translated into foreign language on a virtual cable (e.g., VB-Cable) fed into the meeting app.

#### Proposed Design & Implementation
1. **CLI Parity (`cli.py`):**
   - `--list-apps`: Print running desktop applications discovered via `application_inputs()`.
   - `--app <exe_or_pid>`: Resolve an `ApplicationAudioSource` by executable name or PID and pass it to `SystemAudioLoop`.
   - `--dub-mute` / `--dub-bed <0.0..1.0>` / `--no-ducking`: Wire `SourceDub` + `playback_active` callbacks into `cli_emit` so terminal workflows enjoy the exact same dynamic audio ducking as the GUI.
2. **Two-Way Meeting Mode (Bi-Directional):**
   - Orchestrate two independent `SystemAudioLoop` instances (`inbound_loop` and `outbound_loop`) with opposite `(src, dst)` pairs and disjoint `(source_mic, output_speaker)` endpoints.
   - Enforce endpoint validation so `outbound_loop`'s virtual output speaker is never accidentally captured by `inbound_loop` (requiring either per-app capture on `inbound_loop` or distinct audio endpoints).

#### Verification Plan
- CLI argument tests mocking `application_inputs()` and `SourceDub` lifecycle (including `atexit` / `KeyboardInterrupt` restoration of system audio levels).
- Dual-loop unit test verifying independent stop/retry isolation and feedback-loop prevention checks.

---

### R08 — Friendly Application Names (`FileDescription`) & Icons in App Picker

#### Current State & Evidence
- `applications.py` (`lines 256–263`) intentionally avoids reading window titles (`GetWindowTextW`) to protect user privacy (preventing browser tab titles or private chat names from appearing in logs/config).
- Consequently, every item in `_open_application_picker` (`gui/app.py:825–920`) is displayed solely as a raw executable filename (`msedge.exe`, `chrome.exe`, `Spotify.exe`, `Shipping-Win64-Shipping.exe`), which can be cryptic for games and Electron apps.

#### Proposed Design & Implementation
1. **PE Version Resource Lookup (`applications.py`):**
   - Query `version.dll` (`GetFileVersionInfoSizeW` → `GetFileVersionInfoW` → `VerQueryValueW` for `\StringFileInfo\<lang-codepage>\FileDescription` or `ProductName`) once per unique executable path, cached in an `@functools.lru_cache(maxsize=128)` helper.
   - Format labels as `"Google Chrome (chrome.exe)"` (falling back to `"chrome.exe"` when `FileDescription` is absent or identical), preserving privacy because PE metadata comes strictly from the static binary on disk, never window titles.
2. **Optional Small Icons in Picker (`gui/app.py`):**
   - Replace the plain `tk.Listbox` in `_open_application_picker` with a lightweight themed `Treeview` or canvas row list capable of displaying 16×16 icons extracted via `ExtractIconExW` + `GetDIBits` → `tk.PhotoImage` (or keep text-first if icon extraction fails).

#### Verification Plan
- Unit tests on Windows `version.dll` extraction against `python.exe` / `explorer.exe` + fallback tests when version info is missing, ensuring `find_input_by_label` and `config.json` path matching remain backward-compatible.

---

## 3. Performance, Architecture & Packaging Optimizations

### R09 — Event-Driven Overlay Hover (Conditional `50 ms` Pointer Polling)

#### Current State & Evidence
- While the subtitle overlay is open, `_poll_overlay_pointer` (`gui/app.py:4499–4505`) schedules `pop.after(50, ...)` continuously (20 times per second), calling `winfo_pointerxy()`, `winfo_rootx()`, and `winfo_rooty()` via Tcl/Tk even when the user is not touching the mouse or when click-through mode is **off**.
- Global pointer polling is strictly necessary **only** when `self.overlay_click_through` is `True` (because `WS_EX_TRANSPARENT` causes Windows to route mouse events through the window, suppressing normal `<Enter>` / `<Leave>` events).

#### Proposed Design & Implementation
1. When `overlay_click_through` is `False`:
   - Cancel `_overlay_pointer_after_id` and rely on native `<Enter>` and `<Leave>` bindings on `pop` (with a tiny `after(40, ...)` debounce to avoid flicker when moving between `wrap`, `overlay_label`, `hdr`, and `grip`) to show/hide overlay controls.
2. When `overlay_click_through` is `True`:
   - Start `_poll_overlay_pointer`, and optionally adapt the interval (`200 ms` when the cursor is >100 px outside the overlay rectangle, `50 ms` when near/inside the overlay).

#### Verification Plan
- GUI test verifying `_overlay_pointer_after_id is None` when `overlay_click_through` is `False`, controls still toggle on `<Enter>`/`<Leave>`, and polling starts/stops cleanly when `_toggle_overlay_click_through()` is invoked.

---

### R10 — `SourceDub` Background Watcher Optimization

#### Current State & Evidence
- In `source_mute.py` (`lines 232–246` and `694–719`), `SourceDub._watch` wakes up every `0.5 s` whenever dubbing is engaged and calls `backend.refresh(token)`.
- With dynamic ducking (Phase 1) now returning the plan to `idle` between sentences (`self._active.action == "idle"`), idle CPU usage is already dramatically reduced!
- However, during continuous speech:
  1. In `mute_endpoint` mode (e.g., capturing system audio on Speakers while outputting translation to Headphones), `_watch` still wakes up every `0.5 s` and activates `IMMDevice` + `IAudioEndpointVolume` via COM even though an endpoint's mute/gain does not spawn child processes like per-app sessions do.
  2. In `mute_process` / `mute_other_sessions` modes, `_tree_of` calls `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)` across all system processes twice per second.

#### Proposed Design & Implementation
1. **Skip Polling for `mute_endpoint`:** In `_watch`, skip periodic `backend.refresh` (or reduce to a `5.0 s` health check) when `self._active.action == "mute_endpoint"`, since endpoint volume is static once set.
2. **Throttle Process-Tree Snapshots:** In `_WasapiBackend`, cache `(timestamp, tree_pids)` for `1.5–2.0 s` so newly spawned browser audio utility processes are still caught promptly without snapshotting the entire OS process table every `500 ms`.
3. **(Optional Future Enhancement):** Register `IAudioSessionNotification` COM callbacks so new audio sessions trigger immediate attenuation without polling.

#### Verification Plan
- Unit tests in `tests/test_source_mute.py` verifying `mute_endpoint` does not repeatedly invoke COM endpoint volume writes every `500 ms` and process-tree cache invalidates after TTL.

---

### R11 — Bounded Transcript Buffers & Zero-Copy `AudioConverter`

#### Current State & Evidence
1. **Unbounded UI & Export Growth:**
   - In multi-hour livestreams or all-day conferences, `self.heard` (`tk.Text`), `self.trans` (`tk.Text`), `self.log` (`tk.Text`), and `self.transcript_items` (`list[TranscriptItem]`) in `gui/app.py` grow without bound. After thousands of utterances, Tk text layout/measurement slows down and RAM usage climbs steadily—even though full history is already persisted on disk in `history.jsonl`.
2. **Per-Block Array Allocations in `AudioConverter` (`audio.py:92–135`):**
   - At `50 blocks/sec` (`20 ms` blocks), `AudioConverter.process` allocates multiple temporary NumPy arrays per block (`np.concatenate` for `_filter_state`, `np.convolve`, `np.concatenate` for `_leftover`, `np.arange(n_out)` index arrays).
   - Additionally, `_capture_inner` in `loop.py` already computes `mono` for RMS metering before calling `conv.process`, while `conv.process` checks `frame.ndim > 1` again.

#### Proposed Design & Implementation
1. **Bounded Ring / Windowing (`gui/app.py`):**
   - Cap `self.log` at e.g. `500` lines (deleting `"1.0"` to `"101.0"` in batches when exceeded).
   - Cap `self.heard` and `self.trans` visual panes at e.g. `2,000` lines (preserving scroll position if scrolled up) and cap in-memory `self.transcript_items` at e.g. `5,000` items (or spill older items to a session temp JSONL file so full-session `.srt` export still covers multi-hour sessions).
2. **Pre-Allocated Resampler Buffers (`audio.py`):**
   - Pre-compute the fractional resampling index table for the standard steady-state block size (`block_frames` at `48000 → 16000 Hz` is an exact `3:1` integer decimation!).
   - Fast-path integer ratios (`48000 → 16000` = `3:1`, `32000 → 16000` = `2:1`, `16000 → 16000` = `1:1`): after FIR filtering into a pre-allocated work buffer, slice `filtered[offset::ratio]` directly instead of computing floating-point linear interpolation indices every `20 ms`, keeping the general linear-interpolation path for non-integer rates (`44100 → 16000`, `24000 → 16000`).

#### Verification Plan
- Signal-fidelity unit tests in `tests/test_live_translate.py` comparing fast-path `3:1` / `2:1` output SNR and phase continuity across chunk boundaries against reference output.
- GUI stress test inserting `2,500` lines and verifying line count stays bounded without losing recent content.

---

### R12 — Modularize `gui/app.py` into Focused Submodules

#### Current State & Evidence
- `gui/app.py` has grown to **~4,860 lines** in a single class (`App`), handling Win32 ctypes helpers, idle VU preview monitoring, main rail/pane layout, theme retinting, message-queue pumping (`_pump_log`), settings dialog, history viewer, application picker, about/updater workflows, and the floating click-through subtitle overlay.
- High method count and cognitive complexity in `App` make navigation, code review, and isolated widget testing harder over time.

#### Proposed Design & Implementation
Split `gui/app.py` incrementally into cohesive modules under `gui/` while keeping `from gui.app import App, format_user_error` 100% backward-compatible for `main.py` and existing tests:
1. **`gui/win32.py`:** `_win32_gui_apis`, `_virtual_screen_bounds`, `_monitor_work_area`, `_parse_geometry`, `_clamp_to_bounds`, single-instance message polling helpers.
2. **`gui/preview.py`:** `_InputPreviewMonitor` class.
3. **`gui/overlay.py`:** Subtitle overlay controller/mixin (`_build_overlay`, `_close_overlay`, `_update_overlay`, `_overlay_tail`, `_apply_overlay_click_through`, pointer/hover handling).
4. **`gui/settings_dialog.py`:** Settings Toplevel builder, 2-tab switcher, shortcut capture, API key test UI, and reset adoption.
5. **`gui/dialogs.py`:** About dialog (`_open_about`), Application Picker (`_open_application_picker`), and Conversation History viewer (`_open_history`).
6. **`gui/app.py`:** Core `App` shell, rail/transcript panes, session lifecycle (`start`, `stop`, `restart`, `_run`), `_pump_log` dispatcher, and theme coordination.

> **Important Constraint:** Do not break monkeypatch targets used in `tests/test_gui.py` (such as `gui.app.tk.Toplevel`, `gui.app.messagebox`, `gui.app.save_preferences`, `gui.app.SystemAudioLoop`, `gui.app.dark_titlebar`). Re-export or reference through `gui.app` or pass dependency hooks cleanly so all 80+ GUI tests pass unchanged.

#### Verification Plan
- Full `pytest -q -m "not device"` pass with zero test modifications required, plus `codebase-memory` graph check confirming zero circular imports (`cycles: 0`) and reduced per-file complexity.

---

### R13 — Documentation Sync (`README`), CI Matrix & Release Code Signing

#### Current State & Evidence
1. **Documentation Drift:**
   - `README.md` (footer line `420` still says `Ahenk 0.7.1` instead of `0.7.6+`, and Troubleshooting line `406` still says `48000 Hz` is mandatory for microphones) and `README.en.md` do not yet document **Dubbing / Dynamic Audio Ducking**, **Custom Glossary**, **Translation Volume & Subtitle Opacity Sliders**, **Conversation History Viewer**, or the new CLI flags (`--glossary`, `--prompt`, automatic CLI reconnect, zero-Tkinter CLI build).
2. **CI Pipeline (`.github/workflows/ci.yml`):**
   - Currently tests Python `3.11` and `3.12` without a linter step, whereas local development already runs on Python `3.13` / `3.14`.
3. **Release Trust (`.github/workflows/release.yml`):**
   - `Ahenk.exe` and `Ahenk-cli.exe` publish SHA-256 checksums for verified self-updates (`updater.py`), but unsigned Windows binaries trigger SmartScreen warnings on first download.

#### Proposed Design & Implementation
1. **Update `README.md` & `README.en.md`:**
   - Document the 2-tab Settings workflow, Dynamic Dubbing / Audio Ducking modes, Custom Glossary syntax, History controls, automatic sample-rate fallback, and new CLI flags (`--glossary`, `--prompt`, `--volume`, `--vad`), and sync version badges/footers.
2. **Expand `.github/workflows/ci.yml`:**
   - Add `"3.13"` to `matrix.python-version`.
   - Add a fast `ruff check .` step (configured conservatively in `pyproject.toml` for `E9,F63,F7,F82` syntax/undefined-name safety first) and a CLI zero-Tkinter smoke check (`python -c "import sys, cli; assert 'tkinter' not in sys.modules"`).
3. **Evaluate Open-Source Code Signing:**
   - Prepare optional Authenticode signing step in `.github/workflows/release.yml` (e.g., via SignPath Foundation or Azure Trusted Signing gated on repository secrets so forks/PRs continue building cleanly without secrets) and optional Winget manifest generation.

#### Verification Plan
- Local execution of `ruff check`, wheel build smoke test (`python -m build --wheel`), CLI entrypoint checks, and Markdown link validation.

---

## Suggested Implementation Order (Next Waves)

1. **Wave 2A — Fast High-Value Polish (Low Effort):**
   - **R13** (Sync `README.md` / `README.en.md` + CI zero-Tkinter & Python 3.13 check)
   - **R04** (Transcript Auto-Scroll Lock + `Ctrl+F` Search)
   - **R01** (Live Pause / Resume button & hotkey)
   - **R06** (Bilingual `.srt` & `.vtt` export)
2. **Wave 2B — Desktop & Audio Experience Upgrades (Medium Effort):**
   - **R02** (`vad_threshold` & `system_instruction` in GUI Settings)
   - **R05** (Output `voice_name` selection in GUI & CLI)
   - **R03** (System Tray mode & right-click quick actions)
   - **R08** (`FileDescription` product names & icons in App Picker)
3. **Wave 2C — Engine Efficiency, CLI Parity & Modular Architecture:**
   - **R09** & **R10** (Conditional overlay pointer polling + `SourceDub` watcher throttling)
   - **R11** (Bounded transcript panes + fast-path `3:1` integer decimation in `AudioConverter`)
   - **R07** (CLI `--app` / `--dub` parity + Two-Way Meeting Mode)
   - **R12** (Modularizing `gui/app.py` into focused `gui/*` submodules)
