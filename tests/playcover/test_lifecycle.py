import plistlib
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
    unrelated.terminate.assert_not_called()
    target.kill.assert_not_called()


def test_invalid_plist_executable_cannot_escape_app(tmp_path):
    app = make_app(tmp_path)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "company.test", "CFBundleExecutable": "../elsewhere"}))
    with pytest.raises(ValueError):
        read_app_identity(app)
