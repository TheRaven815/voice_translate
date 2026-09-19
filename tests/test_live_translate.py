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
        self.stop_event = asyncio.Event()

    def receive(self):
        return self._gen()
    async def _gen(self):
        yield _canned_response("Bir, iki")
        yield _canned_response(", üç.", finished=True)
        await asyncio.Event().wait()

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


@pytest.mark.parametrize("console_input", [False, True])
@pytest.mark.parametrize("stop_at", ["before_run", "connecting", "connected"])
def test_stop_prevents_audio_start_during_connection(monkeypatch, stop_at, console_input):
    async def scenario():
        entered = asyncio.Event()
        released = asyncio.Event()
        closed = asyncio.Event()
        events = []
        session = FakeSession()

        class DelayedConnect(FakeConnect):
            async def __aenter__(self):
                entered.set()
                try:
                    if stop_at == "connected":
                        # Stop arrives from the GUI as connection entry completes.
                        await asyncio.to_thread(loop_obj.request_stop)
                    else:
                        await released.wait()
                    return self._session
                except asyncio.CancelledError:
                    closed.set()
                    raise

            async def __aexit__(self, *args):
                closed.set()
                return False

        client = _stub_client(session)
        client.aio.live.connect = lambda **kwargs: DelayedConnect(session)
        monkeypatch.setattr("loop.genai.Client", lambda **kwargs: client)
        loop_obj = SystemAudioLoop(
            "en", "tr", FakeMic(), "dummy-key",
            output_speaker=FakeSpeaker(), on_text=events.append,
            console_input=console_input,
        )
        started = []

        async def audio_started():
            started.append(True)

        monkeypatch.setattr(loop_obj, "listen_system", audio_started)
        monkeypatch.setattr(loop_obj, "play", audio_started)
        if stop_at == "before_run":
            loop_obj.request_stop()
        worker = asyncio.create_task(loop_obj.run())
        try:
            if stop_at != "before_run":
                await asyncio.wait_for(entered.wait(), timeout=2)
            if stop_at == "connecting":
                await asyncio.to_thread(loop_obj.request_stop)
            # wait() does not cancel the worker on timeout: stop must finish it.
            done, _ = await asyncio.wait({worker}, timeout=2)
            assert worker in done, "Durdur, bekleyen bağlantıyı iptal etmedi"
            with pytest.raises(asyncio.CancelledError):
                await worker
            assert not started, "Durdur sonrasında ses aygıtları başlatıldı"
            session.send_realtime_input.assert_not_awaited()
            assert not events, "Durdur sonrasında oturum çıktısı üretildi"
            if stop_at == "before_run":
                assert not entered.is_set(), "Durdurulmuş oturum bağlantı açtı"
            else:
                assert closed.is_set(), "Bekleyen bağlantı temizlenmedi"
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(scenario())


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



@pytest.mark.device
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
    # Live Translation yalnız AUDIO yanıtını destekler; hoparlör yoksa ses yerelde atılır.
    loop_obj = SystemAudioLoop("en", "tr", FakeMic(), "dummy-key", output_speaker=None)
    assert loop_obj.config.response_modalities == ["AUDIO"]
    assert loop_obj.config.output_audio_transcription is not None


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

def test_queue_drop_oldest_on_full_via_receive():
    """G03: receive() metodunun tam dolu audio_in_queue üzerinde en eskiyi atıp yeniyi eklemesini doğrula."""
    loop_obj = SystemAudioLoop("en", "tr", FakeMic(), "dummy-key", output_speaker=FakeSpeaker())
    loop_obj.audio_in_queue = asyncio.Queue(maxsize=2)
    # 2 eleman doldur
    loop_obj.audio_in_queue.put_nowait(b"oldest")
    loop_obj.audio_in_queue.put_nowait(b"middle")
    assert loop_obj.audio_in_queue.full()

    class StreamSession:
        def receive(self):
            async def _gen():
                # receive() bu veriyi alıp audio_in_queue'ya koyacak; dolu olduğu için 'oldest' atılmalı
                yield SimpleNamespace(data=b"newest", text=None, server_content=None)
                await asyncio.sleep(3600)
            return _gen()

    loop_obj.session = StreamSession()

    async def _run():
        task = asyncio.create_task(loop_obj.receive())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert loop_obj.audio_in_queue.qsize() == 2
    assert loop_obj.audio_in_queue.get_nowait() == b"middle"
    assert loop_obj.audio_in_queue.get_nowait() == b"newest"


def test_g06_bounded_byte_queue_caps_latency():
    """G06: BoundedByteQueue toplam byte bütçesini aşan eski ses paketlerini atarak gecikmeyi sınırlar."""
    from loop import BoundedByteQueue
    bq = BoundedByteQueue(max_bytes=100)
    # 40'ar byte'lık 4 parça (toplam 160 byte > 100)
    bq.put_nowait(b"A" * 40)
    bq.put_nowait(b"B" * 40)
    bq.put_nowait(b"C" * 40)
    bq.put_nowait(b"D" * 40)

    # En eski A ve B atılmış olmalı; C ve D (80 byte <= 100) kalmalı
    item1 = bq.get(timeout=0.1)
    assert item1 == b"C" * 40
    item2 = bq.get(timeout=0.1)
    assert item2 == b"D" * 40
    assert bq.curr_bytes == 0
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

def test_pause_resume_and_volume_controls():
    loop_obj = SystemAudioLoop("auto", "tr", "fake_mic", "test_key", volume=0.8, vad_threshold=0.01)
    assert not loop_obj.is_paused
    loop_obj.pause()
    assert loop_obj.is_paused
    loop_obj.resume()
    assert not loop_obj.is_paused

    loop_obj.set_volume(1.5)
    assert loop_obj.volume == 1.5
    loop_obj.set_volume(5.0)  # clamped to 2.0
    assert loop_obj.volume == 2.0
    loop_obj.set_muted(True)
    assert loop_obj.muted is True


def test_build_config_glossary_and_system_instruction():
    cfg = build_config(
        "en",
        "tr",
        system_instruction="Always translate in professional tone.",
    )
    assert cfg.system_instruction is not None
    assert "professional tone" in cfg.system_instruction.parts[0].text

    loop_obj = SystemAudioLoop(
        "en",
        "tr",
        "fake_mic",
        "test_key",
        glossary={"Kubernetes": "K8s", "Docker": "Konteyner"},
    )
    assert loop_obj.config.system_instruction is not None
    txt = loop_obj.config.system_instruction.parts[0].text
    assert "Kubernetes: K8s" in txt
    assert "Docker: Konteyner" in txt


def test_receive_latency_and_detected_language():
    emitted = []
    loop_obj = SystemAudioLoop("auto", "tr", "fake_mic", "test_key", on_text=emitted.append)
    loop_obj.audio_in_queue = asyncio.Queue()
    loop_obj._last_speech_time = time.monotonic() - 0.250  # 250 ms ago
    loop_obj._waiting_response = True

    class MockSession:
        def receive(self):
            async def _gen():
                yield SimpleNamespace(
                    data=b"\x00\x01",
                    text=None,
                    server_content=SimpleNamespace(
                        output_transcription=SimpleNamespace(text="Hello", finished=True),
                        input_transcription=SimpleNamespace(text="Bonjour", language_code="fr", finished=True),
                    ),
                )
                await asyncio.sleep(3600)
            return _gen()

    loop_obj.session = MockSession()

    async def _run():
        task = asyncio.create_task(loop_obj.receive())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert loop_obj.detected_src == "fr"
    assert ("detected_src", "fr") in emitted
    assert any(item[0] == "latency" and item[1] >= 200 for item in emitted if isinstance(item, tuple))

def test_capture_does_not_drop_when_output_speaker_is_different_device():
    """H05: Çıkış aygıtı farklı olduğunda loopback kaynak ses bastırılmamalı."""
    from loop import _is_same_endpoint

    class Device:
        def __init__(self, id, name, isloopback=False):
            self.id = id
            self.name = name
            self.isloopback = isloopback

    spk_a = Device(id="dev_A", name="Hoparlör A")
    spk_b = Device(id="dev_B", name="Kulaklık B")
    mic_a_loop = Device(id="dev_A", name="Hoparlör A", isloopback=True)
    mic_b_loop = Device(id="dev_B", name="Kulaklık B", isloopback=True)

    assert _is_same_endpoint(mic_a_loop, spk_a) is True
    assert _is_same_endpoint(mic_a_loop, spk_b) is False
    assert _is_same_endpoint(mic_b_loop, spk_b) is True
    assert _is_same_endpoint(mic_b_loop, spk_a) is False

    frames_recorded = []

    class MockRecorder:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def record(self, numframes):
            frames_recorded.append(True)
            return np.ones((numframes, 2), dtype=np.float32) * 0.1

    class TestMic:
        id = "dev_A"
        name = "Hoparlör A"
        isloopback = True
        channels = 2
        def recorder(self, **kwargs):
            return MockRecorder()

    posted = []
    loop_obj = SystemAudioLoop("en", "tr", TestMic(), "dummy-key", output_speaker=spk_b)
    loop_obj._post = lambda msg: posted.append(msg)
    loop_obj._playback_until = time.monotonic() + 10.0  # Aktif çalma var ama farklı cihaz

    import threading
    t = threading.Thread(target=loop_obj._capture_thread, daemon=True)
    t.start()
    time.sleep(0.05)
    loop_obj._cap_stop.set()
    t.join(timeout=1.0)

    assert len(frames_recorded) > 0
    assert len(posted) > 0

    # Aynı cihaz senaryosu: playback_until aktifken frame atılmalı (echo loop önleme)
    posted_same = []
    loop_obj_same = SystemAudioLoop("en", "tr", TestMic(), "dummy-key", output_speaker=spk_a)
    loop_obj_same._post = lambda msg: posted_same.append(msg)
    loop_obj_same._playback_until = time.monotonic() + 10.0

    t_same = threading.Thread(target=loop_obj_same._capture_thread, daemon=True)
    t_same.start()
    time.sleep(0.05)
    loop_obj_same._cap_stop.set()
    t_same.join(timeout=1.0)

    assert len(posted_same) == 0

def test_h13_audio_converter_anti_aliasing():
    """H13: 48 kHz -> 16 kHz dönüşümünde 8 kHz üstü frekanslar (örn 12 kHz) filtrelenmeli."""
    from audio import AudioConverter
    conv = AudioConverter(in_rate=48000, out_rate=16000)
    t = np.arange(48000) / 48000.0
    # 12 kHz sinyal
    sig_12k = (0.7 * np.sin(2 * np.pi * 12000.0 * t)).astype(np.float32)
    out_bytes = b""
    for chunk in np.array_split(sig_12k, 50):
        out_bytes += conv.process(chunk)
    out_samples = np.frombuffer(out_bytes, dtype=np.int16) / 32768.0
    # 12 kHz aliased genliği en az -30 dB (yaklaşık 0.02'den küçük) olmalı
    max_out = np.max(np.abs(out_samples[500:]))
    assert max_out < 0.02


def test_h14_play_thread_single_volume_scaling_and_mute_preroll():
    """H14: Ses kazancı bir kez uygulanmalı (çift ölçekleme olmamalı) ve mute preroll'u atlamamalı."""
    import queue
    played_blocks = []

    class RecordingPlayer:
        def __init__(self, **_kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def play(self, data):
            played_blocks.append(np.array(data, copy=True))

    class MockSpeaker:
        name = "MockSpeaker"
        def player(self, **kwargs):
            return RecordingPlayer(**kwargs)

    # 1. Volume 0.5 test
    loop_obj = SystemAudioLoop("en", "tr", None, "key", output_speaker=MockSpeaker())
    loop_obj.volume = 0.5
    loop_obj._play_q = queue.Queue()

    # 1 saniyelik 0.8 genlikli float ses verisi
    raw_float = np.full(4000, 0.8, dtype=np.float32)
    pcm_bytes = (raw_float * 32767.0).astype(np.int16).tobytes()
    loop_obj._play_q.put(pcm_bytes)
    loop_obj._play_q.put(None)  # durma sinyali

    loop_obj._play_thread()

    assert len(played_blocks) > 0
    concatenated = np.concatenate(played_blocks)
    # Kazanç bir kez uygulanmış olmalı: 0.8 * 0.5 = ~0.4 (0.25 gibi çift çarpılmış olmamalı)
    assert np.allclose(concatenated, 0.4, atol=0.02)

    # 2. Mute test (preroll tamponundayken bile mute sesi engellemeli)
    played_blocks.clear()
    loop_obj_muted = SystemAudioLoop("en", "tr", None, "key", output_speaker=MockSpeaker())
    loop_obj_muted.muted = True
    loop_obj_muted._play_q = queue.Queue()
    loop_obj_muted._play_q.put(pcm_bytes)
    loop_obj_muted._play_q.put(None)

    loop_obj_muted._play_thread()
    assert len(played_blocks) == 0

def test_r01_vad_hangover_silence_chunks_sent_before_dropping():
    """R01: Konuşma bittiğinde ilk sessizlik parçaları (hangover) hemen kesilmeden Gemini VAD'e gönderilmeli."""
    loop_obj = SystemAudioLoop("en", "tr", None, "key", output_speaker=None, vad_threshold=0.05)
    # vad_silence_chunks 1 olduğunda (yani 15'ten küçük) continue yapılmayıp post edilmeli
    loop_obj._vad_silence_chunks = 0
    rms = 0.01  # eşiğin altında sessizlik
    HANGOVER_CHUNKS = 15
    # 1. parça sessizlik: HANGOVER_CHUNKS dahilinde gönderilmeli
    loop_obj._vad_silence_chunks += 1
    should_skip = loop_obj._vad_silence_chunks > HANGOVER_CHUNKS and loop_obj._vad_silence_chunks % 75 != 0
    assert should_skip is False

    # 16. parça sessizlik: HANGOVER bitti, atılmalı
    loop_obj._vad_silence_chunks = 16
    should_skip = loop_obj._vad_silence_chunks > HANGOVER_CHUNKS and loop_obj._vad_silence_chunks % 75 != 0
    assert should_skip is True


def test_r02_merge_transcript_preserves_repeated_words():
    """R02: merge_transcript peş peşe gelen aynı kelimeleri (ha ha, no no) silmemeli."""
    # Tekrarlanan parçalar
    full, delta = merge_transcript("ha", "ha")
    assert full == "haha"
    assert delta == "ha"

    # Kümülatif büyüyen parça
    full, delta = merge_transcript("hello", "hello world")
    assert full == "hello world"
    assert delta == " world"

def test_r04_loop_close_and_finally_closes_client():
    """R04: loop_obj.close() metodu client kaynaklarını serbest bırakmalı."""
    from unittest.mock import MagicMock
    loop_obj = SystemAudioLoop("en", "tr", None, "key", output_speaker=None)
    mock_client = MagicMock()
    loop_obj.client = mock_client
    loop_obj.close()
    mock_client.close.assert_called_once()


class _NamedMic(FakeMic):
    def __init__(self, name):
        self.name = name
        self.isloopback = False
        self.channels = 2
        self.calls = 0

    def record(self, numframes):
        self.calls += 1
        return super().record(numframes)


def test_hotswap_input_keeps_session_alive():
    """Giriş hot-swap: çeviri oturumu ölmeden yeni cihaz devreye girer."""
    mic_a = _NamedMic("Mic A")
    mic_b = _NamedMic("Mic B")
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", mic_a, "dummy-key",
        output_speaker=FakeSpeaker(),
        on_text=lambda *_: None,
        console_input=False,
    )
    loop_obj.client = _stub_client(session)
    errors: list = []
    t = threading.Thread(target=_run_worker, args=(loop_obj, errors), daemon=True)
    t.start()
    try:
        deadline = time.time() + 15
        while session.send_realtime_input.await_count == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert session.send_realtime_input.await_count > 0
        assert loop_obj.swap_input(mic_b) is True
        deadline = time.time() + 5
        while loop_obj.source_mic is not mic_b and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.source_mic is mic_b
        assert loop_obj.swap_input(mic_b) is False  # aynı aygıt: no-op
        before = session.send_realtime_input.await_count
        time.sleep(0.4)
        assert session.send_realtime_input.await_count > before
        assert mic_b.calls > 0
        assert t.is_alive()
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"


def test_hotswap_output_to_none_and_back():
    """Çıkış hot-swap: hoparlör -> Hiçbiri -> hoparlör, oturum sağ kalır."""
    spk_a = FakeSpeaker()
    spk_b = FakeSpeaker()
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", FakeMic(), "dummy-key",
        output_speaker=spk_a,
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
        assert loop_obj.audio_in_queue is not None
        pcm = (np.full(2400, 16384, dtype=np.int16)).tobytes()
        loop_obj._loop.call_soon_threadsafe(loop_obj.audio_in_queue.put_nowait, pcm)
        deadline = time.time() + 5
        while not spk_a.played and time.time() < deadline:
            time.sleep(0.05)
        assert spk_a.played, "ilk hoparlör çalmadı"
        assert loop_obj.swap_output(None) is True
        deadline = time.time() + 5
        while loop_obj.output_speaker is not None and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.output_speaker is None
        time.sleep(0.3)
        assert t.is_alive(), "drain modunda oturum öldü"
        assert loop_obj.swap_output(spk_b) is True
        deadline = time.time() + 5
        while loop_obj.output_speaker is not spk_b and time.time() < deadline:
            time.sleep(0.05)
        assert loop_obj.output_speaker is spk_b
        loop_obj._loop.call_soon_threadsafe(loop_obj.audio_in_queue.put_nowait, pcm)
        deadline = time.time() + 5
        while not spk_b.played and time.time() < deadline:
            time.sleep(0.05)
        assert spk_b.played, "yeni hoparlör devreye girmedi"
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"


def test_vu_level_updates_during_echo_suppression():
    """Yankı bastırma gönderimi keser ama VU göstergesini dondurmaz."""
    frames_recorded = []

    class MockRecorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def record(self, numframes):
            frames_recorded.append(True)
            return np.ones((numframes, 2), dtype=np.float32) * 0.1

    class TestMic:
        id = "dev_A"
        name = "Hoparlör A"
        isloopback = True
        channels = 2

        def recorder(self, **kwargs):
            return MockRecorder()

    class Spk:
        id = "dev_A"
        name = "Hoparlör A"

    posted: list = []
    loop_obj = SystemAudioLoop("en", "tr", TestMic(), "dummy-key", output_speaker=Spk())
    loop_obj._post = lambda msg: posted.append(msg)
    loop_obj._playback_until = time.monotonic() + 10.0  # aktif çalma

    t = threading.Thread(target=loop_obj._capture_thread, daemon=True)
    t.start()
    time.sleep(0.15)
    loop_obj._cap_stop.set()
    t.join(timeout=2.0)

    assert len(frames_recorded) > 0
    assert posted == [], "yankı bastırma gönderimi kesmeli"
    assert loop_obj.last_level > 0.3, f"VU dondu: {loop_obj.last_level}"


class _FlakyRec:
    def __init__(self, mic):
        self._mic = mic

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def record(self, numframes):
        self._mic.calls += 1
        if self._mic.calls <= 2:
            raise RuntimeError("kısa kopma")
        time.sleep(0.005)
        t = np.arange(numframes) / 48000
        tone = 0.3 * np.sin(2 * np.pi * 440 * t)
        return np.stack([tone, tone], axis=1).astype(np.float32)


class _FlakyMic:
    name = "Flaky"
    isloopback = False
    channels = 2

    def __init__(self):
        self.calls = 0

    def recorder(self, **kwargs):
        return _FlakyRec(self)


def test_capture_recovers_after_transient_error():
    """Kısa giriş kopması oturumu öldürmez; akış kendiliğinden döner."""
    heard: list = []
    session = FakeSession()
    loop_obj = SystemAudioLoop(
        "en", "tr", _FlakyMic(), "dummy-key",
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
        while session.send_realtime_input.await_count == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert session.send_realtime_input.await_count > 0, "akış geri dönmedi"
        assert t.is_alive()
        assert any("yeniden deneniyor" in str(m) for m in heard), f"uyarı loglanmadı: {heard}"
    finally:
        loop_obj.request_stop()
        t.join(timeout=20)
    assert not t.is_alive(), "worker durmadı"
    assert errors == [], f"worker hatası: {errors}"


def test_capture_suppresses_discontinuity_warnings():
    """WASAPI kesinti uyarısı log'a taşmaz, sayaçta izlenir, akış sürer."""
    import warnings

    class WarnMic:
        name = "WarnMic"
        isloopback = False
        channels = 2

        def __init__(self):
            self.calls = 0

        def recorder(self, **kwargs):
            return WarnMic._Rec(self)

        class _Rec:
            def __init__(self, mic):
                self._mic = mic

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def record(self, numframes):
                self._mic.calls += 1
                warnings.warn("data discontinuity in recording", RuntimeWarning)
                time.sleep(0.005)
                t = np.arange(numframes) / 48000
                tone = 0.3 * np.sin(2 * np.pi * 440 * t)
                return np.stack([tone, tone], axis=1).astype(np.float32)

    posted: list = []
    emitted: list = []
    loop_obj = SystemAudioLoop(
        "en", "tr", WarnMic(), "dummy-key",
        output_speaker=FakeSpeaker(), on_text=emitted.append, console_input=False,
    )
    loop_obj._post = lambda msg: posted.append(msg)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # sızan uyarı burada patlardı
        t = threading.Thread(target=loop_obj._capture_thread, daemon=True)
        t.start()
        deadline = time.time() + 10
        while loop_obj._disc_count < 30 and time.time() < deadline:
            time.sleep(0.05)
        loop_obj._cap_stop.set()
        t.join(timeout=2.0)
    assert not t.is_alive()
    assert len(posted) > 0, "uyarı bastırma akışı kesmemeli"
    assert loop_obj._disc_count >= 30, f"kesinti sayılmadı: {loop_obj._disc_count}"
    notices = [m for m in emitted if "kesinti" in str(m)]
    assert len(notices) == 1, f"sürekli kesinti tek satırda kısılmalı: {notices}"


def test_unsupported_mic_fails_fast_with_guidance():
    """soundcard'ın açamadığı mikrofon sonsuz 'yeniden deneniyor' seline girmez.

    Gerçek raporda: `[Sistem] 24G4HA` -> `[Mikrofon]` swap'inden sonra
    `[uyarı] Giriş aygıtı sorunu (); ...` satırları art arda geldi; `str(e)`
    boş `AssertionError` idi (sürücü mix biçimi WAVE_FORMAT_EXTENSIBLE değil).
    Deterministik uyumsuzluk hızlı ve yol gösterici hataya dönüşmeli.
    """
    from loop import describe_audio_error

    class AssertMic:
        name = "Mikrofon (High Definition Audio Device)"
        isloopback = False
        channels = 2

        def recorder(self, **kwargs):
            raise AssertionError()

    emitted: list = []
    loop_obj = SystemAudioLoop(
        "en", "tr", AssertMic(), "dummy-key",
        output_speaker=FakeSpeaker(), on_text=emitted.append, console_input=False,
    )
    # Önce çalışan bir aygıt varmış gibi yap (hot-swap senaryosu: retry yolu).
    loop_obj._capture_opened_once = True
    errors: list = []
    t = threading.Thread(
        target=lambda: errors.append(_run_capture_expect_raise(loop_obj)),
        daemon=True,
    )
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "desteklenmeyen aygıt thread'i kilitledi"
    assert errors and isinstance(errors[0], RuntimeError), f"beklenen RuntimeError: {errors}"
    text = str(errors[0])
    assert "48000" in text, f"yol gösterici mesaj yok: {text}"
    assert "()" not in text, f"boş hata metni sızdı: {text}"

    # Yardımcı da boş AssertionError'i açıklasın.
    hint = describe_audio_error(AssertionError(), AssertMic())
    assert "Mikrofon" in hint and "48000" in hint, f"ipucu yetersiz: {hint}"


def _run_capture_expect_raise(loop_obj):
    try:
        loop_obj._capture_thread()
    except BaseException as e:  # noqa: BLE001 - test bilerek yakalar
        return e
    return None


def test_device_label_helpers():
    """devices: görünen ad eşleme ve kimlik karşılaştırma."""
    from types import SimpleNamespace

    from devices import (
        NONE_OUTPUT,
        device_key,
        display_input_label,
        find_input_by_label,
        find_output_by_label,
    )

    loop_dev = SimpleNamespace(id="1", name="Hoparlör X", isloopback=True)
    mic_dev = SimpleNamespace(id="2", name="Mikrofon Y", isloopback=False)
    assert display_input_label(loop_dev) == "[Sistem] Hoparlör X"
    assert display_input_label(mic_dev) == "[Mikrofon] Mikrofon Y"
    assert find_input_by_label([loop_dev, mic_dev], "[Sistem] Hoparlör X") is loop_dev
    assert find_input_by_label([loop_dev, mic_dev], "Mikrofon Y") is mic_dev
    assert find_output_by_label([loop_dev], NONE_OUTPUT) is None
    assert find_output_by_label([loop_dev], "Hoparlör X") is loop_dev
    assert find_output_by_label([loop_dev], "Yok") is None
    assert device_key(None) == (None, None, None)
    assert device_key(loop_dev) != device_key(mic_dev)
