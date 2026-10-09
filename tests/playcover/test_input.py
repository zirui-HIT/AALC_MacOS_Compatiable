import threading
from dataclasses import replace

import pytest

from module.backends.base import BackendCancelled
from module.backends.playcover.geometry import Geometry
from module.backends.playcover.input import GestureTiming, PlayCoverInput


class TouchRecorder:
    connected = True

    def __init__(self):
        self.events = []
        self.on_touch = None

    def touch(self, phase, x, y, contact=0):
        self.events.append((phase, x, y, contact))
        if self.on_touch:
            self.on_touch(phase)


def make_input():
    recorder = TouchRecorder()
    geometry = Geometry((1920, 1080), (3840, 2160), (0, 0, 1920, 1080))
    cancel = threading.Event()
    timing = GestureTiming(click_hold=0, drag_hold=0, repeat_interval=0)
    return PlayCoverInput(recorder, lambda: geometry, cancel, timing), recorder


def test_click_repeats_complete_touch_sequences():
    handler, recorder = make_input()
    assert handler.mouse_click(960, 540, times=3)
    assert recorder.events == [(phase, 1920, 1080, 0) for phase in [0, 3, 0, 3, 0, 3]]
    assert not handler.active_contacts


def test_linked_path_has_one_down_and_one_up_and_fixed_geometry():
    handler, recorder = make_input()
    snapshot = replace(handler._current_geometry(), touch_size=(1920, 1080))
    with handler.geometry_context(snapshot):
        handler.mouse_drag_link([(10, 10), (20, 20), (30, 30)], drag_time=0)
    assert [event[0] for event in recorder.events] == [0, 1, 1, 3]
    assert recorder.events[-1] == (3, 30, 30, 0)


def test_cancel_mid_drag_releases_contact():
    handler, recorder = make_input()
    recorder.on_touch = lambda phase: handler.cancel.set() if phase == 1 else None
    with pytest.raises(BackendCancelled):
        handler.mouse_drag(10, 10, dx=100, drag_time=0.2)
    assert [event[0] for event in recorder.events] == [0, 1, 3]
    assert not handler.active_contacts


def test_paused_gesture_waits_until_resume_and_records_restore_time():
    handler, recorder = make_input()
    handler.is_pause = True
    thread = threading.Thread(target=handler.mouse_click, args=(10, 10))
    thread.start()
    assert not recorder.events
    handler.is_pause = False
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert handler.restore_time is not None
    assert [event[0] for event in recorder.events] == [0, 3]


def test_scroll_has_no_long_endpoint_hold():
    handler, recorder = make_input()
    handler.mouse_swipe_for_team_scroll(100, 500, dy=-100, duration=0)
    assert [event[0] for event in recorder.events] == [0, 1, 1, 3]
    assert recorder.events[-1][1:3] == (200, 800)


def test_pause_during_gesture_takes_effect_after_release():
    handler, recorder = make_input()
    recorder.on_touch = lambda phase: setattr(handler, "is_pause", True) if phase == 1 else None
    handler.mouse_drag(10, 10, dx=10, drag_time=0)
    assert recorder.events[-1][0] == 3


def test_unsupported_inputs_fail_explicitly():
    handler, _ = make_input()
    for action in (lambda: handler.key_press("enter"), lambda: handler.input_text("abc"), handler.mouse_scroll):
        with pytest.raises(NotImplementedError):
            action()


def test_blank_click_uses_original_empty_corner_and_maps_explicit_positions():
    handler, recorder = make_input()
    handler.mouse_click_blank()
    handler.mouse_click_blank(coordinate=(10, 20))
    assert recorder.events == [(0, 2, 2, 0), (3, 2, 2, 0), (0, 20, 40, 0), (3, 20, 40, 0)]


def test_pinch_uses_two_stable_contacts_and_releases_both():
    handler, recorder = make_input()
    handler.pinch((960, 540), 400, 200, duration=0)
    assert recorder.events == [(0, 1520, 1080, 0), (0, 2320, 1080, 1),
                               (1, 1720, 1080, 0), (1, 2120, 1080, 1),
                               (3, 1720, 1080, 0), (3, 2120, 1080, 1)]
    assert not handler.active_contacts


def test_cancelled_pinch_releases_both_contacts():
    handler, recorder = make_input()
    recorder.on_touch = lambda phase: handler.cancel.set() if phase == 1 else None
    with pytest.raises(BackendCancelled):
        handler.pinch((960, 540), 400, 200, duration=0.2)
    assert {(e[0], e[3]) for e in recorder.events[-2:]} == {(3, 0), (3, 1)}
    assert not handler.active_contacts


def test_link_holds_both_gears_before_moving_and_releasing(monkeypatch):
    handler, recorder = make_input()
    handler.timing = GestureTiming(drag_hold=0.1)
    held = []
    monkeypatch.setattr(handler, "_wait", lambda seconds: held.append((seconds, recorder.events[-1])))
    handler.mouse_drag_link([(100, 800), (700, 850), (1250, 840)], drag_time=0.1)
    assert held[0] == (0.1, (0, 200, 1600, 0))
    assert held[-1] == (0.1, (1, 2500, 1680, 0))
    assert recorder.events[-1] == (3, 2500, 1680, 0)
    assert [event[0] for event in recorder.events].count(0) == 1
    assert [event[0] for event in recorder.events].count(3) == 1


@pytest.mark.parametrize("height", [720, 1080, 1440])
def test_pack_pull_crosses_card_bottom_and_scales_with_logical_height(height, monkeypatch):
    from unittest.mock import Mock

    handler, _ = make_input()
    geometry = replace(handler._current_geometry(), logical_size=(height * 16 // 9, height))
    drag = Mock()
    monkeypatch.setattr(handler, "mouse_drag", drag)
    with handler.geometry_context(geometry):
        handler.mouse_drag_down(100, 339 * height / 1080)
    assert drag.call_args.kwargs["drag_time"] == 0.4
    assert drag.call_args.kwargs["dy"] == pytest.approx(660 * height / 1080)
    assert drag.call_args.args[1] + drag.call_args.kwargs["dy"] > 900 * height / 1080
