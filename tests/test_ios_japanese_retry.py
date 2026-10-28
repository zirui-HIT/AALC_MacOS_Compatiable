"""Mixed localization server errors reuse the original retry and monitor paths."""

import threading
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from utils.runtime_paths import SOURCE_ROOT

FIXTURES = SOURCE_ROOT / "tests/fixtures/ios_zh_cn"


@pytest.fixture
def hybrid(monkeypatch):
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
    return cfg, auto, path_manager


@pytest.mark.parametrize("height", [1080, 1440])
@pytest.mark.parametrize("theme", ["default", "dark"])
def test_japanese_retry_is_found_by_both_existing_matchers(hybrid, monkeypatch, height, theme):
    from tasks.base.retry_monitor import RetryMonitor

    cfg, auto, paths = hybrid
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"set_win_size": height}))
    paths.set_theme(theme)
    frame = Image.open(FIXTURES / "japanese_server_retry.png").resize((round(height * 16 / 9), height))
    monkeypatch.setattr(auto, "screenshot", frame)
    point = auto.find_element("base/retry.png", threshold=0.9)
    monitor = RetryMonitor()
    monitor._templates = monitor._load_templates()
    for x, y in (point, monitor._find_retry_button(frame)):
        assert 1080 < x / (height / 1080) < 1140
        assert 685 < y / (height / 1080) < 720


def test_original_retry_clicks_japanese_error_then_returns_without_event_input(hybrid, monkeypatch):
    from module.backends import factory

    _, auto, _ = hybrid
    recovery = import_module("tasks.base.retry")
    frames = iter([Image.open(FIXTURES / "japanese_server_retry.png"), Image.new("L", (1920, 1080))])

    def capture(**kwargs):
        auto.screenshot = next(frames)
        return auto.screenshot

    monkeypatch.setattr(auto, "take_screenshot", capture)
    monkeypatch.setattr(auto, "get_restore_time", lambda: 0)
    monkeypatch.setattr(auto, "last_click_time", -1)
    monkeypatch.setattr(auto, "mouse_click", Mock())
    monkeypatch.setattr(auto, "mouse_to_blank", Mock())
    monkeypatch.setattr(recovery, "check_times", Mock(return_value=False))
    monkeypatch.setattr(factory, "get_playcover_session", lambda: SimpleNamespace(
        cancel=threading.Event(), input=SimpleNamespace(check_cancel=Mock()),
    ))
    recovery.retry()
    auto.mouse_click.assert_called_once()
    x, y = auto.mouse_click.call_args.args
    assert 1080 < x < 1140 and 685 < y < 720


def test_monitor_keeps_original_gate_cooldown_and_two_clear_frame_release(hybrid, monkeypatch):
    module = import_module("tasks.base.retry_monitor")
    monitor = module.RetryMonitor()
    monitor._templates = monitor._load_templates()
    automation = Mock()
    automation.check_pause.return_value = False
    monkeypatch.setattr(module, "auto", automation)
    monkeypatch.setattr(module.time, "monotonic", lambda: 10)
    frame = Image.open(FIXTURES / "japanese_server_retry.png")
    assert monitor.check_once(frame)
    assert not monitor.check_once(frame)
    automation.monitor_mouse_click.assert_called_once()
    automation.suspend_interactions.assert_called_once()
    blank = Image.new("L", frame.size)
    assert not monitor.check_once(blank)
    automation.resume_interactions.assert_not_called()
    assert not monitor.check_once(blank)
    automation.resume_interactions.assert_called_once()


def test_bundled_japanese_candidate_preserves_original_chinese_and_english_templates(hybrid):
    from tasks.base.retry_monitor import RetryMonitor
    from utils.image_utils import ImageUtils

    monitor = RetryMonitor()
    monitor._templates = monitor._load_templates()
    assert len(monitor._templates) == 3
    assert "ios_zh_cn" not in str(ImageUtils.resolve_path("default/zh_cn", "base/retry.png"))
    for path in monitor.TEMPLATE_PATHS:
        template = ImageUtils.load_from_specific_path("base/retry.png", path)
        canvas = Image.new("L", (1920, 1080))
        canvas.paste(Image.fromarray(template), (700, 500))
        x, y = monitor._find_retry_button(canvas)
        assert (x, y) == (700 + template.shape[1] // 2, 500 + template.shape[0] // 2)


def test_retry_candidate_does_not_match_normal_chinese_pages(hybrid):
    from tasks.base.retry_monitor import RetryMonitor
    from utils.image_utils import ImageUtils

    template = ImageUtils.load_from_specific_path("base/retry.png", "default/ios_zh_cn")
    monitor = RetryMonitor()
    monitor._templates = (template,)
    for path in FIXTURES.glob("*.png"):
        if path.name == "japanese_server_retry.png":
            continue
        assert monitor._find_retry_button(Image.open(path)) is None, path.name


@pytest.mark.parametrize("profile", ["auto", "ios_en"])
def test_other_profiles_keep_original_monitor_candidates(hybrid, monkeypatch, profile):
    from tasks.base.retry_monitor import RetryMonitor

    cfg, _, _ = hybrid
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": profile}))
    assert len(RetryMonitor()._load_templates()) == 2


def test_hybrid_retry_remains_available_after_shared_resource_sync(hybrid, monkeypatch):
    from utils import image_utils

    _, auto, _ = hybrid
    monkeypatch.setattr(image_utils, "synced_image_tree", lambda: True)
    monkeypatch.setattr(auto, "screenshot", Image.open(FIXTURES / "japanese_server_retry.png"))
    assert auto.find_element("base/retry.png", threshold=0.9)
    assert np.asarray(auto.screenshot).shape == (1080, 1920)
