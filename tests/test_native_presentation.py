"""Presentation regressions using native controls, without a host or game session."""

# AppKit-dependent imports must follow the optional framework check.
# ruff: noqa: E402

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

A = pytest.importorskip("AppKit")

from Foundation import NSDate, NSRunLoop

from frontend_appkit import widgets
from frontend_appkit.application import PAGE_KEYS, Application, Delegate
from frontend_appkit.forms import Form
from frontend_appkit.presentation import segmented
from frontend_appkit.widgets import FlippedView, button, label
from native_contract import GROUPS, TASK_KEYS


@pytest.fixture(autouse=True)
def native_application():
    # Initialize Cocoa only; Application.__init__ never starts a backend here.
    A.NSApplication.sharedApplication()


def view():
    return FlippedView.alloc().initWithFrame_(((0, 0), (720, 400)))


def navigation_app():
    app = Application.__new__(Application)
    app.targets = []
    app.navigation = segmented(None, ["任务", "工具"], ((0, 0), (144, 30)), lambda _: None, app.targets)
    app.settings_button = button(view(), "设置", ((0, 0), (44, 32)), lambda _: None, app.targets)
    app.section_navigation = segmented(None, ["常规", "队伍", "主题包", "高级"], ((0, 0), (400, 30)), lambda _: None, app.targets)
    app.settings_navigation = segmented(None, ["游戏", "定时", "外观", "运行", "资源"], ((0, 0), (500, 30)), lambda _: None, app.targets)
    app.task_detail_navigation = segmented(None, ["常规", "高级"], ((0, 0), (200, 30)), lambda _: None, app.targets)
    app.task_rows = [view() for _ in TASK_KEYS]
    app.page_index = app.last_task_page = app.mirror_section = app.settings_section = 0
    app.task_details = {0: 0, 2: 0}
    app.settings_details = {}
    app.layout_window = Mock()
    app.build_page = Mock()
    app.window = Mock()
    app.client = Mock()
    app.error = Mock()
    app.data = {"config": {"set_EXP_count": 1, "language_in_program": "zh_cn"}}
    app.forms = []
    return app


@pytest.mark.parametrize("destination", ["primary", "task_detail"])
def test_invalid_number_restores_navigation_and_keeps_current_page(destination):
    app = navigation_app()
    form = Form(view(), app.data["config"], ["set_EXP_count"], app.targets, lambda *_: None)
    app.forms = [form]
    form.controls["set_EXP_count"].setStringValue_("")

    if destination == "primary":
        app.navigation.setSelectedSegment_(1)
        app.select_primary(1)
    else:
        app.task_detail_navigation.setSelectedSegment_(1)
        app.select_task_detail(1)

    assert app.page_index == 0 and app.task_details[0] == 0
    assert app.navigation.selectedSegment() == 0
    assert app.task_detail_navigation.selectedSegment() == 0
    assert form.controls["set_EXP_count"].stringValue() == ""
    app.window.makeFirstResponder_.assert_called_once_with(None)
    app.error.assert_called_once()
    app.client.request.assert_not_called()
    app.build_page.assert_not_called()


def test_old_page_numbers_restore_the_correct_navigation_hierarchy():
    assert PAGE_KEYS == ["daily", "reward", "energy", "mirror", "teams", "theme", "settings", "tools"]
    app = navigation_app()
    for page, primary, mirror in [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 1), (5, 0, 2), (6, -1, 0), (7, 1, 0)]:
        app.page_index, app.mirror_section = page, 0
        app.sync_navigation()
        assert app.navigation.selectedSegment() == primary
        assert app.section_navigation.selectedSegment() == mirror
        assert [bool(row.selected) for row in app.task_rows] == [page == i or (i == 3 and page in {4, 5}) for i in range(4)]

    app.page_index, app.mirror_section = 3, 3
    app.sync_navigation()
    assert app.section_navigation.selectedSegment() == 3


@pytest.mark.parametrize("section,page", [(0, 3), (1, 4), (2, 5), (3, 3)])
def test_mirror_subpages_keep_original_persisted_page_numbers(section, page):
    app = navigation_app()
    app.select_mirror_section(section)
    assert app.page_index == page and app.mirror_section == section
    app.client.request.assert_called_once_with("config.patch", {"values": {"default_page": page}})
    app.build_page.assert_called_once()


def test_language_refresh_preserves_expanded_log_and_updates_dynamic_titles(monkeypatch):
    app = navigation_app()
    app.root = view()
    app.sidebar_content = view()
    app.log_toggle = button(app.root, "运行日志 ▸", ((0, 40), (140, 30)), lambda _: None, app.targets)
    app.page_heading = label(app.root, "设置", ((0, 80), (500, 30)))
    app.page_description = label(app.root, "游戏连接、定时任务与应用偏好", ((0, 120), (500, 30)))
    app.page_heading.setIdentifier_(None)
    app.page_description.setIdentifier_(None)
    app.page_title = ("设置", "游戏连接、定时任务与应用偏好")
    app.logs_expanded = True
    app.editors = []
    app.tray_menu = A.NSMenu.alloc().init()
    app.native = SimpleNamespace(mainMenu=lambda: A.NSMenu.alloc().init())
    app.translations = {"设置": "Settings", "游戏连接、定时任务与应用偏好": "Game connection, schedules and preferences", "运行日志": "Run log"}
    monkeypatch.setattr(widgets, "translate", app.text)

    for language, heading, description, log in [("en", "Settings", app.translations[app.page_title[1]], "Run log ▾"), ("zh_cn", app.page_title[0], app.page_title[1], "运行日志 ▾")]:
        app.data["config"]["language_in_program"] = language
        app.refresh_language()
        assert app.page_heading.stringValue() == heading
        assert app.page_description.stringValue() == description
        assert app.logs_expanded
        assert app.log_toggle.title() == log


def test_running_state_disables_nested_actions_and_completion_but_keeps_general_settings():
    app = navigation_app()
    config = {**dict.fromkeys(TASK_KEYS, False), "language_in_program": "zh_cn", "set_EXP_count": 1, "set_thread_count": 2, "set_get_prize": 0, "set_lunacy_to_enkephalin": 1, "set_mirror_count": 2, "theme_mode": "AUTO", "teams_active_queue": [1], "floor_3_exit": False, "hard_mirror_chance": 2, "after_completion_actions": ["exit_game"], "keep_after_completion": False}
    state = {"running": True, "stopping": False, "startup": False, "kind": "task", "paused": False, "queued": 0}
    app.data = {"config": config, "state": state, "version": "test"}
    app.page_index, app.mirror_section = 3, 3
    app.page = view()
    app.completion_root = view()
    nested = view()
    app.page.addSubview_(nested)
    nested_action = button(nested, "编辑", ((0, 0), (80, 30)), lambda _: None, app.targets)
    inactive_order = button(nested, "上移", ((0, 40), (80, 30)), lambda _: None, app.targets)
    app.team_order_controls = [(inactive_order, 2)]
    task_form = Form(app.page, config, ["floor_3_exit", "hard_mirror_chance"], app.targets, lambda *_: None)
    completion = Form(app.completion_root, config, GROUPS["completion"], app.targets, lambda *_: None)
    app.forms = [task_form, completion]
    app.start_button = button(view(), "开始", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.pause_button = button(view(), "暂停", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.status = label(view(), "", ((0, 0), (300, 30)))
    app.task_buttons = [button(view(), "", ((0, 0), (30, 30)), lambda _: None, app.targets, checkbox=True) for _ in TASK_KEYS]
    app.select_all_button = button(view(), "全选", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.clear_tasks_button = button(view(), "清空", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.task_summaries = [label(view(), "", ((0, 0), (300, 30))) for _ in TASK_KEYS]
    app.native = Mock()
    completion_controls = completion.controls["after_completion_actions"] + [completion.controls["keep_after_completion"]]

    app.update_state()
    assert not nested_action.isEnabled() and not inactive_order.isEnabled()
    assert not task_form.controls["floor_3_exit"].isEnabled()
    assert task_form.controls["hard_mirror_chance"].isEnabled()
    assert all(not control.isEnabled() for control in completion_controls)
    assert app.start_button.isEnabled() and app.pause_button.isEnabled()

    state["stopping"] = True
    app.update_state()
    assert not app.start_button.isEnabled() and not app.pause_button.isEnabled()

    state.update(running=False, stopping=False, kind="")
    app.update_state()
    assert nested_action.isEnabled() and not inactive_order.isEnabled()
    assert task_form.controls["floor_3_exit"].isEnabled()
    assert all(control.isEnabled() for control in completion_controls)
    assert completion.values() == {"after_completion_actions": ["exit_game"], "keep_after_completion": False}


def test_installed_toolbar_preserves_control_size_hit_targets_and_actions():
    app = Application.__new__(Application)
    app.targets = []
    app.data = None
    app.page_index = 6
    app.logs_expanded = False
    app.client = Mock()
    app.select_primary = Mock()
    app.select_page = Mock()
    app.start_or_stop = Mock()
    app.native = A.NSApplication.sharedApplication()
    app.delegate = Delegate.alloc().init()
    app.delegate.owner = app
    # Build the actual production toolbar, not a copy of its item setup.
    app.build_window()
    try:
        for width in (860, 1200):
            app.window.setFrame_display_(((100, 100), (width, 580)), True)
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
            frame = app.window.contentView().superview()
            frame.layoutSubtreeIfNeeded()
            app.select_primary.reset_mock()
            app.select_page.reset_mock()
            app.start_or_stop.reset_mock()
            app.client.request.reset_mock()

            def hit(control, point):
                window_point = control.convertPoint_toView_(point, None)
                return frame.hitTest_(frame.convertPoint_fromView_(window_point, None))

            controls = {"navigation": (app.navigation, (144, 30)), "pause": (app.pause_button, (44, 32)), "start": (app.start_button, (44, 32)), "settings": (app.settings_button, (44, 32))}
            for identifier, (control, expected_size) in controls.items():
                wrapper = app.toolbar_items[identifier].view()
                assert wrapper.window() == app.window, f"{identifier} disappeared at window width {width}"
                assert control.frame().size.width > 0 and control.frame().size.height > 0
                if hasattr(A, "NSGlassEffectView"):
                    if isinstance(control, A.NSButton):
                        # Native glass artwork adds alignment insets. Verify a
                        # compact, usable target rather than private art sizes.
                        assert wrapper == control and control.isBordered()
                        assert control.bezelStyle() == getattr(A, "NSBezelStyleGlass", 16)
                        assert 44 <= control.bounds().size.width <= 80
                        assert 28 <= control.bounds().size.height <= 48
                    else:
                        assert tuple(control.frame().size) == pytest.approx(expected_size)
                        assert tuple(wrapper.frame().size) == pytest.approx((expected_size[0] + 16, 36))

            x = 0
            for index in range(app.navigation.segmentCount()):
                segment_width = app.navigation.widthForSegment_(index)
                assert hit(app.navigation, (x + segment_width / 2, app.navigation.bounds().size.height / 2)) == app.navigation
                app.navigation.setSelectedSegment_(index)
                assert app.native.sendAction_to_from_(app.navigation.action(), app.navigation.target(), app.navigation)
                app.select_primary.assert_called_with(index)
                x += segment_width

            for control in (app.pause_button, app.start_button, app.settings_button):
                size = control.bounds().size
                assert hit(control, (size.width / 2, size.height / 2)) == control
                assert app.native.sendAction_to_from_(control.action(), control.target(), control)
            app.client.request.assert_called_once_with("task.pause")
            app.start_or_stop.assert_called_once_with()
            app.select_page.assert_called_once_with(6)
    finally:
        app.window.orderOut_(None)
        app.window.setDelegate_(None)
        app.window.close()
