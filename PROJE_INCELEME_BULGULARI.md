# Ahenk — Proje İnceleme Bulguları

İnceleme tarihi: 18 Eylül 2026  
Kapsam: ses/çeviri akışı, arayüz, güvenlik/güncelleme, paketleme/CLI ve testler.

## Özet

En önemli sorunlar: durdurma ve yeniden başlatma yarışları, güncellemede geri dönüş dosyasının erken silinmesi, transkript kaybı ve API anahtarının korumasız kaydedilebilmesi.

İnceleme dört hafif `scout` ajanıyla paralel yürütüldü. Önemli bulgular ayrıca kaynak üzerinden ve izole çalıştırmalarla doğrulandı. İnceleme sırasında uygulama kodu değiştirilmedi. Bu belge düzeltme uygulamaz; bulguları ve önerilen düzeltmeleri kaydeder.

Dosya ve satır referansları inceleme anındaki kaynaklara aittir; sonraki değişikliklerde kayabilir.

### İnceleme sonrası düzeltmeler

- **H01 düzeltildi (18 Eylül 2026).**
- **H02 düzeltildi (18 Eylül 2026).** Diğer maddeler bu değişiklikler kapsamında ele alınmadı.
## Doğrulama kapsamı ve sınırlar

- Ortam: Windows, Python 3.14.7.
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

### H03 — Güncelleme temizliği geri dönüş dosyasını erken siliyor

- **Konum:** `updater.py:306-329`, `updater.py:373-390`, `updater.py:403-429`.
- **Sorun:** Yeni uygulama hazır işaretini oluşturuyor; üç saniye sonra helper onayı beklemeden hem işareti hem `.old` yedeğini siliyor. Helper bu pencereyi kaçırırsa yeni sürümü başarısız sayıp mevcut EXE'yi silerek artık bulunmayan yedeği geri yüklemeye çalışabiliyor.
- **Etki:** Normal uygulama EXE'si ve geri dönüş yedeği birlikte kaybolabilir.
- **Kanıt:** Gerçek temizlik işlevinin onaysız silmesi doğrulandı. Kaçırılmış hazır bildirimi simülasyonunda hedef EXE kalmadı.
- **Sınır:** Her güncellemede oluşan hata değildir. Helper gecikmesi veya askıya alınması gibi zamanlama koşulu gerekir. Gerçek paketlenmiş EXE güncellemesi çalıştırılmadı.
- **Öneri:** Hazır işareti ve yedek temizliğini helper yönetmeli. Geri dönüş güvencesi olmadan mevcut EXE silinmemeli.

### H04 — DPAPI başarısızlığında API anahtarı sessizce düz metin kaydediliyor

- **Konum:** `config.py:75-85`, `config.py:164-175`.
- **Sorun:** Şifreleme hatası yutuluyor; `_encrypt_key()` düz anahtarı döndürüyor. Windows'ta Unix `0600` izni yolu da uygulanmıyor.
- **Etki:** Belgelenen DPAPI koruması kullanıcıya bildirilmeden devre dışı kalıyor. Dosya, profil veya yedek erişiminde anahtar açığa çıkabilir; bu bulgu uzaktan kod yürütme iddiası değildir.
- **Kanıt:** DPAPI hatası üretildiğinde sahte anahtar JSON'a düz yazıldı.
- **Öneri:** Windows'ta şifreleme başarısızsa kaydı reddetmek, mevcut dosyayı korumak ve kullanıcıya hata göstermek.

### H05 — Farklı çıkış aygıtında bile kaynak ses atılıyor

- **Konum:** `loop.py:240-255`.
- **Sorun:** Yankı önleme yalnız loopback giriş ve herhangi bir çıkış olup olmadığını kontrol ediyor. Giriş ve çıkışın aynı fiziksel uç olması aranmıyor.
- **Etki:** Kaynak hoparlör A, çeviri kulaklık B olsa bile çeviri oynarken kaynak konuşma parçaları kayboluyor.
- **Kanıt:** Ayrı çıkış senaryosunda yakalanan blok gönderilmeden atıldı. Fiziksel aygıtlarla denenmedi.
- **Öneri:** Sabit aygıt kimlikleriyle aynı uç eşleşmesini kontrol etmek; yalnız gerektiğinde bastırmak.

### H06 — Görünen son cümle dışa aktarılmayabiliyor

- **Konum:** `gui/app.py:723-735`, `gui/app.py:984-1009`.
- **Sorun:** Tamamlanan kayıtlar `transcript_items` içinde; devam eden cümleler ayrı tamponlarda. Liste boş değilse dışa aktarma bu tamponları dikkate almıyor.
- **Etki:** Durdurma veya bağlantı kopması sonrasında ekrandaki son metin TXT, SRT ve JSONL dosyalarında eksik kalabilir.
- **Kanıt:** Ekranda görünen ikinci, tamamlanmamış cümle dışa aktarılmadı.
- **Öneri:** Dışa aktarma anında tamamlanmış kayıtlarla bekleyen parçaları birleştiren, tekrar ekleme yapmayan tutarlı bir görünüm oluşturmak.

### H07 — Tema değişimi çeviri metnini okunamaz hale getiriyor

- **Konum:** `gui/app.py:409`, `gui/app.py:923-932`, `gui/app.py:958-963`, `gui/theme.py:44-60`.
- **Sorun:** Tema değişince Text widget rengi güncelleniyor; onu geçersiz kılan `body` etiketi eski renkte kalıyor. Açık temadaki altyazı da koyu zeminde koyu yazı kullanıyor.
- **Kanıt:** Gerçek Tk widget'larında etiketin eski renk tuttuğu doğrulandı. Renklerden hesaplanan kontrast ana metinde yaklaşık **1,13:1**, açık tema altyazısında **1,07:1**.
- **Etki:** Çeviri çıktısının okunabilirliği ciddi biçimde düşüyor.
- **Öneri:** Metin etiketlerini de tema ile güncellemek; altyazıya uyumlu ön/arka plan çifti vermek.

## 2. Diğer doğrulanmış hatalar

| Kimlik | Sorun ve konum | Kanıt ve etki | Önerilen düzeltme |
| --- | --- | --- | --- |
| H08 | Durdurmak SRT zamanlarını değiştiriyor. `gui/app.py:1248-1250`, `export.py:42-46`. | Aynı ilk altyazı durdurmadan önce yaklaşık `00:00:10`, sonra `00:00:00` oldu. Çalıştırmayla doğrulandı. | Sayaç durumuyla kalıcı oturum başlangıcını ayır. |
| H09 | Ayar değiştirerek yeniden başlatmak transkripti siliyor. `gui/app.py:809-822`, `1186-1192`. | Aygıt/dil değişimi normal `start()` yoluna giriyor; paneller, kayıtlar ve zaman başlangıcı sıfırlanıyor. Kaynak üzerinden doğrulandı. | Yeni kullanıcı oturumu ile bağlantıyı yeniden kurmayı ayır. |
| H10 | Temizle yalnız ekranı temizliyor. `gui/app.py:624-629`, `723`. | Panel boşaldıktan sonra eski cümle dışa aktarılmaya devam etti. Çalıştırmayla doğrulandı. | Temizleme kapsamını açık tanımla; ilgili kayıt/tamponları temizle veya eylemi Ekranı temizle olarak adlandır. |
| H11 | Transkript odağında F5 ve Tab çalışmıyor. `gui/app.py:416-424`. | Genel `<Key>` engeli gezinmeyi ve kök kısayollarını kesiyor. Gerçek Tk olaylarında F5 engellendi, Tab odağı panelden çıkaramadı. | Tüm tuşları değil, metin düzenleme işlemlerini engelle. |
| H12 | Aygıt yenileme güncel seçimi geri alıyor. `gui/app.py:539-578`. | Başlangıçtaki `_cfg` kullanılıyor. B seçilip kaydedildikten sonra yenileme A'ya döndü. Çalıştırmayla doğrulandı. | Mevcut geçerli seçimi koru; başlangıç tercihlerini yalnız gerektiğinde kullan. |
| H13 | Örnekleme dönüşümü yüksek frekansları yanlış banda taşıyor. `audio.py:50-74`. | Üretim yolu anti-alias filtresi olmadan örnek azaltıyor. 12 kHz giriş, 16 kHz çıkışta güçlü 4 kHz bileşene dönüştü. Sayısal sinyalle doğrulandı; tanıma kalitesindeki etki ölçülmedi. | Bloklar arasında durum koruyan alçak geçiren filtre kullan. |
| H14 | Ön tampon mute kontrolünü atlıyor; kuyruk sonuna kazanç iki kez uygulanıyor. `loop.py:415-450`. | Mute sonrası bekleyen ses gönderildi; `volume=0.5` için son parçanın etkin kazancı `0.25` oldu. Kontrollü oynatıcıyla doğrulandı. | Tamponu ham tut; sesi gönderirken mute/kazancı bir kez uygula. |
| H15 | Geçerli JSON içindeki bozuk ayar uygulamayı açtırmıyor. `config.py:191-192`, `gui/app.py:84-90`. | `overlay_font_size="bad"` doğrudan `ValueError` üretti. Arayüz oluşturulmadan config okunuyor. | Alan bazlı tip/aralık doğrulaması ve güvenli varsayılanlar kullan. |
| H16 | Bozuk config üzerine tercih kaydı eski veriyi yok ediyor. `config.py:140-169`, `220-260`. | Okuma hatası boş sözlük sayılıyor; sonraki tercih kaydı dosyanın tamamını değiştiriyor. İzole dosyada doğrulandı. | Dosya yok ve dosya okunamadı durumlarını ayır; kurtarılabilir dosyayı koru. |
| H17 | İngilizce arayüz ayarı uygulanmıyor. `gui/app.py:131`, `i18n.py:36-65`. | `ui_lang="en"` iken gerçek etiketler `Hazır / Duyulan / Çeviri` kaldı. | Mevcut `t()` kataloğunu arayüzde kullan; görünen çevirileri sabit iç değerlerden ayır. |

## 3. Paketleme ve CLI hataları

| Kimlik | Sorun ve konum | Kanıt | Önerilen düzeltme |
| --- | --- | --- | --- |
| H18 | Wheel/pip paketleme bozuk. `pyproject.toml:1-22`, `main.py:12-22`. | İzole derleme `Multiple top-level packages discovered in a flat-layout: ['gui', 'assets']` hatası verdi. Ayrıca tanımlanan `main:main` için `main.py` içinde `main()` yok. | Paket/modül/veri keşfini açık tanımla; mevcut başlangıç ve helper yönlendirmesini kapsayan gerçek giriş işlevi oluştur. |
| H19 | Temiz ortamda doğrudan `build.bat` başlangıcı bozuk. `build.bat:15-23`. | Aynı parantez bloğunda set edilen `%SYSPY%` erken genişletiliyor. Kontrol senaryosu `'-m' is not recognized` verdi. Tetikleyici: mevcut venv ve kalıtılmış `SYSPY` yok. | Değişkeni ayrı alt yordamda kullan veya doğru gecikmeli genişletme uygula. |
| H20 | Başlatıcı hata kodunu kaybediyor. `ahenk.bat:17-27`. | Alt komutun `7` çıkış kodu izole başlatıcı kontrolünde `0` döndü. | Çıkış kodunu çocuk işlem bittikten sonra değerlendir. |
| H21 | Başlatıcı argümanları kesiyor. `ahenk.bat:17-23`. | `cli` yolunda yalnız `%2`–`%9` iletiliyor; dokuzuncu CLI tokenı doğrulamada kayboldu. | Tüm argümanları tırnaklarını koruyarak aktar. `SHIFT` işleminin `%*` değerini değiştirmediğini dikkate al. |
| H22 | Çince dil kodları CLI'da reddediliyor. `cli.py:84-92`, `languages.py:20-21`. | Girdi küçük harfe çevriliyor; geçerli kümede `zh-CN/zh-TW` kalıyor. `--dst zh-CN` kontrollü çalıştırmada çıkış kodu 1 verdi. | Normalize anahtardan kanonik koda eşleme yap. |
| H23 | `--json` çıktısı normal duruşta bozuluyor. `cli.py:163-170`. | stdout'a JSON yerine `Durduruldu.` yazılıyor. İptal senaryosunda doğrulandı. | Bilgi mesajını stderr'e veya yapılandırılmış olaya taşı. |

## 4. Güvenlik, test ve bakım geliştirmeleri

### G01 — Konuşma geçmişinin kaydı açık ve yönetilebilir olmalı

- **Konum:** `logger.py:51-85`, `gui/app.py:997-1008`.
- Tamamlanan çeviriler otomatik olarak düz metin `history.jsonl` dosyasına yazılıyor. Panel temizlemek bu dosyayı temizlemiyor.
- Geçmiş ve günlükler sınırsız büyüyor. Son kayıtları okuma işlevi önce dosyanın tamamını belleğe alıyor.
- İzole dizinde geçmiş dosyasının okunabilir konuşma metni tuttuğu doğrulandı.
- **Öneri:** Kullanıcıya kayıt politikasını göster; kapatma, silme ve saklama süresi sun. Günlük döndürme ve sınırlı geçmiş okuma kullan.
- **Sınır:** Yerel gizlilik riski. Uzaktan veri sızdırıldığına dair bulgu yok; Windows profil erişim denetimleri yine geçerli.

### G02 — Test izolasyonu gerçek config dosyasına yazabilir

- **Konum:** `tests/test_config.py:8-11`, `config.py:133-137`.
- Testler yalnız `VOICE_TRANSLATE_CONFIG` değişkenini ayarlıyor. Ortamda daha yüksek öncelikli `AHENK_CONFIG` varsa kayıtlar o dosyaya gidiyor; anahtar temizleme testi mevcut anahtarı silebilir.
- Geçici harici config üzerinde aynı öncelik davranışı yeniden üretildi.
- Bu incelemenin mevcut testleri çalıştırdığı ortamda `AHENK_CONFIG` tanımlı değildi.
- **Öneri:** Testler yüksek öncelikli değişkeni de temizlemeli veya geçici dosyaya yönlendirmeli.

### G03 — Bazı testler uygulama davranışını değil, test içindeki taklidi doğruluyor

- **Konum:** `tests/test_live_translate.py:374-403`, `445-470`.
- Kuyruk testi üretim `receive()` yolunu çalıştırmadan kuyruk mantığını tekrar yazıyor.
- Yankı önleme testi capture işlevini çağırmıyor; yalnız nesne alanlarını kontrol ediyor.
- Resampler testi ses kalitesini değil, sıfır girişin byte sayısını ölçüyor.
- **Öneri:** Test sayısını artırmak yerine gerçek yolları çalıştıran sınır testlerine öncelik ver: geciktirilmiş bağlantıda stop, farklı aygıtlar, frekans bastırma, ön tampon mute/kazanç ve dışa aktarma bütünlüğü.

### G04 — CI dağıtılan ürünü de çalıştırmalı

- **Konum:** `.github/workflows/ci.yml:22-29`, `.github/workflows/release.yml:48-73`, `Ahenk.spec:53-98`.
- Kaynak testleri var; kurulu wheel ve üretilmiş EXE için çalıştırma kontrolü yok.
- Spec CLI EXE'sini üretirken release yalnız GUI EXE'si ve checksum yayımlıyor.
- **Öneri:** Checkout dışında wheel kurulumu; paketlenmiş CLI için `--version` ve `--list-langs`; batch argüman ve çıkış kodu kontrolleri. CLI dosyasının yayımlanıp yayımlanmayacağını açıklaştır.
- **Sınır:** Paketlenmiş EXE'nin çöktüğü iddia edilmiyor; bu dağıtım sınırı çalıştırılarak doğrulanmadı.

### G05 — Bağımlılık sözleşmeleri aynı olmalı

- **Konum:** `requirements.txt:1-4`, `pyproject.toml:13-18`, `requirements-dev.txt:2-3`.
- `requirements.txt` SDK ve NumPy sınırları koyuyor; `pyproject.toml` koymuyor. Release girdileri de tam sabitlenmemiş.
- **Öneri:** Tek, tutarlı sürüm aralığı; release için kilitli bağımlılık ve derleme aracı girdileri.
- **Sınır:** Manifest farkı doğrulandı; gelecekteki bağımlılık kırılması henüz gözlenmedi.

### G06 — Ses gecikmesi mesaj sayısıyla değil süreyle sınırlandırılmalı

- **Konum:** `loop.py:375-386`, `loop.py:453-493`.
- 200 mesajlık kuyruk, mesaj boyuna bağlı olarak uzun ses gecikmesi tutabilir. Örneğin 100 ms'lik mesajlarda tek kuyruk 20 saniyelik ses tutabilir; bu gözlenen Gemini mesaj boyutu değil, kapasite hesabıdır.
- **Öneri:** Kuyruk bütçesini PCM byte veya süre üzerinden belirle. Kesilen yanıtları normal cümle sonundan ayrı işle.
- **Sınır:** Gerçek Gemini akışında gecikme ölçülmedi.

## 5. Canlı ortamda doğrulanmamış riskler

Aşağıdaki maddeler kesin üretim arızası olarak değerlendirilmemeli.

### R01 — VAD veya pause sonrasında cümle bitişi gecikebilir

- **Konum:** `loop.py:249-277`, `loop.py:216-219`.
- Yerel sessizlik kapısı çoğu sessizlik parçasını atlıyor; pause sırasında ses gönderilmiyor. `audio_stream_end` sinyali gönderilmiyor.
- **Olası etki:** Son kelimelerin gecikmesi veya cümlenin geç tamamlanması.
- **Sonraki doğrulama:** Gemini'nin paket boşlukları ile PCM sessizlik süresini nasıl yorumladığını canlı oturumda ölçmek. Gerekirse aktif segment kapanışını açıkça bildirmek.

### R02 — Tekrarlı transkript parçaları kaybolabilir

- **Konum:** `loop.py:73-79`, `loop.py:354-359`.
- `merge_transcript("ha", "ha")` sonucu `("ha", "")`; ikinci parça atılıyor. İşlev düzeyinde doğrulandı.
- **Sınır:** Gerçek olayın delta mı kümülatif mi olduğu ve tekrar eden parçaların sıklığı canlı akışta netleştirilmedi.
- **Öneri:** Modu metin içeriğinden tahmin etmek yerine taşıma protokolünün açık delta/kümülatif sözleşmesine göre işle.

### R03 — Yardımcı worker'ların Tk erişimi kapanışta yarışabilir

- **Konum:** `gui/app.py:515-532`, `gui/app.py:697-718`, `gui/app.py:809-820`.
- Aygıt tarama, anahtar testi ve yeniden başlatma yardımcıları arka plan thread'lerinden Tk nesnelerine veya zamanlayıcılarına erişiyor.
- **Sınır:** Thread içinden her `after()` çağrısının mutlaka hata verdiği iddia edilmiyor. Risk, pencere kapanışı veya eski isteğin sonucunun yeni duruma uygulanmasıyla ilişkili.
- **Öneri:** Sonuçları mevcut kuyruk üzerinden ana threade taşı; eski veya kapatılmış diyaloga ait yanıtları istek kimliğiyle ayır.

### R04 — SDK istemcileri açıkça kapatılmıyor

- **Konum:** `loop.py:100-103`, `loop.py:515-541`; karşılaştırma: `loop.py:59-70`.
- Live bağlantı bağlamı kapanıyor; sahip olunan async/sync istemci açıkça kapatılmıyor. Yeniden bağlantıda yeni loop nesnesi oluşturuluyor.
- **Sınır:** Kaynak tükenmesi gözlenmedi.
- **Öneri:** Her oturum denemesinin `finally` yolunda istemcileri kapat; playback içindeki bekleyen queue-get görevlerinin iptal ve beklenmesini de sahiplik sınırında tamamla.

### R05 — Yüksek DPI'da özel seçim penceresi kırpılabilir

- **Konum:** `gui/widgets.py:204-266`, `gui/theme.py:114-164`.
- Nokta tabanlı yazı boyutlarıyla birlikte sabit piksel satır yüksekliği kullanılıyor. Pencere konumlandırması ilgili monitörün çalışma alanını tam temsil etmeyebilir.
- **Sınır:** Farklı DPI ve çoklu monitörlerde görsel kontrol yapılmadı.
- **Öneri:** Gerçek satır yüksekliğini ölç; açılır pencereyi ilgili monitörün kullanılabilir alanına göre sınırla ve gerektiğinde kaydırma sun.

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

Bu sıralama özgün düzeltme önerisidir. İnceleme sırasında düzeltme uygulanmadı; inceleme sonrasında H01 ve H02 tamamlandı. Diğer maddeler açık kaldı.
