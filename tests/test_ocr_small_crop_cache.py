"""Exact small-crop inference reuse preserves task results and retry semantics."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import import_module
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image
from rapidocr.utils.output import RapidOCROutput


def result(image):
    return RapidOCROutput(
        img=image.copy(), txts=("0x30",), scores=(0.98,),
        boxes=np.array([[[1, 2], [50, 2], [50, 20], [1, 20]]]),
        word_results=((("30", 0.98, [[1, 2], [50, 20]]),),),
        elapse_list=[0.2],
    )


@pytest.fixture
def recognition(monkeypatch):
    module = import_module("module.ocr.ocr")
    from module.config import cfg

    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    clock = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    ocr = object.__new__(module.OCR)
    ocr.logger = Mock(spec=logging.Logger)
    ocr._inference_lock = threading.RLock()
    ocr._vision = ocr._vision_zh_cn = None
    ocr.engine = Mock(side_effect=result)
    pixels = np.arange(60 * 121, dtype=np.uint8).reshape(60, 121)
    return ocr, pixels, cfg, module, clock


def test_five_original_retry_calls_keep_outputs_and_logs_with_one_inference(recognition):
    ocr, pixels, _, _, _ = recognition
    outputs = [ocr.run(pixels.copy()) for _ in range(5)]
    ocr.engine.assert_called_once()
    assert ocr.logger.debug.call_count == 5
    for output in outputs:
        assert output.txts == ("0x30",)
        assert output.scores == (0.98,)
        np.testing.assert_array_equal(output.boxes, outputs[0].boxes)


def test_mutating_input_and_returned_fields_cannot_poison_later_reads(recognition):
    ocr, pixels, _, _, _ = recognition
    original = pixels.copy()
    first = ocr.run(pixels)
    expected = deepcopy(first)
    first.txts = ("modified",)
    first.img[:] = 0
    first.boxes[:] = 999
    first.word_results[0][0][2][0][0] = 999
    first.elapse_list.append(99)
    pixels[:] = 0
    second = ocr.run(original.copy())
    assert second.txts == expected.txts
    np.testing.assert_array_equal(second.img, expected.img)
    np.testing.assert_array_equal(second.boxes, expected.boxes)
    assert second.word_results == expected.word_results
    assert second.elapse_list == expected.elapse_list
    second.boxes[:] = 888
    np.testing.assert_array_equal(ocr.run(original).boxes, expected.boxes)
    ocr.engine.assert_called_once()
    ocr.run(pixels)
    assert ocr.engine.call_count == 2


def test_one_second_expiry_requires_fresh_inference(recognition):
    ocr, pixels, _, _, clock = recognition
    ocr.run(pixels)
    clock[0] = 10.99
    ocr.run(pixels)
    ocr.engine.assert_called_once()
    clock[0] = 11.0
    ocr.run(pixels)
    assert ocr.engine.call_count == 2


def test_different_pixels_shape_profile_and_engine_do_not_share_results(recognition, monkeypatch):
    ocr, pixels, cfg, _, _ = recognition
    ocr.run(pixels)
    ocr.run(255 - pixels)
    ocr.run(pixels.T)
    assert ocr.engine.call_count == 3
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn"}))
    ocr.run(pixels.T)
    assert ocr.engine.call_count == 4
    ocr.engine = Mock(side_effect=result)
    ocr.run(pixels.T)
    ocr.engine.assert_called_once()


@pytest.mark.parametrize("kind", ["large", "rgb", "pil", "path"])
def test_full_frames_color_and_file_inputs_keep_original_inference(recognition, tmp_path, kind):
    ocr, pixels, _, _, _ = recognition
    image = pixels
    if kind == "large":
        image = np.zeros((257, 257), dtype=np.uint8)
    elif kind == "rgb":
        image = np.repeat(pixels[:, :, None], 3, axis=2)
    elif kind == "pil":
        image = Image.fromarray(pixels)
    else:
        path = tmp_path / "crop.png"
        Image.fromarray(pixels).save(path)
        image = str(path)
    ocr.run(image)
    ocr.run(image)
    assert ocr.engine.call_count == 2


@pytest.mark.parametrize("platform,profile", [("win32", "ios_en"), ("darwin", "auto")])
def test_other_platforms_and_profiles_keep_original_inference(recognition, monkeypatch, platform, profile):
    ocr, pixels, cfg, module, _ = recognition
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile}))
    ocr.run(pixels)
    ocr.run(pixels)
    assert ocr.engine.call_count == 2


def test_empty_results_and_errors_are_retried_normally(recognition):
    ocr, pixels, _, _, _ = recognition
    ocr.engine.side_effect = [RapidOCROutput(), RuntimeError("temporary"), result(pixels)]
    assert not ocr.run(pixels).txts
    assert not ocr.run(pixels).txts
    assert ocr.run(pixels).txts == ("0x30",)
    assert ocr.engine.call_count == 3


@pytest.mark.parametrize("primed", [False, True])
def test_uncopyable_results_fall_back_without_losing_successful_ocr(recognition, monkeypatch, primed):
    ocr, pixels, _, module, _ = recognition
    if primed:
        ocr.run(pixels)
    monkeypatch.setattr(module, "deepcopy", Mock(side_effect=RuntimeError("uncopyable")))
    assert ocr.run(pixels).txts == ("0x30",)
    assert ocr.run(pixels).txts == ("0x30",)
    assert ocr.engine.call_count == 2 + int(primed)


def test_concurrent_identical_crops_share_inference_but_not_mutable_outputs(recognition):
    ocr, pixels, _, _, _ = recognition
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: ocr.run(pixels.copy()), range(4)))
    ocr.engine.assert_called_once()
    outputs[0].boxes[:] = 999
    assert all(output.boxes.max() == 50 for output in outputs[1:])
