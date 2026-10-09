"""Page-confirmed semantic actions; iOS never translates PC keys to fixed taps."""

from __future__ import annotations

import time

from module.backends.base import BackendCapabilities


class GameActions:
    def __init__(self, automation, capabilities: BackendCapabilities):
        self.auto = automation
        self.capabilities = capabilities

    def select_win_rate(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("p")
            return True
        self.auto.take_screenshot()
        if not self.auto.click_element("battle/win_rate_card.png", offset=False):
            raise RuntimeError("Cannot recognize iOS Win Rate button; record this page for calibration")
        return True

    def enter_battle(self) -> bool:
        """Send the resource-consuming entry once, then only observe the page."""
        self.auto.take_screenshot()
        target = next((path for path in ("battle/chaim_to_battle_assets.png", "battle/normal_to_battle_assets.png")
                       if self.auto.find_element(path)), None)
        if target is None or not self.auto.click_element(target, offset=False):
            raise RuntimeError("Cannot recognize an enabled To Battle button")
        for _ in range(100):
            self.auto.take_screenshot()
            if any(self.auto.find_element(path) for path in ("battle/gear_right.png", "battle/pause_assets.png")):
                return True
            time.sleep(0.3)
        raise RuntimeError("Battle entry was sent once; transition unconfirmed. Inspect the game before another run")

    def start_turn(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("enter")
            return True
        self.auto.take_screenshot()
        target = "battle/gear_start.png" if self.auto.find_element("battle/gear_start.png") else "battle/gear_right.png"
        if not self.auto.click_element(target, offset=False):
            raise RuntimeError("Cannot recognize iOS Start Turn button")
        for _ in range(10):
            self.auto.take_screenshot()
            if self.auto.find_element("battle/pause_assets.png"):
                return True
            time.sleep(0.2)
        raise RuntimeError("Start Turn touch was sent, but battle transition was not confirmed")

    def back(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("esc")
            return True
        self.auto.take_screenshot()
        target = "home/back_assets.png" if self.auto.find_element("home/back_assets.png") else "home/back_ios.png"
        if not self.auto.click_element(target, offset=False):
            raise RuntimeError("Cannot recognize an iOS Back button on this page")
        self.auto.take_screenshot()
        return True

    def zoom_map(self, zoom_out: bool = True) -> None:
        if not self.capabilities.zoom:
            raise NotImplementedError("This backend has no verified map zoom")
        self.auto.take_screenshot()
        if not self.auto.find_element("mirror/road_in_mir/legend_assets.png"):
            raise RuntimeError("Map zoom requires a recognized Mirror Dungeon map")
        distances = (600, 300) if zoom_out else (300, 600)
        self.auto.mouse_pinch((960, 540), *distances, duration=0.5)
        self.auto.take_screenshot()

    def return_home(self) -> bool:
        for _ in range(30):
            self.auto.take_screenshot()
            if self.auto.find_element("battle/victory.png") and self.auto.find_element("battle/battle_finish_confirm_assets.png"):
                self.auto.click_element("battle/battle_finish_confirm_assets.png", offset=False)
                time.sleep(0.5)
            elif self.auto.find_element("home/window_assets.png"):
                self.auto.click_element("home/window_assets.png", offset=False)
                time.sleep(0.3)
                self.auto.take_screenshot()
                if self.auto.find_element("home/mail_assets.png", model="normal"):
                    return True
            elif self.auto.find_element("home/back_assets.png"):
                self.back()
                time.sleep(0.3)
            else:
                time.sleep(0.3)
        raise RuntimeError("Cannot confirm iOS home; no automatic restart or blind tap was attempted")

    def enter_exp_menu(self) -> None:
        tutorial_exits = 0
        for _ in range(30):
            self.auto.take_screenshot()
            if self.auto.find_element("teams/reset_deployment.png"):
                if not self.auto.click_element("teams/clear_selection_confirm_assets.png", offset=False):
                    raise RuntimeError("Cannot confirm iOS Reset Deployment dialog")
            elif self.auto.find_element("teams/tutorial_heading.png"):
                tutorial_exits += 1
                if tutorial_exits > 1:
                    raise RuntimeError("Repeated iOS team tutorial; close it manually before continuing")
                self.back()
            elif self.auto.find_element("teams/identify_assets.png") and self.auto.find_element("battle/chaim_to_battle_assets.png"):
                return
            elif self.auto.find_element("luxcavation/exp_enter.png", threshold=0.85):
                levels = self.auto.find_element("luxcavation/exp_enter.png", threshold=0.85,
                                                find_type="image_with_multiple_targets")
                x, y = max(levels, key=lambda point: point[0])
                self.auto.mouse_click(x, y)
            elif self.auto.find_element("home/luxcavation_assets.png"):
                self.auto.click_element("home/luxcavation_assets.png", offset=False)
            elif self.auto.find_element("home/drive_assets.png"):
                self.auto.click_element("home/drive_assets.png", offset=False)
            else:
                raise RuntimeError("Unknown iOS daily navigation page; return to home before starting")
            time.sleep(0.5)
        raise RuntimeError("iOS EXP navigation timed out")


def get_game_actions() -> GameActions:
    from module.automation import auto
    from module.config import cfg

    if cfg.backend == "playcover":
        from module.backends.factory import get_playcover_session

        capabilities = get_playcover_session().capabilities
    else:
        capabilities = BackendCapabilities(native_keys=True, text_input=True)
    return GameActions(auto, capabilities)


def validate_task_capabilities(config) -> None:
    """Fail before game input for workflows not yet validated on iOS."""
    if config.backend != "playcover":
        return
    if config.mirror:
        raise NotImplementedError("Full iOS Mirror automation is still under validation; use the explicit current-dungeon diagnostic")
    if config.daily_task and (config.set_thread_count or config.use_continuous_combat or config.daily_teams != 1 or config.targeted_teaming_EXP):
        raise NotImplementedError("First iOS daily validation requires EXP only, team #1, no continuous combat or targeted teams")
    if config.get_reward:
        raise NotImplementedError("iOS additional mail/pass rewards await separate validation")
    if config.buy_enkephalin or not config.skip_enkephalin:
        raise NotImplementedError("For first PlayCover validation, disable purchases and enable Skip Enkephalin")
    if config.mirror_keyboard_navigation or config.mirror_keyboard_simple_pathfinding:
        raise NotImplementedError("PlayCover does not support keyboard map navigation")
    if config.get_value("after_completion_power_action", "none") != "none" or "exit_emulator" in config.after_completion_actions:
        raise NotImplementedError("macOS completion supports only Exit Game / Exit AALC")
    teams = config.config.teams.values()
    if any(team.use_team_code for team in teams):
        raise NotImplementedError("Disable team-code import: MaaTools v4 has no text-input command")
