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
@pytest.mark.parametrize("cancelled", [False, True])
def test_screenshot_tool_only_resets_stop_at_new_independent_task(monkeypatch, main_running, cancelled):
    from module.backends import factory
    from module.config import cfg

    tool = import_module("tasks.tools.screenshot_module")
    main = import_module("tasks.base.script_task_scheme")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    monkeypatch.setattr(tool.auto, "task_running", main_running)
    session = Mock()
    session.cancel = threading.Event()
    if cancelled:
        session.cancel.set()
    session.input.is_pause = True
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)

    def initialize():
        if session.cancel.is_set():
            raise BackendCancelled("stopping main task")

    initialize = Mock(side_effect=initialize)
    monkeypatch.setattr(main, "init_game", initialize)
    capture = Mock(return_value=Mock())
    monkeypatch.setattr(tool.auto, "take_screenshot", capture)
    tool.ScreenshotGet().run()
    assert session.cancel.is_set() == (main_running and cancelled)
    assert session.input.is_pause == main_running
    assert initialize.call_count == int(not main_running)
    assert capture.call_count == int(not main_running)


@pytest.mark.parametrize("mode", ["open", "timeout", "cancel"])
def test_playcover_gate_keeps_original_timeout_and_stop_response(monkeypatch, mode):
    module = import_module("module.automation.automation")
    from module.backends import factory

    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"backend": "playcover"}))
    monkeypatch.setattr(module, "GATE_WAIT_TIMEOUT", 0.03 if mode == "timeout" else 30)
    automation = object.__new__(module.Automation)
    automation._interaction_gate = threading.Event()
    automation._input_lock = threading.RLock()
    automation._business_frame = None
    automation.input_handler = Mock()
    automation._invoke_input = Mock(return_value="clicked")
    session = Mock()
    if mode == "open":
        automation._interaction_gate.set()
    if mode == "cancel":
        session.input.check_cancel.side_effect = BackendCancelled("stopped")
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    results = []

    def click():
        try:
            results.append(automation._run_business_interaction("mouse_click")(10, 20))
        except BackendCancelled as exc:
            results.append(exc)

    worker = threading.Thread(target=click, daemon=True)
    worker.start()
    worker.join(0.5)
    try:
        assert not worker.is_alive(), "Closed gate bypassed the original deadline or cancellation"
        if mode == "cancel":
            assert isinstance(results[0], BackendCancelled)
            automation._invoke_input.assert_not_called()
        else:
            assert results == ["clicked"]
            automation._invoke_input.assert_called_once()
        assert automation._interaction_gate.is_set() == (mode == "open")
    finally:
        session.input.check_cancel.side_effect = BackendCancelled("cleanup")
        automation._interaction_gate.set()
        worker.join(0.5)


def test_coordinate_click_uses_one_existing_gate_deadline(monkeypatch):
    module = import_module("module.automation.automation")
    from module.backends import factory

    elapsed = 0.

    class ClosedGate:
        def wait(self, timeout):
            nonlocal elapsed
            elapsed += timeout
            return False

        def is_set(self):
            return False

    automation = object.__new__(module.Automation)
    automation._interaction_gate = ClosedGate()
    automation._input_lock = threading.RLock()
    automation._business_frame = None
    automation.input_handler = Mock()
    automation._invoke_input = Mock(return_value=True)
    automation.calculate_click_position = Mock(return_value=(10, 20))
    automation.last_click_time = 1
    automation.mouse_click = automation._run_business_interaction("mouse_click")
    automation.mouse_drag = automation.mouse_drag_down = automation.mouse_scroll = Mock()
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"backend": "playcover"}))
    monkeypatch.setattr(module.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(module.time, "time", lambda: 1)
    monkeypatch.setattr(factory, "get_playcover_session", lambda: Mock())

    assert automation.mouse_action_with_pos((10, 20)) is True
    assert elapsed == pytest.approx(module.GATE_WAIT_TIMEOUT)
    automation._invoke_input.assert_called_once()
