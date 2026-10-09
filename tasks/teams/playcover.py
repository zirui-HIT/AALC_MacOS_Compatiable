"""English iOS daily formation, calibrated on 1.116.2 at logical 1920x1080."""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher

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
            match = re.search(r"(\d+)/(\d{1,2})(?!\d)", text)
            if match is not None and 0 <= int(match[1]) <= int(match[2]) <= 12:
                return int(match[1]), int(match[2])
        # Detector boxes can overlap in "12 / 12", producing "12", "2/12".
        # Read the two fixed counter cells independently instead of concatenating duplicates.
        counts = []
        for box in ((1695, 755, 1750, 820), (1770, 755, 1825, 820)):
            cell = ImageEnhance.Contrast(auto.screenshot.crop(box)).enhance(2)
            text = "".join(ocr.run(np.array(cell)).txts or ()).strip()
            counts.append(int(text) if re.fullmatch(r"\d{1,2}", text) else None)
        if counts[1] is not None and counts[0] is not None and 0 <= counts[0] <= counts[1] <= 12:
            return counts[0], counts[1]
        if attempt < 5:
            time.sleep(0.2)  # Wait for the disabled counter's fade, without toggling selections.
    raise RuntimeError("Cannot confirm iOS participant count")


def select_preset(number: int, *, by_order: bool) -> None:
    """Select a named TEAMS#N row or an ordinal row, including scrolled presets."""
    from tasks.common.ios_pages import normalized, text_hits

    if not 1 <= number <= 40:
        raise ValueError("Preset number must be between 1 and 40")
    auto.take_screenshot()
    # The list is present during preset selection and EXP/Thread deployment.
    # In a dungeon deployment page only the current preset card is shown.
    if not any(normalized(hit.text) == "teams" for hit in text_hits(auto, (110, 400, 290, 450))):
        raise RuntimeError("This page has no iOS preset list; cannot change presets here")
    for _ in range(10):
        auto.mouse_swipe_for_team_scroll(195, 480, dy=300, duration=0.2)
    time.sleep(0.2)
    if by_order:
        # Six complete rows and a partial seventh; each page advances five rows.
        page_start = min(((number - 1) // 5) * 5, 34)
        scrolled = 0
        while scrolled < page_start:
            rows = min(5, page_start - scrolled)
            auto.mouse_swipe_for_team_scroll(195, 755, dy=-55 * rows, duration=0.2)
            scrolled += rows
            time.sleep(0.3)
        auto.take_screenshot()
        y = 470 + (number - 1 - page_start) * 55
        row = text_hits(auto, (115, y - 20, 280, y + 20))
        if not row:
            raise RuntimeError(f"iOS preset row #{number} is empty")
        expected_name = normalized("".join(hit.text for hit in row))
        auto.mouse_click(195, y)
    else:
        for _ in range(9):
            auto.take_screenshot()
            hit = next((hit for hit in text_hits(auto, (110, 445, 285, 800))
                        if normalized(hit.text) in {f"teams{number}", f"tfams{number}"}), None)
            if hit:
                expected_name = normalized(hit.text)
                auto.mouse_click(*hit.point)
                break
            auto.mouse_swipe_for_team_scroll(195, 755, dy=-275, duration=0.2)
            time.sleep(0.3)
        else:
            raise RuntimeError(f"No preset named TEAMS#{number}; for renamed presets enable Select Team by Order")
    time.sleep(0.3)
    auto.take_screenshot()
    selected_name = normalized("".join(hit.text for hit in text_hits(auto, (320, 160, 662, 212))))
    # Both the list and title clip custom names; compare their shared interior,
    # excluding the first/last glyph where partial clipping changes OCR letters.
    expected = expected_name[2:-2] if len(expected_name) > 8 else expected_name
    similar = max((SequenceMatcher(None, expected, selected_name[i:i + len(expected)]).ratio()
                   for i in range(max(1, len(selected_name) - len(expected) + 1))), default=0)
    confirmed = similar >= 0.85 if by_order else re.fullmatch(rf"t[ef]ams{number}", selected_name) is not None
    if not expected or not confirmed:
        raise RuntimeError(f"Cannot confirm selected iOS team #{number}; no deployment was changed")


def select_daily_team(number: int) -> bool:
    from module.config import cfg

    select_preset(number, by_order=cfg.select_team_by_order)
    if participant_count()[0] == 0:
        raise RuntimeError("The selected daily preset has no participants; configure its deployment in the game")
    return True


def select_mirror_participants(sinner_order: list[int] | None = None) -> bool:
    """Deploy the already selected Mirror preset; its page has no team list."""
    order = list(range(1, 13)) if sinner_order is None else sinner_order
    selected = [index for index, rank in sorted(enumerate(order), key=lambda pair: pair[1]) if rank > 0]
    ranks = [order[index] for index in selected]
    if len(order) != 12 or not selected or ranks != list(range(1, len(selected) + 1)):
        raise ValueError("Sinner order must have 12 entries with contiguous unique positive ranks")
    auto.take_screenshot()
    if not auto.find_element("teams/identify_assets.png"):
        raise RuntimeError("Cannot recognize iOS formation page")
    current, maximum = participant_count()
    if len(selected) > maximum:
        if sinner_order is not None:
            raise ValueError(f"Configured {len(selected)} participants exceeds capacity {maximum}")
        selected = selected[:maximum]
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
    for index in selected:
        auto.mouse_click(440 + (index % 6) * 200, 350 + (index // 6) * 300)
        time.sleep(0.1)
    if participant_count() != (len(selected), maximum):
        raise RuntimeError(f"iOS selection was not confirmed as {len(selected)}/{maximum}")
    return True
