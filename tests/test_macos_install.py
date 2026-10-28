"""Installing over a running PyInstaller bundle invalidates its lazy imports."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import build


def test_install_guard_allows_other_apps_and_stopped_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(build.psutil, "process_iter", lambda attrs: [
        SimpleNamespace(info={"pid": 10, "exe": "/usr/bin/python3", "cmdline": ["python3", "build.py"]}),
        SimpleNamespace(info={"pid": 11, "exe": None, "cmdline": None}),
    ])
    build.ensure_bundle_stopped(tmp_path / "AALC.app")


@pytest.mark.parametrize("backend", [False, True])
def test_install_guard_detects_app_even_after_previous_bundle_was_renamed(tmp_path, monkeypatch, backend):
    bundle = tmp_path / "AALC.app"
    executable = str(bundle / "Contents/MacOS/AALC")
    monkeypatch.setattr(build.psutil, "process_iter", lambda attrs: [SimpleNamespace(info={
        "pid": 12, "exe": str(tmp_path / ".AALC-previous.app/Contents/MacOS/AALC"),
        "cmdline": [executable] + (["--backend"] if backend else []),
    })])
    with pytest.raises(SystemExit, match="Quit AALC.*12"):
        build.ensure_bundle_stopped(bundle)


def test_install_guard_runs_before_installed_bundle_is_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build.sys, "platform", "darwin")
    monkeypatch.setattr(build.sys, "argv", ["build.py", "--install"])
    monkeypatch.setattr(build.subprocess, "run", Mock())
    bundles = []

    def guard(bundle):
        bundles.append(bundle)
        if bundle.name == "AALC.app" and bundle.parent == build.Path("/Applications"):
            raise SystemExit("Quit AALC")

    rename = Mock(side_effect=AssertionError("The running bundle must not be moved"))
    monkeypatch.setattr(build, "ensure_bundle_stopped", guard)
    monkeypatch.setattr(build.Path, "exists", lambda path: False)
    monkeypatch.setattr(build.Path, "rename", rename)
    with pytest.raises(SystemExit, match="Quit AALC"):
        build.main()
    assert bundles == [tmp_path / ".runtime/dist.noindex/AALC.app", build.Path("/Applications/AALC.app")]
    rename.assert_not_called()
    assert not any(call.args[0][0] == build.LSREGISTER for call in build.subprocess.run.call_args_list)


def test_build_output_and_signature_check_use_the_unindexed_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build.sys, "platform", "darwin")
    monkeypatch.setattr(build.sys, "argv", ["build.py"])
    guard = Mock()
    run = Mock()
    monkeypatch.setattr(build, "ensure_bundle_stopped", guard)
    monkeypatch.setattr(build.subprocess, "run", run)
    build.main()
    distribution = tmp_path / ".runtime/dist.noindex"
    guard.assert_called_once_with(distribution / "AALC.app")
    command = run.call_args_list[0].args[0]
    assert command[command.index("--distpath") + 1] == str(distribution)
    assert run.call_args_list[1].args[0][-1] == str(distribution / "AALC.app")


@pytest.mark.parametrize("failure", [None, OSError("unavailable"), build.subprocess.CalledProcessError(1, "lsregister")])
def test_registration_only_changes_the_build_and_installed_entries(monkeypatch, failure):
    run = Mock(side_effect=[failure, None])
    monkeypatch.setattr(build.subprocess, "run", run)
    bundle = build.Path("/project/.runtime/dist.noindex/AALC.app")
    destination = build.Path("/Applications/AALC.app")
    build.register_installed_bundle(bundle, destination)
    assert [call.args[0] for call in run.call_args_list] == [
        [build.LSREGISTER, "-u", str(bundle)],
        [build.LSREGISTER, "-f", str(destination)],
    ]
    assert [call.kwargs["check"] for call in run.call_args_list] == [False, True]


def test_each_update_backs_up_all_presets_and_weights_without_modifying_user_data(tmp_path, monkeypatch):
    from utils import runtime_paths

    source = tmp_path / "user/config"
    weights = source / "theme_pack_weight/team2.yaml"
    weights.parent.mkdir(parents=True)
    weights.write_text("team 2 weights")
    (source / "config.yaml").write_text("teams: {'1': {}, '2': {}}")
    monkeypatch.setattr(build, "ROOT", tmp_path / "build")
    monkeypatch.setattr(runtime_paths, "data_path", lambda path: tmp_path / "user" / path)
    first = build.backup_user_config()
    second = build.backup_user_config()
    assert first != second
    for directory in (first, second):
        assert (directory / "config.yaml").read_bytes() == (source / "config.yaml").read_bytes()
        assert (directory / "theme_pack_weight/team2.yaml").read_bytes() == weights.read_bytes()
