"""Validate launchd registration and the existing scheduled task entry without game input."""

import os
import plistlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from utils import schedule_helper
from utils.runtime_paths import SOURCE_ROOT


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_helper.os, "getuid", lambda: 501, raising=False)
    helper = schedule_helper.ScheduleHelper_MacOS()
    helper.directory = tmp_path / "schedules"
    loaded = set()
    calls = []

    def launchctl(*arguments, check=True):
        calls.append(arguments)
        command = arguments[0]
        if command == "print":
            return SimpleNamespace(returncode=0 if arguments[1] in loaded else 113)
        if command == "bootstrap":
            with open(arguments[2], "rb") as file:
                definition = plistlib.load(file)
            loaded.add(f"{arguments[1]}/{definition['Label']}")
        elif command == "bootout":
            loaded.remove(arguments[1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper, "_launchctl", launchctl)
    return helper, loaded, calls


@pytest.mark.parametrize("frozen", [False, True])
def test_source_and_bundle_use_resident_protocol_and_only_run_at_calendar_time(scheduler, monkeypatch, frozen):
    helper, loaded, calls = scheduler
    monkeypatch.setattr(schedule_helper.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(schedule_helper.sys, "executable", "/Applications/With Spaces/AALC" if frozen else "/venv/bin/python")
    for name, hour, slot in [("AALC Daily Task", 8, "autodaily"), ("AALC Daily Task2", 20, "autodaily2")]:
        helper.register_daily_task(name, f"start --exit {slot}", hour, 0)
        path = helper.directory / f"{helper._labels[name]}.plist"
        definition = plistlib.loads(path.read_bytes())
        assert definition["ProgramArguments"] == ["/bin/sh", "-c",
            f"printf '%s' 'start|--exit|{slot}' | /usr/bin/nc -w 2 -G 1 127.0.0.1 62333"]
        assert definition["StartCalendarInterval"] == {"Hour": hour, "Minute": 0}
        assert "RunAtLoad" not in definition and "KeepAlive" not in definition
        assert definition["LimitLoadToSessionType"] == "Aqua"
        assert definition["WorkingDirectory"] == "/"
        assert path.stat().st_mode & 0o777 == 0o600
    assert len(loaded) == 2


def test_repeated_registration_update_and_removal_are_idempotent(scheduler):
    helper, loaded, calls = scheduler
    helper.unregister_task("AALC Daily Task")
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len([call for call in calls if call[0] == "bootstrap"]) == 1
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 9, 30)
    assert len([call for call in calls if call[0] == "bootstrap"]) == 2
    assert len([call for call in calls if call[0] == "bootout"]) == 1
    helper.unregister_task("AALC Daily Task")
    helper.unregister_task("AALC Daily Task")
    assert not loaded and not list(helper.directory.glob("*.plist"))


def test_saved_job_is_loaded_again_after_a_new_login_session(scheduler):
    helper, loaded, calls = scheduler
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    loaded.clear()
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len(loaded) == 1
    assert len([call for call in calls if call[0] == "bootstrap"]) == 2


def test_bootstrap_failure_is_reported_and_can_be_retried(scheduler, monkeypatch):
    helper, loaded, calls = scheduler
    original = helper._launchctl

    def fail(*arguments, check=True):
        if arguments[0] == "bootstrap":
            raise subprocess.CalledProcessError(5, arguments, stderr="fixture registration denied")
        return original(*arguments, check=check)

    monkeypatch.setattr(helper, "_launchctl", fail)
    with pytest.raises(subprocess.CalledProcessError):
        helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert not loaded and not list(helper.directory.glob("*.tmp"))
    monkeypatch.setattr(helper, "_launchctl", original)
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len(loaded) == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS scheduled UI and completion")
def test_two_slots_use_original_worker_close_only_game_and_keep_aalc_alive(tmp_path):
    script = """
import os
import threading
import time
from unittest.mock import Mock
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
cfg.config = cfg.config.model_copy(update={
    'backend': 'playcover', 'autodaily': True, 'autodaily2': True,
    'autodaily_task': [True, True, True, False],
    'autodaily2_task': [False, False, True, False],
    'autodaily_time': '08:00', 'autodaily_time2': '20:00',
    'autodaily_task_exit': [True, False, False, False, False, False, False],
    'autodaily2_task_exit': [True, False, False, False, False, False, False],
    'set_EXP_count': 1, 'set_thread_count': 3, 'set_lunacy_to_enkephalin': 2,
    'resonate_with_Ahab': False,
})
from utils import schedule_helper
registrations = []
schedule_helper.ScheduleHelper_MacOS.register_daily_task = lambda self, *args: registrations.append(args)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from app.my_app import MainWindow
from app.base_combination import AutoDailyView
from module.backends import factory
from tasks.base import script_task_scheme as task
app = QApplication(['schedule-test'])
window = MainWindow(['--smoke-test'])
assert not window.setting_interface.autodaily_group.isHidden()
assert 'autodaily' in window.setting_interface.setting_nav.nav_buttons
assert registrations == [('AALC Daily Task', 'start --exit autodaily', 8, 0),
                         ('AALC Daily Task2', 'start --exit autodaily2', 20, 0)]
view = AutoDailyView(window.setting_interface.autodaily_card)
assert not view.box_exit_game.isHidden()
assert all(widget.isHidden() for widget in
    (view.box_exit_emulator, view.box_sleep, view.box_hibernate, view.box_shutdown, view.box_lock))
marks = []
session = Mock()
session.cancel = threading.Event()
session.transport.connected = True
session.stop_game.side_effect = lambda: marks.append('close_game')
factory.get_playcover_session = lambda: session
task.init_game = lambda: marks.append('start_game')
task._warn_if_game_monitor_hdr_enabled = lambda: None
task.auto.click_element = Mock(return_value=False)
task.retry_monitor.start = lambda: None
task.retry_monitor.stop = lambda: None
task.apply_power_keep_awake = lambda enabled: None
task.send_toast = lambda *args, **kwargs: None
task.Daily_task_wrapper = lambda **kwargs: lambda: marks.append('daily')
task.to_get_reward = lambda: marks.append('reward')
task.Buy_enkephalin = lambda: marks.append(('exchange', cfg.set_lunacy_to_enkephalin))
task.Mirror_task = lambda: marks.append('mirror')
quit_requested = []
app.aboutToQuit.connect(lambda: quit_requested.append(True))
left = window.farming_interface.interface_left
def run_slot(slot):
    window.command_start(['aalc', 'start', '--exit', slot])
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        app.processEvents()
        if not window._scheduled_start_pending and left.my_script is not None and not left.my_script.isRunning():
            app.processEvents()
            assert getattr(left.my_script, 'exception', None) is None
            return
        time.sleep(0.01)
    raise AssertionError('Scheduled worker did not finish')
run_slot('autodaily')
assert marks == ['start_game', 'daily', 'reward', ('exchange', 2), 'close_game'], marks
marks.clear()
run_slot('autodaily2')
assert marks == ['start_game', ('exchange', 2), 'close_game'], marks
assert not quit_requested and not app.quitOnLastWindowClosed()
assert cfg.set_EXP_count == 1 and cfg.set_thread_count == 3 and cfg.set_lunacy_to_enkephalin == 2
window.on_tray_quit()
QTimer.singleShot(0, app.quit)
app.exec()
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT,
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen",
                                 "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
