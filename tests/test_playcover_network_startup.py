"""Startup-only network-exit recovery reuses initialization and task cancellation."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image


@pytest.mark.parametrize("texts", [
    ("网络连接不稳定。游戏即将关闭。", "确认"),
    ("網路不穩定", "確認"),
    ("網絡不穩定，遊戲即將關閉。",),
    ("The network is unstable.", "The game will close.", "OK"),
    ("Network is unstable", "Confirm"),
    ("ネットワークが不安定です。", "ゲームを終了します。", "確認"),
    ("不 安 定", "終 了"),  # Japanese kanji remain readable by the shared CJK model.
])
def test_specific_network_exit_notice_languages(texts):
    from tasks.base.playcover_startup import is_network_exit_notice

    assert is_network_exit_notice(texts)


@pytest.mark.parametrize("texts", [
    None, (), ("Server error", "Retry"), ("Network is unstable", "Retry"),
    ("网络连接失败，请重试", "重试"), ("ネットワークが不安定です。", "再試行"),
    ("確認",), ("确定关闭游戏？",), ("错误", "确定"),
])
def test_other_notices_do_not_close_game(texts):
    from tasks.base.playcover_startup import is_network_exit_notice

    assert not is_network_exit_notice(texts)


@pytest.fixture
def startup(monkeypatch):
    from module.backends import factory
    from module.config import cfg
    from tasks.base import script_task_scheme as script
    from utils.path_manager import path_manager

    recovery = import_module("tasks.base.retry")
    native = import_module("tasks.base.playcover_startup")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_zh_cn",
    }))
    if not path_manager.pic_path:
        path_manager.initialize_paths()
    state = {"running": False, "starts": 0, "ready": False, "clock": 0, "captures": 0}
    session = SimpleNamespace(input=SimpleNamespace(check_cancel=Mock()), transport=SimpleNamespace(connected=False))
    session.lifecycle = SimpleNamespace(identity=object(), process=lambda: object() if state["running"] else None)

    def start():
        state["starts"] += 1
        state["running"] = True

    def close():
        state["running"] = False

    session.start_game = Mock(side_effect=start)
    session.stop_game = Mock(side_effect=close)
    session.disconnect = Mock()
    automation = Mock()
    automation.click_element.return_value = False
    automation.screenshot = Image.new("L", (1920, 1080))

    def capture(*args, **kwargs):
        state["captures"] += 1
        assert state["captures"] <= 40, "Startup recovery must finish or stop"
        return automation.screenshot

    automation.take_screenshot.side_effect = capture
    automation.find_element.side_effect = lambda target, *args, **kwargs: (
        (1700, 80) if state["ready"] and target == "home/mail_assets.png" else None)
    automation.mouse_click.side_effect = lambda *args: close()
    automation.get_restore_time.return_value = None
    monkeypatch.setattr(script, "auto", automation)
    monkeypatch.setattr(recovery, "auto", automation)
    monkeypatch.setattr(native, "auto", automation)
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    monkeypatch.setattr(native, "get_playcover_session", lambda: session)
    monkeypatch.setattr(native, "_notice_position", Mock(return_value=(900, 700)))
    monkeypatch.setattr(recovery, "check_times", Mock(return_value=False))
    monkeypatch.setattr(native, "worker_sleep", Mock())
    return native, script, recovery, automation, session, state


def test_four_failed_launches_close_game_and_never_launch_a_fifth(startup):
    from module.backends.base import BackendCancelled

    native, script, _, auto, session, state = startup
    with pytest.raises(BackendCancelled, match="连续失败 4 次"):
        script.init_game()
    assert session.start_game.call_count == 4
    assert auto.mouse_click.call_count == 4
    assert session.disconnect.call_count == 4
    assert not state["running"]
    session.stop_game.assert_not_called()  # The confirmation already exited it.
    assert session._network_startup_pending is False


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
def test_success_before_limit_preserves_game_and_resets_budget(startup, failures):
    native, script, _, auto, session, state = startup

    def notice(_):
        state["ready"] = state["starts"] > failures
        return None if state["ready"] else (900, 700)

    native._notice_position.side_effect = notice
    script.init_game()
    assert session.start_game.call_count == failures + 1
    assert auto.mouse_click.call_count == failures
    assert state["running"]
    assert session._network_startup_failures == 0
    assert session._network_startup_pending is False


def test_unknown_loading_frame_does_not_reset_consecutive_failures(startup):
    native, _, _, _, session, _ = startup
    native.begin_startup(session)
    session._network_startup_failures = 3
    native._notice_position.return_value = None
    assert not native.recover_network_exit_notice()
    native.begin_startup(session)
    assert session._network_startup_failures == 3
    assert session._network_startup_pending is True


def test_new_task_owner_gets_a_fresh_budget(startup, monkeypatch):
    native, _, _, _, session, _ = startup
    native.begin_startup(session)
    session._network_startup_failures = 3
    monkeypatch.setattr(native.threading, "current_thread", lambda: object())
    native.begin_startup(session)
    assert session._network_startup_failures == 0


def test_repeated_visible_dialog_gets_one_click_then_verified_close_fallback(startup, monkeypatch):
    native, script, _, auto, session, state = startup
    auto.mouse_click.side_effect = None  # Confirmation was ignored or exit stalled.

    def clock():
        state["clock"] += 1
        return state["clock"]

    monkeypatch.setattr(native.time, "monotonic", clock)
    from module.backends.base import BackendCancelled

    with pytest.raises(BackendCancelled):
        script.init_game()
    assert session.start_game.call_count == auto.mouse_click.call_count == session.stop_game.call_count == 4
    assert not state["running"]


def test_user_stop_during_exit_wait_cannot_relaunch_game(startup):
    from module.backends.base import BackendCancelled

    native, script, _, auto, session, _ = startup
    auto.mouse_click.side_effect = None
    native.worker_sleep.side_effect = BackendCancelled("user stopped")
    with pytest.raises(BackendCancelled, match="user stopped"):
        script.init_game()
    session.start_game.assert_called_once()
    auto.mouse_click.assert_called_once()


@pytest.mark.parametrize("exited", [True, False])
def test_uncertain_click_is_not_blindly_repeated(startup, exited):
    from module.backends.base import BackendCancelled

    _, script, _, auto, session, state = startup

    def click(*args):
        state["running"] = not exited
        raise OSError("MaaTools closed during confirmation")

    auto.mouse_click.side_effect = click
    if exited:
        with pytest.raises(BackendCancelled, match="连续失败 4 次"):
            script.init_game()
        assert session.start_game.call_count == 4
    else:
        with pytest.raises(OSError):
            script.init_game()
        session.start_game.assert_called_once()
    assert auto.mouse_click.call_count == session.start_game.call_count


def test_normal_running_session_is_not_checked_until_startup(startup):
    native, _, _, _, session, _ = startup
    assert not native.recover_network_exit_notice()
    native._notice_position.assert_not_called()
    assert not hasattr(session, "_network_startup_failures")


def test_limit_uses_existing_worker_stop_instead_of_mirror_retry(startup, monkeypatch):
    from module.my_error.my_error import userStopError

    _, script, _, _, session, state = startup
    worker = script.my_script_task()
    monkeypatch.setattr(worker, "_run", script.init_game)
    monkeypatch.setattr(script.retry_monitor, "stop", Mock())
    worker.run()
    assert isinstance(worker.exception, userStopError)
    assert "连续失败 4 次" in str(worker.exception)
    assert session.start_game.call_count == 4
    assert not state["running"]


@pytest.mark.parametrize("resolved", ["com.ProjectMoon.LimbusCompany", "other.app", None])
def test_bundle_only_connection_resolves_exact_game_before_closing(monkeypatch, resolved):
    import AppKit

    from module.backends.playcover import lifecycle as module
    from tasks.base.playcover_startup import _ensure_process_identity

    target = SimpleNamespace(identity=None, bundle_id="com.ProjectMoon.LimbusCompany")
    url = None if resolved is None else SimpleNamespace(path=lambda: "/game.app")
    workspace = SimpleNamespace(URLForApplicationWithBundleIdentifier_=Mock(return_value=url))
    monkeypatch.setattr(AppKit, "NSWorkspace", SimpleNamespace(sharedWorkspace=lambda: workspace))
    monkeypatch.setattr(module, "read_app_identity", Mock(return_value=SimpleNamespace(bundle_id=resolved)))
    if resolved == target.bundle_id:
        _ensure_process_identity(target)
        assert target.identity.bundle_id == target.bundle_id
    else:
        with pytest.raises(RuntimeError):
            _ensure_process_identity(target)
        assert target.identity is None


@pytest.mark.parametrize("height", [810, 1080])
@pytest.mark.parametrize("texts,expected", [
    (["ネットワークが不安定です。", "ゲームを終了します。", "確認"], True),
    (["网络连接不稳定。", "游戏即将关闭。", "确认"], True),
    (["The network is unstable.", "The game will close.", "OK"], True),
    (["Server error", "Retry"], False),
    (["ネットワークが不安定です。", "再試行"], False),
])
def test_synthetic_dialog_ocr_and_cropped_button_coordinates(monkeypatch, height, texts, expected):
    # Synthetic OCR regression, not a claim of a real captured network notice.
    from PIL import ImageDraw, ImageFont

    from module.automation import auto
    from module.config import cfg
    from tasks.base.playcover_startup import _notice_position
    from utils.path_manager import path_manager
    from utils.runtime_paths import SOURCE_ROOT

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_zh_cn", "set_win_size": height,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    auto.clear_img_cache()
    scale = height / 1080
    image = Image.new("L", (round(height * 16 / 9), height))
    font = ImageFont.truetype(str(SOURCE_ROOT / "assets/app/fonts/ChineseFont.ttf"), round(36 * scale))
    draw = ImageDraw.Draw(image)
    for index, text in enumerate(texts):
        draw.text((round(520 * scale), round((400 + index * 80) * scale)), text, font=font, fill=230)
    template, _ = auto._load_template_for_path("base/only_option_assets.png", "default/share", True)
    origin = (round(820 * scale), round(680 * scale))
    image.paste(Image.fromarray(template), origin)
    monkeypatch.setattr(auto, "screenshot", image)
    point = _notice_position(image)
    if expected:
        assert point == pytest.approx((origin[0] + template.shape[1] // 2,
                                      origin[1] + template.shape[0] // 2), abs=1)
    else:
        assert point is None


@pytest.mark.parametrize("height", [810, 1080])
def test_actual_ios_network_notice_uses_confirm_text_when_old_corner_fails(monkeypatch, height):
    from pathlib import Path

    from module.automation import auto
    from module.config import cfg
    from tasks.base.playcover_startup import _notice_position
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "playcover", "game_profile": "ios_zh_cn", "set_win_size": height,
    }))
    for key, value in vars(path_manager).copy().items():
        monkeypatch.setattr(path_manager, key, value)
    path_manager.initialize_paths()
    image = Image.new("L", (1920, 1080))
    # Actual 2026-11-07 MaaTools capture, cropped to remove account/UID labels.
    with Image.open(Path(__file__).parent / "fixtures/playcover_startup_network_notice.png") as dialog:
        image.paste(dialog, (288, 216))
    scale = height / 1080
    image = image.resize((round(1920 * scale), height), Image.Resampling.LANCZOS)
    auto.clear_img_cache()
    monkeypatch.setattr(auto, "screenshot", image)
    point = _notice_position(image)
    assert point is not None
    assert 738 * scale < point[0] < 1182 * scale
    assert 718 * scale < point[1] < 777 * scale


@pytest.mark.parametrize("labels,expected", [
    ([("確", 960, 745)], True),
    ([("確", 960, 540)], False),  # Confirmation mentioned in the body, not a button.
    ([("確認", 800, 745), ("確認", 1100, 745)], False),
    ([("再試行", 960, 745)], False),
])
def test_ocr_fallback_requires_one_central_confirmation_button(monkeypatch, labels, expected):
    import numpy as np

    from tasks.base import playcover_startup as native

    image = Image.new("L", (1920, 1080))
    words = ["ネットワークが不安定です。"]
    boxes = [[[500, 250], [850, 250], [850, 290], [500, 290]]]
    for text, x, y in labels:
        words.append(text)
        x, y = x - 288, y - 216
        boxes.append([[x - 20, y - 15], [x + 20, y - 15], [x + 20, y + 15], [x - 20, y + 15]])
    monkeypatch.setattr(native, "auto", SimpleNamespace(find_element=Mock(return_value=None)))
    monkeypatch.setattr(native, "ocr", SimpleNamespace(run=Mock(return_value=SimpleNamespace(txts=words, boxes=np.array(boxes)))))
    assert bool(native._notice_position(image)) is expected
