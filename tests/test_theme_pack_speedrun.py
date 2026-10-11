"""Exercise the configured pack policy through the real matcher and selection loop."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from ruamel.yaml import YAML

from utils.runtime_paths import SOURCE_ROOT


def preset():
    return YAML(typ="safe").load((SOURCE_ROOT / "assets/config/theme_pack_list.speedrun.yaml").read_text())


@pytest.mark.parametrize("language,texts,expected", [
    ("zh_cn", ["身无分文的徒"], "赌徒"),
    ("zh_cn", ["去・海物辺"], "海边"),
    ("zh_cn", ["肉斬音断"], "骨断"),
    ("zh_cn", ["肉斬音断", "復刻"], "骨断&&复刻"),
    ("zh_cn", ["20区的奇迹", "復刻"], "区的奇&&复刻"),
    ("zh_cn", ["20区的奇迹"], "区的奇"),
    ("zh_cn", ["肉斬骨断", "復刻"], "骨断&&复刻"),
    ("zh_cn", ["時間殺人時間", "復刻"], "时间杀人&&复刻"),
    ("en", ["Miracle", "in District 20", "BokGak"], "miracle&&bokgak"),
    ("en", ["Miracle in District 20"], "miracle"),
    ("en", ["Yield My Flesh to Claim Their Bones", "BokGak"], "bones&&bokgak"),
    ("en", ["Timekilling Time", "BokGak"], "time&&bokgak"),
    ("zh_cn", ["1号綫"], "1号线"),
    ("zh_cn", ["2号綫"], "2号线"),
    ("zh_cn", ["3号綫"], "3号线"),
    ("zh_cn", ["4号綫 - 第3区段"], "4号线&&3区段"),
    ("zh_cn", ["4号綫 - 第4区段"], "4号线&&4区段"),
    ("zh_cn", ["5号綫"], "5号线"),
    ("zh_cn", ["3号綫", "終点站"], "3号线&&终点"),
    ("zh_cn", ["1号綫", "瘋狂"], "1号线&&疯狂"),
    ("zh_cn", ["1号綫", "MADNESS"], "1号线&&疯狂"),
    ("zh_cn", ["1号綫", "MAPNESS"], "1号线&&疯狂"),
    ("zh_cn", ["3号綫", "TERMINUS"], "3号线&&终点"),
    ("en", ["Line 1"], "line 1"),
    ("en", ["Line 2"], "line 2"),
    ("en", ["Line 3"], "line 3"),
    ("en", ["Line 4 Section#3"], "line 4&&section&&#3"),
    ("en", ["Line 4", "Section #4"], "line 4&&section&&#4"),
    ("en", ["Line 5"], "line 5"),
])
def test_specific_pack_keywords_match_before_family(monkeypatch, language, texts, expected):
    from module.automation import Automation
    from module.config import cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn"}))
    data = preset()
    suffix = "_cn" if language == "zh_cn" else ""
    weights = {**data[f"theme_pack_list{suffix}"], **data[f"theme_pack_list_hard{suffix}"]}
    matcher = Automation.__new__(Automation)
    result = matcher._find_target_in_ocr_dict(weights, {text: (100, 100 + i) for i, text in enumerate(texts)})
    assert result.text == expected
    assert result.value == weights[expected]


def test_compound_keyword_requires_every_part_in_one_crop(monkeypatch):
    from module.automation import Automation
    from module.config import cfg

    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn"}))
    matcher = Automation.__new__(Automation)
    assert matcher.find_str_in_text("区的奇&&复刻", {"20区的奇迹": (1, 2)}) is False
    assert matcher.find_str_in_text("区的奇&&复刻", {"肉斬骨断 復刻": (1, 2)}) is False
    assert matcher.find_str_in_text("区的奇&&", {"20区的奇迹": (1, 2)}) is False


@pytest.mark.parametrize("refreshes", [0, 1, 2, 3])
def test_refresh_exhaustion_selects_best_normal_pack(monkeypatch, refreshes):
    task, auto, home = selection(monkeypatch, [["无归属者", "被遗忘者们", "自动工厂"]], refreshes)
    task.select_theme_pack(False, 1, 1, True)
    assert auto.selected == "被遗忘者们"
    assert auto.refresh_count == refreshes
    home.assert_not_called()


@pytest.mark.parametrize("hard,floor,pages,refreshes,expected,used", [
    (False, 1, [["囊空如洗的赌徒", "被遗忘者们"]], 3, "囊空如洗的赌徒", 0),
    (False, 2, [["囊空如洗的赌徒", "地狱鸡"]], 3, "地狱鸡", 0),
    (False, 3, [["落花", "憎惡与絶望"]], 3, "憎惡与絶望", 0),
    (False, 1, [["被遗忘者们"], ["囊空如洗的赌徒"]], 3, "囊空如洗的赌徒", 1),
    (True, 4, [["2号綫", "20区的奇迹 復刻", "20区的奇迹"]], 3, "20区的奇迹 復刻", 0),
    (True, 4, [["20区的奇迹", "異常地震帯"]], 0, "異常地震帯", 0),
    (True, 5, [["3号綫", "20区的奇迹 復刻", "2号綫"]], 3, "3号綫", 0),
    (True, 5, [["4号綫 - 第3区段", "5号綫", "1号綫"]], 0, "1号綫", 0),
    (True, 5, [["3号綫 - 終点站", "異常地震帯"]], 0, "異常地震帯", 0),
])
def test_floor_policy(monkeypatch, hard, floor, pages, refreshes, expected, used):
    task, auto, home = selection(monkeypatch, pages, refreshes)
    task.select_theme_pack(hard, floor, 1, True)
    assert auto.selected == expected
    assert auto.refresh_count == used
    home.assert_not_called()


@pytest.mark.parametrize("hard,floor,pack", [
    (False, 1, "自動工厂"), (False, 1, "无法去愛"), (False, 1, "无慈悲者"),
    (False, 2, "自動工厂"), (False, 2, "无法去愛"), (False, 2, "湖的世界"),
    (False, 3, "未曾面对"), (False, 3, "无作为者"), (False, 3, "宅邸的副産物"),
    (True, 4, "紫羅蘭的正午"), (True, 4, "20区的奇迹"), (True, 4, "定義為惡"),
    (True, 5, "4号綫 - 第3区段"), (True, 5, "4号綫 - 第4区段"),
    (True, 5, "5号綫"), (True, 5, "定義為惡"), (True, 5, "梦之終焉"),
])
def test_forbidden_pack_cannot_override_fallback_or_preferred_weight(monkeypatch, hard, floor, pack):
    task, auto, home = selection(monkeypatch, [[pack, "被遗忘者们"]], 0, banned_weight=99)
    task.select_theme_pack(hard, floor, 1, True)
    assert auto.selected == "被遗忘者们"
    home.assert_not_called()


@pytest.mark.parametrize("language,hard,floor,pack", [
    ("en", False, 1, "Automated Factory"), ("en", False, 2, "The Unloving"),
    ("en", False, 2, "Lake World"), ("en", False, 3, "The Unconfronting"),
    ("en", False, 3, "Dregs of the Manor"), ("en", True, 4, "The Noon of Violet"),
    ("en", True, 4, "Miracle in District 20"), ("en", True, 5, "Line 4 Section#3"),
    ("en", True, 5, "Line 4 Section#4"), ("en", True, 5, "Line 5"),
    ("en", True, 5, "The Evil Defining"), ("en", True, 5, "The Dream Ending"),
])
def test_english_hard_bans(monkeypatch, language, hard, floor, pack):
    task, auto, home = selection(monkeypatch, [[pack, "Forgotten Ones"]], 0, language=language, banned_weight=99)
    task.select_theme_pack(hard, floor, 1, True)
    assert auto.selected == "Forgotten Ones"
    home.assert_not_called()


@pytest.mark.parametrize("refreshes", [0, 1, 2, 3])
def test_all_forbidden_after_exhaustion_stops_without_selecting_or_restarting(monkeypatch, refreshes):
    from module.backends.base import BackendCancelled

    task, auto, home = selection(monkeypatch, [["自动工厂", "无法去爱"]], refreshes)
    with pytest.raises(BackendCancelled, match="剩余卡包均为禁选"):
        task.select_theme_pack(False, 1, 1, True)
    assert auto.selected is None
    assert auto.refresh_count == refreshes
    home.assert_not_called()


@pytest.mark.parametrize("next_pack", ["被遗忘者们", "囊空如洗的赌徒"])
def test_all_forbidden_refreshes_before_safe_selection(monkeypatch, next_pack):
    task, auto, home = selection(monkeypatch, [["自动工厂", "无法去爱"], [next_pack]], 1)
    task.select_theme_pack(False, 1, 1, True)
    assert auto.selected == next_pack
    assert auto.refresh_count == 1
    home.assert_not_called()


@pytest.mark.parametrize("pack", ["N", "4号綫", "未来新卡包", "未知"])
def test_unconfirmed_packs_cannot_bypass_active_bans(monkeypatch, pack):
    task, auto, home = selection(monkeypatch, [[pack, "解放的暴怒"]], 0)
    task.select_theme_pack(True, 5, 1, True)
    assert auto.selected == "解放的暴怒"  # -5 是允许的软低优先级，不在本层硬禁选表里。
    home.assert_not_called()


@pytest.mark.parametrize("hard,floor,pack", [
    (False, 1, "湖的世界"), (False, 3, "自动工厂"),
    (False, 3, "无法去爱"), (False, 4, "20区的奇迹"),
    (True, 3, "宅邸的副産物"), (True, 5, "20区的奇迹"),
    (True, 5, "紫罗兰的正午"), (True, 5, "1号綫 瘋狂"),
    (True, 5, "3号綫 終点站"),
])
def test_bans_are_scoped_to_requested_floor_and_difficulty(monkeypatch, hard, floor, pack):
    task, auto, home = selection(monkeypatch, [[pack]], 0)
    task.select_theme_pack(hard, floor, 1, True)
    assert auto.selected == pack
    home.assert_not_called()


def test_force_event_pack_cannot_bypass_hard_bans(monkeypatch):
    task, auto, home = selection(monkeypatch, [["梦之终焉", "1号綫"]], 0)
    task.cfg.select_event_pack = True
    task.select_theme_pack(True, 5, 1, True)
    assert auto.selected == "1号綫"
    home.assert_not_called()


def test_default_empty_policy_preserves_unknown_and_event_selection(monkeypatch):
    task, auto, home = selection(monkeypatch, [["未来新卡包", "梦之终焉"]], 0, bans=False)
    task.cfg.select_event_pack = True
    task.select_theme_pack(True, 5, 1, True)
    assert auto.selected == "未来新卡包"
    home.assert_not_called()


def test_mirror_worker_does_not_retry_when_all_packs_are_forbidden(monkeypatch):
    from module.backends.base import BackendCancelled
    from module.config import cfg

    selector, auto, home = selection(monkeypatch, [["自动工厂", "无法去爱"]], 0)
    task = import_module("tasks.base.script_task_scheme")
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={
        "auto_hard_mirror": False, "set_mirror_count": 1,
        "teams_be_select": [True], "teams_active_queue": [1],
    }))
    adventure = Mock()
    adventure.run.side_effect = lambda: selector.select_theme_pack(False, 1, 1, True)
    constructor = Mock(return_value=adventure)
    monkeypatch.setattr(task, "Mirror", constructor)
    with pytest.raises(BackendCancelled):
        task.Mirror_task()
    constructor.assert_called_once()
    assert auto.selected is None
    home.assert_not_called()


def test_global_bans_survive_team_override_and_yaml_sync(tmp_path):
    import copy

    from module.config.config import Theme_pack_list

    data = preset()
    config = object.__new__(Theme_pack_list)
    config.yaml = YAML()
    config.config = copy.deepcopy(data)
    config.theme_pack_list_path = str(tmp_path / "global.yaml")
    config.theme_pack_weight_path = tmp_path / "teams"
    custom = copy.deepcopy(data)
    custom["forbidden_theme_packs"]["normal_1"] = ["湖的"]
    config.save_config(config.theme_pack_list_path, data)
    config.save_config(config.build_team_weight_path(1), custom)
    default = YAML(typ="safe").load((SOURCE_ROOT / "assets/config/theme_pack_list.example.yaml").read_text())
    config._sync_team_weight_configs(default)
    assert config.load_config(config.theme_pack_list_path)["forbidden_theme_packs"] == data["forbidden_theme_packs"]
    assert config.get_forbidden_theme_packs(False, 1, 1, True) == set(data["forbidden_theme_packs"]["normal_1"]) | {"湖的"}
    assert config.get_forbidden_theme_packs(False, 1, 1, False) == set(data["forbidden_theme_packs"]["normal_1"])
    assert config.get_forbidden_theme_packs(False, 2, 99, True) == set(data["forbidden_theme_packs"]["normal_2"])
    assert config.get_forbidden_theme_packs(False, None, 1, False) == {
        keyword for key, values in data["forbidden_theme_packs"].items() if key.startswith("normal_") for keyword in values
    }
    for key, values in data["forbidden_theme_packs"].items():
        hard = key.startswith("hard_")
        keywords = set(data["theme_pack_list"]) | set(data["theme_pack_list_cn"])
        if hard:
            keywords |= set(data["theme_pack_list_hard"]) | set(data["theme_pack_list_hard_cn"])
        assert set(values) <= keywords


def test_missing_pack_frame_is_retried_before_fallback(monkeypatch):
    task, auto, home = selection(monkeypatch, [["被遗忘者们"]], 0)
    auto.missing_frames = 2
    task.select_theme_pack(False, 1, 1, True)
    assert auto.captures == 3
    assert auto.selected == "被遗忘者们"
    home.assert_not_called()


def selection(monkeypatch, pages, refreshes, *, language="zh_cn", banned_weight=None, bans=True):
    from module.automation import Automation
    from module.config import cfg

    task = import_module("tasks.mirror.select_theme_pack")
    data = preset()
    if banned_weight is not None:
        forbidden = {key for keys in data["forbidden_theme_packs"].values() for key in keys}
        for section in ("theme_pack_list", "theme_pack_list_hard", "theme_pack_list_cn", "theme_pack_list_hard_cn"):
            for key in data[section]:
                if key in forbidden:
                    data[section][key] = banned_weight
    monkeypatch.setattr(cfg, "config", cfg.config.model_copy(update={"game_profile": "ios_zh_cn"}))
    matcher = Automation.__new__(Automation)

    class FakeAutomation:
        index = 0
        captures = 0
        refresh_count = 0
        selected = None
        missing_frames = 0

        def take_screenshot(self):
            self.captures += 1
            assert self.captures < 40, "Selection must finish without returning to home"
            return object()

        def find_element(self, path, **kwargs):
            if path.endswith("theme_pack_features.png") and self.captures > self.missing_frames:
                self.pack_index = 0
                return [(300 + 500 * i, 200) for i in range(len(pages[self.index]))]
            return None

        def find_language_text(self, zh, en, crop):
            name = pages[self.index][self.pack_index]
            self.pack_index += 1
            return matcher._find_target_in_ocr_dict(en if language == "en" else zh, {name: (100, 100)})

        def click_element(self, path):
            if self.refresh_count >= refreshes:
                return False
            self.refresh_count += 1
            self.index = min(self.index + 1, len(pages) - 1)
            return True

        def mouse_drag_down(self, x, y):
            self.selected = pages[self.index][round((x - 300) / 500)]

        def mouse_to_blank(self, **kwargs):
            pass

    def weights(hard, language, team, custom):
        suffix = "_cn" if language == "zh_cn" else ""
        return {**data[f"theme_pack_list{suffix}"], **(data[f"theme_pack_list_hard{suffix}"] if hard else {})}

    def forbidden(hard, floor, team, custom):
        return set(data["forbidden_theme_packs"].get(f"{'hard' if hard else 'normal'}_{floor}", [])) if bans else set()

    auto = FakeAutomation()
    home = Mock()
    monkeypatch.setattr(task, "auto", auto)
    monkeypatch.setattr(task, "cfg", SimpleNamespace(set_win_size=1080, select_event_pack=False, skip_event_pack=False))
    monkeypatch.setattr(task, "theme_list", SimpleNamespace(preferred_thresholds=data["preferred_thresholds"], get_effective_theme_pack_list=weights, get_forbidden_theme_packs=forbidden))
    monkeypatch.setattr(task, "path_manager", SimpleNamespace(current_language=language))
    monkeypatch.setattr(task, "back_init_menu", home)
    monkeypatch.setattr(task, "sleep", lambda _: None)
    return task, auto, home
