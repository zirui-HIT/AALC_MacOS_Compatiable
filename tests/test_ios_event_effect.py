"""Real hybrid iOS event effects keep the original option/confirmation branch."""

import json
import threading
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT

FIXTURES = SOURCE_ROOT / "tests/fixtures/ios_zh_cn"
TARGET = "mirror/road_in_mir/select_event_effect_confirm.png"
OPTION = "mirror/road_in_mir/event_effect_button.png"


@pytest.fixture
def hybrid(monkeypatch):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_zh_cn", "set_win_size": 1080,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "model", "clam")
    return cfg, auto, path_manager


@pytest.mark.parametrize("height", [1080, 1440])
@pytest.mark.parametrize("theme", ["default", "dark"])
@pytest.mark.parametrize("model", ["normal", "clam"])
def test_real_selected_event_effect_matches_confirmation_at_original_threshold(hybrid, monkeypatch, height, theme, model):
    cfg, auto, paths = hybrid
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": height}))
    paths.set_theme(theme)
    frame = Image.open(FIXTURES / "event_effect_choice.png").resize((round(height * 16 / 9), height))
    monkeypatch.setattr(auto, "screenshot", frame)
    point = auto.find_element(TARGET, threshold=0.8, model=model)
    assert point is not None
    x, y = [value / (height / 1080) for value in point]
    assert 900 < x < 1025 and 750 < y < 795


@pytest.mark.parametrize("height", [1080, 1440])
def test_original_mirror_branch_selects_then_confirms_before_next_capture(hybrid, monkeypatch, height):
    from module.backends import factory
    from module.config import TeamSetting

    cfg, auto, _ = hybrid
    task = import_module("tasks.mirror.mirror")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": height}))
    frame = Image.open(FIXTURES / "event_effect_choice.png").resize((round(height * 16 / 9), height))
    metadata = json.loads((FIXTURES / "event_effect_choice.json").read_text())
    clicks = []

    class ReplayComplete(Exception):
        pass

    def capture(**kwargs):
        if len(clicks) == 2:
            raise ReplayComplete
        auto.screenshot = frame.copy()
        return auto.screenshot

    def click(x, y, **kwargs):
        # The original matcher may choose either card as scaling changes its
        # best score. Preserve that choice; only the confirmation asset changes.
        rects = metadata["original_option_rects"] if not clicks else [metadata["confirm_button_rect"]]
        x1080, y1080 = x * 1080 / height, y * 1080 / height
        assert any(left < x1080 < right and top < y1080 < bottom
                   for left, top, right, bottom in rects), (x, y, rects)
        clicks.append((x, y))

    monkeypatch.setattr(auto, "screenshot", frame)
    monkeypatch.setattr(auto, "take_screenshot", capture)
    monkeypatch.setattr(auto, "mouse_click", click)
    monkeypatch.setattr(auto, "last_click_time", -1)
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    monkeypatch.setattr(factory, "get_playcover_session", lambda: SimpleNamespace(
        cancel=threading.Event(), input=SimpleNamespace(check_cancel=Mock()),
    ))
    with pytest.raises(ReplayComplete):
        task.Mirror(TeamSetting(), 1).run()
    assert len(clicks) == 2


def test_event_effect_guard_does_not_confirm_other_real_pages(hybrid, monkeypatch):
    _, auto, paths = hybrid
    for path in FIXTURES.glob("*.png"):
        if path.name == "event_effect_choice.png":
            continue
        paths.initialize_paths()
        monkeypatch.setattr(auto, "screenshot", Image.open(path))
        assert not (auto.find_element(OPTION, threshold=0.75) and auto.find_element(TARGET)), path.name


def test_event_effect_overlay_remains_available_after_resource_sync(hybrid, monkeypatch):
    from utils import image_utils

    _, auto, _ = hybrid
    monkeypatch.setattr(image_utils, "synced_image_tree", lambda: True)
    monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / "event_effect_choice.png"))
    assert auto.find_element(TARGET)


@pytest.mark.parametrize("profile", ["ios_en", "auto"])
def test_other_profiles_do_not_use_hybrid_event_effect_asset(hybrid, monkeypatch, profile):
    from utils.image_utils import ImageUtils

    cfg, _, paths = hybrid
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile}))
    paths.initialize_paths()
    assert not any(path.endswith("/ios_zh_cn") for path in ImageUtils.existing_image_paths(TARGET))
