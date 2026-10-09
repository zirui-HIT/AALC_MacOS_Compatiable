from pathlib import Path

import pytest

from utils import runtime_paths


def test_paths_are_independent_of_current_directory(tmp_path, monkeypatch):
    before = runtime_paths.resource_path("assets/config/config.example.yaml")
    monkeypatch.chdir(tmp_path)
    assert before == runtime_paths.resource_path("assets/config/config.example.yaml")
    assert before.is_file()
    assert runtime_paths.data_path("config/config.yaml").is_relative_to(runtime_paths.SOURCE_ROOT)


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
