"""Host cancellation must not become an original Mirror Dungeon retry."""
import os
import threading
from importlib import import_module
from unittest.mock import Mock

import pytest

from module.backends.base import BackendCancelled
from module.my_error.my_error import userStopError


def test_original_mirror_retry_does_not_swallow_backend_stop(monkeypatch):
    from module.config import cfg

    task = import_module("tasks.base.script_task_scheme")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "auto_hard_mirror": False, "set_mirror_count": 1,
        "teams_be_select": [True], "teams_active_queue": [1],
    }))
    adventure = Mock()
    adventure.run.side_effect = BackendCancelled("stopped")
    constructor = Mock(return_value=adventure)
    monkeypatch.setattr(task, "Mirror", constructor)
    with pytest.raises(BackendCancelled):
        task.Mirror_task()
    constructor.assert_called_once()
    adventure.run.assert_called_once()


def test_worker_translates_stop_and_releases_backend(monkeypatch):
    from module.backends import factory
    from module.config import cfg

    task = import_module("tasks.base.script_task_scheme")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    stop_monitor = Mock()
    monkeypatch.setattr(task.retry_monitor, "stop", stop_monitor)
    session = Mock()
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    worker = task.my_script_task()
    monkeypatch.setattr(worker, "_run", Mock(side_effect=BackendCancelled("stopped")))
    worker.run()
    assert isinstance(worker.exception, userStopError)
    assert str(worker.exception) == "stopped"
    stop_monitor.assert_called_once()
    session.input.release_contacts.assert_called_once()
    session.disconnect.assert_called_once()
    assert not task.auto.task_running
    assert worker.mutex.tryLock()
    worker.mutex.unlock()


def test_retry_monitor_exits_on_host_stop_without_retrying(monkeypatch):
    monitor = import_module("tasks.base.retry_monitor").RetryMonitor()
    monitor.check_once = Mock(side_effect=BackendCancelled("stopped"))
    monkeypatch.setattr(monitor._stop_event, "wait", Mock(return_value=False))
    monitor._run()
    monitor.check_once.assert_called_once()


def test_caffeinate_tracks_host_process_and_balances_nested_users(monkeypatch):
    host = import_module("module.platforms.macos")
    child = Mock()
    start = Mock(return_value=child)
    monkeypatch.setattr(host, "_depth", 0)
    monkeypatch.setattr(host, "_awake", None)
    monkeypatch.setattr(host.subprocess, "Popen", start)
    host.keep_awake(True)
    host.keep_awake(True)
    start.assert_called_once_with(["/usr/bin/caffeinate", "-di", "-w", str(os.getpid())])
    host.keep_awake(False)
    child.terminate.assert_not_called()
    host.keep_awake(False)
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=2)


@pytest.mark.parametrize("main_running", [False, True])
def test_screenshot_tool_only_resets_stop_at_new_independent_task(monkeypatch, main_running):
    from module.backends import factory
    from module.config import cfg

    tool = import_module("tasks.tools.screenshot_module")
    main = import_module("tasks.base.script_task_scheme")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    monkeypatch.setattr(tool.auto, "task_running", main_running)
    session = Mock()
    session.cancel = threading.Event()
    session.cancel.set()
    session.input.is_pause = True
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)

    def initialize():
        if session.cancel.is_set():
            raise BackendCancelled("stopping main task")

    monkeypatch.setattr(main, "init_game", initialize)
    capture = Mock(return_value=Mock())
    monkeypatch.setattr(tool.auto, "take_screenshot", capture)
    tool.ScreenshotGet().run()
    assert session.cancel.is_set() == main_running
    assert session.input.is_pause == main_running
    assert capture.call_count == int(not main_running)
