"""Exercise shared task decisions with iOS controls and different saved settings."""
from importlib import import_module
from unittest.mock import Mock

import pytest


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
