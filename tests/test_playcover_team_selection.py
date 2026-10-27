"""iOS row geometry while retaining the desktop/simulator selection branches."""

import pytest


@pytest.mark.parametrize("profile", ["ios_en", "ios_zh_cn"])
@pytest.mark.parametrize("page,distance", [(None, 362.5), (1, 362.5), (6, 362.5), (7, 253.75)])
def test_ios_ordered_pages_follow_five_rows_and_the_clamped_last_page(monkeypatch, profile, page, distance):
    from module.config import cfg
    from tasks.teams.team_formation import _ordered_team_page_swipe_distance

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": profile, "simulator": False,
    }))
    assert _ordered_team_page_swipe_distance(page) == distance


@pytest.mark.parametrize("simulator,kind,distances", [
    (False, 0, (400, 400)),
    (True, 0, (362.5, 253.75)),
    (True, 10, (375, 375)),
])
def test_desktop_and_simulator_page_distances_stay_unchanged(monkeypatch, simulator, kind, distances):
    from module.config import cfg
    from tasks.teams.team_formation import _ordered_team_page_swipe_distance

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "game_profile": "auto", "simulator": simulator, "simulator_type": kind,
    }))
    assert tuple(_ordered_team_page_swipe_distance(page) for page in (1, 7)) == distances
