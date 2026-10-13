"""IPC, cancellation, control ordering and UI data invariants without game input."""

import json
import os
import subprocess
import sys
import threading
import time
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
