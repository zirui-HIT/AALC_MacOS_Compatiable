"""Malformed resource manifests must not become plans that delete local images."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from module.resource_sync.manifest import ResourceManifest, ResourcePackageEntry
from module.resource_sync.service import ResourceSyncService
from module.resource_sync.source import ResourceSource


@pytest.mark.parametrize("field,value", [("files", "absent"), ("files", None), ("files", {}),
                                        ("files", ""), ("files", False), ("files", 0),
                                        ("schema_version", "absent"), ("schema_version", 999),
                                        ("schema_version", 0), ("schema_version", True),
                                        ("schema_version", 1.0), ("schema_version", "1"),
                                        ("schema_version", None)])
@pytest.mark.parametrize("existing", [False, True])
def test_invalid_remote_manifest_cannot_become_a_deletion_plan(tmp_path, field, value, existing):
    payload = ResourceManifest(manifest_id="remote", package=ResourcePackageEntry(
        "packages/images.7z", "0" * 64, 10, "7z")).to_dict()
    if value == "absent":
        payload.pop(field)
    else:
        payload[field] = value
    response = SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None, json=lambda: payload)
    root = tmp_path / "images"
    image = root / "default/en/keep.png"
    if existing:
        image.parent.mkdir(parents=True)
        image.write_bytes(b"preserve local image")
    service = ResourceSyncService(session=SimpleNamespace(get=Mock(return_value=response)), assets_dir=root,
        state_path=tmp_path / "state.json", temp_dir=tmp_path / "download",
        sources={"GitHub": ResourceSource("GitHub", "https://invalid/manifest.json")})
    with pytest.raises(ValueError):
        result = service.check_for_updates("GitHub")
        plan = service.build_sync_plan(result.remote_manifest)
        pytest.fail(f"Invalid manifest generated a deletion plan: {plan.files_to_delete}")
    if existing:
        assert image.read_bytes() == b"preserve local image"
    else:
        assert not root.exists()
    assert not service.state_path.exists()
    assert not service.temp_dir.exists()


def test_explicit_empty_file_list_remains_a_valid_manifest():
    payload = ResourceManifest(manifest_id="empty").to_dict()
    assert ResourceManifest.from_dict(payload).to_dict() == payload
