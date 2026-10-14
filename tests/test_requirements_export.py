"""Keep native dependencies in the CI lockfile export without running uv."""

import runpy
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export-requirements-from-uv-lock.py"


def test_export_preserves_mac_and_other_platform_markers(monkeypatch, tmp_path):
    exported = (
        "requests==2.32.5\n"
        "pyobjc-framework-cocoa==11.1 ; sys_platform == 'darwin'\n"
        "pyobjc-framework-vision==11.1 ; sys_platform == 'darwin'\n"
        "evdev==1.9.2 ; 'linux' in sys_platform\n"
        "pywin32==311 ; sys_platform == 'win32'\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, exported, "")))
    runpy.run_path(str(SCRIPT))["main"]()
    assert (tmp_path / "requirements.txt").read_text() == exported


def test_failed_export_preserves_existing_requirements(monkeypatch, tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("existing dependencies\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 7, "", "export failed")))
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT))["main"]()
    assert error.value.code == 7
    assert path.read_text() == "existing dependencies\n"
