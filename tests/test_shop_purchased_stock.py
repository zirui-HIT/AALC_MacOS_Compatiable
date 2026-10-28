"""Real purchased stamps prevent repeated clicks on gifts that retain prices."""

import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from tasks.mirror import shop_stock
from utils.runtime_paths import SOURCE_ROOT

FIXTURES = SOURCE_ROOT / "tests/fixtures/playcover"


@pytest.fixture
def recognition(monkeypatch):
    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "game_profile": "ios_zh_cn", "set_win_size": 1080,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", None)
    shop_stock._cached_service_template.cache_clear()
    yield cfg, auto
    shop_stock._cached_service_template.cache_clear()


@pytest.mark.parametrize("height", [720, 1080, 1440, 2160])
def test_real_sold_out_page_needs_no_price_inference(recognition, monkeypatch, height):
    cfg, auto = recognition
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": height}))
    image = Image.open(FIXTURES / "mirror_shop_all_purchased.png").resize((round(height * 16 / 9), height))
    auto.screenshot = image
    coins = auto.find_element("mirror/shop/shop_coins_assets.png", model="clam")
    assert coins
    inference = Mock(side_effect=AssertionError("Purchased gifts must be removed before OCR"))
    monkeypatch.setattr(shop_stock, "ocr", SimpleNamespace(
        engine=SimpleNamespace(get_rec_res=inference), _inference_lock=threading.RLock(),
    ))
    assert shop_stock.current_page_items(image, coins) == []
    inference.assert_not_called()


@pytest.mark.skipif(os.environ.get("AALC_SHOP_OCR_TEST") != "1", reason="Opt-in actual OCR replay")
@pytest.mark.parametrize("name", [
    "mirror_shop_part_purchased", "mirror_shop_stock_4", "mirror_shop_stock_5", "mirror_shop_stock_live",
])
def test_real_partial_and_fresh_pages_keep_only_unpurchased_gifts(recognition, name):
    _, auto = recognition
    image = Image.open(FIXTURES / f"{name}.png")
    auto.screenshot = image.convert("L")
    coins = auto.find_element("mirror/shop/shop_coins_assets.png", model="clam")
    assert coins
    metadata = json.loads((FIXTURES / f"{name}.json").read_text())
    items = shop_stock.current_page_items(image, coins)
    assert [item.price for item in items] == metadata["expected_prices"]
