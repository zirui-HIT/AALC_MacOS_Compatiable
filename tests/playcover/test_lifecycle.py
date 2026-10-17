import plistlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from module.backends.playcover.lifecycle import PlayCoverLifecycle, read_app_identity


def make_app(tmp_path):
    app = tmp_path / "Game with spaces.app"
    app.mkdir()
    (app / "Game").write_bytes(b"fixture")
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "company.test", "CFBundleExecutable": "Game"}))
    return app


def test_actual_app_identity_and_open_argument_list(tmp_path):
    app = make_app(tmp_path)
    identity = read_app_identity(app)
    assert identity.bundle_id == "company.test"
    lifecycle = PlayCoverLifecycle(str(app), "company.test")
    with patch("subprocess.run") as run:
        lifecycle.start()
    run.assert_called_once_with(["/usr/bin/open", "-a", str(app)], check=True, capture_output=True)
    with pytest.raises(ValueError):
        PlayCoverLifecycle(str(app), "other")


def test_only_verified_game_executable_is_terminated(tmp_path):
    lifecycle = PlayCoverLifecycle(str(make_app(tmp_path)))
    unrelated = Mock(info={"exe": "/Applications/Other.app/Game"})
    target = Mock(info={"exe": str(lifecycle.identity.executable)})
    target.exe.return_value = str(lifecycle.identity.executable)
    with patch("psutil.process_iter", return_value=[unrelated, target]):
        lifecycle.stop_verified_process()
    target.terminate.assert_called_once()
    target.wait.assert_called_once_with(timeout=10)
    unrelated.terminate.assert_not_called()
    target.kill.assert_not_called()


def test_term_exit_during_identity_check_is_already_stopped(tmp_path):
    import psutil

    lifecycle = PlayCoverLifecycle(str(make_app(tmp_path)))
    target = Mock()
    target.exe.side_effect = psutil.NoSuchProcess(42)
    with patch.object(lifecycle, "process", return_value=target):
        lifecycle.stop_verified_process(terminate=False)
    target.terminate.assert_not_called()
    target.wait.assert_not_called()


def test_term_wait_timeout_does_not_force_kill(tmp_path):
    import psutil

    lifecycle = PlayCoverLifecycle(str(make_app(tmp_path)))
    target = Mock()
    target.exe.return_value = str(lifecycle.identity.executable)
    target.wait.side_effect = psutil.TimeoutExpired(10)
    with patch.object(lifecycle, "process", return_value=target), pytest.raises(TimeoutError):
        lifecycle.stop_verified_process(terminate=False)
    target.terminate.assert_not_called()
    target.kill.assert_not_called()


def test_term_wait_allows_playcover_shutdown_delay(tmp_path):
    lifecycle = PlayCoverLifecycle(str(make_app(tmp_path)))
    target = Mock()
    target.exe.return_value = str(lifecycle.identity.executable)

    def wait(*, timeout):
        import psutil

        if timeout <= 5.1:
            raise psutil.TimeoutExpired(timeout)

    target.wait.side_effect = wait
    with patch.object(lifecycle, "process", return_value=target):
        lifecycle.stop_verified_process(terminate=False)
    target.wait.assert_called_once_with(timeout=10)
    target.terminate.assert_not_called()
    target.kill.assert_not_called()


def test_invalid_plist_executable_cannot_escape_app(tmp_path):
    app = make_app(tmp_path)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "company.test", "CFBundleExecutable": "../elsewhere"}))
    with pytest.raises(ValueError):
        read_app_identity(app)


def test_migrated_game_path_is_resolved_on_this_mac(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    workspace = Mock()
    workspace.URLForApplicationWithBundleIdentifier_.return_value.path.return_value = str(app)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(NSWorkspace=Mock(sharedWorkspace=Mock(return_value=workspace))))
    with patch("subprocess.run") as run:
        lifecycle = PlayCoverLifecycle("/Users/previous-user/Old Game.app", "company.test")
    assert lifecycle.identity == read_app_identity(app)
    workspace.URLForApplicationWithBundleIdentifier_.assert_called_once_with("company.test")
    run.assert_not_called()


@pytest.mark.parametrize("registered", [False, True])
def test_migrated_path_requires_matching_registered_identity(tmp_path, monkeypatch, registered):
    app = make_app(tmp_path)
    workspace = Mock()
    workspace.URLForApplicationWithBundleIdentifier_.return_value = Mock(path=Mock(return_value=str(app))) if registered else None
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(NSWorkspace=Mock(sharedWorkspace=Mock(return_value=workspace))))
    with pytest.raises(ValueError):
        PlayCoverLifecycle("/Users/previous-user/Old Game.app", "other.game")


def test_registered_bundle_can_launch_without_saved_app_path(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    workspace = Mock()
    workspace.URLForApplicationWithBundleIdentifier_.return_value.path.return_value = str(app)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(NSWorkspace=Mock(sharedWorkspace=Mock(return_value=workspace))))
    lifecycle = PlayCoverLifecycle(bundle_id="company.test")
    with patch("subprocess.run") as run:
        lifecycle.start()
    workspace.URLForApplicationWithBundleIdentifier_.assert_called_once_with("company.test")
    assert lifecycle.identity == read_app_identity(app)
    run.assert_called_once_with(["/usr/bin/open", "-a", str(app)], check=True, capture_output=True)


@pytest.mark.parametrize("registered", [False, True])
def test_unresolved_or_wrong_registered_identity_never_launches(tmp_path, monkeypatch, registered):
    app = make_app(tmp_path)
    workspace = Mock()
    workspace.URLForApplicationWithBundleIdentifier_.return_value = Mock(path=Mock(return_value=str(app))) if registered else None
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(NSWorkspace=Mock(sharedWorkspace=Mock(return_value=workspace))))
    lifecycle = PlayCoverLifecycle(bundle_id="other.game")
    with patch("subprocess.run") as run, pytest.raises(ValueError):
        lifecycle.start()
    run.assert_not_called()
