"""Color disambiguation and solo event safety, without controlling the game."""
from importlib import import_module
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image


def test_red_mask_preserves_amber_neutral_and_outside_pixels():
    from tasks.event.event_handling import black_out_red

    frame = np.zeros((30, 40, 3), dtype=np.uint8)
    frame[:] = (220, 220, 220)
    frame[10:20, 10:15] = (220, 20, 20)
    frame[10:20, 15:20] = (220, 150, 20)
    frame[0:5, 0:5] = (220, 20, 20)
    expected = frame.copy()
    expected[10:20, 10:15] = 0
    black_out_red(frame, (8, 8, 22, 22))
    assert np.array_equal(frame, expected)
    black_out_red(frame, (100, 100, 200, 200))
    assert np.array_equal(frame, expected)


@pytest.mark.parametrize("high_present", [True, False])
def test_color_stage_prevents_red_false_high_and_restores_low_frame(monkeypatch, high_present):
    from module.config import cfg

    event = import_module("tasks.event.event_handling")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "auto", "set_win_size": 1080}))
    raw = Image.new("RGB", (100, 40), (0, 0, 0))
    pixels = np.asarray(raw).copy()
    pixels[10, 10] = (220, 20, 20)
    if high_present:
        pixels[10, 70] = (220, 150, 20)
    raw = Image.fromarray(pixels)
    automation = Mock()

    def capture(*args, **kwargs):
        automation.screenshot = raw
        return raw

    def find(path, **kwargs):
        image = np.asarray(automation.screenshot)
        if path.endswith("very_high.png"):
            if image[10, 10].any():
                return (10, 10)  # The old grayscale false positive.
            return (70, 10) if high_present else None
        if path.endswith("very_low.png") and image[10, 10].any():
            return (10, 10)
        return None

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = find
    monkeypatch.setattr(event, "auto", automation)
    monkeypatch.setattr(event.ImageUtils, "load_image", lambda _: np.ones((40, 100), dtype=np.uint8))
    monkeypatch.setattr(event.ImageUtils, "get_bbox", lambda _: (0, 0, 100, 40))
    handler = event.EventHandling()
    assert handler.decision_event_handling()
    automation.mouse_action_with_pos.assert_called_once_with((70, 10) if high_present else (10, 10))
    assert automation.take_screenshot.call_count == (1 if high_present else 2)
    # Mutating the recognition frame must not modify the captured source image.
    assert tuple(np.asarray(raw)[10, 10]) == (220, 20, 20)


def option_automation(markers, positions):
    automation = Mock()

    def find(path, find_type="image", **kwargs):
        if path.endswith("unknown_event.png"):
            return markers if find_type == "image_with_multiple_targets" else (markers[0] if markers else None)
        if path.endswith("select_first_option_assets.png"):
            return positions
        return None

    automation.find_element.side_effect = find
    return automation


@pytest.mark.parametrize("height", [810, 1080])
def test_actual_ios_event_pixels_with_recolored_grade_band(monkeypatch, height):
    from pathlib import Path

    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    event = import_module("tasks.event.event_handling")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn", "set_win_size": height}))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    path_manager.set_theme("default")
    with Image.open(Path(__file__).parent / "fixtures/ios_zh_cn/full_event_check.png") as fixture:
        rgb = np.asarray(fixture.convert("RGB")).copy()
    # Actual glyphs/layout; colors are synthetic because the retained fixture
    # is grayscale. Red low badges surround the real fourth-slot high badge.
    band = rgb[910:950].astype(np.float32)
    band[:, :, 1:] *= .1
    band[:, 390:475, 1] = rgb[910:950, 390:475, 1] * .7
    rgb[910:950] = band.astype(np.uint8)
    frame = Image.fromarray(rgb).resize((round(height * 16 / 9), height), Image.Resampling.LANCZOS)

    def capture(*args, **kwargs):
        auto.screenshot = frame
        return frame

    monkeypatch.setattr(auto, "take_screenshot", capture)
    click = Mock()
    monkeypatch.setattr(auto, "mouse_action_with_pos", click, raising=False)
    auto.clear_img_cache()
    assert event.EventHandling().decision_event_handling()
    point = click.call_args.args[0]
    scale = height / 1080
    assert 390 * scale < point[0] < 475 * scale
    assert 910 * scale < point[1] < 950 * scale


@pytest.mark.parametrize("markers,expected", [
    ([(1200, 330)], (1040, 470)),
    ([(1200, 500)], (1040, 640)),
    ([(1200, 670)], (1040, 470)),
    ([(1200, 330), (1200, 500)], (1040, 640)),
])
def test_solo_avoids_every_unknown_owner(monkeypatch, markers, expected):
    event = import_module("tasks.event.event_handling")
    automation = option_automation(markers, [(1040, 300), (1040, 470), (1040, 640)])
    monkeypatch.setattr(event, "auto", automation)
    assert event.EventHandling().click_option_avoiding_unknown()
    automation.mouse_click.assert_called_once_with(*expected)


@pytest.mark.parametrize("markers,positions", [
    ([(1200, 330)], None),
    ([(1200, 330)], [(1040, 300)]),
    ([(1200, 330), (1200, 500)], [(1040, 300), (1040, 470)]),
])
def test_no_safe_solo_alternative_stops_without_a_click(monkeypatch, markers, positions):
    from module.backends.base import BackendCancelled

    event = import_module("tasks.event.event_handling")
    automation = option_automation(markers, positions)
    monkeypatch.setattr(event, "auto", automation)
    with pytest.raises(BackendCancelled, match="安全|只有"):
        event.EventHandling().click_option_avoiding_unknown()
    automation.mouse_click.assert_not_called()


@pytest.mark.parametrize("solo", [True, False])
def test_mirror_retry_fallbacks_cannot_bypass_solo_unknown_rule(monkeypatch, solo):
    from module.config import TeamSetting

    event = import_module("tasks.event.event_handling")
    task = import_module("tasks.mirror.mirror")
    dungeon = task.Mirror(TeamSetting(defense_for_solo=solo), 1)
    automation = option_automation([(1200, 330)], [(1040, 300), (1040, 470)])
    base_find = automation.find_element.side_effect
    clicks = []

    def find(path, **kwargs):
        if path.endswith("legend_assets.png"):
            return (10, 10) if len(clicks) >= (12 if solo else 1) else None
        return base_find(path, **kwargs)

    automation.find_element.side_effect = find
    automation.mouse_click.side_effect = lambda *p: clicks.append(p)
    automation.click_element.return_value = False
    automation.take_screenshot.return_value = True
    monkeypatch.setattr(event, "auto", automation)
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "event_handling", event.EventHandling())
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    dungeon.event_handling()
    assert clicks == ([(1040, 470)] * 12 if solo else [(1200, 330)])
    assert not any(c.args[0] == "event/select_first_option_assets.png" for c in automation.click_element.call_args_list)
