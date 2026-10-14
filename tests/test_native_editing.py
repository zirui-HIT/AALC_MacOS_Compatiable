"""Draft and state-update regressions without a backend or game connection."""

# Cocoa imports follow the optional framework check.
# ruff: noqa: E402

import base64
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

A = pytest.importorskip("AppKit")

from ruamel.yaml import YAML

from frontend_appkit import widgets
from frontend_appkit.application import Application
from frontend_appkit.forms import Form
from frontend_appkit.widgets import FlippedView, refresh
from native_contract import FIELDS, TASK_KEYS


@pytest.fixture(autouse=True)
def cocoa():
    A.NSApplication.sharedApplication()


def view(width=780):
    return FlippedView.alloc().initWithFrame_(((0, 0), (width, 500)))


def descendants(parent):
    for child in parent.subviews():
        yield child
        yield from descendants(child)


@pytest.mark.parametrize("local,expected", [("3", "3"), ("", ""), ("1", "2")])
def test_state_echo_preserves_local_input_and_updates_untouched_fields(local, expected):
    app = Application.__new__(Application)
    app.page_index = 0
    app.data = {"config": {"set_EXP_count": 1, "language_in_program": "zh_cn"}}
    app.update_state = Mock()
    form = Form(view(), app.data["config"], ["set_EXP_count"], [], lambda *_: None)
    app.forms = [form]
    form.controls["set_EXP_count"].setStringValue_(local)

    app.event("state", {"config": {"set_EXP_count": 2, "language_in_program": "zh_cn"}})

    assert form.controls["set_EXP_count"].stringValue() == expected
    assert app.data["config"]["set_EXP_count"] == 2


def test_state_update_does_not_replace_a_focused_field_even_before_typing():
    app = Application.__new__(Application)
    app.page_index = 0
    app.data = {"config": {"set_EXP_count": 1, "language_in_program": "zh_cn"}}
    app.update_state = Mock()
    parent = view()
    form = Form(parent, app.data["config"], ["set_EXP_count"], [], lambda *_: None)
    app.forms = [form]
    control = form.controls["set_EXP_count"]
    window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((0, 0), (780, 500)), A.NSWindowStyleMaskTitled, A.NSBackingStoreBuffered, False)
    window.setReleasedWhenClosed_(False)
    window.setContentView_(parent)
    try:
        window.makeKeyAndOrderFront_(None)
        assert window.makeFirstResponder_(control)
        assert control.currentEditor() is not None
        app.event("state", {"config": {"set_EXP_count": 2, "language_in_program": "zh_cn"}})
        assert control.stringValue() == "1"
    finally:
        window.orderOut_(None)
        window.close()


@pytest.fixture
def editor_app():
    app = Application.__new__(Application)
    app.data = {"config": {"language_in_program": "zh_cn"}}
    app.translations = {}
    app.editors = []
    app.team_editor = None
    app.client = Mock()
    app.error = Mock()
    app.update_state = Mock()
    yield app
    for editor in list(app.editors):
        editor.close()


def theme_values():
    return {"preferred_thresholds": 0, "theme_pack_list": {"nagel": 0, "nag": 0}, "theme_pack_list_cn": {"钉与锤": 0}, "theme_pack_list_hard": {}, "forbidden_theme_packs": {}}


@pytest.mark.parametrize("key,value", [("screenshot_interval", 0.01), ("mouse_action_interval", 0.25), ("mouse_down_duration", 1.25)])
def test_float_form_preserves_fraction_when_editing_ends(key, value):
    changes = []
    form = Form(view(), {key: 0.5}, [key], [], lambda name, result: changes.append((name, result)))
    control = form.controls[key]
    window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((0, 0), (780, 500)), A.NSWindowStyleMaskTitled, A.NSBackingStoreBuffered, False)
    window.setReleasedWhenClosed_(False)
    window.setContentView_(form.parent)
    try:
        window.makeKeyAndOrderFront_(None)
        assert window.makeFirstResponder_(control)
        control.currentEditor().setString_(str(value))
        assert window.makeFirstResponder_(None)
        assert form.values()[key] == value
        assert changes[-1] == (key, value)
    finally:
        window.orderOut_(None)
        window.close()


def test_deletion_closes_only_editors_whose_presets_will_be_reindexed(editor_app, monkeypatch):
    monkeypatch.setattr("frontend_appkit.application.confirm", lambda *args, **kwargs: True)
    editors = []
    for attribute, scope in [("team_scope", 1), ("team_scope", 2), ("theme_scope", 3), ("theme_scope", None)]:
        editor = Mock(closed=False, spec=["closed", "window", "close_window", attribute])
        setattr(editor, attribute, scope)
        editor.close_window.return_value = True
        editors.append(editor)
    editor_app.editors = editors
    editor_app.delete_team(2)
    editors[0].close_window.assert_not_called()
    editors[1].close_window.assert_called_once_with(editors[1].window)
    editors[2].close_window.assert_called_once_with(editors[2].window)
    editors[3].close_window.assert_not_called()
    assert editor_app.deleting_team
    request = editor_app.client.request.call_args
    assert request.args[:2] == ("team.delete", {"number": 2})
    request.args[2](None)
    assert not editor_app.deleting_team
    editor_app.editors = []


def test_cancelled_editor_close_prevents_preset_deletion(editor_app, monkeypatch):
    monkeypatch.setattr("frontend_appkit.application.confirm", lambda *args, **kwargs: True)
    editor = Mock(closed=False, team_scope=2)
    editor.close_window.return_value = False
    editor_app.editors = [editor]
    editor_app.delete_team(1)
    editor_app.client.request.assert_not_called()
    assert not editor_app.deleting_team
    editor_app.editors = []


@pytest.mark.parametrize("success", [True, False])
def test_deletion_invalidates_old_theme_replies_and_blocks_new_preset_editors(editor_app, monkeypatch, success):
    monkeypatch.setattr("frontend_appkit.application.confirm", lambda *args, **kwargs: True)
    editor_app.open_theme(2)
    old_reply = editor_app.client.request.call_args.args[2]
    editor_app.delete_team(1)
    deletion = editor_app.client.request.call_args
    editor_app.client.request.reset_mock()
    editor_app.open_theme(2)
    editor_app.edit_team(2)
    editor_app.client.request.assert_not_called()
    old_reply(theme_values())
    assert not editor_app.editors
    if success:
        deletion.args[2](None)
    else:
        deletion.kwargs["on_error"]("deletion failed")
        editor_app.error.assert_called_once_with("deletion failed")
    assert not editor_app.deleting_team
    old_reply(theme_values())
    assert not editor_app.editors
    editor_app.open_theme(2)
    editor_app.client.request.call_args.args[2](theme_values())
    assert len(editor_app.editors) == 1


def open_theme(app):
    app.edit_theme(None, theme_values())
    return app.editors[-1]


def weight_field(editor):
    return next(control for control in descendants(editor.document) if isinstance(control, A.NSTextField) and control.isEditable())


def theme_popup(editor, count):
    return next(control for control in editor.root.subviews() if isinstance(control, A.NSPopUpButton) and control.numberOfItems() == count)


def test_browsing_theme_modes_and_floors_does_not_create_unsaved_changes(editor_app):
    editor = open_theme(editor_app)
    assert not editor.dirty()
    for count in (5, 2):
        control = theme_popup(editor, count)
        control.selectItemAtIndex_(1)
        control.target().callback(control)
        assert not editor.dirty()
    editor_app.client.request.assert_not_called()


@pytest.mark.parametrize("count,index", [(2, 1), (5, 2)])
def test_invalid_theme_weight_restores_scope_before_a_ban_can_be_set(editor_app, count, index):
    editor = open_theme(editor_app)
    weight_field(editor).setStringValue_("11")
    control = theme_popup(editor, count)
    control.selectItemAtIndex_(index)
    with pytest.raises(ValueError, match="权重范围"):
        control.target().callback(control)
    assert control.indexOfSelectedItem() == 0
    assert not editor.dirty()

    # A subsequent click still belongs to the displayed original scope.
    weight_field(editor).setStringValue_("0")
    ban = next(control for control in editor.document.subviews() if isinstance(control, A.NSButton))
    ban.setState_(1)
    ban.target().callback(ban)
    save = next(control for control in editor.root.subviews() if isinstance(control, A.NSButton) and control.title() == "保存并关闭")
    save.target().callback(save)
    payload = editor_app.client.request.call_args.args[1]
    assert "nagel" in payload["values"]["forbidden_theme_packs"]["normal_1"]
    assert not payload["values"]["forbidden_theme_packs"].get("normal_3")
    assert not payload["values"]["forbidden_theme_packs"].get("hard_1")


def test_changed_theme_weight_keeps_original_bilingual_and_ocr_aliases(editor_app):
    editor = open_theme(editor_app)
    weight_field(editor).setStringValue_("5")
    floor = theme_popup(editor, 5)
    floor.selectItemAtIndex_(1)
    floor.target().callback(floor)
    assert editor.dirty()
    save = next(control for control in editor.root.subviews() if isinstance(control, A.NSButton) and control.title() == "保存并关闭")
    save.target().callback(save)
    payload = editor_app.client.request.call_args.args[1]["values"]
    assert payload["theme_pack_list"]["nagel"] == 5
    assert payload["theme_pack_list"]["nag"] == 5
    assert payload["theme_pack_list_cn"]["钉与锤"] == 5


def team_values():
    root = Path(__file__).resolve().parents[1]
    team = YAML(typ="safe").load((root / "assets/config/config.example.yaml").read_text())["teams"]["1"]
    for key, metadata in FIELDS["TeamSetting"].items():
        if key not in team:
            kind = metadata["type"]
            team[key] = False if kind == "bool" else [] if kind.startswith("List") else 0 if kind in {"int", "float"} else ""
    team["remark_name"] = ""
    return team


def test_team_dynamic_order_and_starlight_survive_language_refresh(editor_app):
    team = team_values()
    editor_app.data["config"]["teams"] = {"1": team}
    editor_app.edit_team(1)
    editor = editor_app.team_editor
    sinner = next(control for control in descendants(editor.document) if isinstance(control, A.NSButton) and control.title() == "李箱")
    sinner.setState_(1)
    sinner.target().callback(sinner)
    cost = next(control for control in descendants(editor.document) if isinstance(control, A.NSTextField) and str(control.stringValue()).startswith("星光总消耗"))
    original_cost = cost.stringValue()

    refresh(editor.root)

    assert sinner.title() == "李箱 · 1"
    assert cost.stringValue() == original_cost


@pytest.mark.parametrize("values", [[], None, "invalid"])
def test_team_code_with_non_object_json_reports_a_normal_error(values):
    app = Application.__new__(Application)
    app.client = Mock()
    app.error = Mock()
    code = base64.b64encode(("||AALC_TEAM_SETTING||" + json.dumps(values)).encode()).decode()
    with patch("frontend_appkit.application.A.NSPasteboard") as pasteboard:
        pasteboard.generalPasteboard.return_value.stringForType_.return_value = code
        app.paste_team(1, None, None)
    app.error.assert_called_once_with("队伍配置码必须包含设置对象")
    app.client.request.assert_not_called()


def test_old_paste_reply_does_not_close_a_new_dirty_team_editor(editor_app):
    editor_app.data["config"]["teams"] = {"1": team_values(), "2": team_values()}
    editor_app.edit_team(1)
    original = editor_app.team_editor
    code = base64.b64encode(("||AALC_TEAM_SETTING||" + json.dumps(team_values())).encode()).decode()
    with patch("frontend_appkit.application.A.NSPasteboard") as pasteboard:
        pasteboard.generalPasteboard.return_value.stringForType_.return_value = code
        editor_app.paste_team(1, None, None)
    reply = editor_app.client.request.call_args.args[2]
    original.close()
    editor_app.edit_team(2)
    current = editor_app.team_editor
    field = next(control for control in descendants(current.document) if isinstance(control, A.NSTextField)
                 and control.isEditable() and control.formatter() is None)
    field.setStringValue_("unsaved preset 2")
    assert current.dirty()
    reply(None)
    assert not current.closed
    assert current in editor_app.editors


@pytest.mark.parametrize("invalidated", ["closed", "reindexed"])
@pytest.mark.parametrize("stage", ["save", "transfer", "refresh"])
def test_theme_transfer_drops_late_replies_for_closed_or_reindexed_editors(editor_app, monkeypatch, invalidated, stage):
    editor_app.edit_theme(2, theme_values())
    editor = editor_app.editors[-1]
    index = 2 if stage == "save" else 1
    monkeypatch.setattr("frontend_appkit.application.choose_path", lambda **kwargs: "/tmp/weights.yaml")
    board = Mock()
    monkeypatch.setattr("frontend_appkit.application.A.NSPasteboard", Mock(generalPasteboard=Mock(return_value=board)))
    invoke_menu_item(more_menu(editor), "复制配置码" if index == 2 else "导入 YAML")
    reply = editor_app.client.request.call_args.args[2]
    if stage == "refresh":
        reply(True)
        assert editor_app.client.request.call_args.args[:2] == ("theme.get", {"number": 2})
        reply = editor_app.client.request.call_args.args[2]
    if invalidated == "closed":
        editor.close()
    else:
        editor_app.team_generation = 1
    before = editor_app.client.request.call_count
    weight = weight_field(editor)
    reply({**theme_values(), "theme_pack_list": {"nagel": 7, "nag": 7}} if stage == "refresh" else True)
    assert editor_app.client.request.call_count == before
    assert weight.stringValue() == "0"
    board.clearContents.assert_not_called()
    board.setString_forType_.assert_not_called()


def test_current_theme_transfer_still_saves_then_copies_its_own_code(editor_app, monkeypatch):
    editor_app.edit_theme(2, theme_values())
    editor = editor_app.editors[-1]
    board = Mock()
    monkeypatch.setattr("frontend_appkit.application.A.NSPasteboard", Mock(generalPasteboard=Mock(return_value=board)))
    invoke_menu_item(more_menu(editor), "复制配置码")
    save = editor_app.client.request.call_args
    assert save.args[:2] == ("theme.save", {"number": 2, "values": theme_values() | {
        "forbidden_theme_packs": {"normal_1": []},
    }})
    save.args[2](None)
    transfer = editor_app.client.request.call_args
    assert transfer.args[:2] == ("theme.transfer", {"number": 2, "action": "copy"})
    transfer.args[2]("own preset code")
    board.clearContents.assert_called_once()
    board.setString_forType_.assert_called_once_with("own preset code", A.NSPasteboardTypeString)


def test_nullable_remark_does_not_make_an_untouched_team_dirty(editor_app):
    editor_app.data["config"]["teams"] = {"1": {**team_values(), "remark_name": None}}
    editor_app.edit_team(1)
    editor = editor_app.team_editor
    assert not editor.dirty()


def test_preset_theme_editor_uses_the_global_threshold_without_an_editable_override(editor_app):
    editor_app.edit_theme(1, {**theme_values(), "preferred_thresholds": 10})
    editor = editor_app.editors[-1]
    assert not any(isinstance(control, A.NSTextField) and control.isEditable() for control in editor.root.subviews())
    assert any(isinstance(control, A.NSTextField) and "全局主题包权重" in str(control.stringValue()) for control in editor.root.subviews())


@pytest.mark.parametrize("locale", ["fr_FR", "de_DE"])
def test_float_form_reads_localized_numbers_and_rejects_invalid_input(locale):
    from Foundation import NSLocale

    form = Form(view(), {"screenshot_interval": 0.5}, ["screenshot_interval"], [], lambda *_: None)
    control = form.controls["screenshot_interval"]
    control.formatter().setLocale_(NSLocale.alloc().initWithLocaleIdentifier_(locale))
    form.set_value("screenshot_interval", 0.25)
    assert control.stringValue() == "0,25"
    assert form.values() == {"screenshot_interval": 0.25}
    control.setStringValue_("0,25junk")
    with pytest.raises(ValueError):
        form.values()


def connection_app():
    app = Application.__new__(Application)
    app.data = {"config": {"playcover_port": 1718, "language_in_program": "zh_cn"}}
    app.window = Mock()
    app.client = Mock()
    app.error = Mock()
    app.forms = [Form(view(), app.data["config"], ["playcover_port"], [], lambda *_: None)]
    return app


@pytest.mark.parametrize("accepted", [True, False])
def test_connection_waits_for_successful_configuration_submission(accepted):
    app = connection_app()
    app.forms[0].controls["playcover_port"].setStringValue_("1719")
    app.test_connection()
    assert app.client.request.call_count == 1
    submission = app.client.request.call_args
    assert submission.args[:2] == ("config.patch", {"values": {"playcover_port": 1719}})

    if accepted:
        submission.args[2](None)
        assert app.client.request.call_count == 2
        app.client.request.assert_called_with("connection.test")
    else:
        submission.kwargs["on_error"]("Invalid connection settings")
        assert app.client.request.call_count == 1
        app.error.assert_called_once_with("Invalid connection settings")


def test_connection_invalid_numeric_input_never_sends_a_request():
    app = connection_app()
    app.forms[0].controls["playcover_port"].setStringValue_("")
    app.test_connection()
    app.error.assert_called_once()
    app.client.request.assert_not_called()


def state_app():
    app = Application.__new__(Application)
    app.editors = []
    config = {**dict.fromkeys(TASK_KEYS, False), "language_in_program": "zh_cn", "set_EXP_count": 1, "set_thread_count": 1, "set_get_prize": 0, "set_lunacy_to_enkephalin": 1, "set_mirror_count": 1, "theme_mode": "AUTO"}
    state = {"running": True, "stopping": False, "startup": False, "kind": "task", "paused": False, "queued": 0}
    app.data = {"config": config, "state": state, "version": "test"}
    app.page_index = 6
    for name in ("window", "status", "select_all_button", "clear_tasks_button", "native"):
        setattr(app, name, Mock())
    app.start_button = A.NSButton.alloc().initWithFrame_(((0, 0), (126, 32)))
    app.pause_button = A.NSButton.alloc().initWithFrame_(((0, 0), (88, 32)))
    app.task_buttons = [Mock() for _ in TASK_KEYS]
    app.task_summaries = []
    app.forms = []
    app.team_order_controls = []
    app.page_targets = []
    app.page = view(548)
    app.connection_controls = []
    return app


def test_connection_actions_follow_running_state():
    app = state_app()
    app.connection_controls = [A.NSButton.alloc().initWithFrame_(((0, 0), (100, 30))) for _ in range(2)]
    for running in (True, False):
        app.data["state"]["running"] = running
        app.update_state()
        assert all(bool(control.isEnabled()) == (not running) for control in app.connection_controls)


def test_theme_reopening_same_scope_preserves_existing_draft(editor_app):
    editor = open_theme(editor_app)
    weight_field(editor).setStringValue_("5")
    editor_app.open_theme(None)
    editor_app.edit_theme(None, theme_values())
    assert editor_app.editors == [editor]
    assert weight_field(editor).stringValue() == "5"
    editor_app.client.request.assert_not_called()


def test_theme_duplicate_get_replies_create_only_one_editor(editor_app):
    editor_app.open_theme(None)
    editor_app.open_theme(None)
    replies = [call.args[2] for call in editor_app.client.request.call_args_list]
    assert len(replies) == 2
    for reply in replies:
        reply(theme_values())
    assert len(editor_app.editors) == 1
    assert editor_app.editors[0].theme_scope is None


def test_theme_scopes_are_independent_and_a_closed_scope_can_be_reopened(editor_app):
    global_editor = open_theme(editor_app)
    editor_app.edit_theme(1, theme_values())
    assert {editor.theme_scope for editor in editor_app.editors} == {None, 1}
    global_editor.close()
    reopened = open_theme(editor_app)
    assert reopened is not global_editor
    assert {editor.theme_scope for editor in editor_app.editors} == {None, 1}


def more_menu(editor):
    return next(control for control in descendants(editor.root) if isinstance(control, A.NSPopUpButton) and control.pullsDown())


def invoke_menu_item(control, title):
    item = next(item for item in control.itemArray() if str(item.representedObject()) == title)
    assert A.NSApplication.sharedApplication().sendAction_to_from_(item.action(), item.target(), item)


def test_team_list_more_commands_disabled_state_language_and_compact_geometry(monkeypatch):
    app = state_app()
    app.client = Mock()
    app.page_index = 4
    app.data["config"].update(teams={"1": {"remark_name": "A", "team_number": 1, "team_system": 0}, "2": {"remark_name": "B", "team_number": 2, "team_system": 1}}, teams_active_queue=[1])
    app.translations = {"更多": "More", "上移": "Move up", "下移": "Move down", "复制": "Copy", "删除": "Delete"}
    monkeypatch.setattr(widgets, "translate", app.text)
    app.build_teams()
    menus = [control for control in descendants(app.page) if isinstance(control, A.NSPopUpButton) and control.pullsDown()]
    assert len(menus) == 2
    for menu in menus:
        row = menu.superview()
        for control in row.subviews():
            rect = control.frame()
            assert 0 <= rect.origin.x and rect.origin.x + rect.size.width <= row.bounds().size.width
        assert not menu.menu().autoenablesItems()

    app.data["state"]["running"] = False
    app.update_state()
    assert all(menu.isEnabled() for menu in menus)
    for index in (1, 2):
        assert menus[0].itemAtIndex_(index).isEnabled()
        assert not menus[1].itemAtIndex_(index).isEnabled()
    menus[1].menu().update()
    assert not menus[1].itemAtIndex_(1).isEnabled()

    with patch("frontend_appkit.application.confirm", return_value=True):
        for title in ("上移", "下移", "复制", "删除"):
            invoke_menu_item(menus[0], title)
    assert [call.args[:2] for call in app.client.request.call_args_list] == [("team.order", {"number": 1, "offset": -1}), ("team.order", {"number": 1, "offset": 1}), ("team.add", {"copy_from": 1}), ("team.delete", {"number": 1})]
    assert all(not menu.isEnabled() for menu in menus)
    app.client.request.call_args.args[2](None)
    assert all(menu.isEnabled() for menu in menus)

    app.data["state"]["running"] = True
    app.update_state()
    assert all(not menu.isEnabled() for menu in menus)
    assert all(not menu.itemAtIndex_(index).isEnabled() for menu in menus for index in (1, 2))

    app.data["config"]["language_in_program"] = "en"
    refresh(app.page)
    assert [item.title() for item in menus[0].itemArray()] == ["More", "Move up", "Move down", "Copy", "Delete"]


def test_team_editor_more_routes_and_save_collects_unsubmitted_input(editor_app):
    editor_app.data["config"]["teams"] = {"1": team_values()}
    for name in ("export_team", "import_team", "copy_team", "paste_team"):
        setattr(editor_app, name, Mock())
    editor_app.edit_team(1)
    editor = editor_app.team_editor
    stats = next(control for control in editor.document.subviews() if isinstance(control, A.NSTextField) and str(control.stringValue()).startswith("普通镜牢"))
    clear_stats = next(control for control in editor.document.subviews() if isinstance(control, A.NSButton) and control.title() == "清空历史统计")
    assert stats.frame().origin.y + stats.frame().size.height <= clear_stats.frame().origin.y
    editor_app.client.request.reset_mock()
    more = more_menu(editor)
    for title in ("导出 YAML", "导入 YAML", "复制配置码", "粘贴配置码"):
        invoke_menu_item(more, title)
    editor_app.export_team.assert_called_once_with(1)
    editor_app.import_team.assert_called_once_with(1, editor)
    editor_app.copy_team.assert_called_once_with(1)
    number, form, draft = editor_app.paste_team.call_args.args
    assert number == 1 and isinstance(form, Form)
    assert draft.values["sinners_be_select"] == 0
    editor_app.client.request.assert_not_called()

    form.controls["remark_name"].setStringValue_("Pending remark")
    sinner = next(control for control in descendants(editor.document) if isinstance(control, A.NSButton) and control.title() == "李箱")
    sinner.setState_(1)
    sinner.target().callback(sinner)
    save = next(control for control in editor.root.subviews() if isinstance(control, A.NSButton) and control.title() == "保存")
    assert A.NSApplication.sharedApplication().sendAction_to_from_(save.action(), save.target(), save)
    request = editor_app.client.request.call_args
    assert request.args[0] == "team.save"
    payload = request.args[1]["values"]
    assert payload["remark_name"] == "Pending remark"
    assert payload["sinners_be_select"] == 1
    assert payload["chosen_sinners"][0] == payload["sinner_order"][0] == 1
    assert not {"mirror_normal_count", "mirror_hard_count", "use_team_code", "team_code"} & payload.keys()
    assert not editor.closed
    request.args[2](None)
    assert editor.closed


def test_theme_more_routes_keep_scope_and_validate_pending_weights(editor_app):
    editor_app.theme_transfer = Mock()
    editor_app.edit_theme(1, theme_values())
    editor = editor_app.editors[-1]
    more = more_menu(editor)
    for title in ("导出 YAML", "导入 YAML", "复制配置码", "粘贴配置码"):
        invoke_menu_item(more, title)
    assert [call.args[:2] for call in editor_app.theme_transfer.call_args_list] == [(1, 0), (1, 1), (1, 2), (1, 3)]

    weight_field(editor).setStringValue_("11")
    reset = next(item for item in more.itemArray() if item.representedObject() == "重置默认")
    with pytest.raises(ValueError, match="权重范围"):
        reset.target().callback(reset)
    editor_app.client.request.assert_not_called()
    assert weight_field(editor).stringValue() == "11"

    weight_field(editor).setStringValue_("5")
    invoke_menu_item(more, "重置默认")
    assert editor_app.client.request.call_args.args == ("theme.defaults",)
    invoke_menu_item(more, "拉取全局")
    assert editor_app.client.request.call_args.args == ("theme.get",)
    invoke_menu_item(more, "全部设为 -5")
    assert weight_field(editor).stringValue() == "-5"
    assert editor.dirty()


def test_tool_launchers_disable_nested_actions_while_game_is_busy():
    app = state_app()
    app.page_index = 7
    app.page = view(820)
    app.client = Mock()
    app.open_tool = Mock()
    app.build_tools()
    controls = [control for control in descendants(app.page) if isinstance(control, A.NSButton)]
    assert len(controls) == 2
    app.data["state"].update(running=True, kind="battle")
    app.update_state()
    assert all(not control.isEnabled() for control in controls)
    assert app.start_button.isEnabled()

    app.data["state"].update(running=False, kind="")
    app.update_state()
    assert all(control.isEnabled() for control in controls)
    for title in ("打开自动战斗…", "打开截图小工具…"):
        control = next(control for control in controls if control.title() == title)
        assert A.NSApplication.sharedApplication().sendAction_to_from_(control.action(), control.target(), control)
    assert [call.args for call in app.open_tool.call_args_list] == [("battle",), ("capture",)]
    app.client.request.assert_not_called()
