"""PC'de çalan sistem sesini Gemini Live Translate ile canlı çevirir.

Örnek AI Studio kodundan farkı: mikrofon + kamera yerine
WASAPI loopback üzerinden hoparlörden çıkan sesi yakalar.

Kurulum:
    pip install -r requirements.txt
    # .env dosyasına veya ortama: GEMINI_API_KEY=...

Kullanım:
    python live_translate.py --list-devices   # loopback cihazlarını listele
    python live_translate.py                  # varsayılan hoparlörü en->tr çevir
    python live_translate.py --src en --dst tr --device Kulaklık
    python live_translate.py --mic            # sistem sesi yerine mikrofon
"""

import argparse
import asyncio
import os
import queue
import sys
import threading
from types import SimpleNamespace

import numpy as np

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    import soundcard as sc
except ImportError:
    print("soundcard kurulu değil: pip install soundcard")
    sys.exit(1)

from google import genai
from google.genai import types

SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CAPTURE_RATE = 48000  # Windows mix format; yakalanıp 16k'ya indirilir
CAPTURE_BLOCK = 960  # 48000 Hz'de 20 ms
MODEL = "models/gemini-3.5-live-translate-preview"


def build_config(src: str, dst: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=[src],
        ),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=0,
            sliding_window=types.SlidingWindow(target_tokens=0),
        ),
        translation_config=types.TranslationConfig(
            target_language_code=dst,
        ),
    )


def list_devices() -> None:
    print("Hoparlörler:")
    for s in sc.all_speakers():
        default = " (varsayılan)" if s == sc.default_speaker() else ""
        print(f"  - {s.name}{default}")
    print("Loopback (sistem sesi) kaynakları:")
    for m in sc.all_microphones(include_loopback=True):
        if m.isloopback:
            print(f"  - {m.name}")
    print("Mikrofonlar:")
    for m in sc.all_microphones(include_loopback=True):
        if not m.isloopback:
            print(f"  - {m.name}")


def pick_loopback(device_substr: str | None):
    loops = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not loops:
        raise RuntimeError("Loopback cihaz bulunamadı.")
    if device_substr:
        for m in loops:
            if device_substr.lower() in m.name.lower():
                return m
        raise RuntimeError(f"'{device_substr}' ile eşleşen loopback cihaz yok.")
    default_sp = sc.default_speaker()
    for m in loops:
        if default_sp.name in m.name or m.name in default_sp.name:
            return m
    return loops[0]


def merge_transcript(prev: str, incoming: str) -> tuple[str, str]:
    """Gelen parça delta veya kümülatif olabilir; (tam metin, eklenecek) döner."""
    if not incoming:
        return prev, ""
    if prev and incoming.startswith(prev):
        return incoming, incoming[len(prev):]
    return prev + incoming, incoming


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    """Gemini PCM16 (24 kHz) → soundcard'ın beklediği [-1, 1] float32."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return np.empty(0, dtype=np.float32)
    return samples.astype(np.float32) * (1.0 / 32768.0)


def to_16k_mono(frame: np.ndarray) -> bytes:
    """float32 (n, ch) yakalamayı 16 kHz mono int16 PCM'e çevirir."""
    mono = frame.mean(axis=1).astype(np.float32)
    n_out = int(len(mono) * SEND_SAMPLE_RATE / CAPTURE_RATE)
    if n_out != len(mono):
        idx = np.linspace(0, len(mono) - 1, n_out).astype(np.float32)
        mono = np.interp(idx, np.arange(len(mono), dtype=np.float32), mono).astype(np.float32)
    pcm = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
    return pcm.tobytes()


class SystemAudioLoop:
    def __init__(self, src, dst, source_mic, api_key, output_speaker=None,
                 on_text=None, console_input=True):
        self.client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key,
        )
        self.config = build_config(src, dst)
        self.source_mic = source_mic
        self.output_speaker = output_speaker
        self._emit = on_text or self._console_emit
        self.console_input = console_input
        self.session = None
        self.audio_in_queue: asyncio.Queue | None = None
        self.out_queue: asyncio.Queue | None = None
        self._stop: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cap_stop = threading.Event()
        self._play_stop = threading.Event()
        self._play_q: queue.Queue | None = None
        self._bufs = {"heard": "", "trans": ""}
        self._open = {"heard": False, "trans": False}

    def request_stop(self):
        """GUI'den thread-safe durdurma; worker zaten ölmüşse sessiz geç."""
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
        while True:
            text = await asyncio.to_thread(input, "çıkmak için q + Enter > ")
            if text.strip().lower() == "q":
                break
            if self.session is not None:
                content = types.Content(role="user", parts=[types.Part(text=text or ".")])
                await self.session.send_client_content(turns=content, turn_complete=True)

    async def send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(audio=msg)
    def _post(self, msg):
        try:
            self.out_queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # model gerideyse eski chunk düşer

    def _capture_thread(self):
        """Ömrü boyunca TEK thread'de bloklayan yakalama.

        soundcard COM nesneleri thread'ler arası paylaşılamaz; her
        chunk'ta ayrı to_thread kullanmak erişim ihlaline yol açar.
        """
        with self.source_mic.recorder(
            samplerate=CAPTURE_RATE, channels=2, blocksize=CAPTURE_BLOCK
        ) as mic:
            while not self._cap_stop.is_set():
                frame = mic.record(numframes=CAPTURE_BLOCK)
                if frame is None or len(frame) == 0:
                    continue
                # Sessizlikte bile gönder: model cümle sınırını ancak akışla anlar.
                pcm = to_16k_mono(np.asarray(frame, dtype=np.float32))
                try:
                    self._loop.call_soon_threadsafe(
                        self._post, {"data": pcm, "mime_type": "audio/pcm"})
                except RuntimeError:
                    break

    async def listen_system(self):
        # to_thread'in executor thread'i non-daemon: bloklanan record()
        # çağrısı proses çıkışını asabilir. Daemon thread + done olayı
        # ile kapanış garanti altında.
        done = asyncio.Event()

        def _wrapper():
            try:
                self._capture_thread()
            finally:
                try:
                    self._loop.call_soon_threadsafe(done.set)
                except RuntimeError:
                    pass

        threading.Thread(target=_wrapper, daemon=True).start()
        await done.wait()

    def _console_emit(self, msg):
        if not isinstance(msg, tuple):
            print(msg, end="", flush=True)
            return
        kind = msg[0]
        if kind in ("heard", "trans"):
            if not self._open[kind]:
                self._open[kind] = True
                print("\nDuyulan:\n" if kind == "heard" else "\nÇeviri:\n", end="", flush=True)
            print(msg[1], end="", flush=True)
        elif kind in ("heard_end", "trans_end"):
            self._open[kind.removesuffix("_end")] = False
            print("\n", flush=True)
        elif kind == "log" and len(msg) > 1:
            print(msg[1], end="", flush=True)

    def _handle_tr(self, stream: str, tr) -> None:
        text = getattr(tr, "text", None) or ""
        if text:
            full, delta = merge_transcript(self._bufs[stream], text)
            self._bufs[stream] = full
            if delta:
                self._emit((stream, delta))
        if getattr(tr, "finished", False):
            self._bufs[stream] = ""
            self._open[stream] = False
            self._emit((f"{stream}_end",))

    async def receive(self):
        while True:
            turn = self.session.receive()
            async for response in turn:
                if data := response.data:
                    self.audio_in_queue.put_nowait(data)
                    continue
                content = getattr(response, "server_content", None)
                if content is not None:
                    self._handle_tr("heard", getattr(content, "input_transcription", None))
                    self._handle_tr("trans", getattr(content, "output_transcription", None))
                elif text := response.text:
                    self._handle_tr("trans", SimpleNamespace(text=text, finished=False))
            # Çeviride turn_complete kuyruğu boşaltmaz: her cümle bir turn,
            # kuyruk silinince ses kesik kesik kalır.

    def _play_thread(self):
        speaker = self.output_speaker or sc.default_speaker()
        preroll_n = int(RECEIVE_SAMPLE_RATE * 0.08)  # ~80 ms jitter tamponu
        pending: list[np.ndarray] = []
        pending_n = 0
        started = False
        with speaker.player(
            samplerate=RECEIVE_SAMPLE_RATE, channels=1, blocksize=4096
        ) as sp:
            while not self._play_stop.is_set():
                try:
                    pcm = self._play_q.get(timeout=0.05)
                except queue.Empty:
                    continue
                if pcm is None:
                    break
                audio = pcm16_to_float(pcm)
                if audio.size == 0:
                    continue
                if not started:
                    pending.append(audio)
                    pending_n += audio.size
                    if pending_n < preroll_n:
                        continue
                    audio = np.concatenate(pending)
                    pending.clear()
                    pending_n = 0
                    started = True
                sp.play(audio)

    async def play(self):
        self._play_q = queue.Queue(maxsize=200)
        done = asyncio.Event()

        def _wrapper():
            try:
                self._play_thread()
            finally:
                try:
                    self._loop.call_soon_threadsafe(done.set)
                except RuntimeError:
                    pass

        threading.Thread(target=_wrapper, daemon=True).start()
        try:
            while True:
                bytestream = await self.audio_in_queue.get()
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
            try:
                self._play_q.put_nowait(None)
            except queue.Full:
                pass
            await done.wait()

    async def run(self):
        async with (
            self.client.aio.live.connect(model=MODEL, config=self.config) as session,
            asyncio.TaskGroup() as tg,
        ):
            self.session = session
            self._loop = asyncio.get_running_loop()
            self._stop = asyncio.Event()
            self._cap_stop.clear()
            self._play_stop.clear()
            self.audio_in_queue = asyncio.Queue()
            self.out_queue = asyncio.Queue(maxsize=50)
            stopper = self.send_text() if self.console_input else self.watch_stop()
            stop_task = tg.create_task(stopper)
            tg.create_task(self.send_realtime())
            tg.create_task(self.listen_system())
            tg.create_task(self.receive())
            tg.create_task(self.play())
            await stop_task
            self._cap_stop.set()
            self._play_stop.set()
            raise asyncio.CancelledError("Kullanıcı çıkışı")


def main() -> None:
    parser = argparse.ArgumentParser(description="PC sistem sesini canlı çevir")
    parser.add_argument("--src", default="en", help="kaynak dil (varsayılan: en)")
    parser.add_argument("--dst", default="tr", help="hedef dil (varsayılan: tr)")
    parser.add_argument("--device", default=None, help="loopback cihaz adı filtresi")
    parser.add_argument("--mic", action="store_true", help="sistem sesi yerine mikrofon")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    api_key = args.api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY bulunamadı. Ortama veya .env dosyasına ekleyin.")
        print("Alın: https://aistudio.google.com/apikey")
        sys.exit(1)

    if args.mic:
        source = sc.default_microphone()
        print(f"Mikrofon yakalanıyor: {source.name}")
    else:
        source = pick_loopback(args.device)
        print(f"Sistem sesi yakalanıyor (loopback): {source.name}")
    print(f"{args.src} -> {args.dst} çeviri başlıyor. Durdurmak: q + Enter veya Ctrl+C")

    loop = SystemAudioLoop(args.src, args.dst, source, api_key)
    try:
        asyncio.run(loop.run())
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
