"""Read-only Git provenance shared by source checks and macOS packaging."""

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

OFFICIAL_REPOSITORY = "KIYI671/AhabAssistantLimbusCompany"
SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(root, *args):
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, check=True, timeout=10).stdout


def _official_remote(url):
    value = url.strip().rstrip("/").removesuffix(".git")
    if value.startswith("git@github.com:"):
        return value.partition(":")[2].lower() == OFFICIAL_REPOSITORY.lower()
    parsed = urlsplit(value)
    return parsed.hostname == "github.com" and parsed.path.strip("/").lower() == OFFICIAL_REPOSITORY.lower()


def _tree(root, ref):
    result = {}
    for entry in _git(root, "ls-tree", "-rz", ref).split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            mode, kind, sha = metadata.decode("ascii").split()
            if kind in {"blob", "commit"}:
                result[os.fsdecode(path)] = mode + ":" + sha
    return result


def _working_file(path):
    if path.is_symlink():
        content, mode = os.fsencode(os.readlink(path)), "120000"
    elif path.is_file():
        content = path.read_bytes()
        mode = "100755" if path.stat().st_mode & stat.S_IXUSR else "100644"
    else:
        return None
    digest = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
    return mode + ":" + digest


def build_provenance(root):
    """Snapshot Git history and changed source files without changing refs/index."""
    root = Path(root).resolve()
    if Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel")).strip()).resolve() != root:
        raise ValueError("The application directory is not the Git repository root")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    ancestors = _git(root, "rev-list", "HEAD").decode().splitlines()
    files = _tree(root, "HEAD")
    modified = _git(root, "diff", "--no-ext-diff", "--name-only", "-z", "HEAD").split(b"\0")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
    changes = {os.fsdecode(path) for path in modified + untracked if path}
    for name in changes:
        value = _working_file(root / name)
        if value is None:
            files.pop(name, None)
        else:
            files[name] = value
    base = ""
    for remote in _git(root, "remote").decode().splitlines():
        if not _official_remote(_git(root, "remote", "get-url", remote).decode()):
            continue
        try:
            ref = _git(root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD").decode().strip()
        except subprocess.CalledProcessError:
            ref = f"refs/remotes/{remote}/main"
        try:
            base = _git(root, "merge-base", "HEAD", ref).decode().strip()
        except subprocess.CalledProcessError:
            continue
        if SHA.fullmatch(base):
            break
    return {"schema": 1, "repository": OFFICIAL_REPOSITORY, "head": head,
            "head_tree": _git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
            "ancestors": ancestors, "upstream_base": base,
            "upstream_files": _tree(root, base) if base else {}, "files": files,
            "dirty": bool(changes)}
