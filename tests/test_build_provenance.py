"""Build snapshots record actual source content without modifying Git refs."""

import hashlib
import json
import subprocess

import pytest

from utils.build_provenance import OFFICIAL_REPOSITORY, build_provenance


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def blob(value, mode="100644"):
    content = value.encode()
    return mode + ":" + hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


@pytest.fixture
def checkout(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Update test")
    git(tmp_path, "config", "user.email", "update-test@example.invalid")
    (tmp_path / "code.py").write_text("old official code\n")
    git(tmp_path, "add", "code.py")
    git(tmp_path, "commit", "-m", "Official baseline")
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "remote", "add", "origin", "https://github.com/" + OFFICIAL_REPOSITORY)
    git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    git(tmp_path, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    (tmp_path / "macos.py").write_text("local adaptation\n")
    git(tmp_path, "add", "macos.py")
    git(tmp_path, "commit", "-m", "Local adaptation")
    return tmp_path


def test_build_provenance_records_ancestry_and_actual_dirty_content_without_changing_refs(checkout):
    refs = git(checkout, "show-ref")
    (checkout / "code.py").write_text("changed local code\n")
    (checkout / "new.py").write_text("new local file\n")
    provenance = build_provenance(checkout)
    assert provenance["head"] == git(checkout, "rev-parse", "HEAD")
    assert provenance["upstream_base"] in provenance["ancestors"]
    assert provenance["files"]["code.py"] == blob("changed local code\n")
    assert provenance["files"]["new.py"] == blob("new local file\n")
    assert provenance["upstream_files"]["code.py"] == blob("old official code\n")
    assert provenance["dirty"]
    assert git(checkout, "show-ref") == refs


def test_build_records_only_reviewed_releases_applied_in_current_history(checkout):
    applied = {"tag": "V1.6.1", "sha": "b" * 40,
               "local_commit": git(checkout, "rev-parse", "HEAD"), "scope": "selected_macos_fixes"}
    path = checkout / "assets/config/official-release-adaptations.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema": 1, "repository": OFFICIAL_REPOSITORY,
        "releases": [applied, {**applied, "local_commit": "c" * 40},
                     {**applied, "sha": "invalid"}, {**applied, "scope": "unreviewed"}, None],
    }))
    metadata = build_provenance(checkout)
    assert metadata["adapted_releases"] == [applied]
    assert applied["sha"] not in metadata["ancestors"]


@pytest.mark.parametrize("invalid", [[], {"schema": 0}, {"schema": 1, "repository": "other/repo", "releases": []}])
def test_unknown_review_manifest_does_not_suppress_updates(checkout, invalid):
    path = checkout / "assets/config/official-release-adaptations.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(invalid))
    assert build_provenance(checkout)["adapted_releases"] == []
