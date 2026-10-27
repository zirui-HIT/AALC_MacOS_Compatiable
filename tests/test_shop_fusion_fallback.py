"""Exercise the existing ordinary fusion after an aggressive anchor miss."""

from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize(
    "anchor,selected",
    [
        (None, [(100, 100), (200, 200), (300, 300)]),
        (350, [(400, 400), (500, 500), (600, 600)]),
    ],
)
def test_missing_aggressive_anchor_preserves_ordinary_fusion(monkeypatch, anchor, selected):
    from module.config import TeamSetting
    from tasks.mirror import in_shop as task

    automation = Mock()
    candidates_seen = False

    def find(path, **kwargs):
        nonlocal candidates_seen
        if path == "mirror/shop/fuse_label.png":
            return []
        if path == "unused-gift.png" and not candidates_seen:
            candidates_seen = True
            return [(i * 100, i * 100) for i in range(1, 7)]
        if path == "mirror/road_in_mir/ego_gift_get_confirm_assets.png":
            return (900, 700)
        return None

    automation.find_element.side_effect = find
    automation.take_screenshot.return_value = True
    automation.click_element.return_value = True
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    monkeypatch.setattr(task, "retry", Mock(return_value=True))
    monkeypatch.setattr(task, "must_be_abandoned", ["unused-gift.png"])
    shop = task.Shop(TeamSetting())
    shop.fuse_switch = shop.fuse_aggressive_switch = True
    shop.only_system_fuse = shop.only_aggressive_fuse = False
    shop.do_not_system_fuse = True
    shop.second_system = False
    shop.shop_sell_list = []
    shop.the_first_line_position = anchor
    shop.enter_fuse = Mock(return_value=True)

    shop.fuse_gift()

    assert automation.mouse_click.call_args_list == [call(*position) for position in selected]
    assert shop.the_first_line_position == anchor
    assert shop.enter_fuse.call_count == 3
    task.retry.assert_called_once_with()
