"""Frontend replacement contracts, using isolated config and no game connection."""

import os
import subprocess
import sys

import pytest

from utils.runtime_paths import SOURCE_ROOT

BOOTSTRAP = """
import os
import module
module.CONFIG_PATH = os.environ['AALC_TEST_CONFIG_PATH']
from module.config import cfg
cfg.config = cfg.config.model_copy(update={'backend': 'playcover', 'default_page': 0,
    'auto_hard_mirror': False, 'keep_after_completion': False})
from module.hotkey_listener import global_hotkeys
from utils.schedule_helper import ScheduleHelper
global_hotkeys.register = lambda *_: 'ui-test'
global_hotkeys.unregister = lambda *_: None
ScheduleHelper.restore_daily_tasks = lambda *_: None
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from qfluentwidgets import Theme, setTheme
from app import mediator, task_check_box
from app.my_app import MainWindow
app = QApplication(['frontend-contract-test'])
window = MainWindow(['--smoke-test'])
window.resize(880, 600)
app.processEvents()
farming = window.farming_interface
left = farming.interface_left
center = farming.interface_center
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS frontend")
@pytest.mark.parametrize("scenario", ["bindings", "team_navigation", "layout", "language"])
def test_macos_frontend_contracts(tmp_path, scenario):
    scripts = {
        "language": """
from app.language_manager import LanguageManager
LanguageManager().set_language('en')
app.processEvents()
assert left.link_start_button.get_text() == 'Link Start!'
assert QPushButton.text(left.link_start_button.button) == 'Start'
assert window.screenshot_action.text() == 'Capture tool'
assert window.setting_interface.playcover_settings.test.text() == 'Test connection and capture'
assert left.mirror.box.check_box.text() == 'Mirror Dungeon'
assert window.setting_interface.playcover_group.titleLabel.text() == 'PlayCover connection'
assert window.setting_interface.setting_nav.nav_buttons['playcover'].text() == 'PlayCover'
LanguageManager().set_language('zh_cn')
app.processEvents()
assert QPushButton.text(left.link_start_button.button) == '开始运行'
assert left.mirror.box.check_box.text() == '镜牢任务'
assert window.setting_interface.playcover_group.titleLabel.text() == 'PlayCover 连接'
assert window.setting_interface.setting_nav.nav_buttons['playcover'].text() == 'PlayCover 连接'
""",
        "bindings": """
assert list(window.pivot.items) == ['farming_interface', 'setting_interface']
assert len(task_check_box) == 6  # Hidden anchors preserve original positional operations.
assert center.setting_page.currentIndex() == 1 and cfg.default_page == 0
assert left.set_windows.isHidden() and left.resonate_with_Ahab.isHidden()
assert left.link_start_button.get_text() == 'Link Start!'
assert QPushButton.text(left.link_start_button.button) == '开始运行'
spy = QSignalSpy(mediator.switch_page)
left.mirror.button.button.click()
assert spy.count() == 1 and cfg.default_page == 4
assert center.heading.text() == '镜牢任务'
assert center.setting_page.currentWidget() is center.mirror
combo = center.get_reward.set_get_prize.combo_box.combo_box
spy = QSignalSpy(combo.currentIndexChanged)
combo.setCurrentIndex(2)
assert spy.count() == 1 and cfg.set_get_prize == 2
center.daily_task.EXP_count.box.spin_box.setValue(2)
assert cfg.set_EXP_count == 2
left.select_all.be_click()
assert all(cfg.get_value(key) for key in ('daily_task', 'get_reward', 'buy_enkephalin', 'mirror'))
left.clear_all.be_click()
assert not any(cfg.get_value(key) for key in ('daily_task', 'get_reward', 'buy_enkephalin', 'mirror'))
left._disable_setting(farming)
assert not left.daily_task.box.check_box.isEnabled()
assert left.link_start_button.button.isEnabled()  # Still usable after moving into the footer.
left._enable_setting(farming)
assert left.daily_task.box.check_box.isEnabled()
""",
        "team_navigation": """
from app.team_setting_card import TeamSettingCard
window.add_and_switch_to_page('team1_setting')
app.processEvents()
assert window.pivot.currentRouteKey() == 'team_setting'
assert list(window.pivot.items)[-1] == 'team_setting'
assert left.parent().parent().findChild(TeamSettingCard) is not None
window.close_setting_page()
app.processEvents()
assert list(window.pivot.items) == ['farming_interface', 'setting_interface']
assert window.stackedWidget.currentWidget() is farming
""",
        "layout": """
for theme in (Theme.LIGHT, Theme.DARK):
    setTheme(theme)
    for width, height in ((880, 600), (760, 540)):
        window.resize(width, height)
        window.pivot.setCurrentItem('farming_interface')
        app.processEvents()
        button = left.link_start_button.button
        bounds = button.rect().translated(button.mapTo(window, QPoint(0, 0)))
        assert window.rect().contains(bounds), (width, height, bounds)
        assert button.height() >= button.fontMetrics().height()
        for task in ('daily_task', 'get_reward', 'buy_enkephalin', 'mirror'):
            getattr(left, task).button.button.click()
            app.processEvents()
            assert center.setting_page.currentWidget().all_page.height() > 60
        window.pivot.setCurrentItem('setting_interface')
        QTest.qWait(100)
        for card in window.setting_interface.findChildren(QWidget):
            if not hasattr(card, 'titleLabel') or not hasattr(card, 'contentLabel'):
                continue
            if not card.isVisibleTo(window.setting_interface):
                continue
            for label in (card.titleLabel, card.contentLabel):
                if not label.isHidden() and label.wordWrap():
                    needed = label.heightForWidth(label.width())
                    assert label.height() >= needed, (label.text(), label.height(), needed)
""",
    }
    result = subprocess.run(
        [sys.executable, "-c", BOOTSTRAP + scripts[scenario] + "\nwindow.on_tray_quit()\napp.processEvents()\n"],
        cwd=SOURCE_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "AALC_TEST_CONFIG_PATH": str(tmp_path / "config.yaml")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
