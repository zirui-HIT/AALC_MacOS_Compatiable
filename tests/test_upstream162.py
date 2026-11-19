"""Selective 1.6.2 integration: migrations, single back taps and reward verification."""

import copy
from importlib import import_module
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.parametrize("mode,mission,mail", [(0, True, True), (1, True, False), (2, False, True)])
def test_legacy_reward_migration_preserves_scope_and_keeps_pass_rewards_opt_in(mode, mission, mail):
    from module.config.config import Config

    values = {"config_version": 1781049600, "set_get_prize": str(mode), "teams": {"1": {"remark_name": "keep"}}}
    original = copy.deepcopy(values["teams"])
    result = Config._migrate_reward_settings(values)
    assert "set_get_prize" not in result
    assert result["claim_mission_rewards"] is mission
    assert result["claim_mail_rewards"] is mail
    assert result["claim_battle_pass_rewards"] is False
    assert result["teams"] == original
    assert Config._migrate_reward_settings(result) == result


def test_partial_legacy_and_explicit_new_reward_settings_migrate_safely():
    from module.config.config import Config

    values = Config._migrate_reward_settings({"config_version": 1781049600})
    assert values["claim_battle_pass_rewards"] is False
    assert values["claim_mission_rewards"] and values["claim_mail_rewards"]
    explicit = {"set_get_prize": 2, "claim_mission_rewards": True, "claim_mail_rewards": False,
                "claim_battle_pass_rewards": True}
    result = Config._migrate_reward_settings(explicit)
    assert result == {"claim_mission_rewards": True, "claim_mail_rewards": False, "claim_battle_pass_rewards": True}


@pytest.mark.parametrize("backend,original", [("playcover", None), ("playcover", (120, 70)), ("windows", None)])
def test_back_variant_is_recognized_on_same_frame_and_clicked_once(monkeypatch, backend, original):
    module = import_module("module.automation.automation")
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"backend": backend, "game_profile": "auto"}))
    auto = module.Automation.__new__(module.Automation)
    auto.model = "clam"
    auto.take_screenshot = Mock(return_value=Image.new("L", (1920, 1080)))
    auto.find_image_element = Mock(side_effect=lambda path, *args, **kwargs: original if path.endswith("back_assets.png") else (180, 90))
    auto.mouse_action_with_pos = Mock(return_value=True)
    result = auto.click_element("home/back_assets.png", take_screenshot=True)
    auto.take_screenshot.assert_called_once()
    if original or backend == "playcover":
        assert result is True
        auto.mouse_action_with_pos.assert_called_once()
        assert auto.mouse_action_with_pos.call_args.args[0] == (original or (180, 90))
    else:
        assert result is False
        auto.mouse_action_with_pos.assert_not_called()
    assert auto.find_image_element.call_count == (2 if backend == "playcover" and not original else 1)


def test_template_anchor_uses_existing_resolver_scale_and_handles_missing_image(monkeypatch):
    from module.automation import Automation
    from utils.image_utils import ImageUtils

    auto = Automation.__new__(Automation)
    template = np.zeros((1080, 1920), dtype=np.uint8)
    template[100:160, 300:380] = 255
    monkeypatch.setattr(ImageUtils, "load_image", Mock(return_value=template))
    assert auto.get_template_position("native/asset.png") == (340, 130)
    assert auto.get_template_position("native/asset.png", "bbox") == (300, 100, 380, 160)
    with pytest.raises(ValueError):
        auto.get_template_position("native/asset.png", "invalid")
    monkeypatch.setattr(ImageUtils, "load_image", Mock(return_value=None))
    assert auto.get_template_position("missing.png") is None


@pytest.fixture
def rewards(monkeypatch):
    task = import_module("tasks.daily.get_prize")
    auto = Mock()
    auto.screenshot = Image.new("RGB", (1920, 1080))
    auto.get_restore_time.return_value = None
    auto.take_screenshot.return_value = auto.screenshot
    auto.get_template_position.return_value = (1423, 291)
    auto.find_element.side_effect = lambda path, **kwargs: [(800, 300), (800, 600)] if path.endswith("pass_coin.png") else path.endswith("daily_assets.png")
    auto.click_element.return_value = True
    monkeypatch.setattr(task, "auto", auto)
    monkeypatch.setattr(task, "sleep", Mock())
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    monkeypatch.setattr(task, "check_times", Mock(return_value=False))
    return task, auto


def test_red_dot_mask_rejects_brown_cards_clear_stamps_and_borders():
    from tasks.daily.get_prize import pass_red_dot_mask

    colors = np.array([[[220, 15, 15], [110, 0, 0], [180, 80, 60], [180, 180, 20], [90, 0, 0], [150, 50, 40]]], dtype=np.uint8)
    assert pass_red_dot_mask(colors).tolist() == [[255, 255, 0, 0, 0, 0]]


@pytest.mark.parametrize("height", [810, 1080])
def test_real_ios_162_pass_tabs_and_badge_geometry(monkeypatch, height):
    from PIL import ImageDraw

    from module.automation import auto
    from module.config import cfg
    from tasks.daily.get_prize import (
        PASS_DAILY_DOT_ROI,
        PASS_DOT_MIN_AREA,
        PASS_SEASONAL_DOT_ROI,
        PASS_WEEKLY_DOT_ROI,
        pass_red_dot_mask,
    )
    from utils.image_utils import ImageUtils
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn", "set_win_size": height}))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    frame = Image.open(SOURCE_ROOT / "tests/fixtures/ios_zh_cn/pass162_missions.png").resize((round(height * 16 / 9), height))
    monkeypatch.setattr(auto, "screenshot", frame.convert("L"))
    auto.clear_img_cache()
    for name in ("daily", "weekly", "seasonal", "battle_pass"):
        assert auto.find_element(f"pass/{name}_assets.png"), (height, name)
    for roi in (PASS_DAILY_DOT_ROI, PASS_WEEKLY_DOT_ROI, PASS_SEASONAL_DOT_ROI):
        assert ImageUtils.match_color_regions(np.array(frame), pass_red_dot_mask, roi=roi, min_area=PASS_DOT_MIN_AREA) == []
        # Place a badge on the retained real tab area, preserving screenshot scale.
        marked = frame.copy()
        scale = height / 1440
        x, y = (roi[0] + roi[2]) / 2 * scale, (roi[1] + roi[3]) / 2 * scale
        radius = 20 * scale
        ImageDraw.Draw(marked).ellipse((x-radius, y-radius, x+radius, y+radius), fill=(200, 10, 10))
        regions = ImageUtils.match_color_regions(np.array(marked), pass_red_dot_mask, roi=roi, min_area=PASS_DOT_MIN_AREA)
        assert len(regions) == 1, (height, roi, regions)


def test_missions_recheck_dots_and_repeat_claim_until_clear(rewards):
    task, auto = rewards
    auto.find_regions_by_color.side_effect = [[(1, 1, 600)], [(1, 1, 600)], [], [], []]
    assert task.get_pass_prize(claim_rewards=False)
    assert auto.mouse_click.call_count == 4
    assert [call.args[0] for call in auto.click_element.call_args_list] == ["pass/daily_assets.png"] * 2
    assert auto.find_regions_by_color.call_count == 5


def test_seasonal_missions_use_existing_two_page_scroll_and_verify_again(rewards):
    task, auto = rewards
    auto.find_regions_by_color.side_effect = [[], [], [(1, 1, 600)], []]
    assert task.get_pass_prize(claim_rewards=False)
    assert [call.args[0] for call in auto.click_element.call_args_list] == ["pass/weekly_assets.png", "pass/seasonal_assets.png"]
    auto.mouse_swipe_for_scroll.assert_called_once_with(750, 900, dy=-652)
    assert auto.mouse_click.call_count == 4
    assert auto.find_regions_by_color.call_count == 4


@pytest.mark.parametrize("recognized", [False, True])
def test_battle_pass_reward_success_requires_confirmation(rewards, recognized):
    task, auto = rewards
    auto.click_element.side_effect = lambda path, **kwargs: recognized if path.endswith("rewards_acquired_assets.png") else True
    assert task.get_pass_prize(claim_missions=False) is recognized
    auto.find_regions_by_color.assert_not_called()
    targets = [call.args[0] for call in auto.click_element.call_args_list]
    assert targets == ["pass/battle_pass_assets.png", "pass/claim_all_assets.png", "mirror/claim_reward/rewards_acquired_assets.png"]


def test_unavailable_pass_claim_all_is_a_successful_noop(rewards):
    task, auto = rewards
    auto.click_element.side_effect = lambda path, **kwargs: not path.endswith("claim_all_assets.png")
    assert task.get_pass_prize(claim_missions=False)
    assert auto.click_element.call_count == 2


def test_reward_timeout_and_invalid_color_capture_stay_bounded(rewards):
    task, auto = rewards
    auto.find_regions_by_color.return_value = None
    task.check_times.side_effect = [False, False, False, True]
    assert task.get_pass_prize(claim_rewards=False) is False
    assert auto.find_regions_by_color.call_count == 2
    auto.mouse_click.assert_not_called()


def test_network_retry_failure_aborts_rewards(rewards):
    task, auto = rewards
    auto.find_regions_by_color.return_value = [(1, 1, 600)]
    task.retry.return_value = False
    assert task.get_pass_prize(claim_rewards=False) is False
    assert auto.find_regions_by_color.call_count == 1


@pytest.mark.parametrize("missions,passes,mail", [(False, False, False), (True, False, True), (False, True, False), (True, True, True)])
def test_independent_reward_switches_route_the_existing_task(monkeypatch, missions, passes, mail):
    from module.config import cfg
    from tasks.base import script_task_scheme as script

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "claim_mission_rewards": missions, "claim_battle_pass_rewards": passes, "claim_mail_rewards": mail,
    }))
    back, claim, inbox = Mock(), Mock(return_value=True), Mock()
    monkeypatch.setattr(script, "back_init_menu", back)
    monkeypatch.setattr(script, "get_pass_prize", claim)
    monkeypatch.setattr(script, "get_mail_prize", inbox)
    script.to_get_reward()
    if missions or passes:
        claim.assert_called_once_with(claim_missions=missions, claim_rewards=passes)
    else:
        claim.assert_not_called()
    assert inbox.call_count == int(mail)
    assert back.call_count == (0 if not (missions or passes or mail) else 1 + int(missions or passes) + int(mail))


def test_failed_pass_claim_does_not_continue_to_mail(monkeypatch):
    from module.config import cfg
    from tasks.base import script_task_scheme as script

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "claim_mission_rewards": True, "claim_battle_pass_rewards": True, "claim_mail_rewards": True,
    }))
    monkeypatch.setattr(script, "back_init_menu", Mock())
    monkeypatch.setattr(script, "get_pass_prize", Mock(return_value=False))
    inbox = Mock()
    monkeypatch.setattr(script, "get_mail_prize", inbox)
    script.to_get_reward()
    inbox.assert_not_called()
