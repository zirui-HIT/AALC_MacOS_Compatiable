import gc
import inspect
import math
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import psutil
from PIL.Image import Image

from utils.image_utils import ImageUtils
from utils.path_manager import path_manager
from utils.singletonmeta import SingletonMeta

from ..config import cfg, theme_list
from ..logger import log
from ..ocr import ocr
from .input_handlers import AbstractInput
from .screenshot import ScreenShot

# ponytail: 交互门最长关闭时间。监控线程卡在持久弹窗上时,超时放行业务输入,
# 恢复 retry() 等流程的卡死看门狗(kill_game/restart_game)。
GATE_WAIT_TIMEOUT = 30.0
_FRAME_CACHE_MISS = object()


@dataclass(frozen=True)
class TextMatchResult:
    """Structured result for dict-based OCR target matches."""

    value: Any
    text: str
    position: list[float]


class Automation(metaclass=SingletonMeta):
    """自动化管理类，用于管理与游戏窗口有关的自动化操作"""

    def __init__(self, windows_title):
        self.task_running = False
        self._business_frame = None
        self._monitor_frame = None
        self.windows_title = windows_title
        self.screenshot = None
        self._reset_frame_cache()
        self._ocr_image = None
        self._ocr_regions = {}
        self._ocr_lock = threading.RLock()
        self.input_handler = AbstractInput()
        self._screenshot_lock = threading.RLock()
        self._latest_screenshot = None
        self._latest_frame = None
        self._latest_screenshot_monotonic = 0.0
        self._input_lock = threading.RLock()
        self._interaction_gate = threading.Event()
        self._interaction_gate.set()

        self.init_input()

        self.img_cache = {}
        self._unavailable_feature_templates: set[str] = set()
        self.last_screenshot_time = 0
        self.last_click_time = 0
        self.model = "clam"

    def init_input(self):
        """初始化输入处理器，将输入操作如点击、拖动等绑定至实例变量"""
        if self.input_handler:
            self.input_handler = None
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            self.input_handler = get_playcover_session().input
            self.mouse_pinch = self._run_business_interaction("pinch")
        elif cfg.simulator:
            if cfg.simulator_type == 0:
                from .input_handlers.simulator.mumu_control import MumuControl

                log.debug("使用MuMu模拟器输入模块")
                if MumuControl.connection_device is not None:
                    self.input_handler = MumuControl.connection_device
            else:
                from .input_handlers.simulator.simulator_control import SimulatorControl

                log.debug("使用基于PyMiniTouch的通用模拟器输入模块")
                self.input_handler = SimulatorControl.connection_device
        else:
            input_type = cfg.win_input_type
            if input_type == "background":
                from .input_handlers.input import BackgroundInput

                log.debug("使用后台点击模块")
                self.input_handler = BackgroundInput()
            elif input_type == "foreground":
                from .input_handlers.input import Input

                log.debug("使用前台点击模块")
                self.input_handler = Input()
            elif input_type == "window_move":
                from .input_handlers.input import WindowMoveInput

                log.debug("使用基于窗口移动的后台点击模块")
                self.input_handler = WindowMoveInput()
        if self.input_handler is None:
            if cfg.backend == "playcover":
                raise ConnectionError("PlayCover input is unavailable")
            from .input_handlers.input import BackgroundInput

            self.input_handler = BackgroundInput()
        assert isinstance(self.input_handler, AbstractInput), "输入处理器必须是AbstractInput的实例"
        self.set_pause = self.input_handler.set_pause
        self.wait_pause = self.input_handler.wait_pause

        methods = inspect.getmembers(AbstractInput, predicate=inspect.isfunction)
        for name, method in methods:
            if name.startswith("mouse_") or name.startswith("key_") or name.startswith("input_"):
                method = self._run_business_interaction(name)
                setattr(self, name, method)
        self.memory_protection = cfg.memory_protection

    def suspend_interactions(self) -> None:
        """暂时阻止业务线程继续点击。"""
        self._interaction_gate.clear()

    def resume_interactions(self) -> None:
        """恢复业务线程点击。"""
        self._interaction_gate.set()

    def reset_safety_locks(self) -> None:
        """线程被强制终止后换新锁,清除可能残留的持有状态。

        仅应在 my_script_task.terminate() 等硬杀路径调用:被杀线程持有的
        RLock 计数不会释放,不换锁则后续任务取锁永久阻塞。
        """
        self._input_lock = threading.RLock()
        self._screenshot_lock = threading.RLock()

    def _run_business_interaction(self, method_name: str):
        """在交互门放行且取得输入锁后执行一次业务输入。

        交互门可能在等待输入锁期间被监控线程关闭，因此取得锁后需要再次确认。
        门连续关闭超过 GATE_WAIT_TIMEOUT 时视为监控卡在持久弹窗上，放行业务
        输入，让业务流程自身的卡死兜底(如 check_times)得以继续运行。
        """

        def wrapper(*args, **kwargs):
            while True:
                if cfg.backend == "playcover":
                    from module.backends.factory import get_playcover_session

                    # Preserve the original deadline while polling cancellation.
                    deadline = time.monotonic() + GATE_WAIT_TIMEOUT
                    while True:
                        remaining = max(0.0, deadline - time.monotonic())
                        gate_open = self._interaction_gate.wait(timeout=min(0.1, remaining))
                        get_playcover_session().input.check_cancel()
                        if gate_open or time.monotonic() >= deadline:
                            break
                else:
                    gate_open = self._interaction_gate.wait(timeout=GATE_WAIT_TIMEOUT)
                with self._input_lock:
                    if gate_open and self._interaction_gate.is_set():
                        method = getattr(self.input_handler, method_name)
                        return self._invoke_input(method, self._business_frame, *args, **kwargs)
                    if not gate_open:
                        method = getattr(self.input_handler, method_name)
                        return self._invoke_input(method, self._business_frame, *args, **kwargs)
                    # gate_open 但等待输入锁期间门被关闭:重新等待

        return wrapper

    def monitor_mouse_click(self, x, y, times=1):
        """由系统监控线程点击，不等待该监控线程设置的互斥门。"""
        with self._input_lock:
            return self._invoke_input(self.input_handler.mouse_click, self._monitor_frame, x, y, times=times)

    def _invoke_input(self, method, frame, *args, **kwargs):
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            session = get_playcover_session()
            session.input.check_cancel()
            if frame is None:
                raise RuntimeError("Input needs a fresh recognized frame")
            if frame.geometry_version != session.geometry().version:
                raise RuntimeError("Geometry changed; capture and recognize the page again")
            with session.input.geometry_context(frame.geometry):
                if getattr(method, "__name__", None) == "mouse_to_blank":
                    return method(*args, **kwargs)
                self.invalidate_screenshot_cache()
                try:
                    return method(*args, **kwargs)
                finally:
                    self.invalidate_screenshot_cache()
        self._reset_frame_cache()
        try:
            return method(*args, **kwargs)
        finally:
            self._reset_frame_cache()

    def _capture(self, gray, monitor=False):
        if cfg.backend != "playcover":
            return ScreenShot.take_screenshot(gray)
        from module.backends.factory import get_playcover_session

        frame = get_playcover_session().capture()
        previous = self._business_frame
        if previous is not None and frame.geometry_version != previous.geometry_version:
            self.clear_img_cache()
            self._business_frame = None
            self.screenshot = None
        if monitor:
            self._monitor_frame = frame
        else:
            self._business_frame = frame
        return frame.image.convert("L") if gray else frame.image

    def request_stop(self):
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            get_playcover_session().request_stop()
        self.resume_interactions()

    def _remember_screenshot(self, screenshot: Image | None, frame=None) -> None:
        if screenshot is None:
            self._latest_screenshot_monotonic = 0.0
            return
        self._latest_screenshot = screenshot
        self._latest_frame = frame
        self._latest_screenshot_monotonic = time.monotonic()

    def invalidate_screenshot_cache(self) -> None:
        """让监控线程在下一轮检查时获取新截图。"""
        with self._screenshot_lock:
            self._latest_screenshot_monotonic = 0.0
            self._reset_frame_cache()

    def take_monitor_screenshot(self, gray: bool = True, max_age: float = 0.0) -> Image | None:
        """获取监控截图，优先复用业务线程的最近帧且不覆盖业务截图。"""
        with self._screenshot_lock:
            if (
                self._latest_screenshot is not None
                and max_age > 0
                and time.monotonic() - self._latest_screenshot_monotonic <= max_age
            ):
                self._monitor_frame = self._latest_frame
                if gray and self._latest_screenshot.mode != "L":
                    return self._latest_screenshot.convert("L")
                return self._latest_screenshot

            screenshot = self._capture(gray, monitor=True)
            self._remember_screenshot(screenshot, self._monitor_frame)
            return screenshot

    def check_pause(self) -> bool:
        """
        检查是否处于暂停状态

        Returns:
            bool: 是否处于暂停状态
        """
        return self.input_handler.is_pause

    def get_restore_time(self) -> float:
        """
        获取上一次结束暂停的时间
        Returns:
            float: 上一次结束暂停的时间
        """
        return self.input_handler.restore_time if self.input_handler.restore_time else 0

    def click_element(
        self,
        target,
        find_type="image",
        threshold=0.8,
        max_retries=1,
        take_screenshot=False,
        offset=True,
        action="click",
        times=1,
        dx=0,
        dy=0,
        model=None,
        my_crop=None,
        click=True,
        drag_time=None,
        interval=0.5,
    ):
        """查找并点击屏幕上的元素"""
        if model is None:
            model = self.model
        coordinates = self.find_element(
            target,
            find_type,
            threshold,
            max_retries,
            take_screenshot,
            model=model,
            my_crop=my_crop,
            additional_stack=1,
        )
        if coordinates:
            if click:
                return self.mouse_action_with_pos(
                    coordinates,
                    offset,
                    action,
                    times,
                    drag_time,
                    dx,
                    dy,
                    find_type,
                    interval,
                )
            return coordinates
        return False

    def calculate_click_position(self, coordinates, offset=True):
        """
        根据给定的坐标计算点击位置。
        参数:
        coordinates (tuple): 一个包含(x, y)坐标的元组，表示点击的位置。
        返回:
        tuple: 经过计算后的点击位置坐标。
        """
        # TODO:后续适配无需窗口设置模式
        x, y = coordinates
        screenshot = self.get_screenshot_array()
        if offset:
            x = max(0, min(screenshot.shape[1], x + random.randint(-10, 10)))
            y = max(0, min(screenshot.shape[0], y + random.randint(-10, 10)))
        return x, y

    def mouse_action_with_pos(
        self,
        coordinates,
        offset=True,
        action="click",
        times=1,
        drag_time=None,
        dx=0,
        dy=0,
        find_type=None,
        interval=0.5,
    ) -> bool:
        """
        在指定坐标上执行点击操作
        Args:
            coordinates: 坐标位置，用于计算点击位置
            offset: 是否使用偏移量计算点击位置，默认为True
            action: 鼠标操作类型，默认为"click"
            move_back: 是否在操作后将鼠标移动回原位置，默认为False
        Returns:
           bool (True) : 总是返回True表示操作执行完毕
        """
        if find_type == "image_with_multiple_targets" and len(coordinates) > 0:
            for c in coordinates:
                self.mouse_action_with_pos(
                    c,
                    offset=offset,
                    action=action,
                    times=times,
                    drag_time=drag_time,
                    dx=dx,
                    dy=dy,
                    find_type="image",
                    interval=1,
                )
            return True

        if cfg.mouse_action_interval and interval == 0.5:
            interval = cfg.mouse_action_interval

        if self.last_click_time == 0:
            self.last_click_time = time.time()
        wait_time = max(0, interval - (time.time() - self.last_click_time))
        time.sleep(wait_time)

        # 计算传入的位置
        self._interaction_gate.wait(timeout=GATE_WAIT_TIMEOUT)
        x, y = self.calculate_click_position(coordinates, offset)

        # 定义鼠标操作映射
        action_map = {
            "click": self.mouse_click,
            "drag": self.mouse_drag,
            "drag_down": self.mouse_drag_down,
            "scroll": self.mouse_scroll,
        }
        # 根据操作类型执行相应的鼠标操作
        if action in action_map:
            if action == "click":
                self.mouse_click(x, y, times=times)
            elif action == "drag":
                self.mouse_drag(x, y, drag_time=drag_time, dx=dx, dy=dy)
            elif action == "drag_down":
                self.mouse_drag_down(x, y)
            elif action == "scroll":
                self.mouse_scroll()
            self.last_click_time = time.time()
        else:
            # 如果操作类型未知，抛出异常
            raise ValueError(f"未知的操作类型{action}")

        return True

    def take_screenshot(self, gray: bool = True, *, max_age: float = 0.0) -> Image | None:
        """
        截取当前屏幕并返回图像对象。
        Args:
            gray (bool): 是否将图像转换为灰度图，默认为True。
            max_age (float): PlayCover 只读检查可复用的帧龄；默认仍获取新帧。
        Returns:
            Image: 截取当前屏幕的图像对象
        """
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            # Preserve the original capture cadence after touch input. MaaTools
            # has no acknowledgement that the UI has handled a touch yet.
            interval = cfg.screenshot_interval or 0.85
            session = get_playcover_session()
            session.input.check_cancel()
            with self._screenshot_lock:
                frame = self._latest_frame
                if (max_age > 0 and frame is not None and session.transport.connected
                        and self._latest_screenshot_monotonic > 0
                        and time.monotonic() - self._latest_screenshot_monotonic <= min(max_age, interval)
                        and frame.geometry_version == session.geometry().version):
                    self._business_frame = frame
                    if gray and self._latest_screenshot is not None and self._latest_screenshot.mode == "L":
                        self.screenshot = self._latest_screenshot
                    else:
                        self.screenshot = frame.image.convert("L") if gray else frame.image
                    self._latest_screenshot = self.screenshot
                    return self.screenshot
        start_time = time.time()
        screenshot_interval_time = cfg.screenshot_interval if cfg.screenshot_interval else 0.85
        while True:
            try:
                if time.time() - self.last_screenshot_time < screenshot_interval_time:
                    wait_time = max(
                        screenshot_interval_time - (time.time() - self.last_screenshot_time),
                        0,
                    )
                    if cfg.backend == "playcover":
                        session.cancel.wait(wait_time)
                        session.input.check_cancel()
                    else:
                        time.sleep(wait_time)

                with self._screenshot_lock:
                    result = self._capture(gray)
                    self._remember_screenshot(result, self._business_frame if cfg.backend == "playcover" else None)
                if result:
                    self.screenshot = result
                    self.last_screenshot_time = time.time()
                    return result
                else:
                    return None
            except Exception as e:
                log.error(f"截图失败:{e}")
            if cfg.backend == "playcover":
                session.cancel.wait(1)
                session.input.check_cancel()
            else:
                time.sleep(1)
            if time.time() - start_time > 60:
                log.error("截图超时，尝试重启游戏")
                if cfg.backend == "playcover":
                    session.stop_game()
                else:
                    import os

                    import win32process

                    from module.game_and_screen import screen

                    try:
                        _, pid = win32process.GetWindowThreadProcessId(screen.handle.hwnd)
                        os.system(f"taskkill /F /PID {pid}")
                    except:  # noqa: E722 - Preserve the original Windows recovery handler.
                        pass
                from tasks.base.script_task_scheme import init_game

                init_game()
                start_time = time.time()

    def _reset_frame_cache(self) -> None:
        """仅缓存当前截图的派生数据，不延长截图的复用时间。"""
        self._screenshot_array_source = None
        self._screenshot_array = None
        self._frame_match_cache = {}

    def get_screenshot_array(self):
        """复用同一截图的 NumPy 视图，兼容直接替换 screenshot 的调用。"""
        with self._screenshot_lock:
            if getattr(self, "_screenshot_array_source", None) is not self.screenshot:
                self._reset_frame_cache()
                self._screenshot_array_source = self.screenshot
            if self.screenshot is None:
                log.error("尚未截图，无法识别图片（请先执行 take_screenshot）")
                return None
            if self._screenshot_array is None:
                self._screenshot_array = np.asarray(self.screenshot)
            screenshot = self._screenshot_array
            if screenshot.ndim not in (2, 3) or screenshot.size == 0:
                log.error(f"无效的截图维度: {screenshot.shape}")
                return None
            return screenshot

    def _image_match_cache_key(self, target, threshold, model, my_crop):
        return (
            target, threshold, model, tuple(my_crop) if my_crop is not None else None,
            cfg.set_win_size, cfg.game_profile, path_manager.version,
            path_manager.current_theme, path_manager.current_language, tuple(path_manager.pic_path),
        )

    @staticmethod
    def _cache_frame_match(cache, key, value):
        if key is not None:
            if len(cache) >= 128:
                cache.clear()
            cache[key] = value

    def find_element(
        self,
        target,
        find_type="image",
        threshold=0.8,
        max_retries=1,
        take_screenshot=False,
        model=None,
        my_crop=None,
        min_dist=10,
        additional_stack=0,
    ):
        """
        查找元素，并根据指定的查找类型执行不同的查找策略。
        Args:
            target: 查找目标，可以是图像路径或文字。(zh_cn)->en->share
            find_type: 查找类型，例如'image', 'text'等。
            threshold: 查找阈值，用于图像查找时的相似度匹配。
            max_retries: 最大重试次数。
            take_screenshot: 是否需要先截图。
            model: 查找的策略,'clam' 为在模板图片位置查找，'normal' 为模板图片位置扩大范围查找，'aggressive' 为全截屏区域查找
            my_crop: 用于限制图像或OCR识别范围的裁剪区域
            min_dist: 多目标图像查找时的NMS最小距离。
            additional_stack: 用于日志堆栈层级调整
        Returns:
            查找到的元素位置，或者在图像计数查找时返回计数。
        """
        if model is None:
            model = self.model
        # 如果不需要截图，则重试次数设置为1
        max_retries = 1 if not take_screenshot else max_retries
        for i in range(max_retries):
            if take_screenshot:
                # 截图并根据裁剪参数获取截图结果
                while self.take_screenshot() is None:
                    continue
            # 根据查找类型执行不同的查找策略
            if find_type in ["image", "text"]:
                center = None
                if find_type in ["image"]:
                    # 使用图像查找方法查找元素
                    center = self.find_image_element(
                        target,
                        threshold,
                        model=model,
                        my_crop=my_crop,
                        additional_stack=additional_stack,
                    )
                    if (not center and my_crop is None and sys.platform == "darwin" and cfg.game_profile == "ios_en"
                            and path_manager.current_language == "en"):
                        center = self._find_event_grade(target)
                elif find_type == "text":
                    # 使用文本查找方法查找元素
                    center = self.find_text_element(target, my_crop, additional_stack=additional_stack)
                if center:
                    return center
            elif find_type in ["feature"]:
                return self.find_feature_element(target, my_crop, additional_stack=additional_stack)
            elif find_type in ["image_with_multiple_targets"]:
                # 使用多目标图像查找方法查找元素
                return self.find_image_with_multiple_targets(
                    target, threshold, my_crop=my_crop, min_dist=min_dist, additional_stack=additional_stack
                )
            else:
                raise ValueError("错误的类型")

            if i < max_retries - 1:
                time.sleep(1)  # 在重试前等待一定时间
        return None

    def find_image_with_multiple_targets(
        self, target: str, threshold, my_crop=None, min_dist=10, additional_stack=0
    ) -> list:
        """
        在当前截图中查找多个目标图像的位置
        """
        try:
            screenshot = self.get_screenshot_array()
            if screenshot is None:
                return []
            cache = self._frame_match_cache
            cache_key = ("multiple", min_dist, self._image_match_cache_key(target, threshold, None, my_crop)) if self._path_state_is_known() else None
            cached = cache.get(cache_key, _FRAME_CACHE_MISS)
            if cached is not _FRAME_CACHE_MISS:
                return list(cached)
            template = ImageUtils.load_image(target)
            if target.endswith("assets.png"):
                bbox = ImageUtils.get_bbox(template)
                template = ImageUtils.crop(template, bbox)
            if template is None:
                raise ValueError("读取图片失败")
            crop_offset = (0, 0)
            if my_crop:
                crop_offset = (int(round(my_crop[0])), int(round(my_crop[1])))
                screenshot = ImageUtils.crop(screenshot, my_crop)
            elif (
                sys.platform == "darwin" and cfg.game_profile == "ios_en" and min_dist == 10
                and screenshot.shape[:2] in ((810, 1440), (1080, 1920))
                and (threshold == 0.8 or (target == "luxcavation/exp_enter.png" and threshold == 0.85))
            ):
                # Only layouts covered by the non-OCR replay; coordinates use a 1080px baseline.
                roi = {
                    "mirror/theme_pack/theme_pack_features.png": (0, 220, 1920, 450),
                    "luxcavation/exp_enter.png": (0, 550, 1920, 850),
                    "teams/selected.png": (0, 200, 1920, 800),
                    "pass/pass_coin.png": (0, 250, 1920, 1050),
                }.get(target)
                if roi:
                    bounds = [int(round(value * screenshot.shape[0] / 1080)) for value in roi]
                    crop_offset = (bounds[0], bounds[1])
                    screenshot = ImageUtils.crop(screenshot, bounds)
            matches = ImageUtils.match_template_with_multiple_targets(
                screenshot, template, threshold, min_dist=min_dist
            )
            if crop_offset != (0, 0):
                matches = [(x + crop_offset[0], y + crop_offset[1]) for x, y in matches]
            self._cache_frame_match(cache, cache_key, tuple(matches))
            if len(matches) == 0:
                log.debug(f"未找到任何目标图像{target}", stacklevel=additional_stack + 3)
                return []
            else:
                log.debug(
                    f"找到{len(matches)}个目标：{matches}",
                    stacklevel=additional_stack + 3,
                )
                return matches
        except Exception as e:
            log.error(f"寻找图片出错:{e}")
            return []

    def find_regions_by_color(self, roi, mask_fn, min_area=300, min_dist=80) -> list | None:
        """
        Args:
            roi: (x1, y1, x2, y2) 1440 高度基准坐标，内部按实际截图高度自动缩放
            mask_fn: callable(ROI的RGB ndarray) -> uint8 掩码(0/255)
            min_area/min_dist: 透传 ImageUtils.match_color_regions

        Returns:
            list[(cx, cy, area)]: 颜色区域质心与面积；无匹配返回 []，匹配出错返回 None
        """
        while self.take_screenshot(gray=False) is None:
            continue
        color_image = np.array(self.screenshot)
        if self.screenshot.mode != "L":
            self.screenshot = self.screenshot.convert("L")
        regions = ImageUtils.match_color_regions(
            color_image, mask_fn, roi=roi, min_area=min_area, min_dist=min_dist
        )
        if regions is not None:
            log.debug(f"颜色匹配到{len(regions)}个区域：{regions}", stacklevel=3)
        return regions

    def find_str_in_text(self, target, ocr_dict):
        """
        返回目标文本的坐标
        """
        # YAML 中的 && 要求同一卡包裁剪内同时命中各片段，允许 OCR 分行。
        if "&&" in target:
            parts = [part.strip() for part in target.split("&&")]
            positions = [self.find_str_in_text(part, ocr_dict) for part in parts] if all(parts) else []
            return positions[0] if positions and all(positions) else False
        targets = [target]
        if cfg.game_profile == "ios_zh_cn":
            targets += ImageUtils.ios_zh_cn_profile().get("text_aliases", {}).get(target, [])
        targets = [ImageUtils.normalize_ocr_text(value) for value in targets]
        for raw_text in ocr_dict.keys():
            text = ImageUtils.normalize_ocr_text(raw_text)
            for target in targets:
                if target.lower() in text.lower():
                    log.debug(f"识别到目标：{raw_text},坐标为：{ocr_dict[raw_text]}")
                    return ocr_dict[raw_text]
                # 去除空格后再匹配，解决OCR识别结果带空格的问题（如 "HongLu" vs "Hong Lu"）
                if target.replace(" ", "").lower() in text.replace(" ", "").lower():
                    log.debug(f"识别到目标（去空格匹配）：{raw_text},坐标为：{ocr_dict[raw_text]}")
                    return ocr_dict[raw_text]
        return False

    def _run_ocr_for_text(
        self, my_crop=None, only_text=False, additional_stack=0, target=None, zh_target=None, all_text=False
    ):
        ocr_result = self._ocr_for_target(target, my_crop, zh_target, all_text) if not only_text else self._ocr_screenshot(my_crop)

        if not ocr_result.txts:
            return False if only_text else {}

        ocr_text_list = [ocr_result.txts[i] for i in range(len(ocr_result.txts))]
        if only_text:
            return ocr_text_list

        ocr_position_list = []
        for box in ocr_result.boxes:
            x = (box[0][0] + box[2][0]) / 2
            y = (box[0][1] + box[2][1]) / 2
            ocr_position_list.append([x, y])

        ocr_dict = {text: position for text, position in zip(ocr_text_list, ocr_position_list)}
        log.debug(f"识别到文本及其坐标：{ocr_dict}", stacklevel=additional_stack + 3)
        return ocr_dict

    def _ocr_for_target(self, target, my_crop, zh_target=None, all_text=False):
        """Choose only validated English OCR profiles; matching stays unchanged."""
        profile = None
        if sys.platform == "darwin" and cfg.game_profile == "ios_en" and path_manager.current_language == "en":
            if isinstance(target, str):
                pair = (zh_target, target.lower())
                if pair == ("已持有", "owned") and my_crop is not None:
                    profile = "owned"
                elif pair in (("拒绝饰品", "refuse"), ("选择", "select"), ("胜率", "rate"), ("判定", "check")):
                    profile = "buttons"
            elif isinstance(target, list) and my_crop is not None:
                if tuple(target) in (
                    ("0/1", "01", "1/1", "11", "1/2", "12", "/1"),
                    ("0/2", "02", "2/2", "22", "/2"),
                ):
                    profile = "count"
                elif tuple(target) in (
                    ("continue", "proceed", "commence", "choices", "confirm", "行判", "始战", "继续"),
                    ("conti", "proc", "comme", "choices", "confirm", "行判", "始战", "继续"),
                ):
                    profile = "buttons"
            elif isinstance(target, dict) and my_crop is not None and "unknown" in target:
                pack_keys = set(theme_list.config.get("theme_pack_list", {})) | set(
                    theme_list.config.get("theme_pack_list_hard", {})
                )
                if len(target) > 1 and set(target) <= pack_keys:
                    profile = "pack"
        if profile is None:
            return self._ocr_screenshot(my_crop)

        region = my_crop
        if profile == "owned":
            x1, y1, x2, y2 = my_crop
            region = (x1, y1, x2, y1 + round((y2 - y1) * 0.16))
        with self._ocr_lock:
            image = self.screenshot
            result = self._ocr_screenshot(region, engine="vision", image=image)
            valid = result is not None
            texts = (result.txts or ()) if valid else ()
            if profile == "count":
                counts = [
                    match.groups() for text in texts
                    for match in re.finditer(r"(?<![\w/])([0-2])/([12])(?![\w/])", re.sub(r"\s*/\s*", "/", text))
                ]
                valid = len(counts) == 1 and int(counts[0][0]) <= int(counts[0][1])
            elif profile in {"pack", "buttons"}:
                keys = [target] if isinstance(target, str) else [key for key in target if key != "unknown"]
                hits = [
                    any(str(key).replace(" ", "").lower() in text.replace(" ", "").lower() for text in texts)
                    for key in keys
                ]
                valid = valid and (all(hits) if all_text else any(hits))
            if not valid:
                result = self._ocr_screenshot(region, image=image)
            return result

    def _ocr_screenshot(self, my_crop=None, engine="rapid", image=None):
        """同一图像、裁剪及引擎复用推理；关键词匹配和返回值仍由原代码处理。"""
        image = self.screenshot if image is None else image
        with self._ocr_lock:
            if self._ocr_image is not image:
                self._ocr_image = image
                self._ocr_regions.clear()
            region = (tuple(my_crop) if my_crop is not None else None, engine, cfg.game_profile)
            if region not in self._ocr_regions:
                if len(self._ocr_regions) >= 32:
                    self._ocr_regions.clear()
                pixels = image.crop(my_crop) if my_crop is not None else image
                result = ocr.run_vision(pixels) if engine == "vision" else ocr.run(pixels)
                if result is None:  # Warming up/busy: retry Vision on a later request.
                    return None
                self._ocr_regions[region] = result
            return self._ocr_regions[region]

    def _find_event_grade(self, target):
        """Recognize the existing grade asset at its actual iOS text position."""
        if not isinstance(target, str):
            return None
        grades = {
            "event/very_high.png": "veryhigh", "event/high.png": "high",
            "event/normal.png": "normal", "event/low.png": "low",
            "event/very_low.png": "verylow",
        }
        label = grades.get(target)
        if label is None or self.screenshot is None:
            return None
        scale = self.screenshot.height / 1440
        region = tuple(round(value * scale) for value in (50, 1180, 1780, 1270))
        for engine in ("vision", "rapid"):
            result = self._ocr_screenshot(region, engine=engine)
            if result is None or not result.txts:
                continue
            for text, box in zip(result.txts, result.boxes):
                compact = re.sub(r"\s+", "", text).lower()
                if compact == label:
                    return [region[0] + (box[0][0] + box[2][0]) / 2,
                            region[1] + (box[0][1] + box[2][1]) / 2]
                if label not in compact or compact in grades.values():
                    continue
                # OCR can join adjacent grades; separate the original 12 slots.
                for index in range(12):
                    x = 150 + 140 * index
                    cell = tuple(round(value * scale) for value in (x - 68, 1180, x + 68, 1270))
                    if cell[2] < region[0] + box[0][0] or cell[0] > region[0] + box[2][0]:
                        continue
                    separated = self._ocr_screenshot(cell, engine=engine)
                    if separated is None or not separated.txts:
                        continue
                    for word, bounds in zip(separated.txts, separated.boxes):
                        if re.sub(r"\s+", "", word).lower() == label:
                            return [cell[0] + (bounds[0][0] + bounds[2][0]) / 2,
                                    cell[1] + (bounds[0][1] + bounds[2][1]) / 2]
        return None

    def _find_target_in_ocr_dict(self, target, ocr_dict, all_text=False):
        if ocr_dict == {}:
            return False
        if isinstance(target, str):
            return self.find_str_in_text(target, ocr_dict)
        elif isinstance(target, list):
            if all_text:
                for key in target:
                    if self.find_str_in_text(str(key), ocr_dict) is False:
                        return False
                return True
            for key in target:
                if result := self.find_str_in_text(str(key), ocr_dict):
                    return result
            return False
        elif isinstance(target, dict):
            for key, value in target.items():
                if position := self.find_str_in_text(str(key), ocr_dict):
                    return TextMatchResult(value=value, text=str(key), position=position)
            return None
        return False

    def find_language_text(
        self,
        zh_text,
        en_text,
        my_crop=None,
        all_text=False,
        additional_stack=0,
    ):
        """
        按当前语言状态查找中英文文本，并在语言未知时用命中结果同步语言。

        该方法复用同一份 OCR 结果匹配文本，必要时在识别层回退引擎：
        - 当前语言为 zh_cn 时，只匹配 zh_text。
        - 当前语言为 en 时，只匹配 en_text。
        - 当前语言未知时，先匹配 zh_text；中文命中则同步语言为 zh_cn。
        - 中文未命中时再匹配 en_text；英文命中则同步语言为 en，并移除 zh_cn 图片路径。

        Args:
            zh_text: 中文目标文本，支持 str、list、dict，规则同 find_text_element。
            en_text: 英文目标文本，支持 str、list、dict，规则同 find_text_element。
            my_crop: OCR 裁剪区域，格式为 (x1, y1, x2, y2)；为 None 时识别整张截图。
            all_text: 当目标文本为 list 时，是否要求列表内所有关键词全部命中。
            additional_stack: 日志 stacklevel 补偿，用于让日志定位到业务调用处。

        Returns:
            文本命中结果，返回格式同 find_text_element；未命中返回 False。
        """
        ocr_dict = self._run_ocr_for_text(
            my_crop=my_crop, additional_stack=additional_stack, target=en_text, zh_target=zh_text, all_text=all_text
        )
        if ocr_dict == {}:
            return False

        if path_manager.current_language == "zh_cn":
            return self._find_target_in_ocr_dict(zh_text, ocr_dict, all_text=all_text)
        if path_manager.current_language == "en":
            return self._find_target_in_ocr_dict(en_text, ocr_dict, all_text=all_text)

        zh_result = self._find_target_in_ocr_dict(zh_text, ocr_dict, all_text=all_text)
        if zh_result is not False and zh_result is not None:
            path_manager.set_language("zh_cn", log_stacklevel=additional_stack + 4)
            return zh_result

        en_result = self._find_target_in_ocr_dict(en_text, ocr_dict, all_text=all_text)
        if en_result is not False and en_result is not None:
            path_manager.set_language("en", log_stacklevel=additional_stack + 4)
            if path_manager.eliminate_zh_cn_paths():
                self.clear_img_cache()
            return en_result

        return False

    def find_text_element(self, target, my_crop=None, all_text=False, only_text=False, additional_stack=0):
        """
        寻找文本元素所在的坐标位置。

        str/list 目标返回坐标；dict 目标返回 TextMatchResult。
        """
        ocr_result = self._run_ocr_for_text(
            my_crop=my_crop, only_text=only_text, additional_stack=additional_stack, target=target, all_text=all_text
        )
        if only_text:
            return ocr_result
        return self._find_target_in_ocr_dict(target, ocr_result, all_text=all_text)

    def get_text_from_screenshot(self, my_crop=None):
        """
        从屏幕截图中提取文字
        """
        ocr_result = self._ocr_screenshot(my_crop)
        if ocr_result.txts:
            ocr_text_list = [ocr_result.txts[i] for i in range(len(ocr_result.txts))]
        else:
            ocr_text_list = []

        return ocr_text_list

    def find_feature_element(self, target, pic_crop=None, min_matches=8, additional_stack=0):
        """
        寻找特征元素所在的坐标位置
        """
        try:
            unavailable_templates = getattr(self, "_unavailable_feature_templates", None)
            if unavailable_templates is None:
                unavailable_templates = set()
                self._unavailable_feature_templates = unavailable_templates
            if target in unavailable_templates:
                return None

            template = ImageUtils.load_image(target, resize=False)
            if template is None or not isinstance(template, np.ndarray) or template.size == 0:
                unavailable_templates.add(target)
                return None

            if self.screenshot is None:
                return None
            screenshot = self.get_screenshot_array()
            if screenshot is None:
                return None
            if screenshot.size == 0 or screenshot.ndim < 2 or 0 in screenshot.shape[:2]:
                return None
            if cfg.set_win_size < 1440:
                screenshot = cv2.resize(
                    screenshot,
                    None,
                    fx=1440 / cfg.set_win_size,
                    fy=1440 / cfg.set_win_size,
                    interpolation=cv2.INTER_AREA,
                )
            elif cfg.set_win_size > 1440:
                screenshot = cv2.resize(
                    screenshot,
                    None,
                    fx=cfg.set_win_size / 1440,
                    fy=cfg.set_win_size / 1440,
                    interpolation=cv2.INTER_AREA,
                )
            if pic_crop:
                if cfg.set_win_size < 1440:
                    pic_crop = [int(i * 1440 / cfg.set_win_size) for i in pic_crop]
                elif cfg.set_win_size > 1440:
                    pic_crop = [int(i * cfg.set_win_size / 1440) for i in pic_crop]
                screenshot = ImageUtils.crop(screenshot, pic_crop)
                if screenshot.size == 0 or screenshot.ndim < 2 or 0 in screenshot.shape[:2]:
                    return None
            result, num_matches = ImageUtils.feature_matching(template, screenshot, min_matches)
            log.debug(
                f"匹配目标特征图片：{target.replace('./assets/images/', '')}结果{result}, 找到 {num_matches} 个匹配点",
                stacklevel=additional_stack + 3,
            )
            return result
        except Exception as e:
            error_message = str(e)
            if "cv::flann" in error_message:
                pass
            else:
                log.error(f"匹配图片特征失败:{e}")
            return None

    def clear_img_cache(self) -> None:
        """清除图片缓存"""
        self.img_cache.clear()
        self._reset_frame_cache()
        self._ocr_image = None
        self._ocr_regions.clear()
        self._unavailable_feature_templates.clear()
        gc.collect()  # 强制垃圾回收，清理内存
        log.debug("图片缓存已清除", stacklevel=2)

    def _load_template_for_path(self, target: str, target_path: str, cacheable: bool):
        cache_key = (target, str(ImageUtils.resolve_path(target_path, target)), cfg.set_win_size, cfg.game_profile, getattr(path_manager, "version", 0))
        if cacheable and cache_key in self.img_cache:
            cached = self.img_cache[cache_key]
            return cached["template"], cached["bbox"]

        template = ImageUtils.load_from_specific_path(target, target_path)
        if template is None:
            return None, None
        if target.endswith("assets.png"):
            bbox = ImageUtils.get_bbox(template)
            template = ImageUtils.crop(template, bbox)
        else:
            bbox = None
        if cacheable:
            self.img_cache[cache_key] = {"template": template, "bbox": bbox}
        return template, bbox

    @staticmethod
    def _is_valid_match(match_val, threshold) -> bool:
        return (
            isinstance(match_val, (int, float, np.integer, np.floating))
            and not math.isinf(match_val)
            and match_val >= threshold
        )

    MATCH_GAP = 0.15

    def _update_path_state_from_match_results(self, results, additional_stack: int = 0) -> None:
        dark_results = [result for result in results if path_manager.is_path_dark(result["path"])]
        default_results = [result for result in results if path_manager.is_path_default(result["path"])]
        zh_cn_results = [result for result in results if path_manager.is_path_zh_cn(result["path"])]
        en_results = [result for result in results if result["path"].endswith("/en")]
        share_results = [result for result in results if result["path"].endswith("/share")]

        dark_matched = any(result["matched"] for result in dark_results)
        default_matched = any(result["matched"] for result in default_results)

        path_changed = False
        if dark_matched and not default_matched:
            path_manager.set_theme("dark", log_stacklevel=additional_stack + 4)
        elif default_matched and dark_results and not dark_matched:
            path_manager.set_theme("default", log_stacklevel=additional_stack + 4)
            path_changed = path_manager.eliminate_dark_paths() or path_changed
        elif dark_matched and default_matched:
            best_dark = max(r["matchVal"] for r in dark_results if r["matched"])
            best_default = max(r["matchVal"] for r in default_results if r["matched"])
            if best_default - best_dark > self.MATCH_GAP:
                path_manager.set_theme("default", log_stacklevel=additional_stack + 4)
                path_changed = path_manager.eliminate_dark_paths() or path_changed
            elif best_dark - best_default > self.MATCH_GAP:
                path_manager.set_theme("dark", log_stacklevel=additional_stack + 4)

        zh_cn_matched = any(result["matched"] for result in zh_cn_results)
        en_matched = any(result["matched"] for result in en_results)
        share_matched = any(result["matched"] for result in share_results)

        # share 路径是语言无关资源，不能单独决定语言为英文
        if zh_cn_matched and not en_matched:
            path_manager.set_language("zh_cn", log_stacklevel=additional_stack + 4)
        elif en_matched and not zh_cn_matched:
            path_manager.set_language("en", log_stacklevel=additional_stack + 4)
            path_changed = path_manager.eliminate_zh_cn_paths() or path_changed
        elif zh_cn_matched and en_matched:
            best_zh = max(r["matchVal"] for r in zh_cn_results if r["matched"])
            best_en = max(r["matchVal"] for r in en_results if r["matched"])
            if best_en - best_zh > self.MATCH_GAP:
                path_manager.set_language("en", log_stacklevel=additional_stack + 4)
                path_changed = path_manager.eliminate_zh_cn_paths() or path_changed
            elif best_zh - best_en > self.MATCH_GAP:
                path_manager.set_language("zh_cn", log_stacklevel=additional_stack + 4)
        elif share_matched:
            # 仅命中 share 时保持当前语言未知/不变，等待后续专属语言资源判定
            pass

        if path_changed:
            self.clear_img_cache()

    @staticmethod
    def _path_state_is_known() -> bool:
        return path_manager.current_theme is not None and path_manager.current_language is not None

    def find_image_element(
        self,
        target: str,
        threshold,
        cacheable=True,
        model="clam",
        my_crop=None,
        additional_stack=0,
    ):
        """
        在当前截图中查找目标图像的位置
        """
        try:
            if self.memory_protection:
                memory = psutil.virtual_memory()
                # memory.percent 直接返回当前已使用的百分比 (0.0 到 100.0)
                current_percent = memory.percent
                if current_percent > 90:
                    log.debug(f"当前系统内存总占用率: {current_percent}%，释放图片缓存")
                    self.clear_img_cache()

            screenshot = self.get_screenshot_array()
            if screenshot is None:
                return None
            cache = self._frame_match_cache
            cache_key = self._image_match_cache_key(target, threshold, model, my_crop) if cacheable and self._path_state_is_known() else None
            cached = cache.get(cache_key, _FRAME_CACHE_MISS)
            if cached is not _FRAME_CACHE_MISS:
                return cached

            existing_paths = ImageUtils.existing_image_paths(target)
            if not existing_paths:
                log.error(f"未找到图片： {target} ")
                log.debug(f"无法加载图片: {target}", stacklevel=additional_stack + 3)
                return None

            if my_crop:
                screenshot = ImageUtils.crop(screenshot, my_crop)

            results = []
            for loaded_path in existing_paths:
                template, bbox = self._load_template_for_path(target, loaded_path, cacheable)
                if template is None:
                    continue
                center, matchVal = ImageUtils.match_template(screenshot, template, bbox, model)
                if loaded_path.endswith(("/ios_en", "/ios_zh_cn")):
                    center = tuple(round(v) for v in ImageUtils.layout_point(f"image.{target}.anchor", center, cfg.set_win_size / 1440))
                matched = self._is_valid_match(matchVal, threshold)
                if 0.70 < matchVal < 0.90 and int(matchVal * 1000 + 1e-9) % 10 >= 5:
                    match_fmt = ".3f"
                else:
                    match_fmt = ".2f"
                log.debug(
                    f"目标图片：{target.replace('./assets/images/', '')}, 路径: {loaded_path}, 相似度：{matchVal:{match_fmt}}, 目标位置：{center}",
                    stacklevel=additional_stack + 3,
                )
                results.append(
                    {
                        "path": loaded_path,
                        "center": center,
                        "matched": matched,
                        "matchVal": matchVal,
                    }
                )
                if matched and self._path_state_is_known():
                    self._cache_frame_match(cache, cache_key, center)
                    return center

            if not results:
                log.debug(f"无法加载图片: {target}", stacklevel=additional_stack + 3)
                return None

            self._update_path_state_from_match_results(results, additional_stack=additional_stack)
            for result in results:
                if result["matched"]:
                    return result["center"]
            self._cache_frame_match(cache, cache_key, None)
        except Exception as e:
            log.error(f"寻找图片失败:{e}")
        return None

    def get_screenshot_crop(self, crop):
        """
        获取指定区域的彩色截图
        """
        self.take_screenshot(False)
        screenshot = self.get_screenshot_array()
        screenshot = screenshot[:, :, ::-1]
        screenshot = ImageUtils.crop(screenshot, crop)
        return screenshot.copy()
