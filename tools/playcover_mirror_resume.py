"""Explicit, zero-module diagnostics for an already entered normal Mirror Dungeon."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-current", action="store_true", help="Enable touch input in the current dungeon only")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--output", default="artifacts/mirror-validation")
    args = parser.parse_args()
    from utils.runtime_paths import SOURCE_ROOT

    output = (SOURCE_ROOT / args.output).resolve()
    if not output.is_relative_to(SOURCE_ROOT.parent) or args.timeout <= 0:
        parser.error("Output must stay in the workspace and timeout must be positive")
    output.mkdir(parents=True, exist_ok=True)
    from module.backends.factory import get_playcover_session
    from module.config import cfg
    from utils.path_manager import path_manager

    if cfg.backend != "playcover":
        parser.error("Select the PlayCover backend first")
    path_manager.initialize_paths()
    session = get_playcover_session()
    session.capture().image.save(output / "before.png")
    result = {"bundle_id": session.transport.bundle_id, "module_rewards": False, "new_entry": False,
              "active": args.resume_current, "status": "read_only"}
    if not args.resume_current:
        session.disconnect()
        sys.stdout.write(json.dumps(result) + "\n")
        return 0
    from module.automation import auto
    from module.logger import log
    from module.my_error.my_error import userStopError
    from module.system_actions import apply_power_keep_awake
    from tasks.mirror.mirror import Mirror

    auto.take_screenshot()
    pages = ("mirror/road_in_mir/legend_assets.png", "teams/identify_assets.png", "battle/in_mirror_assets.png",
             "mirror/theme_pack/feature_theme_pack_assets.png", "mirror/shop/shop_coins_assets.png",
             "mirror/road_in_mir/select_encounter_reward_card_assets.png", "event/skip_assets.png")
    battle_ready = auto.find_element("battle/gear_right.png") and auto.find_element("battle/win_rate_card.png")
    if not battle_ready and not any(auto.find_element(path) for path in pages):
        session.disconnect()
        parser.error("Enter a normal Mirror Dungeon manually before resuming; this tool never starts one")
    cfg.config = cfg.config.model_copy(update={"hard_mirror": False, "floor_3_exit": False,
                                              "skip_enkephalin": True, "fight_to_last_man": True})
    team = cfg.config.teams["1"].model_copy(update={"team_number": 1, "normal_to_hard_floor": 0,
                                                  "use_starlight": False, "opening_bonus": [0] * 10})
    dungeon = Mirror(team, 1, allow_module_rewards=False)
    # Current Mirror preset was selected at entry; deploy it only if necessary.
    from tasks.teams.playcover import participant_count

    dungeon.first_battle = bool(auto.find_element("teams/identify_assets.png") and participant_count()[0] == 0)
    finished = threading.Event()

    def watchdog() -> None:
        started = time.monotonic()
        while not finished.wait(15):
            elapsed = time.monotonic() - started
            sys.stdout.write(f"Mirror floor={dungeon.floor} elapsed={elapsed:.0f}s; module rewards disabled\n")
            sys.stdout.flush()
            if elapsed >= args.timeout:
                session.cancel.set()
                return

    watcher = threading.Thread(target=watchdog, name="mirror-validation-watchdog", daemon=True)
    handler = logging.FileHandler(output / "events.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.setLevel(logging.DEBUG)
    log.addHandler(handler)
    watcher.start()
    try:
        apply_power_keep_awake(True)
        dungeon.run()
        result["status"] = "returned"
    except (RuntimeError, NotImplementedError, OSError) as exc:
        result.update(status="stopped", reason=str(exc))
    except (KeyboardInterrupt, userStopError):
        result.update(status="cancelled", reason="Stopped by the user or diagnostic timeout")
    finally:
        finished.set()
        watcher.join(timeout=1)
        try:
            if session.transport.connected:
                session.input.release_contacts()
            if not session.cancel.is_set():
                session.capture().image.save(output / "after.png")
        except OSError as exc:
            result["final_capture_error"] = str(exc)
        finally:
            result.update(floor=dungeon.floor, events=dungeon.event_times)
            session.disconnect()
            apply_power_keep_awake(False)
            log.removeHandler(handler)
            handler.close()
            (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["status"] == "returned" else 2


if __name__ == "__main__":
    raise SystemExit(main())
