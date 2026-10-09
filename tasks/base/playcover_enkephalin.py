"""English iOS module conversion and daily-count-based Lunacy refills."""

from __future__ import annotations

import re
from dataclasses import dataclass

from module.ocr import ocr
from tasks.common.ios_pages import click_label, label_point, wait_until

PANEL = "enkephalin/charge_ios_assets.png"


@dataclass(frozen=True)
class RefillState:
    used: int
    limit: int
    cost: int


def read_refill_state(automation) -> RefillState:
    count = ocr.run_line(automation.screenshot.crop((1030, 450, 1220, 520))) or ""
    cost = ocr.run_line(automation.screenshot.crop((875, 405, 970, 478))) or ""
    match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", count)
    if match is None or not cost.strip().isdigit():
        raise RuntimeError("Cannot read iOS Lunacy daily count and price")
    state = RefillState(int(match[1]), int(match[2]), int(cost.strip()))
    if not 0 <= state.used <= state.limit <= 10 or state.cost <= 0:
        raise RuntimeError(f"Invalid iOS Lunacy refill state: {state}")
    return state


def open_panel(automation) -> None:
    automation.take_screenshot()
    if automation.find_element(PANEL):
        return
    if not automation.click_element("home/enkephalin_box_assets.png", offset=False):
        raise RuntimeError("Cannot recognize iOS Enkephalin entry")
    wait_until(automation, lambda: bool(automation.find_element(PANEL)), "Charge Enkephalin")


def select_tab(automation, name: str) -> None:
    if not click_label(automation, name, (640, 308, 1275, 375)):
        raise RuntimeError(f"Cannot recognize iOS Enkephalin {name} tab")
    wait_until(automation, lambda: bool(automation.find_element(PANEL)), name)


def close_panel(automation) -> None:
    if not automation.click_element("enkephalin/enkephalin_cancel_assets.png", offset=False):
        raise RuntimeError("Cannot recognize iOS Enkephalin Cancel")
    wait_until(automation, lambda: not automation.find_element(PANEL), "Enkephalin panel dismissal")


def assemble_modules(automation, *, close: bool = True) -> bool:
    open_panel(automation)
    select_tab(automation, "Modules")
    if not automation.click_element("enkephalin/all_in_assets.png", offset=False):
        raise RuntimeError("Cannot recognize iOS maximum module amount")
    automation.take_screenshot()
    amount = ocr.run_line(automation.screenshot.crop((960, 465, 1105, 530))) or ""
    if not amount.strip().isdigit():
        raise RuntimeError("Cannot read the selected module amount")
    if int(amount.strip()) == 0:
        if close:
            close_panel(automation)
        return False
    if not automation.click_element("enkephalin/enkephalin_confirm_assets.png", offset=False):
        raise RuntimeError("Cannot recognize iOS module conversion Confirm")
    wait_until(automation, lambda: not automation.find_element(PANEL), "module conversion")
    if not close:
        open_panel(automation)
    return True


def refill_lunacy(automation, target_count: int, *, grandet: bool = False) -> int:
    """Match the existing setting: reach today's target count, rather than buy N more."""
    if not 0 <= target_count <= 10:
        raise ValueError("Daily Lunacy target count must be between 0 and 10")
    if target_count == 0:
        return 0
    spent = 0
    open_panel(automation)
    select_tab(automation, "Use Lunacy")
    state = read_refill_state(automation)
    while state.used < min(target_count, state.limit):
        # Convert existing energy before each refill to avoid overflowing the meter.
        assemble_modules(automation, close=False)
        select_tab(automation, "Use Lunacy")
        if grandet:
            def near_full_tick() -> bool:
                text = ocr.run_line(automation.screenshot.crop((1030, 550, 1140, 590))) or ""
                match = re.search(r"(\d{1,2}):(\d{2})", text)
                return bool(match and int(match[1]) >= 5 and int(match[2]) >= 20)

            wait_until(automation, near_full_tick, "Grandet recovery tick", timeout=360)
        state = read_refill_state(automation)
        if state.used >= target_count:
            break
        if not automation.click_element("enkephalin/enkephalin_confirm_assets.png", offset=False):
            raise RuntimeError("Cannot recognize iOS Lunacy refill Confirm")
        # A missing transition never causes the paid action to be replayed.
        def refill_completed() -> bool:
            if not automation.find_element(PANEL):
                open_panel(automation)
                select_tab(automation, "Use Lunacy")
            return bool(label_point(automation, "Daily Count", (990, 400, 1250, 450))) and read_refill_state(automation).used == state.used + 1

        wait_until(automation, refill_completed, "Lunacy daily count increase", timeout=15)
        spent += state.cost
        state = read_refill_state(automation)
    close_panel(automation)
    if spent:
        assemble_modules(automation)
    return spent
