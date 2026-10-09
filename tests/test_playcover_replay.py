import json
from unittest.mock import Mock

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT


def test_real_ios_experience_menu_recognizes_three_enters_without_input(monkeypatch):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en", "set_win_size": 1080}))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    fixture = SOURCE_ROOT / "tests/fixtures/playcover/luxcavation.png"
    monkeypatch.setattr(auto, "screenshot", Image.open(fixture).convert("L"))
    metadata = json.loads(fixture.with_suffix(".json").read_text())
    assert metadata["game_version"] == "1.116.2"
    results = auto.find_element("luxcavation/exp_enter.png", model="normal", threshold=0.85,
                                find_type="image_with_multiple_targets")
    assert len(results) == 3
    assert sorted(round(p[0]) for p in results) == [608, 1120, 1632]


@pytest.mark.parametrize("page,targets", [
    ("formation", ["teams/identify_assets.png", "battle/chaim_to_battle_assets.png"]),
    ("formation_selected", ["teams/clear_selection.png", "battle/chaim_to_battle_assets.png"]),
    ("battle_selected", ["battle/gear_start.png", "battle/win_rate_card.png"]),
    ("victory", ["battle/victory.png", "battle/battle_finish_confirm_assets.png"]),
    ("reset_deployment", ["teams/reset_deployment.png", "teams/clear_selection_confirm_assets.png"]),
])
def test_real_ios_daily_pages_recognize_required_actions(monkeypatch, page, targets):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en", "set_win_size": 1080}))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", Image.open(SOURCE_ROOT / f"tests/fixtures/playcover/{page}.png").convert("L"))
    for target in targets:
        assert auto.find_element(target, model="normal", threshold=0.8), target


@pytest.mark.parametrize("page,count", [("formation", (0, 12)), ("formation_selected", (12, 12))])
def test_real_ios_participant_count(monkeypatch, page, count):
    from module.automation import auto
    from tasks.teams.playcover import participant_count

    monkeypatch.setattr(auto, "take_screenshot", lambda: None)
    monkeypatch.setattr(auto, "screenshot", Image.open(SOURCE_ROOT / f"tests/fixtures/playcover/{page}.png").convert("L"))
    assert participant_count() == count


def test_team_reset_waits_for_dialog_before_confirming(monkeypatch):
    from tasks.teams import playcover

    automation = Mock()
    settled = iter([False, True])
    automation.find_element.side_effect = lambda path: next(settled, False) if path == "teams/reset_deployment.png" else True
    monkeypatch.setattr(playcover, "auto", automation)
    monkeypatch.setattr(playcover, "participant_count", Mock(side_effect=[(12, 12), (0, 12), (12, 12)]))
    monkeypatch.setattr(playcover.time, "sleep", lambda _: None)
    assert playcover.select_daily_team(1)
    confirms = [call for call in automation.click_element.call_args_list if call.args[0] == "teams/clear_selection_confirm_assets.png"]
    assert len(confirms) == 1
