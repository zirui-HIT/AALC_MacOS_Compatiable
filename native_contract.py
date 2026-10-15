"""Presentation metadata shared across the process boundary, without imports of tasks."""

import json

from utils.runtime_paths import resource_path

FIELDS = json.loads(resource_path("assets/config/native_fields.json").read_text())
GROUPS = {
    "daily": ["set_EXP_count", "set_thread_count", "daily_teams", "use_continuous_combat", "use_continuous_combat_select", "targeted_teaming_EXP", "EXP_day_1_2", "EXP_day_3_4", "EXP_day_5_6", "EXP_day_7", "targeted_teaming_thread", *[f"thread_day_{i}" for i in range(1, 8)]],
    "reward": ["set_get_prize"],
    "energy": ["set_lunacy_to_enkephalin", "Dr_Grandet_mode", "skip_enkephalin"],
    "mirror": ["set_mirror_count", "hard_mirror", "no_weekly_bonuses", "floor_3_exit", "infinite_dungeons", "save_rewards", "hard_mirror_single_bonuses", "select_event_pack", "skip_event_pack", "re_claim_rewards", "fight_to_last_man"],
    "playcover": ["game_profile", "playcover_host", "playcover_port", "playcover_app_path", "playcover_bundle_id", "playcover_capture_method"],
    "settings": ["select_team_by_order", "auto_hard_mirror", "last_auto_change", "hard_mirror_chance", "memory_protection", "language_in_program", "theme_mode", "minimize_to_tray", "shutdown_hotkey", "pause_hotkey", "resume_hotkey", "screenshot_interval", "mouse_action_interval", "mouse_down_duration", "experimental_keep_screen_awake", "task_stall_timeout", "check_update", "update_prerelease_enable", "image_resource_sync", "image_resource_source"],
    "completion": ["after_completion_actions", "keep_after_completion"],
}
TASK_KEYS = ["daily_task", "get_reward", "buy_enkephalin", "mirror"]
for suffix in ("", "2", "3", "4"):
    GROUPS["schedule" + suffix] = ["autodaily" + suffix, "autodaily_time" + suffix, "autodaily" + suffix + "_task", "autodaily" + suffix + "_task_exit"]
EDITABLE_CONFIG = set(TASK_KEYS + [key for group in GROUPS.values() for key in group])
EDITABLE_CONFIG.update(["window_position_x", "window_position_y", "default_page"])
HIDDEN_TEAM = {"use_team_code", "team_code", "sinners_be_select", "chosen_sinners", "sinner_order", "total_mirror_time_hard", "mirror_hard_count", "total_mirror_time_normal", "mirror_normal_count"}
STATS = {"total_mirror_time_hard", "mirror_hard_count", "total_mirror_time_normal", "mirror_normal_count"}
OPTIONS = {
    "team_system": FIELDS["options"]["all_systems"],
    "opening_items_system": FIELDS["options"]["all_systems"],
    "second_system_select": FIELDS["options"]["all_systems"],
    "shop_strategy": FIELDS["options"]["shop_strategy"],
    "after_level_IV_select": FIELDS["options"]["after_fuse_level_IV"],
    "reward_cards_select": FIELDS["options"]["reward_cards"],
    "fixed_team_use_select": FIELDS["options"]["fixed_team_use"],
    "shopping_strategy_select": FIELDS["options"]["shopping_strategy"],
    "opening_items_select": FIELDS["options"]["start_gift"],
    "second_system_setting": FIELDS["options"]["second_systems"],
    "skill_replacement_select": FIELDS["options"]["skill_replacement_sinner"],
    "skill_replacement_mode": FIELDS["options"]["skill_replacement_mode"],
    "set_get_prize": FIELDS["options"]["set_get_prize_options"],
    "set_lunacy_to_enkephalin": FIELDS["options"]["set_lunacy_to_enkephalin_options"],
    "game_profile": [["English", "ios_en"], ["中文（日文字库汉化）", "ios_zh_cn"]],
    "language_in_program": [["简体中文", "zh_cn"], ["English", "en"]],
    "theme_mode": [["跟随系统", "AUTO"], ["浅色", "LIGHT"], ["深色", "DARK"]],
    "playcover_capture_method": [["BGR", "bgr"], ["SCRN", "scrn"]],
    "image_resource_source": [["自动", "Auto"], ["GitHub", "GitHub"], ["Gitee", "Gitee"]],
    "hard_mirror": [["关闭", 0], ["本次开启", 1], ["保持开启", 2]],
    "no_weekly_bonuses": [["关闭", 0], ["本次开启", 1], ["保持开启", 2]],
}
RANGES = {"task_stall_timeout": (30, 3600), "playcover_port": (1, 65535), "hard_mirror_chance": (0, 3), "last_auto_change": (0, 9999999999), "defense_for_solo_turns": (1, 5), "max_keyword_refresh": (0, 5), "max_normal_refresh": (0, 5), "normal_to_hard_floor": (0, 5), "use_continuous_combat_select": (1, 10), "screenshot_interval": (0.01, 60), "mouse_action_interval": (0, 60), "mouse_down_duration": (0.01, 60)}
for key in ["team_number", "daily_teams", "EXP_day_1_2", "EXP_day_3_4", "EXP_day_5_6", "EXP_day_7", *[f"thread_day_{i}" for i in range(1, 8)]]:
    RANGES[key] = (1, 40)


def validate_fields(values, *, team=False):
    allowed = set(FIELDS["TeamSetting"]) - STATS if team else EDITABLE_CONFIG
    if not isinstance(values, dict) or not values.keys() <= allowed:
        raise ValueError("Unknown or unavailable setting")
    for key, value in values.items():
        if key in OPTIONS and value not in [item[1] for item in OPTIONS[key]]:
            raise ValueError(f"Invalid choice: {key}")
        if key == "task_stall_timeout" and type(value) is not int:
            raise ValueError("Task stall timeout must be an integer")
        if key in RANGES:
            low, high = RANGES[key]
            if not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f"{key}: {low}–{high}")
        if key in {"set_EXP_count", "set_thread_count", "set_mirror_count"} and (type(value) is not int or value < 0):
            raise ValueError("Task count must be a non-negative integer")
        if key.startswith("autodaily_time"):
            from datetime import datetime

            datetime.strptime(value, "%H:%M")
        lengths = {"chosen_sinners": 12, "sinner_order": 12, "opening_bonus": 10, "ignore_shop": 5, "second_system_action": 4}
        length = lengths.get(key)
        if key.startswith("autodaily") and key.endswith("_task"):
            length = 4
        if key.startswith("autodaily") and key.endswith("_task_exit"):
            length = 7
            if value[2:] != [False] * 5:
                raise ValueError("Only Exit Game / Exit AALC is available on macOS")
        if length is not None and (not isinstance(value, list) or len(value) != length):
            raise ValueError(f"Invalid list length: {key}")
        if key == "opening_bonus" and any(type(item) is not int or item not in range(4) for item in value):
            raise ValueError("Opening bonus must be 0–3")
        if key == "after_completion_actions" and (not isinstance(value, list) or not set(value) <= {"exit_game", "exit_aalc"}):
            raise ValueError("Only Exit Game / Exit AALC is available on macOS")
        if key in {"chosen_sinners", "ignore_shop", "second_system_action"} and any(item not in (0, 1, False, True) for item in value):
            raise ValueError(f"Invalid selection: {key}")
        if key == "observe_ego_gift_selected":
            import re

            systems = {"burn", "bleed", "tremor", "rupture", "poise", "sinking", "charge", "slash", "pierce", "blunt", "general"}
            if not isinstance(value, list) or len(value) > 3:
                raise ValueError("Select at most three observed gifts")
            for item in value:
                match = re.fullmatch(r"([a-z]+)_(\d+)_(\d+)_(\d+)", item)
                if not match or match[1] not in systems or not (1 <= int(match[2]) <= 3 and 1 <= int(match[3]) <= 10 and 1 <= int(match[4]) <= 8):
                    raise ValueError("Invalid observed gift")
    if team and {"chosen_sinners", "sinner_order", "sinners_be_select"} <= values.keys():
        chosen, order = values["chosen_sinners"], values["sinner_order"]
        count = sum(bool(item) for item in chosen)
        if count != values["sinners_be_select"] or sorted(item for item in order if item) != list(range(1, count + 1)) or any(bool(active) != bool(position) for active, position in zip(chosen, order)):
            raise ValueError("Sinner selection count and order must agree")
