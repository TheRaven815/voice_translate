# Ahenk (Voice Translate) - Geliştirme, Optimizasyon ve İyileştirme Yol Haritası

Bu liste, kod tabanının tamamı (çekirdek döngü, ses boru hattı, UI/UX, CLI, yapılandırma, derleme ve testler) derinlemesine incelenerek önem sırasına (P0: Kritik, P1: Yüksek, P2: Orta, P3: Düşük/Temizlik) göre derlenmiştir.

---

## 1. Kritik Hatalar ve Kararlılık (P0 - Acil Düzeltmeler)

- [x] **[loop.py:161-177, 305] Ses yakalama iş parçacığı sızıntısı (Thread Leak & COM Crash)**
  - *Sorun:* `listen_system` TaskGroup iptal edildiğinde (`CancelledError`), `finally` bloğu olmadığı için `_cap_stop.set()` çağrılmıyor. `_capture_thread` arka planda zombi olarak çalışmaya devam ediyor ve WASAPI ses aygıtını kilitli tutuyor.
  - *Etki:* Yeniden bağlanmada (`retry`) iki iş parçacığı aynı aygıta erişiyor, `GetCurrentPadding` COM bellek ihlali (`0xC0000005`) çökmesi üretiyor.
  - *Çözüm:* `listen_system` içine `try...finally` bloğu ekle, `self._cap_stop.set()` çağır ve iş parçacığının tamamen durmasını bekle.

- [x] **[gui/app.py:448-477] `_pump_log` yakalanmayan hata nedeniyle UI döngüsünün kalıcı olarak donması**
  - *Sorun:* `_pump_log` yalnızca `queue.Empty` yakalıyor. Mesaj işleme sırasında herhangi bir beklenmedik hata (`TclError`, `ValueError`) fırlatılırsa `self.after(120, self._pump_log)` satırına ulaşılamıyor.
  - *Etki:* Arayüz olay döngüsü sessizce ölüyor; VU metre, loglar, çeviriler ve butonlar tamamen kilitleniyor.
  - *Çözüm:* `self.after` çağrısını `finally:` bloğuna al, kuyruktan gelen her mesajı `try...except Exception` ile sar.

- [x] **[gui/widgets.py:230-244] `Select._close()` içindeki `unbind_all` global olayları yok ediyor**
  - *Sorun:* Dropdown kapandığında `self.unbind_all("<Button-1>")` ve `self.unbind_all("<Escape>")` çağrılıyor.
  - *Etki:* Tkinter'daki `"all"` etiketine bağlı tüm global kısayollar ve kapatma olayları kalıcı olarak siliniyor.
  - *Çözüm:* `unbind_all` yerine yalnızca `winfo_toplevel()` seviyesinde kaydedilen spesifik binding ID'lerini kaldır.

- [x] **[audio.py:24-31] `to_16k_mono` 50 Hz faz kırılması ve aşırı bellek tüketimi (Resampling Phase Glitch)**
  - *Sorun:* `np.linspace(0, len(mono)-1, 320)` ve `np.interp` blok sınırlarında 1 örnek aralık bırakıyor; bu da saniyede 50 kez faz sıçramasına ve seste çıtırtıya yol açıyor. Ayrıca her 20 ms'de 6 geçici NumPy dizisi tahsis ediliyor (~400 KB/s gereksiz GC çöpü).
  - *Etki:* Gemini modeline giden seste 50 Hz tıkırtı/uğultu oluşuyor, konuşma tanıma doğruluğu düşüyor.
  - *Çözüm:* 48 kHz -> 16 kHz tam 3:1 tam sayı oranıdır. `linspace` ve `interp` yerine doğrudan 3'lü kutu ortalaması (anti-aliasing) ile dilimleme yap: `frame.mean(axis=1).reshape(-1, 3).mean(axis=1).astype(np.float32)`.

- [x] **[loop.py:227-250] Oynatma arabelleğinde kısa seslerin takılması ve jitter boşalması (Buffer Underrun / Trapped Audio)**
  - *Sorun:* 
    1. `preroll_n` 1920 örnek (~80ms), ancak donanım `blocksize` 4096 örnek. İlk başlatmada donanım arabelleği yarım kalıyor ve ses çıtlıyor.
    2. 80 ms'den kısa seslerde ("Evet", "No" gibi) `pending_n < preroll_n` kalıyor ve `queue.Empty` durumunda `continue` edildiği için ses arabellekte hapsoluyor; dakikalar sonra yeni ses gelene kadar çalınmıyor.
    3. `started = True` bayrağı sessizlikte sıfırlanmıyor, her yeni cümle başında jitter arabelleklemesi devre dışı kalıyor.
  - *Etki:* Kısa kelimeler yutuluyor veya gecikmeli çalıyor; cümle başlarında patlama sesleri oluşuyor.
  - *Çözüm:* `queue.Empty` durumunda arabellekte kalan `pending` ses varsa derhal `sp.play()` ile boşalt, `started = False` yap.

- [x] **[.gitignore:9 & build.bat:34] `Ahenk.spec` gitignore'da, temiz klonda derleme başarısız**
  - *Sorun:* `.gitignore` dosyasında `*.spec` kuralı var. `build.bat` ise doğrudan `Ahenk.spec` dosyasını arıyor.
  - *Etki:* Projeyi klonlayan birisi doğrudan `build.bat` veya `ahenk.bat` çalıştırdığında derleme `Ahenk.spec bulunamadı` hatasıyla başarısız oluyor.
  - *Çözüm:* `.gitignore` içine `!Ahenk.spec` ekle veya `build.bat` komutunu doğrudan PyInstaller parametreleriyle güncelle.

---

## 2. Ses, Kuyruk ve Performans Optimizasyonları (P1 - Yüksek Öncelik)

- [x] **[loop.py:124-128] Ters çalışan kuyruk düşürme mantığı (Inverted Drop Policy)**
  - *Sorun:* `_post()` içinde `put_nowait(msg)` kuyruk dolduğunda `QueueFull` alıp `pass` geçiyor. Yorum satırında "eski chunk düşer" yazsa da aslında **yeni** ses paketi atılıyor, eski 50 paket kuyrukta kalıyor.
  - *Etki:* Ağ yavaşladığında 1000 ms'ye kadar eski ses birikiyor, gecikme kalıcı hale geliyor ve çeviri desenskronize oluyor.
  - *Çözüm:* Kuyruk dolduğunda önce en eski öğeyi `get_nowait()` ile düşür, ardından yeni öğeyi ekle (`play()` fonksiyonundaki gibi).

- [x] **[loop.py:141-144] VU Metre kuyruk istilası (50 Hz / sn log_queue flooding)**
  - *Sorun:* Her 20 ms'de bir (`_capture_thread`), RMS seviyesi `log_queue` içine `("level", ...)` mesajı olarak atılıyor (saniyede 50 mesaj). `gui/app.py` ise her 120 ms'de bir kuyruğu okuyor; 6 mesajın 5'i gereksiz yere canvas koordinatını değiştirip çöpe gidiyor.
  - *Etki:* GUI thread üzerinde gereksiz koordinat hesaplama yükü ve metin çeviri olaylarının gecikmesi.
  - *Çözüm:* Seviyeyi kuyruğa basmak yerine `loop_obj` üzerinde atomic/thread-safe bir `last_level` float değişkeni olarak sakla, GUI 120 ms timer tetiklendiğinde son değeri doğrudan oradan oku.

- [x] **[audio.py:16-21] `pcm16_to_float` tek sayıda bayt geldiğinde çökme**
  - *Sorun:* Ağdan veya WebSocket paketinden tek sayılı (odd-length) bayt dizisi geldiğinde `np.frombuffer(pcm, dtype=np.int16)` doğrudan `ValueError` fırlatıyor ve oynatma iş parçacığı çöküyor.
  - *Etki:* Oynatıcı iş parçacığı sessizce ölüyor, ses çıkışı kesiliyor.
  - *Çözüm:* `if len(pcm) % 2 != 0: pcm = pcm[:-1]` koruması ekle.

- [ ] **[loop.py:208-210, 258-273] Gereksiz çift kuyruk ve köprü coroutine (Async Queue Redundancy)**
  - *Sorun:* `receive()` gelen sesi `self.audio_in_queue` içine atıyor (`asyncio.Queue`), `play()` coroutine'i ise bunu çekip `_play_q` (`queue.Queue`) içine kopyalıyor.
  - *Etki:* Fazladan coroutine context-switch ve bellek kopyalaması.
  - *Çözüm:* `receive()` içinden doğrudan `_play_q.put_nowait()` çağır, aradaki `audio_in_queue` ve aktarım coroutine'ini kaldır.

- [x] **[loop.py:141] RMS hesaplamasında gereksiz dizi kopyası**
  - *Sorun:* `rms = float(np.sqrt(np.mean(arr**2)))` saniyede 50 kez yeni bir 960x2 dizi tahsis ediyor.
  - *Çözüm:* İndirgenmiş tek kanallı dizi üzerinden BLAS destekli `np.dot` ile sıfır ek bellek tahsisiyle hesapla: `np.sqrt(np.dot(mono, mono) / len(mono))`.

---

## 3. UI / UX Düzeltmeleri ve Geliştirmeleri (P1 - P2)

- [x] **[gui/theme.py:47-53] Windows High-DPI bulanıklık sorunu (DPI Awareness)**
  - *Sorun:* DPI awareness ayarlanmadığı için Windows %125, %150, %200 ölçeklemede Tkinter penceresini bitmap olarak büyütüyor.
  - *Etki:* Yazılar, kenarlıklar ve ikonlar bulanık görünüyor.
  - *Çözüm:* `gui/theme.py` içindeki `prepare_app_id` fonksiyonunda `ctypes.windll.shcore.SetProcessDpiAwareness(1)` çağrısı ekle.

- [x] **[gui/widgets.py:152-164] Dropdown menünün ekranın altına taşması ve tıklanamaması**
  - *Sorun:* `Select` popup açılırken yatay taşma (`screen_w`) kontrol ediliyor ama dikey taşma (`screen_h`) kontrol edilmiyor.
  - *Etki:* Pencere ekranın altındayken hedef dil seçimi açıldığında menü görev çubuğunun altına kaçıyor ve öğeler seçilemiyor.
  - *Çözüm:* `if y + h > screen_h: y = max(0, self.winfo_rooty() - h + 1)` kontrolü ekleyerek menüyü yukarıya doğru aç.

- [x] **[gui/app.py:753-759] Altyazı penceresi sürüklenirken titreme / sıçrama (Drag Jitter)**
  - *Sorun:* Sürükleme olayında `e.x` ve `e.y` yerel bileşen koordinatları kullanılıyor; fare etiket kenarlığını geçtiğinde koordinat aniden 16 px zıplıyor.
  - *Etki:* Altyazı kutusu sürüklenirken şiddetli titreme ve zıplama yaşanıyor.
  - *Çözüm:* `e.x_root` ve `e.y_root` mutlak ekran koordinatlarını kullan: `pop.geometry(f"+{e.x_root - pop._drag_x}+{e.y_root - pop._drag_y}")`.

- [x] **[gui/app.py:391-424] Aygıt taramasının ana iş parçacığını dondurması (UI Freeze on Refresh)**
  - *Sorun:* `refresh_devices()` ana thread'de `soundcard.all_inputs()` ve `all_outputs()` çağırıyor. Windows COM arayüzü Bluetooth veya harici aygıtları sorgularken 500 ms - 2 sn arayüzü kilitliyor.
  - *Etki:* "Yenile" butonuna basıldığında pencere "(Yanıt Vermiyor)" durumuna düşüyor.
  - *Çözüm:* Aygıt taramasını arka plan daemon iş parçacığında çalıştır, sonuçları `self.after` ile ana thread'e aktar.

- [x] **[gui/app.py:483-486] `in_box.current() == -1` durumunda sessizce son aygıtın seçilmesi**
  - *Sorun:* `Select.current()` eşleşme bulamazsa `-1` döndürür. Python'da `self.inputs[-1]` hata vermez, listenin en sonundaki aygıtı seçer.
  - *Etki:* Yanlış/geçersiz aygıt seçildiğinde kullanıcıya uyarı vermek yerine rastgele son aygıt başlatılır.
  - *Çözüm:* `idx = self.in_box.current(); if idx < 0 or idx >= len(self.inputs): raise ValueError(...)` doğrulaması ekle.

- [x] **[gui/app.py:51, 135-164] Dar sol panel nedeniyle dil isimlerinin kesilmesi**
  - *Sorun:* Sol panel sabit 248 px. Kaynak ve hedef dil yan yana yerleştirildiği için açılır kutulara sadece ~56 px alan kalıyor.
  - *Etki:* "Otomatik algıla", "Geleneksel Çince", "Endonezce" gibi diller sığmıyor ve okunamıyor.
  - *Çözüm:* Sol paneli 280-300 px seviyesine genişlet veya kaynak/hedef dilleri aralarında dikey swap butonuyla alt alta hizala.

- [x] **[gui/app.py:427-434, 729-738] Canlı altyazı akışında O(N) metin ayrıştırma ve UI takılması**
  - *Sorun:* Gelen her ses parçasında `widget.get("1.0", "end").splitlines()` ile tüm metin baştan sona okunup satırlara bölünüyor ve senkron `update_idletasks()` çağrılıyor.
  - *Etki:* Çeviri uzadıkça CPU tavan yapıyor, arayüzde mikro donmalar ve altyazı kutusunda titremeler başlıyor.
  - *Çözüm:* Tüm metni kopyalamak yerine sadece son satırı al (`widget.get("end - 2 lines", "end - 1 chars")`) ve geometri güncellemelerini debounce et.

- [ ] **[gui/app.py:92-96] Granüler durum bildirimleri (Connecting, Listening, Translating, Error)**
  - *Sorun:* "Başlat" tıklandığı an henüz bağlantı kurulmadan gösterge "Çalışıyor" (yeşil) oluyor. Hata olduğunda neden durduğu anlaşılmıyor.
  - *Çözüm:* Durumları ayrıştır: `Bağlanıyor...` (sarı), `Dinleniyor` (yeşil), `Çevriliyor` (canlı mavi/yeşil), `Yeniden bağlanıyor` (turuncu), `Hata` (kırmızı).

- [x] **[gui/app.py] Klavye kısayolları ve erişilebilirlik desteği**
  - *Sorun:* Klavye ile başlatma/durdurma, altyazı açma veya dil değiştirme yapılamıyor.
  - *Çözüm:* `<Control-Return>` veya `<F5>` ile Başlat/Durdur, `<Control-O>` veya `<F2>` ile Altyazı Penceresi, API anahtarı alanında `<Return>` ile kaydetme bağla. `Select` bileşenine klavye ok tuşları (`<Up>`, `<Down>`, `<Return>`) desteği ekle.

- [ ] **[gui/app.py:97-99] VU Metre hassasiyeti ve çıkış (hoparlör) göstergesi**
  - *Sorun:* 36x4 px boyutundaki giriş göstergesi doğrusal RMS kullandığı için insan kulağı algısına uymuyor ve çok küçük. Çıkış sesi (çeviri konuşması) için hiçbir gösterge yok.
  - *Çözüm:* Göstergeyi genişlet (80x6 px), RMS değerini logaritmik (dBFS) ölçeğe çevir ve yanına çıkış sesi (hoparlör aktivitesi) için ikinci bir mini seviye/nabız barı ekle.

- [x] **[gui/theme.py:56-78] Windows görev çubuğunda bulanık ikon sorunu**
  - *Sorun:* `apply_icon` önce `.ico` yüklüyor, hemen ardından 1024x1024 PNG'yi `iconphoto` ile basıyor. Tkinter PNG'yi kötü bir algoritmayla küçülterek `.ico` dosyasını eziyor.
  - *Etki:* Windows görev çubuğunda ve Alt+Tab menüsünde ikon pikselli/bulanık çıkıyor.
  - *Çözüm:* Windows üzerinde (`os.name == "nt"`) sadece çok çözünürlüklü `iconbitmap` kullan, `iconphoto` çağrısını sadece Linux/macOS için çalıştır.

- [x] **[gui/app.py:712] Çoklu monitör negatif koordinat hatası (Multi-Monitor Teleport)**
  - *Sorun:* Hakkında penceresi `max(x, 0)` ve `max(y, 0)` ile konumlandırılıyor.
  - *Etki:* Sol veya üst tarafta ikincil monitör kullanan sistemlerde pencere ikincil ekranda değil ana ekranda zorla açılıyor.
  - *Çözüm:* `max(x, 0)` sınırlamasını kaldır, pencereyi ana pencere koordinatlarına göre göreceli ortala.

---

## 4. Mimari, Hata Yönetimi ve Dayanıklılık (P2 - Orta Öncelik)

- [x] **[gui/app.py:527-545] Yeniden denemede (Retry) kirli `SystemAudioLoop` nesnesinin tekrar kullanılması**
  - *Sorun:* `asyncio.run(self.loop_obj.run())` hata alıp çöktüğünde `retries += 1` yapılıyor ve aynı `self.loop_obj` tekrar `asyncio.run`'a veriliyor. Bu nesnenin içindeki kuyruklar, iptal bayrakları ve Gemini client oturumu eski kapalı döngüye bağlı kalıyor.
  - *Etki:* Yeniden denemeler çoğunlukla `RuntimeError: Event loop is closed` hatası vererek başarısız oluyor.
  - *Çözüm:* Her yeniden denemede sıfır `SystemAudioLoop` nesnesi oluştur.

- [x] **[gui/app.py:596] Python 3.11+ `ExceptionGroup` nedeniyle hataların maskelenmesi**
  - *Sorun:* TaskGroup içindeki hatalar `ExceptionGroup` olarak yakalanıyor. GUI logunda sadece `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` yazıyor.
  - *Etki:* Kullanıcı gerçek hatanın (örneğin 403 API Key hatası mı yoksa mikrofon erişim hatası mı) ne olduğunu göremiyor.
  - *Çözüm:* `getattr(e, "exceptions", [e])[0]` ile asıl kök hatayı çöz ve loga yazdır.

- [ ] **[loop.py:130-159 & 227-250] USB/Bluetooth kulaklık bağlantısı koptuğunda sessiz çökme**
  - *Sorun:* Cihaz bağlantısı koptuğunda `mic.record()` veya `sp.play()` hata veriyor, iş parçacığı sessizce ölüyor ve program hata vermeden sonsuz sessizlikte bekliyor.
  - *Çözüm:* Donanım hatalarını yakala, ana döngüye ileterek kullanıcıya `Aygıt bağlantısı koptu` uyarısı ver ve durdur.

- [x] **[cli.py:46-49] CLI `q + Enter` ile çıkışta çirkin traceback düşmesi**
  - *Sorun:* `loop.py` içindeki kullanıcı çıkışı `asyncio.CancelledError` fırlatıyor. `cli.py` sadece `KeyboardInterrupt` yakaladığı için temiz çıkışta bile konsola Python hata izi dökülüyor.
  - *Çözüm:* `except (KeyboardInterrupt, asyncio.CancelledError):` olarak güncelle.

- [ ] **[cli.py:109-114] Windows konsolunda `input()` bloke olması ve çakışma**
  - *Sorun:* `send_text` içindeki `input()` komutu Windows üzerinde `ReadFile` ile tüm iş parçacığını bloke ediyor. Canlı gelen çeviri metinleri `input` satırıyla iç içe giriyor ve Ctrl+C yapıldığında Enter'a basana kadar terminal kapanmıyor.
  - *Çözüm:* Windows için `msvcrt.kbhit()` tabanlı bloke olmayan okuma ekle veya `--no-interactive` parametresi sağla.

- [x] **[loop.py:179-195] Konsol modunda duyulan ve çevrilen metinlerin satır satır birbirine karışması**
  - *Sorun:* Gelen ve giden akış eşzamanlı geldiğinde `_open` sözlüğü mevcut aktif akışı takip etmediği için duyulan ses ile çeviri tek bir satırda harf harf birbirine giriyor.
  - *Çözüm:* `active_stream` değişkeni tut; akış türü değiştiğinde araya yeni satır ve başlık koy.

- [x] **[devices.py:33-37] Varsayılan hoparlör `None` olduğunda çökme**
  - *Sorun:* Sistemde hiç çıkış aygıtı yoksa `sc.default_speaker()` `None` döner. Kod `default_sp.name` okumaya çalıştığı için `AttributeError` patlar.
  - *Çözüm:* `if default_sp is not None:` kontrolü ekle.

- [x] **[loop.py:24] Canlı çeviri model adının sabit kodlanması (Hardcoded Model)**
  - *Sorun:* `MODEL = "models/gemini-3.5-live-translate-preview"` kod içine gömülü. Google model adını güncellediğinde kod değiştirilmeden program çalışmaz.
  - *Çözüm:* `os.environ.get("GEMINI_LIVE_MODEL")` ve `--model` CLI parametresi ile ezilebilir yap.

- [x] **[gui/app.py:804-812] Pencere kapatılırken iş parçacıkları kapanmadan Tcl yorumlayıcısının yok edilmesi**
  - *Sorun:* `_on_close` çağrıldığında `self.destroy()` hemen çalışıyor; arkada WASAPI okuyan iş parçacıkları kapanmakta olan nesnelere erişmeye çalışırken erişim ihlali oluşturabiliyor.
  - *Çözüm:* Önce pencereyi gizle (`withdraw`), worker iş parçacığının bitmesini kısa bir timeout (`0.3s`) ile bekle, ardından `destroy()` çağır.

- [ ] **[config.py & gui/app.py] Dil saklama biçimindeki uyumsuzluk (UI İsimleri vs BCP-47)**
  - *Sorun:* GUI `config.json` dosyasına Türkçe isim yazıyor (`"Türkçe"`, `"İngilizce"`), CLI ise BCP-47 kodları kullanıyor (`"tr"`, `"en"`).
  - *Çözüm:* Yapılandırma dosyasında her zaman standart BCP-47 dil kodlarını sakla, UI seviyesinde bunları yerelleştirilmiş isimlere dönüştür.

- [ ] **[config.py] Ayarların genişletilmesi (Pencere boyutu, konumu ve altyazı pozisyonu)**
  - *Sorun:* Pencere koordinatları ve altyazı penceresinin yeri kaydedilmiyor. Her açılışta kullanıcı altyazıyı tekrar taşımak zorunda kalıyor.
  - *Çözüm:* `config.json` içine `window_geom` ve `overlay_geom` alanları ekle.

---

## 5. Ölü Kod, Fazlalıklar ve Kod Temizliği (P2 - P3)

- [x] **[loop.py:216-218] Asla ulaşılamayan ölü kod (`elif text := response.text`)**
  - *Sorun:* `google.genai` yanıtında `server_content is not None` ise ilk `if` bloğuna girer. Eğer `None` ise `response.text` zaten `None` döner. Dolayısıyla `elif` bloğu hiçbir zaman çalışmaz.
  - *Çözüm:* `output_transcription` bulunamadığında `response.text` kontrolünü `if content is not None:` içine taşı.

- [ ] **[loop.py:186 & 171] Çift `_open` sözlük güncellemesi ve GUI modunda ölü durum**
  - *Sorun:* `_open[stream] = False` hem `_handle_tr` hem de `_console_emit` içinde mükerrer yapılıyor. GUI modunda ise `_open` tamamen işlevsiz kalıyor.
  - *Çözüm:* Sözlük durumunu sadece konsol fonksiyonuna indirge veya temizle.

- [ ] **[audio.py:8] Kullanılmayan `RECEIVE_SAMPLE_RATE = 24000` sabiti**
  - *Sorun:* `audio.py` içinde tanımlı fakat modül içinde hiçbir yerde kullanılmıyor, sadece `loop.py` dışarıdan import ediyor.
  - *Çözüm:* Sabiti mantıksal olarak doğru yere taşı veya modül içinde dokümante et.

- [x] **[gui/widgets.py:43-50] Asimetrik `Select.__getitem__` ve `__setitem__`**
  - *Sorun:* `__getitem__` içinde `"state"` destekleniyor ancak `__setitem__` içine `"state"` yazıldığında `KeyError` patlıyor. Ayrıca `Select.configure(values=[...])` çağrısı `TclError` veriyor.
  - *Çözüm:* `__setitem__` ve `configure` metotlarında `"state"` ve `"values"` desteğini standart Tkinter arayüzüne tam uyumlu hale getir.

- [x] **[gui/theme.py:75-78] `apply_icon()` içindeki gereksiz mükerrer try-except**
  - *Sorun:* Linux/macOS kolunda hata alındığında aynı başarısız kod satırı `except` içinde bir kez daha çalıştırılıyor.
  - *Çözüm:* İç içe try-except bloklarını tekilleştir.

- [x] **[config.py:108-114, 124-144] Ayar kaydederken çift disk okuması ve gereksiz şifreleme**
  - *Sorun:* `save_api_key` önce `load()` ile diskten okuyup şifreyi çözüyor, sonra `save()` çağırarak diskten tekrar okuyup şifreyi yeniden kriptoluyor.
  - *Çözüm:* Ham ayar sözlüğünü doğrudan güncelleyerek çift disk I/O ve gereksiz şifreleme turunu kaldır.

- [x] **[devices.py:13, 18-24] Mükerrer WASAPI COM sorguları**
  - *Sorun:* `list_devices()` içinde `sc.all_microphones(include_loopback=True)` arka arkaya iki kez çağrılıyor. Döngü içinde her hoparlör için `sc.default_speaker()` tekrar tekrar tetikleniyor.
  - *Çözüm:* Donanım listesini bir defa alıp hafızada filtrele; varsayılan hoparlörü döngü öncesinde tek değişkene ata.

- [ ] **[gui/app.py:78-85, 109, 175] Kullanılmayan/salt-yazılır örnek nitelikleri (Dead Instance Attributes)**
  - *Sorun:* `self.brand`, `self.version_lbl`, `self.info_btn`, `self.refresh_btn`, `self.about_name` gibi bileşenler `self` üzerine atanıyor fakat sınıf içinde bir daha asla okunmuyor.
  - *Çözüm:* Testlerin veya dinamik güncellemelerin ihtiyaç duymadığı statik etiketleri yerel değişkene dönüştür.

- [x] **[gui/app.py & gui/theme.py] Temadan bağımsız sabit renk kodları (Hardcoded Hex Colors)**
  - *Sorun:* `app.py` içinde `"#1a1a1a"`, `"#2c2c2c"`, `"#0c0c0c"`, `"#ffffff"` gibi renkler `theme.C` yerine doğrudan yazılmış.
  - *Çözüm:* Bu renkleri `theme.C` paletine taşı (`C.select`, `C.overlay_bg`, `C.disabled_bg`).

---

## 6. Bağımlılıklar, Derleme ve Test Geliştirmeleri (P2 - P3)

- [x] **[requirements.txt:5] Çalışma zamanı bağımlılıklarına test paketlerinin karışması**
  - *Sorun:* `pytest>=8` ana `requirements.txt` içinde yer alıyor.
  - *Etki:* Son kullanıcılar veya `ahenk.bat` kurulumu yapanlar gereksiz yere pytest ve yan paketlerini yüklüyor; PyInstaller paket boyutu şişiyor.
  - *Çözüm:* `requirements.txt` (prod) ve `requirements-dev.txt` (dev) olarak ikiye ayır.

- [x] **[requirements.txt:1] `google-genai>=2.0` için üst sürüm sınırı olmaması**
  - *Sorun:* Canlı WebSocket ve model şemaları hızla değişen bir SDK'da üst sürüm kısıtı olmaması gelecekteki bir güncellemede kodun bozulmasına yol açabilir.
  - *Çözüm:* Sürümü `google-genai>=2.0,<3.0` veya test edilen kararlı aralıkta sabitle.

- [x] **[Ahenk.spec:17] PyInstaller `excludes` listesinin boş olması (Büyük Binary Boyutu)**
  - *Sorun:* `excludes=[]` boş olduğu için `pytest`, `unittest`, `tkinter.test`, `numpy.testing`, `numpy.f2py` gibi geliştirme modülleri `.exe` içine gömülüyor.
  - *Etki:* Üretilen `.exe` dosyası gereksiz yere 30-50 MB daha büyük oluyor.
  - *Çözüm:* `Ahenk.spec` içine kapsamlı `excludes` listesi ekle ve `optimize=1` yap.

- [x] **[Ahenk.spec:39] İkon tanımında tip uyuşmazlığı**
  - *Sorun:* `icon=['assets/ahenk.ico']` şeklinde liste verilmiş; PyInstaller string dosya yolu bekler.
  - *Çözüm:* `icon='assets/ahenk.ico'` olarak düzelt.

- [x] **[tests/] `cli.py` için test bulunmaması (0% Test Kapsamı)**
  - *Sorun:* CLI argümanları (`--src`, `--dst`, `--device`, `--list-devices`, `--api-key`), eksik anahtarda `sys.exit(1)` davranışı ve döngü parametreleri hiç test edilmiyor.
  - *Çözüm:* `tests/test_cli.py` dosyasını oluştur ve CLI bayraklarını, hata durumlarını test et.

- [x] **[tests/test_gui.py:284-307] Worker döngü testinin iş yapmadan sonlanması**
  - *Sorun:* `DummyLoop` içindeki `_user_stop` önceden `True` yapıldığı için `gui/app.py:529` döngüsüne hiç girilmiyor; hata ve retry mekanizması test edilmemiş kalıyor.
  - *Çözüm:* Mock loop'un en az 1 kez hata verip retry mekanizmasını tetiklemesini sağlayan senaryo ekle.

- [x] **[tests/test_live_translate.py:293] Testlerdeki yapay `time.sleep(4)` gecikmesi**
  - *Sorun:* Testler gereksiz yere her çalıştırmada 4 saniye bekliyor.
  - *Çözüm:* `time.sleep` yerine `asyncio.Event` veya durum tabanlı bekleme kullan.
