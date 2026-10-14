"""OCR routing, validation and cache isolation; never interact with the game."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image
from rapidocr.utils.output import RapidOCROutput


def output(*texts):
    return RapidOCROutput(
        txts=texts, scores=(1.0,) * len(texts),
        boxes=np.asarray([[[1, 2], [9, 2], [9, 6], [1, 6]]] * len(texts)).reshape(-1, 4, 2),
    )


@pytest.fixture
def recognition(monkeypatch):
    module = import_module("module.automation.automation")
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"game_profile": "ios_en"}))
    monkeypatch.setattr(module.path_manager, "current_language", "en")
    monkeypatch.setattr(module.theme_list, "config", {"theme_pack_list": {"outcast": 3, "unknown": -5}})
    engines = SimpleNamespace(run=Mock(return_value=output("rapid")), run_vision=Mock(return_value=output("Select")))
    monkeypatch.setattr(module, "ocr", engines)
    auto = object.__new__(module.Automation)
    auto.screenshot = Image.new("RGB", (1000, 700))
    auto._ocr_image = None
    auto._ocr_regions = {}
    auto._ocr_lock = threading.RLock()
    return auto, engines, module


def test_cache_invalidation_waits_for_an_in_progress_ocr_lookup(recognition):
    auto, engines, module = recognition
    reading, resume, clearing, cleared = (threading.Event() for _ in range(4))
    result = output("cached")

    class PausedLookup(dict):
        def __getitem__(self, key):
            reading.set()
            assert resume.wait(2)
            return super().__getitem__(key)

    auto._ocr_image = auto.screenshot
    auto._ocr_regions = PausedLookup({(None, "rapid", module.cfg.game_profile): result})
    auto.img_cache = {}
    auto._unavailable_feature_templates = set()

    def invalidate():
        clearing.set()
        auto.clear_img_cache()
        cleared.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        lookup = workers.submit(auto._ocr_screenshot)
        try:
            assert reading.wait(2)
            invalidation = workers.submit(invalidate)
            assert clearing.wait(2)
            assert not cleared.wait(0.1)
        finally:
            resume.set()
        assert lookup.result(timeout=2) is result
        invalidation.result(timeout=2)
    assert auto._ocr_image is None
    assert not auto._ocr_regions
    engines.run.assert_not_called()


def test_owned_uses_header_for_both_engines_without_changing_coordinates(recognition):
    auto, engines, _ = recognition
    engines.run_vision.return_value = None
    engines.run.return_value = output("Owned")
    assert auto.find_language_text("已持有", "Owned", (100, 20, 600, 670)) == [5, 4]
    assert engines.run.call_args.args[0].size == (500, 104)
    assert engines.run_vision.call_args.args[0].size == (500, 104)


def test_owned_empty_header_is_a_valid_negative(recognition):
    auto, engines, _ = recognition
    engines.run_vision.return_value = output()
    engines.run.return_value = output("most-owned least-owned")
    assert auto.find_language_text("已持有", "Owned", (100, 20, 600, 670)) is False
    engines.run.assert_not_called()


@pytest.mark.parametrize("text,valid", [
    ("0/1", True), ("Select 0 / 1", True), ("1/2", True), ("2/2", True),
    ("elect U/1", False), ("2/1", False), ("0/3", False), ("10/1", False),
    ("01", False), ("0/1 and 0/2", False), ("", False),
])
def test_count_syntax_decides_fallback_even_at_confidence_one(recognition, text, valid):
    auto, engines, _ = recognition
    engines.run_vision.return_value = output(text)
    auto.find_text_element(["0/1", "01", "1/1", "11", "1/2", "12", "/1"], (0, 0, 300, 200))
    assert engines.run.call_count == (0 if valid else 1)


def test_two_count_branches_share_one_field_validation(recognition):
    auto, engines, _ = recognition
    engines.run_vision.return_value = output("0/2")
    crop = (0, 0, 300, 200)
    assert auto.find_text_element(["0/1", "01", "1/1", "11", "1/2", "12", "/1"], crop) is False
    assert auto.find_text_element(["0/2", "02", "2/2", "22", "/2"], crop) == [5, 4]
    engines.run_vision.assert_called_once()
    engines.run.assert_not_called()


def test_pack_uses_passed_keywords_and_preserves_weights(recognition):
    auto, engines, _ = recognition
    engines.run_vision.return_value = output("The Jutcast")
    engines.run.return_value = output("The Outcast")
    result = auto.find_language_text({}, {"outcast": 17, "unknown": -5}, (0, 0, 300, 450))
    assert (result.value, result.text, result.position) == (17, "outcast", [5, 4])
    engines.run.assert_called_once()


def test_unrecognized_pack_dictionary_keeps_rapid(recognition):
    auto, engines, _ = recognition
    auto.find_language_text({}, {"new custom pack": 8, "unknown": -5}, (0, 0, 300, 450))
    engines.run_vision.assert_not_called()


def test_button_validation_is_per_target_but_raw_inference_is_reused(recognition):
    auto, engines, _ = recognition
    engines.run_vision.return_value = output("Select")
    engines.run.return_value = output("Check")
    assert auto.find_language_text("选择", "select") == [5, 4]
    assert auto.find_language_text("判定", "check") == [5, 4]
    engines.run_vision.assert_called_once()
    engines.run.assert_called_once()


def test_full_text_keeps_rapid_after_vision_on_same_frame(recognition):
    auto, engines, _ = recognition
    auto.find_language_text("选择", "select")
    assert auto.find_text_element("", only_text=True) == ["rapid"]
    assert auto.get_text_from_screenshot() == ["rapid"]
    engines.run.assert_called_once()
    auto.screenshot = auto.screenshot.copy()
    auto.find_language_text("选择", "select")
    assert engines.run_vision.call_count == 2


@pytest.mark.parametrize("grade", ["Very High", "High", "Normal", "Low", "Very Low"])
def test_event_grade_fallback_uses_actual_box_and_original_priority(recognition, monkeypatch, grade):
    event_handling = import_module("tasks.event.event_handling")

    auto, engines, _ = recognition
    auto.screenshot = Image.new("RGB", (1920, 1080))
    auto.model = "clam"
    auto.find_image_element = Mock(return_value=None)
    auto.mouse_action_with_pos = Mock()
    result = output("Unselectable", "like", grade)
    result.boxes[2] = [[350, 30], [440, 30], [440, 52], [350, 52]]
    engines.run_vision.return_value = result
    engines.run.return_value = output()
    monkeypatch.setattr(event_handling, "auto", auto)
    handler = event_handling.EventHandling()
    assert handler.decision_event_handling()
    auto.mouse_action_with_pos.assert_called_once_with([433.0, 926.0])
    assert handler.fallback_offset == 0
    engines.run_vision.assert_called_once()


def test_event_grade_falls_back_to_rapid_when_vision_is_unavailable(recognition):
    auto, engines, _ = recognition
    auto.screenshot = Image.new("RGB", (1920, 1080))
    auto.find_image_element = Mock(return_value=None)
    engines.run_vision.return_value = None
    engines.run.return_value = output("High")
    assert auto.find_element("event/high.png", model="clam") == [43.0, 889.0]
    assert engines.run.call_args.args[0].size == (1297, 67)


def test_event_grade_splits_joined_text_before_returning_coordinates(recognition):
    auto, engines, _ = recognition
    auto.screenshot = Image.new("RGB", (1920, 1080))
    auto.find_image_element = Mock(return_value=None)
    joined = output("Very High Very Low Unselectable")
    joined.boxes[0] = [[355, 30], [600, 30], [600, 52], [355, 52]]
    engines.run_vision.side_effect = [joined, output("Very High")]
    assert auto.find_element("event/very_high.png", model="clam") == [381.0, 889.0]
    assert engines.run_vision.call_args.args[0].size == (102, 67)
    engines.run.assert_not_called()


def test_event_grade_is_exact_and_does_not_use_unrelated_text(recognition):
    auto, engines, _ = recognition
    auto.screenshot = Image.new("RGB", (1920, 1080))
    auto.find_image_element = Mock(return_value=None)
    engines.run_vision.return_value = output("like", "highway", "Very Low", "Unselectable")
    engines.run.return_value = output()
    assert auto.find_element("event/high.png", model="clam") is None
    assert auto.find_element("event/low.png", model="clam") is None
    assert auto.find_element("event/very_low.png", model="clam") == [43.0, 889.0]


def test_non_event_image_failure_does_not_run_extra_ocr(recognition):
    auto, engines, _ = recognition
    auto.find_image_element = Mock(return_value=None)
    assert auto.find_element("home/drive_assets.png", model="clam") is None
    engines.run_vision.assert_not_called()
    engines.run.assert_not_called()


@pytest.mark.parametrize("language,profile,platform", [
    ("zh_cn", "ios_en", "darwin"), (None, "ios_en", "darwin"),
    ("en", "steam", "darwin"), ("en", "ios_en", "win32"),
])
def test_language_and_platform_gate(recognition, language, profile, platform, monkeypatch):
    auto, engines, module = recognition
    monkeypatch.setattr(module.path_manager, "current_language", language)
    monkeypatch.setattr(module.cfg, "config", module.cfg.config.model_copy(update={"game_profile": profile}))
    monkeypatch.setattr(module.sys, "platform", platform)
    auto.find_language_text("选择", "select")
    engines.run_vision.assert_not_called()
    engines.run.assert_called_once()


@pytest.mark.parametrize("target,only_text", [("turn", False), ("100", False), (["season", "seasun"], False), (None, True)])
def test_non_whitelisted_calls_keep_rapid(recognition, target, only_text):
    auto, engines, _ = recognition
    auto.find_text_element(target, (0, 0, 300, 200), only_text=only_text)
    engines.run_vision.assert_not_called()


def test_not_ready_vision_is_retried_without_caching_the_failure(recognition):
    auto, engines, _ = recognition
    engines.run_vision.side_effect = [None, output("Select")]
    auto.find_language_text("选择", "select")
    assert auto.find_language_text("选择", "select") == [5, 4]
    assert engines.run_vision.call_count == 2
    engines.run.assert_called_once()


def test_shared_frame_ocr_is_serialized_and_reused(recognition):
    auto, engines, _ = recognition
    barrier = threading.Barrier(3)
    results = []

    def recognize():
        barrier.wait()
        results.append(auto.find_language_text("选择", "select"))

    workers = [threading.Thread(target=recognize) for _ in range(2)]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert results == [[5, 4], [5, 4]]
    engines.run_vision.assert_called_once()


def test_native_failure_disables_vision_and_never_blocks(monkeypatch):
    from module.ocr.vision import VisionOCR

    monkeypatch.setattr(VisionOCR, "_warmup", lambda self: None)
    vision = VisionOCR(logging.getLogger("test-vision"))
    image = Image.new("L", (200, 80))
    assert vision.run(image) is None
    vision.ready.set()
    recognize = Mock(side_effect=RuntimeError("native failure"))
    monkeypatch.setattr(vision, "_recognize", recognize)
    assert vision.run(image) is None
    assert vision.run(image) is None
    recognize.assert_called_once()


def test_vision_can_start_after_profile_changes_without_reinitializing_rapid(monkeypatch):
    from module.ocr import vision as native
    from module.ocr.ocr import OCR

    instance = object.__new__(OCR)
    instance._vision = None
    instance._inference_lock = threading.RLock()
    instance.logger = Mock()
    engine = SimpleNamespace(run=Mock(return_value=output("Select")))
    factory = Mock(return_value=engine)
    monkeypatch.setattr(native, "VisionOCR", factory)
    monkeypatch.setattr(import_module("module.ocr.ocr").sys, "platform", "darwin")
    image = Image.new("L", (200, 80))
    assert instance.run_vision(image).txts == ("Select",)
    instance.run_vision(image)
    factory.assert_called_once()
