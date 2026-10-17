"""Exercise original weekly switching, successful-run counts and bonus selection offline."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.fixture
def settings(monkeypatch):
    from module.config import cfg

    team = cfg.config.teams["1"].model_copy(update={"fixed_team_use": False})
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(deep=True, update={
        "backend": "playcover", "game_profile": "ios_en", "set_win_size": 1080,
        "mirror": True, "auto_hard_mirror": True, "hard_mirror": True,
        "hard_mirror_chance": 3, "set_mirror_count": 10, "infinite_dungeons": False,
        "save_rewards": False, "floor_3_exit": False, "no_weekly_bonuses": False,
        "hard_mirror_single_bonuses": True, "re_claim_rewards": False,
        "teams": {"1": team}, "teams_active_queue": [1],
        "teams_be_select": [True], "teams_order": [1], "teams_be_select_num": 1,
    }))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    monkeypatch.setattr(cfg, "save", Mock())
    monkeypatch.setattr(cfg, "flush", Mock())
    return cfg


@pytest.mark.parametrize("last,now,expected", [
    ("2026-10-09T12:00", "2026-10-12T12:00", False),
    ("2026-10-14T12:00", "2026-10-15T05:00", False),
    ("2026-10-14T12:00", "2026-10-15T05:59:59", False),
    ("2026-10-14T12:00", "2026-10-15T06:00", True),
    ("2026-10-15T06:00", "2026-10-15T06:01", False),
    ("2026-09-30T12:00", "2026-10-15T06:00", True),
    ("2026-10-16T12:00", "2026-10-15T06:00", False),
])
def test_week_boundary_is_06_seoul(settings, monkeypatch, last, now, expected):
    from utils import utils

    tz = ZoneInfo("Asia/Seoul")
    settings.config.last_auto_change = datetime.fromisoformat(last).replace(tzinfo=tz).timestamp()
    instant = datetime.fromisoformat(now).replace(tzinfo=tz)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(utils, "datetime", Clock)
    assert utils.check_hard_mirror_time() is expected


@pytest.mark.parametrize("new_week", [False, True])
def test_week_switch_precedes_original_mirror_creation(settings, monkeypatch, new_week):
    from tasks.base import script_task_scheme as task

    settings.config.hard_mirror = False
    settings.config.hard_mirror_chance = 0
    monkeypatch.setattr(task, "check_hard_mirror_time", lambda: new_week)
    seen = []

    def create(team, number):
        seen.append((settings.hard_mirror, settings.hard_mirror_chance))
        return Mock(run=Mock(return_value=True))

    monkeypatch.setattr(task, "Mirror", create)
    monkeypatch.setattr(task, "back_init_menu", Mock())
    monkeypatch.setattr(task, "make_enkephalin_module", Mock())
    assert task.onetime_mir_process(settings.config.teams["1"], 1)
    assert seen == [(new_week, 3 if new_week else 0)]


@pytest.mark.parametrize("first_failure", [False, True])
def test_three_successful_hard_runs_then_normal(settings, monkeypatch, first_failure):
    from tasks.base import script_task_scheme as task

    seen = []

    def run(team, number):
        seen.append((settings.hard_mirror, settings.hard_mirror_chance))
        return not (first_failure and len(seen) == 1)

    monkeypatch.setattr(task, "onetime_mir_process", run)
    monkeypatch.setattr(task, "mediator", Mock())
    task.Mirror_task()
    expected = [(True, 3), (True, 2), (True, 1)] + [(False, 0)] * 7
    if first_failure:
        expected.insert(0, (True, 3))
    assert seen == expected
    assert settings.hard_mirror_chance == 0
    assert settings.hard_mirror is False
    assert task.mediator.mirror_signal.emit.call_args_list[-1] == call(10, 0)


@pytest.mark.parametrize("remaining", [0, -1])
def test_manual_hard_with_nonpositive_chance_stops_at_zero(settings, monkeypatch, remaining):
    from tasks.base import script_task_scheme as task

    settings.config.hard_mirror_chance = remaining
    settings.config.set_mirror_count = 1
    monkeypatch.setattr(task, "onetime_mir_process", Mock(return_value=True))
    monkeypatch.setattr(task, "mediator", Mock())
    task.Mirror_task()
    assert settings.hard_mirror_chance == 0
    assert settings.hard_mirror is False


@pytest.mark.parametrize("entry", ["run", "get_reward_in_road"])
@pytest.mark.parametrize("bonuses_left", [0, 1, 2, 3])
def test_original_reward_paths_leave_only_one_weekly_bonus(
    settings, monkeypatch, entry, bonuses_left,
):
    from tasks.mirror import mirror

    # Reverse order ensures the original sort selects the leftmost ON toggle.
    selected = [(600 + 100 * i, 350) for i in reversed(range(bonuses_left))]
    state = {"page": "complete", "used": None, "captures": 0}
    automation = Mock()
    automation.screenshot = np.zeros((1080, 1920), dtype=np.uint8)

    def screenshot(**kwargs):
        state["captures"] += 1
        assert state["captures"] < 20, "Reward loop did not finish"
        return automation.screenshot

    def find(path, **kwargs):
        if path.endswith("weekly_bonuses.png"):
            return selected.copy()
        if path.endswith("complete_mirror_100%_assets.png"):
            return state["page"] == "complete"
        if path.endswith("claim_rewards_assets.png"):
            return state["page"] == "complete"
        if path == "home/drive_assets.png":
            return state["page"] == "home"
        return None

    def click(path, **kwargs):
        if state["page"] == "complete" and path.endswith("claim_rewards_assets.png"):
            state["page"] = "preview"
            return True
        if state["page"] == "preview" and path.endswith("use_enkephalin_assets.png"):
            state["used"] = selected.copy()
            state["page"] = "confirm"
            return True
        if state["page"] == "confirm" and path.endswith("claim_rewards_confirm_assets.png"):
            state["page"] = "acquired"
            return True
        if state["page"] == "acquired" and path.endswith("rewards_acquired_assets.png"):
            state["page"] = "home"
            return True
        return False

    automation.take_screenshot.side_effect = screenshot
    automation.find_element.side_effect = find
    automation.find_language_text.return_value = None
    automation.click_element.side_effect = click
    automation.mouse_click.side_effect = lambda x, y: selected.remove((x, y))
    monkeypatch.setattr(mirror, "auto", automation)
    monkeypatch.setattr(mirror, "battle", Mock(fight=Mock(
        side_effect=AssertionError("Reward replay must not enter battle"))))
    monkeypatch.setattr(mirror, "make_enkephalin_module", Mock(
        side_effect=AssertionError("Reward replay must not refill")))
    monkeypatch.setattr(mirror, "sleep", lambda _: None)
    monkeypatch.setattr(mirror, "retry", lambda **kwargs: True)
    monkeypatch.setattr(mirror.ImageUtils, "load_image", lambda _: np.ones((1, 1), dtype=np.uint8))
    monkeypatch.setattr(mirror.ImageUtils, "get_bbox", lambda _: (0, 0, 1, 1))
    monkeypatch.setattr(mirror.ocr, "run", lambda _: SimpleNamespace(txts=["x45"]))
    dungeon = mirror.Mirror(settings.config.teams["1"], 1)
    assert getattr(dungeon, entry)()
    assert state["used"] == ([(600, 350)] if bonuses_left else [])
    assert automation.mouse_click.call_count == max(0, bonuses_left - 1)


@pytest.mark.parametrize("profile", ["ios_en", "ios_zh_cn"])
@pytest.mark.parametrize("height", [810, 1080])
def test_real_hard_reward_frame_recognizes_all_three_selected_bonuses(settings, monkeypatch, profile, height):
    from module.automation import auto
    from utils.path_manager import path_manager

    settings.config.game_profile = profile
    settings.config.set_win_size = height
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    auto.clear_img_cache()
    frame = Image.open(SOURCE_ROOT / "tests/fixtures/ios_zh_cn/hard_mirror_three_bonuses.png").convert("L")
    monkeypatch.setattr(auto, "screenshot", frame.resize((height * 16 // 9, height)))
    matches = auto.find_element("mirror/claim_reward/weekly_bonuses.png", find_type="image_with_multiple_targets")
    expected = [(839, 378), (992, 377), (1146, 377)]
    assert len(matches) == 3
    for actual, position in zip(sorted(matches), expected):
        assert actual == pytest.approx(tuple(value * height / 1080 for value in position), abs=2)
