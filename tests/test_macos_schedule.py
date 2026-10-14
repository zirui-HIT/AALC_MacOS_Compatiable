"""Validate launchd registration and the existing scheduled task entry without game input."""

import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from utils import schedule_helper


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_helper.os, "getuid", lambda: 501, raising=False)
    helper = schedule_helper.ScheduleHelper_MacOS()
    helper.directory = tmp_path / "schedules"
    loaded = set()
    calls = []

    def launchctl(*arguments, check=True):
        calls.append(arguments)
        command = arguments[0]
        if command == "print":
            return SimpleNamespace(returncode=0 if arguments[1] in loaded else 113)
        if command == "bootstrap":
            with open(arguments[2], "rb") as file:
                definition = plistlib.load(file)
            loaded.add(f"{arguments[1]}/{definition['Label']}")
        elif command == "bootout":
            loaded.remove(arguments[1])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper, "_launchctl", launchctl)
    return helper, loaded, calls


@pytest.mark.parametrize("frozen", [False, True])
def test_source_and_bundle_use_resident_protocol_and_only_run_at_calendar_time(scheduler, monkeypatch, frozen):
    helper, loaded, calls = scheduler
    monkeypatch.setattr(schedule_helper.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(schedule_helper.sys, "executable", "/Applications/With Spaces/AALC" if frozen else "/venv/bin/python")
    for name, hour, slot in [("AALC Daily Task", 8, "autodaily"), ("AALC Daily Task2", 20, "autodaily2")]:
        helper.register_daily_task(name, f"start --exit {slot}", hour, 0)
        path = helper.directory / f"{helper._labels[name]}.plist"
        definition = plistlib.loads(path.read_bytes())
        assert definition["ProgramArguments"] == ["/bin/sh", "-c",
            f"printf '%s\\n' 'start|--exit|{slot}' | /usr/bin/nc -w 2 -G 1 127.0.0.1 62333"]
        assert definition["StartCalendarInterval"] == {"Hour": hour, "Minute": 0}
        assert "RunAtLoad" not in definition and "KeepAlive" not in definition
        assert definition["LimitLoadToSessionType"] == "Aqua"
        assert definition["WorkingDirectory"] == "/"
        assert path.stat().st_mode & 0o777 == 0o600
    assert len(loaded) == 2


def test_repeated_registration_update_and_removal_are_idempotent(scheduler):
    helper, loaded, calls = scheduler
    helper.unregister_task("AALC Daily Task")
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len([call for call in calls if call[0] == "bootstrap"]) == 1
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 9, 30)
    assert len([call for call in calls if call[0] == "bootstrap"]) == 2
    assert len([call for call in calls if call[0] == "bootout"]) == 1
    helper.unregister_task("AALC Daily Task")
    helper.unregister_task("AALC Daily Task")
    assert not loaded and not list(helper.directory.glob("*.plist"))


def test_saved_job_is_loaded_again_after_a_new_login_session(scheduler):
    helper, loaded, calls = scheduler
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    loaded.clear()
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len(loaded) == 1
    assert len([call for call in calls if call[0] == "bootstrap"]) == 2


def test_bootstrap_failure_is_reported_and_can_be_retried(scheduler, monkeypatch):
    helper, loaded, calls = scheduler
    original = helper._launchctl

    def fail(*arguments, check=True):
        if arguments[0] == "bootstrap":
            raise subprocess.CalledProcessError(5, arguments, stderr="fixture registration denied")
        return original(*arguments, check=check)

    monkeypatch.setattr(helper, "_launchctl", fail)
    with pytest.raises(subprocess.CalledProcessError):
        helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert not loaded and not list(helper.directory.glob("*.tmp"))
    monkeypatch.setattr(helper, "_launchctl", original)
    helper.register_daily_task("AALC Daily Task", "start --exit autodaily", 8, 0)
    assert len(loaded) == 1
