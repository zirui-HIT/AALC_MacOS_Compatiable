import pytest

from module.backends.configuration import migrate_backend


@pytest.mark.parametrize("values,platform,backend", [({}, "darwin", "playcover"), ({}, "win32", "windows"), ({"simulator": True, "simulator_type": 0}, "win32", "android_mumu"), ({"simulator": True, "simulator_type": 1}, "win32", "android_adb"), ({"backend": "playcover", "simulator": True}, "win32", "playcover")])
def test_missing_backend_migrates_and_explicit_backend_wins(values, platform, backend):
    migrated = migrate_backend(values, platform)
    assert migrated["backend"] == backend
    if backend == "playcover":
        assert migrated["game_profile"] == "ios_en"
        assert migrated["set_win_size"] == 1080
        assert migrated["simulator"] is False


@pytest.mark.parametrize("invalid", [{"playcover_host": "0.0.0.0"}, {"playcover_port": 0}, {"playcover_capture_method": "mtl"}, {"playcover_logical_height": 1440}])
def test_playcover_invalid_settings_are_rejected(invalid):
    with pytest.raises(ValueError):
        migrate_backend({"backend": "playcover", **invalid})
