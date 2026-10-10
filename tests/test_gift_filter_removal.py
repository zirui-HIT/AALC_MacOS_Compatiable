"""Offline coverage for removing White Gossypium filters, including old configs."""
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize("legacy_flag", [False, True])
@pytest.mark.parametrize("count,first_owned,chosen", [
    (1, False, 0), (2, False, 0), (2, True, 1),
    (3, False, 0), (3, True, 1),
])
def test_reward_uses_ordinary_gift_rules_without_name_ocr(
    monkeypatch, legacy_flag, count, first_owned, chosen,
):
    from module.config import cfg
    from module.config.config_typing import ConfigModel
    from tasks.mirror import mirror as task

    settings = ConfigModel.model_validate({**cfg.config.model_dump(),
        "not_skip_whitegossypium": legacy_flag, "set_win_size": 1080})
    assert "not_skip_whitegossypium" not in settings.model_dump()
    monkeypatch.setattr(cfg, "config", settings)
    buttons = [(400, 600), (1000, 600), (1600, 600)][:count]
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: (
        buttons if path.endswith("acquire_ego_gift_card.png") else False)
    automation.click_element.side_effect = lambda path, **kwargs: path.endswith("acquire_ego_gift_select_assets.png")

    def language(zh, en, bbox):
        if en == "Owned":
            return first_owned and bbox[0] == buttons[0][0] - 37.5
        return [(0, 0), (1, 1)]  # Would identify White Gossypium in the old filter.

    automation.find_language_text.side_effect = language
    automation.find_text_element.return_value = True  # Choose one of several gifts.
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task.time, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", lambda: True)
    monkeypatch.setattr(task.ImageUtils, "load_image", Mock())
    monkeypatch.setattr(task.ImageUtils, "get_bbox", lambda _: (0, 0, 1920, 1080))
    task.Mirror(cfg.config.teams["1"], 1).acquire_ego_gift()
    automation.mouse_click.assert_called_once_with(*buttons[chosen])
    queries = automation.find_language_text.call_args_list
    assert len(queries) == (0 if count == 1 else count)
    assert all(query.args[1] == "Owned" for query in queries)
    assert not any("refuse_gift" in query.args[0] for query in automation.click_element.call_args_list)


@pytest.mark.parametrize("secondary", [False, True])
def test_bleed_shop_purchase_has_no_name_ocr_or_filter_wait(monkeypatch, secondary):
    from module.config import cfg
    from tasks import all_systems
    from tasks.mirror import in_shop as task

    team = cfg.config.teams["1"].model_copy(update={
        "team_system": next(key for key, name in all_systems.items() if name == "bleed"),
        "shop_strategy": 0, "shopping_strategy": True,
        "shopping_strategy_select": 1 if secondary else 2,
        "second_system": secondary, "second_system_setting": 1,
        "second_system_action": [False, True, False],
        "max_keyword_refresh": 0, "max_normal_refresh": 0,
    })
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: (
        [(400, 600)] if path.startswith("mirror/shop/enhance_gifts/shop_") else None)
    automation.click_element.side_effect = lambda path, **kwargs: path in {
        "mirror/shop/purchase_assets.png", "mirror/road_in_mir/ego_gift_get_confirm_assets.png"}
    automation.find_language_text.return_value = [(0, 0), (1, 1)]
    waits = Mock()
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", waits)
    monkeypatch.setattr(task, "retry", lambda: True)
    shop = task.Shop(team)
    shop._get_cost = Mock(return_value=0)
    shop.buy_gifts()
    automation.find_language_text.assert_not_called()
    assert sum(query.args[0] == "mirror/shop/purchase_assets.png"
               for query in automation.click_element.call_args_list) == 1
    assert waits.call_args_list == [call(1), call(1)]
