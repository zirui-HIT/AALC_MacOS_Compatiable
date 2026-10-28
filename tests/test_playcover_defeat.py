"""Real iOS defeat options must be selected inside their content, before confirming."""

import json
import threading
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT

FIXTURES = SOURCE_ROOT / "tests/fixtures/playcover"


@pytest.mark.parametrize("profile", ["ios_en", "ios_zh_cn"])
@pytest.mark.parametrize("height", [1080, 1440])
@pytest.mark.parametrize("already_selected", [False, True])
def test_real_defeat_dialog_selects_original_retry_option_then_confirms(monkeypatch, profile, height, already_selected):
    from module.automation import auto
    from module.backends import factory
    from module.config import cfg
    from utils.path_manager import path_manager

    task = import_module("tasks.battle.battle")
    recovery = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": profile, "set_win_size": height,
    }))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "model", "clam")
    monkeypatch.setattr(auto, "memory_protection", False)
    monkeypatch.setattr(auto, "last_click_time", -1)
    monkeypatch.setattr(auto, "get_restore_time", lambda: 0)
    monkeypatch.setattr(recovery, "check_times", Mock(return_value=False))
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(factory, "get_playcover_session", lambda: SimpleNamespace(
        cancel=threading.Event(), input=SimpleNamespace(check_cancel=Mock()),
    ))

    size = (round(height * 16 / 9), height)
    frames = {name: Image.open(FIXTURES / f"mirror_defeat_{name}.png").resize(size)
              for name in ("unselected", "selected")}
    metadata = json.loads((FIXTURES / "mirror_defeat_unselected.json").read_text())
    scale = height / 1080
    clicks = []

    class ReplayComplete(Exception):
        pass

    def capture():
        if len(clicks) == 2:
            # The original post-confirmation check must observe that the popup left.
            auto.screenshot = Image.new("L", size)
        else:
            auto.screenshot = frames["selected" if already_selected else "unselected"].copy()
        if fighter.fail_times:
            raise ReplayComplete
        return auto.screenshot

    def click(x, y, **kwargs):
        rect = metadata["retry_option_content_rect" if not clicks else "confirm_button_rect"]
        left, top, right, bottom = [value * scale for value in rect]
        assert left < x < right and top < y < bottom, (x, y, rect)
        clicks.append((x, y))

    monkeypatch.setattr(auto, "take_screenshot", capture)
    monkeypatch.setattr(auto, "mouse_click", click)
    fighter = task.Battle()
    with pytest.raises(ReplayComplete):
        fighter.fight()
    assert len(clicks) == 2
    assert fighter.fail_times == 1


def test_desktop_defeat_option_keeps_original_click_point(monkeypatch):
    from module.config import cfg

    task = import_module("tasks.battle.battle")
    recovery = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "auto"}))
    automation = Mock()
    automation.get_restore_time.return_value = 0
    automation.find_element.side_effect = lambda path, **kwargs: (
        [(939, 670), (939, 395), (939, 532)] if path == "battle/dead_all.png" and kwargs
        else (939, 395) if path == "battle/dead_all.png" else None
    )
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(recovery, "check_times", Mock(return_value=False))
    automation.mouse_click.side_effect = RuntimeError("recorded original option")
    with pytest.raises(RuntimeError, match="recorded original option"):
        task.Battle().fight()
    automation.mouse_click.assert_called_once_with(939, 532)
