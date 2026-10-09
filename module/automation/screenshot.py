"""Compatibility screenshot facade. Platform imports stay in implementations."""

import time

from module.config import cfg


class ScreenShot:
    @staticmethod
    def take_screenshot(gray=True):
        if cfg.backend == "playcover":
            from module.backends.factory import get_playcover_session

            image = get_playcover_session().capture().image
            return image.convert("L") if gray else image
        from .windows_screenshot import ScreenShot as LegacyScreenShot

        return LegacyScreenShot.take_screenshot(gray)

    @staticmethod
    def screenshot_benchmark(test_time=10):
        if cfg.backend != "playcover":
            from .windows_screenshot import ScreenShot as LegacyScreenShot

            return LegacyScreenShot.screenshot_benchmark(test_time)
        started = time.monotonic()
        for _ in range(test_time):
            ScreenShot.take_screenshot(False)
        return True, (time.monotonic() - started) / test_time * 1000
