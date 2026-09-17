# Ahenk — Güncel öneriler (önem sırası)

Tarih: 2026-09-17. Kaynak: mevcut kodun uçtan uca taraması (`loop.py`, `audio.py`, `devices.py`, `gui/*`, `cli.py`, `config.py`, `tests/*`, paketleme, README).

`GELISTIRME_ONERILERI.md` önceki tur; oradaki P0/P1 maddelerin çoğu **uygulanmış**. Bu dosya yalnızca **hâlâ açık** işler, yeni ürün özellikleri ve profesyonelleşme. Kod yaması yok; her madde bir iş kalemi.

Öncelik: **P0** çökme / yanlış çalışma / güvenlik yanılsaması · **P1** kararlılık, maliyet, “ürün gibi durmama” · **P2** kullanılabilir özellik ve mimari · **P3** temizlik, doküman, parlatma.

---

## P0 — Kritik

- [x] **Python sürüm iddiası kodla çelişiyor (`asyncio.TaskGroup` = 3.11+)**
  - *Nerede:* `README.md` / `README.en.md` “Python 3.10+”; `loop.py` `run()` içinde `asyncio.TaskGroup()`.
  - *Neden:* 3.10’da uygulama açılışta patlar. `ExceptionGroup` yolu da 3.11.
  - *Öneri:* README ve `ahenk.bat` metnini 3.11+ yap; mümkünse sürüm kontrolü ile anlaşılır hata ver.

- [x] **CLI: hoparlör veya mikrofon `None` iken çökme**
  - *Nerede:* `cli.py` — `default_speaker()` / `default_microphone()` sonrası `.name` okunuyor; `devices.py` GUI tarafında `None` koruması var, CLI’da yok.
  - *Neden:* Çıkış aygıtı olmayan (RDP, headless, sürücü düşmüş) makinede traceback.
  - *Öneri:* `None` ise metin-only’ye düş veya net hata + `sys.exit(1)`. `--text-only` ekle.

- [x] **USB / Bluetooth aygıt kopunca sessiz ölüm**
  - *Nerede:* `loop.py` `_capture_thread` (`mic.record`) ve `_play_thread` (`sp.play`) — donanım hatası yakalanmıyor.
  - *Neden:* İş parçacığı ölür; GUI “Çalışıyor” kalır, ses/çeviri durur, kullanıcı nedenini görmez.
  - *Öneri:* COM/IO hatalarını yakala, ana döngüye `Aygıt bağlantısı koptu` ilet, oturumu durdur veya aygıt yenilemeye zorla.

- [x] **API anahtarı “şifreleme” güvenlik tiyatrosu**
  - *Nerede:* `config.py` — sabit `_SECRET_KEY` ile XOR + Base64; README “yerel, güvenli” izlenimi.
  - *Neden:* Anahtar kaynakta; diskteki değer saniyede çözülür. Yanlış güvenlik hissi.
  - *Öneri:* Windows’ta DPAPI (`CryptProtectData`); diğerlerinde düz metin + `0600` ve dürüst doküman. “Şifreli” demeyi bırak veya gerçek KMS kullan.

- [x] **Metin-only modda model hâlâ AUDIO üretiyor**
  - *Nerede:* `loop.py` `build_config` — `response_modalities=["AUDIO"]` sabit; çıkış “Hiçbiri” iken ses atılıyor.
  - *Neden:* Gereksiz kota, gecikme, maliyet; “metin-only” vaadi yarım.
  - *Öneri:* Hoparlör yoksa `TEXT` (SDK izin veriyorsa); GUI/CLI bu seçimi `build_config`’e geçirsin.

- [x] **Yeniden bağlanırken Durdur yeni oturum açıyor**
  - *Nerede:* `gui/app.py` `_run` — hata sonrası `user_stop.wait(2)` bitince her zaman yeni `SystemAudioLoop` (temiz `_user_stop`). `stop()` yalnızca o anki nesneye `request_stop` eder.
  - *Neden:* “Yeniden bağlanılıyor” sırasında Durdur/kapat → 2 sn sonra Gemini+WASAPI tekrar ayağa kalkar.
  - *Öneri:* Bekleme sonrası `user_stop` hâlâ set ise kır; tek paylaşılan Event veya `_stopping` bayrağı. Test: retry beklerken stop.

---

## P1 — Yüksek (kararlılık, UX, performans)

- [x] **Durum makinesi yok: Başlat = hemen “Çalışıyor”**
  - *Nerede:* `gui/app.py` `start()` / `_set_running` / `_run` retry.
  - *Neden:* Bağlantı kurulmadan yeşil; yeniden bağlanırken durum değişmiyor; hata nedeni log satırına sıkışıyor.
  - *Öneri:* `Bağlanıyor` (sarı/`C.warn`) → `Dinleniyor` → `Yeniden bağlanılıyor` → `Hata`. Retry’de UI’ye durum bas.

- [x] **Sınırsız `audio_in_queue` + köprü kuyruk**
  - *Nerede:* `loop.py` `receive()` → sınırsız `asyncio.Queue`; `play()` bunu `_play_q` (max 200) kopyalıyor.
  - *Neden:* Oynatma yavaşlarsa RAM şişer; ekstra context-switch. Eski “çift kuyruk” maddesi hâlâ geçerli.
  - *Öneri:* `receive` doğrudan `_play_q`’ya yazsın (drop-oldest); veya `audio_in_queue`’ya `maxsize` koy. `play()` ikinci `put_nowait` `_post` gibi `QueueFull` yutsun — `request_stop`’un `None`’ı slot doldurursa TaskGroup oturumu keser.

- [x] **Yakalama/oynatma `finally` beklemesi zaman aşımı yok**
  - *Nerede:* `loop.py` `listen_system` / `play()` — `done.wait()`; GUI `_on_close` 0.3 sn `join` sonra `destroy()`. `listen_system` `except CancelledError: pass` iptalde join’i atlar (`shield` yetmez).
  - *Neden:* `record()`/`play()` kilitlenirse kapanış asılır veya Tcl yokken COM erişim ihlali. Retry’de iki recorder riski kapanmamış.
  - *Öneri:* `wait_for(done, timeout=0.5)` + `uncancel()`; stream abort.

- [x] **Gemini’ye giden PCM mime’da örnekleme hızı yok**
  - *Nerede:* `loop.py` `_capture_thread` — `mime_type: "audio/pcm"` (SDK örneği `audio/pcm;rate=16000`).
  - *Neden:* Canlı varsayılan 16 kHz değilse STT yanlış hızda; tanıma bozulur.
  - *Öneri:* `audio/pcm;rate={SEND_SAMPLE_RATE}`.

- [x] **Çeviri sesi loopback’e girer (yankı / yeniden çeviri)**
  - *Nerede:* Yakalama sürekli gönderir, oynatma aynı sistem hoparlöründeyse TTS tekrar yakalanır. VAD/duck/AEC yok.
  - *Neden:* Varsayılan “[Sistem] + hoparlör” yolunda çeviri tekrar çevrilir.
  - *Öneri:* Çıkışı farklı aygıta yönlendir (doküman); oynatma sırasında gönderimi kıs; SDK `activity_end`.

- [x] **İlk açılışta senkron aygıt taraması UI dondurur**
  - *Nerede:* `gui/app.py` `__init__` → `refresh_devices()` (`async_scan=False`). Yenile butonu arka plan; açılış değil. `_apply_devices` Tk thread’de tekrar `pick_loopback()` (ikinci COM taraması).
  - *Neden:* Bluetooth/COM 0.5–2 sn “Yanıt vermiyor”.
  - *Öneri:* Açılışta da async tarama; varsayılanı mevcut `ins`/`outs` listesinden seç, ikinci enumerasyon yok.

- [x] **Async aygıt tarama hatası sessiz (`except` değişkeni)**
  - *Nerede:* `gui/app.py` `refresh_devices` — `except Exception as e: self.after(0, lambda: ... {e})`.
  - *Neden:* Python 3 `except` sonunda `e` silinir; callback `NameError` verir, kullanıcı `[hata]` görmez.
  - *Öneri:* `lambda err=e:`; `winfo_exists` koruması.

- [x] **Tercih kaydı her dropdown değişiminde diske yazılıyor**
  - *Nerede:* `gui/app.py` `trace_add` → `_save_user_prefs`; `__init__`’te `load_config()` iki kez.
  - *Neden:* Açılış ve dil değiştirmede gereksiz I/O; nadiren bozuk JSON.
  - *Öneri:* 300–500 ms debounce; config’i bir kez yükle.

- [x] **Tema geçince ray ayırıcıları ve altyazı güncellenmiyor**
  - *Nerede:* `_rail_sep` `self._rail_seps`’e eklemiyor; `_refresh_theme` boş listeyi boyuyor. Overlay `fg="#ffffff"` sabit; Hakkında `dark_titlebar(pop)` her zaman koyu.
  - *Neden:* Açık temada çizgiler koyu kalır; altyazı/about uyumsuz.
  - *Öneri:* Ayırıcıları listele; overlay/about’u temadan boya; `dark_titlebar(..., dark=theme!="light")`.

- [x] **Açık temada dolu Başlat butonu hover’da kaybolur**
  - *Nerede:* `gui/app.py` `_paint` — `hover = "#ffffff"` sabit. Açık temada `C.fill` koyu, `C.fill_fg` beyaz → beyaz üzerine beyaz.
  - *Öneri:* Hover’ı paletten al (`C.fill`’in açık/koyu varyantı).

- [x] **VU hâlâ kuyrukta; `last_level` okunmuyor**
  - *Nerede:* `loop.py` hem `last_level` yazıyor hem 80 ms’de `("level", …)` emit; GUI kuyruktan işliyor. VU 36×4 px, doğrusal RMS, çıkış göstergesi yok.
  - *Neden:* Eski P1 yarı uygulanmış; çeviri mesajlarıyla yarış; metre okunaksız.
  - *Öneri:* GUI timer’da `loop_obj.last_level` oku; dBFS; genişlet; çıkış için ikinci bar (oynatma kuyruğu aktivitesi).

- [x] **CLI `input()` Windows’ta her şeyi kilitler**
  - *Nerede:* `loop.py` `send_text` → `asyncio.to_thread(input, ...)`.
  - *Neden:* Çeviri satırları prompt ile karışır; Ctrl+C Enter’a kadar kapanmaz.
  - *Öneri:* `--no-interactive` (yalnız Ctrl+C); Windows’ta `msvcrt.kbhit` veya ayrı stdin thread + queue.

- [x] **CLI çıkışta `ExceptionGroup` traceback**
  - *Nerede:* `cli.py` yalnız `KeyboardInterrupt` + `CancelledError`; `loop.py` `run()` TaskGroup içinde `CancelledError` fırlatıyor. GUI `e.exceptions[0]` çözüyor, CLI değil.
  - *Neden:* `q` veya Ctrl+C “temiz çıkış” değil, konsol çökmesi gibi durur.
  - *Öneri:* GUI ile aynı kök-hata çözümü; `ExceptionGroup` / `BaseExceptionGroup` yakala.

- [x] **CLI ürün olarak GUI’nin gerisinde**
  - *Nerede:* `cli.py` — çıkış aygıtı yok, Hiçbiri yok, `--model` var ama README’de yok. `--src/--dst` `languages.py` ile doğrulanmıyor; geçersiz kod canlı oturumda 400 olur. `--version` yok (`meta.py` yalnız GUI).
  - *Öneri:* `--output` / `--text-only` / `--no-interactive` / `--list-langs` / `--version`; kodları `LANGS` ile doğrula.

- [x] **Dil kodları config’de UI Türkçe adı**
  - *Nerede:* `gui/app.py` `save_preferences(src_lang="Türkçe")`; CLI `tr`/`en`.
  - *Neden:* UI dili değişince eski config kırılır; CLI/GUI paylaşımı bozuk.
  - *Öneri:* Diskte her zaman BCP-47 (`auto`, `tr`); UI katmanında yerelleştir.

- [x] **Pencere ve altyazı geometrisi kayboluyor**
  - *Nerede:* `config.Settings` — `theme` var, `window_geom` / `overlay_geom` yok. Overlay her açılışta ekran alt-orta (`max(0, …)` çoklu monitörü keser).
  - *Öneri:* Geometriyi kaydet/yükle; `max(0,x)` kaldırma (önceki about düzeltmesi overlay’e uygulanmamış).

- [x] **Select klavye ile kullanılamıyor**
  - *Nerede:* `gui/widgets.py` — tıklama + Escape; ok / Enter / harf yok. Butonlarda `takefocus=0`.
  - *Neden:* Erişilebilirlik ve “hazır ürün” hissi yok. Önceki listede [x] işaretli ama kodda yok.
  - *Öneri:* Odak halkası, ok tuşları, Enter, Tab sırası; ekran okuyucu etiketleri.

- [x] **48 kHz varsayımı ve kutu-ortalama downsample**
  - *Nerede:* `audio.py` `CAPTURE_RATE = 48000`, `to_16k_mono` 3:1 mean. Aygıt 44.1 kHz veya kısa blok dönerse artık örnek atılır.
  - *Neden:* Tıkırtı, yanlış hız, tanıma kaybı.
  - *Öneri:* Gerçek örnekleme hızını ölç; 48k değilse `resample`; artan örnekleri bir sonraki bloğa taşı.

- [x] **`receive` ses gelince transkripti atlayabilir**
  - *Nerede:* `loop.py` `if data := response.data: ... continue` — aynı yanıtta metin varsa düşer.
  - *Öneri:* PCM ve transkripti `continue` olmadan işle.

- [x] **Bağlantı hataları kullanıcı diline çevrilmiyor**
  - *Nerede:* `gui/app.py` `_run` — `type(root_err).__name__: {root_err}`.
  - *Neden:* 403/429/quota/model-not-found ham SDK metni.
  - *Öneri:* Statü kodu eşlemesi: geçersiz anahtar, kota, model adı, ağ. Kaydet’te anahtar doğrulama (hafif ping).

- [x] **Çalışırken dil/aygıt değiştirilemiyor (yeniden bağlanma yok)**
  - *Nerede:* Çalışırken kilit; değişiklik oturumu yenilemiyor.
  - *Öneri:* “Uygula” = nazik reconnect; veya dil değişiminde tek tıkla yeniden başlat.

- [x] **`ahenk.bat` her açılışta `pip install`**
  - *Nerede:* `ensure_deps` menüden önce her seferinde pip upgrade + `requirements.txt`.
  - *Neden:* Yavaş başlangıç; çevrimdışı/ağ hatasında venv sağlamken bile fail; `where python` Windows Store stub’a düşebilir.
  - *Öneri:* Pip yalnız venv yokken veya menü `[4]`; `py -3.11` gerçek yorumlayıcı kontrolü; CLI’ye `%*` geçir.

- [x] **Onefile exe CLI’yi içermiyor; UPX + deprecated PyInstaller kwargs**
  - *Nerede:* `Ahenk.spec` `Analysis(["main.py"])`, `console=False`, `upx=True`, `win_no_prefer_redirects` / `win_private_assemblies` (PyInstaller 6’da kalkmış olabilir). `build.bat` pyinstaller pinsiz ve her başarıda `pause`.
  - *Neden:* `dist\Ahenk.exe` konsol yolu yok; imzasız UPX SmartScreen; CI derlemesi `pause` ile kilitlenir.
  - *Öneri:* GUI onefile kalsın; ayrı console spec veya `--console` debug; `upx=False`; deprecated kwargs sil; `meta.py` FileVersion; `build.bat` `/nopause`.

---

## P2 — Ürün özellikleri (kullanıma değer)

Sıra: sık kullanılan → farklılaştırıcı.

- [ ] **Transkript dışa aktar (TXT / SRT / JSONL)**
  - Duyulan + çeviri, zaman damgası. Toplantı/video sonrası asıl teslimat bu. Kopyala yetersiz.

- [ ] **Altyazı stüdyosu: punto, opaklık, 2–3 satır geçmiş, tıklama-delici (click-through)**
  - Oyun/film kullanımı için overlay tek satır ve sabit 12pt. `wraplength=520` dar.

- [ ] **Çeviri ses seviyesi ve hızlı sessiz**
  - Oynatma öncesi gain; 0 = metin-only’ye düşmeden mute. Orijinali kısmak Windows’ta sanal kablo ister — dokümante et, vaat etme.

- [ ] **Duraklat (oturumu yıkmadan)**
  - Gönderimi durdur, Gemini oturumunu açık tut; kota ve yeniden bağlanma maliyetini kes.

- [ ] **Sessizlik kapısı (VAD)**
  - RMS eşiğinin altında chunk gönderme. Canlı API faturasını düşürür; “her 20 ms PCM” modelini bozmadan.

- [ ] **Otomatik dilde algılanan kaynak dil rozeti**
  - Model `language_codes` boşken kullanıcı “ne duyulduğunu” görmüyor.

- [ ] **Gecikme HUD (yakalama → ilk çeviri sesi / ilk harf)**
  - Ağ mı, kuyruk mı, preroll mı ayırt edilir; destek ve güven için şart.

- [ ] **Oturum geçmişi (son N çeviri, arama)**
  - Paneller Temizle ile yok oluyor. Yerel SQLite veya günden günlük dosya; API’ye tekrar gitmesin.

- [ ] **Sistem tepsisi + Windows ile başlat**
  - Kapat = tepsi; global kısayol (Win+Shift+T) başlat/durdur/altyazı. Toplantı aracı kimliği.

- [ ] **İlk çalıştırma sihirbazı**
  - API anahtarı linki, aygıt seçimi, 10 sn deneme, gizlilik cümlesi (ses Google’a gider). Boş “Hazır” ekranı yetmez.

- [ ] **API anahtarı UX**
  - Yalnız son 4 karakter; “göster”; Kaydet’te format (`AIza…`) ve canlı doğrulama; başarısızsa kırmızı durum.

- [ ] **Daha fazla dil + Çince ayrımı + RTL**
  - Hindi, Lehçe, Ukraynaca, Endonezce, Vietnamca, İsveççe; `zh-CN` / `zh-TW`; Arapça için `Text` RTL. `languages.py` tek tablo kalsın.

- [ ] **Özel terimler / sözlük (glossary)**
  - Ürün adları, kişi adları. Live Translate context/system talimatı veya oturum başı metin turn’ü (SDK ne sunuyorsa).

- [ ] **Toplantı modu: loopback + mikrofon karışımı**
  - Şu an tek kaynak. İki recorder → mix → tek akış (COM thread kuralına uy: aygıt başı bir thread).

- [ ] **İki yönlü / konuşma modu (opsiyonel)**
  - Push-to-talk ile mic; hedef dilde cevap sesi. Ahenk’i “film altyazısı”ndan “canlı tercüman”a taşır. Ayrı preset.

- [ ] **CLI’yi betiklenebilir yap**
  - `--json` satır satır transcript; `--log FILE`; çıkış kodları (anahtar yok=1, aygıt yok=2). n8n / ffmpeg yanına oturur.

- [ ] **Model seçici (GUI)**
  - CLI `--model` / env var var; GUI yok. Preview model adı değişince tek yerden güncellensin (`meta` veya config).

- [ ] **Kota / kullanım özeti**
  - Oturum süresi, gönderilen ses saniyesi (yaklaşık maliyet). Faturalı API’de güven.

- [ ] **Arayüz dili (i18n)**
  - Tüm etiketler Türkçe sabit. `tr`/`en` JSON; config `ui_lang`. Dil kodları P1 maddesiyle birlikte.

- [ ] **Ana pencere always-on-top ve punto**
  - Altyazı yetmez; transkript panelleri ikinci monitörde pin + Ctrl+Fare tekerleği.

- [ ] **Hata günlüğü dosyası**
  - `%APPDATA%\Ahenk\logs\…`. Windowed exe’de traceback yok; destek mümkün değil.

---

## P2 — Profesyonelleşme (dağıtım, güvenlik, süreç)

- [ ] **LICENSE yok**
  - README “henüz yok”. Public repo için MIT (veya seçilen) şart; aksi yasal belirsizlik.

- [ ] **Sürüm 0.1.0 ve exe metadata yok**
  - `meta.py` 0.1.0; PyInstaller `version`/`file_version` yok. Windows “Dosya bilgisi” boş. Semver + CHANGELOG.

- [ ] **CI yok**
  - `pytest` yerel. GitHub Actions: 3.11/3.12, Windows, `requirements-dev.txt`. GUI testleri xvfb/offscreen zaten `withdraw` kullanıyor.

- [ ] **`pyproject.toml` yok**
  - Paket adı, requires-python, ruff/mypy, script entry (`ahenk`, `ahenk-cli`). `requirements.txt` kopyası kalmasın.

- [ ] **Kurulum: Inno Setup / winget, imza**
  - `ahenk.bat` geliştirici menüsü. Son kullanıcı `Ahenk.exe` + SmartScreen. Code signing; UPX kapat (AV yanlış pozitif, `Ahenk.spec` `upx=True`).

- [ ] **PyInstaller `optimize` ve sürüm bilgisi**
  - `excludes` kısmen var; `optimize=1` yok; deprecated `win_no_prefer_redirects` / `win_private_assemblies` duruyor.

- [ ] **README sapması**
  - Hâlâ `pytest`’i runtime bağımlılık sayıyor; `test_cli.py`, tema, `--model`, `AHENK_CONFIG`, `!Ahenk.spec` yok. TR/EN ikisini senkron tut.

- [ ] **`.env` yolu ve frozen import**
  - *Nerede:* `config.load_dotenv()` cwd’den yükler; `Ahenk.spec` `python-dotenv` hiddenimport yok.
  - *Öneri:* Exe/proje dizininden `.env`; gerekirse hiddenimport.

- [ ] **Gizlilik metni (in-app)**
  - Ses Google’a gidiyor. Hakkında veya ilk açılışta kısa onay; kota linki.

- [ ] **Çökme raporu (isteğe bağlı, PII’siz)**
  - Yerel log yeterli; telemetri yoksa “profesyonel” için crash file + kopyala butonu.

- [ ] **Otomatik güncelleme yok**
  - GitHub Release + exe hash. İmzalı olmadan riskli; en az “yeni sürüm var” bildirimi.

- [ ] **Katkı / güvenlik dokümanı**
  - `CONTRIBUTING.md`, anahtar sızdırma uyarısı, `SECURITY.md` (asıl anahtar asla issue’ya).

---

## P3 — Ölü kod, fazlalık, küçük temizlik

- [ ] **`loop.py` `MODEL` modül sabiti ölü**
  - Örnek `self.model = model or env or DEFAULT_MODEL`. `MODEL` import edilmiyor. Tek kaynak `DEFAULT_MODEL`.

- [ ] **`self._open` sözlüğü yaz-only**
  - `_handle_tr` `self._open[stream] = False`; kimse okumuyor. Konsol `_active_stream` kullanıyor. Sil.

- [ ] **`self._rail_seps` hiç doldurulmuyor**
  - Tema döngüsü no-op. Ya bağla ya alanı sil.

- [ ] **`last_level` yazılıp GUI’de okunmuyor**
  - Ya kuyruk `level`’ı kaldır ya alanı kaldır. İkisini birden bırakma.

- [ ] **Salt yazılan widget referansları**
  - `brand`, `version_lbl`, `info_btn`, `about_*` testler ve tema için lazım olabilir; tema/test kullanmayanları lokale indir.

- [ ] **`config.py` biçim**
  - `Settings` ile `config_dir` arasında boş satır yok; XOR yorumu ASCII (`Basitce acikta…`).

- [ ] **Legacy config okunuyor, taşınmıyor**
  - `LEGACY_APP_NAME = "voice_translate"` eski dosyayı okur, yeni yere yazmaz. Bir kez migrate et.

- [ ] **CLI kayıtlı dilleri okumuyor**
  - GUI `src_lang`/`dst_lang` yazar; `cli.py` bunları hiç okumaz. BCP-47’ye geçince CLI varsayılanı config’den gelsin.

- [ ] **`_pump_log` kapanışta iptal edilmiyor**
  - `after(120)` sonsuz; `destroy` sonrası TclError riski. `after_cancel`.

- [ ] **`Select` popup çoklu monitör `max(0, screen_w - w)`**
  - Yatay düzeltme negatif koordinatı keser (dikey kısmen düzelmiş).

- [ ] **Test boşlukları**
  - Donanım kopması, BCP-47 roundtrip, CLI `None` speaker, `build_config` text-only, tema ayırıcı rengi, overlay geometri, `input()` / `--no-interactive` yok.
  - `test_duplex_with_real_devices_stays_alive` gerçek aygıt + 15 sn; CI’da skip doğru, işaretle `pytest.mark.device`.
  - `FakeSession.receive` `sleep(3600)` — kırılgan; Event ile iptal daha sıkı.

- [ ] **`context_window_compression` `trigger_tokens=0` / `target_tokens=0`**
  - Agresif; uzun oturumda bağlam uçabilir. Değerleri ölç, config’e al.

- [ ] **Stereo zorlaması**
  - Recorder `channels=2`. Mono mic gereksiz kopya. Aygıta göre 1/2.

- [ ] **`ahenk.bat` menü 2 = çıplak `cli.py`**
  - Anahtarsız traceback/exit. En az `--help` ipucu.

- [ ] **`.gitattributes` / satır sonu**
  - `.bat` `crlf` belirtilmemiş; Linux checkout’ta launcher bozulabilir.

- [ ] **Eski öneri dosyasını arşivle**
  - `GELISTIRME_ONERILERI.md` çoğunlukla [x]; bu backlog ile çakışıyor. Ya “yapıldı” diye dondur ya sil; tek kaynak bu dosya kalsın.

---

## Bilinçli olarak önerme (kapsam dışı)

- Çevrimdışı / yerel Whisper “yedek”: ürün Gemini Live’a bağlı; sahte offline vaat etme.
- Orijinal hoparlörü sistem genelinde kısmak: WASAPI loopback + aynı cihaz = geri besleme/ducking ayrı ürün (VB-Cable). Dokümanda “kulaklık + ayrı çıkış” yeter.
- Mobil / web: masaüstü WASAPI kimliği bozulur.

---

## Önerilen uygulama sırası (özet)

1. Python 3.11 pin + CLI `None` aygıt + aygıt-kopma hatası + dürüst anahtar saklama.
2. Durum makinesi, text-only modality, kuyruk sadeleştirme, açılış async tarama, tema/hover/ayırıcı.
3. LICENSE, CHANGELOG, CI, README senkron, UPX kapat.
4. SRT dışa aktar, overlay punto/opaklık, volume, pause, VAD, tepsi.
5. Toplantı karışımı, glossary, i18n, installer.

Her madde bağımsız PR olabilir; 1 ve 2 olmadan 4–5 “özellik” üzerine yeni borç biner.
