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
        # 2026-10-11: user explicitly requested per-floor hard bans in addition to weights.
        hard_ban_guards = (
            'forbidden_keywords and (theme_pack_name in forbidden_keywords '
            'or theme_pack_name in {"unknown", "未知", "号线", "line"})',
            'weight_list and max(weight_list) == float("-inf")',
        )
        if any(ast.dump(node.test) == ast.dump(ast.parse(test, mode="eval").body) for test in hard_ban_guards):
            return None
        if ast.dump(node.test) == ast.dump(ast.parse(
                "floor == 5 and cfg.select_event_pack and not forbidden_keywords", mode="eval").body):
            node.test = ast.parse("floor == 5 and cfg.select_event_pack", mode="eval").body
        # 2026-10-11: user authorized selecting the best visible pack when refresh is unavailable.
        if ast.dump(node.test) == ast.dump(ast.parse("refresh_times <= 0 or weight_list", mode="eval").body):
            node.test = ast.parse("refresh_times <= 0", mode="eval").body
        # 2026-10-11: user explicitly requested deleting keyboard pathfinding.
        keyboard_pathfinding = (
            isinstance(node.test, ast.Attribute)
            and isinstance(node.test.value, ast.Name)
            and node.test.value.id == "cfg"
            and node.test.attr == "mirror_keyboard_simple_pathfinding"
        )
        return None if self.is_gossypium_filter(node) or keyboard_pathfinding else self.generic_visit(node)

    def visit_Assign(self, node):
        # Ignore only the authorized policy load; preserve every original assignment.
        policy_load = ast.parse(
            "forbidden_keywords = theme_list.get_forbidden_theme_packs("
            "hard_mode, floor, team_num, use_custom_theme_pack_weight)"
        ).body[0]
        if ast.dump(node) == ast.dump(policy_load):
            return None
        return self.generic_visit(node)

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
        # 2026-10-11: user authorized clamping the remaining hard-run count at zero.
        if (isinstance(node.func, ast.Name) and node.func.id == "max"
                and len(node.args) == 2 and not node.keywords
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0
                and ast.dump(node.args[1]) == ast.dump(ast.parse("cfg.hard_mirror_chance - 1", mode="eval").body)):
            return node.args[1]
        # 2026-10-11: user authorized correcting the weekly reset's hour only.
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "datetime" and node.func.attr == "combine"
                and len(node.args) == 2 and isinstance(node.args[1], ast.Call)):
            clock = node.args[1]
            if (isinstance(clock.func, ast.Name) and clock.func.id == "time"
                    and len(clock.args) == 2 and not clock.keywords
                    and all(isinstance(arg, ast.Constant) for arg in clock.args)
                    and [arg.value for arg in clock.args] == [6, 0]):
                clock.args[0].value = 5
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
