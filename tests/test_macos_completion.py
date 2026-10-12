"""Exercise the original completion path and real Qt exit in isolated processes."""

import json
import os
import subprocess
import sys

import pytest

from utils.runtime_paths import SOURCE_ROOT


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS completion adapter")
@pytest.mark.parametrize("actions,suspended,game_failure,full_window,late_delivery", [
    ([], False, False, False, False),
    (["exit_game"], False, False, False, False),
    (["exit_aalc"], False, False, False, False),
    (["exit_game", "exit_aalc"], False, False, True, False),
    (["exit_game", "exit_aalc"], False, False, False, True),
    (["exit_game", "exit_aalc"], True, False, False, False),
    (["exit_game", "exit_aalc"], False, True, False, False),
])
def test_completion_waits_for_worker_cleanup(tmp_path, actions, suspended, game_failure, full_window, late_delivery):
    script = """
import json
import os
import sys
import threading
import time
from unittest.mock import Mock

import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
from module.backends import factory
from module.platforms import macos
from module import system_actions
from tasks.base import script_task_scheme as task
from app import mediator
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

actions, suspended, game_failure, full_window, late_delivery = json.loads(sys.argv[1])
cfg.config = cfg.config.model_copy(update={
    'backend': 'playcover', 'daily_task': False, 'get_reward': False,
    'buy_enkephalin': False, 'mirror': False,
})
marks = []
warnings = []
mediator.warning.connect(warnings.append)
session = Mock()
session.cancel = threading.Event()
session.transport.connected = True
def stop_game():
    assert 'monitor_stopped' in marks
    if game_failure:
        raise OSError('fixture exit failure')
    marks.append('game_stopped')
    session.transport.connected = False
session.stop_game.side_effect = stop_game
def disconnect():
    time.sleep(0.2)
    marks.append('disconnected')
session.disconnect.side_effect = disconnect
factory.get_playcover_session = lambda: session
task.init_game = lambda: None
task._warn_if_game_monitor_hdr_enabled = lambda: None
task.auto.click_element = Mock(return_value=False)
task.retry_monitor.start = lambda: None
task.retry_monitor.stop = lambda: marks.append('monitor_stopped')
def awake(enable):
    if not enable:
        time.sleep(0.2)
        marks.append('awake_released')
task.apply_power_keep_awake = awake
macos.hotkeys_available = lambda: False
mediator.kill_signal.connect(lambda: marks.append('exit_requested'))
app = QApplication(['completion-test'])
if full_window:
    from app.my_app import MainWindow
    window = MainWindow(['--smoke-test'])
    left = window.farming_interface.interface_left
else:
    from app.farming_interface import FarmingInterfaceLeft
    left = FarmingInterfaceLeft()
left.after_completion_selector.apply_selection(actions, 'none', False)
system_actions.suspend_completion_actions(suspended)
should_exit = 'exit_aalc' in actions and not suspended and not game_failure
left.my_script = task.my_script_task()
left.my_script.finished.connect(lambda: marks.append('worker_finished'))
if not should_exit:
    left.my_script.finished.connect(app.quit)
app.aboutToQuit.connect(lambda: marks.append('quit_after_cleanup' if 'disconnected' in marks else 'quit_too_early'))
def timeout():
    marks.append('timeout')
    app.quit()
QTimer.singleShot(5000, timeout)
if late_delivery:
    left.my_script.start()
    assert left.my_script.wait(2000)
else:
    QTimer.singleShot(0, left.my_script.start)
assert app.exec() == 0
assert left.my_script.wait(2000)
assert 'timeout' not in marks, marks
assert 'quit_after_cleanup' in marks and 'quit_too_early' not in marks, marks
assert 'awake_released' in marks and 'worker_finished' in marks, marks
assert ('exit_requested' in marks) == should_exit, marks
assert ('game_stopped' in marks) == ('exit_game' in actions and not suspended and not game_failure), marks
assert getattr(left.my_script, 'exception', None) is None
assert warnings == [], warnings  # Successful completion never opens a warning dialog.
sys.stdout.write('COMPLETION_CHECK_PASSED\\n')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps([actions, suspended, game_failure, full_window, late_delivery])],
        cwd=SOURCE_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COMPLETION_CHECK_PASSED" in result.stdout, result.stdout + result.stderr
    assert "Destroyed while thread" not in result.stderr
