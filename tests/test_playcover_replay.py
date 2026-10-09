import json

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
    ("sign_in", ["base/sign_in_assets.png"]),
    ("title", ["base/touch_to_start_assets.png", "base/clear_all_caches_assets.png"]),
    ("formation", ["teams/identify_assets.png", "battle/chaim_to_battle_assets.png"]),
    ("formation_selected", ["teams/clear_selection.png", "battle/chaim_to_battle_assets.png"]),
    ("battle_selected", ["battle/gear_start.png", "battle/win_rate_card.png"]),
    ("reaccept_win_rate_selected", ["battle/start_label.png", "battle/gear_start.png", "battle/win_rate_card.png"]),
    ("luxcavation", ["home/back_assets.png"]),
    ("reaccept_thread_ready", ["battle/turn_assets.png", "battle/start_label.png"]),
    ("reaccept_defeat", ["battle/battle_finish_confirm_assets.png", "base/only_option_assets.png"]),
    ("victory", ["battle/victory.png", "battle/battle_finish_confirm_assets.png"]),
    ("reset_deployment", ["teams/reset_deployment.png", "teams/clear_selection_confirm_assets.png"]),
    ("mirror_map", ["mirror/road_in_mir/legend_assets.png", "mirror/mybus_default_distance.png"]),
    ("mirror_theme_pack", ["mirror/theme_pack/normal_assets.png", "mirror/theme_pack/theme_pack_features.png"]),
    ("mirror_guide", ["home/back_ios.png"]),
    ("mirror_battle_ready", ["battle/win_rate_card.png", "battle/gear_right.png"]),
    ("mirror_map_floor2", ["mirror/road_in_mir/legend_assets.png", "mirror/mybus_default_distance.png"]),
    ("mirror_map_floor3", ["mirror/road_in_mir/legend_assets.png", "mirror/mybus_default_distance.png"]),
    ("mirror_completed", ["mirror/claim_reward/complete_mirror_100%_assets.png", "mirror/claim_reward/claim_rewards_assets.png"]),
    ("mirror_reward_preview", ["mirror/claim_reward/reward_preview_assets.png",
                               "mirror/claim_reward/completed_five_floors_assets.png",
                               "mirror/claim_reward/claim_modules_assets.png", "mirror/claim_reward/use_enkephalin_assets.png"]),
    ("energy_max_disabled", ["enkephalin/all_in_assets.png"]),
    ("mirror_entry_real", ["mirror/entry/landing_enter_assets.png", "mirror/road_to_mir/enter_assets.png"]),
    ("mirror_after_enter", ["mirror/entry/entry_prompt_assets.png", "mirror/entry/entry_confirm_assets.png", "mirror/road_to_mir/enter_mirror_assets.png"]),
    ("mirror_team_settled", ["mirror/entry/preset_assets.png", "mirror/entry/preset_confirm_assets.png", "mirror/road_to_mir/select_team_stars_assets.png", "mirror/road_to_mir/select_team_confirm_assets.png"]),
    ("mirror_team_confirmed", ["mirror/entry/grace_assets.png", "mirror/entry/grace_enter_assets.png", "mirror/road_to_mir/dreaming_star/coins_assets.png"]),
    ("mirror_grace_enter", ["mirror/entry/grace_prompt_assets.png", "mirror/entry/grace_confirm_assets.png",
                            "mirror/entry/convert_checked_assets.png"]),
    ("mirror_start_gifts", ["mirror/entry/gift_page_assets.png", "mirror/entry/search_on_assets.png",
                            "mirror/entry/bleed_assets.png"]),
    ("mirror_gift_selected", ["mirror/entry/wound_clerid_assets.png"]),
    ("mirror_gift_one", ["mirror/entry/gift_select_assets.png"]),
    ("mirror_pass_level_up", ["mirror/claim_reward/pass_level_up_assets.png",
                              "mirror/claim_reward/pass_level_confirm_assets.png"]),
    ("mirror_reward_confirm", ["mirror/claim_reward/reward_confirm_prompt_assets.png",
                               "mirror/claim_reward/reward_final_confirm_assets.png", "mirror/claim_reward/claim_rewards_confirm_assets.png"]),
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


def test_feature_matching_blank_roi_is_a_normal_miss():
    import numpy as np

    from utils.image_utils import ImageUtils

    blank = np.zeros((100, 100), dtype=np.uint8)
    assert ImageUtils.feature_matching(blank, blank) == (False, 0)


@pytest.mark.parametrize("page", ["mirror_reward_confirm", "mirror_grace_enter", "energy_max_disabled"])
def test_single_option_battle_exit_does_not_match_resource_confirmation(monkeypatch, page):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en", "set_win_size": 1080}))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", Image.open(SOURCE_ROOT / f"tests/fixtures/playcover/{page}.png").convert("L"))
    assert not auto.find_element("base/only_option_assets.png", model="clam")
