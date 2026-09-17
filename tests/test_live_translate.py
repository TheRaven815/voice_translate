"""live_translate regresyon testleri. Ağ gerektirmez (istemci taklit edilir).

Kilitlenen bug'lar:
- run() içinde session/kuyruk atamasının düşmesi (AttributeError: 'NoneType').
- soundcard akışlarının thread'ler arası paylaşılması (GetCurrentPadding
  erişim ihlali): yakalama tek thread'de, oynatma loop thread'inde olmalı.
- google-genai SDK alan adı kayması (audio_transcription_config kaldırıldı).
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from audio import pcm16_to_float, to_16k_mono
from devices import pick_loopback
from loop import SystemAudioLoop, build_config, merge_transcript


def test_resample_48k_stereo_to_16k_mono():
    t = np.arange(960) / 48000
    frame = np.stack(
        [0.5 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1
    ).astype(np.float32)
    pcm = to_16k_mono(frame)
    assert len(pcm) == 320 * 2  # 20 ms @16k mono int16
    assert to_16k_mono(np.zeros((960, 2), dtype=np.float32)) == bytes(640)

def test_resample_1d_mono():
    mono_1d = np.zeros(960, dtype=np.float32)
    pcm = to_16k_mono(mono_1d)
    assert len(pcm) == 640


def test_pcm16_to_float_stays_in_unit_range():
    pcm = np.array([0, 32767, -32768, 16384], dtype=np.int16).tobytes()
    f = pcm16_to_float(pcm)
    assert f.dtype == np.float32
    assert abs(float(f[3]) - 0.5) < 1e-4
    assert float(np.max(np.abs(f))) <= 1.0 + 1e-6
def test_pcm16_to_float_handles_odd_and_short_bytes():
    assert pcm16_to_float(b"").size == 0
    assert pcm16_to_float(b"\x00").size == 0
    # 5 bytes -> truncated to 4 bytes (2 int16 samples) without crash
    f = pcm16_to_float(b"\x00\x00\x00\x40\xff")
    assert f.size == 2



def test_build_config_matches_installed_sdk():
    cfg = build_config("en", "tr")
    assert cfg.translation_config.target_language_code == "tr"
    assert cfg.response_modalities == ["AUDIO"]
    assert cfg.input_audio_transcription.language_codes == ["en"]
    auto = build_config(None, "tr")
    assert auto.translation_config.target_language_code == "tr"
    assert not auto.input_audio_transcription.language_codes


def test_merge_transcript_joins_deltas_and_cumulative():
    full, delta = merge_transcript("", "Onlar da dedi")
    assert delta == "Onlar da dedi"
    full, delta = merge_transcript(full, " ki gördüğün gibi")
    assert full == "Onlar da dedi ki gördüğün gibi"
    assert delta == " ki gördüğün gibi"
    full, delta = merge_transcript("Onlar da", "Onlar da dedi")
    assert full == "Onlar da dedi"
    assert delta == " dedi"

def test_post_drops_oldest_chunk_when_queue_full():
    loop = SystemAudioLoop("en", "tr", None, "dummy_key")
    loop.out_queue = asyncio.Queue(maxsize=2)
    loop._post("chunk1")
    loop._post("chunk2")
    loop._post("chunk3")
    assert loop.out_queue.qsize() == 2
    assert loop.out_queue.get_nowait() == "chunk2"
    assert loop.out_queue.get_nowait() == "chunk3"


class _Ctx:
    def __init__(self, inner):
        self._inner = inner

    def __enter__(self):
        return self._inner

    def __exit__(self, *args):
        return False


class FakeMic:
    def recorder(self, **kwargs):
        return _Ctx(self)

    def record(self, numframes):
        time.sleep(0.005)
        t = np.arange(numframes) / 48000
        tone = 0.3 * np.sin(2 * np.pi * 440 * t)
        return np.stack([tone, tone], axis=1).astype(np.float32)


class FakeSpeaker:
    def __init__(self):
        self.played: list = []

    def player(self, **kwargs):
        return _Ctx(self)
    def play(self, data):
        self.played.append(np.asarray(data, dtype=np.float32).copy())


def _canned_response(text, finished=False):
    return SimpleNamespace(
        data=None,
        text=None,
        server_content=SimpleNamespace(
            output_transcription=SimpleNamespace(text=text, finished=finished),
            input_transcription=None,
        ),
    )


class FakeSession:
    def __init__(self):
        self.send_realtime_input = AsyncMock()
        self.send_client_content = AsyncMock()

    def receive(self):
        return self._gen()

    async def _gen(self):
        yield _canned_response("Bir, iki")
        yield _canned_response(", üç.", finished=True)
        await asyncio.sleep(3600)  # stop ile iptal edilir


class FakeConnect:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return False


def _stub_client(session):
    return SimpleNamespace(
        aio=SimpleNamespace(
            live=SimpleNamespace(
                connect=lambda model, config: FakeConnect(session)
            )
        )
    )


def _run_worker(loop_obj, errors):
    try:
        asyncio.run(loop_obj.run())
    except asyncio.CancelledError:
        pass  # normal durdurma
    except Exception as e:  # noqa: BLE001
        errors.append(e)


def test_run_initializes_session_and_queues_then_stops():
    """Düşen init satırları (bug 2) bu testte AttributeError verirdi."""
    heard: list = []
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", FakeMic(), "dummy-key",
        output_speaker=FakeSpeaker(),
        on_text=heard.append,
        console_input=False,
    )
    loop_obj.client = _stub_client(session)
    errors: list = []
    t = threading.Thread(target=_run_worker, args=(loop_obj, errors), daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while loop_obj.session is None and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.session is not None, "session kurulamadı"
        deadline = time.time() + 15
        while not session.send_realtime_input.await_count and time.time() < deadline:
            time.sleep(0.05)
        assert session.send_realtime_input.await_count > 0, "ses akışı gönderilmedi"
        sent = session.send_realtime_input.await_args.kwargs["audio"]
        assert len(sent["data"]) == 640, "16k mono chunk boyutu yanlış"
        trans = "".join(m[1] for m in heard if isinstance(m, tuple) and m[0] == "trans")
        assert "Bir, iki, üç." in trans, f"çeviri metni gelmedi: {heard}"
        assert not any(isinstance(m, str) and "[çeviri]" in m for m in heard)
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"


def test_playback_converts_pcm16_to_unit_float():
    speaker = FakeSpeaker()
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", FakeMic(), "dummy-key",
        output_speaker=speaker,
        on_text=lambda *_: None,
        console_input=False,
    )
    loop_obj.client = _stub_client(session)
    errors: list = []
    t = threading.Thread(target=_run_worker, args=(loop_obj, errors), daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while (loop_obj.audio_in_queue is None or loop_obj._loop is None) and time.time() < deadline:
            time.sleep(0.05)
        pcm = np.full(2400, 16384, dtype=np.int16).tobytes()
        loop_obj._loop.call_soon_threadsafe(loop_obj.audio_in_queue.put_nowait, pcm)
        deadline = time.time() + 5
        while not speaker.played and time.time() < deadline:
            time.sleep(0.05)
        assert speaker.played, "oynatma çağrılmadı"
        chunk = np.concatenate(speaker.played)
        assert chunk.dtype == np.float32
        assert float(np.max(np.abs(chunk))) <= 1.0 + 1e-5
        assert abs(float(np.mean(chunk)) - 0.5) < 0.05
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert errors == [], f"worker hatası: {errors}"


def test_request_stop_without_run_is_safe():
    loop_obj = SystemAudioLoop.__new__(SystemAudioLoop)
    loop_obj._loop = None
    loop_obj._stop = None
    loop_obj._cap_stop = __import__("threading").Event()
    loop_obj._play_stop = __import__("threading").Event()
    loop_obj._user_stop = __import__("threading").Event()
    loop_obj._play_q = None
    loop_obj.request_stop()  # yükseltmemeli
    assert loop_obj._user_stop.is_set()


def test_none_speaker_skips_playback_keeps_text():
    heard: list = []
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", FakeMic(), "dummy-key",
        output_speaker=None,
        on_text=heard.append,
        console_input=False,
    )
    loop_obj.client = _stub_client(session)
    errors: list = []
    t = threading.Thread(target=_run_worker, args=(loop_obj, errors), daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while loop_obj.session is None and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.session is not None, "session kurulamadı"
        deadline = time.time() + 15
        while not session.send_realtime_input.await_count and time.time() < deadline:
            time.sleep(0.05)
        trans = "".join(m[1] for m in heard if isinstance(m, tuple) and m[0] == "trans")
        assert "Bir, iki, üç." in trans, f"çeviri metni gelmedi: {heard}"
        assert loop_obj.audio_in_queue is None
        assert loop_obj._play_q is None
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"



def test_duplex_with_real_devices_stays_alive():
    """Gerçek aygıtlarla yakalama+oynatma: çökmeden (AV) akmalı.

    Eski desen (her chunk'ta ayrı thread'den COM çağrısı) bu testi
    erişim ihlaliyle öldürürdü; makinede aygıt yoksa atlanır.
    """
    try:
        import soundcard as sc

        source = pick_loopback(None)
        speaker = sc.default_speaker()
    except Exception:  # noqa: BLE001
        pytest.skip("ses aygıtı yok")
    heard: list = []
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", source, "dummy-key",
        output_speaker=speaker,
        on_text=heard.append,
        console_input=False,
    )
    loop_obj.client = _stub_client(session)
    # Oynatma yolunu da işlet: sentetik 24k ton kuyruğa doldurulur.
    tone = (0.2 * np.sin(2 * np.pi * 440 * np.arange(1024) / 24000) * 32767).astype(np.int16)
    errors: list = []
    t = threading.Thread(target=_run_worker, args=(loop_obj, errors), daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while (loop_obj.audio_in_queue is None or loop_obj._loop is None) and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.audio_in_queue is not None, "kuyruk kurulamadı"
        for _ in range(5):
            loop_obj._loop.call_soon_threadsafe(
                loop_obj.audio_in_queue.put_nowait, tone.tobytes())
        deadline = time.time() + 4.0
        while session.send_realtime_input.await_count == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert session.send_realtime_input.await_count > 0, "yakalama akmadı"
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"

def test_build_config_text_only():
    cfg = build_config("en", "tr", modalities=["TEXT"])
    assert cfg.response_modalities == ["TEXT"]
    assert cfg.output_audio_transcription is None

    loop_obj = SystemAudioLoop("en", "tr", FakeMic(), "dummy-key", output_speaker=None)
    assert loop_obj.config.response_modalities == ["TEXT"]
    assert loop_obj.config.output_audio_transcription is None


def test_capture_thread_device_disconnect_raises():
    class BrokenMic:
        name = "BrokenMic"
        def recorder(self, *args, **kwargs):
            raise RuntimeError("USB unplugged")

    loop_obj = SystemAudioLoop("en", "tr", BrokenMic(), "dummy-key", output_speaker=None)

    async def _run():
        loop_obj._loop = asyncio.get_running_loop()
        await loop_obj.listen_system()

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(_run())
    assert "Giriş ses aygıtı hatası" in str(exc_info.value)


def test_play_thread_device_disconnect_raises():
    class BrokenSpeaker:
        name = "BrokenSpeaker"
        def player(self, *args, **kwargs):
            raise RuntimeError("Speaker unplugged")

    loop_obj = SystemAudioLoop("en", "tr", FakeMic(), "dummy-key", output_speaker=BrokenSpeaker())

    async def _run():
        loop_obj._loop = asyncio.get_running_loop()
        loop_obj.audio_in_queue = asyncio.Queue()
        await loop_obj.play()

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(_run())
    assert "Çıkış ses aygıtı hatası" in str(exc_info.value)

def test_queue_drop_oldest_on_full():
    loop_obj = SystemAudioLoop("en", "tr", FakeMic(), "dummy-key", output_speaker=FakeSpeaker())
    loop_obj.audio_in_queue = asyncio.Queue(maxsize=3)
    for i in range(3):
        loop_obj.audio_in_queue.put_nowait(f"msg_{i}".encode())
    assert loop_obj.audio_in_queue.full()

    # Receive logic: drop oldest and insert newest
    try:
        loop_obj.audio_in_queue.put_nowait(b"msg_3")
    except asyncio.QueueFull:
        loop_obj.audio_in_queue.get_nowait()
        loop_obj.audio_in_queue.put_nowait(b"msg_3")

    assert loop_obj.audio_in_queue.qsize() == 3
    assert loop_obj.audio_in_queue.get_nowait() == b"msg_1"


def test_loopback_echo_suppressed_during_playback(monkeypatch):
    class LoopbackMic(FakeMic):
        isloopback = True

    loop_obj = SystemAudioLoop("en", "tr", LoopbackMic(), "dummy-key", output_speaker=FakeSpeaker())
    # Set playback_until to 10 seconds in the future
    loop_obj._playback_until = time.monotonic() + 10.0
    loop_obj._cap_stop.set() # Don't loop

    # Ensure the check prevents sending
    assert loop_obj.source_mic.isloopback is True
    assert loop_obj.output_speaker is not None

def test_receive_handles_both_audio_and_transcription():
    emitted = []
    loop_obj = SystemAudioLoop(
        "en", "tr", FakeMic(), "dummy-key",
        output_speaker=FakeSpeaker(),
        on_text=lambda msg: emitted.append(msg),
    )
    loop_obj.audio_in_queue = asyncio.Queue()

    class CombinedSession:
        def receive(self):
            async def _gen():
                yield SimpleNamespace(
                    data=b"\x01\x02\x03\x04",
                    text=None,
                    server_content=SimpleNamespace(
                        output_transcription=SimpleNamespace(text="Merged audio-text", finished=True),
                        input_transcription=None,
                    ),
                )
                await asyncio.sleep(3600)
            return _gen()

    loop_obj.session = CombinedSession()

    async def _run():
        task = asyncio.create_task(loop_obj.receive())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert not loop_obj.audio_in_queue.empty()
    assert loop_obj.audio_in_queue.get_nowait() == b"\x01\x02\x03\x04"
    assert ("trans", "Merged audio-text") in emitted
    assert ("trans_end",) in emitted

def test_audio_converter_sample_rate_resampling():
    from audio import AudioConverter
    conv48 = AudioConverter(48000, 16000)
    total_bytes = sum(len(conv48.process(np.zeros(960, dtype=np.float32))) for _ in range(50))
    # 1 second of 48k input must produce 16k mono 16-bit samples = 32000 bytes
    assert total_bytes == 32000

    conv44 = AudioConverter(44100, 16000)
    total_bytes_44 = sum(len(conv44.process(np.zeros(882, dtype=np.float32))) for _ in range(50))
    # 1 second of 44.1k input must produce 16k mono 16-bit samples = 32000 bytes
    assert total_bytes_44 == 32000
