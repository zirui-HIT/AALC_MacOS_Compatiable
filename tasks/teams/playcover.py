"""English iOS daily formation, calibrated on 1.116.2 at logical 1920x1080."""

from __future__ import annotations

import re
import time

import numpy as np
from PIL import ImageEnhance

from module.automation import auto
from module.ocr import ocr


def participant_count() -> tuple[int, int]:
    for attempt in range(6):
        auto.take_screenshot()
        crop = auto.screenshot.crop((1580, 730, 1840, 825))
        # Mirror's disabled zero is darker than EXP's count. Enhance only this ROI.
        for image in (crop, ImageEnhance.Contrast(crop).enhance(2)):
            result = ocr.run(np.array(image))
            text = "".join(result.txts or ()).replace(" ", "")
            match = re.search(r"(\d+)/(12)(?!\d)", text)
            if match is not None and 0 <= int(match[1]) <= 12:
                return int(match[1]), int(match[2])
        # Detector boxes can overlap in "12 / 12", producing "12", "2/12".
        # Read the two fixed counter cells independently instead of concatenating duplicates.
        counts = []
        for box in ((1695, 755, 1750, 820), (1770, 755, 1825, 820)):
            cell = ImageEnhance.Contrast(auto.screenshot.crop(box)).enhance(2)
            text = "".join(ocr.run(np.array(cell)).txts or ()).strip()
            counts.append(int(text) if re.fullmatch(r"\d{1,2}", text) else None)
        if counts[1] == 12 and counts[0] is not None and 0 <= counts[0] <= 12:
            return counts[0], counts[1]
        if attempt < 5:
            time.sleep(0.2)  # Wait for the disabled counter's fade, without toggling selections.
    raise RuntimeError("Cannot confirm iOS participant count")


def select_daily_team(number: int) -> bool:
    if number != 1:
        raise NotImplementedError("First iOS daily validation supports team #1; other team rows await validation")
    auto.take_screenshot()
    if not auto.find_element("teams/identify_assets.png"):
        raise RuntimeError("Cannot recognize iOS formation page")
    # This is a fast list gesture, never a long hold/reorder operation.
    for _ in range(10):
        auto.mouse_swipe_for_team_scroll(195, 480, dy=300, duration=0.2)
    auto.take_screenshot()
    auto.mouse_click(195, 470)
    time.sleep(0.3)
    return select_mirror_participants()


def select_mirror_participants() -> bool:
    """Deploy the already selected Mirror preset; its page has no team list."""
    auto.take_screenshot()
    if not auto.find_element("teams/identify_assets.png"):
        raise RuntimeError("Cannot recognize iOS formation page")
    current, maximum = participant_count()
    if maximum != 12:
        raise RuntimeError(f"Unvalidated iOS formation capacity: {maximum}")
    if current:
        if not auto.click_element("teams/clear_selection.png", offset=False):
            raise RuntimeError("Cannot recognize iOS Clear Selection")
        for _ in range(15):
            time.sleep(0.2)
            auto.take_screenshot()
            if auto.find_element("teams/reset_deployment.png") and auto.find_element("teams/clear_selection_confirm_assets.png"):
                auto.click_element("teams/clear_selection_confirm_assets.png", offset=False)
                break
        else:
            raise RuntimeError("Cannot recognize the settled Reset Deployment dialog")
        for _ in range(10):
            time.sleep(0.2)
            auto.take_screenshot()
            if not auto.find_element("teams/reset_deployment.png"):
                break
        else:
            raise RuntimeError("Reset Deployment confirmation did not close")
        if participant_count()[0] != 0:
            raise RuntimeError("Clear Selection was not confirmed; no toggle clicks were repeated")
    # Row-major order: seven active slots and five backups for EXP #10 (Blunt).
    for y in (350, 650):
        for x in (440, 640, 840, 1040, 1240, 1440):
            auto.take_screenshot()
            auto.mouse_click(x, y)
            time.sleep(0.1)
    if participant_count() != (12, 12):
        raise RuntimeError("iOS selection was not confirmed as 12/12")
    return True
