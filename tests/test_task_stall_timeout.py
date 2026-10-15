"""Upstream timeout behavior with simulated time and no game input."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("configured,expected", [
    (90, 90), (600, 600), (3600, 3600), ("600", 600), (0, 30), (-1, 30),
    (None, 90), ("invalid", 90), (float("inf"), 90),
])
def test_upstream_timeout_fallback_and_lower_bound(monkeypatch, configured, expected):
    from tasks.base import retry

    monkeypatch.setattr(retry, "cfg", SimpleNamespace(get_value=lambda *args: configured))
    assert retry.get_task_stall_timeout() == expected


@pytest.mark.parametrize("timeout,restarts", [(None, False), (60, True), (120, False)])
def test_default_timeout_uses_config_but_explicit_timeout_wins(monkeypatch, timeout, restarts):
    from tasks.base import retry

    monkeypatch.setattr(retry, "cfg", SimpleNamespace(get_value=lambda *args: 600))
    monkeypatch.setattr(retry.time, "time", lambda: 100)
    monkeypatch.setattr(retry, "kill_game", Mock())
    monkeypatch.setattr(retry, "restart_game", Mock())
    assert retry.check_times(0, timeout, logs=False) is restarts
    assert retry.kill_game.call_count == retry.restart_game.call_count == int(restarts)


@pytest.mark.parametrize("loading", [False, True])
@pytest.mark.parametrize("timeout", [90, 600])
def test_return_home_waits_for_configured_time_even_after_30_loops(monkeypatch, loading, timeout):
    # Reuse the regression from upstream 2b88666, adapting only the macOS back action.
    from tasks.base import back_init_menu as recovery

    elapsed = 0

    def retry():
        nonlocal elapsed
        elapsed += 1
        return True

    automation = SimpleNamespace(
        model="clam",
        click_element=lambda *args, **kwargs: False,
        find_element=lambda target, **kwargs: loading and target == "base/waiting_assets.png",
        mouse_click_blank=lambda: None,
    )
    monkeypatch.setattr(recovery, "auto", automation)
    monkeypatch.setattr(recovery, "get_game_actions", Mock())
    monkeypatch.setattr(recovery, "monotonic", lambda: elapsed)
    monkeypatch.setattr(recovery, "get_task_stall_timeout", lambda: timeout)
    monkeypatch.setattr(recovery, "retry", retry)
    monkeypatch.setattr(recovery, "ensure_simulator_game_started", lambda: False)
    monkeypatch.setattr(recovery, "update_model_for_retry", lambda *args, **kwargs: None)

    assert recovery.back_init_menu(allow_restart=False) is False
    assert elapsed == timeout


@pytest.mark.parametrize("value", [30, 90, 600, 3600])
def test_appkit_timeout_range_matches_upstream_spinbox(value):
    from native_contract import validate_fields

    validate_fields({"task_stall_timeout": value})


@pytest.mark.parametrize("value", [0, 29, 3601, True, "600", 600.5])
def test_appkit_timeout_rejects_invalid_values(value):
    from native_contract import validate_fields

    with pytest.raises(ValueError):
        validate_fields({"task_stall_timeout": value})
