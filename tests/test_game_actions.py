from unittest.mock import Mock

import pytest

from module.backends.base import BackendCapabilities
from tasks.common.game_actions import GameActions


def test_windows_shortcuts_remain_unchanged():
    automation = Mock()
    actions = GameActions(automation, BackendCapabilities(native_keys=True))
    actions.select_win_rate()
    actions.start_turn()
    actions.back()
    assert [call.args for call in automation.key_press.call_args_list] == [("p",), ("enter",), ("esc",)]
    automation.click_element.assert_not_called()


def test_ios_clicks_buttons_and_confirms_battle():
    automation = Mock()
    automation.click_element.return_value = True
    automation.find_element.side_effect = lambda path, **kwargs: path != "battle/pause_assets.png" or automation.click_element.call_count >= 2
    actions = GameActions(automation, BackendCapabilities(touch=True))
    assert actions.select_win_rate()
    assert actions.start_turn()
    assert actions.back()
    assert [call.args[0] for call in automation.click_element.call_args_list] == ["battle/win_rate_card.png", "battle/gear_start.png", "home/back_assets.png"]
    automation.key_press.assert_not_called()


@pytest.mark.parametrize("page, ready", [("flow_chain_start", True), ("mirror_battle_ready", False)])
def test_real_static_start_label_distinguishes_selected_from_unselected_gears(page, ready, monkeypatch):
    import numpy as np
    from PIL import Image

    from module.config import cfg
    from utils.image_utils import ImageUtils
    from utils.runtime_paths import SOURCE_ROOT

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    screen = np.array(Image.open(SOURCE_ROOT / f"tests/fixtures/playcover/{page}.png").convert("L"))
    template = ImageUtils._prepare_loaded_image(np.array(Image.open(
        SOURCE_ROOT / "assets/ios_en/default/battle/start_label.png")), True)
    _, score = ImageUtils.match_template(screen, template, None, "aggressive")
    assert (score >= 0.9) == ready


def test_ios_start_turn_leaves_retry_to_original_battle_loop():
    automation = Mock()
    automation.find_element.return_value = False
    assert not GameActions(automation, BackendCapabilities(touch=True)).start_turn()
    automation.click_element.assert_not_called()
    assert automation.take_screenshot.call_count == 1


def test_ios_back_without_a_button_returns_control_to_original_retry_loop():
    automation = Mock()
    automation.find_element.return_value = False
    automation.click_element.return_value = False
    assert not GameActions(automation, BackendCapabilities(touch=True)).back()
    automation.mouse_click.assert_not_called()


def test_map_zoom_requires_verified_capability_and_page():
    automation = Mock()
    automation.find_element.return_value = False
    with pytest.raises(NotImplementedError):
        GameActions(automation, BackendCapabilities(touch=True)).zoom_map()
    with pytest.raises(RuntimeError, match="recognized Mirror"):
        GameActions(automation, BackendCapabilities(touch=True, zoom=True)).zoom_map()
    automation.mouse_pinch.assert_not_called()
    automation.find_element.return_value = True
    GameActions(automation, BackendCapabilities(touch=True, zoom=True)).zoom_map()
    automation.mouse_pinch.assert_called_once_with((960, 540), 600, 300, duration=0.5)


def test_calibrated_normal_ios_mirror_is_available_in_task_runner(monkeypatch):
    from module.config import cfg
    from tasks.common.game_actions import validate_task_capabilities

    team = cfg.config.teams["1"].model_copy(update={
        "team_number": 1, "team_system": 1, "use_starlight": False, "opening_bonus": [0] * 10,
        "opening_items": False, "observe_ego_gift": False, "re_formation_each_floor": False,
        "normal_to_hard_floor": 0, "avoid_skill_3": False, "prioritize_skill_3": False,
        "defense_first_round": False, "defense_for_solo": False,
    })
    config = cfg.config.model_copy(update={
        "backend": "playcover", "mirror": True, "fight_to_last_man": True,
        "teams": {"1": team}, "teams_be_select": [True],
        "hard_mirror": False, "auto_hard_mirror": False, "floor_3_exit": False, "save_rewards": False,
        "re_claim_rewards": False, "daily_task": False, "get_reward": False, "buy_enkephalin": False,
        "skip_enkephalin": True, "mirror_keyboard_navigation": False, "mirror_keyboard_simple_pathfinding": False,
    })
    monkeypatch.setattr(cfg, "config", config)
    validate_task_capabilities(cfg)

def test_ios_title_waits_for_pulsing_label_then_taps_it(monkeypatch):
    from importlib import import_module

    from module.config import cfg

    recovery = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    frames = iter([False, True, True])
    automation.find_element.side_effect = lambda path: next(frames) if path.endswith("touch_to_start_assets.png") else False
    monkeypatch.setattr(recovery, "auto", automation)
    monkeypatch.setattr(recovery, "sleep", lambda _: None)
    recovery.click_title_screen_safely()
    assert automation.take_screenshot.call_count == 2
    automation.click_element.assert_called_once_with("base/touch_to_start_assets.png", offset=False)


def test_ios_login_page_requests_manual_login_without_input(monkeypatch):
    from importlib import import_module

    from module.config import cfg

    recovery = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_element.side_effect = lambda path: path.endswith("sign_in_assets.png")
    monkeypatch.setattr(recovery, "auto", automation)
    with pytest.raises(RuntimeError, match="manual Google / Apple login"):
        recovery.click_title_screen_safely()
    automation.click_element.assert_not_called()
