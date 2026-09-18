# Ahenk — Proje İnceleme Bulguları

İnceleme tarihi: 18 Eylül 2026  
Kapsam: ses/çeviri akışı, arayüz, güvenlik/güncelleme, paketleme/CLI ve testler.

## Özet

En önemli sorunlar: durdurma ve yeniden başlatma yarışları, güncellemede geri dönüş dosyasının erken silinmesi, transkript kaybı ve API anahtarının korumasız kaydedilebilmesi.

İnceleme dört hafif `scout` ajanıyla paralel yürütüldü. Önemli bulgular ayrıca kaynak üzerinden ve izole çalıştırmalarla doğrulandı. İnceleme sırasında uygulama kodu değiştirilmedi. Bu belge düzeltme uygulamaz; bulguları ve önerilen düzeltmeleri kaydeder.

Dosya ve satır referansları inceleme anındaki kaynaklara aittir; sonraki değişikliklerde kayabilir.

### İnceleme sonrası düzeltmeler

- **H01 düzeltildi (18 Eylül 2026).**
- **H02 düzeltildi (18 Eylül 2026).**
- **H03 düzeltildi (18 Eylül 2026).**
- **H04 düzeltildi (18 Eylül 2026).**
- **H05 düzeltildi (18 Eylül 2026).**
- **H06 düzeltildi (18 Eylül 2026).**
- **H07 düzeltildi (18 Eylül 2026).** 1. maddedeki (Yüksek öncelikli hatalar) tüm bulgular (H01-H07) tamamlandı.
- **H08–H17 düzeltildi (18 Eylül 2026).** 2. maddedeki (Diğer doğrulanmış hatalar) tüm bulgular (H08-H17) tamamlandı.
- **H18–H23 düzeltildi (18 Eylül 2026).** 3. maddedeki (Paketleme ve CLI hataları) tüm bulgular (H18-H23) tamamlandı.
- **G01–G06 düzeltildi (18 Eylül 2026).** 4. maddedeki (Güvenlik, test ve bakım geliştirmeleri) tüm bulgular (G01-G06) tamamlandı.
- **R01–R05 düzeltildi (18 Eylül 2026).** 5. maddedeki (Canlı ortamda doğrulanmamış riskler) tüm bulgular (R01-R05) tamamlandı.
- Çalıştırılan mevcut test komutu: `venv/Scripts/python.exe -m pytest -q -m "not device"`.
- Sonuç: **86 geçti, 1 donanım testi dışarıda bırakıldı, 1 bağımlılık uyarısı**. Uyarı, `google.genai.types` içindeki `_UnionGenericAlias` kullanımının Python 3.17 için kullanımdan kaldırılmasına ilişkindi.
- Gerçek Tk arayüzünde dışa aktarma, tema, aygıt seçimi, oturum olayları, İngilizce ayarı ve klavye olayları çalıştırıldı.
- Ses, bağlantı, güncelleme ve hata senaryolarında kontrollü sahte uçlar kullanıldı; gerçek uygulama işlevleri çağrıldı.
- Wheel derlemesi geçici proje kopyasında denendi.
- Windows batch davranışları izole kontrol senaryoları ve geçici başlatıcı kopyalarıyla sınandı.
- Canlı Gemini, fiziksel ses yakalama/oynatma ve gerçek paketlenmiş EXE güncellemesi denenmedi.
- Ekran okuyucu, yüksek DPI ve çoklu monitör için görsel doğrulama yapılmadı.
- Kod grafiği keşif için kullanıldı. Kapsam kontrollerindeki güncellik uyarıları nedeniyle maddi bulgular doğrudan kaynak okumalarıyla desteklendi.
- Geçici kontrol dosyaları kalıcı test olarak projeye eklenmedi.

### Kanıt sınıfları

- **Çalıştırmayla doğrulandı:** Belirtilen davranış gerçek işlev veya izole senaryo çalıştırılarak gözlendi. Canlı servis/donanım doğrulaması anlamına gelmez.
- **Kaynak üzerinden doğrulandı:** Davranış ilgili kaynak ve çağrı akışında görüldü; uçtan uca çalıştırılmadı.
- **Koşullu risk:** Kodda riskli koşul mevcut; üretimde ortaya çıkması zamanlama, servis veya platform davranışına bağlı.

## 1. Yüksek öncelikli hatalar

### H01 (Düzeltildi) — Bağlantı kurulurken Durdur isteği kayboluyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** `run()` bağlantıdan önce stop olayını ve iptal bekleyicisini oluşturuyor. Önceden verilmiş stop isteği bağlantı açılmasını engelliyor; bağlantı sırasında stop, bekleyen bağlantıyı iptal ediyor. Bağlantı girişi tamamlanırken kalıcı istek yeniden kontrol ediliyor; capture/playback stop işaretleri artık temizlenmiyor. İptal bekleyicisi oturum sonunda iptal edilip bekleniyor. GUI ve CLI'nın mevcut `CancelledError` sözleşmesi korunuyor.
- **Regresyon kapsamı:** `tests/test_live_translate.py::test_stop_prevents_audio_start_during_connection`; run öncesi, bağlantı beklerken ve bağlantı tamamlanırken stop. Her sınır konsol girişi açık/kapalı olarak çalıştırıldı; ses görevlerinin başlamaması, ses gönderilmemesi ve bağlantı temizliği denetlendi.
- **Doğrulama:** Donanımsız test takımı: **92 geçti, 1 donanım testi dışarıda bırakıldı**. Mevcut SDK deprecation uyarısı sürüyor. Canlı Gemini ve fiziksel ses aygıtları denenmedi.

- **Konum:** `loop.py:165-180`, `loop.py:515-536`.
- **Sorun:** Bağlantı henüz kurulmamışken `request_stop()` durdurma işaretlerini set ediyor. Bağlantı tamamlanınca `run()` işaretleri temizleyip görevleri başlatıyor; kalıcı `_user_stop` isteği kontrol edilmiyor.
- **Etki:** Kullanıcı durdurduğunu düşünürken kayıt ve gönderim başlayabilir.
- **Kanıt:** Geciktirilmiş bağlantı senaryosunda stop isteğine rağmen oturum çalışmaya devam etti; capture stop işareti temizlendi.
- **Öneri:** Durdurma olayını bağlantıdan önce oluşturmak; bağlantı sonrasında kalıcı stop isteğini kontrol etmek. Bekleyen bağlantıyı da iptal edebilmek.

### H02 (Düzeltildi) — Eski kapanış mesajı yeni oturumun referanslarını silebiliyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** Oturum kimliği (`_session_id`) eklendi. `_run()` kapanış mesajını `("__stopped__", session_id)` olarak iletiyor. `_pump_log()` eski oturumlara ait kapanış mesajlarını yok sayıyor. `restart()` keyfi 1,2 saniyelik thread/join yerine olay güdümlü (`_pending_restart`) hale getirildi; eski worker durduğunda yeni oturum hemen başlatılıyor. Açık `stop()` çağrısı bekleyen yeniden başlatmayı ve debounce zamanlayıcısını iptal ediyor.
- **Regresyon kapsamı:** `tests/test_gui.py::test_stale_stopped_message_does_not_clear_new_session`, `tests/test_gui.py::test_restart_lifecycle_and_user_stop_cancellation`.
- **Doğrulama:** Donanımsız test takımı: **94 geçti, 1 donanım testi dışarıda bırakıldı**.

- **Konum:** `gui/app.py:809-822`, `gui/app.py:974-979`, `gui/app.py:1246`.
- **Sorun:** Yeniden başlatma eski worker için 1,2 saniye bekleyip zamanlayıcıyla `start()` çağırıyor. Kapanış mesajı yalnız `__stopped__`; hangi oturuma ait olduğu bilinmiyor.
- **Tetikleyiciler:** Yavaş kapanışta yeni başlangıç reddediliyor ve tekrar denenmiyor. Yeni oturum eski kapanış mesajı işlenmeden başlarsa mesaj yeni `worker` ve `loop_obj` referanslarını temizliyor.
- **Etki:** Arayüz durdu gösterirken oturum çalışabilir; durdurma kontrolü kaybolabilir veya ikinci worker başlatılabilir.
- **Kanıt:** Eski kapanış mesajının mevcut worker referanslarını sildiği çalıştırmayla doğrulandı. Gerçek yarışın oluşması zamanlamaya bağlı.
- **Öneri:** Oturum kimliği taşıyan olaylar kullanmak. Yeniden başlatmayı yalnız ilgili kapanış işlendiğinde yapmak; açık kullanıcı stop isteği bekleyen yeniden başlatmayı iptal etmeli.

### H03 (Düzeltildi) — Güncelleme temizliği geri dönüş dosyasını erken siliyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** `cleanup_previous_update()` artık hazır işaretini (`ready`) ve geri dönüş yedeğini (`.old`) silme adaylarına eklemiyor; yalnız helper geçici dosyasını siliyor. `ready` dosyasını helper kendi `finally` bloğunda yönetiyor, `.old` yedeğini ise helper yeni sürümün başladığını teyit ettikten sonra siliyor. Helper içinde başlatma başarısız olduğunda yedek dosya yoksa `target` silinmiyor, mevcut dosya korunarak hata bildiriliyor.
- **Regresyon kapsamı:** `tests/test_updater.py::test_update_helper_does_not_delete_target_if_backup_is_missing_on_failed_start`, `tests/test_updater.py::test_cleanup_previous_update_touches_ready_without_deleting_backup_or_ready`.

- **Konum:** `updater.py:306-329`, `updater.py:373-390`, `updater.py:403-429`.
- **Sorun:** Yeni uygulama hazır işaretini oluşturuyor; üç saniye sonra helper onayı beklemeden hem işareti hem `.old` yedeğini siliyor. Helper bu pencereyi kaçırırsa yeni sürümü başarısız sayıp mevcut EXE'yi silerek artık bulunmayan yedeği geri yüklemeye çalışabiliyor.
- **Etki:** Normal uygulama EXE'si ve geri dönüş yedeği birlikte kaybolabilir.
- **Kanıt:** Gerçek temizlik işlevinin onaysız silmesi doğrulandı. Kaçırılmış hazır bildirimi simülasyonunda hedef EXE kalmadı.
- **Sınır:** Her güncellemede oluşan hata değildir. Helper gecikmesi veya askıya alınması gibi zamanlama koşulu gerekir. Gerçek paketlenmiş EXE güncellemesi çalıştırılmadı.
- **Öneri:** Hazır işareti ve yedek temizliğini helper yönetmeli. Geri dönüş güvencesi olmadan mevcut EXE silinmemeli.

### H04 (Düzeltildi) — DPAPI başarısızlığında API anahtarı sessizce düz metin kaydediliyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** Windows'ta `_dpapi_protect` başarısız olduğunda `_encrypt_key()` sessizce düz metne dönmek yerine `OSError` fırlatıyor. `save_api_key()` ve `save()` yazma yapmadan hata veriyor, mevcut dosya içeriği korunuyor. Arayüzde `save_key` ve `start` bu hatayı yakalayarak kullanıcıya güvenli kayıt yapılamadığını bildiriyor.
- **Regresyon kapsamı:** `tests/test_config.py::test_dpapi_failure_raises_oserror_and_does_not_save_plaintext`.

- **Konum:** `config.py:75-85`, `config.py:164-175`.
- **Sorun:** Şifreleme hatası yutuluyor; `_encrypt_key()` düz anahtarı döndürüyor. Windows'ta Unix `0600` izni yolu da uygulanmıyor.
- **Etki:** Belgelenen DPAPI koruması kullanıcıya bildirilmeden devre dışı kalıyor. Dosya, profil veya yedek erişiminde anahtar açığa çıkabilir; bu bulgu uzaktan kod yürütme iddiası değildir.
- **Kanıt:** DPAPI hatası üretildiğinde sahte anahtar JSON'a düz yazıldı.
- **Öneri:** Windows'ta şifreleme başarısızsa kaydı reddetmek, mevcut dosyayı korumak ve kullanıcıya hata göstermek.

### H05 (Düzeltildi) — Farklı çıkış aygıtında bile kaynak ses atılıyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** `_is_same_endpoint()` fonksiyonu eklendi; giriş (loopback) ile çıkış aygıtının aygıt kimliği (`id`) veya adı (`name`) üzerinden aynı fiziksel uca ait olup olmadığı denetleniyor. Yalnızca giriş loopback VE çıkış aynı uç ise oynatma sırasında yakalanan blok bastırılıyor; çıkış farklı bir aygıtsa (ör. kulaklık) kaynak ses kesintisiz yakalanıyor.
- **Regresyon kapsamı:** `tests/test_live_translate.py::test_capture_does_not_drop_when_output_speaker_is_different_device`.

- **Konum:** `loop.py:240-255`.
- **Sorun:** Yankı önleme yalnız loopback giriş ve herhangi bir çıkış olup olmadığını kontrol ediyor. Giriş ve çıkışın aynı fiziksel uç olması aranmıyor.
- **Etki:** Kaynak hoparlör A, çeviri kulaklık B olsa bile çeviri oynarken kaynak konuşma parçaları kayboluyor.
- **Kanıt:** Ayrı çıkış senaryosunda yakalanan blok gönderilmeden atıldı. Fiziksel aygıtlarla denenmedi.
- **Öneri:** Sabit aygıt kimlikleriyle aynı uç eşleşmesini kontrol etmek; yalnız gerektiğinde bastırmak.

### H06 (Düzeltildi) — Görünen son cümle dışa aktarılmayabiliyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** `_get_export_items()` metodu eklendi. Tamamlanmış kayıtlarla birlikte devam eden `_curr_heard_buf` ve `_curr_trans_buf` tamponları anlık olarak birleştirilerek dışa aktarılıyor. Ayrıca oturum kapandığında (`__stopped__`) bekleyen tamponlar `transcript_items` içine aktarılıp tamponlar sıfırlanıyor; böylece duplikasyon olmadan tüm görünen cümleler TXT/SRT/JSONL çıktılarına yansıtılıyor.
- **Regresyon kapsamı:** `tests/test_gui.py::test_export_includes_pending_buffer_and_flushes_on_stop`.

- **Konum:** `gui/app.py:723-735`, `gui/app.py:984-1009`.
- **Sorun:** Tamamlanan kayıtlar `transcript_items` içinde; devam eden cümleler ayrı tamponlarda. Liste boş değilse dışa aktarma bu tamponları dikkate almıyor.
- **Etki:** Durdurma veya bağlantı kopması sonrasında ekrandaki son metin TXT, SRT ve JSONL dosyalarında eksik kalabilir.
- **Kanıt:** Ekranda görünen ikinci, tamamlanmamış cümle dışa aktarılmadı.
- **Öneri:** Dışa aktarma anında tamamlanmış kayıtlarla bekleyen parçaları birleştiren, tekrar ekleme yapmayan tutarlı bir görünüm oluşturmak.

### H07 (Düzeltildi) — Tema değişimi çeviri metnini okunamaz hale getiriyor

- **Durum:** Düzeltildi — 18 Eylül 2026. Aşağıdaki sorun ve kanıt özgün inceleme durumunu anlatır.
- **Uygulanan değişiklik:** `_refresh_theme()` içinde `self.heard` ve `self.trans` Text widget'larının `"body"` tag foreground rengi güncel `C.text` rengine ayarlandı (açık temada `#1a1d20`, koyu temada `#e8e8e8`). `gui/theme.py` içindeki açık tema `LIGHT["overlay_bg"]` rengi `#ffffff` olarak güncellendi ve altyazı başlığı/düğmelerinin (`_overlay_hdr`, `_overlay_thru_btn`, `_overlay_fplus`, `_overlay_fminus`) temayla birlikte güncellenmesi sağlandı; böylece hem ana metinde hem altyazıda yüksek kontrast ve okunabilirlik garantilendi.
- **Regresyon kapsamı:** `tests/test_gui.py::test_theme_toggle_updates_body_tag_and_overlay_contrast`.

- **Konum:** `gui/app.py:409`, `gui/app.py:923-932`, `gui/app.py:958-963`, `gui/theme.py:44-60`.
- **Sorun:** Tema değişince Text widget rengi güncelleniyor; onu geçersiz kılan `body` etiketi eski renkte kalıyor. Açık temadaki altyazı da koyu zeminde koyu yazı kullanıyor.
- **Kanıt:** Gerçek Tk widget'larında etiketin eski renk tuttuğu doğrulandı. Renklerden hesaplanan kontrast ana metinde yaklaşık **1,13:1**, açık tema altyazısında **1,07:1**.
- **Etki:** Çeviri çıktısının okunabilirliği ciddi biçimde düşüyor.
- **Öneri:** Metin etiketlerini de tema ile güncellemek; altyazıya uyumlu ön/arka plan çifti vermek.

## 2. Diğer doğrulanmış hatalar

| Kimlik | Sorun ve konum | Kanıt ve etki | Önerilen düzeltme |
| --- | --- | --- | --- |
| H08 (Düzeltildi) | Durdurmak SRT zamanlarını değiştiriyor. `gui/app.py:1248-1250`, `export.py:42-46`. | Aynı ilk altyazı durdurmadan önce yaklaşık `00:00:10`, sonra `00:00:00` oldu. Çalıştırmayla doğrulandı. | Sayaç durumuyla kalıcı oturum başlangıcı ayrıldı; durdurma sonrası SRT oturum başı bazını koruyor. Regresyon testi: `tests/test_gui.py::test_h08_srt_export_preserves_timeline_base_after_stop`. |
| H09 (Düzeltildi) | Ayar değiştirerek yeniden başlatmak transkripti siliyor. `gui/app.py:809-822`, `1186-1192`. | Aygıt/dil değişimi normal `start()` yoluna giriyor; paneller, kayıtlar ve zaman başlangıcı sıfırlanıyor. Kaynak üzerinden doğrulandı. | Runtime restart çağrılarında transkript ve paneller korunuyor (`preserve_transcript=True`). Regresyon testi: `tests/test_gui.py::test_h09_runtime_restart_preserves_transcripts_and_panes`. |
| H10 (Düzeltildi) | Temizle yalnız ekranı temizliyor. `gui/app.py:624-629`, `723`. | Panel boşaldıktan sonra eski cümle dışa aktarılmaya devam etti. Çalıştırmayla doğrulandı. | `_clear_pane()` ilgili Text widget'ının yanı sıra `transcript_items` ve tamponları da siliyor. Regresyon testi: `tests/test_gui.py::test_h10_clear_pane_clears_transcript_items_and_buffers`. |
| H11 (Düzeltildi) | Transkript odağında F5 ve Tab çalışmıyor. `gui/app.py:416-424`. | Genel `<Key>` engeli gezinmeyi ve kök kısayollarını kesiyor. Gerçek Tk olaylarında F5 engellendi, Tab odağı panelden çıkaramadı. | `_lock_text()` fonksiyonu F1-F12, Tab, yön tuşları ve genel kısayolları geçiriyor; yalnız metin düzenleme tuşlarını engelliyor. Regresyon testi: `tests/test_gui.py::test_h11_lock_text_allows_navigation_and_shortcuts`. |
| H12 (Düzeltildi) | Aygıt yenileme güncel seçimi geri alıyor. `gui/app.py:539-578`. | Başlangıçtaki `_cfg` kullanılıyor. B seçilip kaydedildikten sonra yenileme A'ya döndü. Çalıştırmayla doğrulandı. | Yenileme sırasında kullanıcının mevcut geçerli seçimi listede varsa korunuyor. Regresyon testi: `tests/test_gui.py::test_h12_device_refresh_preserves_current_selection`. |
| H13 (Düzeltildi) | Örnekleme dönüşümü yüksek frekansları yanlış banda taşıyor. `audio.py:50-74`. | Üretim yolu anti-alias filtresi olmadan örnek azaltıyor. 12 kHz giriş, 16 kHz çıkışta güçlü 4 kHz bileşene dönüştü. Sayısal sinyalle doğrulandı; tanıma kalitesindeki etki ölçülmedi. | `AudioConverter` içinde durum koruyan 41-tap FIR pencerelemeli sinc alçak geçiren filtre eklendi; 12 kHz aliased bileşeni -60 dB zayıflatıldı. Regresyon testi: `tests/test_live_translate.py::test_h13_audio_converter_anti_aliasing`. |
| H14 (Düzeltildi) | Ön tampon mute kontrolünü atlıyor; kuyruk sonuna kazanç iki kez uygulanıyor. `loop.py:415-450`. | Mute sonrası bekleyen ses gönderildi; `volume=0.5` için son parçanın etkin kazancı `0.25` oldu. Kontrollü oynatıcıyla doğrulandı. | `_play_thread` içinde tampon ham tutuluyor; ses kazancı ve mute oynatma anında tek noktadan (`_play_chunk`) uygulanıyor. Regresyon testi: `tests/test_live_translate.py::test_h14_play_thread_single_volume_scaling_and_mute_preroll`. |
| H15 (Düzeltildi) | Geçerli JSON içindeki bozuk ayar uygulamayı açtırmıyor. `config.py:191-192`, `gui/app.py:84-90`. | `overlay_font_size="bad"` doğrudan `ValueError` üretti. Arayüz oluşturulmadan config okunuyor. | `_safe_int`, `_safe_float` ve tip/aralık doğrulaması eklendi; bozuk veya sınır dışı değerlerde güvenli varsayılanlara düşülüyor. Regresyon testi: `tests/test_config.py::test_h15_malformed_config_values_fall_back_safely`. |
| H16 (Düzeltildi) | Bozuk config üzerine tercih kaydı eski veriyi yok ediyor. `config.py:140-169`, `220-260`. | Okuma hatası boş sözlük sayılıyor; sonraki tercih kaydı dosyanın tamamını değiştiriyor. İzole dosyada doğrulandı. | Dosya okunamadığında `.bak` yedeği oluşturuluyor ve ham metinden `api_key` dahil kurtarılabilen alanlar kurtarılıyor. Regresyon testi: `tests/test_config.py::test_h16_corrupt_config_is_backed_up_and_salvages_keys`. |
| H17 (Düzeltildi) | İngilizce arayüz ayarı uygulanmıyor. `gui/app.py:131`, `i18n.py:36-65`. | `ui_lang="en"` iken gerçek etiketler `Hazır / Duyulan / Çeviri` kaldı. | Arayüzdeki tüm butonlar, etiketler ve durum metinleri `t()` fonksiyonuna bağlandı; `ui_lang="en"` ayarı tam uygulandı. Regresyon testi: `tests/test_gui.py::test_h17_ui_lang_en_applies_to_all_gui_labels`. |

## 3. Paketleme ve CLI hataları

| Kimlik | Sorun ve konum | Kanıt | Önerilen düzeltme |
| --- | --- | --- | --- |
| H18 (Düzeltildi) | Wheel/pip paketleme bozuk. `pyproject.toml:1-22`, `main.py:12-22`. | İzole derleme `Multiple top-level packages discovered in a flat-layout: ['gui', 'assets']` hatası verdi. Ayrıca tanımlanan `main:main` için `main.py` içinde `main()` yok. | `pyproject.toml` içinde `tool.setuptools` paket ve modül listesi açık tanımlandı. `main.py` içine CLI helper yönlendirmesini içeren `main()` işlevi eklendi. Regresyon testi: `tests/test_cli.py::test_h18_main_entrypoint_exists_and_routes_helper`. |
| H19 (Düzeltildi) | Temiz ortamda doğrudan `build.bat` başlangıcı bozuk. `build.bat:15-23`. | Aynı parantez bloğunda set edilen `%SYSPY%` erken genişletiliyor. Kontrol senaryosu `'-m' is not recognized` verdi. Tetikleyici: mevcut venv ve kalıtılmış `SYSPY` yok. | venv oluşturma adımı ayrı bir alt yordama (`:init_venv`) taşındı; erken blok genişletme hatası giderildi. |
| H20 (Düzeltildi) | Başlatıcı hata kodunu kaybediyor. `ahenk.bat:17-27`. | Alt komutun `7` çıkış kodu izole başlatıcı kontrolünde `0` döndü. | Parantez içi `%errorlevel%` erken genişletmesi kaldırıldı; işlem bittikten sonra doğrudan alt işlem çıkış kodu döndürülüyor. Regresyon testi: `tests/test_cli.py::test_h20_h21_batch_launcher_preserves_exit_code_and_arguments`. |
| H21 (Düzeltildi) | Başlatıcı argümanları kesiyor. `ahenk.bat:17-23`. | `cli` yolunda yalnız `%2`–`%9` iletiliyor; dokuzuncu CLI tokenı doğrulamada kayboldu. | `%*` argümanları Python çalıştırıcısı üzerinden tırnakları ve sayısı korunarak kayıpsız iletiliyor. Regresyon testi: `tests/test_cli.py::test_h20_h21_batch_launcher_preserves_exit_code_and_arguments`. |
| H22 (Düzeltildi) | Çince dil kodları CLI'da reddediliyor. `cli.py:84-92`, `languages.py:20-21`. | Girdi küçük harfe çevriliyor; geçerli kümede `zh-CN/zh-TW` kalıyor. `--dst zh-CN` kontrollü çalıştırmada çıkış kodu 1 verdi. | `cli.py` içinde büyük/küçük harf duyarsız normalizasyondan kanonik BCP-47 koduna (`zh-CN`, `zh-TW`) eşleme eklendi. Regresyon testi: `tests/test_cli.py::test_h22_chinese_language_codes_accepted`. |
| H23 (Düzeltildi) | `--json` çıktısı normal duruşta bozuluyor. `cli.py:163-170`. | stdout'a JSON yerine `Durduruldu.` yazılıyor. İptal senaryosunda doğrulandı. | `--json` modunda durdurma mesajı `stderr`'e yönlendirildi; stdout saf JSON akışı olarak korundu. Regresyon testi: `tests/test_cli.py::test_h23_json_mode_routes_stop_message_to_stderr`. |

## 4. Güvenlik, test ve bakım geliştirmeleri

### G01 (Düzeltildi) — Konuşma geçmişinin kaydı açık ve yönetilebilir olmalı

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `logger.py`, `config.py`, `gui/app.py`.
- **Uygulanan değişiklik:** Günlük dosyaları `RotatingFileHandler` ile sınırlandırıldı (1 MB, 2 yedek). Konuşma geçmişi için dosya boyutu kontrolü (2 MB üstünde `.jsonl.1` rotasyonu), dosyanın tamamını belleğe almadan sondan öne parçalı okuma (`load_recent_history`) ve `clear_history()` işlevi eklendi. `config.py` ve `gui/app.py` içine `save_history` tercihi eklendi. Regresyon testi: `tests/test_logger_i18n.py::test_logger_and_history_persistence`.
### G02 (Düzeltildi) — Test izolasyonu gerçek config dosyasına yazabilir

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `tests/conftest.py`, `tests/test_config.py:8-12`, `tests/test_gui.py`.
- **Uygulanan değişiklik:** Global `conftest.py` içine tüm testlerde otomatik çalışan (`autouse=True`) ortam izolasyonu eklendi. Hem `AHENK_CONFIG` hem de `VOICE_TRANSLATE_CONFIG` geçici sandbox yoluna yönlendirildi; testlerin gerçek AppData config'ine yazması kesin olarak engellendi. Regresyon testi: `tests/test_config.py::test_g02_ahenk_config_priority_and_isolation`.
### G03 (Düzeltildi) — Bazı testler uygulama davranışını değil, test içindeki taklidi doğruluyor

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `tests/test_live_translate.py:444-476`.
- **Uygulanan değişiklik:** Sentetik taklit testler kaldırıldı; doğrudan üretim kodundaki `loop_obj.receive()` metodunu çağıran ve dolu kuyrukta en eski verinin atılıp yeni verinin eklendiğini doğrulayan `test_queue_drop_oldest_on_full_via_receive` yazıldı.
### G04 (Düzeltildi) — CI dağıtılan ürünü de çalıştırmalı

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `.github/workflows/ci.yml:30-38`, `.github/workflows/release.yml:52-80`.
- **Uygulanan değişiklik:** CI iş akışına `build` ile wheel üretimi, wheel'in izole kurulumu ve `ahenk-cli --version` / `ahenk-cli --list-langs` çalıştırma adımı eklendi. Release iş akışına `Ahenk-cli.exe` doğrulaması, SHA-256 sağlama üretimi ve release varlıklarına eklenmesi sağlandı.
### G05 (Düzeltildi) — Bağımlılık sözleşmeleri aynı olmalı

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `pyproject.toml:13-18`, `requirements.txt:1-4`.
- **Uygulanan değişiklik:** `pyproject.toml` içindeki `dependencies` girdileri `requirements.txt` ile birebir tutarlı sürümlere (`google-genai>=2.0,<3.0`, `soundcard>=0.4.3`, `numpy>=1.26,<3.0`, `python-dotenv>=1.0`) eşitlendi.
### G06 (Düzeltildi) — Ses gecikmesi mesaj sayısıyla değil süreyle sınırlandırılmalı

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `loop.py:97-128`, `loop.py:502`.
- **Uygulanan değişiklik:** `loop.py` içine `BoundedByteQueue` sınıfı eklendi. Ses oynatma kuyruğu 2,5 saniyelik PCM byte bütçesiyle (~120 KB) sınırlandı; bütçeyi aşan gecikmiş paketler kuyruktan otomatik olarak atılarak ses gecikmesi birikimi önlendi. Regresyon testi: `tests/test_live_translate.py::test_g06_bounded_byte_queue_caps_latency`.
## 5. Canlı ortamda doğrulanmamış riskler

Aşağıdaki maddeler kesin üretim arızası olarak değerlendirilmemeli.

### R01 (Düzeltildi) — VAD veya pause sonrasında cümle bitişi gecikebilir

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `loop.py:323-328`.
- **Uygulanan değişiklik:** Konuşma kesildiğinde ilk 15 parça (~300 ms hangover) atlanmadan Gemini VAD'e gönderiliyor; böylece cümlenin bittiği sunucu tarafında gecikmeksizin algılanıyor ve ardından paket tasarrufuna geçiliyor. Regresyon testi: `tests/test_live_translate.py::test_r01_vad_hangover_silence_chunks_sent_before_dropping`.
### R02 (Düzeltildi) — Tekrarlı transkript parçaları kaybolabilir

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `loop.py:73-79`.
- **Uygulanan değişiklik:** `merge_transcript` fonksiyonunda `len(incoming) > len(prev)` koşulu eklendi. Yalnızca kümülatif olarak büyüyen parçalar kesilirken, peş peşe gelen yinelenen kelimeler ("ha", "no", "bye bye" vb.) silinmeden korunuyor. Regresyon testi: `tests/test_live_translate.py::test_r02_merge_transcript_preserves_repeated_words`.
### R03 (Düzeltildi) — Yardımcı worker'ların Tk erişimi kapanışta yarışabilir

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `gui/app.py:536-544`, `gui/app.py:732-741`, `gui/app.py:1088-1096`.
- **Uygulanan değişiklik:** Aygıt tarama (`refresh_devices`) ve API anahtarı doğrulama (`_test_api_key`) arka plan thread'lerinden doğrudan `self.after()` çağırmak yerine sonuçları `self.log_queue` kuyruğuna aktarıyor; tüm UI güncellemeleri ana Tk iş parçacığındaki `_pump_log` üzerinden güvenle uygulanıyor. Regresyon testi: `tests/test_gui.py::test_r03_background_scans_routed_through_queue_without_direct_after`.
### R04 (Düzeltildi) — SDK istemcileri açıkça kapatılmıyor

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `loop.py:608-625`.
- **Uygulanan değişiklik:** `SystemAudioLoop.run()` `finally` bloğu içine `client.aio.aclose()` ve `client.close()` çağrıları eklendi. Ayrıca dışarıdan güvenli kapatma için `SystemAudioLoop.close()` metodu sağlandı. Regresyon testi: `tests/test_live_translate.py::test_r04_loop_close_and_finally_closes_client`.
### R05 (Düzeltildi) — Yüksek DPI'da özel seçim penceresi kırpılabilir

- **Durum:** Düzeltildi — 18 Eylül 2026.
- **Konum:** `gui/widgets.py:204-284`.
- **Uygulanan değişiklik:** Sabit `row_h = 24` yerine `font.metrics("linespace")` ile DPI-ölçekli gerçek satır yüksekliği ölçülüyor. Ekran çalışma alanı (`winfo_screenheight`) hesaplanarak aşağıda yer yoksa yukarı açılma, ekran dışına taşmayı önleyen koordinat sınırlandırması ve gerektiğinde dinamik kaydırma (`needs_scroll`) uygulandı. Regresyon testi: `tests/test_gui.py::test_r05_select_widget_measures_font_and_bounds_popup`.
## 6. Korunması gereken iyi taraflar

- Ses kayıt ve oynatma bağlamları ayrı, sahipliği belirli thread'lerde tutuluyor.
- Ses aygıtı hataları async akışa taşınıyor.
- Güncellemede boyut, SHA-256 ve GitHub adres kontrolleri mevcut. İncelenen yollarda sıradan bir uzak hash doğrulama atlatması bulunmadı; bu kapsamlı güvenlik garantisi değildir.
- Ana GUI/worker iletişiminde yeniden kullanılabilir kuyruk altyapısı var.
- Yeniden deneme beklemesi stop isteğiyle kesilebiliyor.
- Test altyapısı çalışıyor. Asıl açık, yaşam döngüsü ve dağıtım sınırlarının kapsamı.

## 7. Önerilen düzeltme sırası

1. **Durdurma ve oturum sahipliği:** H01, H02. Kayıt/gönderim kontrolünü ve tek oturum sahipliğini güvenilir hale getir.
2. **Güncelleme geri dönüşü ve anahtar koruması:** H03, H04. EXE kaybını ve sessiz şifreleme düşüşünü engelle.
3. **Transkript bütünlüğü:** H06, H08, H09, H10. Görünen, saklanan ve dışa aktarılan metni tutarlı yap.
4. **Ses doğruluğu:** H05, H13, H14. Aygıt eşlemesi, anti-alias filtreleme ve playback sınır davranışlarını düzelt.
5. **Arayüz kullanılabilirliği ve config güvenilirliği:** H07, H11, H12, H15, H16, H17.
6. **Paketleme ve CLI:** H18–H23. Kurulum, başlatıcı ve makine tarafından tüketilen çıktıları düzelt.
7. **Test, gizlilik ve dağıtım sınırları:** G01–G06. Özellikle G02 test izolasyonunu yeni test çalıştırmalarından önce güvenceye al.
8. **Canlı servis ve platform doğrulaması:** R01–R05. Hipotezleri gerçek Gemini, fiziksel aygıtlar ve hedef Windows ölçeklerinde doğrula.

Bu sıralama özgün düzeltme önerisidir. İnceleme sırasında düzeltme uygulanmadı; inceleme sonrasında H01–H23, G01–G06 ve R01–R05 arasındaki tüm bulgular ve riskler başarıyla tamamlandı.
