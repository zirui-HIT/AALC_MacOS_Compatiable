"""The current-page shop choice preserves existing values and native team saves."""

import json
import os
import subprocess
import sys

import pytest

from native_contract import FIELDS, OPTIONS, validate_fields
from utils.runtime_paths import SOURCE_ROOT

LEGACY_OPTIONS = [
    ["仅购买回血饰品", 0],
    ["启用四级优先时：仅购买所有3-4级饰品", 1],
    ["仅购买体系饰品", 2],
    ["不购买体系饰品", 3],
    ["不购买回血饰品", 4],
    ["启用四级优先时：不购买所有3-4级饰品", 5],
]


def test_quick_buy_appends_to_existing_shopping_choices():
    choices = OPTIONS["shopping_strategy_select"]
    assert choices[:-1] == LEGACY_OPTIONS
    assert choices[-1] == ["快速购买当前页并离店", 6]
    for _, value in choices:
        validate_fields({"shopping_strategy": True, "shopping_strategy_select": value}, team=True)
    with pytest.raises(ValueError, match="Invalid choice: shopping_strategy_select"):
        validate_fields({"shopping_strategy_select": 7}, team=True)


def test_quick_buy_team_save_survives_backend_restart(tmp_path):
    def host(method, params=None):
        request = {"v": 1, "id": 1, "method": method, "params": params or {}}
        result = subprocess.run(
            [sys.executable, "-u", "main.py", "--backend", "--no-hotkeys"],
            input=json.dumps(request) + "\n", cwd=SOURCE_ROOT,
            env={**os.environ, "AALC_DATA_ROOT": str(tmp_path)},
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        response = next(message for message in map(json.loads, result.stdout.splitlines()) if message.get("id") == 1)
        assert "error" not in response, response
        return response["result"]

    host("team.save", {"number": 1, "values": {"shopping_strategy": True, "shopping_strategy_select": 6}})
    team = host("snapshot")["config"]["teams"]["1"]
    assert team["shopping_strategy"] is True
    assert team["shopping_strategy_select"] == 6


def test_quick_buy_popup_and_explanation_refresh_in_both_languages(monkeypatch):
    A = pytest.importorskip("AppKit")
    from frontend_appkit import widgets
    from frontend_appkit.application import Application
    from frontend_appkit.forms import SHOPPING_TRANSLATIONS, Form

    A.NSApplication.sharedApplication()
    app = Application.__new__(Application)
    app.data = {"config": {"language_in_program": "zh_cn"}}
    app.translations = SHOPPING_TRANSLATIONS.copy()
    monkeypatch.setattr(widgets, "translate", app.text)
    parent = widgets.FlippedView.alloc().initWithFrame_(((0, 0), (780, 300)))
    values = {"shopping_strategy": True, "shopping_strategy_select": 6}
    form = Form(parent, values, list(values), [], lambda *_: None, team=True, grouped=True, text=app.text)
    control = form.controls["shopping_strategy_select"]
    description = FIELDS["TeamSetting"]["shopping_strategy_select"]["description"]
    assert control.numberOfItems() == 7

    for language in ("zh_cn", "en", "zh_cn"):
        app.data["config"]["language_in_program"] = language
        widgets.refresh(parent)
        assert control.titleOfSelectedItem() == app.text("快速购买当前页并离店")
        assert control.toolTip() == app.text(description)
        assert form.values() == values

    for index in range(7):
        control.selectItemAtIndex_(index)
        assert form.values()["shopping_strategy_select"] == index
