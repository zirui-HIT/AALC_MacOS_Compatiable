"""Offline regressions for the task errors confirmed before the final repair."""

from importlib import import_module
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("mail", [None, (100, 100)])
def test_pass_reward_failure_uses_at_most_one_fallback(monkeypatch, mail):
    task = import_module("tasks.daily.get_prize")
    automation = Mock()
    captures = []

    def capture():
        captures.append(True)
        assert len(captures) <= 20, "The reward retry budget must terminate"
        return True

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = lambda path, **kwargs: mail if path == "home/mail_assets.png" else None
    automation.click_element.return_value = False
    automation.find_text_element.return_value = False
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task.ImageUtils, "load_image", lambda _: True)
    monkeypatch.setattr(task.ImageUtils, "get_bbox", lambda _: (0, 0, 20, 20))
    task.get_pass_prize()
    assert automation.mouse_click.call_count == (0 if mail is None else 1)


def test_successful_pass_rewards_keep_daily_then_weekly_order(monkeypatch):
    task = import_module("tasks.daily.get_prize")
    automation = Mock()
    automation.find_element.return_value = [(10, 20)]
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "retry", lambda: True)
    task.get_pass_prize()
    assert automation.mouse_click.call_count == 2
    automation.click_element.assert_called_once_with("pass/weekly_assets.png")


@pytest.mark.parametrize("kind", ["EXP", "thread"])
def test_resumed_daily_battle_is_counted_and_flag_restored(monkeypatch, kind):
    from module.config import cfg
    from tasks.base import script_task_scheme as task

    fighter = import_module("tasks.battle.battle")
    recovery = import_module("tasks.base.retry")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(deep=True, update={
        "backend": "playcover", "daily_task": True, "get_reward": False,
        "buy_enkephalin": False, "mirror": False, "set_EXP_count": 2,
        "set_thread_count": 2, "use_continuous_combat": False,
    }))
    automation = Mock()
    automation.get_restore_time.return_value = 0
    automation.find_element.side_effect = lambda path, **kwargs: (
        (10, 10) if path == f"battle/clear_rewards_{kind}{'_1' if kind == 'EXP' else ''}_assets.png" else None)
    automation.click_element.side_effect = lambda path, **kwargs: path in {
        "battle/turn_assets.png", "battle/battle_finish_confirm_assets.png"}
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(fighter, "auto", automation)
    monkeypatch.setattr(fighter, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "check_times", lambda *args, **kwargs: False)
    monkeypatch.setattr(task, "battle", fighter.Battle())
    for name in ("init_game", "_warn_if_game_monitor_hdr_enabled", "back_init_menu", "make_enkephalin_module"):
        monkeypatch.setattr(task, name, Mock())
    monkeypatch.setattr(task.retry_monitor, "start", Mock())
    monkeypatch.setattr(task.retry_monitor, "stop", Mock())
    monkeypatch.setattr(task, "execute_after_completion", Mock(return_value=False))
    exp, thread = Mock(), Mock()
    monkeypatch.setattr(task, "onetime_EXP_process", exp)
    monkeypatch.setattr(task, "onetime_thread_process", thread)
    task.script_task()
    assert exp.call_count == (1 if kind == "EXP" else 2)
    assert thread.call_count == (1 if kind == "thread" else 2)
    assert task.battle.first_battle is False


@pytest.mark.parametrize("identity", range(12))
def test_super_shop_priority_refers_to_selected_sinner_identity(monkeypatch, identity):
    from module.config import TeamSetting, cfg
    from tasks.mirror import in_shop as task

    chosen, order = [0] * 12, [0] * 12
    chosen[identity] = order[identity] = 1
    shop = task.Shop(TeamSetting(chosen_sinners=chosen, sinner_order=order,
                                 sinners_be_select=1, skill_replacement_select=0))
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: (
        [(100, 300), (200, 300), (300, 300)] if path.endswith("skill_replacement_coins.png") else None)
    automation.click_element.return_value = False
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    shop.selected_id_skill_replacement("mirror/shop/ID_skill_search_assets.png")
    positions = [198, 353, 510, 663, 818, 968, 1121, 1277, 1428, 1581, 1737, 1889]
    scale = cfg.set_win_size / 1440
    assert automation.mouse_click.call_args_list[0].args == (positions[identity] * scale, 1299 * scale)


@pytest.mark.parametrize("success", [False, True])
def test_starting_gift_is_selected_and_only_successful_upgrade_is_recorded(monkeypatch, success):
    from module.config import TeamSetting
    from tasks.mirror import in_shop as task

    shop = task.Shop(TeamSetting())
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: (
        (50, 50) if path.endswith("sort_button_assets.png") else
        (700, 400) if path.endswith(f"big_{shop.system}.png") else None)
    automation.click_element.side_effect = lambda path, **kwargs: success and path.endswith("power_up_assets.png")
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    shop.enhance_gifts()
    assert (700, 400) in [call.args for call in automation.mouse_click.call_args_list]
    assert shop.first_gift_enhance is success
    assert shop.enhance_gifts_list == ([(700, 400)] if success else [])


@pytest.mark.parametrize("timing", [0, 1])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("fused", [False, True])
def test_second_system_reward_uses_configured_timing_and_action(monkeypatch, timing, enabled, fused):
    from module.config import TeamSetting, cfg
    from tasks.mirror import mirror as task

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": 1080}))
    dungeon = task.Mirror(TeamSetting(second_system=True, second_system_select=1,
                                    second_system_setting=timing,
                                    second_system_action=[0, 0, enabled, 0]), 1)
    dungeon.shop.fuse_IV = fused
    gifts = [(500, 300), (900, 300), (1300, 300)]
    automation = Mock()

    def find(path, **kwargs):
        if path.endswith("acquire_ego_gift_card.png"):
            return gifts.copy()
        if path.endswith("acquire_ego_gift/bleed.png") and kwargs["my_crop"][0] == 900 - 50 * .75:
            return (20, 20)
        return None

    automation.find_element.side_effect = find
    automation.find_language_text.return_value = None
    automation.find_text_element.return_value = (1, 1)
    automation.click_element.return_value = False
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task.ImageUtils, "load_image", lambda _: None)
    monkeypatch.setattr(task.ImageUtils, "get_bbox", lambda _: (0, 0, 100, 100))
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    dungeon.acquire_ego_gift()
    expected = gifts[1] if enabled and (timing == 1 or fused) else gifts[0]
    assert automation.mouse_click.call_args_list[0].args == expected


@pytest.mark.parametrize("initial", [False, True])
def test_restart_resets_difficulty_to_initial_configuration(monkeypatch, initial):
    from module.config import TeamSetting, cfg
    from tasks.mirror import mirror as task

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"hard_mirror": initial}))
    dungeon = task.Mirror(TeamSetting(normal_to_hard_floor=3), 1)
    dungeon.floor = 3
    dungeon._enter_hard_mode_if_needed()
    automation = Mock()
    automation.click_element.side_effect = lambda path, **kwargs: path.endswith("towindow&forfeit_confirm_assets.png")
    monkeypatch.setattr(task, "auto", automation)
    dungeon.re_start()
    dungeon.floor = 1
    dungeon._enter_hard_mode_if_needed()
    assert dungeon.hard_mode is initial
    assert dungeon.mirror_map.hard_mode is initial
    assert dungeon.hard_reward_eligible is initial


@pytest.mark.parametrize("keyword", [False, True])
def test_refresh_does_not_count_previous_stock_as_new_purchases(monkeypatch, keyword):
    from module.config import TeamSetting
    from tasks.mirror import in_shop as task

    shop = task.Shop(TeamSetting(shopping_strategy=True, shopping_strategy_select=2))
    shop.fuse_aggressive_switch = False
    shop.max_keyword_refresh = int(keyword)
    shop.max_normal_refresh = int(not keyword)
    state = {"page": 0, "purchases": [0, 0]}
    automation = Mock()

    def click(path, **kwargs):
        if path.endswith("purchase_assets.png"):
            state["purchases"][state["page"]] += 1
            return True
        if path.endswith("refresh_assets.png") or path.endswith("refresh_keyword_confirm_assets.png"):
            state["page"] = 1
            return True
        return path.endswith("refresh_keyword_assets.png")

    automation.click_element.side_effect = click
    automation.find_element.side_effect = lambda path, **kwargs: (
        [(1000, 400), (1250, 400), (1500, 400)] if path.endswith(f"shop_{shop.system}.png") else
        (20, 20) if path.endswith("shop_coins_assets.png") else None)
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(shop, "_get_cost", lambda: 500 if state["page"] == 0 else 0)
    shop.buy_gifts()
    assert state["purchases"] == [3, 3]
