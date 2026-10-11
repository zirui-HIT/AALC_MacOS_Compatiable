"""Same-frame recognition reuse preserves results and never changes capture cadence."""

import threading
from contextlib import nullcontext
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def matcher(monkeypatch):
    module = import_module("module.automation.automation")
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_en", "set_win_size": 1080,
    }))
    for name, value in {"current_theme": "default", "current_language": "en",
                        "active_paths": ["default/share"], "version": 1}.items():
        monkeypatch.setattr(module.path_manager, name, value)
    auto = object.__new__(module.Automation)
    auto._screenshot_lock = threading.RLock()
    auto.memory_protection = False
    auto.img_cache, auto._ocr_regions, auto._unavailable_feature_templates = {}, {}, set()
    pixels = np.random.default_rng(42).integers(0, 256, (60, 80), dtype=np.uint8)
    auto.screenshot = Image.fromarray(pixels)
    template = pixels[18:28, 25:37].copy()
    monkeypatch.setattr(module.ImageUtils, "existing_image_paths", lambda _: ["default/share"])
    monkeypatch.setattr(auto, "_load_template_for_path", Mock(return_value=(template, None)))
    match = Mock(wraps=module.ImageUtils.match_template)
    monkeypatch.setattr(module.ImageUtils, "match_template", match)
    return auto, match, module


@pytest.mark.parametrize("score,expected", [(1.0, (31, 23)), (0.5, None)])
def test_positive_and_negative_results_are_reused_only_on_same_image(matcher, score, expected):
    auto, match, _ = matcher
    match.side_effect = lambda *args: ((31, 23), score)
    assert auto.find_image_element("sample.png", .8) == expected
    assert auto.find_image_element("sample.png", .8) == expected
    assert match.call_count == 1
    auto.screenshot = auto.screenshot.copy()
    assert auto.find_image_element("sample.png", .8) == expected
    assert match.call_count == 2
    assert auto.find_image_element("sample.png", .8, cacheable=False) == expected
    assert auto.find_image_element("sample.png", .8, cacheable=False) == expected
    assert match.call_count == 4


def test_read_only_consumers_share_one_array_conversion(matcher, monkeypatch):
    auto, match, module = matcher
    convert = Mock(wraps=np.asarray)
    monkeypatch.setattr(module.np, "asarray", convert)
    for _ in range(3):
        assert auto.find_image_element("sample.png", .8) == (31, 23)
        assert auto.calculate_click_position((31, 23), offset=False) == (31, 23)
    assert match.call_count == convert.call_count == 1
    np.testing.assert_array_equal(auto.get_screenshot_array(), np.array(auto.screenshot))


@pytest.mark.parametrize("changed", [
    {"threshold": .9}, {"model": "normal"}, {"my_crop": [0, 0, 70, 50]},
])
def test_matching_parameters_and_exact_crop_coordinates_are_separate(matcher, changed):
    auto, match, _ = matcher
    assert auto.find_image_element("sample.png", .8) == (31, 23)
    options = {"threshold": .8, **changed}
    assert auto.find_image_element("sample.png", **options) == (31, 23)
    assert auto.find_image_element("sample.png", **options) == (31, 23)
    assert match.call_count == 2


@pytest.mark.parametrize("scope", ["theme", "language", "paths", "version", "profile", "resolution"])
def test_path_profile_and_geometry_settings_do_not_reuse_old_results(matcher, monkeypatch, scope):
    auto, match, module = matcher
    auto.find_image_element("sample.png", .8)
    if scope in {"profile", "resolution"}:
        update = {"game_profile": "ios_zh_cn"} if scope == "profile" else {"set_win_size": 1440}
        monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update=update))
    else:
        name, value = {"theme": ("current_theme", "dark"), "language": ("current_language", "zh_cn"),
                       "paths": ("active_paths", ["dark/share"]), "version": ("version", 2)}[scope]
        monkeypatch.setattr(module.path_manager, name, value)
    assert auto.find_image_element("sample.png", .8) == (31, 23)
    assert match.call_count == 2


@pytest.mark.parametrize("failure", [False, True])
def test_touch_and_failed_touch_invalidate_recognition_results(matcher, monkeypatch, failure):
    from module.backends import factory

    auto, match, _ = matcher
    auto.find_image_element("sample.png", .8)
    geometry = SimpleNamespace(version=1)
    session = Mock()
    session.geometry.return_value = geometry
    session.input.geometry_context.return_value = nullcontext()
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    frame = SimpleNamespace(geometry_version=1, geometry=geometry)
    def touch():
        if failure:
            raise RuntimeError("lost touch")
    if failure:
        with pytest.raises(RuntimeError, match="lost touch"):
            auto._invoke_input(touch, frame)
    else:
        auto._invoke_input(touch, frame)
    assert auto.find_image_element("sample.png", .8) == (31, 23)
    assert match.call_count == 2
    auto.clear_img_cache()  # Resource updates use this existing invalidation path.
    assert auto.find_image_element("sample.png", .8) == (31, 23)
    assert match.call_count == 3


def test_unknown_theme_or_language_still_runs_original_path_discovery(matcher, monkeypatch):
    auto, match, module = matcher
    monkeypatch.setattr(module.path_manager, "current_theme", None)
    monkeypatch.setattr(module.path_manager, "current_language", None)
    monkeypatch.setattr(module.ImageUtils, "existing_image_paths", lambda _: ["dark/share", "default/share"])
    match.side_effect = [((31, 23), 1.0), ((0, 0), .1)] * 2
    for _ in range(2):
        assert auto.find_image_element("sample.png", .8) == (31, 23)
    assert module.path_manager.current_theme == "dark"
    assert module.path_manager.current_language is None  # Shared templates cannot determine language.
    assert match.call_count == 4


@pytest.mark.parametrize("image", [None, np.array(1), np.zeros((4,)), np.zeros((2, 2, 2, 2)), Image.new("L", (0, 0))])
def test_invalid_screenshot_never_reaches_template_matching(matcher, image):
    auto, match, _ = matcher
    auto.screenshot = image
    assert auto.find_image_element("sample.png", .8) is None
    assert auto.find_image_with_multiple_targets("sample.png", .8) == []
    match.assert_not_called()


def test_template_utility_rejects_unsupported_dimensions_before_opencv(matcher, monkeypatch):
    _, _, module = matcher
    cv_match = Mock()
    monkeypatch.setattr(module.cv2, "matchTemplate", cv_match)
    assert module.ImageUtils.match_template(np.array(1), np.ones((2, 2)), None) is None
    cv_match.assert_not_called()


def test_multiple_matches_return_independent_lists_and_keep_crop_offsets(matcher, monkeypatch):
    auto, _, module = matcher
    monkeypatch.setattr(module.ImageUtils, "load_image", lambda _: np.ones((4, 4), dtype=np.uint8))
    match = Mock(return_value=[(5, 6), (15, 16)])
    monkeypatch.setattr(module.ImageUtils, "match_template_with_multiple_targets", match)
    first = auto.find_image_with_multiple_targets("sample.png", .8, my_crop=[10, 10, 40, 40])
    assert first == [(15, 16), (25, 26)]
    first.clear()
    assert auto.find_image_with_multiple_targets("sample.png", .8, my_crop=(10, 10, 40, 40)) == [(15, 16), (25, 26)]
    assert match.call_count == 1
    auto.find_image_with_multiple_targets("sample.png", .8, min_dist=20, my_crop=(10, 10, 40, 40))
    assert match.call_count == 2


@pytest.mark.parametrize("height", [810, 1080])
def test_real_ios_frame_cached_and_uncached_matches_keep_exact_coordinates(matcher, monkeypatch, height):
    from utils.runtime_paths import SOURCE_ROOT

    auto, match, module = matcher
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"set_win_size": height}))
    del auto._load_template_for_path  # Use the original template loading and scaling.
    with Image.open(SOURCE_ROOT / "tests/fixtures/playcover/formation_selected.png") as image:
        auto.screenshot = image.convert("L").resize((height * 16 // 9, height))
    expected = auto.find_image_element("teams/selected.png", .8, cacheable=False)
    assert expected is not None
    assert auto.find_image_element("teams/selected.png", .8) == expected
    count = match.call_count
    for _ in range(3):
        assert auto.find_image_element("teams/selected.png", .8) == expected
    assert match.call_count == count
