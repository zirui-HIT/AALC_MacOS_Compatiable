"""Regressions for the already confirmed persistence and recovery failures."""

import copy
import threading
from time import strptime

import pytest
from ruamel.yaml import YAML


@pytest.fixture
def config(tmp_path):
    from module.config import cfg
    from module.config.config import Config
    from module.config.config_typing import ConfigModel

    value = object.__new__(Config)
    value.yaml = YAML()
    value._lock = threading.RLock()
    value._pending_save = False
    value._save_timer = None
    value._save_interval = 60
    value._writer_event = threading.Event()
    value._defaults = copy.deepcopy(cfg._defaults)
    value.config = ConfigModel(**value._defaults)
    value.example_path = cfg.example_path
    value.config_path = tmp_path / "config.yaml"
    value.backup_path = tmp_path / "backup"
    value.version = cfg.version
    value._save_config()
    yield value
    value.flush()


class StopWriter(BaseException):
    pass


def test_old_config_gets_upstream_timeout_default_and_saves_user_value(config):
    saved = config.yaml.load(config.config_path.read_text())
    saved.pop("task_stall_timeout")
    with config.config_path.open("w") as stream:
        config.yaml.dump(saved, stream)
    config._load_config()
    assert config.task_stall_timeout == 90
    config.set_value("task_stall_timeout", 600)
    config.flush()
    config._load_config()
    assert config.task_stall_timeout == 600


@pytest.fixture
def writer(config):
    stopping = threading.Event()

    class Event(threading.Event):
        def wait(self, timeout=None):
            result = super().wait(timeout)
            if stopping.is_set():
                raise StopWriter()
            return result

    config._writer_event = Event()

    def run():
        try:
            config._writer_loop()
        except StopWriter:
            pass

    thread = threading.Thread(target=run, name="ConfigWriter", daemon=True)
    thread.start()
    yield thread
    config.flush()
    stopping.set()
    config._writer_event.set()
    thread.join(2)
    assert not thread.is_alive()
    config._writer_event.clear()


def test_new_save_during_old_write_reaches_disk(config, writer, monkeypatch):
    entered, release, changing = threading.Event(), threading.Event(), threading.Event()
    changed = threading.Event()
    original = config._load_default_config

    def delayed(*args):
        if threading.current_thread() is writer:
            entered.set()
            assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(config, "_load_default_config", delayed)
    config.set_value("set_EXP_count", 41)
    config._flush_save()
    assert entered.wait(2)

    def change():
        changing.set()
        config.set_value("set_EXP_count", 42)
        config._flush_save()
        changed.set()

    changer = threading.Thread(target=change)
    changer.start()
    try:
        assert changing.wait(1)
        changed.wait(.05)
    finally:
        release.set()
        changer.join(3)
    assert not changer.is_alive()
    config.flush()
    assert YAML().load(config.config_path.read_text())["set_EXP_count"] == 42
    assert not config._pending_save and not config._writer_event.is_set()


def test_host_closes_only_after_inflight_dump_completed(config, writer, monkeypatch):
    import backend_host.service as host

    monkeypatch.setattr(host, "cfg", config)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    original = config.yaml.dump

    def delayed(*args, **kwargs):
        if threading.current_thread() is writer:
            entered.set()
            assert release.wait(3)
        result = original(*args, **kwargs)
        completed.set()
        return result

    service = host.BackendService(lambda event, data: closed.append(completed.is_set()) if event == "closed" else None,
                                  hotkeys=False)
    config.flush()
    completed.clear()
    closed = []
    monkeypatch.setattr(config.yaml, "dump", delayed)
    config.set_value("set_EXP_count", 7)
    config._flush_save()
    assert entered.wait(2)
    timer = threading.Timer(.05, release.set)
    timer.start()
    try:
        service.shutdown()
    finally:
        release.set()
        timer.join()
    assert closed == [True]
    assert YAML().load(config.config_path.read_text())["set_EXP_count"] == 7


@pytest.mark.parametrize("explicit", [False, True])
def test_legacy_completion_migration_uses_stored_values(config, explicit):
    values = copy.deepcopy(config._defaults)
    values.update(config_version=1771965839, after_completion=6, keep_after_completion=True,
                  team1_setting=config.config.teams["1"].model_dump())
    values.pop("teams")
    if explicit:
        values.update(after_completion_actions=["exit_aalc"], after_completion_power_action="none")
    else:
        values.pop("after_completion_actions")
        values.pop("after_completion_power_action")
    with config.config_path.open("w") as stream:
        YAML().dump(values, stream)
    config._load_config()
    expected = ["exit_aalc"] if explicit else ["exit_game", "exit_aalc"]
    assert config.after_completion_actions == expected
    assert YAML().load(config.config_path.read_text())["after_completion_actions"] == expected


@pytest.mark.parametrize("main", [None, "", "[]", "[", 'config_version: "bad"'])
@pytest.mark.parametrize("newest", ["", "[", 'config_version: "bad"'])
def test_recovery_skips_invalid_backups_of_different_kinds(config, main, newest):
    config.config.set_EXP_count = 9
    config.backup_path.mkdir()
    with (config.backup_path / "older.yaml").open("w") as stream:
        YAML().dump(config.config.model_dump(), stream)
    (config.backup_path / "newest.yaml").write_text(newest)
    config.config.set_EXP_count = 1
    if main is None:
        config.config_path.unlink()
    else:
        config.config_path.write_text(main)
    config._load_config()
    assert config.set_EXP_count == 9
    assert YAML().load(config.config_path.read_text())["set_EXP_count"] == 9


@pytest.mark.parametrize("today", ["2026-11-14", "2027-10-14"])
def test_backup_compares_year_month_and_day(config, monkeypatch, today):
    import module.config.config as implementation

    config.backup_path.mkdir()
    (config.backup_path / "older.yaml").write_text("old")
    dates = iter([strptime(today, "%Y-%m-%d"), strptime("2026-10-14", "%Y-%m-%d")])
    monkeypatch.setattr(implementation, "localtime", lambda _: next(dates))
    config.backup_config()
    backups = list(config.backup_path.glob("*.yaml"))
    assert len(backups) == 2
    saved = next(path for path in backups if path.name != "older.yaml")
    assert YAML().load(saved.read_text())["set_EXP_count"] == config.set_EXP_count


def test_failed_async_save_is_retried_by_flush(config, writer, monkeypatch):
    completed = threading.Event()
    original = config._save_config

    def fail_writer():
        if threading.current_thread() is writer:
            completed.set()
            raise OSError("offline test")
        original()

    monkeypatch.setattr(config, "_save_config", fail_writer)
    config.set_value("set_EXP_count", 8)
    config._flush_save()
    assert completed.wait(2)
    config.flush()
    assert YAML().load(config.config_path.read_text())["set_EXP_count"] == 8


def test_temporary_completion_does_not_replace_saved_preferences_or_new_teams(config):
    from module.config import TeamSetting

    config.set_value("keep_after_completion", True)
    config.set_value("after_completion_actions", ["exit_game", "exit_aalc"])
    config.set_runtime_values(keep_after_completion=False, after_completion_actions=[])
    config.set_runtime_values(keep_after_completion=False, after_completion_actions=["exit_aalc"])
    config.set_value("2", TeamSetting(team_number=20, remark_name="retained"), config_obj=config.config.teams)
    config.set_value("set_mirror_count", 17)
    config.flush()
    assert config.after_completion_actions == ["exit_aalc"]  # This run still follows the command.
    saved = YAML().load(config.config_path.read_text())
    assert saved["keep_after_completion"] is True
    assert saved["after_completion_actions"] == ["exit_game", "exit_aalc"]
    assert saved["teams"]["2"]["team_number"] == 20
    config.backup_config()
    assert YAML().load(next(config.backup_path.glob("*.yaml")).read_text())["keep_after_completion"] is True
    config._load_config()
    assert config.keep_after_completion is True
    assert config.config.teams["2"].remark_name == "retained"
    assert config.set_mirror_count == 17
    assert not config.__dict__.get("_runtime_restore_values")


def test_explicit_new_preference_replaces_temporary_override(config):
    config.set_runtime_values(after_completion_actions=["exit_aalc"])
    config.set_value("after_completion_actions", ["exit_game"])
    config.flush()
    config._load_config()
    assert config.after_completion_actions == ["exit_game"]


def test_failed_yaml_serialization_keeps_the_complete_previous_config(config, monkeypatch):
    before = config.config_path.read_bytes()

    def fail_dump(value, stream):
        stream.write("incomplete YAML")
        raise OSError("simulated interrupted write")

    with monkeypatch.context() as patch:
        patch.setattr(config.yaml, "dump", fail_dump)
        with pytest.raises(OSError, match="interrupted write"):
            config._save_config()
    assert config.config_path.read_bytes() == before
    assert not list(config.config_path.parent.glob(".config-*.tmp"))
