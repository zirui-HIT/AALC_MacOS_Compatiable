"""Automatic checks stay quiet unless official source updates are confirmed."""

# Cocoa imports follow the optional framework check.
# ruff: noqa: E402

from unittest.mock import Mock

import pytest

pytest.importorskip("AppKit")

from frontend_appkit.application import Application


def app():
    result = Application.__new__(Application)
    result.data = {"config": {"language_in_program": "zh_cn"}}
    result.translations = {}
    result.show_text = Mock()
    result.error = Mock()
    result.mirror_status = Mock()
    return result


@pytest.mark.parametrize("status", ["CURRENT", "LOCAL_AHEAD", "EQUIVALENT", "UNKNOWN", "FAILURE"])
def test_automatic_non_update_results_do_not_interrupt_the_window(status):
    controller = app()
    payload = {"status": status, "automatic": True, "message": "检查结论"}
    controller.event("update_status", payload)
    assert controller.update_result == payload
    controller.show_text.assert_not_called()
    controller.error.assert_not_called()
    controller.mirror_status.setStringValue_.assert_not_called()


def test_confirmed_update_shows_the_official_commit_notice():
    controller = app()
    commit = "12345678" + "0" * 32
    controller.event("update", {"status": "UPDATE_AVAILABLE", "automatic": True, "version": "12345678", "commit": commit, "content": "官方变更"})
    controller.show_text.assert_called_once_with("官方仓库有更新 · 12345678", "官方变更", html=True, source_url="https://github.com/KIYI671/AhabAssistantLimbusCompany/commit/" + commit)


def test_manual_check_displays_its_specific_comparison_result():
    controller = app()
    controller.event("update", {"status": "LOCAL_AHEAD", "automatic": False, "message": "本地已包含官方最新提交"})
    controller.mirror_status.setStringValue_.assert_called_once_with("本地已包含官方最新提交")
    controller.show_text.assert_not_called()


def test_automatic_failure_stays_quiet_and_manual_failure_is_explained():
    controller = app()
    for automatic in (True, False):
        controller.event("update", {"status": "FAILURE", "automatic": automatic, "message": "网络暂不可用"})
    controller.error.assert_called_once_with("网络暂不可用")


@pytest.mark.parametrize("event,status", [("update", "UPDATE_AVAILABLE"), ("update", "FAILURE"), ("update_status", "CURRENT")])
def test_late_update_results_cannot_open_windows_during_quit(event, status):
    controller = app()
    controller.quitting = True
    controller.event(event, {"status": status})
    controller.show_text.assert_not_called()
    controller.error.assert_not_called()
    controller.mirror_status.setStringValue_.assert_not_called()
