"""Replay current-page purchases against an offline shop with immutable frames."""

from collections import Counter
from dataclasses import dataclass
from itertools import count
from unittest.mock import Mock

import pytest

from module.backends.base import BackendCancelled
from module.config import TeamSetting
from tasks.mirror import in_shop, quick_shop
from tasks.mirror.shop_stock import ShopItem

LEAVE = "mirror/shop/leave_assets.png"
LEAVE_CONFIRM = "mirror/shop/leave_shop_confirm_assets.png"
RETURN = "mirror/shop/return_assets.png"
PURCHASE_POSITION = (2100, 1100)
ACQUIRED_POSITION = (1900, 1200)
COIN_POSITION = (800, 200)


@dataclass(frozen=True)
class Gift:
    name: str
    price: int
    behavior: str = "buy"


@dataclass(frozen=True)
class ShopFrame:
    sequence: int
    screen: str
    money: int
    entries: tuple[tuple[Gift, ShopItem], ...]


class SimulatedShop:
    """Clicks change the next frame; the current screenshot never changes."""

    def __init__(self, gifts, money, kind="normal", delay=2):
        self.stock = list(gifts)
        self.money, self.kind, self.delay = money, kind, delay
        self.screen = "grid"
        self.screenshot = None
        self.selected = None
        self.waiting_frames = 0
        self.captures = self.capture_failures = 0
        self.reported_money = None
        self.events, self.click_attempts, self.money_reads = [], [], []
        self.stock_reads, self.frames, self.input_frames, self.money_read_frames = [], [], [], []
        self.acquisition_stuck = False
        self.model = "normal"

    def take_screenshot(self):
        self.captures += 1
        assert self.captures <= 150, "The shop replay exceeded its finite operation budget"
        if self.capture_failures:
            self.capture_failures -= 1
            return None
        if self.screen == "waiting":
            if self.waiting_frames:
                self.waiting_frames -= 1
            else:
                self.stock.remove(self.selected)
                self.screen = "acquired"
        # A normal shop has one service slot; a special shop has three.
        start = 1 if self.kind == "normal" else 3
        entries = tuple(
            (gift, ShopItem(slot // 4, slot % 4, gift.price, (900 + slot % 4 * 300, 450 + slot // 4 * 300)))
            for slot, gift in enumerate(self.stock, start)
        )
        self.screenshot = ShopFrame(self.captures, self.screen, self.money, entries)
        self.frames.append(self.screenshot)
        return self.screenshot

    def find_element(self, path, **kwargs):
        screen = self.screenshot.screen
        if path == quick_shop.COINS and screen in {"grid", "purchase", "waiting"}:
            return COIN_POSITION
        if path == quick_shop.PURCHASE and screen in {"purchase", "waiting"}:
            return PURCHASE_POSITION
        if path == quick_shop.ACQUIRED and screen in {"acquired", "service"}:
            return ACQUIRED_POSITION
        if path == quick_shop.MAP and screen == "map":
            return (200, 200)
        return None

    def click_element(self, path, **kwargs):
        screen = self.screenshot.screen
        self.click_attempts.append((screen, path))
        if path == quick_shop.ACQUIRED and screen == "acquired":
            self.events.append(("acquired", self.selected.name))
            self.selected, self.screen = None, "grid"
            return True
        if path == LEAVE_CONFIRM and screen == "leave_confirm":
            self.events.append(("leave_confirm",))
            self.screen = "map"
            return True
        if path == LEAVE and screen == "grid":
            self.events.append(("leave",))
            self.screen = "leave_confirm"
            return True
        return False

    def mouse_action_with_pos(self, point, *, offset):
        assert offset is False
        frame = self.screenshot
        assert frame.screen == self.screen, "An input used a screenshot from before the last screen transition"
        assert frame.sequence not in [sequence for sequence, _, _ in self.input_frames], "Two inputs used the same stale frame"
        self.input_frames.append((frame.sequence, frame.screen, point))
        if frame.screen == "acquired":
            assert point == ACQUIRED_POSITION
            if self.acquisition_stuck:
                self.events.append(("acquired_stuck", self.selected.name))
                return
            self.events.append(("acquired", self.selected.name))
            self.selected, self.screen = None, "grid"
            return
        if frame.screen == "grid":
            gift = next(gift for gift, item in frame.entries if item.position == point)
            self.events.append(("select", gift.name, point))
            if gift.behavior != "miss_touch":
                self.selected = gift
                self.screen = "service" if gift.behavior == "generic_checkmark" else "purchase"
            return
        assert point == PURCHASE_POSITION and frame.screen in {"purchase", "waiting"}
        self.events.append(("purchase", self.selected.name))
        if self.selected.behavior in {"disabled", "miss_confirm"}:
            return
        # The balance can update while the purchase dialog is still visible.
        # Inventory remains behind that dialog until the acquisition arrives.
        if self.screen != "waiting":
            self.money -= self.selected.price
            assert self.money >= 0
            self.screen, self.waiting_frames = "waiting", self.delay

    def mouse_click_blank(self, **kwargs):
        self.events.append(("blank", self.screen))
        if self.screen in {"purchase", "service"}:
            self.selected, self.screen = None, "grid"

    def read_money(self):
        self.money_reads.append(self.screenshot.screen)
        self.money_read_frames.append(self.screenshot)
        return self.screenshot.money if self.reported_money is None else self.reported_money

    def read_stock(self, frame, coins):
        assert frame is self.screenshot and coins == COIN_POSITION
        assert frame.screen == "grid", "A modal's dimmed background is not a fresh shop grid"
        self.stock_reads.append(frame)
        return [item for _, item in frame.entries]

    def event_names(self, kind):
        return [event[1] for event in self.events if event[0] == kind]


@pytest.fixture
def replay(monkeypatch):
    def create(gifts, money=1000, kind="normal", **settings):
        ui = SimulatedShop(gifts, money, kind)
        values = {"shopping_strategy": True, "shopping_strategy_select": 6} | settings
        shop = in_shop.Shop(TeamSetting(**values))
        shop._get_cost = Mock(side_effect=ui.read_money)
        monkeypatch.setattr(quick_shop, "auto", ui)
        monkeypatch.setattr(in_shop, "auto", ui)
        monkeypatch.setattr(quick_shop, "current_page_items", Mock(side_effect=ui.read_stock))
        monkeypatch.setattr(quick_shop, "retry", Mock(return_value=True))
        monkeypatch.setattr(in_shop, "retry", Mock(return_value=True))
        monkeypatch.setattr(quick_shop, "log", Mock())
        monkeypatch.setattr(in_shop, "log", Mock())
        monkeypatch.setattr(in_shop, "sleep", lambda _: None)
        monkeypatch.setattr(in_shop, "back_init_menu", Mock(side_effect=AssertionError("Unexpected recovery")))
        monkeypatch.setattr(quick_shop.ImageUtils, "load_image", Mock(return_value=None))
        clock = count(step=0.1)
        monkeypatch.setattr(quick_shop, "monotonic", lambda: next(clock))
        return shop, ui

    return create


@pytest.mark.parametrize("kind,length", [("normal", 4), ("normal", 5), ("special", 3), ("special", 5)])
def test_buys_current_page_to_empty_with_fresh_positions_after_each_purchase(replay, kind, length):
    gifts = [Gift(f"gift-{i}", 10 + i) for i in range(length)]
    shop, ui = replay(gifts, kind=kind)
    quick_shop.buy_current_page(shop)
    assert ui.stock == []
    assert ui.money == 1000 - sum(gift.price for gift in gifts)
    assert ui.event_names("select") == ui.event_names("purchase") == ui.event_names("acquired") == [gift.name for gift in gifts]
    # Every removal shifts the next gift into the first available shop slot.
    positions = [event[2] for event in ui.events if event[0] == "select"]
    assert len(set(positions)) == 1
    assert len({frame.sequence for frame in ui.stock_reads}) == len(ui.stock_reads)


def test_skips_expensive_items_and_still_buys_later_affordable_gifts(replay):
    gifts = [Gift("expensive", 200), Gift("affordable", 30), Gift("too-much-now", 60), Gift("last-cheap", 10)]
    shop, ui = replay(gifts, money=50)
    quick_shop.buy_current_page(shop)
    assert ui.event_names("purchase") == ["affordable", "last-cheap"]
    assert [gift.name for gift in ui.stock] == ["expensive", "too-much-now"]
    assert ui.money == 10


def test_zero_balance_still_allows_free_gifts_and_waits_for_acquisition(replay):
    shop, ui = replay([Gift("paid", 1), Gift("free-1", 0), Gift("free-2", 0)], money=0)
    quick_shop.buy_current_page(shop)
    assert ui.event_names("purchase") == ui.event_names("acquired") == ["free-1", "free-2"]
    assert ui.stock == [Gift("paid", 1)]
    assert ui.money == 0


def test_purchase_confirmation_is_sent_once_while_balance_is_visible_behind_dialog(replay):
    shop, ui = replay([Gift("first", 30), Gift("second", 20)], money=100)
    quick_shop.buy_current_page(shop)
    assert Counter(ui.event_names("purchase")) == {"first": 1, "second": 1}
    assert ui.event_names("acquired") == ["first", "second"]
    assert set(ui.money_reads) == {"grid"}
    assert ui.money == 50


@pytest.mark.parametrize("delay", [4, 5, 8])
def test_delayed_settlement_keeps_each_same_price_gift_pending_until_acquired(replay, delay):
    shop, ui = replay([Gift("first", 20), Gift("second", 20)], money=100)
    ui.delay = delay
    quick_shop.buy_current_page(shop)
    assert ui.stock == []
    assert ui.money == 60
    assert ui.event_names("select") == ui.event_names("acquired") == ["first", "second"]
    assert Counter(ui.event_names("purchase")) == {"first": 1, "second": 1}
    assert all(frame.screen == "grid" for frame in ui.stock_reads)
    assert set(ui.money_reads) == {"grid"}


def test_very_delayed_settlement_exits_without_rescanning_dialog_background_or_another_purchase(replay):
    shop, ui = replay([Gift("first", 20), Gift("second", 20)], money=100)
    ui.delay = 40
    quick_shop.buy_current_page(shop)
    assert ui.event_names("select") == ui.event_names("purchase") == ["first"]
    assert ui.event_names("acquired") == []
    assert ui.screen == "waiting"
    assert ui.money == 80
    assert len(ui.stock_reads) == 1
    assert set(ui.money_reads) == {"grid"}
    assert not any(event[0] == "blank" for event in ui.events)
    assert ui.captures <= 20


def test_return_to_grid_frame_can_read_money_and_next_gift_before_one_fresh_input(replay):
    shop, ui = replay([Gift("first", 20), Gift("second", 30)], money=100)
    quick_shop.buy_current_page(shop)
    returned_frames = [
        frame for previous, frame in zip(ui.frames, ui.frames[1:])
        if previous.screen == "acquired" and frame.screen == "grid"
    ]
    next_selection_frame = [sequence for sequence, screen, _ in ui.input_frames if screen == "grid"][1]
    assert returned_frames[0].sequence == next_selection_frame
    assert returned_frames[0] in ui.stock_reads
    assert returned_frames[0] in ui.money_read_frames
    assert len({sequence for sequence, _, _ in ui.input_frames}) == len(ui.input_frames)


def test_stuck_acquisition_confirmation_is_bounded_and_hands_back_to_original_exit(replay, monkeypatch):
    shop, ui = replay([Gift("gift", 10)])
    ui.acquisition_stuck = True
    blank = ui.mouse_click_blank

    def original_exit_cleanup(**kwargs):
        blank(**kwargs)
        if ui.screen == "acquired":
            # Only the original post-shopping cleanup owns this three-tap action.
            assert kwargs == {"times": 3}
            ui.screen, ui.selected = "grid", None

    monkeypatch.setattr(ui, "mouse_click_blank", original_exit_cleanup)
    shop.in_shop(1)
    assert 1 <= len(ui.event_names("acquired_stuck")) <= 4
    assert ui.event_names("purchase") == ["gift"]
    assert [event for event in ui.events if event[0].startswith("leave")] == [("leave",), ("leave_confirm",)]
    assert ui.screen == "map"


def test_missed_selection_is_abandoned_before_checking_other_gifts(replay):
    behavior = "miss_touch"
    shop, ui = replay([Gift("unavailable", 20, behavior), Gift("available", 30)], money=100)
    quick_shop.buy_current_page(shop)
    assert ui.event_names("acquired") == ["available"]
    assert ui.stock == [Gift("unavailable", 20, behavior)]
    assert ui.money == 70
    assert ui.event_names("select").count("unavailable") <= 2
    assert ui.captures < 30
    assert ("blank", "grid") in ui.events


@pytest.mark.parametrize("behavior", ["miss_confirm", "disabled"])
def test_submitted_but_unconfirmed_purchase_exits_without_selecting_other_gifts(replay, behavior):
    gifts = [Gift("unconfirmed", 20, behavior), Gift("available", 30)]
    shop, ui = replay(gifts, money=100)
    quick_shop.buy_current_page(shop)
    assert ui.event_names("select") == ui.event_names("purchase") == ["unconfirmed"]
    assert ui.event_names("acquired") == []
    assert ui.stock == gifts
    assert ui.money == 100
    assert ui.screen == "purchase"
    assert len(ui.stock_reads) == 1
    assert set(ui.money_reads) == {"grid"}
    assert not any(event[0] == "blank" for event in ui.events)
    assert ui.captures <= 20


def test_selected_service_generic_checkmark_is_never_treated_as_gift_acquisition(replay):
    shop, ui = replay([Gift("service", 20, "generic_checkmark"), Gift("gift", 30)], money=100)
    quick_shop.buy_current_page(shop)
    assert ui.event_names("purchase") == ui.event_names("acquired") == ["gift"]
    assert ui.stock == [Gift("service", 20, "generic_checkmark")]
    assert ui.money == 70
    assert ("blank", "service") in ui.events
    assert not any(screen == "service" for _, screen, _ in ui.input_frames)
    assert not any(path == quick_shop.ACQUIRED for _, path in ui.click_attempts)


def test_unreadable_money_is_not_zero_and_does_not_trigger_blind_or_free_purchase(replay):
    shop, ui = replay([Gift("free", 0), Gift("paid", 10)])
    ui.reported_money = -1
    quick_shop.buy_current_page(shop)
    assert ui.event_names("select") == ui.event_names("purchase") == []
    assert ui.stock_reads == []
    assert 1 <= ui.captures <= 5


def test_server_retry_failure_raises_the_original_shop_restart_exception(replay, monkeypatch):
    shop, ui = replay([Gift("gift", 10)])
    monkeypatch.setattr(quick_shop, "retry", Mock(return_value=False))
    with pytest.raises(shop.RestartGame):
        quick_shop.buy_current_page(shop)
    assert ui.event_names("select") == []
    quick_shop.retry.assert_called_once_with(reuse_screenshot=True)


@pytest.mark.parametrize("cancellation_point", ["capture", "retry", "touch"])
def test_backend_cancellation_propagates_through_the_shop_entry(replay, monkeypatch, cancellation_point):
    shop, ui = replay([Gift("gift", 10)])
    cancel = Mock(side_effect=BackendCancelled)
    if cancellation_point == "capture":
        monkeypatch.setattr(ui, "take_screenshot", cancel)
    elif cancellation_point == "retry":
        monkeypatch.setattr(quick_shop, "retry", cancel)
    else:
        monkeypatch.setattr(ui, "mouse_action_with_pos", cancel)
    with pytest.raises(BackendCancelled):
        shop.in_shop(1)
    cancel.assert_called_once()
    assert not any(event[0].startswith("leave") for event in ui.events)


def test_persistent_screenshot_failure_returns_after_a_finite_number_of_attempts(replay):
    shop, ui = replay([Gift("gift", 10)])
    ui.capture_failures = 100
    quick_shop.buy_current_page(shop)
    assert 1 <= ui.captures <= 8
    assert ui.events == []
    quick_shop.retry.assert_not_called()


@pytest.mark.parametrize("kind", ["normal", "special"])
def test_fast_mode_overrides_other_shop_actions_and_reuses_leave_confirmation_loop(replay, kind):
    shop, ui = replay(
        [Gift("gift", 10)], kind=kind, ignore_shop=[True] * 5,
        do_not_buy=True, do_not_heal=False, do_not_sell=False, do_not_fuse=False,
        do_not_enhance=False, skill_replacement=True, shop_strategy=2,
    )
    for name in ("heal_sinner", "sell_gifts", "buy_gifts", "fuse_gift", "enhance_gifts", "replacement_skill"):
        setattr(shop, name, Mock(side_effect=AssertionError(f"Unexpected service: {name}")))
    shop.in_shop(1)
    assert ui.event_names("acquired") == ["gift"]
    assert [event for event in ui.events if event[0].startswith("leave")] == [("leave",), ("leave_confirm",)]
    assert ui.screen == "map"
    assert set(path for _, path in ui.click_attempts) <= {quick_shop.ACQUIRED, RETURN, LEAVE_CONFIRM, LEAVE}
    assert all(call.kwargs == {"reuse_screenshot": True} for call in quick_shop.retry.call_args_list)
    assert all(call.args == () and call.kwargs == {} for call in in_shop.retry.call_args_list)


@pytest.mark.parametrize("enabled,mode", [(True, mode) for mode in range(6)] + [(False, 6)])
def test_existing_modes_and_disabled_custom_strategy_do_not_enter_quick_buy(replay, monkeypatch, enabled, mode):
    shop, ui = replay([], shopping_strategy=enabled, shopping_strategy_select=mode, ignore_shop=[True] * 5)
    helper = Mock(side_effect=AssertionError("Legacy mode entered quick buy"))
    monkeypatch.setattr(quick_shop, "buy_current_page", helper)
    shop.in_shop(1)
    helper.assert_not_called()
    assert [event for event in ui.events if event[0].startswith("leave")] == [("leave",), ("leave_confirm",)]
    assert ui.screen == "map"
