"""Observation settings and upstream selection work without live game input."""

from unittest.mock import Mock, call

import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT

OBSERVE = "mirror/road_to_mir/observe_ego_gift/"


@pytest.fixture
def preserve_shop_catalogs():
    from tasks import mirror

    previous = {name: list(getattr(mirror, name)) for name in ("must_purchase", "must_be_abandoned", "fusion_result")}
    yield
    for name, values in previous.items():
        getattr(mirror, name)[:] = values


def test_observation_uses_latest_saved_team_setting_without_changing_it():
    from module.config.config_typing import TeamSetting
    from tasks.mirror.mirror import Mirror
    original = TeamSetting(observe_ego_gift=True, observe_ego_gift_selected=['general_3_4_8'])
    dungeon = Mirror(original, 1)
    assert dungeon.observe_ego_gift
    assert dungeon.observe_ego_gift_selected == ['general_3_4_8']
    dungeon.observe_ego_gift_selected.append('burn_1_1_1')
    assert original.observe_ego_gift_selected == ['general_3_4_8']


@pytest.mark.parametrize("profile", ["ios_en", "ios_zh_cn"])
@pytest.mark.parametrize("height", [1080, 1440])
@pytest.mark.parametrize("synced", [False, True])
def test_upstream_observation_templates_find_both_anchors_in_real_ios_frame(monkeypatch, tmp_path, preserve_shop_catalogs, profile, height, synced):
    from module.automation import auto
    from module.config import cfg
    from utils.image_utils import ImageUtils
    from utils.path_manager import path_manager

    monkeypatch.setattr("utils.image_utils.data_path", lambda path: tmp_path / path)
    monkeypatch.setattr("utils.image_catalog.data_path", lambda path: tmp_path / path)
    if synced:
        # An older authoritative image tree has none of the new shared assets.
        state = tmp_path / "config/image_resource_state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"last_applied_manifest_id": "before-observation-update"}')
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": profile, "set_win_size": height,
    }))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    with Image.open(SOURCE_ROOT / "tests/fixtures/playcover/observe_general_tier3_grid.png") as image:
        frame = image.convert("L").resize((round(height * 16 / 9), height))
    monkeypatch.setattr(auto, "screenshot", frame)
    monkeypatch.setattr(auto, "model", "clam")
    for name in ("burn.png", "bleed.png", "observe_bbox.png"):
        resolved = ImageUtils.resolve_path("default/" + profile, OBSERVE + name)
        assert resolved.read_bytes() == (SOURCE_ROOT / "assets/images/default/share" / (OBSERVE + name)).read_bytes()
    bounds = ImageUtils.get_bbox(ImageUtils.load_image(OBSERVE + "observe_bbox.png"))
    burn = auto.find_element(OBSERVE + "burn.png", my_crop=bounds)
    bleed = auto.find_element(OBSERVE + "bleed.png", my_crop=bounds)
    assert burn is not None and bleed is not None
    scale = height / 1080
    assert burn == pytest.approx((155 * scale, 277 * scale), abs=2)
    assert bleed == pytest.approx((238 * scale, 277 * scale), abs=2)
    assert bounds[0] <= burn[0] < bleed[0] <= bounds[2]
    assert bounds[1] <= burn[1] <= bounds[3]


@pytest.mark.parametrize("gift,index", [("burn", 0), ("sinking", 4), ("general", 10)])
@pytest.mark.parametrize("scroll_to_level", [False, True])
def test_upstream_observation_uses_measured_spacing_and_keeps_level_scroll(monkeypatch, gift, index, scroll_to_level):
    from module.config import TeamSetting, cfg
    from tasks.mirror import mirror as task

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": 1080}))
    dungeon = task.Mirror(TeamSetting(observe_ego_gift=True, observe_ego_gift_selected=[f"{gift}_3_1_1"]), 1)
    dungeon.observe_bbox = (0, 200, 1300, 350)
    burn, bleed = (180, 280), (273, 280)  # Deliberately differs from the former 110 * scale.
    automation = Mock()
    burns = iter([None, burn])  # A late first anchor exercises the bounded lookup retry.
    levels = iter([None, (200, 400)] if scroll_to_level else [(200, 400)])

    def find(path, **kwargs):
        if path == OBSERVE + "burn.png":
            return next(burns)
        if path == OBSERVE + "bleed.png":
            return bleed
        if path == OBSERVE + "Level_III.png":
            return next(levels)
        raise AssertionError(path)

    automation.find_element.side_effect = find
    automation.find_language_text.return_value = None
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", Mock())
    monkeypatch.setattr(task.ImageUtils, "load_image", lambda _: None)
    monkeypatch.setattr(task.ImageUtils, "get_bbox", lambda _: (0, 350, 1400, 900))
    dungeon.select_observe_ego_gift()
    assert automation.mouse_click.call_args_list == [
        call(*bleed), call(*burn), call(*burn), call(*bleed),
        call(burn[0] + (bleed[0] - burn[0]) * index, burn[1]), call(200, 460),
    ]
    assert automation.find_element.call_args_list[:3] == [
        call(OBSERVE + "bleed.png", my_crop=dungeon.observe_bbox, take_screenshot=True),
        call(OBSERVE + "burn.png", my_crop=dungeon.observe_bbox, take_screenshot=True),
        call(OBSERVE + "burn.png", my_crop=dungeon.observe_bbox, take_screenshot=True),
    ]
    level_calls = [c for c in automation.find_element.call_args_list if c.args[0] == OBSERVE + "Level_III.png"]
    assert level_calls == [call(OBSERVE + "Level_III.png", threshold=0.85, take_screenshot=True)] * (1 + scroll_to_level)
    assert automation.mouse_drag.call_count == int(scroll_to_level)
    assert all(c == call(0.5) for c in task.sleep.call_args_list)


@pytest.mark.parametrize("missing", ["burn", "bleed", "both"])
def test_missing_observation_anchor_exits_after_three_attempts_without_selecting(monkeypatch, missing):
    from module.config import TeamSetting
    from tasks.mirror import mirror as task

    dungeon = task.Mirror(TeamSetting(observe_ego_gift=True, observe_ego_gift_selected=["general_3_1_1"]), 1)
    dungeon.observe_bbox = (0, 200, 1300, 350)
    automation = Mock()
    automation.find_element.side_effect = lambda path, **kwargs: (
        None if missing == "both" or path == OBSERVE + missing + ".png" else (180, 280))
    monkeypatch.setattr(task, "auto", automation)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    dungeon.select_observe_ego_gift()
    assert automation.find_element.call_count == (6 if missing == "both" else 4)
    assert automation.mouse_click.call_count == int(missing != "both")
    automation.mouse_drag.assert_not_called()
    automation.find_language_text.assert_not_called()
    automation.click_element.assert_not_called()
