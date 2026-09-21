"""Gemini Live oturumu: yakala → çevir → oynat."""

from __future__ import annotations

import asyncio
import math
import queue
import re
import threading
import os
import sys
import time
import warnings
from types import SimpleNamespace

import numpy as np
from google import genai
from google.genai import types

from audio import (
    CAPTURE_BLOCK,
    CAPTURE_RATE,
    RECEIVE_SAMPLE_RATE,
    SEND_SAMPLE_RATE,
    AudioConverter,
    cosine_fade,
    pcm16_to_float,
    soften_join,
    to_16k_mono,
)
DEFAULT_MODEL = "models/gemini-3.5-live-translate-preview"

# Kayıt tamponu: okuma yine 20 ms bloklarla yapılır, ancak WASAPI tarafında
# ~100 ms'lik tampon tutulur; zamanlama dalgalanmalarında "data
# discontinuity" kesintileri azalır.
CAPTURE_BUFFER_BLOCKS = CAPTURE_BLOCK * 5

try:  # yalnızca Windows WASAPI arka ucunda bulunur
    from soundcard.mediafoundation import SoundcardRuntimeWarning as _SoundcardRuntimeWarning
except Exception:
    _SoundcardRuntimeWarning = None


_DISC_RE = re.compile(r"data discontinuity", re.IGNORECASE)


def _is_discontinuity_warning(message, category=None) -> bool:
    """WASAPI 'data discontinuity' uyarısı mı? (mesaj esastır, kategori değil).

    Eskiden `or` ile kategori tek başına yeterli sayılıyordu; bu, kesintiyle
    ilgisiz tüm SoundcardRuntimeWarning'leri de yutuyordu. Artık mesaj şart:
    kategori ne olursa olsun mesaj eşleşmeli.
    """
    try:
        text = str(message)
    except Exception:
        return False
    return bool(_DISC_RE.search(text))


def ensure_discontinuity_suppressed() -> None:
    """Konsol selini tek seferde keser (soundcard importundan SONRA çağrılmalı).

    soundcard, import sırasında `simplefilter('always',
    SoundcardRuntimeWarning)` koyar; bu ignore filtresi onun önüne geçip
    "data discontinuity" uyarılarının stderr'e düşmesini engeller. Blok başına
    değil, oturum başında bir kez kurulur (thread-safe, ucuz).
    """
    try:
        warnings.filterwarnings("ignore", message=".*data discontinuity.*")
    except Exception:
        pass


# Modül importunda da dene; asıl garanti __init__'teki çağrıdır (sıralama için).
try:
    if _SoundcardRuntimeWarning is not None:
        ensure_discontinuity_suppressed()
except Exception:
    pass


def _record_block(mic):
    """Tek 20 ms kayıt bloğu (uyarı yakalama YOK; sayım dış hook'tadır).

    Uyarı bastırma/sayım `_capture_inner` içindeki oturum-seviyesi
    `showwarning` hook'unda yapılır. Burada blok başına `catch_warnings`
    kullanılmaz: o desen global filtre listesini saniyede ~50 kez değiştirir,
    thread-safe değildir ve diğer thread'lerin uyarılarını yutar/geçirir
    (sızıntının asıl sebebi buydu). Geriye uyumluluk için (frame, bool)
    döner; bool her zaman False'tur, gerçek sayım hook'tadır.
    """
    frame = mic.record(numframes=CAPTURE_BLOCK)
    return frame, False


def build_config(
    src: str | None,
    dst: str,
    modalities: list[str] | None = None,
    system_instruction: str | None = None,
) -> types.LiveConnectConfig:
    if src:
        input_tr = types.AudioTranscriptionConfig(language_codes=[src])
    else:
        input_tr = types.AudioTranscriptionConfig()
    mods = modalities or ["AUDIO"]
    out_tr = types.AudioTranscriptionConfig() if "AUDIO" in mods else None
    sys_inst = None
    if system_instruction:
        sys_inst = types.Content(parts=[types.Part(text=system_instruction)])
    return types.LiveConnectConfig(
        response_modalities=mods,
        input_audio_transcription=input_tr,
        output_audio_transcription=out_tr,
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=0,
            sliding_window=types.SlidingWindow(target_tokens=0),
        ),
        translation_config=types.TranslationConfig(
            target_language_code=dst,
        ),
        system_instruction=sys_inst,
    )


async def validate_live_api_key(api_key: str) -> None:
    """Anahtarı uygulamanın kullandığı gerçek Live modeliyle doğrular."""
    client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
    try:
        async with client.aio.live.connect(
            model=os.environ.get("GEMINI_LIVE_MODEL") or DEFAULT_MODEL,
            config=build_config(None, "tr"),
        ):
            return
    finally:
        await client.aio.aclose()
        client.close()


def merge_transcript(prev: str, incoming: str) -> tuple[str, str]:
    """Gelen parça delta veya kümülatif olabilir; (tam metin, eklenecek) döner."""
    if not incoming:
        return prev, ""
    if prev and len(incoming) > len(prev) and incoming.startswith(prev):
        return incoming, incoming[len(prev) :]
    return prev + incoming, incoming


def describe_audio_error(err: BaseException, dev=None) -> str:
    """Ses aygıtı hatasını tipi boş olsa bile açıklayıcı Türkçe mesaja çevirir.

    soundcard, bazı fiziksel mikrofonların sürücü mix biçimini
    (WAVE_FORMAT_EXTENSIBLE değil) `assert` ile reddeder; `str(e)` boş
    (`AssertionError: `) kalır ve kullanıcı `()` görür. Bu deterministik
    uyumsuzluk yeniden denemeyle düzelmez; paylaşımlı sürücü biçimini
    48000 Hz yapmak gerekir.
    """
    name = type(err).__name__
    try:
        msg = str(err).strip()
    except Exception:
        msg = ""
    base = f"{name}: {msg}" if msg else name
    if isinstance(err, AssertionError):
        devname = getattr(dev, "name", "?") if dev is not None else "?"
        return (
            f"{base} — '{devname}' aygıtı ses katmanında açılamadı "
            "(sürücü mix biçimi desteklenmiyor, yeniden denemek işe yaramaz). "
            "Windows Ses → Kayıt → Mikrofon → Özellikler → Gelişmiş → "
            "Varsayılan Biçimi '48000 Hz' yapıp yeniden dene; olmazsa çalışan "
            "bir [Sistem] girişine dön."
        )
    return base

def _is_same_endpoint(source, target) -> bool:
    """Giriş (loopback) ile çıkış aygıtının aynı fiziksel ses ucuna ait olup olmadığını doğrular."""
    if source is None or target is None:
        return False
    src_id = getattr(source, "id", None)
    dst_id = getattr(target, "id", None)
    if src_id is not None and dst_id is not None:
        return str(src_id) == str(dst_id)
    src_name = getattr(source, "name", None)
    dst_name = getattr(target, "name", None)
    if src_name is not None and dst_name is not None:
        s_name = str(src_name).strip().lower()
        d_name = str(dst_name).strip().lower()
        return s_name == d_name or d_name in s_name or s_name in d_name
    return src_id is None and dst_id is None and src_name is None and dst_name is None

def write_playback(player, frames: np.ndarray, *, stop=None, memmove=None) -> int:
    """Float32 çerçeveleri cihaza yaz; bırakılan çerçeve sayısı kopyalanan kadardır.

    soundcard `Player.play` boş alanın tamamını ister ve kısa verinin
    doldurmadığı kuyruğu da serbest bırakır. O kuyruk başlatılmamış bellek
    olduğundan her paket sınırında çıt duyulur. `_render_buffer` yoksa
    (test çiftleri) `play` kullanılır.
    """
    samples = np.asarray(frames, dtype=np.float32)
    if samples.size == 0:
        return 0
    if getattr(player, "_render_buffer", None) is None or getattr(player, "_render_release", None) is None:
        player.play(samples)
        return int(samples.shape[0] if samples.ndim > 1 else samples.size)

    if memmove is None:
        from soundcard.mediafoundation import _ffi
        memmove = _ffi.memmove

    channels = len(set(getattr(player, "channelmap", [0]))) or 1
    mono = np.ascontiguousarray(samples.reshape(-1) if samples.ndim == 1 else samples[:, 0])
    data = mono.reshape(-1, 1) if channels == 1 else np.tile(mono.reshape(-1, 1), (1, channels))
    data = np.ascontiguousarray(data, dtype=np.float32)
    total = int(data.shape[0])
    offset = 0
    while offset < total:
        if stop is not None and stop():
            break
        available = int(player._render_available_frames())
        if available <= 0:
            time.sleep(0.001)
            continue
        count = min(available, total - offset)
        piece = np.ascontiguousarray(data[offset:offset + count])
        raw = piece.ravel().tobytes()
        if len(raw) != count * channels * 4:
            raise RuntimeError("oynatma çerçevesi boyu WASAPI adımıyla uyuşmuyor")
        buffer = player._render_buffer(count)
        memmove(buffer[0], raw, len(raw))
        player._render_release(count)
        offset += count
    return offset


class BoundedByteQueue:
    """Ses gecikmesini sınırlandırmak için byte/süre bütçeli kuyruk (G06)."""

    def __init__(self, max_bytes: int = int(RECEIVE_SAMPLE_RATE * 2 * 2.5)):
        self.max_bytes = max_bytes
        self.curr_bytes = 0
        self._q: queue.Queue[bytes | None] = queue.Queue()
        self._lock = threading.Lock()

    def put_nowait(self, item: bytes | None) -> None:
        with self._lock:
            if item is None:
                self._q.put_nowait(None)
                return
            self.curr_bytes += len(item)
            while self.curr_bytes > self.max_bytes and not self._q.empty():
                try:
                    dropped = self._q.get_nowait()
                    if dropped is not None:
                        self.curr_bytes = max(0, self.curr_bytes - len(dropped))
                except queue.Empty:
                    break
            self._q.put_nowait(item)

    def get(self, timeout: float | None = None) -> bytes | None:
        item = self._q.get(timeout=timeout)
        with self._lock:
            if item is not None:
                self.curr_bytes = max(0, self.curr_bytes - len(item))
        return item



class SystemAudioLoop:
    def __init__(
        self,
        src: str | None,
        dst: str,
        source_mic,
        api_key: str,
        output_speaker=None,
        on_text=None,
        console_input: bool = True,
        model: str | None = None,
        volume: float = 1.0,
        muted: bool = False,
        vad_threshold: float = 0.0,
        system_instruction: str | None = None,
        glossary: dict[str, str] | list[str] | str | None = None,
    ):
        self.model = model or os.environ.get("GEMINI_LIVE_MODEL") or DEFAULT_MODEL
        self.client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key,
        )
        self.source_mic = source_mic
        self.output_speaker = output_speaker
        modalities = ["AUDIO"]
        full_instruction = system_instruction or ""
        if glossary:
            if isinstance(glossary, dict):
                terms = "\n".join(f"- {k}: {v}" for k, v in glossary.items())
            elif isinstance(glossary, list):
                terms = "\n".join(f"- {item}" for item in glossary)
            else:
                terms = str(glossary).strip()
            glossary_text = f"Custom translation glossary and terminology:\n{terms}"
            full_instruction = (
                f"{full_instruction}\n\n{glossary_text}".strip()
                if full_instruction
                else glossary_text
            )
        self.config = build_config(
            src, dst, modalities=modalities, system_instruction=full_instruction or None
        )
        self._emit = on_text or self._console_emit
        self.console_input = console_input
        self.volume = max(0.0, min(2.0, float(volume)))
        self.muted = bool(muted)
        self.vad_threshold = max(0.0, float(vad_threshold))
        self._paused = threading.Event()
        self.detected_src: str | None = None
        self._last_speech_time: float = 0.0
        self.last_latency_ms: float = 0.0
        self._waiting_response: bool = False
        self.session = None
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cap_stop = threading.Event()
        self._play_stop = threading.Event()
        self._user_stop = threading.Event()
        self._play_q: queue.Queue | None = None
        self._bufs = {"heard": "", "trans": ""}
        self._active_stream: str | None = None
        self.last_level: float = 0.0
        self._playback_until: float = 0.0
        # --- Hot-swap + dayanıklılık durumu ---------------------------------
        # Ses thread'leri tek sahiplidir: soundcard COM nesneleri yalnızca
        # kendisini açan thread'de kapatılır. GUI/başka thread yalnızca
        # bekleyen aygıtı yazar; açma/kapama kararı ses thread'indedir.
        self._io_lock = threading.Lock()
        self._pending_input = None
        self._has_pending_input: bool = False
        self._pending_output = None
        self._has_pending_output: bool = False
        self._input_generation: int = 0
        self._output_generation: int = 0
        # Aynı hoparlörde dublaj: yakalama kendi çaldığımız sesi hariç tutar.
        self._dub_exclude = False
        self._dub_generation: int = 0
        self._capture_heartbeat: float = time.monotonic()
        self._play_heartbeat: float = time.monotonic()
        self._capture_opened_once: bool = False
        self._play_opened_once: bool = False
        self._watch_warned_capture: bool = False
        self._watch_warned_play: bool = False
        self._play_task = None
        self._tg = None
        # WASAPI kesinti sayacı: 10 sn pencerede 20'yi bulunca aygıt başına
        # tek satır uyarı (kilitli; swap'e kadar tekrarlamaz).
        self._disc_count: int = 0
        self._disc_window_start: float = time.monotonic()
        self._disc_notice_given: bool = False
        self._disc_lock = threading.Lock()
        # soundcard importundaki 'always' filtresinin önüne geçen global susturma;
        # blok başına değil, bir kez kurulur.
        ensure_discontinuity_suppressed()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def set_volume(self, val: float) -> None:
        self.volume = max(0.0, min(2.0, float(val)))

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)

    def set_dub_exclude(self, enabled: bool) -> None:
        """Aynı hoparlörde dublaj açıkken yakalamayı kendi sürecimiz dışında tut.

        Uç susturması çeviriyi de keser; diğer oturumlar susunca sıradan
        döngü kaynağı da susar. Exclude döngüsü o susturmadan önce akar.
        """
        enabled = bool(enabled)
        with self._io_lock:
            if self._dub_exclude == enabled:
                return
            self._dub_exclude = enabled
            self._dub_generation += 1

    def _dub_state(self) -> tuple[bool, int]:
        with self._io_lock:
            return self._dub_exclude, self._dub_generation

    # -- Hot-swap API (thread-safe; çeviri oturumunu öldürmez) --------------
    @staticmethod
    def _device_key(dev) -> tuple:
        if dev is None:
            return (None, None, None)
        return (
            getattr(dev, "id", None),
            getattr(dev, "name", None),
            bool(getattr(dev, "isloopback", False)),
        )

    def _same_device(self, a, b) -> bool:
        ka, kb = self._device_key(a), self._device_key(b)
        if ka[0] is not None and kb[0] is not None:
            return ka == kb
        return ka[1] == kb[1] and ka[2] == kb[2] and ka[1] is not None

    def swap_input(self, new_mic) -> bool:
        """Çalışan yakalamayı yeni giriş aygıtına geçirir (oturum sağ kalır).

        Eski recorder yalnızca yakalama thread'i içinde kapatılır; burada
        yalnızca bekleyen aygıt kuyruğa yazılır. Aynı aygıt ise False döner.
        """
        if new_mic is None:
            return False
        with self._io_lock:
            if self._same_device(new_mic, self.source_mic) and not self._has_pending_input:
                return False
            self._pending_input = new_mic
            self._has_pending_input = True
            return True

    def swap_output(self, new_speaker) -> bool:
        """Çalışan oynatmayı yeni çıkış aygıtına geçirir (None=text-only).

        Aynı aygıt (None dahil) ise False döner.
        """
        with self._io_lock:
            cur = self.output_speaker
            if new_speaker is None and cur is None and not self._has_pending_output:
                return False
            if new_speaker is not None and self._same_device(new_speaker, cur) and not self._has_pending_output:
                return False
            self._pending_output = new_speaker
            self._has_pending_output = True
            return True

    def _take_pending_input(self):
        with self._io_lock:
            if not self._has_pending_input:
                return None, False
            dev = self._pending_input
            self._pending_input = None
            self._has_pending_input = False
            return dev, True

    def _take_pending_output(self):
        with self._io_lock:
            if not self._has_pending_output:
                return None, False
            dev = self._pending_output
            self._pending_output = None
            self._has_pending_output = False
            return dev, True

    def _peek_pending_output(self) -> bool:
        with self._io_lock:
            return self._has_pending_output

    def _peek_pending_input(self) -> bool:
        with self._io_lock:
            return self._has_pending_input

    @staticmethod
    def _rms_to_level(rms: float) -> float:
        if rms <= 1e-4:
            return 0.0
        db = 20.0 * math.log10(max(rms, 1e-9))
        return max(0.0, min(1.0, (db + 50.0) / 50.0))

    def _note(self, text: str) -> None:
        try:
            if callable(self._emit):
                self._emit(("log", text))
        except Exception:
            pass

    def _note_discontinuity(self) -> None:
        """Tek kesinti kaydı: sayaç + 10 sn pencerede 20 olunca tek satır uyarı."""
        with self._disc_lock:
            now = time.monotonic()
            if self._disc_count == 0 or now - self._disc_window_start > 10.0:
                self._disc_window_start = now
                self._disc_count = 0
            self._disc_count += 1
            if self._disc_count == 20 and not self._disc_notice_given:
                self._disc_notice_given = True
            else:
                return
        self._note(
            "[uyarı] Giriş aygıtında kısa ses kesintileri oluyor "
            "(kablosuz aygıtlarda sık görülür, akış sürer); "
            "sürerse aygıt/sürücü gözden geçirilebilir.\n"
        )

    def request_stop(self):
        """GUI'den thread-safe durdurma; worker zaten ölmüşse sessiz geç."""
        if hasattr(self, "_user_stop"):
            self._user_stop.set()
        self._cap_stop.set()
        self._play_stop.set()
        if self._play_q is not None:
            try:
                self._play_q.put_nowait(None)
            except (queue.Full, AttributeError):
                pass
        try:
            if self._loop is not None and self._stop is not None:
                self._loop.call_soon_threadsafe(self._stop.set)
        except RuntimeError:
            pass

    async def watch_stop(self):
        await self._stop.wait()

    async def send_text(self):
        q: queue.Queue[str] = queue.Queue()
        stop_evt = threading.Event()

        def _reader():
            while not stop_evt.is_set():
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    q.put(line)
                except Exception:
                    break

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        try:
            while not (self._stop and self._stop.is_set()):
                try:
                    line = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue
                text = line.strip()
                if text.lower() == "q":
                    break
                if text and self.session is not None:
                    content = types.Content(role="user", parts=[types.Part(text=text)])
                    await self.session.send_client_content(turns=content, turn_complete=True)
        finally:
            stop_evt.set()
    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(audio=msg)

    def _post(self, msg):
        try:
            self.out_queue.put_nowait(msg)
        except asyncio.QueueFull:
            try:
                self.out_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self.out_queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def _capture_thread(self):
        """Ömrü boyunca TEK thread'de bloklayan yakalama.

        soundcard COM nesneleri thread'ler arası paylaşılamaz; her
        chunk'ta ayrı to_thread kullanmak erişim ihlaline yol açar.
        Bu thread aynı zamanda hot-swap ve hata toleransı sahibidir:
        bekleyen giriş aygıtı bloklar arasında devreye alınır, aygıt
        hataları oturumu öldürmeden aynı/bekleyen aygıtta yeniden dener.
        İlk açılış hatası hızlı başarısızlık için yükseltilir.
        """
        delay = 0.25
        while not self._cap_stop.is_set():
            # Hot-swap: bekleyen giriş varsa onu devral.
            pending_dev, has_pending = self._take_pending_input()
            if has_pending and pending_dev is not None:
                old_name = getattr(self.source_mic, "name", "?")
                self.source_mic = pending_dev
                self._input_generation += 1
                self._disc_count = 0
                self._disc_window_start = time.monotonic()
                self._disc_notice_given = False
                self._watch_warned_capture = False
                self._note(
                    f"[bilgi] Giriş aygıtı değiştirildi: {old_name} -> "
                    f"{getattr(pending_dev, 'name', '?')}\n"
                )
            try:
                self._capture_inner()
            except Exception as e:
                if self._cap_stop.is_set() or self._user_stop.is_set():
                    break
                if isinstance(e, ProcessLookupError):
                    # Kapanan uygulamanın PID'si yeniden kullanılabilir; yeniden
                    # bağlanma veya sistem sesine geri dönüş güvenli değildir.
                    if self._peek_pending_input():
                        continue
                    raise
                if isinstance(e, AssertionError):
                    # Deterministik uyumsuzluk (örn. mikrofonun sürücü mix biçimi
                    # soundcard ile açılamıyor): yeniden denemek hiç işe yaramaz,
                    # sonsuz "yeniden deneniyor" seline girmeden net bildir.
                    raise RuntimeError(
                        describe_audio_error(e, getattr(self, "source_mic", None))
                    ) from e
                if not self._capture_opened_once:
                    # İlk açılış hatası: yanlış aygıt hızlı ve net bildirilmeli.
                    raise
                # Çalışırken kopma: oturumu öldürmeden bekle + yeniden dene.
                self.last_level = 0.0
                self._note(
                    f"[uyarı] Giriş aygıtı sorunu "
                    f"({describe_audio_error(e)}); yeniden deneniyor...\n"
                )
                if self._cap_stop.wait(min(delay, 5.0)):
                    break
                delay = min(delay * 2.0, 5.0)
                continue
            # Normal çıkış: durdurma mı yoksa hot-swap mı?
            if self._cap_stop.is_set():
                break
            if self._peek_pending_input():
                delay = 0.25
                continue
            # Beklenmedik iç çıkış (kayıt nesnesi kapandıysa): kısa bekleyip aç.
            if self._cap_stop.wait(0.25):
                break
            delay = 0.25

    def _capture_inner(self):
        exclude, seen_dub = self._dub_state()
        # Exclude akışında çeviri zaten yakalamaya girmez; yankı susturması
        # kaynak konuşmayı da kesmesin.
        is_loopback = False if exclude else getattr(self.source_mic, "isloopback", False)
        same_endpoint = is_loopback and _is_same_endpoint(self.source_mic, self.output_speaker)
        seen_output_gen = self._output_generation
        conv = AudioConverter(in_rate=CAPTURE_RATE, out_rate=SEND_SAMPLE_RATE)
        ch = 2 if exclude else (1 if getattr(self.source_mic, "channels", 2) == 1 else 2)
        if exclude:
            from process_audio import exclude_self_recorder
            opener = exclude_self_recorder(
                samplerate=CAPTURE_RATE, channels=ch, blocksize=CAPTURE_BUFFER_BLOCKS,
            )
        else:
            opener = self.source_mic.recorder(
                samplerate=CAPTURE_RATE, channels=ch, blocksize=CAPTURE_BUFFER_BLOCKS,
            )
        with opener as mic:
            self._capture_opened_once = True
            self._capture_heartbeat = time.monotonic()
            # Oturum-seviyesi uyarı hook'u: recorder ömrü boyunca BİR kez kurulur.
            # Blok başına catch_warnings global filtreyi saniyede ~50 kez
            # değiştirip diğer thread'lerin uyarılarını yutuyor/sızdırıyordu.
            with warnings.catch_warnings():
                # Yalnızca kesinti mesajı 'always' yapılır; diğer uyarılar dış
                # filtrelere (örn. testteki 'error') aynen düşer.
                warnings.filterwarnings("always", message=".*data discontinuity.*")
                orig_show = warnings.showwarning

                def _showwarning(message, category, filename, lineno, file=None, line=None):
                    try:
                        if _is_discontinuity_warning(message, category):
                            self._note_discontinuity()
                            return
                    except Exception:
                        pass
                    try:
                        orig_show(message, category, filename, lineno, file, line)
                    except Exception:
                        pass

                warnings.showwarning = _showwarning
                try:
                    while not self._cap_stop.is_set():
                        if self._peek_pending_input() or self._dub_state()[1] != seen_dub:
                            # Eski akış `with` çıkışında düzgün kapatılır.
                            return
                        try:
                            frame, _discontinued = _record_block(mic)
                        except Exception:
                            # Kayıt hatası: iç bağlamı kapatıp dış döngüde yeniden aç.
                            raise
                        self._capture_heartbeat = time.monotonic()
                        if frame is None or len(frame) == 0:
                            self.last_level = 0.0
                            continue
                        arr = np.asarray(frame, dtype=np.float32)
                        mono = arr.mean(axis=1) if arr.ndim > 1 else arr
                        rms = (
                            float(np.sqrt(np.dot(mono, mono) / len(mono)))
                            if len(mono) > 0
                            else 0.0
                        )
                        # VU ham giriş seviyesini gösterir; yankı yalnızca Gemini'ye
                        # gönderilen PCM'de susturulur.
                        self.last_level = self._rms_to_level(rms)
                        if self._paused.is_set():
                            continue
                        # Çıkış hot-swap olduysa yankı bastırma hedefini tazele.
                        if seen_output_gen != self._output_generation:
                            seen_output_gen = self._output_generation
                            same_endpoint = is_loopback and _is_same_endpoint(
                                self.source_mic, self.output_speaker
                            )
                        suppress_echo = same_endpoint and time.monotonic() < self._playback_until + 0.15
                        pcm = conv.process(np.zeros_like(mono) if suppress_echo else mono)
                        if not pcm:
                            continue

                        if suppress_echo or (self.vad_threshold > 0.0 and rms < self.vad_threshold):
                            # Live Translate sürekli ses akışı bekler. Paket atmak
                            # yerine aynı süreli sessizlik gönder; yankı/sessizlik
                            # sonraki çeviriyi bekleyen modeli aç bırakmasın.
                            pcm = bytes(len(pcm))
                        elif rms >= max(0.005, self.vad_threshold):
                            if not self._waiting_response:
                                self._last_speech_time = time.monotonic()
                                self._waiting_response = True

                        try:
                            if self._loop is not None and not self._loop.is_closed():
                                self._loop.call_soon_threadsafe(
                                    self._post, {"data": pcm, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"}
                                )
                            else:
                                self._post({"data": pcm, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"})
                        except RuntimeError:
                            break
                finally:
                    try:
                        warnings.showwarning = orig_show
                    except Exception:
                        pass

    async def listen_system(self):
        # to_thread'in executor thread'i non-daemon: bloklanan record()
        # çağrısı proses çıkışını asabilir. Daemon thread + done olayı
        # ile kapanış garanti altında.
        done = asyncio.Event()
        err: list[BaseException] = []

        def _wrapper():
            try:
                self._capture_thread()
            except BaseException as e:
                err.append(e)
            finally:
                try:
                    self._loop.call_soon_threadsafe(done.set)
                except RuntimeError:
                    pass

        threading.Thread(target=_wrapper, daemon=True).start()
        try:
            await done.wait()
            if err and not self._cap_stop.is_set():
                raise RuntimeError(f"Giriş ses aygıtı hatası (bağlantı koptu mu?): {err[0]}") from err[0]
            if not self._cap_stop.is_set():
                raise RuntimeError("Giriş ses aygıtı beklenmedik şekilde durdu.")
        finally:
            self._cap_stop.set()
            try:
                await asyncio.wait_for(done.wait(), timeout=0.8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
    def _console_emit(self, msg):
        if not isinstance(msg, tuple):
            print(msg, end="", flush=True)
            return
        kind = msg[0]
        if kind == "level":
            return
        if kind in ("heard", "trans"):
            if self._active_stream != kind:
                if self._active_stream is not None:
                    print()
                self._active_stream = kind
                print("Duyulan:\n" if kind == "heard" else "Çeviri:\n", end="", flush=True)
            print(msg[1], end="", flush=True)
        elif kind in ("heard_end", "trans_end"):
            if self._active_stream == kind.removesuffix("_end"):
                self._active_stream = None
            print("\n", flush=True)
        elif kind == "log" and len(msg) > 1:
            print(msg[1], end="", flush=True)

    def _handle_tr(self, stream: str, tr) -> None:
        if stream == "heard" and tr is not None:
            lang = getattr(tr, "language_code", None)
            if lang and lang != self.detected_src:
                self.detected_src = lang
                self._emit(("detected_src", lang))
        text = getattr(tr, "text", None) or ""
        if text:
            if stream == "trans" and self._waiting_response and self._last_speech_time > 0:
                latency = (time.monotonic() - self._last_speech_time) * 1000.0
                self.last_latency_ms = latency
                self._waiting_response = False
                self._emit(("latency", round(latency, 1)))
            full, delta = merge_transcript(self._bufs[stream], text)
            self._bufs[stream] = full
            if delta:
                self._emit((stream, delta))
        if getattr(tr, "finished", False):
            self._bufs[stream] = ""
            self._emit((f"{stream}_end",))

    async def receive(self):
        while True:
            turn = self.session.receive()
            async for response in turn:
                if data := response.data:
                    if self._waiting_response and self._last_speech_time > 0:
                        latency = (time.monotonic() - self._last_speech_time) * 1000.0
                        self.last_latency_ms = latency
                        self._waiting_response = False
                        self._emit(("latency", round(latency, 1)))
                    if self.audio_in_queue is not None:
                        try:
                            self.audio_in_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            try:
                                self.audio_in_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            try:
                                self.audio_in_queue.put_nowait(data)
                            except asyncio.QueueFull:
                                pass
                content = getattr(response, "server_content", None)
                if content is not None:
                    self._handle_tr("heard", getattr(content, "input_transcription", None))
                    out_tr = getattr(content, "output_transcription", None)
                    if out_tr is not None:
                        self._handle_tr("trans", out_tr)
                    else:
                        text = response.text or ""
                        turn_done = bool(getattr(content, "turn_complete", False))
                        if text or (turn_done and self._bufs["trans"]):
                            self._handle_tr("trans", SimpleNamespace(text=text, finished=turn_done))
            # Çeviride turn_complete kuyruğu boşaltmaz: her cümle bir turn,
            # kuyruk silinince ses kesik kesik kalır.

    def _play_thread(self):
        """Tek thread'de oynatma; hot-swap ve hata toleranslı.

        Bekleyen çıkış aygıtı bloklar arasında devreye alınır, eski player
        yalnızca bu thread içinde kapatılır. İlk açılış hatası yükseltilir,
        sonraki kopmalar oturumu öldürmeden yeniden denenir.
        """
        delay = 0.25
        while not self._play_stop.is_set() and not self._user_stop.is_set():
            self._playback_until = 0.0
            pending_dev, has_pending = self._take_pending_output()
            if has_pending:
                old = self.output_speaker
                self.output_speaker = pending_dev
                self._output_generation += 1
                old_name = getattr(old, "name", "Hiçbiri") if old is not None else "Hiçbiri"
                new_name = getattr(pending_dev, "name", "Hiçbiri") if pending_dev is not None else "Hiçbiri"
                self._watch_warned_play = False
                if old_name != new_name:
                    self._note(f"[bilgi] Çıkış aygıtı değiştirildi: {old_name} -> {new_name}\n")
            speaker = self.output_speaker
            if speaker is None:
                self._play_drain_until_speaker_or_stop()
                if self._play_stop.is_set() or self._user_stop.is_set():
                    break
                # Bekleyen aygıt geldi (veya stop): döngü başı yeniden değerlendirir.
                continue
            try:
                done_reason = self._play_inner(speaker)
            except Exception as e:
                self._playback_until = 0.0
                if self._play_stop.is_set() or self._user_stop.is_set():
                    break
                if isinstance(e, AssertionError):
                    raise RuntimeError(
                        describe_audio_error(e, getattr(self, "output_speaker", None))
                    ) from e
                if not self._play_opened_once:
                    raise
                self._note(
                    f"[uyarı] Çıkış aygıtı sorunu "
                    f"({describe_audio_error(e)}); yeniden deneniyor...\n"
                )
                # Yeniden denemeden önce kısa bekle; beklerken swap/stop gözet.
                deadline = time.monotonic() + min(delay, 5.0)
                delay = min(delay * 2.0, 5.0)
                while time.monotonic() < deadline:
                    if self._play_stop.is_set() or self._user_stop.is_set():
                        break
                    if self._peek_pending_output():
                        break
                    time.sleep(0.05)
                continue
            delay = 0.25
            if self._play_stop.is_set() or self._user_stop.is_set():
                break
            if self._peek_pending_output():
                continue
            if done_reason == "swap":
                continue
            # Temiz kapanış (kuyruktaki None): test ve teardown davranışını koru.
            break

    def _play_drain_until_speaker_or_stop(self):
        """Text-only modu: gelen sesi çalmadan tüket, aygıt/stop bekle."""
        while not self._play_stop.is_set() and not self._user_stop.is_set():
            if self._peek_pending_output():
                return
            q = self._play_q
            if q is None:
                time.sleep(0.05)
                self._play_heartbeat = time.monotonic()
                continue
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                self._play_heartbeat = time.monotonic()
                continue
            self._play_heartbeat = time.monotonic()
            if item is None:
                return

    def _play_inner(self, speaker) -> str:
        """Tek player ömrü; 'done' (None) ya da 'swap' ile döner.

        Yastık Python'da tutulursa cihaz boşalır, paket arasında sessizlik
        basar ve sonraki örnek sıfırdan girince çıt çıkar. Preroll dolunca
        ses (son 8 ms hariç) hemen WASAPI tamponuna yazılır. Tampon ~120 ms:
        paket gecikmesi bu süreyi aşmadan cihaz susmaz. Cümle bitmek
        üzereyken elde kalan son örnekler kosinüsle iner.
        """
        preroll_n = int(RECEIVE_SAMPLE_RATE * 0.08)  # ~80 ms başlangıç yastığı
        fade_n = max(2, int(RECEIVE_SAMPLE_RATE * 0.008))  # ~8 ms tıkırtı rampa
        device_block = int(RECEIVE_SAMPLE_RATE * 0.12)  # WASAPI tamponu, ~120 ms
        gap_end_s = 0.2
        underrun_lead_s = 0.025
        split_n = 2048  # hot-swap tepkisi için oynatma dilimi
        pending: list[np.ndarray] = []
        pending_n = 0
        hold_n = preroll_n
        started = False
        queued_until = 0.0
        empty_since: float | None = None
        leftover = bytearray()
        with speaker.player(
            samplerate=RECEIVE_SAMPLE_RATE, channels=1, blocksize=device_block
        ) as sp:
            self._play_opened_once = True
            self._play_heartbeat = time.monotonic()

            def _play_chunk(audio_raw: np.ndarray) -> bool:
                """Dilimli oynatma; swap/stop görülürse False döner."""
                nonlocal queued_until
                if self.muted or self.volume <= 0.0 or audio_raw.size == 0:
                    return True
                if abs(self.volume - 1.0) > 1e-3:
                    audio_raw = np.clip(audio_raw * self.volume, -1.0, 1.0)
                pos = 0
                total = int(audio_raw.size)
                while pos < total:
                    if self._play_stop.is_set() or self._user_stop.is_set():
                        return False
                    if self._peek_pending_output():
                        return False
                    piece = audio_raw[pos:pos + split_n]
                    n = int(piece.size)
                    queued_until = max(queued_until, time.monotonic()) + n / RECEIVE_SAMPLE_RATE
                    # Sessiz PCM de oynatılır (zamanlama korunur), fakat yankı
                    # kapısını açık tutmaz. RMS eşiği -80 dBFS: nicemleme tabanı.
                    loud = float(np.dot(piece, piece)) > n * 1e-8
                    if loud:
                        self._playback_until = queued_until

                    def _halt() -> bool:
                        return (
                            self._play_stop.is_set()
                            or self._user_stop.is_set()
                            or self._peek_pending_output()
                        )

                    written = write_playback(sp, piece, stop=_halt)
                    self._play_heartbeat = time.monotonic()
                    if written < n:
                        queued_until -= (n - written) / RECEIVE_SAMPLE_RATE
                        if loud:
                            self._playback_until = queued_until
                        return False
                    pos += split_n
                return True

            def _commit_pending() -> bool:
                """Cihaza, fade kuyruğu hariç birikmiş sesi yaz."""
                nonlocal pending_n
                if pending_n <= hold_n:
                    return True
                buf = np.concatenate(pending)
                pending.clear()
                if not _play_chunk(buf[:-hold_n]):
                    return False
                pending.append(buf[-hold_n:].copy())
                pending_n = hold_n
                return True

            def _end_phrase(fade_in: bool) -> bool:
                """Kuyruğu sessizliğe indir; sonraki cümle yeniden fade-in yapsın."""
                nonlocal pending_n, started, hold_n
                buf = np.concatenate(pending) if pending else np.empty(0, dtype=np.float32)
                pending.clear()
                pending_n = 0
                started = False
                hold_n = preroll_n
                leftover.clear()
                if buf.size == 0:
                    return True
                if fade_in:
                    buf = cosine_fade(buf, fade_n, fade_in=True)
                buf = cosine_fade(buf, fade_n, fade_in=False)
                return _play_chunk(buf)

            def _queue_audio(audio: np.ndarray) -> bool:
                nonlocal pending_n, started, hold_n
                if audio.size == 0:
                    return True
                if pending and pending[-1].size:
                    audio = soften_join(float(pending[-1][-1]), audio)
                pending.append(audio)
                pending_n += int(audio.size)
                if not started:
                    if pending_n < preroll_n:
                        return True
                    buf = cosine_fade(np.concatenate(pending), fade_n, fade_in=True)
                    pending.clear()
                    pending.append(buf)
                    pending_n = int(buf.size)
                    started = True
                    # Yastığın kendisi cihazda kalsın; Python'da yalnız fade kuyruğu.
                    hold_n = fade_n
                return _commit_pending()

            while not self._play_stop.is_set() and not self._user_stop.is_set():
                if self._peek_pending_output():
                    return "swap"
                try:
                    timeout = 0.01 if started else 0.05
                    pcm = self._play_q.get(timeout=timeout)
                except queue.Empty:
                    self._play_heartbeat = time.monotonic()
                    now = time.monotonic()
                    if empty_since is None:
                        empty_since = now
                    elapsed = now - empty_since
                    remaining = queued_until - now
                    # Cihaz susmadan son örnekleri indir. Tampon çoktan bittiyse
                    # kuyruğu geri çalma: araya giren sessizliğin üstüne sıçrar.
                    if started and pending_n and remaining <= underrun_lead_s:
                        if remaining < 0.0:
                            pending.clear()
                            pending_n = 0
                            started = False
                            hold_n = preroll_n
                            leftover.clear()
                        elif not _end_phrase(fade_in=False):
                            return "swap"
                    elif pending_n and not started and elapsed >= gap_end_s:
                        if not _end_phrase(fade_in=True):
                            return "swap"
                    elif started and not pending_n and elapsed >= gap_end_s:
                        started = False
                        hold_n = preroll_n
                        leftover.clear()
                    continue
                except AttributeError:
                    # _play_q henüz yok (teardown yarışı): bekle.
                    time.sleep(0.05)
                    continue
                empty_since = None
                self._play_heartbeat = time.monotonic()
                if pcm is None:
                    break
                if not _queue_audio(pcm16_to_float(pcm, leftover)):
                    return "swap"
            if pending and not self._peek_pending_output():
                _play_chunk(np.concatenate(pending))
                pending.clear()
            return "done"
        return "done"

    async def _watch_audio(self):
        """Gözetmen: kalp atışı uyarıları + text-only'den hoparlöre geçişte
        oynatma hattını oturumu öldürmeden ayağa kaldırır."""
        try:
            while True:
                await asyncio.sleep(0.5)
                if self._cap_stop.is_set() or self._user_stop.is_set():
                    return
                if self._stop is not None and self._stop.is_set():
                    return
                now = time.monotonic()
                # Yakalama duraksama uyarısı (ölçülü: stall başına bir kez).
                if now - self._capture_heartbeat > 6.0 and not self._watch_warned_capture:
                    self._watch_warned_capture = True
                    self._note("[uyarı] Giriş ses akışı duraksadı; aygıt denetleniyor...\n")
                elif now - self._capture_heartbeat <= 6.0:
                    self._watch_warned_capture = False
                play_task = self._play_task
                play_alive = play_task is not None and not play_task.done()
                if play_alive and now - self._play_heartbeat > 6.0 and not self._watch_warned_play:
                    self._watch_warned_play = True
                    self._note("[uyarı] Çıkış ses akışı duraksadı; aygıt denetleniyor...\n")
                elif play_alive and now - self._play_heartbeat <= 6.0:
                    self._watch_warned_play = False
                # Text-only başladıktan sonra hoparlör seçildiyse hattı kur.
                wants_audio = self.output_speaker is not None or self._peek_pending_output()
                tg = getattr(self, "_tg", None)
                if wants_audio and not play_alive and tg is not None:
                    if self.audio_in_queue is None:
                        self.audio_in_queue = asyncio.Queue(maxsize=200)
                    try:
                        self._play_task = tg.create_task(self.play())
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass

    async def play(self):
        self._play_task = asyncio.current_task()
        self._play_q = BoundedByteQueue(max_bytes=int(RECEIVE_SAMPLE_RATE * 2 * 2.5))
        done = asyncio.Event()
        err: list[BaseException] = []

        def _wrapper():
            try:
                self._play_thread()
            except BaseException as e:
                err.append(e)
            finally:
                try:
                    self._loop.call_soon_threadsafe(done.set)
                except RuntimeError:
                    pass

        threading.Thread(target=_wrapper, daemon=True).start()
        done_task = asyncio.create_task(done.wait())
        try:
            while True:
                if self.audio_in_queue is None:
                    # Henüz kuyruk yok (text-only başlangıç yarışı): bekle.
                    await asyncio.sleep(0.1)
                    if done_task.done():
                        break
                    continue
                get_task = asyncio.create_task(self.audio_in_queue.get())
                finished, _ = await asyncio.wait(
                    [get_task, done_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if done_task in finished:
                    get_task.cancel()
                    if err and not self._play_stop.is_set():
                        raise RuntimeError(f"Çıkış ses aygıtı hatası (bağlantı koptu mu?): {err[0]}") from err[0]
                    if not self._play_stop.is_set():
                        raise RuntimeError("Çıkış ses aygıtı beklenmedik şekilde durdu.")
                    break
                bytestream = get_task.result()
                try:
                    self._play_q.put_nowait(bytestream)
                except queue.Full:
                    try:
                        self._play_q.get_nowait()
                    except queue.Empty:
                        pass
                    self._play_q.put_nowait(bytestream)
        finally:
            self._play_stop.set()
            if not done_task.done():
                done_task.cancel()
            try:
                if self._play_q is not None:
                    self._play_q.put_nowait(None)
            except queue.Full:
                try:
                    self._play_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._play_q.put_nowait(None)
                except queue.Full:
                    pass
            except AttributeError:
                pass
            try:
                await asyncio.wait_for(done.wait(), timeout=0.8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            if self._play_task is asyncio.current_task():
                self._play_task = None
            if err and not self._user_stop.is_set():
                raise RuntimeError(f"Çıkış ses aygıtı hatası: {err[0]}") from err[0]
    async def run(self):
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        run_task = asyncio.current_task()

        async def cancel_on_stop():
            await self._stop.wait()
            run_task.cancel()

        stop_task = asyncio.create_task(cancel_on_stop())
        try:
            # request_stop() may have run before the event loop was available.
            if self._user_stop.is_set():
                raise asyncio.CancelledError("Kullanıcı çıkışı")
            async with (
                self.client.aio.live.connect(model=self.model, config=self.config) as session,
                asyncio.TaskGroup() as tg,
            ):
                # Connection entry can finish before the queued stop callback runs.
                if self._user_stop.is_set():
                    raise asyncio.CancelledError("Kullanıcı çıkışı")
                self.session = session
                if self._emit is not None:
                    self._emit(("status", "Dinleniyor"))
                self.audio_in_queue = (
                    asyncio.Queue(maxsize=200) if self.output_speaker is not None else None
                )
                self.out_queue = asyncio.Queue(maxsize=50)
                self._tg = tg
                self._play_task = None
                tg.create_task(self.send_realtime())
                tg.create_task(self.listen_system())
                tg.create_task(self.receive())
                tg.create_task(self._watch_audio())
                if self.output_speaker is not None:
                    self._play_task = tg.create_task(self.play())
                if self.console_input:
                    await self.send_text()
                else:
                    await self.watch_stop()
                raise asyncio.CancelledError("Kullanıcı çıkışı")
        finally:
            self._cap_stop.set()
            self._play_stop.set()
            self._tg = None
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            self.session = None
            if hasattr(self.client, "aio") and hasattr(self.client.aio, "aclose"):
                try:
                    await self.client.aio.aclose()
                except Exception:
                    pass
            if hasattr(self.client, "close"):
                try:
                    self.client.close()
                except Exception:
                    pass

    def close(self):
        """SDK istemci kaynaklarını serbest bırakır (R04)."""
        if hasattr(self.client, "close"):
            try:
                self.client.close()
            except Exception:
                pass
