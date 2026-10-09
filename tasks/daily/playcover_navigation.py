"""English iOS Luxcavation navigation and verified consecutive-battle counts."""

from __future__ import annotations

import re
import time

from module.ocr import ocr
from tasks.common.ios_pages import TextHit, normalized, text_hits, wait_until


def consecutive_label(automation, box: tuple[int, int, int, int]):
    hit = next((hit for hit in text_hits(automation, box)
                if normalized(hit.text).startswith("consecutivebattle")), None)
    if hit is None and box == (740, 240, 1180, 310):
        text = ocr.run_line(automation.screenshot.crop((848, 258, 1070, 294))) or ""
        if normalized(text).startswith("consecutivebattle"):
            hit = TextHit(text, (950, 276))
    return hit


def set_consecutive_count(automation, count: int, point: tuple[int, int]) -> None:
    if not 1 <= count <= 10:
        raise ValueError("Consecutive battle count must be between 1 and 10")
    x, y = point
    # The label's text is left of the dropdown's center by about 20 logical pixels.
    automation.mouse_click(x, y)
    time.sleep(0.3)
    automation.take_screenshot()
    up = automation.find_element("luxcavation/continuous_combat_up_box.png", threshold=0.85)
    if not up:
        raise RuntimeError("Cannot recognize iOS consecutive-battle increment button")
    cx, cy = up[0] - 115, up[1]

    def current() -> int:
        text = ocr.run_line(automation.screenshot.crop((round(cx - 30), round(cy - 23), round(cx + 30), round(cy + 23)))) or ""
        if not text.strip().isdigit() or not 1 <= int(text.strip()) <= 10:
            raise RuntimeError("Cannot read iOS consecutive-battle count")
        return int(text.strip())

    value = current()
    for _ in range(abs(count - value)):
        automation.mouse_click(up[0] if count > value else up[0] - 230, up[1])
        time.sleep(0.15)
    automation.take_screenshot()
    if current() != count:
        raise RuntimeError(f"Consecutive battle count was not confirmed as {count}")
    automation.mouse_click(x, y)
    wait_until(automation, lambda: not automation.find_element("luxcavation/continuous_combat_up_box.png", threshold=0.85),
               "consecutive-battle settings dismissal")
    text = ocr.run_line(automation.screenshot.crop((round(x - 102), round(y - 18), round(x + 120), round(y + 18)))) or ""
    if not re.search(rf"consecutivebattle[x×]?{count}$", normalized(text)):
        raise RuntimeError(f"Consecutive Battle ×{count} label was not confirmed")


def enter_thread_category(automation) -> None:
    hit = consecutive_label(automation, (375, 300, 1900, 380))
    if hit is None:
        raise RuntimeError("Cannot recognize today's available Thread category")
    # Only the available category has a consecutive-battle selector; locked days don't.
    automation.mouse_click(hit.point[0], 720)
    wait_until(automation, lambda: consecutive_label(automation, (740, 240, 1180, 310)) is not None,
               "Thread Level Select")


def enter_thread_level(automation, count: int) -> None:
    hit = consecutive_label(automation, (740, 240, 1180, 310))
    if hit is None:
        raise RuntimeError("Cannot recognize Thread Level Select")
    set_consecutive_count(automation, count, hit.point)
    automation.mouse_swipe_for_scroll(1000, 730, dy=-500, duration=0.2)
    time.sleep(0.3)
    automation.take_screenshot()
    entries = [hit for hit in text_hits(automation, (1150, 340, 1310, 795)) if normalized(hit.text) == "enter"]
    if not entries:
        raise RuntimeError("Cannot recognize Thread difficulty entries")
    automation.mouse_click(*max(entries, key=lambda hit: hit.point[1]).point)
