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
