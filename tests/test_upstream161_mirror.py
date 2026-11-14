"""Reward capacity and bounded initialization through the real Mirror methods."""
from importlib import import_module
from unittest.mock import Mock

import pytest
from PIL import Image


@pytest.mark.parametrize("capacity,selected", [
    (1, ()), (1, (0,)), (2, ()), (2, (0,)), (2, (1,)), (2, (2,)), (2, (0, 1)),
])
def test_reward_counter_completes_partial_selection_without_toggle_loop(monkeypatch, capacity, selected):
    from module.config import TeamSetting, cfg

    task = import_module("tasks.mirror.mirror")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": 1080}))
    dungeon = task.Mirror(TeamSetting(), 1)
    buttons = [(400, 300), (800, 300), (1200, 300)]
    state = {"selected": set(selected), "closed": False, "captures": 0}
    automation = Mock()

    def capture():
        state["captures"] += 1
        assert state["captures"] <= 4
        return True

    def click(x, y):
        index = buttons.index((x, y))
        if index in state["selected"]:
            state["selected"].remove(index)
        elif len(state["selected"]) < capacity:
            state["selected"].add(index)

    def text(target, **kwargs):
        label = f"{len(state['selected'])}/{capacity}"
        targets = [target] if isinstance(target, str) else target
        return (10, 10) if any(t in label for t in targets) else None

    def confirm(path, **kwargs):
        if path.endswith("acquire_ego_gift_select_assets.png"):
            state["closed"] = len(state["selected"]) == capacity
            return state["closed"]
        return False

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = lambda path, **kwargs: buttons if path.endswith("acquire_ego_gift_card.png") else None
    automation.find_language_text.return_value = False
    automation.find_text_element.side_effect = text
    automation.mouse_click.side_effect = click
    automation.click_element.side_effect = confirm
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task.ImageUtils, "load_image", lambda _: None)
    monkeypatch.setattr(task.ImageUtils, "get_bbox", lambda _: (0, 0, 100, 100))
    for _ in range(3):  # Original Mirror loop re-enters while the card page remains.
        dungeon.acquire_ego_gift()
        if state["closed"]:
            break
    assert state["closed"]
    assert len(state["selected"]) == capacity
    if capacity == 2 and len(selected) == capacity:
        automation.mouse_click.assert_not_called()


@pytest.mark.parametrize("scenario", ["empty_capture", "dismiss", "confirm", "scroll"])
def test_initial_gift_continues_and_scrolls_cannot_bypass_retry_budget(monkeypatch, scenario):
    from module.config import TeamSetting

    task = import_module("tasks.mirror.mirror")
    dungeon = task.Mirror(TeamSetting(), 1)
    dungeon.system = "slash" if scenario == "scroll" else "burn"
    dungeon.observe_bbox = (0, 0, 100, 100)
    automation = Mock()
    captures = []

    def capture():
        captures.append(1)
        assert len(captures) <= 31, "A continue bypassed the initialization budget"
        return None if scenario == "empty_capture" else True

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = lambda path, **kwargs: (
        (100, 200) if scenario == "scroll" and path.endswith("slash_gift_1.png") else None)
    automation.click_element.side_effect = lambda path, **kwargs: (
        scenario == "dismiss" and path.endswith("ego_gift_get_confirm_assets.png")
        or scenario == "confirm" and path.endswith("select_init_ego_gifts_confirm_assets.png"))
    home = Mock()
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "back_init_menu", home)
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(dungeon, "_click_init_gift_row", Mock(return_value=False))
    dungeon.select_init_ego_gift()
    home.assert_called_once()
    assert automation.mouse_drag.call_count <= 30


@pytest.mark.parametrize("height", [810, 1080])
@pytest.mark.parametrize("profile,fixture", [
    ("ios_zh_cn", "ios_zh_cn/full_init_gift.png"),
    ("ios_en", "playcover/mirror_gift_selected.png"),
])
def test_official_initial_gift_anchor_matches_actual_ios_rows(monkeypatch, height, profile, fixture):
    from pathlib import Path

    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    task = import_module("tasks.mirror.mirror")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile, "set_win_size": height}))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    path_manager.set_theme("default")
    with Image.open(Path(__file__).parent / "fixtures" / fixture) as frame:
        image = frame.convert("L").resize((round(height * 16 / 9), height), Image.Resampling.LANCZOS)
    monkeypatch.setattr(auto, "screenshot", image)
    click = Mock()
    monkeypatch.setattr(auto, "mouse_click", click, raising=False)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    auto.clear_img_cache()
    dungeon = object.__new__(task.Mirror)
    scale = height / 1080
    for row in [1, 2, 3]:
        assert dungeon._click_init_gift_row(row)
        x, y = click.call_args.args
        assert 1160 * scale < x < 1330 * scale
        assert (320 + 160 * (row - 1)) * scale < y < (475 + 160 * (row - 1)) * scale
    assert not dungeon._click_init_gift_row(4)
    assert click.call_count == 3
