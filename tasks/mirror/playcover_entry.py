"""Normal English iOS Mirror preparation using the recorded 1.116.2 pages."""

from __future__ import annotations

import time

ENTRY = "mirror/entry/"
OBSERVE_PAGES = (
    "mirror/road_to_mir/observe_ego_gift/observe_burn_assets.png",
    "mirror/road_to_mir/observe_ego_gift/observe_bleed_assets.png",
)
ACTIVE_PAGES = (
    "mirror/road_in_mir/legend_assets.png", "mirror/theme_pack/feature_theme_pack_assets.png",
    "teams/identify_assets.png", "battle/gear_right.png", "battle/pause_assets.png", "battle/victory.png",
    "mirror/shop/shop_coins_assets.png", "event/skip_assets.png",
    "mirror/road_in_mir/select_encounter_reward_card_assets.png",
    "mirror/claim_reward/complete_mirror_100%_assets.png",
    "mirror/claim_reward/reward_preview_assets.png", "mirror/claim_reward/reward_confirm_prompt_assets.png",
    "mirror/claim_reward/pass_level_up_assets.png", "mirror/claim_reward/rewards_acquired_assets.png",
) + OBSERVE_PAGES


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


def prepare_normal_mirror(automation, team_number: int, *, team_setting=None, by_order: bool = False) -> None:
    from module.config.config_typing import TeamSetting
    from tasks.mirror.playcover_opening import configure_gifts, configure_graces
    from tasks.teams.playcover import select_preset

    if team_setting is None:
        team_setting = TeamSetting(team_number=team_number, team_system=1, opening_bonus=[0] * 10)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        automation.take_screenshot()
        if automation.find_element(ENTRY + "grace_prompt_assets.png"):
            checked = bool(automation.find_element(ENTRY + "convert_checked_assets.png"))
            if checked != team_setting.use_starlight:
                from tasks.common.ios_pages import click_label

                if not click_label(automation, "Convert Starlight to Cost", (1060, 520, 1440, 580)):
                    raise RuntimeError("Cannot recognize Convert Starlight setting")
                time.sleep(0.3)
                automation.take_screenshot()
                if bool(automation.find_element(ENTRY + "convert_checked_assets.png")) != team_setting.use_starlight:
                    raise RuntimeError("Convert Starlight checkbox did not change")
            click_to_page(automation, ENTRY + "grace_confirm_assets.png", (ENTRY + "gift_page_assets.png",))
        elif automation.find_element(ENTRY + "entry_prompt_assets.png"):
            click_to_page(automation, ENTRY + "entry_confirm_assets.png", (ENTRY + "preset_assets.png",))
        elif automation.find_element(ENTRY + "preset_assets.png"):
            select_preset(team_number, by_order=by_order)
            click_to_page(automation, ENTRY + "preset_confirm_assets.png", (ENTRY + "grace_assets.png",))
        elif automation.find_element(ENTRY + "grace_assets.png"):
            configure_graces(automation, team_setting.opening_bonus)
            click_to_page(automation, ENTRY + "grace_enter_assets.png", (ENTRY + "grace_prompt_assets.png",))
        elif automation.find_element(ENTRY + "gift_page_assets.png"):
            configure_gifts(automation, team_setting)
            wait_page(automation, (
                "mirror/theme_pack/feature_theme_pack_assets.png",
                "mirror/road_in_mir/ego_gift_get_confirm_assets.png",
            ) + OBSERVE_PAGES)
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
