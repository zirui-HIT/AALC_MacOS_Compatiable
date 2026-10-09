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
    assert log.font().pixelSize() >= 16
    assert log.document().firstBlock().blockFormat().lineHeight() == 135
    assert window.pivot.currentItem().font().pixelSize() >= 16
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
