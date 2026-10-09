"""Configurable iOS workflows: presets, formations, batches, graces and strategies."""
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.parametrize('size', [1, 6, 10, 12])
def test_configured_sinners_are_selected_in_rank_order(monkeypatch, size):
    from tasks.teams import playcover
    automation = Mock()
    automation.find_element.return_value = True
    order = [0] * 12
    indices = list(reversed(range(size)))
    for rank, index in enumerate(indices, 1):
        order[index] = rank
    monkeypatch.setattr(playcover, 'auto', automation)
    monkeypatch.setattr(playcover, 'participant_count', Mock(side_effect=[(0, 12), (size, 12)]))
    monkeypatch.setattr(playcover.time, 'sleep', lambda _: None)
    assert playcover.select_mirror_participants(order)
    assert automation.mouse_click.call_args_list == [call(440 + i % 6 * 200, 350 + i // 6 * 300) for i in indices]


@pytest.mark.parametrize('order', [[0] * 12, [1, 1] + [0] * 10, [2] + [0] * 11, [1] * 11])
def test_invalid_sinner_order_fails_before_game_input(monkeypatch, order):
    from tasks.teams import playcover
    automation = Mock()
    monkeypatch.setattr(playcover, 'auto', automation)
    with pytest.raises(ValueError):
        playcover.select_mirror_participants(order)
    assert not automation.mock_calls


@pytest.mark.parametrize('number', [1, 2, 7, 20, 35, 40])
def test_ordinal_preset_selection_scrolls_and_confirms_custom_name(monkeypatch, number):
    from tasks.common import ios_pages
    from tasks.teams import playcover
    automation = Mock()
    monkeypatch.setattr(playcover, 'auto', automation)
    monkeypatch.setattr(playcover.time, 'sleep', lambda _: None)
    def texts(auto, box):
        name = 'TEAMS' if box == (110, 400, 290, 450) else 'Custom Name'
        return [ios_pages.TextHit(name, (195, 470))]
    monkeypatch.setattr(ios_pages, 'text_hits', texts)
    playcover.select_preset(number, by_order=True)
    automation.key_press.assert_not_called()
    assert automation.mouse_swipe_for_team_scroll.call_count >= 10
    y = automation.mouse_click.call_args.args[1]
    assert 445 <= y <= 800


def test_named_preset_one_does_not_match_ten(monkeypatch):
    from tasks.common import ios_pages
    from tasks.teams import playcover
    automation = Mock()
    monkeypatch.setattr(playcover, 'auto', automation)
    monkeypatch.setattr(playcover.time, 'sleep', lambda _: None)
    def texts(auto, box):
        return [ios_pages.TextHit('TEAMS' if box == (110, 400, 290, 450) else 'TEAMS#10', (195, 470))]
    monkeypatch.setattr(ios_pages, 'text_hits', texts)
    with pytest.raises(RuntimeError, match='No preset named'):
        playcover.select_preset(1, by_order=False)
    automation.mouse_click.assert_not_called()


@pytest.mark.parametrize('times,limit,batches', [(0, 3, []), (1, 3, [1]), (3, 3, [3]), (8, 3, [3, 3, 2]), (10, 10, [10])])
def test_daily_batch_counts_include_remainder(times, limit, batches):
    from tasks.base.script_task_scheme import _batch_combat
    process = Mock()
    _batch_combat(process, times, limit)
    assert process.call_args_list == [call(n) for n in batches]


@pytest.mark.parametrize('count', [1, 2, 5, 10])
def test_exp_and_thread_forward_consecutive_count(monkeypatch, count):
    from module.config import cfg
    from tasks.daily import luxcavation
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'backend': 'playcover'}))
    actions = Mock()
    monkeypatch.setattr(luxcavation, 'get_game_actions', lambda: actions)
    luxcavation.EXP_luxcavation(count)
    luxcavation.thread_luxcavation(count)
    assert actions.enter_daily_menu.call_args_list == [call('exp', count), call('thread', count)]


@pytest.mark.parametrize('system', range(10))
def test_active_settings_are_not_restricted_to_a_calibration_team(monkeypatch, system):
    from module.config import cfg
    from tasks.common.game_actions import validate_task_capabilities
    team = cfg.config.teams['1'].model_copy(update={
        'team_number': system + 1, 'team_system': system, 'normal_to_hard_floor': 0,
        'use_team_code': False, 'observe_ego_gift': False,
        'opening_items': True, 'opening_items_system': system, 'opening_items_select': system % 6,
        'opening_bonus': [system % 4] * 10, 'avoid_skill_3': True,
        'defense_for_solo': True, 're_formation_each_floor': True,
    })
    settings = cfg.config.model_copy(update={
        'backend': 'playcover', 'mirror': True, 'hard_mirror': False, 'auto_hard_mirror': False,
        'floor_3_exit': False, 'save_rewards': False, 'fight_to_last_man': False,
        'teams': {'1': team}, 'teams_be_select': [True], 'get_reward': True, 'buy_enkephalin': True,
        'daily_task': True, 'daily_teams': system + 1, 'set_thread_count': 8,
        'use_continuous_combat': True, 'targeted_teaming_thread': True, 'skip_enkephalin': False,
        'mirror_keyboard_navigation': False, 'mirror_keyboard_simple_pathfinding': False,
        'after_completion_actions': [], 'after_completion_power_action': 'none',
    })
    monkeypatch.setattr(cfg, 'config', settings)
    validate_task_capabilities(cfg)


@pytest.mark.parametrize('mode', ['avoid', 'prioritize', 'first_defense', 'always_defense', 'solo', 'default'])
def test_ios_battle_applies_configured_strategy_without_replacing_it(monkeypatch, mode):
    battle = import_module('tasks.battle.battle')
    controller = battle.Battle()
    chain = Mock(return_value=True)
    defense = Mock(return_value=True)
    actions = Mock()
    automation = Mock()
    monkeypatch.setattr(controller, '_chain_battle', chain)
    monkeypatch.setattr(controller, '_defense_this_round', defense)
    monkeypatch.setattr(battle, 'get_game_actions', lambda: actions)
    monkeypatch.setattr(battle, 'auto', automation)
    monkeypatch.setattr(battle, 'sleep', lambda _: None)
    state = battle.DefenseForSoloState(3) if mode == 'solo' else None
    controller._operate_playcover(first_turn=True, avoid_skill_3=mode == 'avoid',
        prioritize_skill_3=mode == 'prioritize', defense_first_round=mode == 'first_defense',
        defense_all_time=mode == 'always_defense', defense_for_solo_state=state)
    if mode in ('avoid', 'prioritize'):
        chain.assert_called_once_with(prioritize_skill_3=mode == 'prioritize')
        automation.take_screenshot.assert_called_once_with(gray=False)
    elif 'defense' in mode or mode == 'solo':
        defense.assert_called_once()
    else:
        actions.select_win_rate.assert_called_once()
        actions.start_turn.assert_called_once()
    if state:
        assert state.remaining_turns == 2


def test_solo_defense_limit_is_shared_across_battles(monkeypatch):
    battle = import_module('tasks.battle.battle')
    state = battle.DefenseForSoloState(2)
    defend = Mock(return_value=True)
    actions = Mock()
    monkeypatch.setattr(battle, 'get_game_actions', lambda: actions)
    monkeypatch.setattr(battle, 'sleep', lambda _: None)
    for _ in range(3):
        controller = battle.Battle()
        monkeypatch.setattr(controller, '_defense_this_round', defend)
        controller._operate_playcover(first_turn=True, avoid_skill_3=False, prioritize_skill_3=False,
            defense_first_round=False, defense_all_time=False, defense_for_solo_state=state)
    assert defend.call_count == 2
    assert actions.select_win_rate.call_count == 1
    assert state.remaining_turns == 0


@pytest.mark.parametrize('page,levels', [
    ('features_grace_initial', [0] * 10), ('features_grace_level1', [1] + [0] * 9),
    ('features_grace_level2', [2] + [0] * 9), ('features_grace_level3', [3] + [0] * 9),
    ('features_grace_configured', [0] * 7 + [1, 0, 0]),
])
def test_real_grace_levels(page, levels):
    from tasks.mirror.playcover_opening import read_grace_levels
    image = Image.open(SOURCE_ROOT / f'tests/fixtures/playcover/{page}.png')
    assert read_grace_levels(SimpleNamespace(screenshot=image)) == levels


@pytest.mark.parametrize('system', range(10))
@pytest.mark.parametrize('capacity', [1, 2, 3])
def test_all_initial_gift_systems_respect_order_and_capacity(monkeypatch, system, capacity):
    from module.config.config_typing import TeamSetting
    from tasks import all_systems
    from tasks.mirror import playcover_opening as opening
    automation = Mock()
    automation.find_element.return_value = False
    automation.click_element.return_value = True
    state = {'count': 0}
    def click(path, **kwargs):
        state['count'] += 1
        return True
    automation.click_element.side_effect = click
    monkeypatch.setattr(opening, 'gift_count', lambda _: (state['count'], capacity))
    monkeypatch.setattr(opening, 'click_label', lambda *args: True)
    monkeypatch.setattr(opening.time, 'sleep', lambda _: None)
    monkeypatch.setattr(opening, 'wait_until', lambda auto, condition, *args: condition() or pytest.fail('Wrong gift count'))
    opening.configure_gifts(automation, TeamSetting(team_system=(system + 1) % 10,
        opening_items=True, opening_items_system=system, opening_items_select=5))
    targets = [c.args[0] for c in automation.click_element.call_args_list]
    assert targets == [f'mirror/road_to_mir/select_init_gift/{all_systems[system]}_ego_gift_{n}.png'
                       for n in [3, 2, 1][:capacity]]


@pytest.mark.parametrize('selected', [1, 6, 10, 12])
def test_daily_preset_keeps_its_saved_game_deployment(monkeypatch, selected):
    from tasks.teams import playcover
    preset = Mock()
    auto = Mock()
    monkeypatch.setattr(playcover, 'select_preset', preset)
    monkeypatch.setattr(playcover, 'participant_count', lambda: (selected, 12))
    monkeypatch.setattr(playcover, 'auto', auto)
    assert playcover.select_daily_team(2)
    assert preset.call_args.args == (2,)
    assert not auto.mock_calls


def test_current_observation_settings_pass_preflight(monkeypatch):
    from module.config import cfg
    from tasks.common.game_actions import validate_task_capabilities
    settings = cfg.config.model_copy(deep=True)
    settings.teams['1'].observe_ego_gift = True
    settings.teams['1'].observe_ego_gift_selected = ['general_3_4_8']
    settings.backend = 'playcover'
    settings.mirror = True
    settings.hard_mirror = False
    settings.auto_hard_mirror = False
    settings.floor_3_exit = False
    settings.save_rewards = False
    monkeypatch.setattr(cfg, 'config', settings)
    validate_task_capabilities(cfg)


@pytest.mark.parametrize('remembered,desired', [(3, 1), (2, 3), (3, 2), (1, 1)])
def test_graces_restore_requested_level_when_game_remembers_previous_upgrade(monkeypatch, remembered, desired):
    from tasks.mirror import playcover_opening as opening
    state = {'selected': True, 'level': remembered}
    automation = Mock()
    def click(x, y):
        if y == 401:
            state['selected'] = not state['selected']
        else:
            button = 2 if x == 282 else 3
            state['level'] = 1 if state['level'] == button else button
    automation.mouse_click.side_effect = click
    monkeypatch.setattr(opening, 'read_grace_levels', lambda _: [state['level'] if state['selected'] else 0] + [0] * 9)
    monkeypatch.setattr(opening, 'wait_until', lambda auto, condition, *args: condition() or pytest.fail('Wrong grace level'))
    opening.configure_graces(automation, [desired] + [0] * 9)
    assert state == {'selected': True, 'level': desired}


@pytest.mark.parametrize('enabled', [False, True])
def test_battle_event_setting_is_forwarded_to_ios_loop(monkeypatch, enabled):
    from module.config import cfg
    battle = import_module('tasks.battle.battle')
    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={'backend': 'playcover'}))
    controller = battle.Battle()
    runner = Mock()
    monkeypatch.setattr(controller, '_fight_playcover', runner)
    controller.fight(choice_event_handling=enabled, combat_count=2)
    assert runner.call_args.args == (2,)
    assert runner.call_args.kwargs['choice_event_handling'] is enabled
