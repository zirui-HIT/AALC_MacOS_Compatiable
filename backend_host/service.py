"""Process boundary: host existing workers, own config, publish plain data."""

import copy

from backend_host.notifications import mediator
from backend_host.runtime import WorkerThread, events
from module.config import TeamSetting, cfg, theme_list
from module.logger import log
from module.logger.my_log import ui_log_dispatcher
from native_contract import GROUPS, STATS, TASK_KEYS, validate_fields


class BackendService:
    def __init__(self, publish, *, hotkeys=True):
        self.publish = publish
        self.worker = None
        self.kind = None
        self.stopping = False
        self.closing = False
        self.force_close = False
        self.shutdown_complete = False
        self._shutdown_save_failed = False
        self.exit_requested = False
        self.draft_open = False
        self.pending = []
        self.scheduled = None
        self.auxiliary = None
        self.resource_payload = None
        self.hotkey_token = None
        self.background = set()
        self.update_check = None
        self.startup_pending = False
        self.startup_args = []
        self.pending_apply = False
        self.awaiting_resource_choice = False
        self._connections = []
        if not cfg.language_in_program:
            cfg.set_value("language_in_program", "zh_cn")
        for key in ("hard_mirror", "no_weekly_bonuses"):
            if cfg.get_value(key) < 2:
                cfg.set_value(key, False)
        if cfg.backend == "playcover":
            actions = [value for value in cfg.after_completion_actions if value != "exit_emulator"]
            if actions != cfg.after_completion_actions:
                cfg.set_value("after_completion_actions", actions)
            if cfg.after_completion_power_action != "none":
                cfg.set_value("after_completion_power_action", "none")
        if not cfg.keep_after_completion:
            cfg.unsaved_set_value("after_completion_actions", [])
            cfg.unsaved_set_value("after_completion_power_action", "none")
        # Removed UI capability: PlayCover v4 cannot enter formation codes.
        # Clear its obsolete preference at the migration boundary; the original
        # capability check and all formation/party execution code stay intact.
        for team in cfg.config.teams.values():
            self._adapt_team_flags(team)
            if team.use_team_code:
                cfg.set_value("use_team_code", False, config_obj=team)
                log.info("已移除 PlayCover 不支持的编队码开关，保留现有角色编队设置")
        self._connect(mediator.link_start, self.stop)
        self._connect(mediator.pause_resume, self.pause)
        self._connect(mediator.kill_signal, self._request_exit)
        self._connect(mediator.warning, lambda text: self.publish("warning", {"message": text}))
        self._connect(mediator.tasks_warning, lambda: self.publish("warning", {"message": "没有勾选任何任务"}))
        self._connect(mediator.mirror_signal, lambda current, total: self.publish("mirror", {"current": current, "remaining": total}))
        self._connect(mediator.mirror_bar_kill_signal, lambda: self.publish("mirror", None))
        self._connect(mediator.request_focus, lambda: self.publish("focus", None))
        self._connect(ui_log_dispatcher.new_lines, lambda lines: self.publish("log", lines))
        self._connect(ui_log_dispatcher.cleared, lambda: self.publish("log_clear", None))
        if hotkeys:
            from module.hotkey_listener import global_hotkeys

            self.hotkey_token = global_hotkeys.register(lambda: {
                cfg.shutdown_hotkey: lambda: events.post(self.stop),
                cfg.pause_hotkey: lambda: events.post(self._set_paused, True),
                cfg.resume_hotkey: lambda: events.post(self._set_paused, False),
            })

    def _connect(self, signal, callback):
        signal.connect(callback, queued=True)
        self._connections.append((signal, callback))

    @staticmethod
    def _adapt_team_flags(team):
        if (cfg.backend == "playcover" and len(team.second_system_action) == 4
                and all(value in (0, 1) for value in team.second_system_action)):
            team.second_system_action = [bool(value) for value in team.second_system_action]

    def busy(self):
        return self.worker is not None

    def snapshot(self):
        from module.automation import auto

        return {"config": cfg.config.model_dump(), "version": cfg.version,
                "state": {"kind": self.kind, "running": self.busy(), "stopping": self.stopping,
                          "paused": bool(auto.input_handler and auto.check_pause()) if self.busy() else False,
                          "queued": len(self.pending), "scheduled": self.scheduled is not None,
                          "closing": self.closing, "startup": self.startup_pending}, "logs": ui_log_dispatcher.snapshot()}

    def changed(self):
        # State events omit the full log ring; it is fetched only when attaching.
        value = self.snapshot()
        value.pop("logs")
        self.publish("state", value)

    def dispatch(self, method, params):
        methods = {
            "snapshot": lambda: self.snapshot(), "config.patch": lambda: self.patch(params["values"]),
            "task.start": self.start, "task.stop": self.stop, "task.pause": self.pause,
            "command": lambda: self.command(params.get("args", [])),
            "draft": lambda: self.set_draft(params["open"]),
            "team.save": lambda: self.save_team(params["number"], params["values"]),
            "team.enable": lambda: self.enable_team(params["number"], params["enabled"]),
            "team.add": lambda: self.add_team(params.get("copy_from")),
            "team.delete": lambda: self.delete_team(params["number"]),
            "team.order": lambda: self.order_team(params["number"], params["offset"]),
            "team.stats.clear": lambda: self.clear_stats(params["number"]),
            "team.export": lambda: self.export_team(params["number"], params["path"]),
            "team.import": lambda: self.import_team(params["number"], params["path"], params.get("confirm", False)),
            "theme.get": lambda: self.get_theme(params.get("number")),
            "theme.save": lambda: self.save_theme(params.get("number"), params["values"]),
            "theme.defaults": self.default_theme,
            "theme.transfer": lambda: self.transfer_theme(params),
            "battle.start": lambda: self.start_battle(params), "screenshot": self.screenshot,
            "connection.test": self.test_connection, "app.identity": lambda: self.app_identity(params["path"]),
            "resources.check": lambda: self.check_resources(False), "resources.apply": self.apply_resources,
            "resources.skip": self.continue_startup,
            "updates.check": self.check_updates, "announcements": self.announcements,
            "logs.clear": ui_log_dispatcher.clear, "shutdown": self.shutdown,
            "startup": lambda: self.startup(params.get("args", [])),
        }
        if method not in methods:
            raise ValueError("Unknown command")
        return methods[method]()

    def patch(self, values):
        validate_fields(values)
        values = {key: bool(value) if key in {"hard_mirror", "no_weekly_bonuses"} and value < 2 else value
                  for key, value in values.items()}
        previous_profile = cfg.game_profile
        if self.busy() and any(key in GROUPS["playcover"] or key in TASK_KEYS or key in sum([GROUPS[k] for k in ("daily", "reward", "energy", "mirror", "completion")], []) for key in values):
            raise ValueError("Stop the current task before changing task settings")
        if any(key.endswith("_hotkey") for key in values):
            from pynput.keyboard import HotKey

            for key, value in values.items():
                if key.endswith("_hotkey"):
                    HotKey.parse(value)
        from module.backends.configuration import migrate_backend

        candidate = cfg.config.model_dump() | values
        if any(key in GROUPS["playcover"] for key in values):
            if candidate["playcover_app_path"]:
                identity = self.app_identity(candidate["playcover_app_path"])
                if candidate["playcover_bundle_id"] and candidate["playcover_bundle_id"] != identity["bundle_id"]:
                    raise ValueError("Bundle ID differs from the selected app")
                candidate["playcover_bundle_id"] = identity["bundle_id"]
                values = values | {"playcover_bundle_id": identity["bundle_id"]}
            migrate_backend(candidate)
        type(cfg.config)(**candidate)
        # Keep one-shot completion preferences on the original unsaved path.
        completion = {key: values[key] for key in GROUPS["completion"] if key in values}
        permanent = values.get("keep_after_completion", cfg.keep_after_completion)
        for key, value in values.items():
            if key in completion and not permanent:
                cfg.unsaved_set_value(key, value)
            else:
                cfg.set_value(key, value)
        if any(key in GROUPS["playcover"] for key in values):
            for team in cfg.config.teams.values():
                self._adapt_team_flags(team)
        if cfg.game_profile != previous_profile:
            from module.automation import auto
            from utils.path_manager import path_manager

            path_manager.initialize_paths()
            auto.clear_img_cache()
        if any(key.endswith("_hotkey") for key in values) and self.hotkey_token is not None:
            from module.hotkey_listener import global_hotkeys

            global_hotkeys.start()
        if any(key.startswith("autodaily") for key in values):
            self.restore_schedules()
        self.changed()

    def set_draft(self, opened):
        self.draft_open = bool(opened)

    def _idle(self):
        if self.busy() or self.stopping or self.closing:
            raise ValueError("Wait for the current task to finish")
        if self.auxiliary is not None and self.auxiliary[0] == "resources.apply":
            raise ValueError("Wait for image resource synchronization")
        if self.startup_pending:
            raise ValueError("Wait for startup resource checks")

    def _launch(self, worker, kind):
        self.worker, self.kind = worker, kind
        self.stopping = False
        def callback():
            self._finished(worker)
        worker.finished.connect(callback, queued=True)
        try:
            worker.start()
        except Exception:
            worker.finished.disconnect(callback)
            self.worker, self.kind, self.stopping = None, None, False
            self.changed()
            raise
        self.changed()

    def start(self):
        self._idle()
        if self.draft_open:
            raise ValueError("Save or cancel the team draft before starting")
        from backend_host.validation import check_setting
        from tasks.common.game_actions import validate_task_capabilities

        if check_setting() is False:
            raise ValueError("Task settings are incomplete")
        validate_task_capabilities(cfg)
        from tasks.base.script_task_scheme import my_script_task

        log.info("开始进行所有任务")
        ui_log_dispatcher.clear()
        self._launch(my_script_task(), "task")

    def stop(self):
        if self.worker is None or self.stopping:
            return
        from module.automation import auto

        self.stopping = True
        self.worker.requestInterruption()
        if self.kind == "battle":
            self.worker.stop()
            auto.request_stop()
        elif self.kind in {"screenshot", "connection"}:
            self.worker.requestInterruption()
            if self.kind == "screenshot":
                auto.request_stop()
        else:
            self.worker.terminate()
        self.changed()
        self._repeat_cancel(self.worker)

    def _repeat_cancel(self, worker):
        # Original task entries reset cancellation; retain the user's request
        # across that initialization window without changing those entries.
        if self.worker is worker and self.stopping and worker.isRunning():
            if self.kind != "connection":
                from module.automation import auto

                auto.request_stop()
            events.later(50, self._repeat_cancel, worker)

    def pause(self):
        if self.kind not in {"task", "battle"} or self.stopping:
            return
        from module.automation import auto

        auto.set_pause()
        self.changed()

    def _set_paused(self, paused):
        from module.automation import auto

        if auto.input_handler and auto.check_pause() != paused:
            self.pause()

    def _finished(self, worker):
        if worker is not self.worker:
            return
        if worker.isRunning():
            events.later(10, self._finished, worker)
            return
        if worker.exception is not None:
            from module.backends.base import BackendCancelled
            from module.my_error.my_error import userStopError

            if not isinstance(worker.exception, (BackendCancelled, userStopError)):
                self.publish("warning", {"message": str(worker.exception)})
        from module.automation import auto

        if auto.input_handler and auto.check_pause():
            auto.set_pause()
        self.worker, self.kind, self.stopping = None, None, False
        self.changed()
        if self.exit_requested:
            self.publish("exit", None)
        if self.closing:
            self._finish_shutdown()
        elif self.pending:
            events.later(250, self._next_command)

    def _request_exit(self):
        self.exit_requested = True
        if not self.busy():
            self.publish("exit", None)

    def _prepare_tool(self):
        self._idle()
        from module.automation import auto
        from module.backends.factory import get_playcover_session

        session = get_playcover_session()
        session.cancel.clear()
        session.input.is_pause = False
        return auto, session

    def start_battle(self, params):
        auto, session = self._prepare_tool()
        from module.system_actions import apply_power_keep_awake
        from tasks.tools.infinite_battle import BattleWorker

        worker = BattleWorker(defense=bool(params.get("defense", False)), defense_on_turn1=bool(params.get("defense_on_turn1", False)), choice_event_handling=not bool(params.get("not_choose_event", False)))
        auto.task_running = True
        awake_acquired = False

        def before_run():
            nonlocal awake_acquired
            apply_power_keep_awake(True)
            awake_acquired = True

        def cleanup():
            try:
                if session.transport.connected:
                    session.input.release_contacts()
            finally:
                try:
                    session.disconnect()
                finally:
                    auto.task_running = False
                    try:
                        auto.clear_img_cache()
                    finally:
                        if awake_acquired:
                            apply_power_keep_awake(False)

        # Thread-local keep-awake ownership is established in the worker itself.
        worker.after_run = cleanup
        worker.before_run = before_run
        worker.error_occurred.connect(lambda text: self.publish("warning", {"message": text}), queued=True)
        worker.initialization_complete.connect(lambda: self.publish("battle_ready", None), queued=True)
        try:
            self._launch(worker, "battle")
        except Exception:
            cleanup()
            raise

    def screenshot(self):
        self._idle()
        from tasks.tools.screenshot_module import ScreenshotGet

        worker = ScreenshotGet()
        worker.on_saved_timestr.connect(lambda stamp: self.publish("screenshot", {"path": str(self.data_path(f"templates/screenshot_{stamp}.png"))}), queued=True)
        self._launch(worker, "screenshot")

    @staticmethod
    def data_path(path):
        from utils.runtime_paths import data_path

        return data_path(path)

    def test_connection(self):
        self._idle()
        service = self

        class ConnectionTest(WorkerThread):
            def run(self):
                from module.backends.playcover.session import PlayCoverSession

                session = PlayCoverSession(cfg.config.model_dump())
                try:
                    session.connect()
                    frame = session.capture()
                    path = service.data_path("tmp/connection-preview.png")
                    frame.image.save(path)
                    service.publish("capture", {"path": str(path), "bundle_id": session.transport.bundle_id, "version": session.transport.version, "raw_size": frame.raw_size, "touch_size": frame.touch_size, "logical_size": frame.logical_size})
                finally:
                    session.disconnect()

        self._launch(ConnectionTest(), "connection")

    @staticmethod
    def app_identity(path):
        from module.backends.playcover.lifecycle import read_app_identity

        identity = read_app_identity(path)
        return {"path": str(identity.path), "bundle_id": identity.bundle_id}

    def save_team(self, number, values):
        self._idle()
        validate_fields(values, team=True)
        previous = cfg.config.teams[str(number)]
        team = TeamSetting(**(previous.model_dump() | values))
        team.use_team_code = False
        validate_fields({key: value for key, value in team.model_dump().items() if key not in STATS}, team=True)
        # Keep statistics from the saved configuration rather than an old draft.
        for key in STATS:
            setattr(team, key, getattr(previous, key))
        self._adapt_team_flags(team)
        cfg.set_value(str(number), team, config_obj=cfg.config.teams)
        self.draft_open = False
        self.changed()

    def enable_team(self, number, enabled):
        self._idle()
        cfg.set_team_enabled(int(number), bool(enabled))
        self.changed()

    def order_team(self, number, offset):
        self._idle()
        queue = list(cfg.teams_active_queue)
        index = queue.index(int(number))
        target = max(0, min(len(queue) - 1, index + int(offset)))
        queue[index], queue[target] = queue[target], queue[index]
        cfg.set_value("teams_active_queue", queue)
        cfg.normalize_and_sync_team_state()
        self.changed()

    def add_team(self, copy_from=None):
        self._idle()
        if len(cfg.config.teams) >= 20:
            raise ValueError("At most 20 presets")
        number = max(cfg.get_team_numbers(), default=0) + 1
        team = cfg.config.teams[str(copy_from)].model_copy(deep=True) if copy_from is not None else TeamSetting()
        cfg.set_value(str(number), team, config_obj=cfg.config.teams)
        if copy_from is not None:
            theme_list.set_team_weight_config_from_team(number, int(copy_from))
        self.changed()
        return number

    def delete_team(self, number):
        self._idle()
        if len(cfg.config.teams) <= 1:
            raise ValueError("Keep at least one team")
        number = int(number)
        cfg.remove_team_from_queue(number)
        cfg.config.teams.pop(str(number))
        theme_list.delete_team_weight_config(number)
        old_to_new, compact = {}, {}
        for new_index, old_index in enumerate(sorted(cfg.config.teams, key=int), start=1):
            old_number = int(old_index)
            old_to_new[old_number] = new_index
            compact[str(new_index)] = cfg.config.teams[old_index]
            if new_index != old_number:
                theme_list.set_team_weight_config_from_team(new_index, old_number)
                theme_list.delete_team_weight_config(old_number)
        cfg.config.teams = compact
        cfg.reindex_team_queue(old_to_new)
        cfg.save()
        self.changed()

    def clear_stats(self, number):
        self._idle()
        team = cfg.config.teams[str(number)]
        for key in STATS:
            setattr(team, key, [0.0] * 3 if key.startswith("total_") else 0)
        cfg.save()
        self.changed()

    def export_team(self, number, path):
        from module.config.team_import_export import export_team_settings

        if not export_team_settings(int(number), path):
            raise ValueError("Team export failed")

    def import_team(self, number, path, confirm):
        self._idle()
        from module.config.team_import_export import apply_team_settings, import_team_settings

        team, weight, missing = import_team_settings(path, int(number))
        if team is None:
            raise ValueError("; ".join(map(str, missing)))
        if weight is not None:
            from backend_host.validation import validate_theme

            validate_theme(weight)
        if missing and not confirm:
            return {"missing": missing}
        team.use_team_code = False
        validate_fields({key: value for key, value in team.model_dump().items() if key not in STATS}, team=True)
        previous = cfg.config.teams[str(number)]
        for key in STATS:
            setattr(team, key, getattr(previous, key))
        self._adapt_team_flags(team)
        apply_team_settings(int(number), team, weight)
        self.changed()
        return {"missing": []}

    def get_theme(self, number=None):
        if number is None:
            return copy.deepcopy(theme_list.config)
        theme_list.create_team_weight_config(int(number))
        return theme_list.load_config(theme_list.build_team_weight_path(int(number)))

    def save_theme(self, number, values):
        self._idle()
        from backend_host.validation import validate_theme

        validate_theme(values)
        path = theme_list.theme_pack_list_path if number is None else theme_list.build_team_weight_path(int(number))
        theme_list.save_config(path, values)
        if number is None:
            theme_list.config = copy.deepcopy(values)
        self.publish("theme_saved", {"number": number})

    @staticmethod
    def default_theme():
        from module import THEME_PACK_LIST_EXAMPLE_PATH

        return theme_list.load_config(THEME_PACK_LIST_EXAMPLE_PATH)

    def transfer_theme(self, params):
        self._idle()
        from module.config import theme_pack_import_export as transfer

        number = int(params["number"])
        action = params["action"]
        if action == "export":
            result = transfer.export_theme_pack_weight(number, params["path"])
        elif action == "copy":
            result = transfer.export_theme_pack_weight_to_base64(number)
        elif action in {"import", "paste"}:
            import base64
            from pathlib import Path

            from ruamel.yaml import YAML

            from backend_host.validation import validate_theme

            text = Path(params["path"]).read_text(encoding="utf-8") if action == "import" else base64.b64decode(params["code"]).decode("utf-8")
            data = YAML().load(text)
            if not data:
                return True
            validate_theme(data)
            path, existing = transfer._load_existing_theme_pack_weight(number)
            merged = transfer._deep_merge_dicts(existing, data)
            validate_theme(merged)
            theme_list.save_config(str(path), merged)
            result = True
        else:
            raise ValueError("Unknown theme transfer")
        if result is False or result is None:
            raise ValueError("Theme configuration transfer failed")
        return result

    def restore_schedules(self):
        from utils.schedule_helper import ScheduleHelper

        scheduler = ScheduleHelper()
        for suffix in ("", "2", "3", "4"):
            if not cfg.get_value("autodaily" + suffix):
                scheduler.unregister_task("AALC Daily Task" + suffix)
        scheduler.restore_daily_tasks(cfg)

    def _suppress_completion(self, suppressed):
        from module.system_actions import suspend_completion_actions

        suspend_completion_actions(suppressed)
        self.publish("completion_suppressed", bool(suppressed))

    def command(self, args):
        # Same resident protocol, start delay, FIFO and completion suppression.
        args = list(args)
        start_flag = "start" in args
        if start_flag and (self.busy() or self.scheduled is not None or self.startup_pending
                           or self.auxiliary is not None and self.auxiliary[0] == "resources.apply"):
            self.pending.append(args)
            self._suppress_completion(True)
            self.changed()
            return
        from backend_host.commands import parse_command

        start_flag, completion = parse_command(["aalc", *args])
        if completion is not None:
            from module.after_completion_types import normalize_after_completion_config

            actions, power = normalize_after_completion_config(*completion)
            cfg.unsaved_set_value("keep_after_completion", False)
            cfg.unsaved_set_value("after_completion_actions", actions)
            cfg.unsaved_set_value("after_completion_power_action", power)
        if start_flag:
            self.scheduled = args
            events.later(3000, self._scheduled_start, args)
        self.changed()

    def _scheduled_start(self, command):
        if self.closing or self.scheduled is not command:
            return
        if self.busy() or self.auxiliary is not None and self.auxiliary[0] == "resources.apply":
            if command is not None:
                self.pending.insert(0, command)
                self._suppress_completion(True)
            self.scheduled = None
            self.changed()
            return
        self.scheduled = None
        self._suppress_completion(bool(self.pending))
        try:
            self.start()
        except Exception as exc:
            self.publish("warning", {"message": str(exc)})
            if self.pending:
                events.later(250, self._next_command)

    def _next_command(self):
        if self.closing:
            return
        if (self.busy() or self.scheduled is not None
                or self.auxiliary is not None and self.auxiliary[0] == "resources.apply"):
            events.later(250, self._next_command)
        elif self.pending:
            self.command(self.pending.pop(0))
            if self.pending:
                self._suppress_completion(True)
        else:
            self._suppress_completion(False)

    def startup(self, args):
        self.startup_pending = True
        self.startup_args = list(args)
        try:
            self.restore_schedules()
        except Exception as exc:
            self.publish("warning", {"message": str(exc)})
        if cfg.check_update:
            try:
                self.check_updates(automatic=True)
            except Exception as exc:
                self.publish("warning", {"message": str(exc)})
        try:
            self.check_resources(True)
        except Exception as exc:
            self.publish("warning", {"message": str(exc)})
            self.continue_startup()
        self.changed()

    def continue_startup(self):
        if not self.startup_pending:
            return
        self.startup_pending = False
        self.awaiting_resource_choice = False
        args, self.startup_args = self.startup_args, []
        self.changed()
        if args and not self.closing:
            self.command(args)
        if self.pending and self.scheduled is None and not self.closing:
            self._next_command()

    def _start_auxiliary(self, worker, kind):
        if self.auxiliary is not None:
            raise ValueError("A background check is already running")
        self.auxiliary = (kind, worker)
        def callback():
            self._aux_finished(worker)
        worker.finished.connect(callback, queued=True)
        try:
            worker.start()
        except Exception:
            worker.finished.disconnect(callback)
            self.auxiliary = None
            raise

    def _aux_finished(self, worker):
        if worker.isRunning():
            events.later(10, self._aux_finished, worker)
            return
        self.auxiliary = None
        if self.closing:
            self._finish_shutdown()
        elif self.pending_apply:
            self.apply_resources()
        elif self.startup_pending and not self.awaiting_resource_choice:
            self.continue_startup()
        elif not self.startup_pending and self.pending and self.scheduled is None:
            self._next_command()

    def check_updates(self, automatic=False):
        from backend_host.git_update import GitUpdateCheck

        active = getattr(self, "update_check", None)
        if active is not None:
            if not automatic:
                active["automatic"] = False
            return None
        worker = GitUpdateCheck(10)
        context = {"automatic": automatic}
        self.update_check = context

        def checked(result):
            if self.update_check is context and "result" not in context:
                context["result"] = result

        def finished():
            if self.update_check is not context:
                return
            if worker.isRunning():
                events.later(10, finished)
                return
            self.update_check = None
            if "result" in context:
                result, is_automatic = context["result"], context["automatic"]
                self.publish("update" if not is_automatic or result["status"] == "UPDATE_AVAILABLE" else "update_status", {**result, "automatic": is_automatic})

        worker.result.connect(checked, queued=True)
        worker.finished.connect(finished, queued=True)
        # Checks own no game connection and can run alongside resource checks.
        try:
            self._start_background(worker)
        except Exception:
            finished()
            raise
        return None

    def _start_background(self, worker):
        self.background.add(worker)

        def finished():
            if worker.isRunning():
                events.later(10, finished)
                return
            self.background.discard(worker)
            if self.closing:
                self._finish_shutdown()

        worker.finished.connect(finished, queued=True)
        try:
            worker.start()
        except Exception:
            worker.finished.disconnect(finished)
            self.background.discard(worker)
            raise

    def announcements(self):
        service = self

        class AnnouncementCheck(WorkerThread):
            def run(self):
                import time

                import requests

                response = requests.get("https://gitee.com/KIYI/aalcresource/raw/main/AALC/announcements.json", timeout=10)
                response.raise_for_status()
                data = response.json()
                stamp = time.mktime(time.strptime(data["Time"], "%Y-%m-%d %H:%M:%S"))
                cfg.set_value("announcement", stamp)
                service.publish("announcement", data)

        worker = AnnouncementCheck()
        worker.finished.connect(lambda: self.publish("warning", {"message": str(worker.exception)}) if worker.exception else None, queued=True)
        self._start_background(worker)

    def check_resources(self, startup=False):
        from module.resource_sync import ResourceSyncService, ResourceSyncWorker, ResourceWorkerMode

        worker = ResourceSyncWorker(service=ResourceSyncService(), mode=ResourceWorkerMode.CHECK_AND_PLAN, preferred_source=cfg.image_resource_source)

        def checked(payload):
            self.resource_payload = payload
            changes = bool(payload.sync_plan and payload.sync_plan.has_changes)
            if payload.sync_plan is not None and not changes and payload.check_result.remote_manifest is not None:
                worker.service.accept_remote_state(payload.check_result)
            self.awaiting_resource_choice = startup and cfg.image_resource_sync and changes
            self.publish("resources", {"status": payload.check_result.status.name, "message": payload.check_result.message, "changes": changes, "startup": startup, "automatic": bool(cfg.image_resource_sync)})

        worker.checkFinished.connect(checked, queued=True)
        worker.failed.connect(lambda text: self.publish("warning", {"message": text}), queued=True)
        self._start_auxiliary(worker, "resources.check")

    def apply_resources(self):
        if self.busy() or self.closing:
            raise ValueError("Stop the task before synchronizing images")
        if self.auxiliary is not None:
            if self.auxiliary[0] == "resources.check":
                self.pending_apply = True
                return
            raise ValueError("Image synchronization is already running")
        self.pending_apply = False
        self.awaiting_resource_choice = False
        if self.resource_payload is None or self.resource_payload.sync_plan is None:
            raise ValueError("Check image resources first")
        from module.resource_sync import ResourceSyncService, ResourceSyncWorker, ResourceWorkerMode

        worker = ResourceSyncWorker(service=ResourceSyncService(), mode=ResourceWorkerMode.APPLY_PLAN, preferred_source=cfg.image_resource_source, check_result=self.resource_payload.check_result, sync_plan=self.resource_payload.sync_plan)
        worker.progressChanged.connect(lambda value: self.publish("resource_progress", value), queued=True)
        worker.applyFinished.connect(lambda result: self.publish("resources_applied", {"message": "图片资源已同步"}), queued=True)
        worker.failed.connect(lambda text: self.publish("warning", {"message": text}), queued=True)
        try:
            self._start_auxiliary(worker, "resources.apply")
        except Exception:
            self.continue_startup()
            raise

    def shutdown(self, force=False):
        if self.shutdown_complete:
            return
        self.force_close = self.force_close or force
        self.closing = True
        self.pending.clear()
        self.scheduled = None
        self._suppress_completion(False)
        self.stop()
        self._finish_shutdown()

    def _finish_shutdown(self):
        if self.shutdown_complete or self.busy() or self.auxiliary is not None or self.background:
            return
        try:
            cfg.flush()
            if self._shutdown_save_failed:
                # Original flush clears its pending flag before writing. A
                # failed flush must therefore be retried explicitly by the host.
                cfg.save(instant=True)
            self._shutdown_save_failed = False
        except Exception as exc:
            self._shutdown_save_failed = True
            log.error(f"退出时保存配置失败: {exc}")
            if not self.force_close:
                self.closing = False
                self.exit_requested = False
                self.publish("shutdown_failed", {"message": f"保存配置失败，请重试退出。\n{exc}"})
                self.changed()
                return
        if self.hotkey_token is not None:
            from module.hotkey_listener import global_hotkeys

            global_hotkeys.unregister(self.hotkey_token)
            self.hotkey_token = None
        for signal, callback in self._connections:
            signal.disconnect(callback)
        self._connections.clear()
        self.shutdown_complete = True
        self.publish("closed", None)
