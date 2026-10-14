"""Language changes keep native field hints consistent with visible labels."""

# Native imports follow the optional framework check.
# ruff: noqa: E402

import pytest

A = pytest.importorskip("AppKit")

from frontend_appkit import widgets
from frontend_appkit.forms import DISPLAY_LABELS, Form
from frontend_appkit.widgets import FlippedView, attributed_html


@pytest.mark.parametrize("key,value", [("set_EXP_count", 1), ("use_continuous_combat", False)])
def test_language_refresh_updates_field_tooltips_without_changing_values(monkeypatch, key, value):
    A.NSApplication.sharedApplication()
    language = ["zh_cn"]
    chinese, english = DISPLAY_LABELS[key]

    def translate(source):
        return english if language[0] == "en" and source == chinese else source

    monkeypatch.setattr(widgets, "translate", translate)
    root = FlippedView.alloc().initWithFrame_(((0, 0), (614, 400)))
    form = Form(root, {key: value}, [key], [], lambda *_: None, grouped=True, text=translate)
    control = form.controls[key]
    assert control.toolTip() == chinese

    language[0] = "en"
    widgets.refresh(root)
    assert control.toolTip() == english
    assert form.values() == {key: value}

    language[0] = "zh_cn"
    widgets.refresh(root)
    assert control.toolTip() == chinese
    assert form.values() == {key: value}


def test_html_notice_preserves_chinese_and_its_official_link():
    A.NSApplication.sharedApplication()
    result = attributed_html('<p>官方更新说明：镜牢与队伍适配。</p><a href="https://github.com/KIYI671/AhabAssistantLimbusCompany">查看官方提交</a>')
    assert "官方更新说明：镜牢与队伍适配。" in result.string()
    assert "查看官方提交" in result.string()
    assert "\ufffd" not in result.string()
    attributes, _ = result.attributesAtIndex_effectiveRange_(str(result.string()).index("查看官方提交"), None)
    assert str(attributes[A.NSLinkAttributeName]) == "https://github.com/KIYI671/AhabAssistantLimbusCompany"
