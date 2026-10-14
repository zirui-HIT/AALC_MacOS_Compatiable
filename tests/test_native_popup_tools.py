"""Native popup, announcement and resizing regressions without game input."""

# Framework imports follow the optional AppKit check.
# ruff: noqa: E402

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

A = pytest.importorskip("AppKit")
from PIL import Image

from frontend_appkit.application import Application, Delegate
from frontend_appkit.presentation import announcement_html
from frontend_appkit.widgets import FlippedView, attributed_html
from native_contract import TASK_KEYS
from tests.test_native_presentation import content_app


@pytest.fixture(autouse=True)
def cocoa():
    A.NSApplication.sharedApplication()


@pytest.fixture
def tool_app():
    app = Application.__new__(Application)
    app.data = {"config": {**dict.fromkeys(TASK_KEYS, False), "language_in_program": "zh_cn",
        "set_EXP_count": 1, "set_thread_count": 1, "set_get_prize": 0, "set_lunacy_to_enkephalin": 1,
        "set_mirror_count": 1, "theme_mode": "AUTO"},
        "state": {"running": False, "kind": None, "stopping": False, "startup": False, "paused": False, "queued": 0}, "version": "test"}
    app.editors, app.forms, app.task_buttons, app.task_summaries, app.team_order_controls = [], [], [], [], []
    app.page_index = 7
    app.page = FlippedView.alloc().initWithFrame_(((0, 0), (760, 500)))
    app.page_targets = []
    app.client, app.window, app.native = Mock(), Mock(), Mock()
    app.start_button, app.pause_button, app.status = Mock(), Mock(), Mock()
    app.start_button.title.return_value = "开始运行"
    app.pause_button.title.return_value = "暂停"
    app.select_all_button, app.clear_tasks_button = Mock(), Mock()
    yield app
    for editor in list(app.editors):
        editor.close()


def test_tool_launchers_open_reused_popups_without_starting_game_work(tool_app):
    tool_app.build_tools()
    launchers = [control for row in tool_app.page.subviews() for control in row.subviews() if isinstance(control, A.NSButton)]
    assert len(launchers) == 2
    assert not any(isinstance(control, A.NSButton) for control in tool_app.page.subviews())
    for launcher in launchers:
        launcher.performClick_(None)
    assert {editor.tool_kind for editor in tool_app.editors} == {"battle", "capture"}
    tool_app.client.request.assert_not_called()
    for editor in list(tool_app.editors):
        assert tool_app.open_tool(editor.tool_kind) is editor
    assert len(tool_app.editors) == 2


def test_battle_popup_keeps_original_options_and_can_stop_its_worker(tool_app):
    editor = tool_app.open_tool("battle")
    options = [control for control in editor.root.subviews() if isinstance(control, A.NSButton) and control is not editor.start_button]
    assert len(options) == 3
    options[0].setState_(True)
    options[2].setState_(True)
    editor.start_button.performClick_(None)
    tool_app.client.request.assert_called_once_with("battle.start", {"defense": True, "defense_on_turn1": False, "not_choose_event": True})
    tool_app.data["state"].update(running=True, kind="battle")
    tool_app.update_state()
    assert all(not control.isEnabled() for control in options)
    assert editor.start_button.isEnabled() and editor.start_button.title() == "停止任务"
    editor.start_button.performClick_(None)
    assert tool_app.client.request.call_args.args == ("task.stop",)
    tool_app.data["state"]["stopping"] = True
    tool_app.update_state()
    assert not editor.start_button.isEnabled()
    tool_app.data["state"].update(stopping=False, kind="task")
    tool_app.update_state()
    assert not editor.start_button.isEnabled()


def test_capture_popup_reuses_preview_and_resizes_with_window(tool_app, tmp_path):
    editor = tool_app.open_tool("capture")
    capture = next(control for control in editor.root.subviews() if isinstance(control, A.NSButton))
    capture.performClick_(None)
    tool_app.client.request.assert_called_once_with("screenshot")
    path = tmp_path / "capture.png"
    Image.new("RGB", (64, 32), "white").save(path)
    tool_app.show_capture({"path": str(path), "bundle_id": "test.bundle"})
    assert len(tool_app.editors) == 1
    assert tuple(editor.image_view.image().size()) == (64, 32)
    assert editor.placeholder.isHidden()
    assert editor.bundle_label.stringValue() == "test.bundle"
    editor.window.setContentSize_((920, 660))
    assert tuple(editor.image_view.frame().size) == (880, 576)
    editor.close()
    replacement = tool_app.open_tool("capture")
    assert replacement is not editor and replacement.image_view.image() is None
    assert not replacement.placeholder.isHidden()
    assert replacement.placeholder.frame().origin.y + replacement.placeholder.frame().size.height / 2 == pytest.approx(replacement.image_view.bounds().size.height / 2)
    tool_app.data["state"].update(running=True, kind="battle")
    tool_app.update_state()
    assert all(not control.isEnabled() for control in replacement.root.subviews() if isinstance(control, A.NSButton))
    assert replacement.image_view.isEnabled()


def test_announcements_render_real_list_schema_as_headings_and_markdown(tool_app):
    data = {"Time": "2026-10-14 00:00:00", "Announcement": [
        {"title": "标题 & 描述", "content": "- 第一项\n- **第二项**\n\n[查看说明](https://example.com)", "contentType": "markdown"},
        {"title": "下一条公告", "content": "保留正文", "contentType": "plain"},
    ]}
    html = announcement_html(data)
    assert "<h2>标题 &amp; 描述</h2>" in html and "<li>" in html and "<strong>第二项</strong>" in html
    assert "contentType" not in html
    rich = attributed_html(html)
    assert "第一项" in rich.string() and "下一条公告" in rich.string()
    heading_font = rich.attribute_atIndex_effectiveRange_(A.NSFontAttributeName, 0, None)[0]
    body_font = rich.attribute_atIndex_effectiveRange_(A.NSFontAttributeName, rich.string().index("第一项"), None)[0]
    assert heading_font.pointSize() > body_font.pointSize()
    tool_app.show_announcements(data)
    editor = tool_app.editors[-1]
    reader = editor.scroller.documentView()
    assert isinstance(reader, A.NSTextView) and not reader.isEditable()
    assert "第一项" in reader.string() and "contentType" not in reader.string()
    assert not any(isinstance(control, A.NSButton) and control.title() == "查看发布页面" for control in editor.root.subviews())


def test_announcement_markdown_escapes_raw_markup_and_handles_empty_payload():
    html = announcement_html({"Announcement": [{"title": "<script>title</script>", "content": "<img src='https://example.com/a'>", "contentType": "markdown"}]})
    assert "&lt;script&gt;" in html and "<script>" not in html and "<img " not in html
    assert "暂无公告" in attributed_html(announcement_html({"Announcement": []})).string()


def test_long_announcement_can_scroll_to_its_final_entry(tool_app):
    data = {"Announcement": [{"title": "长公告", "content": "\n".join(f"- 第 {index} 条内容" for index in range(150)), "contentType": "markdown"}]}
    tool_app.show_announcements(data)
    editor = tool_app.editors[-1]
    reader = editor.scroller.documentView()
    assert "第 149 条内容" in reader.string()
    assert reader.frame().size.height > editor.scroller.contentSize().height


def test_log_divider_changes_height_clamps_and_remembers_collapsed_height():
    app = Application.__new__(Application)
    app.targets, app.data, app.page_index, app.logs_expanded = [], None, 0, False
    app.client = Mock()
    app.native = A.NSApplication.sharedApplication()
    app.delegate = Delegate.alloc().init()
    app.delegate.owner = app
    app.build_window()
    try:
        app.window.setContentSize_((1000, 800))
        assert app.log_resize.isHidden()
        app.toggle_logs()
        assert not app.log_resize.isHidden()
        initial = app.log_scroll.frame().size.height
        def event(y):
            return SimpleNamespace(locationInWindow=lambda: SimpleNamespace(y=y))
        app.log_resize.mouseDown_(event(100))
        app.log_resize.mouseDragged_(event(190))
        assert app.log_scroll.frame().size.height == pytest.approx(initial + 90)
        app.resize_logs(10000)
        assert app.page_scroll.frame().size.height >= 100
        app.resize_logs(-10000)
        assert app.log_scroll.frame().size.height == pytest.approx(72)
        app.toggle_logs()
        app.toggle_logs()
        assert app.log_scroll.frame().size.height == pytest.approx(72)
    finally:
        app.window.setDelegate_(None)
        app.window.close()


def test_manual_timestamp_update_only_changes_existing_timestamp_field(monkeypatch):
    app = content_app(3)
    app.mirror_section = 3
    app.data["config"].update({"floor_3_exit": False, "infinite_dungeons": False,
        "select_event_pack": False, "skip_event_pack": False, "re_claim_rewards": False,
        "fight_to_last_man": False, "select_team_by_order": True, "auto_hard_mirror": True,
        "hard_mirror_chance": 3, "last_auto_change": 1715990400.0})
    app.build_page()
    before = dict(app.data["config"])
    update, field = app.field_actions[0]
    value = 1791970000.125
    monkeypatch.setattr("frontend_appkit.application.time.time", lambda: value)
    update.performClick_(None)
    app.client.request.assert_called_once_with("config.patch", {"values": {"last_auto_change": value}})
    assert app.data["config"] == before | {"last_auto_change": value}
    assert float(field.stringValue()) == value
    assert field.frame().origin.x + field.frame().size.width <= update.frame().origin.x
