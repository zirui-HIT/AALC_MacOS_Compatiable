from unittest.mock import Mock

import pytest


def test_unknown_floor_is_zero_without_guessing_or_touch(monkeypatch):
    from module.config import cfg
    from tasks.mirror import get_floor

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    automation = Mock()
    automation.find_element.return_value = None
    monkeypatch.setattr(get_floor, "auto", automation)
    assert get_floor.get_floor(previous_floor=3) == 0
    automation.mouse_click.assert_not_called()


@pytest.mark.parametrize("height", [1080, 1440])
@pytest.mark.parametrize("panel_shift", [0, -44])
def test_original_floor_detection_counts_real_clear_badges(monkeypatch, height, panel_shift):
    from PIL import Image

    from module.automation import auto
    from module.config import cfg
    from tasks.mirror import get_floor
    from utils.path_manager import path_manager
    from utils.runtime_paths import SOURCE_ROOT

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_en", "set_win_size": height,
    }))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    frame = Image.open(SOURCE_ROOT / "tests/fixtures/playcover/mirror_floor5_progress.png").convert("RGB")
    if panel_shift:
        # Synthetic displacement checks the original and observed iOS panel positions.
        shifted = Image.new("RGB", frame.size)
        shifted.paste(frame, (0, panel_shift))
        frame = shifted
    frame = frame.resize((round(height * 16 / 9), height))

    def capture(gray=True, **kwargs):
        auto.screenshot = frame.convert("L") if gray else frame.copy()
        return auto.screenshot

    original_find = auto.find_element

    def find(target, **kwargs):
        # The fixture starts with the panel open. Only opening input is simulated;
        # panel confirmation, color capture and CLEAR counting use production code.
        if target.endswith("/setting_assets.png"):
            return (1810, 70)
        return original_find(target, **kwargs)

    monkeypatch.setattr(auto, "take_screenshot", capture)
    monkeypatch.setattr(auto, "find_element", find)
    monkeypatch.setattr(auto, "model", "clam")
    monkeypatch.setattr(auto, "mouse_action_with_pos", Mock())
    monkeypatch.setattr(auto, "mouse_click_blank", Mock())
    monkeypatch.setattr(get_floor, "sleep", lambda _: None)
    # A deliberately different previous value proves recognition does not guess +1.
    assert get_floor.get_floor(previous_floor=1) == 5
    auto.mouse_action_with_pos.assert_called_once()
    auto.mouse_click_blank.assert_called_once()


def test_native_floor_region_keeps_original_coordinates(monkeypatch):
    from module.config import cfg
    from tasks.mirror.get_floor import FLOOR_BAND_ROI
    from utils.image_utils import ImageUtils

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "auto"}))
    assert ImageUtils.layout("mirror.floor_band", FLOOR_BAND_ROI) == FLOOR_BAND_ROI


@pytest.mark.parametrize("page,claim", [("mirror_reward_confirm", True), ("mirror_reward_forfeit_confirm", False)])
def test_reward_confirmation_template_distinguishes_forfeiting(monkeypatch, page, claim):
    from PIL import Image

    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager
    from utils.runtime_paths import SOURCE_ROOT

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_en", "set_win_size": 1080,
    }))
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", Image.open(SOURCE_ROOT / f"tests/fixtures/playcover/{page}.png").convert("L"))
    point = auto.find_element("mirror/claim_reward/claim_rewards_confirm_assets.png", threshold=0.75, model="clam")
    assert bool(point) == claim
    if point:
        assert 992 < point[0] < 1300 and 711 < point[1] < 770
