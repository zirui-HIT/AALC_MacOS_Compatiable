"""Configuration-driven opening graces and gifts on the English iOS layout."""

from __future__ import annotations

import re
import time

import numpy as np

from module.ocr import ocr
from tasks import all_systems, start_gift
from tasks.common.ios_pages import click_label, wait_until


def grace_origin(index: int) -> tuple[int, int]:
    return round(207 + index % 5 * 297.5), 226 + index // 5 * 359


def read_grace_levels(automation) -> list[int]:
    """White selected outlines are shared by the red and default game themes."""
    image = automation.screenshot.convert("L")
    levels = []
    for index in range(10):
        x, y = grace_origin(index)
        selected = np.asarray(image.crop((x + 3, y + 15, x + 7, y + 280))).mean() > 135
        if not selected:
            levels.append(0)
            continue
        plus = np.asarray(image.crop((x + 20, y + 292, x + 130, y + 295))).mean() > 135
        double = np.asarray(image.crop((x + 144, y + 292, x + 254, y + 295))).mean() > 135
        levels.append(3 if double else 2 if plus else 1)
    return levels


def configure_graces(automation, desired: list[int]) -> None:
    if len(desired) != 10 or any(level not in range(4) for level in desired):
        raise ValueError("Opening graces require 10 levels between 0 and 3")
    # Remove previous selections first, so their preview cost doesn't prevent the new set.
    for index, level in enumerate(read_grace_levels(automation)):
        if level:
            x, y = grace_origin(index)
            automation.mouse_click(x + 140, y + 175)
            wait_until(automation, lambda: read_grace_levels(automation)[index] == 0, f"clear grace {index + 1}")
    for index, level in enumerate(desired):
        if not level:
            continue
        x, y = grace_origin(index)
        automation.mouse_click(x + 140, y + 175)
        wait_until(automation, lambda: read_grace_levels(automation)[index] > 0, f"select grace {index + 1}")
        current = read_grace_levels(automation)[index]
        if current != level:
            button = level if level > 1 else current
            automation.mouse_click(x + (75 if button == 2 else 198), y + 307)
            wait_until(automation, lambda: read_grace_levels(automation)[index] == level,
                       f"grace {index + 1} level {level}")
    if read_grace_levels(automation) != desired:
        raise RuntimeError("Opening graces differ from the saved configuration")


def gift_count(automation) -> tuple[int, int]:
    text = ocr.run_line(automation.screenshot.crop((1635, 850, 1755, 910))) or ""
    match = re.search(r"(\d)\s*/\s*(\d)", text)
    if match is None or not 0 <= int(match[1]) <= int(match[2]) <= 3:
        raise RuntimeError("Cannot read iOS initial gift selection capacity")
    return int(match[1]), int(match[2])


def configure_gifts(automation, team_setting) -> None:
    system = all_systems[team_setting.opening_items_system if team_setting.opening_items else team_setting.team_system]
    order = start_gift[team_setting.opening_items_select] if team_setting.opening_items else [1, 2, 3]
    from utils.image_utils import ImageUtils

    observe = team_setting.observe_ego_gift and bool(team_setting.observe_ego_gift_selected)
    marker = "mirror/entry/search_on_assets.png"
    if bool(automation.find_element(marker)) != observe:
        box = ImageUtils.get_bbox(ImageUtils.load_image(marker))
        automation.mouse_click((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        wait_until(automation, lambda: bool(automation.find_element(marker)) == observe, "Activate Gift Search")
    for _ in range(3):
        if click_label(automation, system, (200, 220, 1100, 910)):
            break
        automation.mouse_swipe_for_scroll(900, 760, dy=-330, duration=0.2)
        time.sleep(0.3)
        automation.take_screenshot()
    else:
        raise RuntimeError(f"Cannot recognize initial {system} gift category")
    time.sleep(0.3)
    automation.take_screenshot()
    current, capacity = gift_count(automation)
    if current:
        raise RuntimeError("Initial gifts already selected; clear them before starting a new configured run")
    for index in order[:capacity]:
        target = f"mirror/road_to_mir/select_init_gift/{system}_ego_gift_{index}.png"
        if not automation.click_element(target, offset=False):
            raise RuntimeError(f"Cannot recognize initial {system} gift {index}")
        current += 1
        wait_until(automation, lambda: gift_count(automation) == (current, capacity), f"initial gift {index}")
    if not click_label(automation, "Select", (1470, 835, 1640, 925)):
        raise RuntimeError("Cannot recognize initial gift Select")
