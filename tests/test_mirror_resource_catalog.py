"""Bundled image rules must be available to the unchanged shop task."""

import pytest

from tasks import mirror
from utils.runtime_paths import resource_path


@pytest.mark.parametrize("name,sample", [
    ("must_purchase", "carmilla.png"),
    ("must_be_abandoned", "leave2_white_gossypium.png"),
    ("fusion_result", "bleed_hard_1.png"),
])
def test_shop_image_rule_catalogs_are_loaded(name, sample):
    images = getattr(mirror, name)
    assert images
    assert f"mirror/shop/{name}/{sample}" in images
    assert all(resource_path(f"assets/images/default/share/{path}").is_file() for path in images)


@pytest.mark.parametrize("name,sample", [
    ("must_purchase", "carmilla.png"),
    ("must_be_abandoned", "leave2_white_gossypium.png"),
    ("fusion_result", "bleed_hard_1.png"),
])
def test_resource_cache_refresh_updates_existing_shop_aliases(monkeypatch, tmp_path, name, sample):
    import shutil

    from module.automation import auto
    from utils import image_catalog
    from utils.image_utils import ImageUtils

    monkeypatch.setattr(image_catalog, "data_path", lambda path: tmp_path / path)
    monkeypatch.setattr("utils.image_utils.data_path", lambda path: tmp_path / path)
    images = getattr(mirror, name)
    previous = list(images)
    prefix = f"mirror/shop/{name}"
    directory = tmp_path / f"resources/images/default/share/{prefix}"
    directory.mkdir(parents=True)
    probe = directory / "fresh_catalog_probe.png"
    override = directory / sample
    shutil.copyfile(resource_path(f"assets/images/default/share/{prefix}/{sample}"), probe)
    shutil.copyfile(probe, override)
    try:
        auto.clear_img_cache()
        assert getattr(mirror, name) is images
        assert images.count(f"{prefix}/{sample}") == 1
        assert f"{prefix}/{probe.name}" in images
        assert ImageUtils.resolve_path("default/share", f"{prefix}/{probe.name}") == probe
        probe.unlink()
        override.unlink()
        auto.clear_img_cache()
        assert getattr(mirror, name) is images
        assert images == previous
    finally:
        probe.unlink(missing_ok=True)
        override.unlink(missing_ok=True)
        image_catalog.refresh_shop_image_catalogs()


@pytest.mark.parametrize("name,sample", [
    ("must_purchase", "carmilla.png"),
    ("must_be_abandoned", "leave0_fragment1.png"),
    ("fusion_result", "bleed_hard_1.png"),
])
def test_successful_sync_does_not_restore_deleted_bundled_rules(monkeypatch, tmp_path, name, sample):
    import shutil

    from module.resource_sync import ResourceSyncService
    from module.resource_sync.manifest import ResourceManifest
    from module.resource_sync.service import ResourceCheckResult, ResourceCheckStatus
    from module.resource_sync.source import ResourceSource
    from utils import image_catalog, image_utils

    monkeypatch.setattr(image_catalog, "data_path", lambda path: tmp_path / path)
    monkeypatch.setattr(image_utils, "data_path", lambda path: tmp_path / path)
    images = getattr(mirror, name)
    previous = {key: list(getattr(mirror, key)) for key in ("must_purchase", "must_be_abandoned", "fusion_result")}
    relative = f"default/share/mirror/shop/{name}/{sample}"
    overlay = tmp_path / "resources/images" / relative
    overlay.parent.mkdir(parents=True)
    shutil.copyfile(resource_path(f"assets/images/{relative}"), overlay)
    state_path = tmp_path / "config/image_resource_state.json"
    service = ResourceSyncService(assets_dir=tmp_path / "resources/images", state_path=state_path,
                                  temp_dir=tmp_path / "cache/resource-sync")
    manifest = ResourceManifest.from_dict({"schema_version": 1, "generated_at": "2026-10-14T00:00:00Z",
                                          "manifest_id": "deleted-rule", "files": []})
    source = ResourceSource("local", "https://invalid/manifest.json")
    check = ResourceCheckResult(ResourceCheckStatus.UPDATE_AVAILABLE, source=source, remote_manifest=manifest)
    try:
        result = service.apply_sync_plan(check_result=check, sync_plan=service.build_sync_plan(manifest))
        assert result.deleted_count == 1
        assert not overlay.exists()
        assert not image_utils.ImageUtils.resolve_path("default/share", f"mirror/shop/{name}/{sample}").exists()
        assert getattr(mirror, name) is images
        assert f"mirror/shop/{name}/{sample}" not in images
        # Reopening the app must retain deletions using the persisted sync state.
        image_catalog._read_synced_image_tree.cache_clear()
        image_catalog.refresh_shop_image_catalogs()
        assert f"mirror/shop/{name}/{sample}" not in images
    finally:
        for key, values in previous.items():
            getattr(mirror, key)[:] = values


@pytest.mark.parametrize("state", [None, "{", "[]", '{}', '{"last_applied_manifest_id": null}'])
def test_initial_or_invalid_sync_state_keeps_bundled_images(monkeypatch, tmp_path, state):
    from utils import image_catalog, image_utils

    monkeypatch.setattr(image_catalog, "data_path", lambda path: tmp_path / path)
    monkeypatch.setattr(image_utils, "data_path", lambda path: tmp_path / path)
    state_path = tmp_path / "config/image_resource_state.json"
    if state is not None:
        state_path.parent.mkdir(parents=True)
        state_path.write_text(state)
    sample = "mirror/shop/must_purchase/carmilla.png"
    assert image_utils.ImageUtils.resolve_path("default/share", sample) == resource_path(f"assets/images/default/share/{sample}")


@pytest.mark.parametrize("name,sample", [
    ("must_purchase", "carmilla.png"),
    ("must_be_abandoned", "leave0_fragment1.png"),
    ("fusion_result", "bleed_hard_1.png"),
])
def test_nested_resource_rules_keep_their_relative_paths(monkeypatch, tmp_path, name, sample):
    import shutil

    from module.automation import auto
    from utils import image_catalog, image_utils

    monkeypatch.setattr(image_catalog, "data_path", lambda path: tmp_path / path)
    monkeypatch.setattr(image_utils, "data_path", lambda path: tmp_path / path)
    images = getattr(mirror, name)
    previous = list(images)
    prefix = f"mirror/shop/{name}"
    relative = f"{prefix}/nested/{sample}"
    probe = tmp_path / f"resources/images/default/share/{relative}"
    probe.parent.mkdir(parents=True)
    shutil.copyfile(resource_path(f"assets/images/default/share/{prefix}/{sample}"), probe)
    try:
        auto.clear_img_cache()
        assert getattr(mirror, name) is images
        assert f"{prefix}/{sample}" in images
        assert relative in images
        assert image_utils.ImageUtils.resolve_path("default/share", relative) == probe
    finally:
        images[:] = previous
