"""Page-confirmed semantic actions; iOS never translates PC keys to fixed taps."""

from __future__ import annotations

from module.backends.base import BackendCapabilities


class GameActions:
    def __init__(self, automation, capabilities: BackendCapabilities):
        self.auto = automation
        self.capabilities = capabilities

    def select_win_rate(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("p")
            return True
        self.auto.take_screenshot(max_age=0.85)
        return bool(self.auto.click_element("battle/win_rate_card.png", offset=False))

    def start_turn(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("enter")
            return True
        self.auto.take_screenshot()
        # The START lettering rotates and loses detail in smaller captures;
        # the existing orange gear template identifies the selected state.
        return bool(self.auto.click_element("battle/gear_start.png", offset=False))

    def back(self) -> bool:
        if self.capabilities.native_keys:
            self.auto.key_press("esc")
            return True
        self.auto.take_screenshot()
        target = next((path for path in ("home/back_assets.png", "home/back_ios.png", "mirror/entry/grace_back_assets.png")
                       if self.auto.find_element(path)), "home/back_ios.png")
        if not self.auto.click_element(target, offset=False):
            return False  # Like Esc, an unavailable Back leaves this page unchanged.
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
    """Reject unavailable capabilities, without restricting ordinary configuration choices."""
    if config.backend != "playcover":
        return
    if config.mirror:
        if config.mirror_keyboard_navigation or config.mirror_keyboard_simple_pathfinding:
            raise NotImplementedError("PlayCover does not support keyboard map navigation")
        for index, enabled in enumerate(config.teams_be_select, start=1):
            if not enabled:
                continue
            team = config.config.teams[str(index)]
            if team.use_team_code:
                raise NotImplementedError(f"Mirror team {index}: MaaTools v4 has no team-code text input")
    if config.get_value("after_completion_power_action", "none") != "none" or "exit_emulator" in config.after_completion_actions:
        raise NotImplementedError("macOS completion supports only Exit Game / Exit AALC")
