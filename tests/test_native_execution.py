"""Freeze execution bodies with exact, reviewed macOS maintenance exceptions."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((ROOT / "tests/fixtures/native_execution_baseline.json").read_text())
ADAPTATIONS = json.loads((ROOT / "tests/fixtures/native_execution_adaptations.json").read_text())


class ImportsOnly(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None


@pytest.mark.parametrize("path", BASELINE["files"])
def test_current_execution_body_is_unchanged(path):
    source = (ROOT / path).read_text()
    # Reverse only the documented fix/deletion; keep the original hashes intact.
    if path in ADAPTATIONS:
        for change in ADAPTATIONS[path]:
            assert source.count(change["after"]) == 1
            source = source.replace(change["after"], change["before"], 1)
    tree = ast.parse(source)
    if path == "tasks/tools/infinite_battle.py":
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BattleWorker"]
    digest = hashlib.sha256(ast.dump(ImportsOnly().visit(tree), include_attributes=False).encode()).hexdigest()
    assert digest == BASELINE["files"][path]


def test_frontend_imports_only_presentation_and_protocol():
    for path in (ROOT / "frontend_appkit").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            assert not any(name.startswith(("module", "tasks", "backend_host", "cv2", "rapidocr", "PySide", "qfluent")) for name in names), path


def test_no_qt_imports_in_active_source():
    for folder in ("frontend_appkit", "backend_host", "module", "tasks", "utils"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
                assert not any(name.startswith(("PySide", "PyQt", "qfluent", "qframeless", "PIL.ImageQt")) for name in names), path
