import json
import os
import subprocess
import sys

import pytest

from app.common.display import readable_ui_scale
from utils.runtime_paths import SOURCE_ROOT, data_path


@pytest.mark.parametrize("saved", [0, 50, 75, 90])
def test_old_small_mac_zoom_is_migrated(saved):
    assert readable_ui_scale(saved, "darwin") == 125


@pytest.mark.parametrize("saved", [100, 125, 150, 175, 200])
def test_explicit_readable_mac_zoom_is_preserved(saved):
    assert readable_ui_scale(saved, "darwin") == saved


@pytest.mark.parametrize("saved", [0, 50, 75, 90, 100, 125, 200])
def test_windows_zoom_is_preserved(saved):
    assert readable_ui_scale(saved, "win32") == saved


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac typography and native DPI policy")
def test_small_screen_and_theme_changes_keep_ui_readable(tmp_path):
    script = """
import os
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
cfg.config = cfg.config.model_copy(update={'zoom_scale': 125})
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme
from app.my_app import MainWindow
app = QApplication(['ui-test'])
window = MainWindow(['--smoke-test'])
app.processEvents()
# The offscreen screen is smaller than the window. This previously persisted 50%.
assert cfg.zoom_scale == 125
assert window._resize_enabled
assert not window.titleBar.maxBtn.isHidden()
log = window.farming_interface.interface_right.scroll_log_edit
log.append('Win Rate — 图片更新完成')
for theme in (Theme.LIGHT, Theme.DARK):
    setTheme(theme)
    app.processEvents()
    assert 12 <= log.font().pixelSize() <= 13
    assert 100 <= log.document().firstBlock().blockFormat().lineHeight() <= 115
    assert window.pivot.currentItem().font().pixelSize() >= 14
    log.clear()
    for line in ('23:00:00 [INFO] 已准备', '23:00:01 [INFO] 已连接',
                 '23:00:02 [INFO] Win Rate', '23:00:03 [INFO] 图像更新完成'):
        log.append(line)
    app.processEvents()
    assert log.document().blockCount() == 4
    assert log.document().size().height() <= log.viewport().height()
    block = log.document().firstBlock()
    while block.isValid():
        assert 100 <= block.blockFormat().lineHeight() <= 115
        assert block.blockFormat().bottomMargin() == 0
        block = block.next()
options = window.setting_interface.zoom_card.comboBox
assert all(options.itemData(i) >= 100 for i in range(options.count()))
left = window.farming_interface.interface_left
assert left.after_completion_selector.height() <= 96
assert left.link_start_button.button.geometry().height() >= left.link_start_button.button.fontMetrics().height()
window.close()
app.quit()
"""
    environment = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QT_SCALE_FACTOR": "1.25",
        "TMPDIR": str(data_path("tmp")),
        "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml"),
    }
    result = subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT,
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, json.dumps({"stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False)


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac global hotkey lifecycle")
def test_widgets_share_listener_and_release_registrations_on_close_and_destroy(tmp_path):
    script = """
import os
import threading
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from module import hotkey_listener
from module.platforms import macos
macos.hotkeys_available = lambda: True
class FakeListener:
    instances = []
    def __init__(self, **kwargs): self.instances.append(self)
    def canonical(self, key): return key
    def start(self): pass
hotkey_listener.keyboard.Listener = FakeListener
from app.farming_interface import FarmingInterface
from tasks.tools.infinite_battle import InfiniteBattles
from module.config import cfg
app = QApplication(['hotkey-ui-test'])
gui_thread = threading.get_ident()
threads = []
class Probe(InfiniteBattles):
    def _on_stop_shortcut(self): threads.append(threading.get_ident())
farming = FarmingInterface()
manager = hotkey_listener.global_hotkeys
initial = len(manager._registrations)
tool = Probe()
assert len(manager._registrations) == initial + 1
assert len(FakeListener.instances) == 1
def press():
    keys = hotkey_listener.keyboard.HotKey.parse(cfg.shutdown_hotkey)
    for key in keys: manager._on_press(key)
    for key in reversed(keys): manager._on_release(key)
worker = threading.Thread(target=press)
worker.start()
worker.join(2)
app.processEvents()
assert threads == [gui_thread]
tool.close()
assert len(manager._registrations) == initial
farming._listener_stop()
farming._listener_start()
assert len(FakeListener.instances) == 1
farming.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
assert not manager._registrations
app.quit()
"""
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TMPDIR": str(data_path("tmp")),
                   "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")}
    result = subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT, env=environment,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, json.dumps({"stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False)
