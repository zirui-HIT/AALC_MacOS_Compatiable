"""Replay the existing observation routine with configurable galleries and iOS input."""
from unittest.mock import Mock

import pytest

from app.observe_ego_gift_selection import OBSERVE_SYSTEM_KEYS


@pytest.mark.parametrize('system', OBSERVE_SYSTEM_KEYS)
@pytest.mark.parametrize('level', [1, 2, 3])
@pytest.mark.parametrize('row,col', [(1, 1), (4, 8), (10, 2)])
def test_existing_observation_flow_selects_configured_system_tier_and_cell(monkeypatch, system, level, row, col):
    from module.config import cfg
    from tasks import observe_system
    from tasks.mirror import mirror
    from utils.image_utils import ImageUtils

    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'backend': 'playcover', 'set_win_size': 1080}))
    automation = Mock()
    def find(path, **kwargs):
        if path.endswith('observe_burn_assets.png'):
            return (154, 278)
        if path.endswith(f'Level_{"I" * level}.png'):
            return (175, 430)
        return None
    automation.find_element.side_effect = find
    automation.find_language_text.side_effect = [(1650, 860)] + [None] * 3
    automation.click_element.return_value = True
    monkeypatch.setattr(mirror, 'auto', automation)
    monkeypatch.setattr(mirror, 'sleep', lambda _: None)
    monkeypatch.setattr(ImageUtils, 'load_image', lambda path: path)
    monkeypatch.setattr(ImageUtils, 'get_bbox', lambda path: (117, 333, 1188, 936) if 'gift_box_bbox' in path else (1526, 828, 1764, 891))
    dungeon = mirror.Mirror.__new__(mirror.Mirror)
    dungeon.observe_ego_gift_selected = [f'{system}_{level}_{row}_{col}']
    dungeon.select_observe_ego_gift()
    index = 10 if system == 'general' else next(k for k, v in observe_system.items() if v == system)
    category_clicks = automation.mouse_click.call_args_list[:2]
    assert [c.args for c in category_clicks] == [(154 + 82.5 * ((index + 1) % 11), 278), (154 + 82.5 * index, 278)]
    cell = automation.mouse_click.call_args_list[2].args
    assert cell[0] == 175 + (col - 1) * 123.75
    assert 333 <= cell[1] < 936
    if row < 10:
        automation.mouse_drag.assert_not_called()
    else:
        assert automation.mouse_drag.call_count >= 1
    automation.key_press.assert_not_called()


@pytest.mark.parametrize('value', ['unknown_3_1_1', 'general_0_1_1', 'general_3_11_8', 'general_3_4_9', 'bad'])
def test_invalid_observation_setting_fails_before_input(monkeypatch, value):
    from tasks.mirror import mirror
    auto = Mock()
    monkeypatch.setattr(mirror, 'auto', auto)
    dungeon = mirror.Mirror.__new__(mirror.Mirror)
    dungeon.observe_ego_gift_selected = [value]
    with pytest.raises(ValueError, match='Invalid observed'):
        dungeon.select_observe_ego_gift()
    assert not auto.mock_calls


def test_ios_preparation_returns_observation_to_existing_mirror_handler():
    from tasks.mirror import playcover_entry as entry
    automation = Mock()
    automation.find_element.side_effect = lambda path: path == entry.OBSERVE_PAGES[0]
    entry.prepare_normal_mirror(automation, 2)
    automation.mouse_click.assert_not_called()
    automation.click_element.assert_not_called()


def test_observation_uses_latest_saved_team_setting_without_changing_it():
    from module.config.config_typing import TeamSetting
    from tasks.mirror.mirror import Mirror
    original = TeamSetting(observe_ego_gift=True, observe_ego_gift_selected=['general_3_4_8'])
    dungeon = Mirror(original, 1)
    assert dungeon.observe_ego_gift
    assert dungeon.observe_ego_gift_selected == ['general_3_4_8']
    dungeon.observe_ego_gift_selected.append('burn_1_1_1')
    assert original.observe_ego_gift_selected == ['general_3_4_8']


@pytest.mark.parametrize('enabled,current', [(True, False), (False, True), (True, True), (False, False)])
def test_gift_search_switch_follows_saved_observation_setting(monkeypatch, enabled, current):
    from module.config.config_typing import TeamSetting
    from tasks.mirror import playcover_opening as opening
    from utils.image_utils import ImageUtils
    state = {'on': current}
    automation = Mock()
    automation.find_element.side_effect = lambda path: state['on']
    automation.mouse_click.side_effect = lambda *args: state.update(on=not state['on'])
    automation.click_element.return_value = True
    monkeypatch.setattr(ImageUtils, 'load_image', lambda path: path)
    monkeypatch.setattr(ImageUtils, 'get_bbox', lambda path: (100, 200, 140, 240))
    monkeypatch.setattr(opening, 'click_label', lambda *args: True)
    monkeypatch.setattr(opening, 'gift_count', lambda _: (0, 0))
    monkeypatch.setattr(opening.time, 'sleep', lambda _: None)
    monkeypatch.setattr(opening, 'wait_until', lambda auto, condition, *args: condition() or pytest.fail('Wrong search switch'))
    opening.configure_gifts(automation, TeamSetting(observe_ego_gift=enabled,
        observe_ego_gift_selected=['general_3_4_8']))
    assert state['on'] is enabled
    assert automation.mouse_click.call_count == int(enabled != current)
