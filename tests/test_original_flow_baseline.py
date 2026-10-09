"""Verify the requested original control flow, allowing only platform substitutions."""
import ast
import hashlib
import json

import pytest

from utils.runtime_paths import SOURCE_ROOT


class PlatformCalls(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ImageUtils" and node.func.attr in {"layout", "layout_point"}):
            return node.args[1]  # Only image-anchor coordinates may differ.
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "get_game_actions"):
            key = {"select_win_rate": "p", "start_turn": "enter", "back": "esc"}.get(node.func.attr)
            if key:
                return ast.Call(func=ast.Attribute(value=ast.Name(id="auto", ctx=ast.Load()),
                    attr="key_press", ctx=ast.Load()), args=[ast.Constant(key)], keywords=[])
        if (isinstance(node.func, ast.Name) and node.func.id == "str" and len(node.args) == 1
                and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Name)
                and node.args[0].func.id == "resource_path"):
            return node.args[0].args[0]
        return node


def digest(source, names=None):
    tree = ast.parse(source)
    if names:
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    tree = PlatformCalls().visit(tree)
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


BASELINE = json.loads((SOURCE_ROOT / "tests/fixtures/original_flow_baseline.json").read_text())


@pytest.mark.parametrize("path", BASELINE["files"])
def test_business_control_flow_matches_original_aalc(path):
    expected = BASELINE["files"][path]
    assert digest((SOURCE_ROOT / path).read_text(), expected.get("functions")) == expected["sha256"]
