# Sürüm Notları / Changelog

## v0.7.7 — 2026-11-18

### Türkçe

- Arayüz modülerleştirildi (`gui/app.py` küçültüldü; dialogs, overlay, preview, settings_dialog, widgets, win32 ayrıldı).
- Ayar penceresi sadeleştirildi; uygulama seçiciye simgeler eklendi.
- Canlı duraklat/devam, `Ctrl+P` ve bas-konuş (PTT) eklendi.
- Transkriptte `Ctrl+F` arama ve akıllı kaydırma kilidi ("canlıya dön") eklendi.
- Dinamik dublaj ses kısma, özel sözlük, çeviri ses düzeyi ve altyazı opaklığı eklendi.
- İki dilli SRT ve WebVTT dışa aktarma ile konuşma geçmişi görüntüleyici eklendi.
- CLI: `--glossary`, `--prompt` ve otomatik yeniden bağlanma; ses örnekleme hızı/kanal yedeği.
- CI, testler ve belgeler güncellendi.

### English

- Modularized the GUI (trimmed `gui/app.py`; split dialogs, overlay, preview, settings_dialog, widgets, win32).
- Simplified the settings dialog and added icons to the app picker.
- Added live pause/resume, `Ctrl+P`, and push-to-talk.
- Added `Ctrl+F` transcript search and smart scroll lock with jump-to-live.
- Added dynamic dub ducking, custom glossary, translation volume, and subtitle opacity.
- Added bilingual SRT and WebVTT export plus a conversation history viewer.
- CLI: `--glossary`, `--prompt`, auto-reconnect, and capture rate/channel fallback.
- Updated CI, tests, and docs.
