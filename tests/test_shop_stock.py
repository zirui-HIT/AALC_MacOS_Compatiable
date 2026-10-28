"""Current-page stock recognition; special-shop examples are simulated explicitly."""

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tasks.mirror import shop_stock as task

FIXTURES = Path(__file__).parent / "fixtures" / "playcover"
COINS = (827, 205)


@pytest.fixture(autouse=True)
def template_paths(monkeypatch):
    from module.config import cfg
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn", "set_win_size": 1080}))
    monkeypatch.setattr(path_manager, "active_paths", ["default/share"])
    monkeypatch.setattr(path_manager, "current_theme", "default")
    monkeypatch.setattr(path_manager, "current_language", "zh_cn")
    task._cached_service_template.cache_clear()
    yield
    task._cached_service_template.cache_clear()


def output(entries):
    """Batch recognition preserves crop order, including repeated strings."""
    ordered = sorted(entries)
    return SimpleNamespace(txts=tuple(entry[2] for entry in ordered), scores=tuple(entry[3] for entry in ordered))


def stock_pixels(slots):
    """Synthetic bright price strokes; text recognition is mocked separately."""
    image = Image.new("L", (1920, 1080))
    draw = ImageDraw.Draw(image)
    for row, column in slots:
        x, y = 939.5 + column * 225, 475 + row * 225
        draw.rectangle((round(x), round(y - 10), round(x + 30), round(y + 10)), fill=200)
    return image


def mock_ocr(monkeypatch, result):
    class Lock:
        held = False

        def __enter__(self):
            self.held = True

        def __exit__(self, *args):
            self.held = False

    lock = Lock()

    def recognize(crops):
        assert lock.held
        return result

    run = Mock(side_effect=recognize)
    engine = SimpleNamespace(get_rec_res=run, use_det=True, use_rec=True, return_word_box=False)
    monkeypatch.setattr(task, "ocr", SimpleNamespace(engine=engine, _inference_lock=lock))
    return run


def matched_coins(monkeypatch, image):
    """Exercise the production matcher on this frame, without taking a capture."""
    from module.automation import auto

    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", image.convert("L"))
    coins = auto.find_element("mirror/shop/shop_coins_assets.png", model="clam")
    assert coins is not None
    return tuple(int(value) for value in coins)


@pytest.mark.parametrize("name", ["mirror_shop_stock_5", "mirror_shop_stock_4", "mirror_shop_stock_live"])
def test_real_shop_pixels_exclude_question_mark_service_before_batch_ocr(monkeypatch, name):
    metadata = json.loads((FIXTURES / f"{name}.json").read_text())
    slots = [(0, 1), (0, 2), (0, 3), (1, 0), (1, 1)]
    entries = [(row, col, str(price), 0.99) for (row, col), price in zip(slots, metadata["expected_prices"])]
    run = mock_ocr(monkeypatch, output(entries))
    with Image.open(FIXTURES / f"{name}.png") as image:
        original = image.tobytes()
        coins = matched_coins(monkeypatch, image)
        items = task.current_page_items(image, coins)
        assert image.tobytes() == original
    assert [item.price for item in items] == metadata["expected_prices"]
    assert [(item.row, item.column) for item in items] == slots[:len(items)]
    run.assert_called_once()
    crops = run.call_args.args[0]
    assert len(crops) == len(items)  # The service image never reaches recognition.
    assert all(crop.dtype == np.uint8 and crop.ndim == 3 and crop.shape[2] == 3 for crop in crops)
    assert all(np.any((crop > 0) & (crop < 255)) for crop in crops)  # Preserve original grayscale.
    assert vars(task.ocr.engine) == {"get_rec_res": run, "use_det": True, "use_rec": True, "return_word_box": False}
    with pytest.raises(FrozenInstanceError):
        items[0].price = 1


def test_duplicate_prices_remain_separate_items(monkeypatch):
    mock_ocr(monkeypatch, output([(1, 0, "152", 0.99), (0, 2, "152", 0.99), (0, 1, "152", 0.99)]))
    items = task.current_page_items(stock_pixels([(1, 0), (0, 2), (0, 1)]), COINS)
    assert [(item.row, item.column, item.price) for item in items] == [(0, 1, 152), (0, 2, 152), (1, 0, 152)]


@pytest.mark.parametrize("height", [720, 1080, 1440, 2160])
def test_price_bands_and_positions_follow_frame_height_not_global_window_size(monkeypatch, height):
    entries = [(0, 1, "152", 0.99), (0, 2, "155", 0.99), (0, 3, "219", 0.99),
               (1, 0, "183", 0.99), (1, 1, "250", 0.99)]
    run = mock_ocr(monkeypatch, output(entries))
    with Image.open(FIXTURES / "mirror_shop_stock_5.png") as original:
        image = original.resize((round(height * 16 / 9), height))
    coins = tuple(value * height / 1080 for value in COINS)
    items = task.current_page_items(image, coins)
    assert [item.price for item in items] == [152, 155, 219, 183, 250]
    assert items[0].position == pytest.approx((1164.5 * height / 1080, 400 * height / 1080))
    assert items[3].position == pytest.approx((939.5 * height / 1080, 625 * height / 1080))
    run.assert_called_once()


def test_simulated_special_shop_excludes_three_services_and_reordered_gifts(monkeypatch):
    """Synthetic special layout; this is not a captured special-shop fixture."""
    image = stock_pixels([(0, 3), (1, 0)])
    template = Image.fromarray(task._service_template(image.height))
    for column in range(3):
        center = (939.5 + column * 225, 475)
        image.paste(template, (round(center[0] - template.width / 2), round(center[1] - template.height / 2)))
    run = mock_ocr(monkeypatch, output([(0, 3, "219", 0.99), (1, 0, "148", 0.99)]))
    assert [item.price for item in task.current_page_items(image, COINS)] == [219, 148]
    assert len(run.call_args.args[0]) == 2
    mock_ocr(monkeypatch, output([(0, 0, "173", 0.99)]))
    item, = task.current_page_items(stock_pixels([(0, 0)]), COINS)
    assert (item.row, item.column, item.price) == (0, 0, 173)


@pytest.mark.parametrize("text,score", [
    ("", 1), ("??", 1), ("77?", 1), ("-2", 1), ("1.5", 1), ("1 52", 1),
    ("O", 1), ("1O0", 1), ("１２３", 1), ("152", 0.79), ("152", float("nan")),
    ("152", None), ("152", 1.01),
])
def test_invalid_or_unreliable_prices_are_not_guessed(monkeypatch, text, score):
    mock_ocr(monkeypatch, output([(0, 1, text, score)]))
    assert task.current_page_items(stock_pixels([(0, 1)]), COINS) == []


@pytest.mark.parametrize("result", [None, SimpleNamespace(txts=None, scores=None), output([])])
def test_empty_ocr_is_empty_stock(monkeypatch, result):
    mock_ocr(monkeypatch, result)
    assert task.current_page_items(stock_pixels([(0, 1)]), COINS) == []


def test_zero_is_a_price_but_multiple_prices_for_one_slot_are_ambiguous(monkeypatch):
    mock_ocr(monkeypatch, output([(0, 1, "0", 0.8), (0, 2, "152 219", 0.99)]))
    assert [item.price for item in task.current_page_items(stock_pixels([(0, 1), (0, 2)]), COINS)] == [0]


@pytest.mark.parametrize("texts,scores", [((), (1,)), (("152",), ()), (("152", "219"), (1, 1))])
def test_invalid_batch_lengths_are_not_assigned_to_gifts(monkeypatch, texts, scores):
    result = SimpleNamespace(txts=texts, scores=scores)
    mock_ocr(monkeypatch, result)
    assert task.current_page_items(stock_pixels([(0, 1)]), COINS) == []


def test_empty_pixels_skip_recognition(monkeypatch):
    run = mock_ocr(monkeypatch, output([]))
    assert task.current_page_items(Image.new("L", (1920, 1080)), COINS) == []
    run.assert_not_called()


def test_unavailable_service_template_fails_closed_without_ocr(monkeypatch):
    monkeypatch.setattr(task, "_service_template", lambda height: None)
    run = mock_ocr(monkeypatch, output([(0, 0, "77", 1)]))
    assert task.current_page_items(Image.new("L", (1920, 1080)), COINS) == []
    run.assert_not_called()


def test_service_pattern_is_reused_with_bounded_file_and_size_cache(monkeypatch):
    load = Mock(wraps=task.Image.open)
    monkeypatch.setattr(task.Image, "open", load)
    assert task._service_template(1080) is task._service_template(1080)
    assert load.call_count == 1
    for height in [720, 810, 1080, 1440, 2160, 1080]:
        assert task._service_template(height) is not None
    assert task._cached_service_template.cache_info().currsize == 4


def source_paths(monkeypatch, paths):
    from utils.path_manager import path_manager

    monkeypatch.setattr(path_manager, "active_paths", list(paths))
    monkeypatch.setattr(task.ImageUtils, "resolve_path", lambda profile, target: paths[profile])
    return path_manager


def write_pattern(path, seed):
    pixels = np.zeros((48, 96), dtype=np.uint8)
    pattern = np.random.default_rng(seed).integers(1, 256, size=(20, 50), dtype=np.uint8)
    pixels[10:30, 20:70] = pattern
    Image.fromarray(pixels).save(path, compress_level=0)
    return pattern


def test_missing_template_is_not_cached_and_appearing_file_is_loaded(monkeypatch, tmp_path):
    path = tmp_path / "service.png"
    source_paths(monkeypatch, {"default/source": path})
    assert task._service_template(1440) is None
    assert task._cached_service_template.cache_info().currsize == 0
    expected = write_pattern(path, 1)
    np.testing.assert_array_equal(task._service_template(1440), expected)


def test_different_actual_sources_do_not_share_a_pattern(monkeypatch, tmp_path):
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    a, b = write_pattern(first, 1), write_pattern(second, 2)
    first_stat = first.stat()
    os.utime(second, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns))
    assert first.stat().st_size == second.stat().st_size
    paths = source_paths(monkeypatch, {"default/first": first, "default/second": second})
    paths.active_paths = ["default/first"]
    first_template = task._service_template(1440)
    np.testing.assert_array_equal(first_template, a)
    paths.active_paths = ["default/second"]
    np.testing.assert_array_equal(task._service_template(1440), b)
    paths.active_paths = ["default/first"]
    assert task._service_template(1440) is first_template
    assert task._cached_service_template.cache_info().currsize == 2


def test_same_path_and_size_with_updated_mtime_loads_new_pixels(monkeypatch, tmp_path):
    path = tmp_path / "service.png"
    first = write_pattern(path, 1)
    source_paths(monkeypatch, {"default/source": path})
    np.testing.assert_array_equal(task._service_template(1440), first)
    previous = path.stat()
    second = write_pattern(path, 2)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns != previous.st_mtime_ns
    np.testing.assert_array_equal(task._service_template(1440), second)
    assert task._cached_service_template.cache_info().currsize == 2


@pytest.mark.parametrize("coins", [None, (), (827,), (-1000, 205), (827, -1000), (5000, 205), (float("nan"), 205)])
def test_invalid_anchor_does_not_run_ocr(monkeypatch, coins):
    run = mock_ocr(monkeypatch, output([]))
    assert task.current_page_items(Image.new("L", (1920, 1080)), coins) == []
    run.assert_not_called()


@pytest.mark.skipif(os.environ.get("AALC_SHOP_OCR_TEST") != "1", reason="Opt-in actual OCR replay")
@pytest.mark.parametrize("name", ["mirror_shop_stock_5", "mirror_shop_stock_4", "mirror_shop_stock_live"])
@pytest.mark.parametrize("dx", range(-3, 4))
@pytest.mark.parametrize("dy", range(-3, 4))
def test_actual_ocr_reads_complete_real_shop_stock_with_matched_anchor_jitter(monkeypatch, name, dx, dy):
    metadata = json.loads((FIXTURES / f"{name}.json").read_text())
    with Image.open(FIXTURES / f"{name}.png") as image:
        coins = matched_coins(monkeypatch, image)
        items = task.current_page_items(image, (coins[0] + dx, coins[1] + dy))
    assert [item.price for item in items] == metadata["expected_prices"]
