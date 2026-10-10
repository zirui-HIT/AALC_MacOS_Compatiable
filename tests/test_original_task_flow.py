"""Exercise shared task decisions with iOS controls and different saved settings."""
from importlib import import_module
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('avoid,prioritize,turns,first_defense,all_defense,expected', [
    (False, False, None, False, False, 'win_rate'),
    (False, False, 0, False, False, 'win_rate'),
    (True, False, None, False, False, 'avoid'),
    (False, True, None, False, False, 'prioritize'),
    (True, True, None, False, False, 'avoid'),
    (False, False, 5, False, False, 'defense'),
    (False, False, None, True, False, 'defense'),
    (False, False, None, False, True, 'defense'),
])
def test_original_battle_branch_obeys_flags_without_forcing_links(
    monkeypatch, avoid, prioritize, turns, first_defense, all_defense, expected,
):
    task = import_module('tasks.battle.battle')
    automation = Mock()
    automation.find_element.return_value = True  # Gears visible; battle starts successfully.
    actions = Mock()
    monkeypatch.setattr(task, 'auto', automation)
    monkeypatch.setattr(task, 'sleep', lambda _: None)
    monkeypatch.setattr(task, 'get_game_actions', lambda: actions)
    fighter = task.Battle()
    fighter.defense_all_time = all_defense
    fighter._chain_battle = Mock(return_value=True)
    fighter._defense_this_round = Mock(return_value=True)
    state = task.DefenseForSoloState(turns) if turns is not None else None
    fighter._battle_operation(True, first_defense, avoid, prioritize, state)
    if expected in {'avoid', 'prioritize'}:
        fighter._chain_battle.assert_called_once_with(prioritize_skill_3=expected == 'prioritize')
        fighter._defense_this_round.assert_not_called()
    elif expected == 'defense':
        fighter._defense_this_round.assert_called_once()
        fighter._chain_battle.assert_not_called()
        if turns:
            assert state.remaining_turns == turns - 1
    else:
        actions.select_win_rate.assert_called_once()
        actions.start_turn.assert_called_once()
        fighter._chain_battle.assert_not_called()
        fighter._defense_this_round.assert_not_called()


@pytest.mark.parametrize('avoid,prioritize,defense', [
    (False, False, False), (False, False, True), (True, False, False), (False, True, False),
])
def test_original_mirror_forwards_team_battle_flags(monkeypatch, avoid, prioritize, defense):
    from module.config import cfg
    from tasks.mirror import mirror

    team = cfg.config.teams['1'].model_copy(update={
        'avoid_skill_3': avoid, 'prioritize_skill_3': prioritize,
        'defense_for_solo': defense, 'defense_for_solo_turns': 5, 'defense_first_round': False,
    })
    fighter = Mock()
    monkeypatch.setattr(mirror, 'battle', fighter)
    dungeon = mirror.Mirror(team, 1)
    dungeon._fight()
    args = fighter.fight.call_args.kwargs
    assert args['avoid_skill_3'] is avoid
    assert args['prioritize_skill_3'] is prioritize
    assert args['defense_first_round'] is False
    assert (args['defense_for_solo_state'] is not None) == defense
    if defense:
        assert args['defense_for_solo_state'].remaining_turns == 5


@pytest.mark.parametrize("count", [1, 2, 5, 10])
def test_original_exp_loop_sets_count_and_selects_highest_unlocked_stage(monkeypatch, count):
    from module.config import cfg
    from tasks.daily import luxcavation as task

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover", "set_win_size": 1080}))
    automation = Mock()
    state = {"formation": False}
    def find(path, **kwargs):
        if path.endswith("identify_assets.png"):
            return state["formation"]
        if path.endswith("exp_enter.png"):
            return [(600, 700), (1600, 700)] if kwargs.get("find_type") else (1600, 700)
        return None
    automation.find_element.side_effect = find
    automation.mouse_click.side_effect = lambda x, y: state.update(formation=True)
    automation.click_element.return_value = False
    configure = Mock(return_value=True)
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "_prepare_continuous_combat_count", configure)
    task.EXP_luxcavation(count)
    if count > 1:
        assert configure.call_args.args == (count, "EXP", (1615, 362.5))
    else:
        configure.assert_not_called()
    automation.mouse_click.assert_called_once_with(1600, 700)


@pytest.mark.parametrize("dead", [False, True])
@pytest.mark.parametrize("fight_to_last_man", [False, True])
def test_original_battle_loop_obeys_death_policy_on_ios(monkeypatch, dead, fight_to_last_man):
    from module.config import cfg
    from tasks.base import retry as recovery

    task = import_module("tasks.battle.battle")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "fight_to_last_man": fight_to_last_man}))
    automation = Mock()
    def find(path, **kwargs):
        if path.endswith("in_mirror_assets.png"):
            return True
        if path == "battle/dead.png":
            return (700, 500) if dead else None
        return None
    automation.find_element.side_effect = find
    automation.find_language_text.return_value = (700, 500)
    automation.click_element.side_effect = lambda path, **kwargs: path in {
        "battle/give_up_assets.png", "battle/battle_finish_confirm_assets.png"}
    automation.get_restore_time.return_value = None
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "check_times", lambda *args, **kwargs: False)
    task.Battle().fight()
    gave_up = any(call.args[0] == "battle/give_up_assets.png" for call in automation.click_element.call_args_list)
    assert gave_up == (dead and not fight_to_last_man)


def test_mirror_shop_keeps_original_optional_operations(monkeypatch):
    from module.config import cfg
    from tasks.mirror import mirror

    dungeon = mirror.Mirror(cfg.config.teams["1"], 1)
    dungeon.floor = 3
    dungeon.shop = Mock()
    dungeon.in_shop()
    dungeon.shop.in_shop.assert_called_once_with(3)


@pytest.mark.parametrize("used,target", [(0, 1), (0, 2), (0, 3), (1, 2), (2, 2), (3, 2)])
def test_original_refill_price_loop_obeys_today_target(monkeypatch, used, target):
    from module.config import cfg

    task = import_module("tasks.base.make_enkephalin_module")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover", "Dr_Grandet_mode": False}))
    state = {"used": used}
    automation = Mock()
    automation.find_element.side_effect = lambda path: path == f"enkephalin/lunacy_spend_{26 * (state['used'] + 1)}_assets.png"
    def click(path):
        if path.endswith("enkephalin_confirm_assets.png"):
            state["used"] += 1
        return True
    automation.click_element.side_effect = click
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "make_enkephalin_module", Mock())
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    task.lunacy_to_enkephalin(target)
    task.lunacy_to_enkephalin(target)
    assert state["used"] == max(used, target)
    purchases = [call for call in automation.click_element.call_args_list
                 if call.args[0].endswith("enkephalin_confirm_assets.png")]
    assert len(purchases) == max(0, target - used)


def test_original_observation_hits_configured_general_cell_on_real_ios_grid(monkeypatch):
    from PIL import Image

    from module.automation import auto
    from module.config import cfg
    from tasks.mirror.mirror import Mirror
    from utils.path_manager import path_manager
    from utils.runtime_paths import SOURCE_ROOT

    monkeypatch.setattr(cfg, 'config', cfg.config.model_copy(update={
        'backend': 'playcover', 'game_profile': 'ios_en', 'set_win_size': 1080,
    }))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, 'screenshot', Image.open(
        SOURCE_ROOT / 'tests/fixtures/playcover/observe_general_tier3_grid.png').convert('L'))
    monkeypatch.setattr(auto, 'take_screenshot', Mock())
    clicks = Mock(return_value=True)
    monkeypatch.setattr(auto, 'mouse_click', clicks)
    monkeypatch.setattr(auto, 'mouse_drag', Mock())
    monkeypatch.setattr(auto, 'click_element', Mock(return_value=True))
    monkeypatch.setattr(auto, 'find_language_text', lambda zh, en, *args: (1, 1) if en == 'select' else None)
    task = import_module('tasks.mirror.mirror')
    monkeypatch.setattr(task, 'sleep', lambda _: None)
    team = cfg.config.teams['1'].model_copy(update={
        'observe_ego_gift_selected': ['general_3_4_8'],
    })
    Mirror(team, 1).select_observe_ego_gift()
    # Third tab click selects General, then the original row/column calculation
    # hits the actual Spiderweb cell captured with a gold selection border.
    tab_x, tab_y = clicks.call_args_list[2].args
    assert 953 <= tab_x <= 1026 and 249 <= tab_y <= 323
    x, y = clicks.call_args_list[3].args
    assert 1010 <= x <= 1128 and 768 <= y <= 875
    auto.mouse_drag.assert_not_called()
