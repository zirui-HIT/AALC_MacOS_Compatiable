"""Git provenance and official-update decisions without any network access."""

import copy
import hashlib
import json
import subprocess
from unittest.mock import Mock

import pytest
import requests

from backend_host import git_update
from backend_host.runtime import events
from utils.build_provenance import OFFICIAL_REPOSITORY, build_provenance

REMOTE = "a" * 40
TREE = "b" * 40


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


def api(provenance, files=None, *, sha=REMOTE, tree=TREE, status="ahead", truncated=False):
    files = files if files is not None else provenance["upstream_files"]
    entries = [{"path": path, "mode": value.partition(":")[0], "sha": value.partition(":")[2], "type": "blob"} for path, value in files.items()]
    responses = {"/commits?per_page=1": [{"sha": sha, "commit": {"tree": {"sha": tree}, "message": "Official changes"}}],
                 f"/compare/{provenance['upstream_base']}...{sha}?per_page=1": {"status": status, "merge_base_commit": {"sha": provenance["upstream_base"]}},
                 f"/git/trees/{tree}?recursive=1": {"sha": tree, "truncated": truncated, "tree": entries}}
    return Mock(side_effect=lambda path: copy.deepcopy(responses[path]))


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


@pytest.mark.parametrize("local_tip,status", [(True, "CURRENT"), (False, "LOCAL_AHEAD")])
def test_included_official_commit_never_reports_update_even_for_old_version(checkout, local_tip, status):
    provenance = build_provenance(checkout)
    official = provenance["head"] if local_tip else provenance["upstream_base"]
    get = api(provenance, sha=official)
    assert git_update.check_official_git(provenance, get)["status"] == status
    get.assert_called_once_with("/commits?per_page=1")


def test_new_official_content_on_top_of_custom_branch_is_an_update(checkout):
    provenance = build_provenance(checkout)
    files = {"code.py": blob("new official code\n")}
    result = git_update.check_official_git(provenance, api(provenance, files))
    assert result["status"] == "UPDATE_AVAILABLE"
    assert result["reason"] == "upstream_content_missing"
    assert result["commit"] == REMOTE and result["local_commit"] == provenance["head"]


def test_equivalent_cherry_picked_content_is_not_an_update(checkout):
    (checkout / "code.py").write_text("new official code\n")
    provenance = build_provenance(checkout)
    result = git_update.check_official_git(provenance, api(provenance, {"code.py": blob("new official code\n")}))
    assert result["status"] == "EQUIVALENT"


def test_customized_same_file_without_proof_is_unknown_instead_of_a_false_update(checkout):
    (checkout / "code.py").write_text("custom local code\n")
    provenance = build_provenance(checkout)
    result = git_update.check_official_git(provenance, api(provenance, {"code.py": blob("new official code\n")}))
    assert result["status"] == "UNKNOWN" and result["reason"] == "customized_files"


def test_empty_commits_and_reverted_changes_do_not_report_updates(checkout):
    provenance = build_provenance(checkout)
    assert git_update.check_official_git(provenance, api(provenance))["status"] == "EQUIVALENT"
    same_tree = api(provenance, tree=provenance["head_tree"])
    assert git_update.check_official_git(provenance, same_tree)["reason"] == "same_tree"
    same_tree.assert_called_once()


@pytest.mark.parametrize("status,truncated,reason", [("diverged", False, "history_changed"), ("behind", False, "history_changed"), ("ahead", True, "incomplete_tree")])
def test_uncertain_history_and_incomplete_trees_do_not_report_updates(checkout, status, truncated, reason):
    provenance = build_provenance(checkout)
    result = git_update.check_official_git(provenance, api(provenance, {"code.py": blob("new official code\n")}, status=status, truncated=truncated))
    assert result["status"] == "UNKNOWN" and result["reason"] == reason


def test_git_file_modes_are_compared_in_addition_to_blob_content(checkout):
    provenance = build_provenance(checkout)
    assert git_update.check_official_git(provenance, api(provenance, {"code.py": blob("old official code\n", "100755")}))["status"] == "UPDATE_AVAILABLE"


def test_full_tree_comparison_handles_more_than_300_changed_files(checkout):
    provenance = build_provenance(checkout)
    files = {**provenance["upstream_files"], **{f"file-{number}.py": blob(str(number)) for number in range(301)}}
    result = git_update.check_official_git(provenance, api(provenance, files))
    assert result["status"] == "UPDATE_AVAILABLE"
    assert "301" in result["message"]


def test_frozen_bundle_reads_embedded_provenance_without_git(checkout, tmp_path, monkeypatch):
    provenance = build_provenance(checkout)
    metadata = tmp_path / "native-build.json"
    metadata.write_text(json.dumps(provenance))
    monkeypatch.setattr(git_update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(git_update, "resource_path", lambda _: metadata)
    builder = Mock(side_effect=AssertionError("Git must not run in installed bundles"))
    monkeypatch.setattr(git_update, "build_provenance", builder)
    loaded = git_update.load_provenance()
    assert loaded == provenance
    assert git_update.check_official_git(loaded, api(loaded, sha=loaded["upstream_base"]))["status"] == "LOCAL_AHEAD"
    builder.assert_not_called()


def test_missing_provenance_does_not_guess_or_make_network_calls():
    get = Mock(side_effect=AssertionError("No comparison is possible"))
    assert git_update.check_official_git(None, get)["status"] == "UNKNOWN"
    get.assert_not_called()


def test_worker_reports_network_failure_without_leaking_an_update(checkout, monkeypatch):
    monkeypatch.setattr(git_update, "load_provenance", lambda: build_provenance(checkout))
    monkeypatch.setattr(git_update.requests, "get", Mock(side_effect=requests.Timeout("offline")))
    worker = git_update.GitUpdateCheck()
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "FAILURE"
    assert "超时" in results[0]["message"]


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("status", ["UPDATE_AVAILABLE", "CURRENT", "LOCAL_AHEAD", "EQUIVALENT", "UNKNOWN", "FAILURE"])
def test_host_only_sends_automatic_modal_events_for_proven_updates(automatic, status):
    from backend_host.service import BackendService

    host = BackendService.__new__(BackendService)
    host.publish = Mock()
    host._start_background = Mock()
    host.check_updates(automatic=automatic)
    worker = host._start_background.call_args.args[0]
    worker.result.emit({"status": status, "message": "Git result"})
    worker.finished.emit()
    while events.drain():
        pass
    event = "update" if not automatic or status == "UPDATE_AVAILABLE" else "update_status"
    host.publish.assert_called_once_with(event, {"status": status, "message": "Git result", "automatic": automatic})


def host_without_workers():
    from backend_host.service import BackendService

    host = BackendService.__new__(BackendService)
    host.publish = Mock()
    host._start_background = Mock()
    return host


@pytest.mark.parametrize("promote_after_result", [False, True])
def test_repeated_checks_share_one_worker_and_manual_request_promotes_the_result(promote_after_result):
    host = host_without_workers()
    host.check_updates(automatic=True)
    worker = host._start_background.call_args.args[0]
    if promote_after_result:
        worker.result.emit({"status": "CURRENT"})
        events.drain()
        host.publish.assert_not_called()
    for automatic in (False, False, True):
        host.check_updates(automatic=automatic)
    host._start_background.assert_called_once()
    worker.result.emit({"status": "CURRENT"})
    worker.finished.emit()
    while events.drain():
        pass
    host.publish.assert_called_once_with("update", {"status": "CURRENT", "automatic": False})
    assert host.update_check is None


def test_finished_or_duplicate_results_from_an_old_worker_do_not_affect_a_new_check():
    host = host_without_workers()
    host.check_updates(automatic=False)
    old = host._start_background.call_args.args[0]
    old.result.emit({"status": "CURRENT"})
    old.finished.emit()
    while events.drain():
        pass
    host.check_updates(automatic=True)
    current = host._start_background.call_args.args[0]
    context = host.update_check
    old.finished.emit()
    old.result.emit({"status": "UPDATE_AVAILABLE"})
    while events.drain():
        pass
    assert host.update_check is context
    assert host.publish.call_count == 1
    current.result.emit({"status": "LOCAL_AHEAD"})
    current.finished.emit()
    while events.drain():
        pass
    assert host.publish.call_args.args == ("update_status", {"status": "LOCAL_AHEAD", "automatic": True})
    assert host.update_check is None


def test_failed_update_worker_start_releases_the_check_context_for_retry():
    host = host_without_workers()
    host._start_background.side_effect = RuntimeError("thread start failed")
    with pytest.raises(RuntimeError, match="thread start failed"):
        host.check_updates()
    assert host.update_check is None
    host._start_background.side_effect = None
    host.check_updates()
    assert host.update_check is not None


@pytest.mark.parametrize("cost,status,calls", [(3, "UPDATE_AVAILABLE", 3), (6, "FAILURE", 2)])
def test_http_requests_share_one_time_budget_and_late_results_are_rejected(checkout, monkeypatch, cost, status, calls):
    provenance = build_provenance(checkout)
    get = api(provenance, {"code.py": blob("new official code\n")})
    clock = {"now": 0}
    timeouts = []
    monkeypatch.setattr(git_update.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(git_update, "load_provenance", lambda: provenance)

    def request(url, *, timeout, headers):
        timeouts.append(timeout)
        clock["now"] += cost
        response = Mock()
        response.json.return_value = get(url.removeprefix(git_update.API))
        return response

    monkeypatch.setattr(git_update.requests, "get", request)
    worker = git_update.GitUpdateCheck(10)
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == status
    assert len(timeouts) == calls
    assert [sum(timeout) for timeout in timeouts] == [10 - cost * index for index in range(calls)]
    assert all(0 < timeout[0] <= 3 and timeout[1] > 0 for timeout in timeouts)


def test_exhausted_budget_does_not_start_another_request(monkeypatch):
    worker = git_update.GitUpdateCheck(10)
    worker.deadline = 10
    monkeypatch.setattr(git_update.time, "monotonic", lambda: 10)
    get = Mock()
    monkeypatch.setattr(git_update.requests, "get", get)
    with pytest.raises(requests.Timeout):
        worker.get_json("/commits?per_page=1")
    get.assert_not_called()
