"""Known resource path escape and published package URL regressions."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from module.resource_sync.manifest import ResourceFileEntry, ResourceManifest, ResourcePackageEntry
from module.resource_sync.service import ResourceCheckResult, ResourceCheckStatus, ResourceSyncPlan, ResourceSyncService
from module.resource_sync.source import ResourceSource
from scripts.sync_image_resource_repo import sync_resource_repo
from utils.file_utils import sha256_file
from utils.archive_7z import create_7z_archive


@pytest.mark.parametrize("path", ["../bundle.7z", "/tmp/escaped.png", "default/../../escaped.png",
                                 "C:/escaped.png", "default\\..\\escaped.png"])
def test_image_manifest_rejects_paths_outside_resource_tree(path):
    with pytest.raises(ValueError):
        ResourceFileEntry.from_dict({"path": path, "sha256": "0" * 64, "size": 1})


@pytest.mark.parametrize("operation", ["add", "delete", "plan"])
def test_sync_rejects_symlink_targets_before_reading_or_modifying_them(tmp_path, operation):
    root = tmp_path / "images"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"preserve")
    (root / "linked.png").symlink_to(outside)
    entry = ResourceFileEntry("linked.png", hashlib.sha256(b"preserve").hexdigest(), 8)
    manifest = ResourceManifest(manifest_id="known", files=[entry])
    service = ResourceSyncService(assets_dir=root, state_path=tmp_path / "state.json", temp_dir=tmp_path / "cache")
    check = ResourceCheckResult(ResourceCheckStatus.UPDATE_AVAILABLE,
                                source=ResourceSource("local", "https://invalid/manifest.json"),
                                remote_manifest=manifest)
    with pytest.raises(ValueError):
        if operation == "plan":
            service.build_sync_plan(manifest)
        else:
            plan = ResourceSyncPlan(files_to_add=[entry]) if operation == "add" else ResourceSyncPlan(files_to_delete=[entry.path])
            service.apply_sync_plan(check_result=check, sync_plan=plan)
    assert outside.read_bytes() == b"preserve"
    assert not service.state_path.exists()
    assert not service.temp_dir.exists()


@pytest.mark.parametrize("relative", ["../outside.png", "/tmp/outside.png"])
def test_manually_constructed_deletion_plan_cannot_escape(tmp_path, relative):
    service = ResourceSyncService(assets_dir=tmp_path / "images", state_path=tmp_path / "state.json",
                                  temp_dir=tmp_path / "cache")
    check = ResourceCheckResult(ResourceCheckStatus.UPDATE_AVAILABLE,
                                source=ResourceSource("local", "https://invalid/manifest.json"),
                                remote_manifest=ResourceManifest(manifest_id="known"))
    with pytest.raises(ValueError):
        service.apply_sync_plan(check_result=check, sync_plan=ResourceSyncPlan(files_to_delete=[relative]))


def test_extracted_source_must_remain_inside_extraction_tree(tmp_path):
    root = tmp_path / "extracted"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"preserve")
    (root / "linked.png").symlink_to(outside)
    with pytest.raises(ValueError):
        ResourceSyncService._image_path(root, "linked.png")
    assert outside.read_bytes() == b"preserve"


def test_normal_7z_sync_still_adds_and_deletes_resources(tmp_path, monkeypatch):
    source = tmp_path / "source"
    image = source / "default/share/sample.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10), "red").save(image)
    entry = ResourceFileEntry("default/share/sample.png", sha256_file(image), image.stat().st_size)
    archive = tmp_path / "images.7z"
    create_7z_archive(source, archive)
    package = ResourcePackageEntry("packages/images.7z", sha256_file(archive), archive.stat().st_size, "7z")
    manifest = ResourceManifest(manifest_id="known", files=[entry], package=package)
    root = tmp_path / "images"
    root.mkdir()
    (root / "obsolete.png").write_bytes(b"old")
    service = ResourceSyncService(assets_dir=root, state_path=tmp_path / "state.json", temp_dir=tmp_path / "cache")
    monkeypatch.setattr(service, "_download_resource_package", lambda source, metadata, target: shutil.copyfile(archive, target))
    check = ResourceCheckResult(ResourceCheckStatus.UPDATE_AVAILABLE,
                                source=ResourceSource("local", "https://invalid/manifest.json"),
                                remote_manifest=manifest)
    result = service.apply_sync_plan(check_result=check, sync_plan=service.build_sync_plan(manifest))
    assert (result.downloaded_count, result.deleted_count) == (1, 1)
    assert (root / entry.path).read_bytes() == image.read_bytes()
    assert not (root / "obsolete.png").exists()


@pytest.mark.parametrize("manifest_path,packages_dir", [("manifest.json", "packages"),
                                                        ("nested/manifest.json", "packages"),
                                                        ("nested/manifest.json", "custom/发布包")])
def test_published_manifest_references_actual_package_location(tmp_path, manifest_path, packages_dir):
    package = tmp_path / "images.7z"
    source_tree = tmp_path / "source"
    source_tree.mkdir()
    (source_tree / "sample.png").write_bytes(b"package content")
    create_7z_archive(source_tree, package)
    source = tmp_path / "manifest.json"
    original = ResourceManifest(manifest_id="known", package=ResourcePackageEntry(
        "packages/images.7z", sha256_file(package), package.stat().st_size, "7z")).to_json()
    source.write_text(original)
    repository = tmp_path / "repository"
    repository.mkdir()
    target_manifest, target_package = sync_resource_repo(source, package, repository,
                                                       Path(manifest_path), Path(packages_dir))
    published = ResourceManifest.from_dict(json.loads(target_manifest.read_text()))
    assert (target_manifest.parent / published.package.path).resolve() == target_package.resolve()
    assert target_package.read_bytes() == package.read_bytes()
    assert source.read_text() == original
    assert published.package.sha256 == sha256_file(target_package)
    if manifest_path == "manifest.json" and packages_dir == "packages":
        assert target_manifest.read_text() == original


def test_publishing_manifest_without_package_preserves_existing_format(tmp_path):
    manifest = tmp_path / "manifest.json"
    text = json.dumps(ResourceManifest(manifest_id="known").to_dict())
    manifest.write_text(text)
    package = tmp_path / "images.7z"
    package.write_bytes(b"unused")
    repository = tmp_path / "repository"
    repository.mkdir()
    target, _ = sync_resource_repo(manifest, package, repository)
    assert target.read_text() == text
