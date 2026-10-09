import sys
from unittest.mock import Mock

import pytest
from PIL import Image

from tools import playcover_mirror_resume


def diagnostic_session(monkeypatch, tmp_path, active=False):
    from module.backends import factory
    from module.config import cfg
    from utils import runtime_paths
    from utils.path_manager import path_manager

    monkeypatch.setattr(runtime_paths, "SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"backend": "playcover"}))
    monkeypatch.setattr(path_manager, "initialize_paths", Mock())
    session = Mock()
    session.capture.return_value.image = Image.new("RGB", (16, 9))
    session.transport.bundle_id = "com.ProjectMoon.LimbusCompany"
    monkeypatch.setattr(factory, "get_playcover_session", lambda: session)
    monkeypatch.setattr(sys, "argv", ["mirror-resume", "--output", "diagnostics"] + (["--resume-current"] if active else []))
    return session


def test_default_diagnostic_is_read_only(monkeypatch, tmp_path, capsys):
    session = diagnostic_session(monkeypatch, tmp_path)
    assert playcover_mirror_resume.main() == 0
    assert (tmp_path / "diagnostics/before.png").is_file()
    assert '"active": false' in capsys.readouterr().out
    assert not session.input.mock_calls
    session.start_game.assert_not_called()
    session.stop_game.assert_not_called()
    session.disconnect.assert_called_once()


def test_resume_refuses_unknown_or_home_page_before_any_task(monkeypatch, tmp_path):
    from module.automation import auto
    from tasks.mirror import mirror

    session = diagnostic_session(monkeypatch, tmp_path, active=True)
    monkeypatch.setattr(auto, "take_screenshot", Mock())
    monkeypatch.setattr(auto, "find_element", Mock(return_value=None))
    task = Mock()
    monkeypatch.setattr(mirror, "Mirror", task)
    with pytest.raises(SystemExit) as exc:
        playcover_mirror_resume.main()
    assert exc.value.code == 2
    task.assert_not_called()
    session.start_game.assert_not_called()
    session.disconnect.assert_called_once()
