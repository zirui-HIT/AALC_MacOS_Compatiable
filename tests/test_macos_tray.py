"""Exercise menu bar residency and explicit quit without connecting to the game."""

import os
import subprocess
import sys

import pytest

from utils.runtime_paths import SOURCE_ROOT

BOOTSTRAP = """
import os
from unittest.mock import Mock
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
cfg.config = cfg.config.model_copy(update={'backend': 'playcover'})
from PySide6.QtCore import QObject, QEvent, QTimer, Signal, Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from app import my_app
app = QApplication(['tray-test'])
policies = []
my_app.set_dock_visible = policies.append
QSystemTrayIcon.isSystemTrayAvailable = lambda: True
window = my_app.MainWindow(['--smoke-test'])
app.processEvents()
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS menu bar lifecycle")
@pytest.mark.parametrize("scenario", ["hide_and_restore", "tray_clicks", "cancel_quit", "deferred_quit", "application_quit"])
def test_menu_bar_lifecycle(tmp_path, scenario):
    scripts = {
        "hide_and_restore": """
script = Mock()
script.isRunning.return_value = True
window.farming_interface.interface_left.my_script = script
window.setting_interface.playcover_settings.worker = script
my_app.MessageBoxConfirm = Mock(side_effect=AssertionError('Hide must not prompt or stop tasks'))
tray = window.tray_icon
window.init_system_tray()
assert window.tray_icon is tray
assert tray.contextMenu() is None  # Native menus swallow the double click.
assert len(window.tray_menu.actions()) == 3
assert window.tray_menu.actions()[1].isSeparator()
assert not app.quitOnLastWindowClosed()
assert not window.windowIcon().isNull() and not tray.icon().isNull()
for _ in range(3):
    window.titleBar.closeBtn.click()
    app.processEvents()
    assert not window.isVisible() and tray.isVisible()
    assert policies[-1] is False
    assert not window._quit_requested
    script.terminate.assert_not_called()
    script.finished.connect.assert_not_called()
    window.tray_menu.actions()[0].trigger()
    app.processEvents()
    assert window.isVisible() and policies[-1] is True
cfg.config = cfg.config.model_copy(update={'minimize_to_tray': True})
window.showMinimized()
app.processEvents()
assert not window.isVisible() and policies[-1] is False
window.restore_window()
app.processEvents()
assert window.isVisible() and not window.isMinimized()
QSystemTrayIcon.isSystemTrayAvailable = lambda: False
window.close()
assert window.isVisible()  # Never hide without a way to restore.
window.farming_interface.interface_left.my_script = None
window.setting_interface.playcover_settings.worker = None
window.tray_menu.actions()[-1].trigger()
assert window._quit_confirmed
""",
        "tray_clicks": """
from PySide6.QtTest import QTest
script = Mock()
script.isRunning.return_value = True
window.farming_interface.interface_left.my_script = script
my_app.MessageBoxConfirm = Mock(side_effect=AssertionError('Tray clicks must not quit'))
menu = window.tray_menu
for _ in range(3):
    window.close()
    window.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    assert not menu.isVisible() and not window.isVisible()
    window.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
    app.processEvents()
    assert window.isVisible() and policies[-1] is True
    QTest.qWait(QApplication.doubleClickInterval() + 100)
    assert not menu.isVisible() and not window._quit_requested
window.close()
window.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
QTest.qWait(QApplication.doubleClickInterval() + 100)
assert menu.isVisible() and not window.isVisible()
menu.actions()[0].trigger()
app.processEvents()
assert window.isVisible()
menu.close()
window.close()
window.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.Context)
assert menu.isVisible() and not window.isVisible()
menu.close()
window.tray_icon.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
app.processEvents()
assert window.isVisible() and not menu.isVisible()
script.terminate.assert_not_called()
window.farming_interface.interface_left.my_script = None
menu.actions()[-1].trigger()
assert window._quit_confirmed
""",
        "cancel_quit": """
script = Mock()
script.isRunning.return_value = True
window.farming_interface.interface_left.my_script = script
my_app.MessageBoxConfirm = Mock()
my_app.MessageBoxConfirm.return_value.exec.return_value = False
window.close()
assert not window.isVisible()
window.on_tray_quit()
assert window.isVisible() and policies[-1] is True
assert not window._quit_requested and not window._quit_confirmed
script.terminate.assert_not_called()
my_app.MessageBoxConfirm.return_value.exec.assert_called_once()
window.close()
assert not window.isVisible() and policies[-1] is False
window.farming_interface.interface_left.my_script = None
window.on_tray_quit()
assert window._quit_confirmed
""",
        "deferred_quit": """
class Worker(QObject):
    finished = Signal()
    running = True
    def isRunning(self): return self.running
    def terminate(self):
        QTimer.singleShot(0, self.finish)
    def finish(self):
        self.running = False
        self.finished.emit()
probe = Worker()
script = Worker()
window.setting_interface.playcover_settings.worker = probe
window.farming_interface.interface_left.my_script = script
my_app.MessageBoxConfirm = Mock()
my_app.MessageBoxConfirm.return_value.exec.return_value = True
window.close()
assert not window.isVisible()
window.on_tray_quit()
assert window._quit_requested and window._close_deferred
assert not window._quit_confirmed
probe.finish()
assert window._close_deferred and not window._quit_confirmed
app.processEvents()
assert not script.isRunning() and window._quit_confirmed
my_app.MessageBoxConfirm.return_value.exec.assert_called_once()
""",
        "application_quit": """
window.close()
assert not window.isVisible()
QTimer.singleShot(0, app.quit)
""",
    }
    script = BOOTSTRAP + scripts[scenario] + """
marks = []
app.aboutToQuit.connect(lambda: marks.append('quit'))
QTimer.singleShot(3000, lambda: (marks.append('timeout'), app.exit(1)))
assert app.exec() == 0
assert marks == ['quit'], marks
assert window._quit_confirmed
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=SOURCE_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="AppKit status button")
@pytest.mark.parametrize("buttons, expected", [(0, "Trigger"), (1, "Trigger"), (2, "Context")])
def test_native_tray_gesture_does_not_read_mouse_click_count(tmp_path, buttons, expected):
    script = f"""
from unittest.mock import Mock
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from app.common import macos_tray
app = QApplication(['tray-gesture-test'])
tray = macos_tray.MacSystemTrayIcon(None)
event = Mock()
event.type.return_value = 15  # NSEventTypeApplicationDefined, as on macOS 27.
event.clickCount.side_effect = AssertionError('clickCount is invalid on gesture events')
macos_tray.NSApplication = Mock()
macos_tray.NSApplication.sharedApplication.return_value.currentEvent.return_value = event
macos_tray.NSEvent = Mock()
macos_tray.NSEvent.pressedMouseButtons.return_value = {buttons}
reasons = []
tray.activated.connect(reasons.append)
tray._target.clicked_(None)
assert reasons == [QSystemTrayIcon.ActivationReason.{expected}], reasons
event.clickCount.assert_not_called()
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=SOURCE_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "darwin" or os.environ.get("AALC_NATIVE_UI_TEST") != "1",
                    reason="Opt-in native AppKit test requires WindowServer access")
@pytest.mark.parametrize("quit_entry", ["menu", "native"])
def test_native_dock_visibility_and_background_worker(tmp_path, quit_entry):
    script = """
import os
import sys
import time
import traceback
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from PySide6.QtCore import QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular, NSMenu, NSEventTrackingRunLoopMode
from Foundation import NSRunLoop, NSTimer
from app.my_app import MainWindow
class Worker(QThread):
    ticks = 0
    def run(self):
        while not self.isInterruptionRequested():
            self.ticks += 1
            self.msleep(10)
app = QApplication(['native-tray-test'])
window = MainWindow(['--smoke-test'])
native = NSApplication.sharedApplication()
worker = Worker()
window.farming_interface.interface_left.my_script = worker
worker.start()
marks = []
app.aboutToQuit.connect(lambda: marks.append('quit'))
opened = []
selected_action = [0]
timers = []
def inspect_native_menu():
    menu = window.tray_icon._native_menu
    assert isinstance(menu, NSMenu)
    assert menu.numberOfItems() == 3 and menu.itemAtIndex_(1).isSeparatorItem()
    assert menu.itemAtIndex_(0).title() == window.tray_menu.actions()[0].text()
    assert menu.itemAtIndex_(2).title() == window.tray_menu.actions()[-1].text()
    assert menu.itemAtIndex_(0).image() is not None and menu.font() is not None
    assert window.tray_icon._status_item.menu() is None  # Preserve double-click handling.
    opened.append(menu)
    def select_item(timer):
        menu.performActionForItemAtIndex_(selected_action[0])
        menu.cancelTrackingWithoutAnimation()
    timer = NSTimer.timerWithTimeInterval_repeats_block_(0.15, False, select_item)
    timers.append(timer)
    NSRunLoop.currentRunLoop().addTimer_forMode_(timer, NSEventTrackingRunLoopMode)
window.tray_menu.aboutToShow.connect(inspect_native_menu)
def verify():
    try:
        assert app.platformName() == 'cocoa'
        assert QSystemTrayIcon.isSystemTrayAvailable()
        assert native.activationPolicy() == NSApplicationActivationPolicyRegular
        assert window.isVisible() and window.tray_icon.isVisible()
        deadline = time.monotonic() + 2
        while not window.tray_icon.geometry().isValid() and time.monotonic() < deadline:
            QTest.qWait(50)
        assert window.tray_icon.geometry().isValid()
        window.grab().save(os.environ['AALC_NATIVE_PREVIEW_PATH'])
        for _ in range(3):
            before = worker.ticks
            window.titleBar.closeBtn.click()
            QTest.qWait(200)
            assert native.activationPolicy() == NSApplicationActivationPolicyAccessory
            assert not window.isVisible() and window.tray_icon.isVisible()
            assert worker.isRunning() and worker.ticks > before
            before_opened = len(opened)
            window.tray_icon._target.clicked_(None)
            QTest.qWait(QApplication.doubleClickInterval() + 400)
            assert len(opened) == before_opened + 1
            QTest.qWait(200)
            assert window.isVisible() and window.tray_icon._native_menu is None
            window.close()
            window.tray_icon._target.clicked_(None)
            QTest.qWait(50)
            window.tray_icon._target.clicked_(None)
            QTest.qWait(200)
            assert native.activationPolicy() == NSApplicationActivationPolicyRegular
            assert window.isVisible() and not window.isMinimized()
            assert not window.tray_menu.isVisible() and worker.isRunning()
            assert len(opened) == before_opened + 1  # Double clicks never open a menu.
        worker.requestInterruption()
        assert worker.wait(1000)
        if sys.argv[1] == 'native':
            native.terminate_(None)  # Native application menu / ⌘Q / Dock quit.
        else:
            selected_action[0] = 2
            window.tray_icon.popup_menu(window.tray_menu)
    except Exception:
        traceback.print_exc()
        worker.requestInterruption()
        worker.wait(1000)
        app.exit(1)
QTimer.singleShot(200, verify)
QTimer.singleShot(10000, lambda: app.exit(2))
assert app.exec() == 0
assert marks == ['quit']
assert window._quit_confirmed
"""
    result = subprocess.run(
        [sys.executable, "-c", script, quit_entry], cwd=SOURCE_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "cocoa", "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml"),
             "AALC_NATIVE_PREVIEW_PATH": str(tmp_path / "window.png")},
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
