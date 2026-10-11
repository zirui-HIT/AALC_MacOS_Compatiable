"""Japanese-font Chinese recognition and resource isolation; no game input."""

import json
import logging
import os
import sys
import threading
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image
from rapidocr.utils.output import RapidOCROutput

from module.backends.configuration import migrate_backend
from utils.runtime_paths import SOURCE_ROOT


@pytest.fixture
def chinese(monkeypatch):
    from module.config import cfg
    from utils.image_utils import ImageUtils
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn", "set_win_size": 1080}))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    return cfg, ImageUtils, path_manager


def test_saved_chinese_profile_survives_connection_setting_changes():
    values = {"backend": "playcover", "game_profile": "ios_zh_cn"}
    for port in (1718, 1719):
        values = migrate_backend({**values, "playcover_port": port}, "darwin")
        assert values["game_profile"] == "ios_zh_cn"
        assert (values["set_win_size"], values["simulator"]) == (1080, False)
    assert migrate_backend({**values, "game_profile": "ios_en"})["game_profile"] == "ios_en"
    assert migrate_backend({"backend": "playcover", "game_profile": "auto"})["game_profile"] == "ios_en"


def test_overlay_and_explicit_reuse_never_pick_user_english_images(chinese, tmp_path, monkeypatch):
    _, images, paths = chinese
    monkeypatch.setattr(import_module("utils.image_utils"), "resource_path", lambda p: tmp_path / "bundled" / p)
    monkeypatch.setattr(import_module("utils.image_utils"), "data_path", lambda p: tmp_path / "data" / p)
    profile = tmp_path / "bundled/assets/ios_zh_cn/profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"reuse_ios_en": ["default/button.png"]}))
    candidates = [
        "bundled/assets/ios_en/default/button.png",
        "data/templates/ios_en/default/button.png",
        "bundled/assets/images/default/en/button.png",
        "bundled/assets/images/default/zh_cn/button.png",
    ]
    for name in candidates:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9), "red").save(target)
    paths.set_theme("default")
    assert images.resolve_path("default/ios_zh_cn", "button.png") == tmp_path / candidates[0]
    assert images.existing_image_paths("button.png") == ["default/ios_zh_cn", "default/zh_cn"]
    bundled = tmp_path / "bundled/assets/ios_zh_cn/default/button.png"
    bundled.parent.mkdir(parents=True)
    Image.new("RGB", (16, 9), "blue").save(bundled)
    assert images.resolve_path("default/ios_zh_cn", "button.png") == bundled
    custom = tmp_path / "data/templates/ios_zh_cn/default/button.png"
    custom.parent.mkdir(parents=True)
    Image.new("RGB", (16, 9), "green").save(custom)
    assert images.resolve_path("default/ios_zh_cn", "button.png") == custom
    assert not images.resolve_path("default/ios_zh_cn", "unlisted.png").exists()
    assert paths.current_language == "zh_cn"


def test_retry_specific_path_uses_chinese_overlay_without_monitor_changes(chinese, tmp_path, monkeypatch):
    _, images, _ = chinese
    monkeypatch.setattr(import_module("utils.image_utils"), "data_path", lambda p: tmp_path / p)
    retry = tmp_path / "templates/ios_zh_cn/default/base/retry.png"
    retry.parent.mkdir(parents=True)
    Image.new("RGB", (50, 20), "white").save(retry)
    assert images.resolve_path("default/zh_cn", "base/retry.png") == retry
    assert "ios_zh_cn" not in str(images.resolve_path("default/en", "base/retry.png"))


def test_dark_theme_keeps_ios_geometry_and_language(chinese):
    _, images, paths = chinese
    paths.set_theme("dark")
    assert images.existing_image_paths("home/back_ios.png")[0] == "default/ios_zh_cn"
    assert images.layout("luxcavation.exp_count_x", 300) == 20
    assert images.layout("unmodified_coordinate", 123) == 123
    assert paths.current_language == "zh_cn"


@pytest.mark.parametrize("target,text", [
    ("选择", "選擇"), ("胜率", "勝率"), ("继续", "継續"),
    ("阵亡", "陣亡"), ("拒绝饰品", "拒絶飾品"), ("默尔", "黙尓索"),
    ("沉沦", "沈淪"), ("钉与锤", "釘与錘"), ("无归属", "无帰属者"),
    ("地狱鸡", "地獄鶏"), ("海·边", "去·海·辺"), ("时间杀人", "時間殺人時間"),
    ("谋杀", "WARP快車謀殺案"), ("无改变", "无改変者"), ("定义为", "定義為惡"),
    ("号线", "1号綫"), ("束缚的", "束縛的色欲"), ("沉溺的", "沈溺的憂郁"),
    ("自以为", "自以為是的傲慢"), ("摇曳", "燃焼的揺曳"), ("沉沦泛", "沈淪泛濫"),
    ("循环呼", "循環呼吸"), ("终焉", "梦之終焉"), ("观望", "不思観望"),
    ("极高", "極高"), ("极低", "極低"),
])
def test_font_variants_keep_original_coordinates_and_raw_text(chinese, target, text):
    automation = object.__new__(import_module("module.automation.automation").Automation)
    raw = {text: [51, 27]}
    assert automation.find_str_in_text(target, raw) == [51, 27]
    assert raw == {text: [51, 27]}


def test_font_variants_preserve_dictionary_keys_weights_and_priority(chinese):
    automation = object.__new__(import_module("module.automation.automation").Automation)
    targets = {"沉溺者": 17, "遗忘": -2, "未知": -5}
    raw = {"于情感沈溺者": [50, 30], "被遺忘者們": [60, 40]}
    result = automation._find_target_in_ocr_dict(targets, raw)
    assert (result.text, result.value, result.position) == ("沉溺者", 17, [50, 30])
    assert automation._find_target_in_ocr_dict(targets, {"别的卡包": [1, 2]}) is None
    assert targets == {"沉溺者": 17, "遗忘": -2, "未知": -5}


@pytest.mark.parametrize("profile", ["ios_en", "auto"])
def test_chinese_variants_do_not_affect_other_profiles(chinese, monkeypatch, profile):
    cfg, _, _ = chinese
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile}))
    automation = object.__new__(import_module("module.automation.automation").Automation)
    assert automation.find_str_in_text("选择", {"選擇": [1, 2]}) is False
    assert automation.find_str_in_text("沉沦", {"沈淪": [1, 2]}) is False


def test_chinese_uses_profile_ocr_and_preserves_raw_output(chinese, monkeypatch):
    module = import_module("module.automation.automation")
    output = RapidOCROutput(txts=("選擇",), scores=(1.0,), boxes=np.array([[[1, 2], [9, 2], [9, 6], [1, 6]]]))
    engines = SimpleNamespace(run=Mock(return_value=output), run_vision=Mock())
    monkeypatch.setattr(module, "ocr", engines)
    auto = object.__new__(module.Automation)
    auto.screenshot = Image.new("RGB", (200, 100))
    auto._ocr_image, auto._ocr_regions, auto._ocr_lock = None, {}, threading.RLock()
    assert auto.find_language_text("选择", "select") == [5, 4]
    assert auto.get_text_from_screenshot() == ["選擇"]
    engines.run.assert_called_once()
    engines.run_vision.assert_not_called()


def test_ocr_cache_isolated_on_same_frame_after_language_switch(chinese, monkeypatch):
    module = import_module("module.automation.automation")
    engines = SimpleNamespace(run=Mock(side_effect=[RapidOCROutput(txts=("選擇",)), RapidOCROutput(txts=("Select",))]))
    monkeypatch.setattr(module, "ocr", engines)
    auto = object.__new__(module.Automation)
    auto.screenshot = Image.new("L", (200, 100))
    auto._ocr_image, auto._ocr_regions, auto._ocr_lock = None, {}, threading.RLock()
    assert auto.get_text_from_screenshot() == ["選擇"]
    monkeypatch.setattr(chinese[0], "config", chinese[0].config.model_copy(update={"game_profile": "ios_en"}))
    assert auto.get_text_from_screenshot() == ["Select"]
    assert engines.run.call_count == 2


@pytest.fixture
def profile_ocr(chinese, monkeypatch):
    from module.ocr.ocr import OCR

    monkeypatch.setattr(import_module("module.ocr.ocr").sys, "platform", "darwin")
    instance = object.__new__(OCR)
    instance.logger = Mock()
    instance._inference_lock = threading.RLock()
    instance._vision = SimpleNamespace(run=Mock())
    instance._vision_zh_cn = SimpleNamespace(run=Mock())
    instance.engine = Mock(return_value=RapidOCROutput(txts=("rapid",)))
    return instance


@pytest.mark.parametrize("pixels", [Image.new("RGB", (100, 80)), np.zeros((80, 100, 3), np.uint8)])
def test_chinese_native_ocr_preserves_raw_boxes_and_english_engine(profile_ocr, pixels):
    output = RapidOCROutput(txts=("開始戦斗",), boxes=np.asarray([[[1, 2], [8, 2], [8, 6], [1, 6]]]))
    profile_ocr._vision_zh_cn.run.return_value = output
    assert profile_ocr.run(pixels) is output
    profile_ocr.engine.assert_not_called()
    profile_ocr._vision.run.assert_not_called()


@pytest.mark.parametrize("result", [None, RapidOCROutput(txts=())])
def test_unavailable_or_empty_chinese_native_ocr_keeps_rapid_fallback(profile_ocr, result):
    profile_ocr._vision_zh_cn.run.return_value = result
    assert profile_ocr.run(Image.new("L", (100, 80))).txts == ("rapid",)
    profile_ocr.engine.assert_called_once()


def test_other_profile_never_uses_chinese_native_ocr(profile_ocr, chinese, monkeypatch):
    monkeypatch.setattr(chinese[0], "config", chinese[0].config.model_copy(update={"game_profile": "ios_en"}))
    assert profile_ocr.run(Image.new("L", (100, 80))).txts == ("rapid",)
    profile_ocr._vision_zh_cn.run.assert_not_called()


def test_preprocessed_numeric_arrays_keep_original_rapid(profile_ocr):
    assert profile_ocr.run(np.zeros((300, 300), np.uint8)).txts == ("rapid",)
    profile_ocr._vision_zh_cn.run.assert_not_called()


def test_chinese_ocr_can_initialize_after_profile_switch(profile_ocr, monkeypatch):
    factory = Mock(return_value=SimpleNamespace(run=Mock(return_value=RapidOCROutput(txts=("選擇",)))))
    monkeypatch.setattr(import_module("module.ocr.vision"), "VisionOCR", factory)
    profile_ocr._vision_zh_cn = None
    assert profile_ocr.run(Image.new("L", (100, 80))).txts == ("選擇",)
    profile_ocr.run(Image.new("L", (100, 80)))
    factory.assert_called_once_with(profile_ocr.logger, languages=("zh-Hant", "en-US"))


FIXTURES = SOURCE_ROOT / "tests/fixtures/ios_zh_cn"


@pytest.mark.skipif(sys.platform != "darwin" or os.environ.get("AALC_NATIVE_VISION_TEST") != "1",
                    reason="Opt-in native Vision replay requires macOS model access")
def test_native_chinese_ocr_replay(chinese, monkeypatch):
    from module.automation import auto
    from module.ocr.vision import VisionOCR

    vision = VisionOCR(logging.getLogger("chinese-replay"), languages=("zh-Hant", "en-US"))
    assert vision.ready.wait(10), "Chinese Vision failed to warm up"
    cases = json.loads((FIXTURES / "manifest.json").read_text())["ocr"]
    for case in cases:
        image = Image.open(FIXTURES / f'{case["page"]}.png').crop(case["crop"])
        result = vision.run(image)
        assert result is not None and result.txts, case
        raw = {text: list((box[0] + box[2]) / 2) for text, box in zip(result.txts, result.boxes)}
        point = auto.find_str_in_text(case["target"], raw)
        assert point, (case, result.txts)
        assert 0 <= point[0] <= image.width and 0 <= point[1] <= image.height
    formation = import_module("tasks.teams.team_formation")
    from module.ocr import ocr as profile_engine
    results = []

    def recognize(pixels):
        result = profile_engine.run(pixels)
        results.append(result.txts)
        return result

    monkeypatch.setattr(import_module("module.ocr"), "ocr", SimpleNamespace(run=recognize))
    monkeypatch.setattr(formation, "auto", SimpleNamespace(screenshot=Image.open(FIXTURES / "exp_formation.png")))
    formation.deal_with_spills()
    assert len(results) == 1 and "12/12" in "".join(results[0]).replace(" ", ""), results
    from utils.image_utils import ImageUtils

    claim = np.asarray(Image.open(FIXTURES / "full_mirror_claim.png"))
    bounds = ImageUtils.get_bbox(ImageUtils.load_image("mirror/claim_reward/coins_bbox.png"))
    reward = profile_engine.run(ImageUtils.crop(claim, bounds))
    # Original reward parsing takes the number after x from the grayscale ROI.
    assert int("".join(reward.txts).lower().split("x")[-1]) == 30


@pytest.mark.parametrize("model", ["normal", "clam"])
def test_real_chinese_menu_replay_and_confusers(chinese, monkeypatch, model):
    from module.automation import auto

    cases = json.loads((FIXTURES / "manifest.json").read_text())
    for page, case in cases["pages"].items():
        chinese[2].initialize_paths()
        auto.clear_img_cache()
        monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / f"{page}.png").convert("L"))
        for target, bounds in case["targets"].items():
            point = auto.find_element(target, model=model)
            assert point, (page, target)
            x1, y1, x2, y2 = bounds
            assert x1 <= point[0] <= x2 and y1 <= point[1] <= y2, (page, target, point)
        for target in case.get("absent", []):
            assert auto.find_element(target, model=model) is None, (page, target)


@pytest.mark.parametrize("page,target,bounds", [
    ("full_theme_pack", "mirror/theme_pack/theme_pack_features.png", [(700, 300, 760, 365), (1000, 300, 1070, 365), (1320, 300, 1390, 365)]),
    ("full_event_check", "event/very_low.png", [(500, 910, 565, 945), (1230, 910, 1300, 945)]),
    ("luxcavation", "luxcavation/exp_enter.png", [(490, 680, 625, 750), (1010, 680, 1145, 750), (1520, 680, 1660, 750)]),
    ("thread_stages", "luxcavation/thread_consume.png", [(1180, 370, 1280, 420), (1180, 520, 1280, 575), (1180, 675, 1280, 730)]),
    ("pass_missions", "pass/pass_coin.png", [(530, y - 20, 570, y + 20) for y in (337, 468, 599, 729, 860)]),
])
def test_multiple_targets_keep_original_count_and_positions(chinese, monkeypatch, page, target, bounds):
    from module.automation import auto

    chinese[2].set_theme("default")
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / f"{page}.png"))
    points = auto.find_element(target, find_type="image_with_multiple_targets")
    assert len(points) == len(bounds)
    for x1, y1, x2, y2 in bounds:
        assert sum(x1 <= x <= x2 and y1 <= y <= y2 for x, y in points) == 1


@pytest.mark.parametrize("page,bounds", [
    ("full_battle_ready", (1410, 794, 1521, 843)),
    ("full_battle_solo_ready", (1346, 794, 1465, 843)),
])
def test_win_rate_anchor_keeps_original_click_offset_inside_button(chinese, monkeypatch, page, bounds):
    from module.automation import auto

    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / f"{page}.png"))
    x, y = auto.find_element("battle/win_rate_card.png")
    x1, y1, x2, y2 = bounds
    for px, py in ((x, y), (x + 50 * 0.75, y - 50 * 0.75)):
        assert x1 <= px <= x2 and y1 <= py <= y2


def test_start_template_preserves_original_team_count_crop(chinese, monkeypatch):
    from module.automation import auto

    module = import_module("tasks.teams.team_formation")
    captured = []
    monkeypatch.setattr(import_module("module.ocr"), "ocr", SimpleNamespace(run=lambda pixels: captured.append(pixels) or RapidOCROutput()))
    monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / "exp_formation.png"))
    module.deal_with_spills()
    assert len(captured) == 1
    # The original 115px upward offset must still include the 12/12 field.
    import cv2

    source = np.asarray(auto.screenshot)[760:826, 1619:1821]
    mask = cv2.bitwise_not(cv2.inRange(cv2.bitwise_not(source), 220, 255))
    h, w = mask.shape
    assert np.array_equal(captured[0][(300-h)//2:(300-h)//2+h, (300-w)//2:(300-w)//2+w], mask)


def test_resource_cache_isolated_when_language_switches(chinese, monkeypatch):
    from module.automation import auto

    cfg, _, paths = chinese
    target = "battle/normal_to_battle_assets.png"
    auto.clear_img_cache()
    chinese_template, _ = auto._load_template_for_path(target, "default/ios_zh_cn", True)
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    paths.initialize_paths()
    english_template, _ = auto._load_template_for_path(target, "default/en", True)
    assert chinese_template is not None and english_template is not None
    assert chinese_template.shape != english_template.shape or not np.array_equal(chinese_template, english_template)
