"""Actual hybrid purchase dialog and crop-relative OCR button coordinates."""

from unittest.mock import Mock

import pytest
from PIL import Image

from tasks.mirror import quick_shop
from utils.runtime_paths import SOURCE_ROOT


@pytest.fixture
def recognition(monkeypatch):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_zh_cn", "set_win_size": 1080,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "model", "clam")
    monkeypatch.setattr(auto, "screenshot", None)
    return cfg, auto, path_manager


@pytest.mark.parametrize("height", [810, 1080, 1440])
@pytest.mark.parametrize("theme", ["default", "dark"])
def test_real_hybrid_purchase_button_is_detected_at_its_actual_position(recognition, monkeypatch, height, theme):
    cfg, auto, paths = recognition
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": height}))
    paths.set_theme(theme)
    auto.screenshot = Image.open(SOURCE_ROOT / "tests/fixtures/playcover/mirror_shop_purchase.png").resize(
        (round(height * 16 / 9), height))
    fallback = Mock(side_effect=AssertionError("Real purchase image should not need OCR"))
    monkeypatch.setattr(auto, "find_language_text", fallback)
    point = quick_shop._purchase_position()
    assert point is not None
    x, y = [value * 1080 / height for value in point]
    assert 1090 < x < 1180 and 700 < y < 755


def test_ocr_fallback_converts_crop_coordinates_to_full_frame(recognition, monkeypatch):
    _, auto, _ = recognition
    auto.screenshot = Image.new("L", (1920, 1080))
    monkeypatch.setattr(auto, "find_element", Mock(return_value=None))
    ocr = Mock(return_value=[30, 25])
    monkeypatch.setattr(auto, "find_language_text", ocr)
    point = quick_shop._purchase_position()
    region = ocr.call_args.kwargs["my_crop"]
    assert point == [region[0] + 30, region[1] + 25]
    assert 950 < point[0] < 1280 and 630 < point[1] < 820


def test_real_item_grid_does_not_match_the_modal_purchase_button(recognition, monkeypatch):
    _, auto, _ = recognition
    auto.screenshot = Image.open(SOURCE_ROOT / "tests/fixtures/playcover/mirror_shop_stock_4.png").convert("L")
    monkeypatch.setattr(auto, "find_language_text", Mock(return_value=False))
    assert quick_shop._purchase_position() is None


def test_missing_purchase_resource_returns_without_blind_coordinate(recognition, monkeypatch):
    _, auto, _ = recognition
    auto.screenshot = Image.new("L", (1920, 1080))
    monkeypatch.setattr(auto, "find_element", Mock(return_value=None))
    monkeypatch.setattr(quick_shop.ImageUtils, "load_image", lambda _: None)
    fallback = Mock()
    monkeypatch.setattr(auto, "find_language_text", fallback)
    assert quick_shop._purchase_position() is None
    fallback.assert_not_called()
