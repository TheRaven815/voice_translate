# Ahenk

[Türkçe](README.md) · **[English](#ahenk)**

Live-translates whatever is playing on the PC (system loopback) or the microphone via [Gemini Live Translate](https://ai.google.dev/). You get both text and speech; text-only is available.

Version **0.1.0**. Author: Enes Eliağır. Windows-first (WASAPI loopback). Python **3.11+**.

Turkish is the source README ([README.md](README.md)). This file is the English option.

## Contents

- [What it does](#what-it-does)
- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Setup](#setup)
- [Desktop UI](#desktop-ui)
- [CLI](#cli)
- [Languages](#languages)
- [API key](#api-key)
- [Local settings](#local-settings)
- [Privacy and security](#privacy-and-security)
- [Layout](#layout)
- [Onefile build](#onefile-build)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## What it does

Ahenk captures PCM from the selected input, sends it to a Gemini Live Translate session, plays the translated audio, and writes transcripts into two panes:

| Pane | Content |
| --- | --- |
| **Duyulan** (Heard) | Source-language transcript |
| **Çeviri** (Translation) | Target-language transcript + audio |

Typical use: foreign-language video or meeting; hear Turkish (or another target) on the speakers.

## Features

- System audio (loopback) or microphone
- Source language **Otomatik** (model detects) or a fixed BCP-47 code
- 13 target languages (below)
- Output **Hiçbiri** (None): no playback, text only
- Live VU meter and status dot (Ready / Running / Stopped)
- **Altyazı**: always-on-top, draggable overlay (last translation line)
- Heard / Translation: **Kopyala** (copy), **Temizle** (clear)
- Click the arrow to swap source ↔ target (disabled when source is Auto)
- **Yenile** refreshes the device list
- Device, language, and API key persist in local `config.json`
- Up to 3 reconnects if the session drops
- Console (`cli.py`) and `ahenk.bat` launcher
- PyInstaller onefile (`dist\Ahenk.exe`)

## How it works

```
Input device (48 kHz stereo, 20 ms)
        ↓  mono + 16 kHz PCM16
Gemini Live  models/gemini-3.5-live-translate-preview
        ↓  24 kHz PCM16  +  transcript deltas
Speaker (~80 ms preroll)          Heard / Translation panes
```

- Capture stays on **one daemon thread** because soundcard COM objects must not be shared across threads.
- If the model lags, the send queue (50) and playback queue (200) drop the oldest chunk. The playback queue is **not** cleared at turn end (that chopped the audio).
- Transcript pieces may be deltas or cumulative; `merge_transcript` joins them.

## Requirements

| | |
| --- | --- |
| OS | Windows 10/11 (loopback). Mic path may work elsewhere; the launcher is `.bat`. |
| Python | 3.11+ (`py -3` or `python`) |
| Network | Gemini API |
| Key | [Google AI Studio](https://aistudio.google.com/apikey) |
| Audio | WASAPI loopback of a speaker (usually the `[Sistem]` entry for the default device) |

Dependencies (`requirements.txt`): `google-genai`, `soundcard`, `numpy`, `python-dotenv`, `pytest`.

## Setup

Shortest path — venv, pip, menu:

```bat
ahenk.bat
```

| Choice | |
| --- | --- |
| `1` | UI (`main.py`) |
| `2` | Console (`cli.py`) |
| `3` | Onefile build |
| `4` | Refresh dependencies |
| `5` | Exit |

Manual:

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Linux / macOS (microphone; loopback not guaranteed):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## Desktop UI

`python main.py` — 960×580, dark theme, left rail + two transcript panes.

**Left rail**

1. Title, version, **Altyazı**, about (`ⓘ`)
2. Status dot + VU
3. **Giriş** / **Çıkış** — `[Sistem]` loopback, `[Mikrofon]` real mic. **Hiçbiri** on output = text-only.
4. **Dil** — source (Auto + languages) → target. Arrow: swap.
5. **API anahtarı** — masked with `•`; written on **Kaydet** or Start.
6. **Başlat** / **Durdur** — devices, languages, and key lock while running.

**Panes:** Heard | Translation. Copy / Clear on each. Bottom strip: `[bilgi]` / `[hata]` log.

**Altyazı:** small, always on top, drag, ✕ to close. Shows the last translation line.

First launch (no saved prefs): default loopback in, default speaker out, source Auto, target Turkish.

> **Tip (Echo Prevention):** When capturing system audio (loopback), routing translation playback to a separate device (such as headphones) or selecting "None" (text-only) produces the cleanest audio. If using the same speaker, Ahenk automatically ducks loopback capture while playing translation audio to avoid echo loops.

## CLI

```bat
.venv\Scripts\python cli.py --help
.venv\Scripts\python cli.py --list-devices
.venv\Scripts\python cli.py --dst tr
.venv\Scripts\python cli.py --mic --src en --dst tr
.venv\Scripts\python cli.py --device Headphones --src auto --dst de
```

| Flag | Default | Description |
| --- | --- | --- |
| `--src` | `auto` | BCP-47 or `auto` |
| `--dst` | `tr` | Target BCP-47 |
| `--device` | none | Substring of the loopback/input device name |
| `--output` | none | Substring of the output speaker device name |
| `--mic` | off | Capture microphone instead of system audio |
| `--text-only` | off | Run without speaker audio output (text-only) |
| `--no-interactive` | off | Run without reading console stdin; exit with Ctrl+C |
| `--list-devices` | | Print speakers / loopback / mics, then exit |
| `--list-langs` | | Print supported language names and codes, then exit |
| `--version` | | Print version and exit |
| `--json` | off | Produce line-by-line streaming JSON (JSONL) for scripting |
| `--log` | none | Log all console output to the specified file |
| `--vad` | `0.0` | RMS silence gate threshold (e.g. `0.01`) |
| `--volume` | `1.0` | Output translation audio gain multiplier (`0.0` - `2.0`) |
| `--model` | default | Gemini Live model name |
| `--api-key` | none | Lands in shell history; prefer `.env` or GUI |

Stop with `q` + Enter or Ctrl+C (or direct Ctrl+C in `--no-interactive` mode).
`--src` / `--dst` are codes, not the GUI labels (`en`, `tr`, `de`, …).

## Languages

`languages.py`. Add a language as display name → BCP-47.

| UI | Code |
| --- | --- |
| İngilizce | `en` |
| Türkçe | `tr` |
| Almanca | `de` |
| Fransızca | `fr` |
| İspanyolca | `es` |
| İtalyanca | `it` |
| Portekizce | `pt` |
| Rusça | `ru` |
| Arapça | `ar` |
| Felemenkçe | `nl` |
| Japonca | `ja` |
| Çince (Basitleştirilmiş) | `zh-CN` |
| Çince (Geleneksel) | `zh-TW` |
| Korece | `ko` |
| Hintçe | `hi` |
| Lehçe | `pl` |
| Ukraynaca | `uk` |
| Endonezce | `id` |
| Vietnamca | `vi` |
| İsveççe | `sv` |
Source **Otomatik**: empty `language_codes`; the model detects. No Auto on the target.

## API key

No key ships in the repo. Create one in [AI Studio](https://aistudio.google.com/apikey).

Priority (`config.resolve_api_key`):

1. CLI `--api-key` (shell history; avoid)
2. `GEMINI_API_KEY` — environment or project-root `.env` (`python-dotenv`)
3. Saved `config.json` → `api_key` (GUI Save / Start)

`.env` example — **do not commit** (gitignored):

```
GEMINI_API_KEY=your-key-here
```

If it leaks, revoke it in AI Studio. Do not paste it into screenshots, issues, PRs, or `--api-key`.

Test strings `sk-test` / `sk-live-1` are fake.

## Local settings

Not in git. Tests override the path with `VOICE_TRANSLATE_CONFIG`.

| OS | File |
| --- | --- |
| Windows | `%APPDATA%\Ahenk\config.json` |
| Linux / macOS | `$XDG_CONFIG_HOME/Ahenk/config.json` or `~/.config/Ahenk/config.json` |

On Windows, the API key is encrypted using Windows DPAPI (`CryptProtectData`, user-tied local OS encryption); on Unix, the file is saved with `0600` permissions. Fields: `api_key`, `input_device`, `output_device`, `src_lang`, `dst_lang`. Unknown fields are kept.

## Privacy and security

- Captured audio and the translation go to Google. Model: `models/gemini-3.5-live-translate-preview`. Billing and quotas follow the [Gemini API](https://ai.google.dev/) terms.
- The key and preferences live only in this machine’s `config.json`.
- The tree has no real key, `.env`, or `config.json`. Ignored: `.env`, `.env.*`, `config.json`, `.venv/`, `dist/`, `build/`, `*.spec`, `*.exe`.
- Git history was scanned; no real keys. Commit email is GitHub noreply.

This app sends audio to a third-party API. Do not use it on sensitive content unless you accept that.

## Layout

```
main.py          desktop entry
cli.py           console
ahenk.bat        venv + menu + build
config.py        settings file, key order
loop.py          Gemini session, capture / receive / play
audio.py         48k→16k, PCM16↔float
devices.py       soundcard list, loopback pick
languages.py     UI name → BCP-47
meta.py          version, title, author
gui/app.py       window, overlay, reconnect
gui/theme.py     palette, icon, AppUserModelID
gui/widgets.py   custom Select
assets/          ahenk.ico, ahenk.png
tests/           pytest (no network; device test may skip)
```

## Onefile build

`ahenk.bat` → `3`, or:

```bat
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name Ahenk --icon assets\ahenk.ico --add-data "assets;assets" --hidden-import soundcard --hidden-import google.genai --collect-submodules google.genai main.py
```

Output: `dist\Ahenk.exe`. `dist/`, `build/`, and `*.spec` are gitignored. The exe still asks for *your* Gemini key; nothing is baked in.

## Tests

No network. The client is faked.

```bat
.venv\Scripts\python -m pytest
```

| File | |
| --- | --- |
| `tests/test_config.py` | save, priority, corrupt JSON |
| `tests/test_gui.py` | start, panes, overlay, prefs |
| `tests/test_live_translate.py` | resample, merge, fake session |

`test_duplex_with_real_devices_stays_alive` needs real devices; it skips otherwise.

## Troubleshooting

| Symptom | |
| --- | --- |
| `GEMINI_API_KEY bulunamadı` | AI Studio key; `.env`, env, or GUI Save |
| `Loopback cihaz bulunamadı` | Windows speaker; Yenile; try another output |
| Choppy / delayed audio | Set output to **Hiçbiri** and watch text; check network and quota |
| Heard but no translation | Target language; model access (`gemini-3.5-live-translate-preview`) |
| Python not found | [python.org](https://www.python.org/downloads/) — tick PATH in the installer |
| No Tk window | `python main.py` — tkinter (bundled with the official Windows installer) |
| Build failure | `ahenk.bat` → `4` then `3`; antivirus must not lock `dist\` |

## License

This project is licensed under the [MIT License](LICENSE).
