"""Mirror recovery remains bounded and never replays entry or claims rewards."""

from unittest.mock import Mock

import pytest


def route_automation():
    automation = Mock()
    automation.find_element.side_effect = lambda path: (
        (704, 369) if path.endswith("mybus_default_distance.png") else path.endswith("legend_assets.png")
    )
    return automation


def test_upper_adjacent_node_is_reachable_below_toolbar(monkeypatch):
    from tasks.mirror import search_road

    automation = route_automation()
    automation.click_element.side_effect = [False, False, True]
    monkeypatch.setattr(search_road, "auto", automation)
    monkeypatch.setattr(search_road, "sleep", lambda _: None)
    assert search_road._search_playcover_adjacent()
    assert [call.args for call in automation.mouse_click.call_args_list] == [(1087, 435), (1087, 755), (1087, 115)]


def test_unconfirmed_node_entry_is_sent_once(monkeypatch):
    from tasks.mirror import search_road

    automation = route_automation()
    original = automation.find_element.side_effect
    automation.find_element.side_effect = lambda path: path.endswith("enter_assets.png") or original(path)
    automation.click_element.return_value = True
    monkeypatch.setattr(search_road, "auto", automation)
    monkeypatch.setattr(search_road, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="sent once"):
        search_road._search_playcover_adjacent()
    automation.click_element.assert_called_once()
    automation.mouse_click.assert_called_once()


def test_unknown_map_geometry_sends_no_input(monkeypatch):
    from tasks.mirror import search_road

    automation = route_automation()
    automation.find_element.side_effect = lambda path: path.endswith("legend_assets.png")
    monkeypatch.setattr(search_road, "auto", automation)
    # False means no recognized train, whereas the real recognition API returns None.
    automation.find_element.side_effect = lambda path: True if path.endswith("legend_assets.png") else None
    with pytest.raises(RuntimeError, match="no map input"):
        search_road._search_playcover_adjacent()
    automation.mouse_click.assert_not_called()
    automation.click_element.assert_not_called()


def test_ios_missing_theme_pack_never_rerolls_or_returns_home(monkeypatch):
    from module.config import cfg
    from tasks.mirror import select_theme_pack

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_element.return_value = None
    monkeypatch.setattr(select_theme_pack, "auto", automation)
    recover = Mock()
    monkeypatch.setattr(select_theme_pack, "back_init_menu", recover)
    with pytest.raises(RuntimeError, match="keep the current dungeon"):
        select_theme_pack.select_theme_pack()
    automation.click_element.assert_not_called()
    recover.assert_not_called()


def test_unknown_floor_is_zero_without_guessing_or_touch(monkeypatch):
    from module.config import cfg
    from tasks.mirror import get_floor

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_text_element.return_value = []
    monkeypatch.setattr(get_floor, "auto", automation)
    assert get_floor.get_floor(previous_floor=3) == 0
    automation.mouse_click.assert_not_called()
