"""Thread entry failure budgets and logical coordinates with isolated input."""

from unittest.mock import Mock

import pytest


def test_exp_recognized_navigation_cannot_bypass_original_retry_budget(monkeypatch):
    from tasks.daily import luxcavation as task

    automation = Mock()
    automation.find_element.return_value = None
    automation.click_element.side_effect = lambda path, **kwargs: path == "home/drive_assets.png"
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    logger = Mock()
    monkeypatch.setattr(task, "log", logger)

    task.EXP_luxcavation()

    assert automation.take_screenshot.call_count == 31
    assert automation.model == "aggressive"
    logger.error.assert_called_once_with("无法进入经验本,不能进行下一步,此次经验本无效")


@pytest.mark.parametrize("after_scroll", [False, True])
def test_right_half_candidates_exclude_left_side_before_and_after_scroll(monkeypatch, after_scroll):
    from module.config import cfg
    from tasks.daily import luxcavation as task

    automation = Mock()
    formation = False
    queries = 0

    def find(path, **kwargs):
        nonlocal queries
        if path == "teams/identify_assets.png":
            return formation
        if path.endswith("thread_consume.png"):
            if kwargs.get("find_type"):
                queries += 1
                return [(700, 900)] if after_scroll and queries == 1 else [(700, 900), (1300, 700)]
            return (1300, 700)
        return None

    def click(x, y):
        nonlocal formation
        if (x, y) == (1300, 700):
            formation = True

    automation.find_element.side_effect = find
    automation.click_element.side_effect = lambda path, **kwargs: (1600, 300) if path.endswith("thread_enter_up80_assets.png") else False
    automation.mouse_click.side_effect = click
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": 1080}))
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)

    task.thread_luxcavation()

    assert formation
    assert (700, 900) not in [call.args for call in automation.mouse_click.call_args_list]
    assert queries == (2 if after_scroll else 1)


@pytest.mark.parametrize("failure", ["count", "anchor", "entry"])
def test_failed_thread_entry_consumes_original_retry_budget(monkeypatch, failure):
    from tasks.daily import luxcavation as task

    automation = Mock()
    frames = 0

    def capture():
        nonlocal frames
        frames += 1
        assert frames <= 32, "Recognized entries must not bypass the retry budget"
        return True

    automation.take_screenshot.side_effect = capture
    automation.find_element.return_value = None
    automation.click_element.side_effect = lambda path, **kwargs: (1600, 300) if path.endswith("thread_enter_up80_assets.png") else False
    if failure == "entry":
        automation.find_element.side_effect = lambda path, **kwargs: (
            [(1300, 700)] if path.endswith("thread_consume.png") and kwargs.get("find_type")
            else (1300, 700) if path.endswith("thread_consume.png") else None)
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "_prepare_continuous_combat_count", Mock(return_value=False))
    logger = Mock()
    monkeypatch.setattr(task, "log", logger)

    task.thread_luxcavation(2 if failure == "count" else 1)

    assert frames == 31 and automation.model == "aggressive"
    logger.error.assert_called_once_with("无法进入纽本,不能进行下一步,此次纽本无效")
