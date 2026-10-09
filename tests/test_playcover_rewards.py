from importlib import import_module
from unittest.mock import Mock


def test_victory_confirm_precedes_shared_statistics_icon(monkeypatch):
    from module.backends import factory

    battle = import_module("tasks.battle.battle")

    automation = Mock()
    automation.find_element.side_effect = lambda path: path in {
        "battle/victory.png", "battle/battle_finish_confirm_assets.png", "mirror/claim_reward/battle_statistics_assets.png",
    }
    monkeypatch.setattr(battle, "auto", automation)
    monkeypatch.setattr(factory, "get_playcover_session", Mock(return_value=Mock()))
    assert battle.Battle()._fight_playcover(1) is None
    automation.click_element.assert_called_once_with("battle/battle_finish_confirm_assets.png", offset=False)


def test_ios_rewards_continue_through_level_up_and_return_home(monkeypatch):
    from tasks.mirror import playcover_rewards as rewards

    pages = [
        {"mirror/claim_reward/complete_mirror_100%_assets.png", "mirror/claim_reward/claim_rewards_assets.png"},
        {rewards.PREVIEW, rewards.FIVE_FLOORS, rewards.CLAIM},
        {rewards.CONFIRM_PROMPT, rewards.FINAL_CONFIRM},
        {"mirror/claim_reward/pass_level_up_assets.png", "mirror/claim_reward/pass_level_confirm_assets.png"},
        {"home/mail_assets.png", "home/drive_assets.png"},
    ]
    state = {"page": 0}
    automation = Mock()
    automation.find_element.side_effect = lambda path: path in pages[state["page"]]

    def click(path, **kwargs):
        assert path in pages[state["page"]]
        state["page"] += 1
        return True

    automation.click_element.side_effect = click
    monkeypatch.setattr(rewards.time, "sleep", lambda _: None)
    assert rewards.claim_normal_mirror_rewards(automation)
    assert automation.click_element.call_count == 4


def test_normal_mirror_run_routes_completion_to_ios_reward_flow(monkeypatch):
    from module.config import cfg
    from tasks.mirror import mirror, playcover_entry

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_element.side_effect = lambda path: path == "mirror/claim_reward/complete_mirror_100%_assets.png"
    monkeypatch.setattr(mirror, "auto", automation)
    monkeypatch.setattr(playcover_entry, "prepare_normal_mirror", Mock())
    dungeon = mirror.Mirror(cfg.config.teams["1"], 1)
    claim = Mock(return_value=True)
    monkeypatch.setattr(dungeon, "get_reward_in_road", claim)
    assert dungeon.run()
    claim.assert_called_once()
    automation.click_element.assert_not_called()
