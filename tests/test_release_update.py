"""Stable release decisions and notification lifecycle without network access."""

import copy
import json
from unittest.mock import Mock, call

import pytest
import requests

from backend_host import release_update
from backend_host.runtime import events
from utils.build_provenance import OFFICIAL_REPOSITORY

HEAD = "a" * 40
RELEASE_COMMIT = "b" * 40


def release(tag="V1.6.0", **overrides):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "published_at": "2026-09-10T15:00:25Z",
        "body": "### Changes\n- Fixed a bug",
        **overrides,
    }


def provenance(included=False):
    return {
        "schema": 1,
        "repository": OFFICIAL_REPOSITORY,
        "head": HEAD,
        "ancestors": [HEAD, RELEASE_COMMIT] if included else [HEAD],
    }


def api(data=None, *, sha=RELEASE_COMMIT):
    payload = release() if data is None else data

    def get(path):
        if path == "/releases/latest":
            return copy.deepcopy(payload)
        if path == "/commits/" + payload["tag_name"]:
            return {"sha": sha}
        raise AssertionError("Unrelated PR, default-branch or tree request: " + path)

    return Mock(side_effect=get)


@pytest.mark.parametrize(
    "local,tag,status",
    [
        ("1.6.0", "V1.6.0", "CURRENT"),
        ("V1.6.1", "v1.6.0", "CURRENT"),
        ("1.6.9", "V1.6.10", "UPDATE_AVAILABLE"),
        ("1.6.0", "V1.7.0", "UPDATE_AVAILABLE"),
        ("1.6.0rc1", "V1.6.0", "UPDATE_AVAILABLE"),
    ],
)
def test_release_versions_use_numeric_comparison(local, tag, status):
    get = api(release(tag))
    result = release_update.check_official_release(local, None, get)
    assert result["status"] == status
    assert result["version"] == tag
    assert result["release_url"] == release_update.WEB + "/releases/tag/" + tag
    get.assert_called_once_with("/releases/latest")


def test_release_already_in_local_history_does_not_repeat_despite_old_display_version():
    get = api()
    result = release_update.check_official_release("1.0.9", provenance(True), get)
    assert result["status"] == "CURRENT" and result["reason"] == "release_included"
    assert get.call_args_list == [call("/releases/latest"), call("/commits/V1.6.0")]


def test_only_the_published_release_tag_is_compared_never_branch_or_pr_activity():
    get = api()
    result = release_update.check_official_release("1.0.9", provenance(), get)
    assert result["status"] == "UPDATE_AVAILABLE" and result["reason"] == "new_release"
    assert "Fixed a bug" in result["content"]
    assert get.call_args_list == [call("/releases/latest"), call("/commits/V1.6.0")]


@pytest.mark.parametrize(
    "overrides",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "V1.7.0-beta.1"},
        {"tag_name": "V1.7.0.dev1"},
    ],
)
def test_drafts_and_prereleases_do_not_notify(overrides):
    get = api(release(**overrides))
    assert release_update.check_official_release("1.0.9", provenance(), get)["status"] == "CURRENT"
    get.assert_called_once_with("/releases/latest")


@pytest.mark.parametrize(
    "overrides",
    [
        {"published_at": None},
        {"tag_name": ""},
        {"tag_name": None},
        {"tag_name": "not-a-version"},
        {"draft": "false"},
    ],
)
def test_malformed_release_metadata_is_not_treated_as_an_update(overrides):
    with pytest.raises((ValueError, TypeError)):
        release_update.check_official_release("1.0.9", provenance(), api(release(**overrides)))


@pytest.mark.parametrize("invalid", [[], "invalid", None])
def test_non_object_release_is_rejected(invalid):
    with pytest.raises(ValueError):
        release_update.check_official_release("1.0.9", None, Mock(return_value=invalid))


def test_no_published_release_is_a_quiet_current_result():
    error = requests.HTTPError(response=Mock(status_code=404))
    result = release_update.check_official_release("1.0.9", None, Mock(side_effect=error))
    assert result["status"] == "CURRENT" and result["reason"] == "no_release"


@pytest.mark.parametrize("invalid", ["not-a-version", None])
def test_unknown_local_version_does_not_guess_an_update(invalid):
    result = release_update.check_official_release(invalid, None, api())
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize("sha", [None, "", "not-a-commit"])
def test_bad_release_tag_resolution_is_rejected(sha):
    with pytest.raises(ValueError):
        release_update.check_official_release("1.0.9", provenance(), api(sha=sha))


def test_notes_render_markdown_without_fetching_images_or_accepting_raw_html():
    body = "## Notes\n- **Fixed**\n![badge](https://example.invalid/image.png)\n<script>alert(1)</script>"
    result = release_update.check_official_release("1.0.9", None, api(release(body=body)))
    assert "<strong>Fixed</strong>" in result["content"]
    assert "<img" not in result["content"] and "<script>" not in result["content"]


def test_frozen_bundle_reads_its_own_provenance_without_git(tmp_path, monkeypatch):
    metadata = tmp_path / "native-build.json"
    metadata.write_text(json.dumps(provenance(True)))
    monkeypatch.setattr(release_update.sys, "frozen", True, raising=False)
    monkeypatch.setattr(release_update, "resource_path", lambda _: metadata)
    builder = Mock(side_effect=AssertionError("Installed checks must not run Git"))
    monkeypatch.setattr(release_update, "build_provenance", builder)
    assert release_update.load_provenance() == provenance(True)
    builder.assert_not_called()


@pytest.mark.parametrize(
    "error,message",
    [
        (requests.Timeout("offline"), "超时"),
        (requests.HTTPError(response=Mock(status_code=403)), "403"),
        (requests.ConnectionError("offline"), "无法连接"),
        (ValueError("malformed response"), "Release 数据"),
    ],
)
def test_worker_failure_never_claims_an_update(monkeypatch, error, message):
    monkeypatch.setattr(release_update, "load_provenance", lambda: None)
    monkeypatch.setattr(release_update.requests, "get", Mock(side_effect=error))
    worker = release_update.ReleaseUpdateCheck("1.0.9")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "FAILURE"
    assert message in results[0]["message"]


def test_missing_git_metadata_still_allows_release_version_comparison(monkeypatch):
    monkeypatch.setattr(release_update, "load_provenance", Mock(side_effect=FileNotFoundError()))
    response = Mock()
    response.json.return_value = release("V1.7.0")
    monkeypatch.setattr(release_update.requests, "get", Mock(return_value=response))
    worker = release_update.ReleaseUpdateCheck("1.6.0")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "UPDATE_AVAILABLE"


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("status", ["UPDATE_AVAILABLE", "CURRENT", "UNKNOWN", "FAILURE"])
def test_host_only_sends_automatic_modal_events_for_proven_updates(automatic, status):
    from backend_host.service import BackendService

    host = BackendService.__new__(BackendService)
    host.publish = Mock()
    host._start_background = Mock()
    host.check_updates(automatic=automatic)
    worker = host._start_background.call_args.args[0]
    worker.result.emit({"status": status, "message": "Release result"})
    worker.finished.emit()
    while events.drain():
        pass
    event = "update" if not automatic or status == "UPDATE_AVAILABLE" else "update_status"
    host.publish.assert_called_once_with(event, {"status": status, "message": "Release result", "automatic": automatic})


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
    current.result.emit({"status": "CURRENT"})
    current.finished.emit()
    while events.drain():
        pass
    assert host.publish.call_args.args == ("update_status", {"status": "CURRENT", "automatic": True})
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


@pytest.mark.parametrize("cost,status,calls", [(3, "UPDATE_AVAILABLE", 2), (6, "FAILURE", 2), (10, "FAILURE", 1)])
def test_http_calls_share_one_deadline_and_late_results_are_rejected(monkeypatch, cost, status, calls):
    clock, timeouts = {"now": 0}, []
    get = api()
    monkeypatch.setattr(release_update.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(release_update, "load_provenance", lambda: provenance())

    def request(url, *, timeout, headers):
        timeouts.append(timeout)
        clock["now"] += cost
        response = Mock()
        response.json.return_value = get(url.removeprefix(release_update.API))
        return response

    monkeypatch.setattr(release_update.requests, "get", request)
    worker = release_update.ReleaseUpdateCheck("1.0.9", 10)
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == status
    assert len(timeouts) == calls
    assert [sum(timeout) for timeout in timeouts] == [10 - cost * index for index in range(calls)]
    assert all(0 < timeout[0] <= 3 and timeout[1] > 0 for timeout in timeouts)


def test_exhausted_budget_starts_no_additional_request(monkeypatch):
    worker = release_update.ReleaseUpdateCheck("1.0.9", 10)
    worker.deadline = 10
    monkeypatch.setattr(release_update.time, "monotonic", lambda: 10)
    get = Mock()
    monkeypatch.setattr(release_update.requests, "get", get)
    with pytest.raises(requests.Timeout):
        worker.get_json("/releases/latest")
    get.assert_not_called()
