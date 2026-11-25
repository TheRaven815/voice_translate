# Sürüm Notları / Changelog

## v0.7.8 — 2026-11-25

### Türkçe

- Kenar yumuşatmalı SDF `CheckToggle` ve `LevelSlider` çizimi eklendi; tik hizalaması ve kaydırıcı topuzu pürüzsüzleştirildi.
- Konuşma geçmişi kaydı varsayılan olarak kapatıldı (`save_history=False`); iş parçacığı güvenli dosya kilitleme, atomik devir, geliştirilmiş eşleştirme ve otomatik boşaltma eklendi.
- Bölgesel BCP-47 dil kodları (`en-US`, `tr-TR` vb.) geçmiş görüntüleyici ve canlı başlıkta ana dil adına çözümlendi.
- Oturum denetimleri dar/kaydırılan yan panelde sabit tutuldu ve duraklatmada dublaj kapatıldı.
- Canlı transkript bölümleme, altyazı zaman aralığı hesaplama ve `Ctrl+Space` varsayılan duraklatma kısayolu iyileştirildi; arayüz çeviri kazancı %100 olarak sabitlendi.

### English

- Added SDF anti-aliased rendering for `CheckToggle` and `LevelSlider` with centered checkmarks and smooth slider tracks/knobs.
- Disabled conversation history recording by default (`save_history=False`) and hardened persistence with thread-safe locking, atomic rotation, improved pairing, and automatic flushing.
- Resolved regional BCP-47 language codes (`en-US`, `tr-TR`, etc.) to display language names in the live header and history viewer.
- Kept session controls pinned in the sidebar and stopped dubbing immediately on pause.
- Improved live transcript segmentation, subtitle cue timestamp spacing, default `Ctrl+Space` pause shortcut, and fixed 100% GUI translation gain.

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
