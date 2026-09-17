# Ahenk

**[Türkçe](#ahenk)** · [English](README.en.md)

PC’de çalan sesi (sistem hoparlörü / loopback) veya mikrofonu [Gemini Live Translate](https://ai.google.dev/) ile canlı çevirir. Çeviri hem metin hem ses olarak gelir; metin-only mod da vardır.

Sürüm **0.1.0**. Yazar: Enes Eliağır. Windows odaklı (WASAPI loopback). Python **3.11+**.

## İçindekiler

- [Ne yapar](#ne-yapar)
- [Özellikler](#özellikler)
- [Nasıl çalışır](#nasıl-çalışır)
- [Gereksinimler](#gereksinimler)
- [Kurulum](#kurulum)
- [Masaüstü arayüzü](#masaüstü-arayüzü)
- [Konsol](#konsol)
- [Diller](#diller)
- [API anahtarı](#api-anahtarı)
- [Yerel ayarlar](#yerel-ayarlar)
- [Gizlilik ve güvenlik](#gizlilik-ve-güvenlik)
- [Proje yapısı](#proje-yapısı)
- [Onefile derleme](#onefile-derleme)
- [Test](#test)
- [Sorun giderme](#sorun-giderme)
- [Lisans](#lisans)

## Ne yapar

Ahenk, seçilen giriş aygıtından PCM yakalar, Gemini Live Translate oturumuna gönderir, dönen çeviri sesini hoparlörde çalar ve transkriptleri iki panele yazar:

| Panel | İçerik |
| --- | --- |
| **Duyulan** | Kaynak dil transkripti |
| **Çeviri** | Hedef dil transkripti + ses |

Tipik kullanım: videoda / toplantıda yabancı dil; hoparlörden Türkçe (veya seçilen dil) duymak.

## Özellikler

- Sistem sesi (loopback) veya mikrofon
- Kaynak dil **Otomatik** (model algılar) veya sabit BCP-47
- 13 hedef dil (aşağıda)
- Çıkış **Hiçbiri**: ses çalmaz, yalnız metin
- Canlı VU metre, durum noktası (Hazır / Çalışıyor / Durdu)
- **Altyazı**: her zaman üstte, sürüklenebilir overlay (son çeviri satırı)
- Duyulan / Çeviri: **Kopyala**, **Temizle**
- Dil okuna tıklayınca kaynak ↔ hedef takas (kaynak Otomatik iken kapalı)
- Aygıt listesini **Yenile**
- Aygıt, dil, API anahtarı yerel `config.json`’a yazılır
- Bağlantı kopunca en fazla 3 kez yeniden bağlanır
- Konsol (`cli.py`) ve `ahenk.bat` başlatıcı
- PyInstaller onefile (`dist\Ahenk.exe`)

## Nasıl çalışır

```
Giriş aygıtı (48 kHz stereo, 20 ms)
        ↓  mono + 16 kHz PCM16
Gemini Live  models/gemini-3.5-live-translate-preview
        ↓  24 kHz PCM16  +  transkript deltaları
Hoparlör (≈80 ms ön tampon)     Duyulan / Çeviri panelleri
```

- Yakalanan ses COM/soundcard yüzünden **tek daemon thread**’de tutulur; thread’ler arası paylaşılmaz.
- Model geride kalırsa gönderim kuyruğu (50) ve oynatma kuyruğu (200) eski parçayı düşürür; cümle bitince oynatma kuyruğu silinmez (kesik ses olmasın diye).
- Transkript parçası hem delta hem kümülatif gelebilir; `merge_transcript` birleştirir.

## Gereksinimler

| | |
| --- | --- |
| OS | Windows 10/11 (loopback). Mikrofon yolu başka OS’ta da denenebilir; başlatıcı `.bat`. |
| Python | 3.11+ (`py -3` veya `python`) |
| Ağ | Gemini API |
| Anahtar | [Google AI Studio](https://aistudio.google.com/apikey) |
| Ses | WASAPI loopback hoparlör (çoğu PC’de varsayılan cihazın `[Sistem]` kaydı) |

Bağımlılıklar (`requirements.txt`): `google-genai`, `soundcard`, `numpy`, `python-dotenv`, `pytest`.

## Kurulum

En kısa yol — venv, pip ve menü:

```bat
ahenk.bat
```

| Seçim | |
| --- | --- |
| `1` | Arayüz (`main.py`) |
| `2` | Konsol (`cli.py`) |
| `3` | Onefile derle |
| `4` | Bağımlılıkları yenile |
| `5` | Çıkış |

Elle:

```bat
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Linux / macOS (mikrofon; loopback garanti değil):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## Masaüstü arayüzü

`python main.py` — 960×580, koyu tema, sol ray + iki transkript paneli.

**Sol ray**

1. Başlık, sürüm, **Altyazı**, hakkında (`ⓘ`)
2. Durum noktası + VU
3. **Giriş** / **Çıkış** — `[Sistem]` loopback, `[Mikrofon]` gerçek mic. Çıkışta **Hiçbiri** = metin-only.
4. **Dil** — kaynak (Otomatik + diller) → hedef. Ok: takas.
5. **API anahtarı** — `•` ile gizli; **Kaydet** veya Başlat’ta yazılır.
6. **Başlat** / **Durdur** — çalışırken aygıt, dil ve anahtar kilitlenir.

**Paneller:** Duyulan | Çeviri. Her birinde Kopyala / Temizle. Alt şerit: `[bilgi]` / `[hata]` log.

**Altyazı:** küçük, `always on top`, sürükle, ✕ ile kapat. Son çeviri satırını gösterir.

İlk açılışta giriş varsayılan loopback, çıkış varsayılan hoparlör, kaynak Otomatik, hedef Türkçe (kayıt yoksa).

> **İpucu (Yankı Önleme):** Sistem sesi (loopback) dinlerken çeviri çıkışını kulaklık gibi farklı bir aygıta yönlendirmek veya "Hiçbiri" (yalnızca metin) seçmek en temiz sonucu verir. Aynı hoparlör kullanıldığında Ahenk, çeviri çalarken loopback yakalamasını otomatik bastırarak yankı döngüsünü engeller.

## Konsol

```bat
.venv\Scripts\python cli.py --help
.venv\Scripts\python cli.py --list-devices
.venv\Scripts\python cli.py --dst tr
.venv\Scripts\python cli.py --mic --src en --dst tr
.venv\Scripts\python cli.py --device Headphones --src auto --dst de
```

| Bayrak | Varsayılan | |
| --- | --- | --- |
| `--src` | `auto` | BCP-47 veya `auto` |
| `--dst` | `tr` | Hedef BCP-47 |
| `--device` | yok | Loopback adında alt dizgi |
| `--mic` | kapalı | Sistem sesi yerine varsayılan mikrofon |
| `--list-devices` | | Hoparlör / loopback / mikrofon listesi, çık |
| `--api-key` | yok | Kabuk geçmişine düşer; kullanmayın |

Çıkış hoparlörü her zaman varsayılan hoparlördür (GUI’deki Hiçbiri yok). Durdur: `q` + Enter veya Ctrl+C.

`--src` / `--dst` kodları GUI adlarından bağımsızdır (`en`, `tr`, `de` …).

## Diller

`languages.py`. Yeni dil: görünen ad → BCP-47 ekle.

| Arayüz | Kod |
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
| Çince | `zh` |
| Korece | `ko` |

Kaynak **Otomatik**: `language_codes` boş; model dili bulur. Hedefte Otomatik yok.

## API anahtarı

Repoda anahtar yoktur. [AI Studio](https://aistudio.google.com/apikey) → oluştur.

Öncelik (`config.resolve_api_key`):

1. CLI `--api-key` (geçmişe yazar; kaçının)
2. `GEMINI_API_KEY` — ortam veya proje kökü `.env` (`python-dotenv`)
3. Kayıtlı `config.json` → `api_key` (GUI Kaydet / Başlat)

`.env` örneği — **commit etmeyin** (`.gitignore` içinde):

```
GEMINI_API_KEY=your-key-here
```

Sızdıysa AI Studio’dan iptal edin. Ekran görüntüsü, issue, PR, `--api-key` ile paylaşmayın.

Testlerdeki `sk-test` / `sk-live-1` sahte.

## Yerel ayarlar

Git’e düşmez. Testte `VOICE_TRANSLATE_CONFIG` ile yol değiştirilir.

| OS | Dosya |
| --- | --- |
| Windows | `%APPDATA%\Ahenk\config.json` |
| Linux / macOS | `$XDG_CONFIG_HOME/Ahenk/config.json` veya `~/.config/Ahenk/config.json` |

Windows’ta API anahtarı Windows DPAPI (`CryptProtectData`, kullanıcı oturumuna bağlı yerel şifreleme) ile şifrelenir; Unix’te dosya `0600` izinleriyle saklanır. Alanlar: `api_key`, `input_device`, `output_device`, `src_lang`, `dst_lang`. Bilinmeyen alanlar korunur.

## Gizlilik ve güvenlik

- Yakalanan ses ve üretilen çeviri Google’a gider. Model: `models/gemini-3.5-live-translate-preview`. Ücret ve kota [Gemini API](https://ai.google.dev/) şartlarına bağlıdır.
- Anahtar ve tercihler yalnız bu makinedeki `config.json`’da durur.
- Depoda gerçek anahtar, `.env` veya `config.json` yok. Yok sayılanlar: `.env`, `.env.*`, `config.json`, `.venv/`, `dist/`, `build/`, `*.spec`, `*.exe`.
- Git geçmişi taranmıştır; gerçek anahtar yok. Commit e-postası GitHub noreply.

Bu uygulama sesinizi üçüncü taraf bir API’ye yollar. Hassas içerik için kullanmadan önce bunu kabul edin.

## Proje yapısı

```
main.py          masaüstü giriş
cli.py           konsol
ahenk.bat        venv + menü + derleme
config.py        ayar dosyası, anahtar sırası
loop.py          Gemini oturumu, yakala / al / çal
audio.py         48k→16k, PCM16↔float
devices.py       soundcard listesi, loopback seçimi
languages.py     UI adı → BCP-47
meta.py          sürüm, başlık, yazar
gui/app.py       pencere, overlay, yeniden bağlanma
gui/theme.py     palet, ikon, AppUserModelID
gui/widgets.py   özel Select
assets/          ahenk.ico, ahenk.png
tests/           pytest (ağ yok; aygıt testi atlanabilir)
```

## Onefile derleme

`ahenk.bat` → `3`, veya:

```bat
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name Ahenk --icon assets\ahenk.ico --add-data "assets;assets" --hidden-import soundcard --hidden-import google.genai --collect-submodules google.genai main.py
```

Çıktı: `dist\Ahenk.exe`. `dist/`, `build/`, `*.spec` git’te yok. Exe hâlâ kendi Gemini anahtarınızı ister; anahtar gömülü değildir.

## Test

Ağ çağrısı yok. İstemci taklit edilir.

```bat
.venv\Scripts\python -m pytest
```

| Dosya | |
| --- | --- |
| `tests/test_config.py` | kayıt, öncelik, bozuk JSON |
| `tests/test_gui.py` | başlat, paneller, overlay, tercihler |
| `tests/test_live_translate.py` | resample, birleştirme, sahte oturum |

`test_duplex_with_real_devices_stays_alive` gerçek aygıt ister; yoksa atlanır.

## Sorun giderme

| Belirti | |
| --- | --- |
| `GEMINI_API_KEY bulunamadı` | AI Studio anahtarı; `.env`, ortam veya GUI Kaydet |
| `Loopback cihaz bulunamadı` | Windows hoparlör; aygıtı Yenile; başka çıkış deneyin |
| Ses kesik / gecikmeli | Çıkışı **Hiçbiri** yapıp metni izleyin; ağ ve kota |
| Çeviri yok, Duyulan var | Hedef dil; model erişimi (`gemini-3.5-live-translate-preview`) |
| Python bulunamadı | [python.org](https://www.python.org/downloads/) — installer’da PATH |
| Tk penceresi açılmıyor | `python main.py` — tkinter (resmi Windows installer’da gelir) |
| Derleme hatası | `ahenk.bat` → `4` sonra `3`; antivirus `dist\` klasörünü kilitlemesin |

## Lisans

Henüz `LICENSE` yok. Herkese açık yapmadan önce bir lisans seçin (ör. MIT).
