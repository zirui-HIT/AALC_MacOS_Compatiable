"""IPC, cancellation, control ordering and UI data invariants without game input."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from backend_host.runtime import WorkerThread, events
from frontend_appkit.edit_models import TeamDraft
from frontend_appkit.theme_draft import ThemeDraft
from utils.runtime_paths import SOURCE_ROOT


def pump_until(condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        events.drain(0.01)
    assert condition()


@pytest.fixture
def service(monkeypatch):
    from backend_host.service import BackendService
    from module import system_actions
    from module.config import cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(deep=True, update={"backend": "playcover", "keep_after_completion": True}))
    monkeypatch.setattr(cfg, "save", Mock())
    monkeypatch.setattr(cfg, "flush", Mock())
    messages = []
    value = BackendService(lambda event, data: messages.append((event, data)), hotkeys=False)
    value.messages = messages
    yield value
    value.worker = None
    value.auxiliary = None
    value.background.clear()
    value.shutdown(force=True)
    system_actions.suspend_completion_actions(False)
    while events.drain():
        pass


def test_backend_pipe_is_independent_of_frontend_and_shuts_down_on_eof(tmp_path):
    script = "from backend_host.main import run; import sys; result=run(); assert not any(n.startswith(('PySide6','frontend_appkit')) for n in sys.modules); sys.exit(result)"
    process = subprocess.run([sys.executable, "-u", "-c", script, "--no-hotkeys"], input='', cwd=SOURCE_ROOT, env={**os.environ, "AALC_DATA_ROOT": str(tmp_path)}, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    messages = [json.loads(line) for line in process.stdout.splitlines()]
    assert messages[0]["event"] == "ready"
    assert messages[-1]["event"] == "closed"


def test_protocol_rejects_bad_request_and_remains_responsive(tmp_path):
    requests = 'bad json\n' + json.dumps({"v": 99, "id": 1, "method": "snapshot"}) + '\n' + json.dumps({"v": 1, "id": 2, "method": "snapshot"}) + '\n'
    result = subprocess.run([sys.executable, "-u", "main.py", "--backend", "--no-hotkeys"], input=requests, cwd=SOURCE_ROOT, env={**os.environ, "AALC_DATA_ROOT": str(tmp_path)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    responses = {message["id"]: message for message in map(json.loads, result.stdout.splitlines()) if "id" in message}
    assert "error" in responses[None] and "error" in responses[1]
    assert responses[2]["result"]["state"]["running"] is False


def test_frontend_completion_choices_are_saved_across_backend_restarts(tmp_path):
    pytest.importorskip("AppKit")
    from frontend_appkit.application import Application

    app = Application.__new__(Application)
    app.client = Mock()
    app.patch({"after_completion_actions": ["exit_game", "exit_aalc"]})
    method, params = app.client.request.call_args.args
    env = {**os.environ, "AALC_DATA_ROOT": str(tmp_path)}

    def host(request):
        result = subprocess.run([sys.executable, "-u", "main.py", "--backend", "--no-hotkeys"],
            input=json.dumps({"v": 1, "id": 1, **request}) + "\n", cwd=SOURCE_ROOT,
            env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        response = next(message for message in map(json.loads, result.stdout.splitlines()) if message.get("id") == 1)
        assert "error" not in response, response
        return response["result"]

    host({"method": method, "params": params})
    restarted = host({"method": "snapshot"})
    assert restarted["config"]["after_completion_actions"] == ["exit_game", "exit_aalc"]
    assert restarted["config"]["keep_after_completion"] is True


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("power", ["none", "sleep"])
def test_native_host_migrates_unavailable_completion_actions(service, monkeypatch, keep, power):
    from backend_host.service import BackendService
    from module.config import cfg
    from tasks.common.game_actions import validate_task_capabilities

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "keep_after_completion": keep, "after_completion_power_action": power,
        "after_completion_actions": ["exit_game", "exit_emulator", "exit_aalc"],
    }))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    value = BackendService(Mock(), hotkeys=False)
    try:
        assert cfg.after_completion_power_action == "none"
        assert cfg.after_completion_actions == (["exit_game", "exit_aalc"] if keep else [])
        validate_task_capabilities(cfg)
        cfg._schedule_save.assert_called()
    finally:
        value.shutdown(force=True)


def test_native_completion_migration_keeps_other_backend_preferences(service, monkeypatch):
    from backend_host.service import BackendService
    from module.config import cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "backend": "windows", "keep_after_completion": True,
        "after_completion_actions": ["exit_emulator"], "after_completion_power_action": "sleep",
    }))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    value = BackendService(Mock(), hotkeys=False)
    try:
        assert cfg.after_completion_power_action == "sleep"
        assert cfg.after_completion_actions == ["exit_emulator"]
    finally:
        value.shutdown(force=True)


@pytest.mark.parametrize("suffix", ["", "2", "3", "4"])
@pytest.mark.parametrize("saved", [[], [True], [True, True, False, False, False, False],
                                  [False, False, True, True, True, True, True]])
def test_native_schedule_migration_keeps_only_supported_completion_choices(service, monkeypatch, suffix, saved):
    from backend_host.service import BackendService
    from module.config import cfg
    from tasks.common.game_actions import validate_task_capabilities

    key = "autodaily" + suffix + "_task_exit"
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={key: saved, "mirror": False}))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    monkeypatch.setattr(events, "later", Mock())
    value = BackendService(Mock(), hotkeys=False)
    try:
        expected = (saved + [False, False])[:2] + [False] * 5
        assert cfg.get_value(key) == expected
        cfg._schedule_save.assert_called()
        value.command(["start", "--exit", "autodaily" + suffix])
        assert cfg.after_completion_actions == (["exit_game"] if expected[0] else []) + (["exit_aalc"] if expected[1] else [])
        assert cfg.after_completion_power_action == "none"
        validate_task_capabilities(cfg)
    finally:
        value.shutdown(force=True)


def test_native_schedule_migration_keeps_other_backend_preferences(service, monkeypatch):
    from backend_host.service import BackendService
    from module.config import cfg

    saved = [True, False, True, False, False, False]
    values = {"autodaily" + suffix + "_task_exit": saved[:] for suffix in ("", "2", "3", "4")}
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "windows", **values}))
    value = BackendService(Mock(), hotkeys=False)
    try:
        assert all(cfg.get_value(key) == saved for key in values)
    finally:
        value.shutdown(force=True)


def test_corrupt_team_theme_returns_a_request_error_and_preserves_the_file(service, monkeypatch, tmp_path):
    from module.config import theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    path = Path(theme_list.build_team_weight_path(1))
    path.parent.mkdir()
    broken = "theme_pack_list: [\n"
    path.write_text(broken)
    with pytest.raises(ValueError, match="加载错误"):
        service.dispatch("theme.get", {"number": 1})
    assert path.read_text() == broken
    assert service.dispatch("snapshot", {})["state"]["running"] is False


def test_changing_game_profile_refreshes_the_paths_and_recognition_cache(service, monkeypatch):
    import copy

    from module.automation import auto
    from module.config import cfg
    from utils.path_manager import path_manager

    for name, value in vars(path_manager).items():
        monkeypatch.setattr(path_manager, name, copy.deepcopy(value))
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    monkeypatch.setattr(auto, "img_cache", {"old": object()})
    path_manager.initialize_paths()
    service.patch({"game_profile": "ios_zh_cn"})
    assert path_manager.active_paths[0] == "dark/ios_zh_cn"
    assert path_manager.current_language == "zh_cn"
    assert not auto.img_cache


@pytest.mark.parametrize("value", [0, 1, 2])
@pytest.mark.parametrize("key", ["hard_mirror", "no_weekly_bonuses"])
def test_native_mode_choices_keep_original_boolean_types(service, monkeypatch, key, value):
    from module.config import cfg

    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    service.patch({key: value})
    actual = cfg.get_value(key)
    assert actual == value
    assert type(actual) is (bool if value < 2 else int)


def test_native_startup_restores_the_original_normal_route_mode(service, monkeypatch):
    from backend_host.service import BackendService
    from module.config import cfg
    from tasks.mirror.search_road import RouteGraph, Row

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"hard_mirror": 0}))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    value = BackendService(Mock(), hotkeys=False)
    try:
        assert cfg.hard_mirror is False
        graph = RouteGraph([[('battle', (100, 100))]], Row.MID, (0, 100), cfg.hard_mirror)
        assert graph.column_count == 4
        assert graph.columns['column3'][Row.MID].node_class == 'shop'
        assert graph.columns['column4'][Row.MID].node_class == 'boss_battle'
    finally:
        value.shutdown(force=True)


@pytest.mark.parametrize("boundary", ["startup", "save", "import", "profile"])
def test_native_team_flags_keep_the_original_second_system_branch(service, monkeypatch, tmp_path, boundary):
    from ruamel.yaml import YAML

    from backend_host.service import BackendService
    from module.config import TeamSetting, cfg, theme_list
    from tasks.mirror.in_shop import Shop

    values = {"shop_strategy": 2, "after_level_IV": True, "after_level_IV_select": 2,
              "second_system": True, "second_system_action": [1, 0, 0, 0]}
    cfg.config.teams["1"] = TeamSetting(**values)
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    value = None
    try:
        if boundary == "startup":
            value = BackendService(Mock(), hotkeys=False)
        elif boundary == "save":
            service.save_team(1, values)
        elif boundary == "import":
            imported = tmp_path / "team.yaml"
            with imported.open("w") as file:
                YAML().dump(cfg.config.teams["1"].model_dump(), file)
            service.import_team(1, str(imported), True)
        else:
            service.patch({"game_profile": "ios_en"})
        team = cfg.config.teams["1"]
        assert team.second_system_action == [True, False, False, False]
        assert all(type(flag) is bool for flag in team.second_system_action)
        shop = Shop(team)
        shop.after_fuse_IV()
        assert shop.fuse_switch and shop.fuse_aggressive_switch
    finally:
        if value is not None:
            value.shutdown(force=True)


def test_team_flag_adaptation_preserves_other_backend_types(service, monkeypatch):
    from backend_host.service import BackendService
    from module.config import TeamSetting, cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "windows"}))
    team = TeamSetting(second_system_action=[1, 0, 0, 0])
    BackendService._adapt_team_flags(team)
    assert all(type(flag) is int for flag in team.second_system_action)


@pytest.mark.parametrize("values", [
    {"theme_pack_list": "broken"}, {"theme_pack_list_hard": ["broken"]},
    {"theme_pack_list_cn": {"包": True}}, {"theme_pack_list_hard_cn": {"包": 11}},
    {"preferred_thresholds": "3"}, {"preferred_thresholds": 11},
    {"forbidden_theme_packs": []}, {"forbidden_theme_packs": {"normal_1": "pack"}},
])
@pytest.mark.parametrize("action", ["import", "paste"])
def test_bad_theme_transfers_are_rejected_before_changing_the_saved_file(service, monkeypatch, tmp_path, values, action):
    import base64

    from ruamel.yaml import YAML

    from module.config import theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    path = Path(theme_list.build_team_weight_path(1))
    path.parent.mkdir()
    original = "preferred_thresholds: 0\ntheme_pack_list: {pack: 2}\n"
    path.write_text(original)
    imported = tmp_path / "import.yaml"
    with imported.open("w") as file:
        YAML().dump(values, file)
    params = {"number": 1, "action": action, "path": str(imported),
              "code": base64.b64encode(imported.read_bytes()).decode()}
    with pytest.raises(ValueError):
        service.transfer_theme(params)
    assert path.read_text() == original


def test_valid_theme_transfer_preserves_the_existing_merge_behavior(service, monkeypatch, tmp_path):
    from ruamel.yaml import YAML

    from module.config import theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    path = Path(theme_list.build_team_weight_path(1))
    path.parent.mkdir()
    path.write_text("preferred_thresholds: 0\ntheme_pack_list: {keep: 2, update: 1}\n")
    imported = tmp_path / "import.yaml"
    imported.write_text("theme_pack_list: {update: 4}\n")
    assert service.transfer_theme({"number": 1, "action": "import", "path": str(imported)}) is True
    assert YAML().load(path.read_text()) == {"preferred_thresholds": 0, "theme_pack_list": {"keep": 2, "update": 4}}


@pytest.mark.parametrize("index", [1, 3])
@pytest.mark.parametrize("content,accepted", [("theme_pack_list: {update: 4}\n", True),
                                             ("", False), ("{}", False), ("null", False),
                                             ("false", False), ("0", False)])
def test_theme_import_and_paste_preserve_the_current_editor_draft(service, monkeypatch, tmp_path, index, content, accepted):
    import base64
    from types import SimpleNamespace

    pytest.importorskip("AppKit")
    from ruamel.yaml import YAML

    from frontend_appkit.application import Application
    from module.config import theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    path = Path(theme_list.build_team_weight_path(1))
    path.parent.mkdir()
    path.write_text("theme_pack_list: {keep: 1, update: 2}\n")
    imported = tmp_path / "import.yaml"
    imported.write_text(content)
    draft = ThemeDraft({"theme_pack_list": {"keep": 9, "update": 2}})
    app = Application.__new__(Application)
    app.client = Mock()
    calls = []

    def request(method, params, callback):
        calls.append(method)
        callback(service.dispatch(method, params))

    app.client.request.side_effect = request
    monkeypatch.setattr("frontend_appkit.application.choose_path", lambda **kwargs: str(imported))
    board = Mock()
    board.stringForType_.return_value = base64.b64encode(imported.read_bytes()).decode()
    monkeypatch.setattr("frontend_appkit.application.A.NSPasteboard", Mock(generalPasteboard=Mock(return_value=board)))
    render, commit = Mock(), Mock()
    if not accepted:
        with pytest.raises(ValueError, match="empty"):
            app.theme_transfer(1, index, draft, render, commit, SimpleNamespace(closed=False))
        assert draft.config_data == {"theme_pack_list": {"keep": 9, "update": 2}}
        assert YAML().load(path.read_text()) == {"theme_pack_list": {"keep": 1, "update": 2}}
        assert calls == ["theme.transfer"]
        render.assert_not_called()
        return
    app.theme_transfer(1, index, draft, render, commit, SimpleNamespace(closed=False))
    expected = {"theme_pack_list": {"keep": 9, "update": 4}}
    assert draft.config_data == expected
    assert YAML().load(path.read_text()) == expected
    assert calls == ["theme.transfer", "theme.get"]
    commit.assert_called_once_with()
    render.assert_called_once_with()


@pytest.mark.parametrize("invalid_draft", [False, True])
def test_invalid_theme_merge_never_saves_the_draft_or_replaces_the_file(service, monkeypatch, tmp_path, invalid_draft):
    from module.config import theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    path = Path(theme_list.build_team_weight_path(1))
    path.parent.mkdir()
    original = "theme_pack_list: {keep: 1, update: 2}\n"
    path.write_text(original)
    imported = tmp_path / "import.yaml"
    imported.write_text("theme_pack_list: {update: 4}\n" if invalid_draft else "theme_pack_list: 3\n")
    values = {"theme_pack_list": 3} if invalid_draft else {"theme_pack_list": {"keep": 9, "update": 2}}
    with pytest.raises(ValueError):
        service.transfer_theme({"number": 1, "action": "import", "path": str(imported), "values": values})
    assert path.read_text() == original


def test_team_import_rejects_invalid_attached_weights_before_applying_any_settings(service, monkeypatch, tmp_path):
    from ruamel.yaml import YAML

    from module.config import cfg, theme_list

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    original = cfg.config.teams["1"].model_dump()
    imported = tmp_path / "team.yaml"
    values = original | {"remark_name": "must not apply", "custom_theme_pack_weight": {"theme_pack_list": 3}}
    with imported.open("w") as file:
        YAML().dump(values, file)
    with pytest.raises(ValueError):
        service.import_team(1, str(imported), True)
    assert cfg.config.teams["1"].model_dump() == original
    assert not Path(theme_list.build_team_weight_path(1)).exists()


@pytest.mark.parametrize("target", [1, 2])
@pytest.mark.parametrize("included_stats", [False, True])
def test_team_import_preserves_target_statistics(service, monkeypatch, tmp_path, target, included_stats):
    from ruamel.yaml import YAML

    from module.config import TeamSetting, cfg, theme_list
    from native_contract import STATS

    monkeypatch.setattr(theme_list, "theme_pack_weight_path", tmp_path / "weights")
    cfg.config.teams["1"].remark_name = "imported settings"
    cfg.config.teams[str(target)] = cfg.config.teams.get(str(target), TeamSetting()).model_copy(update={
        "mirror_hard_count": 9, "total_mirror_time_hard": [100., 110., 120.],
        "mirror_normal_count": 7, "total_mirror_time_normal": [200., 210., 220.],
    })
    previous = {key: getattr(cfg.config.teams[str(target)], key) for key in STATS}
    imported = tmp_path / "team.yaml"
    service.export_team(1, str(imported))
    values = YAML().load(imported)
    assert not STATS.intersection(values)
    if included_stats:
        values.update({key: [0., 0., 0.] if key.startswith("total_") else 0 for key in STATS})
        with imported.open("w") as file:
            YAML().dump(values, file)
    cfg.config.teams[str(target)].remark_name = "before import"
    assert service.import_team(target, str(imported), True) == {"missing": []}
    actual = cfg.config.teams[str(target)]
    assert actual.remark_name == "imported settings"
    assert {key: getattr(actual, key) for key in STATS} == previous


def test_finished_waits_for_cleanup_and_thread_exit(service):
    marks = []

    class Worker(WorkerThread):
        def run(self):
            marks.append("run")

    worker = Worker()
    worker.after_run = lambda: (time.sleep(0.02), marks.append("cleanup"))
    worker.finished.connect(lambda: marks.append("finished"))
    service._launch(worker, "screenshot")
    service.closing = True
    pump_until(lambda: service.worker is None)
    assert marks == ["run", "cleanup", "finished"]
    assert service.messages[-1][0] == "closed"


@pytest.mark.parametrize("launch", ["idle", "game", "auxiliary", "background"])
def test_shutdown_save_failure_keeps_host_alive_and_can_retry(service, monkeypatch, launch):
    from module.config import cfg

    release = threading.Event()

    class Worker(WorkerThread):
        def run(self):
            assert release.wait(2)

    if launch != "idle":
        worker = Worker()
        if launch == "game":
            service._launch(worker, "screenshot")
        elif launch == "auxiliary":
            service._start_auxiliary(worker, "resources.check")
        else:
            service._start_background(worker)
    callbacks = len(service._connections)
    monkeypatch.setattr(cfg, "flush", Mock(side_effect=OSError("disk full")))
    service.shutdown()
    release.set()
    pump_until(lambda: any(event == "shutdown_failed" for event, _ in service.messages))
    assert not service.closing and not service.shutdown_complete
    assert len(service._connections) == callbacks
    assert not any(event == "closed" for event, _ in service.messages)
    assert not service.busy() and service.auxiliary is None and not service.background
    assert service.dispatch("snapshot", {})["state"]["closing"] is False
    monkeypatch.setattr(cfg, "flush", Mock())
    service.shutdown()
    assert service.shutdown_complete
    assert service.messages[-1][0] == "closed"
    assert not service._connections


def test_backend_eof_does_not_leave_process_running_when_save_fails(tmp_path):
    script = "from module.config import cfg; from unittest.mock import Mock; cfg.flush=Mock(side_effect=OSError('disk full')); from backend_host.main import run; run()"
    process = subprocess.run([sys.executable, "-u", "-c", script, "--no-hotkeys"], input='', cwd=SOURCE_ROOT, env={**os.environ, "AALC_DATA_ROOT": str(tmp_path)}, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    messages = [json.loads(line) for line in process.stdout.splitlines()]
    assert messages[-1]["event"] == "closed"
    assert not any(message.get("event") == "shutdown_failed" for message in messages)


def test_shutdown_retry_writes_again_after_original_flush_clears_pending(service, monkeypatch):
    from module.config import cfg

    monkeypatch.setattr(cfg, "flush", type(cfg).flush.__get__(cfg))
    monkeypatch.setattr(cfg, "save", type(cfg).save.__get__(cfg))
    write = Mock(side_effect=[OSError("disk full"), None])
    monkeypatch.setattr(cfg, "_save_config", write)
    monkeypatch.setattr(cfg, "_pending_save", True)
    service.shutdown()
    assert write.call_count == 1 and not cfg._pending_save
    assert service._shutdown_save_failed and not service.shutdown_complete
    service.shutdown()
    assert write.call_count == 2
    assert service.shutdown_complete and not service._shutdown_save_failed


@pytest.mark.parametrize("launch", ["game", "auxiliary", "background"])
def test_failed_worker_start_releases_registration_and_allows_shutdown(service, monkeypatch, launch):
    worker = WorkerThread()
    monkeypatch.setattr(worker, "start", Mock(side_effect=RuntimeError("start failed")))
    with pytest.raises(RuntimeError):
        if launch == "game":
            service._launch(worker, "task")
        elif launch == "auxiliary":
            service._start_auxiliary(worker, "resources.check")
        else:
            service._start_background(worker)
    assert not service.busy() and service.auxiliary is None and not service.background
    service.shutdown()
    assert service.messages[-1][0] == "closed"


def test_stop_survives_original_cancel_reset(service, monkeypatch):
    from module.automation import auto

    cancel = threading.Event()
    started = threading.Event()
    reset = threading.Event()
    monkeypatch.setattr(auto, "request_stop", cancel.set)

    class Worker(WorkerThread):
        def run(self):
            started.set()
            reset.wait(1)
            cancel.clear()  # Original entry's cancellation reset.
            assert cancel.wait(2)

    worker = Worker()
    service._launch(worker, "screenshot")
    assert started.wait(1)
    service.stop()
    reset.set()
    pump_until(lambda: service.worker is None)
    assert worker.exception is None


def test_battle_uses_original_options_and_cleans_up_even_if_disconnect_fails(service, monkeypatch):
    from module import system_actions
    from module.automation import auto
    from module.backends import factory
    from tasks.tools import infinite_battle

    session = Mock()
    session.cancel = threading.Event()
    session.disconnect.side_effect = OSError("disconnected")
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    monkeypatch.setattr(system_actions, "apply_power_keep_awake", Mock())
    arguments = []

    class BattleWorker(WorkerThread):
        def __init__(self, **params):
            super().__init__()
            self.error_occurred = Mock()
            self.initialization_complete = Mock()
            arguments.append(params)

        def run(self):
            assert auto.task_running

    monkeypatch.setattr(infinite_battle, "BattleWorker", BattleWorker)
    service.start_battle({"defense": True, "defense_on_turn1": True, "not_choose_event": True})
    pump_until(lambda: service.worker is None)
    assert arguments == [{"defense": True, "defense_on_turn1": True, "choice_event_handling": False}]
    assert not auto.task_running
    session.input.release_contacts.assert_called_once()
    assert system_actions.apply_power_keep_awake.call_args_list[-1].args == (False,)


def test_original_battle_window_setup_keeps_playcover_zoom_available(service, monkeypatch):
    from module.config import cfg
    from tasks.tools.infinite_battle import BattleWorker

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"background_click": False}))
    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    worker = BattleWorker()
    worker._set_win()
    assert worker.background_click is False
    assert cfg.background_click is False
    worker.stop()
    assert cfg.background_click is False


def test_command_parser_keeps_original_exit_defaults_and_order(service, monkeypatch):
    from backend_host.commands import parse_command
    from module.config import cfg

    assert parse_command(["aalc", "start", "--exit", "bad"])[1] == (["exit_aalc"], "none")
    assert parse_command(["aalc", "--exit", "4", "start"])[1] is None
    assert parse_command(["aalc", "start", "--exit"])[1] == (["exit_aalc"], "none")
    monkeypatch.setattr(events, "later", lambda *args: None)
    service.command(["start", "--exit", "4"])
    service.command(["start", "--exit", "5"])
    assert service.pending == [["start", "--exit", "5"]]
    assert cfg.after_completion_actions == ["exit_game"]


@pytest.mark.parametrize("slot", ["autodaily", "autodaily2", "autodaily3", "autodaily4"])
def test_scheduled_completion_is_serialized_for_yaml(service, monkeypatch, slot):
    import io

    from ruamel.yaml import YAML

    from module.config import cfg

    monkeypatch.setattr(cfg, "_schedule_save", Mock())
    monkeypatch.setattr(events, "later", Mock())
    cfg.unsaved_set_value(slot + "_task_exit", [True, True, False, False, False, False, False])
    service.command(["start", "--exit", slot])
    assert cfg.after_completion_actions == ["exit_game", "exit_aalc"]
    assert all(type(action) is str for action in cfg.after_completion_actions)
    assert type(cfg.after_completion_power_action) is str and cfg.after_completion_power_action == "none"
    saved = io.StringIO()
    YAML().dump(cfg.config.model_dump(), saved)
    assert YAML().load(saved.getvalue())["after_completion_power_action"] == "none"


@pytest.mark.parametrize("arrival", ["during_apply", "before_apply"])
def test_resource_sync_keeps_scheduled_commands_in_fifo(service, monkeypatch, arrival):
    timers = []
    monkeypatch.setattr(events, "later", lambda delay, callback, *args: timers.append((delay, callback, args)))
    monkeypatch.setattr(service, "start", Mock())
    auxiliary = Mock()
    auxiliary.isRunning.return_value = False
    first, second = ["start", "--exit", "4"], ["start", "--exit", "5"]
    if arrival == "during_apply":
        service.auxiliary = ("resources.apply", auxiliary)
        service.command(first)
        assert not timers
    else:
        service.command(first)
        delay, callback, args = timers.pop()
        assert delay == 3000
        service.auxiliary = ("resources.apply", auxiliary)
        callback(*args)
    service.command(second)
    assert service.pending == [first, second] and service.scheduled is None
    service.start.assert_not_called()
    assert not any(event == "warning" for event, _ in service.messages)
    service._aux_finished(auxiliary)
    assert service.scheduled == first and service.pending == [second]
    delay, callback, args = timers.pop()
    assert delay == 3000
    callback(*args)
    service.start.assert_called_once_with()
    assert service.scheduled is None and service.pending == [second]


@pytest.mark.parametrize("replacement", [False, True])
def test_cancelled_start_timer_cannot_start_after_failed_shutdown(service, monkeypatch, replacement):
    from module.config import cfg

    timers = Mock()
    monkeypatch.setattr(events, "later", timers)
    monkeypatch.setattr(service, "start", Mock())
    monkeypatch.setattr(cfg, "flush", Mock(side_effect=OSError("disk full")))
    service.command(["start"])
    delay, old_callback, old_command = timers.call_args.args
    assert delay == 3000
    service.shutdown()
    assert service._shutdown_save_failed and not service.closing and service.scheduled is None
    if replacement:
        service.command(["start"])
        new_delay, new_callback, new_command = timers.call_args.args
        assert new_delay == 3000 and new_command is not old_command
    old_callback(old_command)
    service.start.assert_not_called()
    if replacement:
        assert service.scheduled is new_command
        new_callback(new_command)
        service.start.assert_called_once_with()
    assert service.scheduled is None


@pytest.mark.parametrize("kind", ["task", "battle"])
@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("requested", [False, True])
def test_pause_and_resume_hotkeys_are_idempotent(service, monkeypatch, kind, paused, requested):
    from backend_host.service import BackendService
    from module.automation import auto
    from module.automation.input_handlers import AbstractInput
    from module.config import cfg
    from module.hotkey_listener import global_hotkeys

    providers = []
    monkeypatch.setattr(global_hotkeys, "register", lambda provider: providers.append(provider) or 1)
    monkeypatch.setattr(global_hotkeys, "unregister", Mock())
    handler = AbstractInput()
    handler.is_pause = paused
    monkeypatch.setattr(auto, "input_handler", handler)
    monkeypatch.setattr(auto, "set_pause", handler.set_pause)
    value = BackendService(Mock(), hotkeys=True)
    value.kind = kind
    try:
        callback = providers[0]()[cfg.pause_hotkey if requested else cfg.resume_hotkey]
        callback()
        callback()
        while events.drain():
            pass
        assert handler.is_pause is requested
    finally:
        value.kind = None
        value.shutdown(force=True)


def test_startup_failure_releases_gate_and_preserves_incoming_fifo(service, monkeypatch):
    monkeypatch.setattr(service, "restore_schedules", lambda: None)
    monkeypatch.setattr(service, "check_updates", lambda: None)
    monkeypatch.setattr(service, "check_resources", Mock(side_effect=RuntimeError("resource worker failed")))
    monkeypatch.setattr(events, "later", lambda *args: None)
    service.startup(["start", "--exit", "4"])
    assert not service.startup_pending
    assert service.scheduled == ["start", "--exit", "4"]
    service.startup_pending = True
    service.command(["start", "--exit", "5"])
    assert service.pending == [["start", "--exit", "5"]]
    with pytest.raises(ValueError):
        service._idle()


def test_team_input_rejects_inconsistent_sinner_arrays():
    from module.config import TeamSetting
    from native_contract import STATS, validate_fields

    values = {key: value for key, value in TeamSetting().model_dump().items() if key not in STATS}
    values["sinners_be_select"] = 1
    with pytest.raises(ValueError):
        validate_fields(values, team=True)


def test_settings_while_running_keep_general_settings_but_reject_task_settings(service):
    service.worker = Mock()
    service.patch({"hard_mirror_chance": 2})
    with pytest.raises(ValueError):
        service.patch({"set_EXP_count": 9})
    with pytest.raises(ValueError):
        service.patch({"playcover_port": 1718})


def test_team_draft_keeps_order_and_primary_system_invariant():
    from module.config import TeamSetting

    values = TeamSetting(system_burn=True).model_dump()
    draft = TeamDraft(values)
    assert draft.values["system_burn"] is False
    draft.select_sinner(3, True)
    draft.select_sinner(0, True)
    draft.select_sinner(7, True)
    draft.select_sinner(0, False)
    assert draft.values["sinners_be_select"] == 2
    assert draft.values["sinner_order"][3] == 1 and draft.values["sinner_order"][7] == 2
    draft.set("system_burn", True)
    assert draft.values["system_burn"] is False
    draft.set("avoid_skill_3", True)
    draft.set("prioritize_skill_3", True)
    assert draft.values["avoid_skill_3"] is False
    assert values["chosen_sinners"] == [0] * 12


def test_original_theme_draft_synchronizes_bilingual_ocr_aliases():
    from ruamel.yaml import YAML

    values = YAML().load((SOURCE_ROOT / "assets/config/theme_pack_list.example.yaml").read_text())
    draft = ThemeDraft(values)
    draft._on_weight_changed("nagel", 7, False, False)
    assert draft.config_data["theme_pack_list"]["nag"] == 7
    assert draft.config_data["theme_pack_list_cn"]["钉与锤"] == 7
    draft._on_weight_changed("unconf", 8, False, False)
    assert draft.config_data["theme_pack_list_cn"]["未曾面对"] == 8
    assert values["theme_pack_list"]["nagel"] != 7
