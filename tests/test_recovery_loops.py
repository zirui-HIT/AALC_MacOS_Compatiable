"""Regressions for recovery stalls observed in the October 21 runtime log."""

from importlib import import_module
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("confirmation", [False, True])
def test_unchanged_defeat_dialog_does_not_count_as_five_battles(monkeypatch, confirmation):
    task = import_module("tasks.battle.battle")
    recovery = import_module("tasks.base.retry")
    home = import_module("tasks.base.back_init_menu")
    automation = Mock()
    frames = 0
    starts = []

    def capture():
        nonlocal frames
        frames += 1
        assert frames <= 20, "The existing battle timeout must remain effective"
        return True

    def find(path, **kwargs):
        if path == "battle/dead_all.png":
            return [(900, 390), (900, 530), (900, 670)] if kwargs else (900, 390)
        return None

    def timeout(start, **kwargs):
        starts.append(start)
        return frames >= 10

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = find
    automation.click_element.return_value = confirmation
    automation.get_restore_time.return_value = None
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task.time, "time", lambda: frames)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "check_times", timeout)
    monkeypatch.setattr(home, "back_init_menu", Mock())
    fighter = task.Battle()

    assert fighter.fight() is False
    assert fighter.fail_times == 0
    assert starts and set(starts) == {0}
    home.back_init_menu.assert_called_once_with()


def test_five_dismissed_defeat_dialogs_preserve_original_failure_limit(monkeypatch):
    task = import_module("tasks.battle.battle")
    recovery = import_module("tasks.base.retry")
    automation = Mock()
    frames = 0

    def capture():
        nonlocal frames
        frames += 1
        assert frames <= 10
        return True

    def find(path, **kwargs):
        if path == "battle/dead_all.png" and frames % 2:
            return [(900, 390), (900, 530), (900, 670)] if kwargs else (900, 390)
        return None

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = find
    automation.click_element.return_value = True
    automation.get_restore_time.return_value = None
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "check_times", Mock(return_value=False))
    fighter = task.Battle()

    assert fighter.fight() is False
    assert fighter.fail_times == 5
    assert automation.click_element.call_count == 5


@pytest.mark.parametrize("screenshot", [None, True])
def test_unknown_restart_page_reuses_configured_stall_recovery(monkeypatch, screenshot):
    from module.config import TeamSetting, cfg
    from tasks.base import retry as recovery
    from tasks.mirror import mirror as task

    now = 0
    automation = Mock()

    def capture():
        nonlocal now
        now += 11
        assert now <= 44, "The entire restart loop needs a persistent deadline"
        return screenshot

    automation.take_screenshot.side_effect = capture
    automation.get_restore_time.return_value = None
    automation.click_element.return_value = False
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"task_stall_timeout": 30}))
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "get_game_actions", Mock())
    monkeypatch.setattr(task.time, "time", lambda: now)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    monkeypatch.setattr(recovery, "kill_game", Mock())
    monkeypatch.setattr(recovery, "restart_game", Mock())
    dungeon = task.Mirror(TeamSetting(), 1)

    assert dungeon.re_start() is False
    assert now == 33
    recovery.kill_game.assert_called_once_with()
    recovery.restart_game.assert_called_once_with()


def test_restart_deadline_respects_existing_restore_time(monkeypatch):
    from module.config import TeamSetting
    from tasks.base import retry as recovery
    from tasks.mirror import mirror as task

    automation = Mock()
    automation.get_restore_time.side_effect = [None, 50, 50, 50, 50]
    automation.take_screenshot.return_value = None
    check = Mock(side_effect=[False, False, True])
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task.time, "time", lambda: 10)
    monkeypatch.setattr(recovery, "check_times", check)

    assert task.Mirror(TeamSetting(), 1).re_start() is False
    assert [call.args[0] for call in check.call_args_list] == [10, 50, 50]


@pytest.mark.parametrize("phase", ["init", "home"])
def test_repeated_recovery_timeouts_do_not_grow_the_call_stack(monkeypatch, phase):
    from tasks.base import back_init_menu as home
    from tasks.base import retry as recovery
    from tasks.base import script_task_scheme as scheme

    attempts = 0

    def stalled():
        nonlocal attempts
        attempts += 1
        if attempts <= 1100:
            recovery.check_times(0, timeout=1, logs=False)

    initialize, return_home = Mock(), Mock()
    monkeypatch.setattr(scheme, "init_game", stalled if phase == "init" else initialize)
    monkeypatch.setattr(home, "back_init_menu", stalled if phase == "home" else return_home)
    monkeypatch.setattr(recovery.time, "time", lambda: 2)
    monkeypatch.setattr(recovery, "sleep", Mock())
    monkeypatch.setattr(recovery, "kill_game", Mock())

    recovery.restart_game()

    assert attempts == 1101
    assert recovery.kill_game.call_count == 1100
    assert initialize.call_count == (1101 if phase == "home" else 0)
    assert return_home.call_count == (1 if phase == "init" else 0)
    assert recovery._restart_context.active is False


def test_cancelled_recovery_clears_its_reentry_guard(monkeypatch):
    from module.backends.base import BackendCancelled
    from tasks.base import back_init_menu as home
    from tasks.base import retry as recovery
    from tasks.base import script_task_scheme as scheme

    initialize = Mock(side_effect=BackendCancelled())
    monkeypatch.setattr(scheme, "init_game", initialize)
    monkeypatch.setattr(home, "back_init_menu", Mock())
    monkeypatch.setattr(recovery, "sleep", Mock())
    with pytest.raises(BackendCancelled):
        recovery.restart_game()
    assert recovery._restart_context.active is False

    initialize.side_effect = None
    recovery.restart_game()
    home.back_init_menu.assert_called_once_with()


@pytest.mark.parametrize("failure", ["unknown", "no_frame", "stop"])
def test_dead_sinner_abandon_loop_keeps_existing_timeout_and_stop_flag(monkeypatch, failure):
    from module.config import cfg
    from tasks.base import back_init_menu as home
    from tasks.base import retry as recovery

    task = import_module("tasks.battle.battle")
    fighter = task.Battle()
    automation = Mock()
    frames = 0

    def capture():
        nonlocal frames
        frames += 1
        assert frames <= 14, "Abandoning must keep the outer battle deadline"
        if failure == "stop" and frames == 3:
            fighter.running = False
        return None if failure == "no_frame" and frames > 1 else True

    def find(path, **kwargs):
        if path == "battle/in_mirror_assets.png":
            return True
        if path == "battle/dead.png":
            return (700, 500)
        return None

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = find
    automation.find_language_text.return_value = (700, 500)
    automation.get_restore_time.return_value = None
    automation.click_element.return_value = False
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"fight_to_last_man": False}))
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task.time, "time", lambda: frames * 100)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(recovery, "kill_game", Mock())
    monkeypatch.setattr(recovery, "restart_game", Mock())
    monkeypatch.setattr(home, "back_init_menu", Mock())

    assert fighter.fight() is False
    assert frames == (3 if failure == "stop" else 13)
    assert home.back_init_menu.call_count == (0 if failure == "stop" else 1)
    assert recovery.kill_game.call_count == recovery.restart_game.call_count == home.back_init_menu.call_count
