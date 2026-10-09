"""Free mail and daily/weekly pass rewards on the English iOS interface."""

from __future__ import annotations

import time

from tasks.common.ios_pages import click_label, label_point, normalized, text_hits, wait_until


def claim_mail(automation) -> int:
    if not automation.click_element("home/mail_assets.png", offset=False):
        raise RuntimeError("Cannot recognize the iOS Mailbox entry")
    wait_until(automation, lambda: bool(label_point(automation, "Mailbox", (730, 140, 1180, 230))), "Mailbox")
    text = " ".join(hit.text for hit in text_hits(automation, (300, 290, 1600, 770)))
    claimed = 0
    if "nomailinstorage" not in normalized(text):
        if not click_label(automation, "Claim All", (1300, 780, 1620, 885)):
            raise RuntimeError("Cannot recognize iOS mail Claim All")
        wait_until(automation, lambda: bool(automation.find_element("mail/get_mail_prize_confirm.png"))
                   or bool(label_point(automation, "Confirm", (500, 600, 1500, 950))), "mail rewards")
        if not automation.click_element("mail/get_mail_prize_confirm.png", offset=False):
            if not click_label(automation, "Confirm", (500, 600, 1500, 950)):
                raise RuntimeError("Cannot recognize acquired-mail confirmation")
        wait_until(automation, lambda: bool(label_point(automation, "Mailbox", (730, 140, 1180, 230))), "mail reward dismissal")
        claimed = 1
    if not click_label(automation, "Close", (1020, 780, 1330, 885)):
        raise RuntimeError("Cannot recognize iOS Mailbox Close")
    wait_until(automation, lambda: bool(automation.find_element("home/drive_assets.png")), "home after mail")
    return claimed


def dismiss_pass_popup(automation) -> bool:
    if automation.find_element("mirror/claim_reward/pass_level_up_assets.png"):
        automation.click_element("mirror/claim_reward/pass_level_confirm_assets.png", offset=False)
        return True
    if label_point(automation, "Rewards Acquired", (500, 150, 1400, 450)):
        if not click_label(automation, "Confirm", (500, 650, 1400, 980)):
            raise RuntimeError("Cannot confirm iOS acquired pass rewards")
        return True
    return False


def claim_pass(automation) -> int:
    if not automation.click_element("home/season_assets.png", offset=False):
        raise RuntimeError("Cannot recognize iOS Battle Pass entry")
    wait_until(automation, lambda: bool(automation.find_element("pass/pass_missions_assets.png")), "Battle Pass")
    automation.click_element("pass/pass_missions_assets.png", offset=False)
    wait_until(automation, lambda: bool(automation.find_element("pass/weekly_assets.png")), "Pass Missions")
    claims = 0
    for tab in ("Daily", "Weekly"):
        if not click_label(automation, tab, (350, 270, 465, 735)):
            # Vertical labels can be missed by OCR; use the recorded tab template.
            target = "pass/daily_ios_assets.png" if tab == "Daily" else "pass/weekly_assets.png"
            if not automation.click_element(target, offset=False):
                raise RuntimeError(f"Cannot recognize iOS {tab} pass tab")
        time.sleep(0.5)
        automation.take_screenshot()
        # These are free XP buttons, including harmless disabled/incomplete rows.
        points = automation.find_element("pass/pass_coin.png", find_type="image_with_multiple_targets") or []
        for x, y in sorted(points, key=lambda point: point[1]):
            if not 480 <= x <= 600 or not 270 <= y <= 930:
                continue
            automation.mouse_click(x, y)
            time.sleep(0.4)
            automation.take_screenshot()
            if dismiss_pass_popup(automation):
                claims += 1
                wait_until(automation, lambda: bool(automation.find_element("pass/weekly_assets.png")), "pass reward dismissal")
    return claims
