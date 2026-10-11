"""Configurable iOS workflows: presets, formations, batches, graces and strategies."""
from importlib import import_module
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize('times,limit,batches', [(0, 3, []), (1, 3, [1]), (3, 3, [3]), (8, 3, [3, 3, 2]), (10, 10, [10])])
def test_daily_batch_counts_include_remainder(times, limit, batches):
    from tasks.base.script_task_scheme import _batch_combat
    process = Mock()
    _batch_combat(process, times, limit)
    assert process.call_args_list == [call(n) for n in batches]


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
    controller.defense_all_time = mode == 'always_defense'
    automation.find_element.return_value = True
    controller._battle_operation(first_turn=True, avoid_skill_3=mode == 'avoid',
        prioritize_skill_3=mode == 'prioritize', defense_first_round=mode == 'first_defense',
        defense_for_solo_state=state)
    if mode in ('avoid', 'prioritize'):
        chain.assert_called_once_with(prioritize_skill_3=mode == 'prioritize')
        automation.take_screenshot.assert_not_called()
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
    monkeypatch.setattr(battle, 'auto', Mock())
    for _ in range(3):
        controller = battle.Battle()
        monkeypatch.setattr(controller, '_defense_this_round', defend)
        controller._battle_operation(first_turn=True, avoid_skill_3=False, prioritize_skill_3=False,
            defense_first_round=False, defense_for_solo_state=state)
    assert defend.call_count == 2
    assert actions.select_win_rate.call_count == 1
    assert state.remaining_turns == 0


def test_focused_encounter_preserves_original_strategy_scope(monkeypatch):
    battle = import_module('tasks.battle.battle')
    automation = Mock()
    automation.find_element.return_value = None
    actions = Mock()
    monkeypatch.setattr(battle, 'auto', automation)
    monkeypatch.setattr(battle, 'get_game_actions', lambda: actions)
    monkeypatch.setattr(battle, 'sleep', lambda _: None)
    controller = battle.Battle()
    controller._chain_battle = Mock()
    controller._defense_this_round = Mock()
    state = battle.DefenseForSoloState(3)
    controller._battle_operation(first_turn=True, avoid_skill_3=True, prioritize_skill_3=False,
        defense_first_round=True, defense_for_solo_state=state)
    controller._chain_battle.assert_not_called()
    controller._defense_this_round.assert_not_called()
    actions.select_win_rate.assert_called_once()
    actions.start_turn.assert_called_once()
    assert state.remaining_turns == 3
