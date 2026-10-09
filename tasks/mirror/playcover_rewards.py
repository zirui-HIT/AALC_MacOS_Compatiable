"""Recognize and complete the normal iOS Mirror reward pages."""

from __future__ import annotations

import time

from module.ocr import ocr

PREVIEW = "mirror/claim_reward/reward_preview_assets.png"
FIVE_FLOORS = "mirror/claim_reward/completed_five_floors_assets.png"
CLAIM = "mirror/claim_reward/claim_modules_assets.png"
CONFIRM_PROMPT = "mirror/claim_reward/reward_confirm_prompt_assets.png"
FINAL_CONFIRM = "mirror/claim_reward/reward_final_confirm_assets.png"


def read_completed_reward_cost(automation) -> int | None:
    automation.take_screenshot()
    text = ocr.run_line(automation.screenshot.crop((1425, 795, 1485, 847))) or ""
    text = text.strip().removeprefix("-")
    return int(text) if text.isdigit() else None


def click_and_wait(automation, target: str, next_page: str | tuple[str, ...], *, disappears: bool = False) -> None:
    if not automation.click_element(target, offset=False):
        raise RuntimeError(f"Reward action disappeared: {target}")
    for _ in range(30):
        time.sleep(0.2)
        automation.take_screenshot()
        paths = (next_page,) if isinstance(next_page, str) else next_page
        if any(automation.find_element(path) for path in paths) != disappears:
            return
    raise RuntimeError(f"Reward page did not finish transitioning after {target}")


def claim_normal_mirror_rewards(automation) -> bool:
    unknown_since = None
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        automation.take_screenshot()
        if automation.find_element("mirror/claim_reward/pass_level_up_assets.png"):
            click_and_wait(automation, "mirror/claim_reward/pass_level_confirm_assets.png",
                           "mirror/claim_reward/pass_level_up_assets.png", disappears=True)
            unknown_since = None
        elif automation.find_element(CONFIRM_PROMPT) and automation.find_element(FINAL_CONFIRM):
            click_and_wait(automation, FINAL_CONFIRM, ("mirror/claim_reward/pass_level_up_assets.png",
                           "mirror/claim_reward/rewards_acquired_assets.png", "home/mail_assets.png"))
            unknown_since = None
        elif automation.find_element(PREVIEW) and automation.find_element(FIVE_FLOORS):
            click_and_wait(automation, CLAIM, CONFIRM_PROMPT)
            unknown_since = None
        elif automation.find_element("mirror/claim_reward/complete_mirror_100%_assets.png"):
            click_and_wait(automation, "mirror/claim_reward/claim_rewards_assets.png", PREVIEW)
            unknown_since = None
        elif automation.find_element("mirror/claim_reward/rewards_acquired_assets.png"):
            automation.click_element("mirror/claim_reward/rewards_acquired_assets.png", offset=False)
            time.sleep(0.5)
            unknown_since = None
        elif automation.find_element("home/mail_assets.png") and automation.find_element("home/drive_assets.png"):
            return True
        else:
            unknown_since = time.monotonic() if unknown_since is None else unknown_since
            if time.monotonic() - unknown_since > 10:
                raise RuntimeError("Unrecognized iOS post-reward page")
            time.sleep(0.2)
    raise RuntimeError("Timed out completing iOS Mirror rewards")
