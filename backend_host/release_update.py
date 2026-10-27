"""Published official releases, independent of default-branch activity."""

import html
import json
import subprocess
import sys
import time
from urllib.parse import quote

import requests
from markdown_it import MarkdownIt
from packaging.version import InvalidVersion, Version

from backend_host.runtime import Signal, WorkerThread
from utils.build_provenance import OFFICIAL_REPOSITORY, SHA, build_provenance
from utils.runtime_paths import SOURCE_ROOT, resource_path

API = "https://api.github.com/repos/" + OFFICIAL_REPOSITORY
WEB = "https://github.com/" + OFFICIAL_REPOSITORY


def load_provenance():
    # Installed checks describe their bundled code, never a nearby checkout.
    if getattr(sys, "frozen", False):
        return json.loads(resource_path("assets/config/native-build.json").read_text())
    return build_provenance(SOURCE_ROOT)


def _valid_ancestry(value):
    return (
        isinstance(value, dict)
        and value.get("schema") == 1
        and value.get("repository") == OFFICIAL_REPOSITORY
        and isinstance(value.get("head"), str)
        and SHA.fullmatch(value["head"])
        and isinstance(value.get("ancestors"), list)
        and value["head"] in value["ancestors"]
        and all(isinstance(sha, str) and SHA.fullmatch(sha) for sha in value["ancestors"])
    )


def check_official_release(current_version, provenance, get_json):
    """Notify only for a published stable release not already included locally."""
    result = {
        "status": "CURRENT",
        "reason": "no_release",
        "version": "",
        "release_url": "",
        "title": "官方版本检查",
        "content": "",
        "message": "官方仓库尚无正式 Release。",
    }
    try:
        release = get_json("/releases/latest")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return result
        raise
    if not isinstance(release, dict):
        raise ValueError("官方 Release 信息格式错误")
    if release.get("draft") is True or release.get("prerelease") is True:
        return result
    if release.get("draft") is not False or release.get("prerelease") is not False or not release.get("published_at"):
        raise ValueError("官方 Release 发布信息不完整")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("官方 Release 未提供版本标签")
    latest = Version(tag.strip().lstrip("Vv"))
    if latest.is_prerelease or latest.is_devrelease:
        return result
    result.update(version=tag, release_url=WEB + "/releases/tag/" + quote(tag, safe=""))
    if _valid_ancestry(provenance):
        # The upstream pyproject version can lag actual releases. Resolve only
        # this release's tag; unrelated PRs/default-branch commits never count.
        commit = get_json("/commits/" + quote(tag, safe=""))
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError("官方 Release 标签未返回有效提交")
        if sha in provenance["ancestors"]:
            result.update(reason="release_included", message=f"本地已包含官方最新 Release {tag}，无需更新。")
            return result
    try:
        local = Version(current_version.strip().lstrip("Vv"))
    except (AttributeError, InvalidVersion):
        result.update(
            status="UNKNOWN", reason="unknown_local_version", message="无法确定本地版本，未自动判断 Release 更新。"
        )
        return result
    if latest <= local:
        result.update(reason="version_current", message=f"本地版本 {current_version} 已不低于官方最新 Release {tag}。")
        return result
    message = f"官方发布了新版本 {tag}。"
    notes = release.get("body") or ""
    if not isinstance(notes, str):
        raise ValueError("官方 Release 更新说明格式错误")
    # AppKit's HTML reader should not fetch images or execute raw release HTML.
    content = MarkdownIt("commonmark", {"html": False, "breaks": True}).disable("image").render(notes)
    result.update(
        status="UPDATE_AVAILABLE",
        reason="new_release",
        title="官方发布新版本",
        message=message,
        content=f"<p>{html.escape(message)}</p>" + content,
    )
    return result


class ReleaseUpdateCheck(WorkerThread):
    result = Signal(dict)

    def __init__(self, current_version, timeout=10):
        super().__init__()
        self.current_version = current_version
        self.timeout = timeout
        self.deadline = None

    def get_json(self, path):
        if self.deadline is None:
            self.deadline = time.monotonic() + self.timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("Release check time budget exhausted")
        connect = min(3.0, remaining / 2)
        response = requests.get(
            API + path,
            timeout=(connect, remaining - connect),
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "AALC-macOS-Release-check",
            },
        )
        if time.monotonic() >= self.deadline:
            raise requests.Timeout("Release check time budget exhausted")
        response.raise_for_status()
        result = response.json()
        if time.monotonic() >= self.deadline:
            raise requests.Timeout("Release check time budget exhausted")
        return result

    def run(self):
        self.deadline = time.monotonic() + self.timeout
        try:
            try:
                provenance = load_provenance()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                provenance = None
            result = check_official_release(self.current_version, provenance, self.get_json)
        except Exception as exc:
            if isinstance(exc, requests.Timeout):
                message = "连接官方 GitHub 超时，请稍后手动重试。"
            elif isinstance(exc, requests.RequestException):
                response = getattr(exc, "response", None)
                message = (
                    f"官方 Release 查询失败（HTTP {response.status_code}），请稍后手动重试。"
                    if response is not None
                    else "无法连接官方 GitHub，请检查网络或代理后重试。"
                )
            else:
                message = "官方 Release 数据无法完成比较，请稍后手动重试。"
            result = {
                "status": "FAILURE",
                "reason": "check_failed",
                "version": "",
                "release_url": "",
                "content": "",
                "message": message,
            }
        self.result.emit(result)
