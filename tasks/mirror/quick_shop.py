"""Current-page gift purchases; existing shop modes and exit flow stay separate."""

from time import monotonic

from module.automation import auto
from module.logger import log
from tasks.base.retry import retry
from tasks.mirror.shop_stock import current_page_items
from utils.image_utils import ImageUtils

COINS = "mirror/shop/shop_coins_assets.png"
PURCHASE = "mirror/shop/purchase_assets.png"
ACQUIRED = "mirror/road_in_mir/ego_gift_get_confirm_assets.png"
MAP = "mirror/road_in_mir/legend_assets.png"


def _purchase_position():
    point = auto.find_element(PURCHASE)
    if point:
        return point
    # Reuse the original button location, with OCR for the iOS hybrid font.
    template = ImageUtils.load_image(PURCHASE)
    if template is None:
        return None
    left, top, right, bottom = ImageUtils.get_bbox(template)
    scale = auto.screenshot.height / 1440
    region = (max(0, left - 160 * scale), max(0, top - 90 * scale),
              min(auto.screenshot.width, right + 160 * scale),
              min(auto.screenshot.height, bottom + 90 * scale))
    point = auto.find_language_text(["购买", "購買", "購入"], ["purchase", "buy"], my_crop=region)
    return [point[0] + region[0], point[1] + region[1]] if point else None


def buy_current_page(shop):
    """Buy affordable visible gifts without keywords, refresh or other services.

    Each touch is followed by a new screenshot. A purchase is counted only on
    returning to the shop with reduced money or an acknowledged acquisition.
    No fixed waits or predicted post-purchase card positions are needed.
    """
    pending = None
    blocked = set()
    purchased = 0
    unreadable = 0
    empty_frames = 0
    cleanup_frames = 0
    deadline = monotonic() + 180
    log.info("商店速购：只购买当前页饰品，不设置标签或刷新")
    while monotonic() < deadline and purchased < 64:
        if auto.take_screenshot() is None:
            unreadable += 1
            if unreadable >= 5:
                break
            continue
        if retry(reuse_screenshot=True) is False:
            raise shop.RestartGame()
        if auto.find_element(MAP):
            return

        coins = None
        money = None

        if pending is not None:
            pending["frames"] += 1
            if pending["phase"] != "selected" and (point := auto.find_element(ACQUIRED)):
                if pending["phase"] != "returning":
                    pending["frames"] = 0
                elif pending["frames"] >= 4:
                    log.warning("商店速购：获得饰品确认未生效，交回原离店流程")
                    break
                auto.mouse_action_with_pos(point, offset=False)
                pending["acquired"] = True
                pending["phase"] = "returning"
                continue
            if pending["phase"] == "selected":
                if point := _purchase_position():
                    log.debug("商店速购：提交购买确认，商品价格 %s", pending["item"].price)
                    auto.mouse_action_with_pos(point, offset=False)
                    pending["phase"] = "purchased"
                    pending["frames"] = 0
                    continue
            elif pending["phase"] == "purchased" and _purchase_position():
                # The balance remains visible behind a purchase dialog. Do not
                # mistake its dimmed background for a return to the item grid.
                pass
            elif coins := auto.find_element(COINS):
                money = shop._get_cost()
                if money >= 0 and (money < pending["money"] or pending["acquired"]):
                    purchased += 1
                    log.info("商店速购：已购入 %s 件饰品，剩余经费 %s", purchased, money)
                    pending = None
                    blocked.clear()
                    unreadable = empty_frames = 0
            if pending is not None and pending["frames"] >= 4:
                if pending["phase"] != "selected":
                    # Once submitted, the transaction may already be charged.
                    # Keep its receipt pending; never scan the dialog backdrop
                    # or start a second transaction while settlement is unknown.
                    if pending["frames"] >= 12:
                        log.warning("商店速购：购买结算未确认，停止购买并交回原离店流程")
                        break
                    continue
                # A missed selection must not keep the same card in a loop.
                blocked.add((pending["item"].row, pending["item"].column, pending["item"].price))
                log.info("商店速购：本次商品未确认购入，检查当前页其他可购买饰品")
                auto.mouse_click_blank()
                pending = None
                continue
            if pending is not None:
                continue

        if auto.click_element("mirror/shop/return_assets.png"):
            cleanup_frames += 1
            if cleanup_frames >= 4:
                log.warning("商店速购：返回商品页未生效，交回原离店流程")
                break
            continue
        cleanup_frames = 0
        coins = coins or auto.find_element(COINS)
        if not coins:
            unreadable += 1
            if unreadable >= 4:
                log.warning("商店速购：无法确认商品页，交回原离店流程")
                break
            # The original return action closes enhance/sell/skill subpages.
            auto.click_element("mirror/shop/return_assets.png")
            continue
        money = shop._get_cost() if money is None else money
        if money < 0:
            unreadable += 1
            if unreadable >= 3:
                log.warning("商店速购：经费识别失败，停止购买并离店")
                break
            continue
        unreadable = 0
        items = current_page_items(auto.screenshot, coins)
        log.debug("商店速购：当前经费 %s，识别到商品价格 %s", money, [item.price for item in items])
        if not items:
            empty_frames += 1
            if empty_frames >= 2:
                log.info("商店速购：当前页没有可识别的在售饰品，离店")
                break
            continue
        empty_frames = 0
        affordable = [item for item in items if item.price <= money
                      and (item.row, item.column, item.price) not in blocked]
        if not affordable:
            log.info("商店速购：当前页已无可购买饰品，剩余经费 %s，离店", money)
            break
        item = affordable[0]
        log.debug("商店速购：选择第 %s 行第 %s 列饰品，价格 %s", item.row + 1, item.column + 1, item.price)
        pending = {"item": item, "money": money, "phase": "selected", "frames": 0, "acquired": False}
        auto.mouse_action_with_pos(item.position, offset=False)
    else:
        log.warning("商店速购：达到本次操作上限，交回原离店流程")
    log.info("商店速购结束：本次确认购入 %s 件饰品", purchased)
