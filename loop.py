"""Gemini Live oturumu: yakala → çevir → oynat."""

from __future__ import annotations

import asyncio
import queue
import threading
import os
import time
from types import SimpleNamespace

import numpy as np
from google import genai
from google.genai import types

from audio import (
    CAPTURE_BLOCK,
    CAPTURE_RATE,
    RECEIVE_SAMPLE_RATE,
    SEND_SAMPLE_RATE,
    pcm16_to_float,
    to_16k_mono,
)
DEFAULT_MODEL = "models/gemini-3.5-live-translate-preview"
MODEL = os.environ.get("GEMINI_LIVE_MODEL") or DEFAULT_MODEL


def build_config(
    src: str | None,
    dst: str,
    modalities: list[str] | None = None,
) -> types.LiveConnectConfig:
    if src:
        input_tr = types.AudioTranscriptionConfig(language_codes=[src])
    else:
        input_tr = types.AudioTranscriptionConfig()
    mods = modalities or ["AUDIO"]
    out_tr = types.AudioTranscriptionConfig() if "AUDIO" in mods else None
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
        src: str | None,
        dst: str,
        source_mic,
        api_key: str,
        output_speaker=None,
        on_text=None,
        console_input: bool = True,
        model: str | None = None,
    ):
        self.model = model or os.environ.get("GEMINI_LIVE_MODEL") or DEFAULT_MODEL
        self.client = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=api_key,
        )
        self.source_mic = source_mic
        self.output_speaker = output_speaker
        modalities = ["TEXT"] if self.output_speaker is None else ["AUDIO"]
        self.config = build_config(src, dst, modalities=modalities)
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
        self._active_stream: str | None = None
        self.last_level: float = 0.0
        self._last_level_emit: float = 0.0
        self._playback_until: float = 0.0
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
        """
        is_loopback = getattr(self.source_mic, "isloopback", False)
        with self.source_mic.recorder(
            samplerate=CAPTURE_RATE, channels=2, blocksize=CAPTURE_BLOCK
        ) as mic:
            while not self._cap_stop.is_set():
                frame = mic.record(numframes=CAPTURE_BLOCK)
                if frame is None or len(frame) == 0:
                    continue
                if is_loopback and self.output_speaker is not None:
                    if time.monotonic() < self._playback_until + 0.15:
                        continue
                arr = np.asarray(frame, dtype=np.float32)
                pcm = to_16k_mono(arr)
                if self._emit is not None and self._loop is not None:
                    mono = arr.mean(axis=1) if arr.ndim > 1 else arr
                    rms = (
                        float(np.sqrt(np.dot(mono, mono) / len(mono)))
                        if len(mono) > 0
                        else 0.0
                    )
                    lvl = min(1.0, rms * 8.0)
                    self.last_level = lvl
                    now = time.monotonic()
                    if now - self._last_level_emit >= 0.08:
                        self._last_level_emit = now
                        try:
                            self._loop.call_soon_threadsafe(
                                self._emit, ("level", lvl)
                            )
                        except RuntimeError:
                            pass
                try:
                    self._loop.call_soon_threadsafe(
                        self._post, {"data": pcm, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"}
                    )
                except RuntimeError:
                    break

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
                    continue
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
                        audio = np.concatenate(pending)
                        self._playback_until = time.monotonic() + len(audio) / RECEIVE_SAMPLE_RATE
                        sp.play(audio)
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
                self._playback_until = time.monotonic() + len(audio) / RECEIVE_SAMPLE_RATE
                sp.play(audio)
            if pending:
                audio = np.concatenate(pending)
                self._playback_until = time.monotonic() + len(audio) / RECEIVE_SAMPLE_RATE
                sp.play(audio)
                pending.clear()

    async def play(self):
        self._play_q = queue.Queue(maxsize=200)
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
            try:
                await asyncio.wait_for(done.wait(), timeout=0.8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            if err and not self._user_stop.is_set():
                raise RuntimeError(f"Çıkış ses aygıtı hatası: {err[0]}") from err[0]
    async def run(self):
        async with (
            self.client.aio.live.connect(model=self.model, config=self.config) as session,
            asyncio.TaskGroup() as tg,
        ):
            self.session = session
            self._loop = asyncio.get_running_loop()
            if self._emit is not None:
                self._emit(("status", "Dinleniyor"))
            self._stop = asyncio.Event()
            self._cap_stop.clear()
            self._play_stop.clear()
            self.audio_in_queue = (
                asyncio.Queue(maxsize=200) if self.output_speaker is not None else None
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
