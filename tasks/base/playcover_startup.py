"""Bound recovery of iOS network notices that close the game on confirmation."""

import re
import threading
import time
import unicodedata

import numpy as np

from backend_host.runtime import worker_sleep
from module.automation import auto
from module.backends.base import BackendCancelled
from module.backends.factory import get_playcover_session
from module.logger import log
from module.ocr import ocr

MAX_STARTUP_ATTEMPTS = 4
EXIT_WAIT_SECONDS = 10


def begin_startup(session):
    owner = threading.current_thread()
    if getattr(session, "_network_startup_owner", None) is not owner:
        session._network_startup_failures = 0
    session._network_startup_owner = owner
    session._network_startup_pending = True


def _reset(session):
    session._network_startup_failures = 0
    session._network_startup_pending = False
    session._network_startup_owner = None


def _fold(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def is_network_exit_notice(texts, *, confirmation=False):
    words = [_fold(text) for text in (texts or ())]
    text = "".join(words)
    unstable = (
        ("network" in text and "unstable" in text)
        or (any(word in text for word in ("网络", "網路", "網絡"))
            and any(word in text for word in ("不稳定", "不穩定")))
        or "不安定" in text
    )
    closing = any(word in text for word in (
        "close", "exit", "terminate", "关闭", "關閉", "退出", "结束", "結束", "終了",
    ))
    confirm = any(word in {"ok", "confirm", "确认", "確認", "确定", "確定", "はい"} for word in words)
    return unstable and (closing or confirm or confirmation)


def _notice_position(image):
    width, height = image.size
    # The shared asset is a button corner, independent of its Japanese glyphs.
    # Search only the central dialog button area; crop coordinates are relative.
    button_roi = (int(width * .2), int(height * .4), int(width * .8), int(height * .9))
    point = auto.find_element("base/only_option_assets.png", model="aggressive", my_crop=button_roi)
    body_roi = (int(width * .15), int(height * .2), int(width * .85), int(height * .9))
    result = ocr.run(np.asarray(image.convert("L").crop(body_roi)))
    if point and is_network_exit_notice(result.txts):
        return point[0] + button_roi[0], point[1] + button_roi[1]
    if not is_network_exit_notice(result.txts, confirmation=True):
        return None
    # iOS 1.118 uses a different button border. Reuse OCR box coordinates when
    # the shared corner no longer matches. RapidOCR reads its Japanese 確認 as
    # just 確; allow that only with 不安定 and one lower, central button label.
    labels = {"ok", "confirm", "确认", "確認", "确定", "確定", "はい"}
    if "不安定" in _fold("".join(result.txts or ())):
        labels |= {"確", "确"}
    candidates = []
    for text, box in zip(result.txts or (), result.boxes if result.boxes is not None else ()):
        if _fold(text) not in labels:
            continue
        x, y = np.mean(box, axis=0) + np.array(body_roi[:2])
        if width * .3 < x < width * .7 and height * .6 < y < height * .85:
            candidates.append((round(float(x)), round(float(y))))
    return candidates[0] if len(candidates) == 1 else None


def _ensure_process_identity(lifecycle):
    if lifecycle.identity is not None:
        return
    from AppKit import NSWorkspace

    from module.backends.playcover.lifecycle import read_app_identity

    url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(lifecycle.bundle_id)
    if url is None:
        raise RuntimeError("无法定位配置的游戏应用，不能确认游戏是否已退出")
    identity = read_app_identity(str(url.path()))
    if identity.bundle_id != lifecycle.bundle_id:
        raise RuntimeError("游戏应用身份与配置不一致，已停止网络恢复")
    lifecycle.identity = identity


def recover_network_exit_notice():
    session = get_playcover_session()
    if getattr(session, "_network_startup_pending", False) is not True or auto.screenshot is None:
        return False
    point = _notice_position(auto.screenshot)
    if point is None:
        # An unknown loading frame is not proof of successful login. Preserve
        # the budget across init_game/retry/back_init_menu until gameplay is seen.
        if any(auto.find_element(target) for target in (
            "home/mail_assets.png", "mirror/road_in_mir/legend_assets.png", "battle/pause_assets.png",
        )):
            _reset(session)
        return False

    _ensure_process_identity(session.lifecycle)
    failures = session._network_startup_failures + 1
    session._network_startup_failures = failures
    log.warning(f"启动时检测到网络不稳定退出弹窗，第 {failures}/{MAX_STARTUP_ATTEMPTS} 次失败")
    try:
        auto.mouse_click(*point)
    except OSError:
        if session.lifecycle.process() is not None:
            raise  # Never blindly repeat an uncertain touch delivery.
    deadline = time.monotonic() + EXIT_WAIT_SECONDS
    while session.lifecycle.process() is not None and time.monotonic() < deadline:
        session.input.check_cancel()
        worker_sleep(.25)
    # The button may have already closed MaaTools; discard its old connection
    # before using the existing verified-process shutdown fallback.
    session.disconnect()
    if session.lifecycle.process() is not None:
        session.stop_game()
    auto.invalidate_screenshot_cache()
    session.input.check_cancel()
    if failures >= MAX_STARTUP_ATTEMPTS:
        _reset(session)
        message = "游戏启动因网络不稳定连续失败 4 次，已关闭游戏并停止当前任务"
        log.error(message)
        raise BackendCancelled(message)
    log.info("网络退出弹窗已确认，重新打开游戏")
    return True
