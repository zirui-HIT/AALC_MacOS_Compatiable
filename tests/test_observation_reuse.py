"""Offline tests for bounded observation reuse; no real game/service is contacted."""
from contextlib import nullcontext
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from module.backends.base import BackendCancelled


@pytest.fixture
def observation(monkeypatch):
    from module.automation import auto
    from module.backends import factory
    from module.config import cfg

    module = import_module("module.automation.automation")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "screenshot_interval": 0.85,
    }))
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(module.time, "time", lambda: 100.0)
    session = Mock()
    session.cancel.wait.return_value = False
    session.transport.connected = True
    geometry = SimpleNamespace(version=1)
    session.geometry.return_value = geometry
    session.input.geometry_context.return_value = nullcontext()
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    image = Image.new("RGB", (16, 9), (255, 0, 0))
    frame = SimpleNamespace(image=image, geometry_version=1, geometry=geometry)
    for name, value in {
        "_business_frame": frame, "_latest_frame": frame, "_latest_screenshot": image,
        "_latest_screenshot_monotonic": 100.0, "last_screenshot_time": 99.0,
        "screenshot": image, "_ocr_image": None, "_ocr_regions": {},
    }.items():
        monkeypatch.setattr(auto, name, value)

    def capture(gray):
        auto._business_frame = frame
        return image.convert("L") if gray else image

    capture_mock = Mock(side_effect=capture)
    monkeypatch.setattr(auto, "_capture", capture_mock)
    return auto, session, capture_mock, module


def test_rgb_and_gray_observations_share_color_frame_without_capture_or_delay(observation):
    auto, session, capture, _ = observation
    assert auto.take_screenshot(max_age=0.85).getpixel((0, 0)) == 76
    rgb = auto.take_screenshot(gray=False, max_age=0.85)
    assert rgb.mode == "RGB" and rgb.getpixel((0, 0)) == (255, 0, 0)
    capture.assert_not_called()
    session.cancel.wait.assert_not_called()


def test_six_read_only_requests_acquire_one_frame_without_extending_its_lifetime(observation, monkeypatch):
    auto, _, capture, module = observation
    auto.take_screenshot()
    for gray in (True, True, True, True, False):
        auto.take_screenshot(gray=gray, max_age=0.85)
    capture.assert_called_once()
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.8)
    gray = auto.take_screenshot(max_age=0.85)
    assert auto.take_screenshot(max_age=0.85) is gray
    assert auto._latest_screenshot_monotonic == 100.0
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.9)
    auto.take_screenshot(max_age=0.85)
    assert capture.call_count == 2


@pytest.mark.parametrize("reason", ["default", "expired", "invalidated", "geometry", "disconnected"])
def test_fresh_capture_remains_required_after_invalidating_observation(observation, reason):
    auto, session, capture, _ = observation
    if reason == "expired":
        auto._latest_screenshot_monotonic = 99.0
    elif reason == "invalidated":
        auto.invalidate_screenshot_cache()
    elif reason == "geometry":
        session.geometry.return_value.version = 2
    elif reason == "disconnected":
        session.transport.connected = False
    auto.take_screenshot(max_age=0.0 if reason == "default" else 0.85)
    capture.assert_called_once_with(True)


def test_frame_reuse_never_exceeds_configured_capture_interval(observation, monkeypatch):
    from module.config import cfg

    auto, _, capture, _ = observation
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"screenshot_interval": 0.1}))
    auto._latest_screenshot_monotonic = 99.8
    auto.take_screenshot(max_age=10)
    capture.assert_called_once()


@pytest.mark.parametrize("monitor", [False, True])
def test_business_and_monitor_touch_invalidate_frame_and_preserve_capture_delay(observation, monitor, monkeypatch):
    auto, session, capture, _ = observation
    auto.last_screenshot_time = 100.0
    def mouse_click(*args, **kwargs):
        assert auto._latest_screenshot_monotonic == 0.0
        # A concurrent observation during input must also become invalid afterward.
        auto._remember_screenshot(auto.screenshot, auto._business_frame)
    if monitor:
        monkeypatch.setattr(auto, "_monitor_frame", auto._business_frame)
        monkeypatch.setattr(auto, "input_handler", SimpleNamespace(mouse_click=mouse_click))
        auto.monitor_mouse_click(5, 5)
    else:
        auto._invoke_input(mouse_click, auto._business_frame, 5, 5)
    assert auto._latest_screenshot_monotonic == 0.0
    auto.take_screenshot(max_age=0.85)
    capture.assert_called_once()
    session.cancel.wait.assert_called_once_with(pytest.approx(0.85))


def test_touch_failure_also_invalidates_observation(observation):
    auto, _, _, _ = observation
    def failed_touch():
        raise RuntimeError("lost input")
    with pytest.raises(RuntimeError, match="lost input"):
        auto._invoke_input(failed_touch, auto._business_frame)
    assert auto._latest_screenshot_monotonic == 0.0


def test_touch_only_hover_noop_does_not_discard_observation(observation):
    auto, _, capture, _ = observation
    def mouse_to_blank():
        pass
    auto._invoke_input(mouse_to_blank, auto._business_frame)
    auto.take_screenshot(max_age=0.85)
    capture.assert_not_called()


def test_cached_capture_still_obeys_stop(observation):
    auto, session, capture, _ = observation
    session.input.check_cancel.side_effect = BackendCancelled("stop")
    with pytest.raises(BackendCancelled):
        auto.take_screenshot(max_age=0.85)
    capture.assert_not_called()


def test_failed_capture_cannot_leave_reusable_observation(observation):
    auto, _, capture, _ = observation
    capture.side_effect = None
    capture.return_value = None
    assert auto.take_screenshot() is None
    assert auto.take_screenshot(max_age=0.85) is None
    assert capture.call_count == 2


def test_repeated_keywords_and_output_formats_reuse_one_ocr_inference(observation, monkeypatch):
    auto, _, _, module = observation
    result = SimpleNamespace(txts=["White Gossypium Owned"], boxes=[[[0, 0], [8, 0], [8, 4], [0, 4]]])
    run = Mock(return_value=result)
    monkeypatch.setattr(module.ocr, "run", run)
    crop = (0, 0, 8, 4)
    assert auto.find_text_element("Gossypium", crop) == [4, 2]
    assert auto.find_text_element("Owned", list(crop)) == [4, 2]
    assert auto.find_text_element("Missing", crop) is False
    assert auto.find_text_element("unused", crop, only_text=True) == result.txts
    assert auto.get_text_from_screenshot(crop) == result.txts
    run.assert_called_once()
    # Callers can modify returned lists/dicts without mutating the cached raw result.
    output = auto.find_text_element("unused", crop, only_text=True)
    output.clear()
    assert auto.get_text_from_screenshot(crop) == result.txts


def test_ocr_cache_is_separate_for_regions_and_invalidated_by_new_image(observation, monkeypatch):
    auto, _, _, module = observation
    run = Mock(return_value=SimpleNamespace(txts=[], boxes=[]))
    monkeypatch.setattr(module.ocr, "run", run)
    assert auto.find_text_element("missing", (0, 0, 8, 4)) is False
    assert auto.find_text_element("missing", (0, 0, 9, 4)) is False
    assert auto.find_text_element("unused", only_text=True) is False
    assert auto.get_text_from_screenshot() == []
    assert run.call_count == 3
    auto.screenshot = auto.screenshot.copy()
    auto.find_text_element("missing", (0, 0, 8, 4))
    assert run.call_count == 4
    auto.clear_img_cache()
    auto.find_text_element("missing", (0, 0, 8, 4))
    assert run.call_count == 5


def test_retry_reuses_only_initial_observation_then_refreshes_while_connecting(monkeypatch):
    from module.config import cfg

    task = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    auto = Mock()
    auto.get_restore_time.return_value = None
    auto.click_element.return_value = False
    connecting = iter([True, True, False])
    auto.find_element.side_effect = lambda target, **kwargs: next(connecting) if target.endswith("connecting_assets.png") else False
    monkeypatch.setattr(task, "auto", auto)
    monkeypatch.setattr(task, "check_times", Mock(return_value=False))
    monkeypatch.setattr(task, "ensure_simulator_game_started", Mock(return_value=False))
    task.retry(reuse_screenshot=True)
    assert [call.kwargs for call in auto.take_screenshot.call_args_list] == [
        {"max_age": 0.85}, {"max_age": 0.0}, {"max_age": 0.0},
    ]
    auto.mouse_click.assert_not_called()
