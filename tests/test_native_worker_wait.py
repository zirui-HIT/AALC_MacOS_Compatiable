"""Cancel the real maintenance wait without altering its task branch or touching the game."""

import datetime
import importlib
import threading
import time
from unittest.mock import Mock

import pytest

from backend_host import runtime
from module.backends.base import BackendCancelled


def test_stopping_native_worker_interrupts_the_maintenance_wait(monkeypatch):
    task = importlib.import_module("tasks.base.back_init_menu")
    retry = importlib.import_module("tasks.base.retry")
    from utils import utils

    class MaintenanceTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 15, 10, tzinfo=tz)

    entered = threading.Event()
    automation = Mock()
    automation.click_element.return_value = False
    automation.find_element.side_effect = lambda target, **_: target == "base/notification_close_assets.png"
    logger = Mock()
    logger.info.side_effect = lambda _: entered.set()
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "log", logger)
    monkeypatch.setattr(task, "ensure_simulator_game_started", lambda: False)
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(retry, "kill_game", Mock())
    monkeypatch.setattr(retry, "restart_game", Mock())
    monkeypatch.setattr(utils, "get_day_of_week", lambda: 4)
    monkeypatch.setattr(datetime, "datetime", MaintenanceTime)
    monkeypatch.setattr(runtime.sys, "platform", "darwin")

    class Worker(runtime.WorkerThread):
        def run(self):
            task.back_init_menu(allow_restart=False)

    worker = Worker()
    cleanup = Mock()
    worker.after_run = cleanup
    worker.start()
    try:
        assert entered.wait(2)
        assert "7200秒" in logger.info.call_args.args[0]
        worker.requestInterruption()
        assert worker.wait(1000)
        assert isinstance(worker.exception, BackendCancelled)
        cleanup.assert_called_once_with()
        retry.kill_game.assert_called_once_with()
        retry.restart_game.assert_not_called()
    finally:
        worker.requestInterruption()
        assert worker.wait(1000)


def test_native_worker_wait_keeps_normal_duration(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    elapsed = []

    class Worker(runtime.WorkerThread):
        def run(self):
            started = time.monotonic()
            runtime.worker_sleep(0.02)
            elapsed.append(time.monotonic() - started)

    worker = Worker()
    worker.start()
    assert worker.wait(1000) and worker.exception is None
    assert elapsed[0] >= 0.02


def test_stop_interrupts_the_configured_click_interval_before_input(monkeypatch):
    from types import SimpleNamespace

    from module.automation import auto
    from module.backends import factory
    from module.config import cfg

    entered = threading.Event()

    class Cancellation(threading.Event):
        def wait(self, timeout=None):
            entered.set()
            return super().wait(timeout)

    cancel = Cancellation()

    def check_cancel():
        if cancel.is_set():
            raise BackendCancelled("fixture stopped")

    monkeypatch.setattr(factory, "get_playcover_session", lambda: SimpleNamespace(cancel=cancel, input=SimpleNamespace(check_cancel=check_cancel)))
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover", "mouse_action_interval": 60}))
    monkeypatch.setattr(auto, "last_click_time", 0)
    monkeypatch.setattr(auto, "mouse_click", Mock())
    monkeypatch.setattr(auto, "calculate_click_position", Mock())

    class Worker(runtime.WorkerThread):
        def run(self):
            auto.mouse_action_with_pos((100, 100))

    worker = Worker()
    worker.start()
    try:
        assert entered.wait(2)
        cancel.set()
        assert worker.wait(1000)
        assert isinstance(worker.exception, BackendCancelled)
        auto.calculate_click_position.assert_not_called()
        auto.mouse_click.assert_not_called()
    finally:
        cancel.set()
        assert worker.wait(1000)


@pytest.mark.parametrize("platform,worker", [("win32", True), ("darwin", False)])
def test_worker_wait_preserves_other_thread_sleep(monkeypatch, platform, worker):
    monkeypatch.setattr(runtime.sys, "platform", platform)
    sleep = Mock()
    monkeypatch.setattr(runtime.time, "sleep", sleep)
    if worker:
        class Worker(runtime.WorkerThread):
            def run(self):
                runtime.worker_sleep(20)

        value = Worker()
        value.start()
        assert value.wait(1000) and value.exception is None
    else:
        runtime.worker_sleep(20)
    sleep.assert_called_once_with(20)
