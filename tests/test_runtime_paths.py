from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import runtime_paths


def test_paths_are_independent_of_current_directory(tmp_path, monkeypatch):
    before = runtime_paths.resource_path("assets/config/config.example.yaml")
    writable = runtime_paths.data_path("config/config.yaml")
    monkeypatch.chdir(tmp_path)
    assert before == runtime_paths.resource_path("assets/config/config.example.yaml")
    assert before.is_file()
    assert writable == runtime_paths.data_path("config/config.yaml")


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside"])
def test_paths_reject_directory_escape(path):
    with pytest.raises(ValueError):
        runtime_paths.resource_path(path)
    with pytest.raises(ValueError):
        runtime_paths.data_path(path)


def test_frozen_bundle_separates_resources_and_portable_data(monkeypatch):
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", "/workspace/dist/AALC.app/Contents/MacOS/AALC")
    assert runtime_paths.application_root() == Path("/workspace/dist")


@pytest.fixture
def mac_directories(tmp_path, monkeypatch):
    monkeypatch.delenv("AALC_DATA_ROOT", raising=False)
    monkeypatch.setattr(runtime_paths.sys, "platform", "darwin")
    paths = {1: tmp_path / "Library/Application Support", 2: tmp_path / "Library/Caches",
             3: tmp_path / "Library", 4: tmp_path / "Pictures"}
    monkeypatch.setitem(runtime_paths.sys.modules, "Foundation", SimpleNamespace(
        NSApplicationSupportDirectory=1, NSCachesDirectory=2, NSLibraryDirectory=3,
        NSPicturesDirectory=4, NSUserDomainMask=1,
        NSSearchPathForDirectoriesInDomains=lambda kind, domain, expand: [str(paths[kind])],
        NSTemporaryDirectory=lambda: str(tmp_path / "system-temp"),
    ))
    return tmp_path


def test_macos_roots_follow_current_user_without_creating_directories(mac_directories, monkeypatch):
    for executable in ("/Applications/AALC.app/Contents/MacOS/AALC",
                       "/Volumes/Other Mac/Moved.app/Contents/MacOS/AALC"):
        monkeypatch.setattr(runtime_paths.sys, "executable", executable)
        monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
        roots = runtime_paths.runtime_directories()
        assert roots == {
            "data": mac_directories / "Library/Application Support/io.aalc.PlayCover",
            "cache": mac_directories / "Library/Caches/io.aalc.PlayCover",
            "logs": mac_directories / "Library/Logs/io.aalc.PlayCover",
            "tmp": mac_directories / "system-temp/io.aalc.PlayCover",
            "screenshots": mac_directories / "Pictures/AALC",
        }
    assert not list(mac_directories.iterdir())


def test_prepare_routes_files_and_preserves_system_temp_for_backend(mac_directories, monkeypatch):
    roots = runtime_paths.runtime_directories()
    monkeypatch.setattr(runtime_paths, "DIRECTORIES", roots)
    monkeypatch.setattr(runtime_paths, "DATA_ROOT", roots["data"])
    monkeypatch.setenv("TMPDIR", str(mac_directories / "system-temp"))
    monkeypatch.setenv("XDG_CACHE_HOME", "before")
    monkeypatch.setenv("PYINSTALLER_CONFIG_DIR", "before")
    runtime_paths.prepare_runtime()
    assert runtime_paths.data_path("config/config.yaml") == roots["data"] / "config/config.yaml"
    assert runtime_paths.data_path("templates/custom.png") == roots["data"] / "templates/custom.png"
    for name in ("cache", "logs", "tmp", "screenshots"):
        assert runtime_paths.data_path(f"{name}/file") == roots[name] / "file"
        assert roots[name].is_dir()
    assert runtime_paths.os.environ["TMPDIR"] == str(mac_directories / "system-temp")
    assert runtime_paths.runtime_directories() == roots


@pytest.mark.parametrize("override", ["", ".runtime", "relative/data"])
def test_relative_or_empty_override_is_rejected(override, monkeypatch):
    monkeypatch.setenv("AALC_DATA_ROOT", override)
    with pytest.raises(ValueError, match="absolute path"):
        runtime_paths.runtime_directories()


def test_explicit_override_keeps_all_writes_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AALC_DATA_ROOT", str(tmp_path))
    roots = runtime_paths.runtime_directories()
    monkeypatch.setattr(runtime_paths, "DIRECTORIES", roots)
    monkeypatch.setattr(runtime_paths, "DATA_ROOT", roots["data"])
    monkeypatch.setenv("TMPDIR", "before")
    monkeypatch.setenv("XDG_CACHE_HOME", "before")
    monkeypatch.setenv("PYINSTALLER_CONFIG_DIR", "before")
    runtime_paths.prepare_runtime()
    for name in ("config", "templates", "resources", "models", "cache", "logs", "tmp", "screenshots"):
        assert runtime_paths.data_path(name) == tmp_path / name
    assert runtime_paths.os.environ["TMPDIR"] == str(tmp_path / "tmp")
