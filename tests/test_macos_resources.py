import logging
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from utils.runtime_paths import resource_path


def test_packaged_ocr_models_work_offline_with_fixed_text():
    from module.ocr import ocr
    from module.ocr.ocr import OCR

    assert callable(ocr.run)  # Importing the implementation cannot replace the public facade.

    image = Image.new("RGB", (640, 120), "white")
    font = ImageFont.truetype(str(resource_path("assets/app/fonts/ChineseFont.ttf")), 48)
    ImageDraw.Draw(image).text((20, 20), "Win Rate", fill="black", font=font)
    with patch("socket.create_connection", side_effect=AssertionError("OCR must stay offline")):
        result = OCR(logging.getLogger("test.ocr")).run(image)
    assert "winrate" in "".join(result.txts or []).replace(" ", "").lower()


def test_ios_overlay_precedes_english_and_shared_resources(tmp_path, monkeypatch):
    from module.config import cfg
    from utils import image_utils
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    monkeypatch.setattr(image_utils, "data_path", lambda path: tmp_path / "data" / path)
    monkeypatch.setattr(image_utils, "resource_path", lambda path: tmp_path / "resources" / path)
    for path in ("assets/ios_en/default/button.png", "assets/images/default/en/button.png", "assets/images/default/share/button.png"):
        full = tmp_path / "resources" / path
        full.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9), "red").save(full)
    path_manager.initialize_paths()
    path_manager.set_theme("default")
    assert image_utils.ImageUtils.existing_image_paths("button.png") == ["default/ios_en", "default/en"]
    _, profile = image_utils.ImageUtils.load_image("button.png", resize=False, return_path=True)
    assert profile == "default/ios_en"
    (tmp_path / "resources/assets/ios_en/default/button.png").unlink()
    _, profile = image_utils.ImageUtils.load_image("button.png", resize=False, return_path=True)
    assert profile == "default/en"
    (tmp_path / "resources/assets/images/default/en/button.png").unlink()
    _, profile = image_utils.ImageUtils.load_image("button.png", resize=False, return_path=True)
    assert profile == "default/share"


def test_mac_updater_never_selects_or_installs_windows_assets(monkeypatch):
    from module.update import check_update

    monkeypatch.setattr(check_update.sys, "platform", "darwin")
    thread = check_update.UpdateThread(1, False)
    assert thread.get_download_url_from_assets([{"name": "AALC.7z", "browser_download_url": "https://invalid/Windows.7z"}]) is None
    import pytest

    with patch("subprocess.Popen") as spawn, patch("requests.get") as request:
        with pytest.raises(NotImplementedError):
            check_update.update("https://invalid/Windows.7z")
        with pytest.raises(NotImplementedError):
            check_update.start_update("Windows.7z")
    spawn.assert_not_called()
    request.assert_not_called()


def test_updated_general_images_remain_below_ios_overlay(tmp_path, monkeypatch):
    from module.config import cfg
    from utils import image_utils
    from utils.path_manager import path_manager

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_en"}))
    monkeypatch.setattr(image_utils, "data_path", lambda path: tmp_path / "data" / path)
    monkeypatch.setattr(image_utils, "resource_path", lambda path: tmp_path / "bundled" / path)
    overlay = tmp_path / "bundled/assets/ios_en/default/button.png"
    bundled = tmp_path / "bundled/assets/images/default/en/button.png"
    updated = tmp_path / "data/resources/images/default/en/button.png"
    for path, color in ((overlay, "green"), (bundled, "red"), (updated, "blue")):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9), color).save(path)
    path_manager.initialize_paths()
    path_manager.set_theme("default")
    _, profile = image_utils.ImageUtils.load_image("button.png", resize=False, return_path=True)
    assert profile == "default/ios_en"
    assert image_utils.ImageUtils.resolve_path(profile, "button.png") == overlay
    overlay.unlink()
    _, profile = image_utils.ImageUtils.load_image("button.png", resize=False, return_path=True)
    assert profile == "default/en"
    assert image_utils.ImageUtils.resolve_path(profile, "button.png") == updated


def test_macos_image_sync_does_not_require_windows_software_update(monkeypatch):
    from unittest.mock import Mock

    from app import resource_sync_coordinator as coordinator

    window = Mock()
    version = Mock(is_prerelease=False, is_current_version_latest=False)
    monkeypatch.setattr(coordinator.sys, "platform", "darwin")
    assert coordinator.ResourceSyncCoordinator._is_resource_sync_version_ready(
        window, coordinator.UpdateStatus.FAILURE, version, notify_user=False,
    )
    monkeypatch.setattr(coordinator.sys, "platform", "win32")
    assert not coordinator.ResourceSyncCoordinator._is_resource_sync_version_ready(
        window, coordinator.UpdateStatus.FAILURE, version, notify_user=False,
    )
