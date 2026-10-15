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
from frontend_appkit.presentation import TOOLBAR_HEIGHT, TOOLBAR_PADDING, TOOLBAR_SLOT_WIDTH, segmented
from frontend_appkit.widgets import FlippedView, button, label
from native_contract import GROUPS, TASK_KEYS, validate_fields


@pytest.fixture(autouse=True)
def native_application():
    # Initialize Cocoa only; Application.__init__ never starts a backend here.
    A.NSApplication.sharedApplication()


def view():
    return FlippedView.alloc().initWithFrame_(((0, 0), (720, 400)))


def navigation_app():
    app = Application.__new__(Application)
    app.targets = []
    app.navigation = segmented(None, ["任务", "工具", "设置"], ((0, 0), (3 * TOOLBAR_SLOT_WIDTH, 30)), lambda _: None, app.targets)
    app.run_controls = view()
    app.section_navigation = segmented(None, ["常规", "队伍", "主题包", "高级"], ((0, 0), (400, 30)), lambda _: None, app.targets)
    app.settings_navigation = segmented(None, ["游戏", "定时", "外观", "运行", "资源"], ((0, 0), (500, 30)), lambda _: None, app.targets)
    app.task_detail_navigation = segmented(None, ["常规", "高级"], ((0, 0), (200, 30)), lambda _: None, app.targets)
    app.task_rows = [view() for _ in TASK_KEYS]
    app.page_index = app.last_task_page = app.mirror_section = app.settings_section = 0
    app.task_details = {0: 0, 2: 0}
    app.settings_details = {}
    app.expanded_schedules = set()
    app.expanded_daily = set()
    app.layout_window = Mock()
    app.build_page = Mock()
    app.window = Mock()
    app.client = Mock()
    app.error = Mock()
    app.data = {"config": {"set_EXP_count": 1, "language_in_program": "zh_cn"}}
    app.forms = []
    return app


@pytest.mark.parametrize("destination", ["primary", "settings", "task_detail"])
def test_invalid_number_restores_navigation_and_keeps_current_page(destination):
    app = navigation_app()
    form = Form(view(), app.data["config"], ["set_EXP_count"], app.targets, lambda *_: None)
    app.forms = [form]
    form.controls["set_EXP_count"].setStringValue_("")

    if destination in {"primary", "settings"}:
        index = 2 if destination == "settings" else 1
        app.navigation.setSelectedSegment_(index)
        app.select_primary(index)
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
    for page, primary, mirror in [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 1), (5, 0, 2), (6, 2, 0), (7, 1, 0)]:
        app.page_index, app.mirror_section = page, 0
        app.sync_navigation()
        assert app.navigation.selectedSegment() == primary
        assert app.section_navigation.selectedSegment() == mirror
        assert [bool(row.selected) for row in app.task_rows] == [page == i or (i == 3 and page in {4, 5}) for i in range(4)]

    app.page_index, app.mirror_section = 3, 3
    app.sync_navigation()
    assert app.section_navigation.selectedSegment() == 3


@pytest.mark.parametrize("primary,page", [(0, 4), (1, 7), (2, 6)])
def test_primary_navigation_reuses_existing_pages_and_remembers_task_detail(primary, page):
    app = navigation_app()
    app.last_task_page = 4
    app.select_primary(primary)
    assert app.page_index == page
    app.client.request.assert_called_once_with("config.patch", {"values": {"default_page": page}})
    app.build_page.assert_called_once()


def schedule_app():
    app = navigation_app()
    app.page_index, app.settings_section = 6, 1
    app.page = view()
    app.root = view()
    app.root.addSubview_(app.page)
    app.page_targets = []
    for suffix in ("", "2", "3", "4"):
        app.data["config"].update({
            "autodaily" + suffix: False, "autodaily_time" + suffix: "08:00",
            "autodaily" + suffix + "_task": [True, False, True, False],
            "autodaily" + suffix + "_task_exit": [True, False, False, False, False, False, False],
        })

    def request(method, params, callback=None, on_error=None):
        assert method == "config.patch"
        validate_fields(params["values"])
        app.data["config"].update(params["values"])
        if callback:
            callback({})

    def rebuild():
        for child in list(app.page.subviews()):
            child.removeFromSuperview()
        app.forms, app.page_targets = [], []
        app.build_settings()

    app.client.request.side_effect = request
    app.build_page.side_effect = rebuild
    rebuild()
    return app


@pytest.mark.parametrize("language", ["zh_cn", "en"])
def test_collapsed_schedules_keep_enable_checkbox_independent_of_disclosure(monkeypatch, language):
    app = schedule_app()
    translations = {f"定时任务 {number}": f"Schedule {number}" for number in range(1, 5)}
    translations.update({f"启用定时任务 {number}": f"Enable schedule {number}" for number in range(1, 5)})
    monkeypatch.setattr(widgets, "translate", lambda text: translations.get(text, text) if language == "en" else text)
    widgets.refresh(app.page)
    assert len(app.forms) == 4
    for form, suffix in zip(app.forms, ("", "2", "3", "4")):
        key = "autodaily" + suffix
        assert set(form.getters) == {key}
        enabled = form.controls[key]
        row = enabled.superview()
        disclosure = next(control for control in row.subviews() if isinstance(control, A.NSButton) and control is not enabled)
        assert disclosure.title() == (f"Schedule {suffix or '1'}" if language == "en" else f"定时任务 {suffix or '1'}")
        assert enabled.accessibilityLabel() == (f"Enable schedule {suffix or '1'}" if language == "en" else f"启用定时任务 {suffix or '1'}")
        assert app.page.hitTest_(row.convertPoint_toView_((26, 22), app.page)) == enabled
        assert app.page.hitTest_(row.convertPoint_toView_((120, 22), app.page)) == disclosure
        enabled.performClick_(None)
        assert app.data["config"][key] is True
        assert not app.expanded_schedules
        assert enabled.isEnabled()
    assert app.client.request.call_count == 4
    app.build_page.assert_not_called()


def test_schedule_collapse_commits_pending_fields_and_keeps_other_slots_collapsed():
    app = schedule_app()
    app.toggle_group(app.expanded_schedules, "2")
    assert app.expanded_schedules == {"2"}
    assert [set(form.getters) for form in app.forms] == [{"autodaily"}, set(GROUPS["schedule2"]), {"autodaily3"}, {"autodaily4"}]
    app.forms[1].controls["autodaily_time2"].setStringValue_("20:30")
    app.toggle_group(app.expanded_schedules, "2")
    assert not app.expanded_schedules
    assert app.data["config"]["autodaily_time2"] == "20:30"
    app.client.request.assert_called_once()
    assert app.client.request.call_args.args[:2] == ("config.patch", {"values": {"autodaily_time2": "20:30"}})
    app.toggle_group(app.expanded_schedules, "2")
    assert app.forms[1].controls["autodaily_time2"].stringValue() == "20:30"


def test_invalid_schedule_time_keeps_expanded_form_and_unsaved_input():
    app = schedule_app()
    app.toggle_group(app.expanded_schedules, "")
    form = app.forms[0]
    form.controls["autodaily_time"].setStringValue_("25:99")
    app.build_page.reset_mock()
    app.toggle_group(app.expanded_schedules, "")
    assert app.expanded_schedules == {""}
    assert app.forms[0] is form
    assert form.controls["autodaily_time"].stringValue() == "25:99"
    assert app.data["config"]["autodaily_time"] == "08:00"
    app.error.assert_called_once()
    app.build_page.assert_not_called()


def content_app(page_index):
    app = schedule_app()
    app.data["config"].update({
        "set_thread_count": 1, "daily_teams": 1, "use_continuous_combat": True,
        "use_continuous_combat_select": 2, "targeted_teaming_EXP": False,
        "targeted_teaming_thread": False, "memory_protection": True,
        "experimental_keep_screen_awake": False, "task_stall_timeout": 90, "after_completion_actions": ["exit_game"],
        "keep_after_completion": False,
        **dict.fromkeys(GROUPS["daily"][6:10] + GROUPS["daily"][11:], 1),
    })
    app.page_index, app.settings_section = page_index, 3
    app.task_details[0] = 1
    app.page_heading = label(app.root, "", ((0, 0), (600, 24)))
    app.page_description = label(app.root, "", ((0, 0), (600, 24)))
    app.sync_navigation = Mock()
    app.update_state = Mock()
    app.build_page.side_effect = lambda: Application.build_page(app)
    app.build_page()
    return app


@pytest.mark.parametrize("group,enabled_key,field,index", [
    ("EXP", "targeted_teaming_EXP", "EXP_day_1_2", 0),
    ("thread", "targeted_teaming_thread", "thread_day_1", 1),
])
def test_daily_date_groups_fold_independently_and_commit_pending_team(group, enabled_key, field, index):
    app = content_app(0)
    assert [set(form.getters) for form in app.forms] == [{"targeted_teaming_EXP"}, {"targeted_teaming_thread"}]
    enabled = app.forms[index].controls[enabled_key]
    enabled.performClick_(None)
    assert app.data["config"][enabled_key] is True
    assert not app.expanded_daily
    disclosure = next(control for control in enabled.superview().subviews() if isinstance(control, A.NSButton) and control is not enabled)
    disclosure.performClick_(None)
    assert app.expanded_daily == {group}
    assert set(app.forms[index].getters) == set(GROUPS["daily"][5:10] if group == "EXP" else GROUPS["daily"][10:])
    assert len(app.forms[1 - index].getters) == 1
    app.forms[index].controls[field].setStringValue_("4")
    app.toggle_group(app.expanded_daily, group)
    assert not app.expanded_daily
    assert app.data["config"][field] == 4
    assert app.data["config"][enabled_key] is True
    app.toggle_group(app.expanded_daily, group)
    assert app.forms[index].controls[field].stringValue() == "4"
    app.error.assert_not_called()


def test_completion_settings_live_in_runtime_settings_and_keep_existing_config_fields():
    app = content_app(0)
    assert not any(set(GROUPS["completion"]) & form.getters.keys() for form in app.forms)
    assert not hasattr(app, "completion_root")
    app.page_index = 6
    app.build_page()
    completion = next(form for form in app.forms if set(form.getters) == {"after_completion_actions"})
    assert any(isinstance(control, A.NSTextField) and control.stringValue() == "完成后" for control in app.page.subviews())
    assert not any("keep_after_completion" in form.controls for form in app.forms)
    completion.controls["after_completion_actions"][1].performClick_(None)
    assert app.data["config"]["keep_after_completion"] is True
    assert app.data["config"]["after_completion_actions"] == ["exit_game", "exit_aalc"]
    app.data["config"]["keep_after_completion"] = False
    completion.controls["after_completion_actions"][0].setState_(False)
    committed = Mock()
    app.commit_current(committed)
    committed.assert_called_once_with()
    assert app.data["config"]["keep_after_completion"] is True
    assert app.data["config"]["after_completion_actions"] == ["exit_aalc"]
    app.error.assert_not_called()


def test_runtime_timeout_uses_integer_form_and_existing_save_navigation():
    app = content_app(6)
    form = next(form for form in app.forms if "task_stall_timeout" in form.controls)
    control = form.controls["task_stall_timeout"]
    assert not control.formatter().allowsFloats()
    assert control.stringValue() == "90"
    assert control.toolTip() == "超时卡死时间设置，低性能PC/模拟器可设置更高"
    control.setStringValue_("600")
    form.changed("task_stall_timeout")
    assert app.data["config"]["task_stall_timeout"] == 600
    assert app.client.request.call_args.args[:2] == ("config.patch", {"values": {"task_stall_timeout": 600}})
    app.select_settings_detail(True)
    app.select_settings_detail(False)
    form = next(form for form in app.forms if "task_stall_timeout" in form.controls)
    assert form.controls["task_stall_timeout"].stringValue() == "600"
    app.error.assert_not_called()


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
    app.translations = {"任务": "Tasks", "工具": "Tools", "设置": "Settings", "游戏连接、定时任务与应用偏好": "Game connection, schedules and preferences", "运行日志": "Run log"}
    monkeypatch.setattr(widgets, "translate", app.text)

    for language, heading, description, log in [("en", "Settings", app.translations[app.page_title[1]], "Run log ▾"), ("zh_cn", app.page_title[0], app.page_title[1], "运行日志 ▾")]:
        app.data["config"]["language_in_program"] = language
        app.refresh_language()
        assert app.page_heading.stringValue() == heading
        assert app.page_description.stringValue() == description
        assert app.logs_expanded
        assert app.log_toggle.title() == log
        assert [app.navigation.labelForSegment_(index) for index in range(3)] == (["Tasks", "Tools", "Settings"] if language == "en" else ["任务", "工具", "设置"])


def test_running_state_disables_nested_actions_and_completion_but_keeps_general_settings():
    app = navigation_app()
    config = {**dict.fromkeys(TASK_KEYS, False), "language_in_program": "zh_cn", "set_EXP_count": 1, "set_thread_count": 2, "set_get_prize": 0, "set_lunacy_to_enkephalin": 1, "set_mirror_count": 2, "theme_mode": "AUTO", "teams_active_queue": [1], "floor_3_exit": False, "hard_mirror_chance": 2, "after_completion_actions": ["exit_game"], "keep_after_completion": False}
    state = {"running": True, "stopping": False, "startup": False, "kind": "task", "paused": False, "queued": 0}
    app.data = {"config": config, "state": state, "version": "test"}
    app.page_index, app.mirror_section = 3, 3
    app.page = view()
    nested = view()
    app.page.addSubview_(nested)
    nested_action = button(nested, "编辑", ((0, 0), (80, 30)), lambda _: None, app.targets)
    inactive_order = button(nested, "上移", ((0, 40), (80, 30)), lambda _: None, app.targets)
    app.team_order_controls = [(inactive_order, 2)]
    task_form = Form(app.page, config, ["floor_3_exit", "hard_mirror_chance"], app.targets, lambda *_: None)
    completion = Form(app.page, config, ["after_completion_actions"], app.targets, lambda *_: None)
    app.forms = [task_form, completion]
    app.start_button = button(view(), "开始", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.pause_button = button(view(), "暂停", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.status = label(view(), "", ((0, 0), (300, 30)))
    app.task_buttons = [button(view(), "", ((0, 0), (30, 30)), lambda _: None, app.targets, checkbox=True) for _ in TASK_KEYS]
    app.select_all_button = button(view(), "全选", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.clear_tasks_button = button(view(), "清空", ((0, 0), (80, 30)), lambda _: None, app.targets)
    app.task_summaries = [label(view(), "", ((0, 0), (300, 30))) for _ in TASK_KEYS]
    app.native = Mock()
    completion_controls = completion.controls["after_completion_actions"]

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
    assert completion.values() == {"after_completion_actions": ["exit_game"]}
    app.page_index = 6
    state.update(running=True, kind="task")
    app.update_state()
    assert all(not control.isEnabled() for control in completion_controls)


@pytest.mark.parametrize("appearance", [A.NSAppearanceNameAqua, A.NSAppearanceNameDarkAqua])
@pytest.mark.parametrize("language", ["zh_cn", "en"])
def test_installed_toolbar_preserves_control_size_hit_targets_and_actions(monkeypatch, appearance, language):
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
    previous_appearance = app.native.appearance()
    app.native.setAppearance_(A.NSAppearance.appearanceNamed_(appearance))
    translations = {"任务": "Tasks", "工具": "Tools", "设置": "Settings"} if language == "en" else {}
    monkeypatch.setattr(widgets, "translate", lambda text: translations.get(text, text))
    app.delegate = Delegate.alloc().init()
    app.delegate.owner = app
    # Build the actual production toolbar, not a copy of its item setup.
    app.build_window()
    try:
        assert set(app.toolbar_items) == {"navigation", "run"}
        assert app.navigation.segmentCount() == 3
        assert not hasattr(app, "settings_button")
        assert not hasattr(app, "completion_root")
        for width in (860, 1200):
            app.window.setFrame_display_(((100, 100), (width, 580)), True)
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
            frame = app.window.contentView().superview()
            frame.layoutSubtreeIfNeeded()
            app.page_index = 0
            app.layout_window()
            assert app.page_scroll.frame().origin.y + app.page_scroll.frame().size.height == pytest.approx(app.log_toggle.frame().origin.y - 8)
            app.page_index = 6
            app.layout_window()
            app.select_primary.reset_mock()
            app.select_page.reset_mock()
            app.start_or_stop.reset_mock()
            app.client.request.reset_mock()

            def hit(control, point):
                window_point = control.convertPoint_toView_(point, None)
                return frame.hitTest_(frame.convertPoint_fromView_(window_point, None))

            controls = {"navigation": app.navigation, "run": app.run_controls}
            for identifier, control in controls.items():
                wrapper = app.toolbar_items[identifier].view()
                assert wrapper.window() == app.window, f"{identifier} disappeared at window width {width}"
                assert control.frame().size.width == pytest.approx(3 * TOOLBAR_SLOT_WIDTH)
                assert tuple(wrapper.frame().size) == pytest.approx((3 * TOOLBAR_SLOT_WIDTH + 2 * TOOLBAR_PADDING, TOOLBAR_HEIGHT))

            centers = []
            for control in (app.status, app.pause_button, app.start_button):
                bounds = control.bounds()
                centers.append(control.convertPoint_toView_((bounds.size.width / 2, bounds.size.height / 2), app.run_controls))
            assert [point.x for point in centers] == pytest.approx([(index + 0.5) * app.navigation.widthForSegment_(index) for index in range(3)])
            assert [point.y for point in centers] == pytest.approx([TOOLBAR_HEIGHT / 2] * 3)
            for status in ("就绪", "停止中… · 排队 12", "Stopping… · Queue 12"):
                app.status.setStringValue_(status)
                frame.layoutSubtreeIfNeeded()
                assert app.status.frame().size.height == pytest.approx(app.status.attributedStringValue().size().height)
                assert app.status.cell().drawingRectForBounds_(app.status.bounds()).size.height == pytest.approx(app.status.attributedStringValue().size().height)
                assert [control.frame().origin.x for control in (app.pause_button, app.start_button)] == pytest.approx([TOOLBAR_SLOT_WIDTH + (TOOLBAR_SLOT_WIDTH - 44) / 2, 2 * TOOLBAR_SLOT_WIDTH + (TOOLBAR_SLOT_WIDTH - 44) / 2])

            x = 0
            for index in range(app.navigation.segmentCount()):
                segment_width = app.navigation.widthForSegment_(index)
                assert hit(app.navigation, (x + segment_width / 2, app.navigation.bounds().size.height / 2)) == app.navigation
                app.navigation.setSelectedSegment_(index)
                assert app.native.sendAction_to_from_(app.navigation.action(), app.navigation.target(), app.navigation)
                app.select_primary.assert_called_with(index)
                x += segment_width

            for control in (app.pause_button, app.start_button):
                size = control.bounds().size
                assert hit(control, (size.width / 2, size.height / 2)) == control
                assert app.native.sendAction_to_from_(control.action(), control.target(), control)
            app.client.request.assert_called_once_with("task.pause")
            app.start_or_stop.assert_called_once_with()
            app.select_page.assert_not_called()
    finally:
        app.window.orderOut_(None)
        app.window.setDelegate_(None)
        app.window.close()
        app.native.setAppearance_(previous_appearance)
