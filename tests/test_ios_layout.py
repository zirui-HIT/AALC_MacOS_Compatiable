"""Real iOS images exercise the original geometry and skill-selection algorithm."""
from importlib import import_module
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.parametrize("profile,offset", [("auto", 300), ("ios_en", 20)])
def test_layout_only_changes_image_geometry_for_ios(monkeypatch, profile, offset):
    from module.config import cfg
    from utils.image_utils import ImageUtils

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile}))
    assert ImageUtils.layout("luxcavation.exp_count_x", 300) == offset
    assert ImageUtils.layout("unmodified_coordinate", 123) == 123


@pytest.mark.parametrize("prioritize,lower", [(False, {2}), (True, {1, 3, 4, 5})])
def test_original_chain_algorithm_selects_correct_ios_skill_rows(monkeypatch, prioritize, lower):
    from module.automation import auto
    from module.config import cfg
    from utils.image_utils import ImageUtils
    from utils.path_manager import path_manager

    task = import_module("tasks.battle.battle")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    path_manager.initialize_paths()
    image = Image.open(SOURCE_ROOT / "tests/fixtures/playcover/reaccept_chain_ready.png")
    monkeypatch.setattr(auto, "screenshot", image.convert("L"))
    monkeypatch.setattr(auto, "model", "normal")
    auto.clear_img_cache()
    bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    monkeypatch.setattr(auto, "get_screenshot_crop", lambda box:
        bgr[int(box[1]):int(box[3]), int(box[0]):int(box[2])])
    gesture = Mock()
    monkeypatch.setattr(auto, "mouse_drag_link", gesture)
    monkeypatch.setattr(auto, "mouse_to_blank", Mock())
    monkeypatch.setattr(task, "get_game_actions", Mock())
    monkeypatch.setattr(task, "sleep", lambda _: None)
    assert task.Battle._chain_battle(prioritize_skill_3=prioritize)
    points = gesture.call_args.args[0]
    assert len(points) == 7
    assert 515 < points[0][0] < 555 and 835 < points[0][1] < 865
    # A loose bounding-box assertion used to accept points below the actual gear.
    start_template = ImageUtils._prepare_loaded_image(np.array(Image.open(
        SOURCE_ROOT / "assets/ios_en/default/battle/gear_start.png")), True)
    gear, _ = ImageUtils.match_template(np.array(image.convert("L")), start_template, None, "aggressive")
    assert abs(points[-1][0] - gear[0]) <= 5 and abs(points[-1][1] - gear[1]) <= 5
    assert {i for i, point in enumerate(points[1:-1], 1) if point[1] > 840} == lower
    assert all(650 < x < 1180 and 790 < y < 900 for x, y in points[1:-1])


def test_playcover_preserves_original_capture_interval_after_input(monkeypatch):
    from module.automation import auto
    from module.backends import factory
    from module.config import cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover", "screenshot_interval": 0.85}))
    session = Mock()
    session.cancel.wait.return_value = False
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    monkeypatch.setattr(auto, "last_screenshot_time", 123.5)
    monkeypatch.setattr(import_module("module.automation.automation").time, "time", lambda: 124.0)
    capture = Mock(return_value=Image.new("L", (1920, 1080)))
    monkeypatch.setattr(auto, "_capture", capture)
    auto.take_screenshot()
    session.cancel.wait.assert_called_once_with(pytest.approx(0.35))
    capture.assert_called_once_with(True)
