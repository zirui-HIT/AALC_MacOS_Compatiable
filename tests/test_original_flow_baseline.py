"""Verify original decisions with explicit platform/optimization exceptions."""
import ast
import hashlib
import json

import pytest

from utils.runtime_paths import SOURCE_ROOT


class PlatformCalls(ast.NodeTransformer):
    # 2026-10-10: user explicitly requested deleting White Gossypium checks.
    @staticmethod
    def is_gossypium_filter(node):
        return isinstance(node, ast.If) and any(
            (isinstance(part, ast.Attribute) and part.attr == "not_skip_whitegossypium")
            or (isinstance(part, ast.Constant) and part.value == "white_gossypium")
            for part in ast.walk(node.test)
        )

    def visit_If(self, node):
        return None if self.is_gossypium_filter(node) else self.generic_visit(node)

    def visit_For(self, node):
        had_filter = any(self.is_gossypium_filter(stmt) for stmt in node.body)
        node = self.generic_visit(node)
        if had_filter and not any(
            isinstance(part, ast.Name) and part.id == "bbox" and isinstance(part.ctx, ast.Load)
            for stmt in node.body for part in ast.walk(stmt)
        ):
            node.body = [stmt for stmt in node.body if not (
                isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "bbox")]
        return node

    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None

    def visit_Call(self, node):
        node = self.generic_visit(node)
        # 2026-10-10: explicitly authorized reuse of fresh, unchanged observations.
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "auto" and node.func.attr == "take_screenshot"):
            node.keywords = [kw for kw in node.keywords if not (
                kw.arg == "max_age" and isinstance(kw.value, ast.Constant) and kw.value.value == 0.85)]
        if isinstance(node.func, ast.Name) and node.func.id == "retry":
            node.keywords = [kw for kw in node.keywords if not (
                kw.arg == "reuse_screenshot" and isinstance(kw.value, ast.Constant) and kw.value.value is True)]
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ImageUtils" and node.func.attr in {"layout", "layout_point"}):
            return node.args[1]  # Only image-anchor coordinates may differ.
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "get_game_actions"):
            if node.func.attr == "select_defense":
                return ast.Call(func=ast.Attribute(value=ast.Name(id="auto", ctx=ast.Load()),
                    attr="mouse_click", ctx=ast.Load()), args=node.args, keywords=node.keywords)
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
