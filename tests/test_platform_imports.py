import os
import subprocess
import sys

from utils.runtime_paths import SOURCE_ROOT, data_path


def test_transport_import_is_independent_of_gui_ocr_and_config(tmp_path):
    script = """
import sys
from module.backends.playcover.transport import PlayCoverTransport
assert not any(name.startswith(('PySide6', 'rapidocr', 'module.config', 'module.automation.automation')) for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                   env={**os.environ, "PYTHONPATH": str(SOURCE_ROOT)}, check=True)


def test_public_automation_import_does_not_load_windows_implementations(tmp_path):
    script = """
import sys, os
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
cfg.config = cfg.config.model_copy(update={'backend': 'playcover', 'game_profile': 'ios_en', 'set_win_size': 1080, 'simulator': False})
from module.automation.automation import Automation
from tasks.common.game_actions import GameActions
from module.game_and_screen import screen
assert not any(name.startswith(('win32', 'pywintypes', 'winreg', 'windows_toasts')) for name in sys.modules)
"""
    # Test the target backend on every runner; Windows native import is tested by legacy tests.
    env = {**os.environ, "TMPDIR": str(data_path("tmp")), "QT_QPA_PLATFORM": "offscreen", "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")}
    subprocess.run([sys.executable, "-c", script], cwd=SOURCE_ROOT, env=env, check=True)
