"""Normal English iOS Mirror preparation using the recorded 1.116.2 pages."""

from __future__ import annotations

import time

ENTRY = "mirror/entry/"
ACTIVE_PAGES = (
    "mirror/road_in_mir/legend_assets.png", "mirror/theme_pack/feature_theme_pack_assets.png",
    "teams/identify_assets.png", "battle/gear_right.png", "battle/pause_assets.png", "battle/victory.png",
    "mirror/shop/shop_coins_assets.png", "event/skip_assets.png",
    "mirror/road_in_mir/select_encounter_reward_card_assets.png",
    "mirror/claim_reward/complete_mirror_100%_assets.png",
    "mirror/claim_reward/reward_preview_assets.png", "mirror/claim_reward/reward_confirm_prompt_assets.png",
    "mirror/claim_reward/pass_level_up_assets.png", "mirror/claim_reward/rewards_acquired_assets.png",
)


def wait_page(automation, paths: tuple[str, ...], timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        automation.take_screenshot()
        if any(automation.find_element(path) for path in paths):
            return
    raise RuntimeError(f"iOS Mirror page transition unconfirmed: {paths}")


def click_to_page(automation, target: str, paths: tuple[str, ...]) -> None:
    if not automation.click_element(target, offset=False):
        raise RuntimeError(f"Cannot recognize iOS Mirror action: {target}")
    wait_page(automation, paths)


def prepare_normal_mirror(automation, team_number: int) -> None:
    if team_number != 1:
        raise NotImplementedError("The calibrated iOS Mirror preset is team #1")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        automation.take_screenshot()
        if automation.find_element(ENTRY + "grace_prompt_assets.png"):
            if automation.find_element(ENTRY + "convert_checked_assets.png"):
                automation.click_element(ENTRY + "convert_checked_assets.png", offset=False)
                time.sleep(0.3)
                automation.take_screenshot()
                if automation.find_element(ENTRY + "convert_checked_assets.png"):
                    raise RuntimeError("Convert Starlight checkbox did not change")
            click_to_page(automation, ENTRY + "grace_confirm_assets.png", (ENTRY + "gift_page_assets.png",))
        elif automation.find_element(ENTRY + "entry_prompt_assets.png"):
            click_to_page(automation, ENTRY + "entry_confirm_assets.png", (ENTRY + "preset_assets.png",))
        elif automation.find_element(ENTRY + "preset_assets.png"):
            # This preset list differs from the twelve-participant battle page.
            for _ in range(10):
                automation.mouse_swipe_for_team_scroll(195, 480, dy=300, duration=0.2)
            automation.take_screenshot()
            automation.mouse_click(195, 470)
            time.sleep(0.3)
            automation.take_screenshot()
            click_to_page(automation, ENTRY + "preset_confirm_assets.png", (ENTRY + "grace_assets.png",))
        elif automation.find_element(ENTRY + "grace_assets.png"):
            click_to_page(automation, ENTRY + "grace_enter_assets.png", (ENTRY + "grace_prompt_assets.png",))
        elif automation.find_element(ENTRY + "gift_page_assets.png"):
            if automation.find_element(ENTRY + "search_on_assets.png"):
                automation.click_element(ENTRY + "search_on_assets.png", offset=False)
                time.sleep(0.3)
                automation.take_screenshot()
            if not automation.find_element(ENTRY + "gift_select_assets.png"):
                if not automation.click_element(ENTRY + "bleed_assets.png", offset=False):
                    raise RuntimeError("Cannot recognize initial Bleed gift category")
                wait_page(automation, (ENTRY + "wound_clerid_assets.png",))
                click_to_page(automation, ENTRY + "wound_clerid_assets.png", (ENTRY + "gift_select_assets.png",))
            click_to_page(automation, ENTRY + "gift_select_assets.png", (
                "mirror/theme_pack/feature_theme_pack_assets.png",
                "mirror/road_in_mir/ego_gift_get_confirm_assets.png",
            ))
        elif any(automation.find_element(path) for path in ACTIVE_PAGES):
            return
        elif automation.find_element("mirror/road_in_mir/ego_gift_get_confirm_assets.png"):
            click_to_page(automation, "mirror/road_in_mir/ego_gift_get_confirm_assets.png", ACTIVE_PAGES)
        elif automation.find_element("mirror/road_to_mir/resume_assets.png"):
            click_to_page(automation, "mirror/road_to_mir/resume_assets.png", ACTIVE_PAGES)
        elif automation.find_element(ENTRY + "landing_enter_assets.png"):
            click_to_page(automation, ENTRY + "landing_enter_assets.png", (
                ENTRY + "entry_prompt_assets.png", "mirror/road_to_mir/resume_assets.png",
            ))
        elif automation.find_element("home/mirror_dungeons_assets.png"):
            click_to_page(automation, "home/mirror_dungeons_assets.png", (ENTRY + "landing_enter_assets.png",))
        elif automation.find_element("home/mail_assets.png") and automation.find_element("home/drive_assets.png"):
            click_to_page(automation, "home/drive_assets.png", ("home/mirror_dungeons_assets.png",))
        else:
            time.sleep(0.3)
    raise RuntimeError("Unrecognized iOS Mirror preparation page")
