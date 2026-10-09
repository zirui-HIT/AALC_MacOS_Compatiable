"""Reward choices and weekly-bonus policy use the existing shared routine."""
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("disable_bonus", [False, True])
def test_shared_mirror_reward_loop_applies_saved_weekly_bonus_setting(monkeypatch, disable_bonus):
    from module.config import cfg
    from tasks.mirror import mirror
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "no_weekly_bonuses": disable_bonus,
        "hard_mirror_single_bonuses": False, "save_rewards": False}))
    automation = Mock()
    state = {"page": "complete"}
    def find(path, **kwargs):
        return [(700, 350)] if path.endswith("weekly_bonuses.png") else None
    def click(path, **kwargs):
        if state["page"] == "complete" and path.endswith("claim_rewards_assets.png"):
            state["page"] = "preview"
            return True
        if state["page"] == "preview" and path.endswith("use_enkephalin_assets.png"):
            state["page"] = "confirm"
            return True
        if state["page"] == "confirm" and path.endswith("claim_rewards_confirm_assets.png"):
            state["page"] = "acquired"
            return True
        return state["page"] == "acquired" and path.endswith("rewards_acquired_assets.png")
    automation.find_element.side_effect = find
    automation.click_element.side_effect = click
    monkeypatch.setattr(mirror, "auto", automation)
    monkeypatch.setattr(mirror, "sleep", lambda _: None)
    dungeon = mirror.Mirror(cfg.config.teams["1"], 1)
    assert dungeon.get_reward_in_road()
    assert automation.mouse_click.call_count == int(disable_bonus)
