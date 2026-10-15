"""Configuration log headers must not expose the saved MirrorChyan credential."""

import importlib
import logging

import pytest
from ruamel.yaml import YAML


@pytest.mark.parametrize("version", ["1.0.9", "DEFAULT VERSION"])
def test_new_and_rotated_log_headers_hide_cdk_without_changing_saved_config(monkeypatch, tmp_path, version):
    module = importlib.import_module("module.logger.my_log")
    config_path = tmp_path / "config.yaml"
    version_path = tmp_path / "version.txt"
    config = {"config_version": 1, "mirrorchyan_cdk": "test-private-cdk", "set_win_size": 1080}
    with config_path.open("w") as output:
        YAML().dump(config, output)
    original = config_path.read_bytes()
    version_path.write_text(version)
    project_path = tmp_path / "pyproject.toml"
    project_path.write_text('[project]\nversion = "1.0.9"\n')
    monkeypatch.setattr(module, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(module, "VERSION_PATH", str(version_path))
    monkeypatch.setattr(module, "resource_path", lambda name: project_path, raising=False)
    path = tmp_path / "debug.log"
    handler = module.SettingConcurrentRotatingFileHandler(str(path), maxBytes=100000, backupCount=1)
    record = logging.LogRecord("test-header", logging.INFO, __file__, 1, "Test event", (), None)
    try:
        handler.emit(record)
        handler.doRollover()
        handler.emit(record)
    finally:
        handler.close()
    for log in (path, tmp_path / "debug.log.1"):
        text = log.read_text()
        assert "AALC 版本: 1.0.9," in text
        assert "test-private-cdk" not in text
        assert "'mirrorchyan_cdk': '***'" in text
        assert "'set_win_size': 1080" in text
        assert "Test event" in text
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("relative", [False, True])
def test_packaged_log_paths_remain_stable_across_handlers(monkeypatch, tmp_path, relative):
    module = importlib.import_module("module.logger.my_log")
    monkeypatch.chdir("/")
    path = "tasks/base/retry.py" if relative else str(tmp_path / "tasks/base/retry.py")
    record = logging.LogRecord("test-path", logging.INFO, path, 1, "Test event", (), None)
    for _ in range(3):
        formatter = module.TranslationFormatter("%(pathname)s: %(message)s", no_color=True)
        formatter.project_root = tmp_path
        assert formatter.format(record) == "tasks/base/retry.py: Test event"
        assert record.pathname == path
