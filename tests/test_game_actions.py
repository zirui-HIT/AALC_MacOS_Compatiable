from unittest.mock import Mock, patch

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
    automation.find_element.return_value = True
    actions = GameActions(automation, BackendCapabilities(touch=True))
    assert actions.select_win_rate()
    assert actions.start_turn()
    assert actions.back()
    assert [call.args[0] for call in automation.click_element.call_args_list] == ["battle/win_rate_card.png", "battle/gear_start.png", "home/back_assets.png"]
    automation.key_press.assert_not_called()


def test_ios_sent_touch_without_transition_is_failure():
    automation = Mock()
    automation.click_element.return_value = True
    automation.find_element.return_value = False
    with patch("time.sleep"), pytest.raises(RuntimeError, match="not confirmed"):
        GameActions(automation, BackendCapabilities(touch=True)).start_turn()


def test_resource_consuming_entry_is_never_replayed_on_missing_transition():
    automation = Mock()
    automation.find_element.side_effect = lambda path: path.endswith("chaim_to_battle_assets.png")
    automation.click_element.return_value = True
    with patch("time.sleep"), pytest.raises(RuntimeError, match="sent once"):
        GameActions(automation, BackendCapabilities(touch=True)).enter_battle()
    assert automation.click_element.call_count == 1


def test_unknown_home_page_never_sends_input_or_restarts():
    automation = Mock()
    automation.find_element.return_value = False
    with patch("time.sleep"), pytest.raises(RuntimeError, match="confirm iOS home"):
        GameActions(automation, BackendCapabilities(touch=True)).return_home()
    automation.click_element.assert_not_called()
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


def test_mirror_disabled_rewards_cannot_send_any_claim_input(monkeypatch):
    from tasks.mirror import mirror

    automation = Mock()
    monkeypatch.setattr(mirror, "auto", automation)
    dungeon = mirror.Mirror.__new__(mirror.Mirror)
    dungeon.allow_module_rewards = False
    with pytest.raises(RuntimeError, match="rewards are disabled"):
        dungeon.get_reward_in_road()
    assert not automation.mock_calls


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
    monkeypatch.setattr(cfg, "config", config.model_copy(update={"hard_mirror": True}))
    with pytest.raises(NotImplementedError, match="normal five-floor"):
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


def test_return_home_uses_ios_back_from_mirror_menu():
    automation = Mock()
    state = {"page": "mirror"}
    automation.find_element.side_effect = lambda path, **kwargs: path in {
        "mirror": {"home/back_ios.png"},
        "drive": {"home/window_assets.png"},
        "home": {"home/mail_assets.png"},
    }[state["page"]]

    def click(path, **kwargs):
        state["page"] = "drive" if path == "home/back_ios.png" else "home"
        return True

    automation.click_element.side_effect = click
    with patch("time.sleep"):
        assert GameActions(automation, BackendCapabilities(touch=True)).return_home()
    assert [call.args[0] for call in automation.click_element.call_args_list] == ["home/back_ios.png", "home/window_assets.png"]
