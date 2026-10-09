import sys

import pytest

from utils.archive_7z import create_7z_archive, extract_7z_archive


@pytest.mark.skipif(sys.platform != "darwin", reason="Native macOS libarchive integration")
def test_native_resource_package_round_trip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "template.png").write_bytes(b"fixture")
    archive = create_7z_archive(source, tmp_path / "resource.7z")
    result = extract_7z_archive(archive, tmp_path / "extracted")
    assert (result / "template.png").read_bytes() == b"fixture"


def test_invalid_resource_member_does_not_extract(tmp_path, monkeypatch):
    from utils import archive_7z

    archive = tmp_path / "resource.7z"
    archive.write_bytes(b"fixture")
    monkeypatch.setattr(archive_7z, "_list_7z_members", lambda _: [tmp_path / "outside.png"])
    with pytest.raises(ValueError):
        extract_7z_archive(archive, tmp_path / "extracted")
