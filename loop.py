"""Gemini Live oturumu: yakala → çevir → oynat."""

from __future__ import annotations

import asyncio
import queue
import threading
from types import SimpleNamespace

import numpy as np
from google import genai
from google.genai import types

from audio import (
    CAPTURE_BLOCK,
    CAPTURE_RATE,
    RECEIVE_SAMPLE_RATE,
    pcm16_to_float,
    to_16k_mono,
)

MODEL = "models/gemini-3.5-live-translate-preview"


def build_config(src: str | None, dst: str) -> types.LiveConnectConfig:
    if src:
        input_tr = types.AudioTranscriptionConfig(language_codes=[src])
    else:
        input_tr = types.AudioTranscriptionConfig()
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=input_tr,
        output_audio_transcription=types.AudioTranscriptionConfig(),
        context_window_compression=types.ContextWindowCompressionConfig(
            trigger_tokens=0,
            sliding_window=types.SlidingWindow(target_tokens=0),
        ),
        translation_config=types.TranslationConfig(
            target_language_code=dst,
        ),
    )


def merge_transcript(prev: str, incoming: str) -> tuple[str, str]:
    """Gelen parça delta veya kümülatif olabilir; (tam metin, eklenecek) döner."""
    if not incoming:
        return prev, ""
    if prev and incoming.startswith(prev):
        return incoming, incoming[len(prev) :]
    return prev + incoming, incoming


class SystemAudioLoop:
    def __init__(
        self,
        src,
        dst,
        source_mic,
        api_key,
        output_speaker=None,
        on_text=None,
        console_input=True,
    ):
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
        self._user_stop = threading.Event()
        self._play_q: queue.Queue | None = None
        self._bufs = {"heard": "", "trans": ""}
        self._open = {"heard": False, "trans": False}

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
                arr = np.asarray(frame, dtype=np.float32)
                if self._emit is not None and self._loop is not None:
                    rms = float(np.sqrt(np.mean(arr**2)))
                    try:
                        self._loop.call_soon_threadsafe(
                            self._emit, ("level", min(1.0, rms * 8.0))
                        )
                    except RuntimeError:
                        pass
                pcm = to_16k_mono(arr)
                try:
                    self._loop.call_soon_threadsafe(
                        self._post, {"data": pcm, "mime_type": "audio/pcm"}
                    )
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
        try:
            await done.wait()
        finally:
            self._cap_stop.set()
            try:
                await asyncio.shield(done.wait())
            except asyncio.CancelledError:
                pass

    def _console_emit(self, msg):
        if not isinstance(msg, tuple):
            print(msg, end="", flush=True)
            return
        kind = msg[0]
        if kind == "level":
            return
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
                    if self.audio_in_queue is not None:
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
        speaker = self.output_speaker
        if speaker is None:
            return
        preroll_n = int(RECEIVE_SAMPLE_RATE * 0.08)  # ~80 ms jitter tamponu
        pending: list[np.ndarray] = []
        pending_n = 0
        started = False
        with speaker.player(
            samplerate=RECEIVE_SAMPLE_RATE, channels=1, blocksize=2048
        ) as sp:
            while not self._play_stop.is_set():
                try:
                    pcm = self._play_q.get(timeout=0.05)
                except queue.Empty:
                    if pending:
                        sp.play(np.concatenate(pending))
                        pending.clear()
                        pending_n = 0
                    started = False
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
            if pending:
                sp.play(np.concatenate(pending))
                pending.clear()

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
            self.audio_in_queue = (
                asyncio.Queue() if self.output_speaker is not None else None
            )
            self.out_queue = asyncio.Queue(maxsize=50)
            stopper = self.send_text() if self.console_input else self.watch_stop()
            stop_task = tg.create_task(stopper)
            tg.create_task(self.send_realtime())
            tg.create_task(self.listen_system())
            tg.create_task(self.receive())
            if self.output_speaker is not None:
                tg.create_task(self.play())
            await stop_task
            self._cap_stop.set()
            self._play_stop.set()
            raise asyncio.CancelledError("Kullanıcı çıkışı")
