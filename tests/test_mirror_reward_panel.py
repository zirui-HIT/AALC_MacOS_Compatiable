"""Replay native reward panels without closing them through the backdrop."""

from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT

CLAIM = "mirror/claim_reward/claim_rewards_assets.png"
CONSUME = "mirror/claim_reward/use_enkephalin_assets.png"
COINS = "mirror/claim_reward/coins.png"
FIXTURES = SOURCE_ROOT / "tests/fixtures"


@pytest.fixture
def native(monkeypatch):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(deep=True, update={
        "backend": "playcover", "game_profile": "ios_zh_cn", "set_win_size": 1080,
        "save_rewards": False, "floor_3_exit": False, "no_weekly_bonuses": False,
        "hard_mirror_single_bonuses": True, "hard_mirror": True,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    monkeypatch.setattr(auto, "screenshot", None)
    monkeypatch.setattr(auto, "model", "clam")
    path_manager.initialize_paths()
    auto.clear_img_cache()
    return auto, cfg, path_manager


def frame(name, height=1080):
    return Image.open(FIXTURES / f"{name}.png").convert("L").resize((height * 16 // 9, height))


@pytest.mark.parametrize("height", [810, 1080, 1440])
@pytest.mark.parametrize("theme", ["default", "dark"])
@pytest.mark.parametrize("profile,page", [
    ("ios_zh_cn", "ios_zh_cn/full_hard_clear_preview"),
    ("ios_zh_cn", "ios_zh_cn/partial_hard_preview"),
    ("ios_zh_cn", "ios_zh_cn/full_mirror_claim"),
    ("ios_zh_cn", "ios_zh_cn/hard_mirror_three_bonuses"),
    ("ios_zh_cn", "ios_zh_cn/hard_mirror_one_bonus"),
    ("ios_en", "playcover/mirror_reward_preview"),
])
def test_open_panel_reuses_original_reward_branch(native, monkeypatch, height, theme, profile, page):
    auto, cfg, paths = native
    cfg.config.game_profile = profile
    cfg.config.set_win_size = height
    paths.initialize_paths()
    paths.set_theme(theme)
    auto.clear_img_cache()
    auto.screenshot = frame(page, height)
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.find_element(CONSUME)
    assert auto.find_element(COINS)
    assert auto.click_element(CLAIM) is True
    action.assert_not_called()


@pytest.mark.parametrize("profile,page", [
    ("ios_zh_cn", "ios_zh_cn/full_hard_statistics"),
    ("ios_zh_cn", "ios_zh_cn/partial_mirror_statistics"),
    ("ios_en", "playcover/mirror_completed"),
    ("ios_en", "playcover/mirror_reward_confirm"),
    ("ios_en", "playcover/mirror_reward_forfeit_confirm"),
])
def test_other_reward_pages_keep_original_click(native, monkeypatch, profile, page):
    auto, cfg, paths = native
    cfg.config.game_profile = profile
    paths.initialize_paths()
    auto.clear_img_cache()
    auto.screenshot = frame(page)
    point = auto.find_element(CLAIM)
    assert point
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.click_element(CLAIM) is True
    assert action.call_args.args[0] == point
    action.assert_called_once()


@pytest.mark.parametrize("options", [
    {"action": "move"}, {"times": 2}, {"dx": 20}, {"dy": -10},
    {"my_crop": (0, 0, 1920, 1080)},
])
def test_explicit_input_requests_keep_their_original_semantics(native, monkeypatch, options):
    auto, _, _ = native
    auto.screenshot = frame("ios_zh_cn/full_hard_clear_preview")
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.click_element(CLAIM, **options) is True
    action.assert_called_once()


def test_coordinate_queries_and_real_claim_button_are_unchanged(native, monkeypatch):
    auto, _, _ = native
    auto.screenshot = frame("ios_zh_cn/full_hard_clear_preview")
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.click_element(CLAIM, click=False) == auto.find_element(CLAIM)
    action.assert_not_called()
    assert auto.click_element(CONSUME) is True
    action.assert_called_once()


@pytest.mark.parametrize("missing", [COINS, CONSUME])
def test_both_panel_anchors_are_required(native, monkeypatch, missing):
    auto, _, _ = native
    monkeypatch.setattr(auto, "find_element", lambda target, *args, **kwargs: None if target == missing else (10, 20))
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.click_element(CLAIM) is True
    action.assert_called_once()


@pytest.mark.parametrize("backend,profile", [("windows", "ios_zh_cn"), ("playcover", "auto")])
def test_other_profiles_and_backends_keep_original_click(native, monkeypatch, backend, profile):
    auto, cfg, _ = native
    cfg.config.backend = backend
    cfg.config.game_profile = profile
    monkeypatch.setattr(auto, "find_element", Mock(return_value=(10, 20)))
    action = Mock(return_value=True)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    assert auto.click_element(CLAIM) is True
    auto.find_element.assert_called_once()
    action.assert_called_once()


@pytest.mark.parametrize("profile,hard_mode,statistics,preview,settled,xp,toggles", [
    ("ios_en", False, "playcover/mirror_completed", "playcover/mirror_reward_preview",
     "playcover/mirror_reward_preview", 30, 0),
    ("ios_zh_cn", True, "ios_zh_cn/full_hard_statistics", "ios_zh_cn/hard_mirror_three_bonuses",
     "ios_zh_cn/hard_mirror_one_bonus", 75, 2),
    # The existing Chinese XP crop is 30 with no weekly bonus. Exercise both
    # initial difficulty settings: only the actual page determines the amount.
    ("ios_zh_cn", False, "ios_zh_cn/full_hard_statistics", "ios_zh_cn/full_mirror_claim",
     "ios_zh_cn/full_mirror_claim", 30, 0),
    ("ios_zh_cn", True, "ios_zh_cn/full_hard_statistics", "ios_zh_cn/full_mirror_claim",
     "ios_zh_cn/full_mirror_claim", 30, 0),
])
def test_original_mirror_run_reads_xp_and_applies_weekly_policy(
    native, monkeypatch, profile, hard_mode, statistics, preview, settled, xp, toggles,
):
    from tasks.mirror import mirror

    auto, cfg, paths = native
    cfg.config.game_profile = profile
    cfg.config.hard_mirror = hard_mode
    paths.initialize_paths()
    auto.clear_img_cache()
    state = {"page": statistics, "opens": 0, "toggles": 0, "captures": 0}

    class RewardReady(BaseException):
        pass

    def capture(**kwargs):
        state["captures"] += 1
        assert state["captures"] < 15, "Original reward flow did not reach claim"
        auto.screenshot = frame(state["page"])
        return auto.screenshot

    def action(position, *args, **kwargs):
        x, y = position
        if x > 1500 and y > 850:
            # The second backdrop tap closes the iOS panel: reproduce the bug.
            state["page"] = statistics if state["page"] != statistics else preview
            state["opens"] += 1
        elif 1200 < x < 1350 and 780 < y < 850:
            raise RewardReady
        else:
            raise AssertionError(f"Unexpected action: {position}")
        return True

    def toggle(x, y):
        assert 760 < x < 1220 and 330 < y < 420
        state["toggles"] += 1
        if state["toggles"] == toggles:
            state["page"] = settled

    monkeypatch.setattr(auto, "take_screenshot", capture)
    monkeypatch.setattr(auto, "mouse_action_with_pos", action)
    monkeypatch.setattr(auto, "mouse_click", toggle)
    monkeypatch.setattr(mirror, "sleep", lambda _: None)
    monkeypatch.setattr(mirror, "retry", lambda **kwargs: True)
    logger = Mock()
    monkeypatch.setattr(mirror, "log", logger)
    capture()
    dungeon = mirror.Mirror(cfg.config.teams["1"], 1)
    with pytest.raises(RewardReady):
        dungeon.run()
    assert dungeon.pass_coins == xp
    assert state["opens"] == 1
    assert state["toggles"] == toggles
    logger.warning.assert_not_called()
