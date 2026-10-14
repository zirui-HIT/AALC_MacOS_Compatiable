"""Official Git ancestry/content checks, independent of frozen release logic."""

import html
import json
import subprocess
import sys
import time

import requests

from backend_host.runtime import Signal, WorkerThread
from utils.build_provenance import OFFICIAL_REPOSITORY, SHA, build_provenance
from utils.runtime_paths import SOURCE_ROOT, resource_path

API = "https://api.github.com/repos/" + OFFICIAL_REPOSITORY
WEB = "https://github.com/" + OFFICIAL_REPOSITORY


def load_provenance():
    # An installed bundle must describe its built code, not a nearby checkout.
    if getattr(sys, "frozen", False):
        return json.loads(resource_path("assets/config/native-build.json").read_text())
    return build_provenance(SOURCE_ROOT)


def _valid_files(files):
    return isinstance(files, dict) and all(isinstance(name, str) and isinstance(value, str)
                                         and value.partition(":")[0] in {"100644", "100755", "120000", "160000"}
                                         and SHA.fullmatch(value.partition(":")[2]) for name, value in files.items())


def _valid_provenance(value):
    return (isinstance(value, dict) and value.get("schema") == 1
            and value.get("repository") == OFFICIAL_REPOSITORY
            and isinstance(value.get("head"), str) and SHA.fullmatch(value["head"])
            and isinstance(value.get("ancestors"), list) and value["head"] in value["ancestors"]
            and all(isinstance(sha, str) and SHA.fullmatch(sha) for sha in value["ancestors"])
            and _valid_files(value.get("files")) and _valid_files(value.get("upstream_files")))


def check_official_git(provenance, get_json):
    """Return update only when ancestry and source content prove missing changes."""
    result = {"status": "UNKNOWN", "reason": "missing_provenance", "commit": "", "local_commit": "",
              "version": "", "title": "官方仓库检查", "content": "",
              "message": "无法读取有效的本地 Git 构建记录，未自动判断更新。"}
    if not _valid_provenance(provenance):
        return result
    result["local_commit"] = provenance["head"]
    commits = get_json("/commits?per_page=1")  # GitHub defaults to the official default branch.
    if not isinstance(commits, list) or not commits:
        raise ValueError("官方仓库未返回默认分支提交")
    latest = commits[0]
    commit = latest.get("sha", "")
    tree = latest.get("commit", {}).get("tree", {}).get("sha", "")
    if not SHA.fullmatch(commit) or not SHA.fullmatch(tree):
        raise ValueError("官方仓库提交信息不完整")
    result.update(commit=commit, version=commit[:8])
    if commit in provenance["ancestors"]:
        same = commit == provenance["head"]
        result.update(status="CURRENT" if same else "LOCAL_AHEAD", reason="same_commit" if same else "upstream_included",
                      message="本地 Git 已与官方仓库一致。" if same else "本地 Git 已包含官方最新提交，并保留本地适配，无需更新。")
        return result
    if tree == provenance.get("head_tree"):
        result.update(status="EQUIVALENT", reason="same_tree", message="本地与官方提交内容一致，无需更新。")
        return result
    base = provenance.get("upstream_base", "")
    if not isinstance(base, str) or not SHA.fullmatch(base) or base not in provenance["ancestors"]:
        result.update(reason="missing_upstream_base", message="缺少可验证的官方 Git 基线，无法自动判断更新。")
        return result
    comparison = get_json(f"/compare/{base}...{commit}?per_page=1")
    if comparison.get("status") != "ahead" or comparison.get("merge_base_commit", {}).get("sha") != base:
        result.update(reason="history_changed", message="官方分支与构建基线的历史关系已改变，无法自动判断更新。")
        return result
    # Compare responses cap changed files at 300; a full tree avoids that limit.
    response = get_json(f"/git/trees/{tree}?recursive=1")
    if response.get("truncated") is not False or response.get("sha") != tree:
        result.update(reason="incomplete_tree", message="官方提交文件清单不完整，未自动判断更新。")
        return result
    remote = {entry["path"]: entry["mode"] + ":" + entry["sha"] for entry in response.get("tree", []) if entry.get("type") in {"blob", "commit"}}
    if not _valid_files(remote):
        raise ValueError("官方提交文件信息不完整")
    old, local = provenance["upstream_files"], provenance["files"]
    changed = [name for name in old.keys() | remote.keys() if old.get(name) != remote.get(name)]
    missing = [name for name in changed if local.get(name) == old.get(name) and local.get(name) != remote.get(name)]
    ambiguous = [name for name in changed if local.get(name) not in (old.get(name), remote.get(name))]
    if missing:
        message = f"官方仓库包含本地尚未收录的文件变更（{len(missing)} 项），提交 {commit[:8]}。"
        summary = latest.get("commit", {}).get("message", "").splitlines()[0:1]
        result.update(status="UPDATE_AVAILABLE", reason="upstream_content_missing", title="官方仓库有新提交", message=message,
                      content=f"<p>{html.escape(message)}</p><p>{html.escape(''.join(summary))}</p><p><a href='{WEB}/commit/{commit}'>查看官方提交</a></p>")
    elif ambiguous:
        result.update(reason="customized_files", message="本地定制与官方新提交涉及相同文件，无法自动确认是否缺少改动，未提示更新。")
    else:
        result.update(status="EQUIVALENT", reason="upstream_content_included", message="官方新提交的文件内容已包含在本地构建中，无需更新。")
    return result


class GitUpdateCheck(WorkerThread):
    result = Signal(dict)

    def __init__(self, timeout=10):
        super().__init__()
        self.timeout = timeout
        self.deadline = None

    def get_json(self, path):
        if self.deadline is None:
            self.deadline = time.monotonic() + self.timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Git check time budget exhausted")
        connect = min(3.0, remaining / 2)
        response = requests.get(API + path, timeout=(connect, remaining - connect),
                                headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "AALC-macOS-Git-check"})
        if time.monotonic() >= self.deadline:
            raise requests.Timeout("Git check time budget exhausted")
        response.raise_for_status()
        result = response.json()
        if time.monotonic() >= self.deadline:
            raise requests.Timeout("Git check time budget exhausted")
        return result

    def run(self):
        self.deadline = time.monotonic() + self.timeout
        try:
            try:
                provenance = load_provenance()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                provenance = None
            result = check_official_git(provenance, self.get_json)
        except Exception as exc:
            if isinstance(exc, requests.Timeout):
                message = "连接官方 GitHub 超时，请稍后手动重试。"
            elif isinstance(exc, requests.RequestException):
                response = getattr(exc, "response", None)
                message = f"官方 GitHub 查询失败（HTTP {response.status_code}），请稍后手动重试。" if response is not None else "无法连接官方 GitHub，请检查网络或代理后重试。"
            else:
                message = "官方 Git 数据无法完成比较，请稍后手动重试。"
            result = {"status": "FAILURE", "reason": "check_failed", "commit": "", "local_commit": "", "version": "", "content": "", "message": message}
        self.result.emit(result)
