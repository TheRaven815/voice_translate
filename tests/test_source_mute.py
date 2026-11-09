"""Dublaj kararı: kaynak sesi yalnız çeviri duyulurken ve geri alınabilir şekilde susar."""

import queue
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import source_mute
from applications import process_tree_pids
from loop import SystemAudioLoop
from source_mute import (
    DUB_BACKGROUND, SESSION_MUTE_FLOOR, DubPlan, MuteHold, SourceDub, WindowsRenderMute,
    bed_target, plan_dub, same_render_endpoint, source_capture_gain,
)


def _loopback(name, ident):
    return SimpleNamespace(name=name, id=ident, isloopback=True, is_application=False)


def _speaker(name, ident):
    return SimpleNamespace(name=name, id=ident)


def _app(pid=42):
    return SimpleNamespace(name="browser.exe", id=f"application:{pid}", pid=pid, is_application=True, isloopback=False)


def _mic():
    return SimpleNamespace(name="Mikrofon", id="mic", isloopback=False, is_application=False)


def test_process_tree_includes_descendants_only():
    parents = {1: 0, 2: 1, 3: 2, 4: 1, 9: 8}
    assert process_tree_pids(1, parents) == frozenset({1, 2, 3, 4})


def test_plan_is_idle_without_output_or_opt_in():
    source = _loopback("Hoparlör", "spk")
    output = _speaker("Kulaklık", "hp")
    assert plan_dub(source, output, enabled=False, own_pid=7, exclude_supported=True).action == "idle"
    assert plan_dub(source, None, enabled=True, own_pid=7, exclude_supported=True).action == "idle"


def test_plan_mutes_only_the_selected_application():
    plan = plan_dub(_app(42), _speaker("Hoparlör", "spk"), enabled=True, own_pid=7, exclude_supported=True)
    assert plan == DubPlan("mute_process", root_pid=42)


def test_bed_target_scales_the_current_level_instead_of_capping_it():
    """Mutlak 1/6 tavan, hoparlör zaten kısıkken açık ile kapalıyı aynı bırakırdı."""
    assert bed_target(1.0, DUB_BACKGROUND) == pytest.approx(DUB_BACKGROUND)
    assert bed_target(0.12, DUB_BACKGROUND) == pytest.approx(0.12 * DUB_BACKGROUND)
    assert bed_target(0.12, DUB_BACKGROUND) < 0.12
    assert bed_target(0.4, 0.0) == 0.0
    assert bed_target(0.4, 1.0) == pytest.approx(0.4)
    assert bed_target(0.4, 1.4) == pytest.approx(0.4)
    assert bed_target(-1.0, 0.5) == 0.0


def test_session_attenuation_is_compensated_in_capture():
    """Oturum sesi yakalamadan önce uygulanır; kısma yakalamada geri açılmalı."""
    assert source_capture_gain(DubPlan("idle")) == 1.0
    assert source_capture_gain(DubPlan("mute_endpoint", endpoint_id="spk")) == 1.0
    assert source_capture_gain(DubPlan("mute_process")) == 1.0
    assert source_capture_gain(DubPlan("mute_process", root_pid=42)) == pytest.approx(
        1.0 / SESSION_MUTE_FLOOR
    )
    assert source_capture_gain(DubPlan("mute_other_sessions", root_pid=7, gain=0.0)) == pytest.approx(
        1.0 / SESSION_MUTE_FLOOR
    )
    assert source_capture_gain(DubPlan("mute_process", root_pid=42, gain=0.25)) == pytest.approx(4.0)


def test_session_mute_keeps_a_capture_floor_but_endpoint_still_mutes(monkeypatch):
    """Sıfır ses yerine taban bırak; uç noktası susturması ise gerçek mute kalsın."""
    state = {"muted": False, "volume": 0.8}

    monkeypatch.setattr(source_mute, "_get_mute", lambda _volume, _index: state["muted"])
    monkeypatch.setattr(source_mute, "_set_mute", lambda _volume, _index, value: state.update(muted=value))
    monkeypatch.setattr(source_mute, "_get_scalar", lambda _volume, _index: state["volume"])
    monkeypatch.setattr(source_mute, "_set_scalar", lambda _volume, _index, value: state.update(volume=value))

    source_mute._shape_level(object(), "session", source_mute.PriorLevel(False, 0.8), None)
    assert state == {"muted": False, "volume": pytest.approx(SESSION_MUTE_FLOOR)}

    source_mute._shape_level(object(), "session", source_mute.PriorLevel(False, 0.8), 0.0)
    assert state["muted"] is False
    assert state["volume"] == pytest.approx(SESSION_MUTE_FLOOR)

    source_mute._shape_level(object(), "endpoint", source_mute.PriorLevel(False, 0.8), None)
    assert state["muted"] is True


def test_plan_can_leave_the_original_as_a_quiet_bed():
    plan = plan_dub(
        _app(42), _speaker("Hoparlör", "spk"),
        enabled=True, own_pid=7, exclude_supported=True, gain=DUB_BACKGROUND,
    )
    assert plan.action == "mute_process"
    assert plan.gain == DUB_BACKGROUND
    same = plan_dub(
        _loopback("Hoparlör", "spk"), _speaker("Hoparlör", "spk"),
        enabled=True, own_pid=7, exclude_supported=True, gain=1.4,
    )
    assert same.action == "mute_other_sessions"
    assert same.gain == 1.0


def test_plan_mutes_source_speaker_when_translation_goes_elsewhere():
    plan = plan_dub(
        _loopback("Hoparlör", "spk"), _speaker("Kulaklık", "hp"),
        enabled=True, own_pid=7, exclude_supported=True,
    )
    assert plan == DubPlan("mute_endpoint", endpoint_id="spk")


def test_plan_mutes_other_apps_when_translation_uses_the_same_speaker():
    plan = plan_dub(
        _loopback("Hoparlör", "spk"), _speaker("Hoparlör", "spk"),
        enabled=True, own_pid=7, exclude_supported=True,
    )
    assert plan.action == "mute_other_sessions"
    assert plan.root_pid == 7
    assert same_render_endpoint(_loopback("Hoparlör", "spk"), _speaker("Hoparlör", "SPK"))


def test_plan_does_not_silence_same_speaker_when_exclude_capture_is_unavailable():
    plan = plan_dub(
        _loopback("Hoparlör", "spk"), _speaker("Hoparlör", "spk"),
        enabled=True, own_pid=7, exclude_supported=False,
    )
    assert plan.action == "idle"
    assert plan.note == "same_speakers"


def test_plan_leaves_a_microphone_alone():
    plan = plan_dub(_mic(), _speaker("Hoparlör", "spk"), enabled=True, own_pid=7, exclude_supported=True)
    assert plan.action == "idle"
    assert plan.note == "microphone"


class _Backend:
    def __init__(self):
        self.applied = []
        self.refreshed = 0
        self.restored = []

    def apply(self, plan):
        self.applied.append(plan.action)
        self.hold = MuteHold(plan)
        return self.hold

    def refresh(self, hold):
        self.refreshed += 1
        self.last_gain = hold.plan.gain

    def restore(self, hold):
        self.restored.append(None if hold is None else hold.plan.action)


def test_gain_change_updates_the_hold_without_restoring_full_volume():
    backend = _Backend()
    dub = SourceDub(backend, own_pid=7, tree=lambda pid: frozenset({pid}), exclude_supported=lambda: True)
    try:
        quiet = dub.preview(_app(), _speaker("Hoparlör", "spk"), enabled=True, gain=0.2)
        dub.engage(quiet)
        louder = DubPlan(quiet.action, root_pid=quiet.root_pid, endpoint_id=quiet.endpoint_id, gain=0.55)
        dub.engage(louder)
        assert backend.applied == ["mute_process"]
        assert backend.restored == []
        assert backend.last_gain == pytest.approx(0.55)
        assert backend.hold.plan.gain == pytest.approx(0.55)
    finally:
        dub.release()


def test_source_dub_restores_exactly_what_it_muted_and_refreshes_while_held():
    backend = _Backend()
    dub = SourceDub(backend, own_pid=7, tree=lambda pid: frozenset({pid}), exclude_supported=lambda: True)
    try:
        plan = dub.preview(_app(), _speaker("Hoparlör", "spk"), enabled=True)
        dub.engage(plan)
        dub.engage(plan)
        assert backend.applied == ["mute_process"]
        assert backend.refreshed == 1
        off = dub.preview(_app(), None, enabled=True)
        dub.engage(off)
        assert backend.restored == ["mute_process"]
        dub.release()
        assert backend.restored == ["mute_process"]
    finally:
        dub.release()


def test_same_speaker_dub_captures_other_processes_not_the_device_mix(monkeypatch):
    used = []

    class _Recorder:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def record(self, numframes):
            loop_obj._cap_stop.set()
            return np.zeros((numframes, 2), dtype=np.float32)

    def exclude_self_recorder(**kwargs):
        used.append(("exclude", kwargs["channels"]))
        return _Recorder()

    def device_recorder(**kwargs):
        used.append(("device", kwargs["channels"]))
        return _Recorder()

    monkeypatch.setattr("process_audio.exclude_self_recorder", exclude_self_recorder)
    mic = SimpleNamespace(
        name="Hoparlör", id="spk", isloopback=True, channels=2, recorder=device_recorder,
    )
    speaker = SimpleNamespace(name="Hoparlör", id="spk")
    loop_obj = SystemAudioLoop(
        "en", "tr", mic, "key", output_speaker=speaker, console_input=False,
    )
    loop_obj.out_queue = queue.Queue()
    loop_obj.set_dub_exclude(True)
    loop_obj._capture_inner()
    loop_obj._cap_stop.clear()
    loop_obj.set_dub_exclude(False)
    loop_obj._capture_inner()
    assert used == [("exclude", 2), ("device", 2)]


@pytest.mark.device
@pytest.mark.skipif(sys.platform != "win32", reason="WASAPI")
def test_windows_endpoint_mute_restores_the_previous_bit():
    """Gerçek hoparlörün mute/ducking bitini geri yükler. Aygıtsız CI'da 0x80070490 olur."""
    import soundcard as sc

    try:
        speaker = sc.default_speaker()
    except Exception:  # noqa: BLE001 — barındırılan Windows'ta varsayılan uç yok
        pytest.skip("ses aygıtı yok")
    if speaker is None:
        pytest.skip("ses aygıtı yok")
    control = WindowsRenderMute(tree=lambda pid: frozenset({pid}))
    endpoint = str(speaker.id)
    before = control.endpoint_level(endpoint)
    assert 0.0 <= before.volume <= 1.0
    pids = control.session_pids()
    assert all(isinstance(pid, int) and pid >= 0 for pid in pids)
    assert control.first_session_muted() in (True, False, None)
    hold = None
    try:
        hold = control.apply(DubPlan("mute_endpoint", endpoint_id=endpoint))
        assert control.endpoint_muted(endpoint) is True
    finally:
        control.restore(hold)
    restored = control.endpoint_level(endpoint)
    assert restored.muted is before.muted
    assert abs(restored.volume - before.volume) < 0.05
    try:
        hold = control.apply(DubPlan("mute_endpoint", endpoint_id=endpoint, gain=DUB_BACKGROUND))
        ducked = control.endpoint_level(endpoint)
        assert ducked.muted is False
        assert abs(ducked.volume - bed_target(before.volume, DUB_BACKGROUND)) < 0.05
    finally:
        control.restore(hold)
    restored = control.endpoint_level(endpoint)
    assert restored.muted is before.muted
    assert abs(restored.volume - before.volume) < 0.05
