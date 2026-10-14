"""Pointer feedback preserves navigation selection and checkbox task intent."""

# Native imports follow the optional framework check.
# ruff: noqa: E402

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

A = pytest.importorskip("AppKit")

from frontend_appkit.presentation import QuietSegments, TaskRow, segmented
from frontend_appkit.widgets import FlippedView, button, label


@pytest.fixture(autouse=True)
def cocoa_application():
    # Only initialize Cocoa; no application window, host, or game is opened.
    A.NSApplication.sharedApplication()


def pointer_event(control, point):
    window_point = control.convertPoint_toView_(point, None)
    return SimpleNamespace(locationInWindow=lambda: window_point)


def quiet_navigation():
    callback = Mock()
    control = segmented(None, ["任务", "工具"], ((0, 0), (144, 30)), callback, [], quiet=True)
    assert isinstance(control, QuietSegments)
    return control, callback


@pytest.mark.parametrize("hovered", [0, 1])
def test_navigation_hover_does_not_replace_persistent_selection(hovered):
    control, callback = quiet_navigation()
    control.setSelectedSegment_(0)
    event = pointer_event(control, (hovered * 72 + 36, 15))

    control.mouseEntered_(event)
    assert control.hovered_segment == hovered
    assert control.selectedSegment() == 0

    control.mouseExited_(event)
    assert control.hovered_segment == -1
    assert control.selectedSegment() == 0
    callback.assert_not_called()


def test_navigation_selection_change_survives_leaving_hovered_segment():
    control, callback = quiet_navigation()
    event = pointer_event(control, (36, 15))
    control.mouseEntered_(event)
    control.setSelectedSegment_(1)
    control.mouseExited_(event)
    assert control.selectedSegment() == 1
    assert control.hovered_segment == -1
    callback.assert_not_called()


def test_disabled_navigation_clears_hover_and_does_not_activate():
    control, callback = quiet_navigation()
    control.setSelectedSegment_(1)
    event = pointer_event(control, (36, 15))
    control.mouseEntered_(event)
    assert control.hovered_segment == 0

    control.setEnabled_(False)
    assert control.hovered_segment == -1
    control.mouseEntered_(event)
    control.mouseMoved_(event)
    assert control.hovered_segment == -1
    assert control.selectedSegment() == 1
    callback.assert_not_called()

    control.setEnabled_(True)
    control.mouseEntered_(event)
    assert control.hovered_segment == 0
    assert control.selectedSegment() == 1


def task_row():
    root = FlippedView.alloc().initWithFrame_(((0, 0), (220, 100)))
    row = TaskRow.alloc().initWithFrame_(((0, 0), (180, 54)))
    root.addSubview_(row)
    row.selected = True
    row.select_callback = Mock()
    targets = []
    root.action_targets = targets
    patch = Mock()
    checkbox = button(row, "", ((10, 13), (20, 24)), patch, targets, checkbox=True)
    title = button(row, "日常任务", ((34, 5), (138, 24)), lambda _: row.select_callback(), targets)
    title.setBordered_(False)
    summary = label(row, "经验 1 · 纽本 3", ((36, 30), (136, 18)))
    return root, row, checkbox, title, summary, patch


def test_task_row_hover_does_not_clear_persistent_selection():
    root, row, *_ = task_row()
    row.mouseEntered_(None)
    assert row.hovered and row.selected
    row.mouseExited_(None)
    assert not row.hovered and row.selected
    row.select_callback.assert_not_called()


@pytest.mark.parametrize("point", [(80, 16), (80, 40), (174, 26), (2, 26)])
def test_task_title_summary_and_empty_space_select_the_row(point):
    root, row, checkbox, title, summary, patch = task_row()
    target = row.hitTest_(point)
    if target == title:
        title.performClick_(None)
    else:
        assert target == row
        row.mouseDown_(None)
    row.select_callback.assert_called_once_with()
    assert checkbox.state() == A.NSControlStateValueOff
    patch.assert_not_called()


def test_task_checkbox_toggles_task_without_selecting_row():
    root, row, checkbox, title, summary, patch = task_row()
    assert row.hitTest_((20, 25)) == checkbox
    checkbox.performClick_(None)
    assert checkbox.state() == A.NSControlStateValueOn
    patch.assert_called_once_with(checkbox)
    row.select_callback.assert_not_called()


def test_disabled_task_checkbox_does_not_redirect_click_to_navigation():
    root, row, checkbox, title, summary, patch = task_row()
    checkbox.setEnabled_(False)
    assert row.hitTest_((20, 25)) == checkbox
    checkbox.performClick_(None)
    assert checkbox.state() == A.NSControlStateValueOff
    patch.assert_not_called()
    row.select_callback.assert_not_called()
