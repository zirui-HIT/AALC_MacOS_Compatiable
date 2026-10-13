"""Native typed forms shared by config pages and team drafts."""

import copy

import AppKit as A

from frontend_appkit.observe_selection import (
    OBSERVE_SYSTEM_KEYS,
    ObserveGiftSelection,
    parse_observe_ego_gift_values,
    serialize_observe_ego_gift_values,
)
from frontend_appkit.starlight_data import STARLIGHT_BONUS_COSTS, STARLIGHT_BONUS_NAMES, STARLIGHT_BONUS_TIPS
from frontend_appkit.widgets import button, label, popup, textfield
from native_contract import FIELDS, OPTIONS


class Form:
    def __init__(self, parent, values, keys, targets, on_change, *, team=False, start=16, text=lambda s: s):
        self.parent, self.targets, self.on_change = parent, targets, on_change
        self.original = copy.deepcopy(values)
        self.getters, self.controls = {}, {}
        self.text = text
        self.y = start
        metadata = FIELDS["TeamSetting" if team else "ConfigModel"]
        for key in keys:
            self.add(key, values.get(key), metadata[key]["label"])
        self.resize()

    def resize(self):
        self.parent.setFrameSize_((self.parent.frame().size.width, max(self.y + 20, 200)))

    def changed(self, key):
        if key == "opening_bonus":
            self.update_starlight_cost()
        self.on_change(key, self.getters[key]())

    def add(self, key, value, title):
        label(self.parent, title, ((16, self.y + 4), (325, 22)))
        frame = ((350, self.y), (max(260, self.parent.frame().size.width - 370), 28))
        if key == "observe_ego_gift_selected":
            self._observe(key, value)
            return
        if isinstance(value, list):
            self._array(key, value, frame)
            return
        if key in OPTIONS:
            choices = OPTIONS[key]
            control, getter = popup(self.parent, choices, value, frame, lambda sender: self.changed(key), self.targets)
        elif isinstance(value, bool):
            control = button(self.parent, self.text("启用"), frame, lambda sender: self.changed(key), self.targets, checkbox=True, checked=value)
            def getter():
                return bool(control.state())
        else:
            numeric = isinstance(value, (int, float))
            control = textfield(self.parent, value, frame, lambda sender: self.changed(key), self.targets, numeric=numeric)
            getter = (lambda: float(control.stringValue())) if isinstance(value, float) else (lambda: int(control.stringValue())) if isinstance(value, int) else (lambda: str(control.stringValue()))
        control.setAutoresizingMask_(A.NSViewWidthSizable)
        self.controls[key], self.getters[key] = control, getter
        self.y += 40

    def _array(self, key, value, frame):
        names = None
        if key == "after_completion_actions":
            names = ["退出游戏", "退出 AALC"]
            selected = ["exit_game" in value, "exit_aalc" in value]
        elif key.endswith("_task_exit"):
            names, selected = ["退出游戏", "退出 AALC"], value[:2]
        elif key.endswith("_task"):
            names, selected = ["日常", "领奖", "狂气换体", "镜牢"], value
        elif key == "second_system_action":
            names, selected = ["合成四级", "购买", "选胜利奖励", "升级四级"], value
        elif key == "ignore_shop":
            names, selected = [f"第{i}层" for i in range(1, 6)], value
        elif key == "opening_bonus":
            names = STARLIGHT_BONUS_NAMES
            selected = value
        else:
            names, selected = [str(i + 1) for i in range(len(value))], value
        controls, getters = [], []
        for i, (name, selected_value) in enumerate(zip(names, selected)):
            x, y = 350 + (i % 3) * 155, self.y + (i // 3) * 34
            if key == "opening_bonus":
                choices = [[f"{name} · {level}", level] for level in range(4)]
                control, getter = popup(self.parent, choices, selected_value, ((x, y), (150, 28)), lambda sender: self.changed(key), self.targets)
                control.setToolTip_("\n\n".join(STARLIGHT_BONUS_TIPS[i].values()))
            else:
                control = button(self.parent, self.text(name), ((x, y), (150, 28)), lambda sender: self.changed(key), self.targets, checkbox=True, checked=selected_value)
                def getter(c=control):
                    return int(bool(c.state()))
            controls.append(control)
            getters.append(getter)

        def collect():
            result = [getter() for getter in getters]
            if key == "after_completion_actions":
                return [name for name, active in zip(["exit_game", "exit_aalc"], result) if active]
            if key.endswith("_task_exit"):
                return [bool(item) for item in result] + [False] * 5
            if key.endswith("_task"):
                return [bool(item) for item in result]
            return result

        self.controls[key], self.getters[key] = controls, collect
        self.y += max(1, (len(names) + 2) // 3) * 34 + 12
        if key == "opening_bonus":
            self.starlight_cost = label(self.parent, "", ((350, self.y), (430, 24)))

            def set_all(sender):
                level = sender.indexOfSelectedItem()
                for control in controls:
                    control.selectItemAtIndex_(level)
                self.changed(key)

            popup(self.parent, [["全选 · 清空", 0], ["全选 · 基础", 1], ["全选 · +", 2], ["全选 · ++", 3]], 0, ((350, self.y + 30), (300, 28)), set_all, self.targets)
            self.y += 72
            self.update_starlight_cost()

    def update_starlight_cost(self):
        values = self.getters["opening_bonus"]()
        self.starlight_cost.setStringValue_(f"星光总消耗 · {sum(cost * value for cost, value in zip(STARLIGHT_BONUS_COSTS, values))}")

    def _observe(self, key, value):
        rows = parse_observe_ego_gift_values(value)
        while len(rows) < 3:
            rows.append(ObserveGiftSelection())
        row_getters = []
        for i, row in enumerate(rows[:3]):
            getters = []
            choices = [["—", None], *[[system, system] for system in OBSERVE_SYSTEM_KEYS]]
            for col, (choices_, selected) in enumerate([(choices, row.system), ([["等级", None], *[[str(n), n] for n in range(1, 4)]], row.level), ([["行", None], *[[str(n), n] for n in range(1, 11)]], row.row), ([["列", None], *[[str(n), n] for n in range(1, 9)]], row.col)]):
                _, getter = popup(self.parent, choices_, selected, ((350 + col * 116, self.y + i * 34), (112, 28)), lambda sender: self.changed(key), self.targets)
                getters.append(getter)
            row_getters.append(getters)
        self.getters[key] = lambda: serialize_observe_ego_gift_values([ObserveGiftSelection(*[get() for get in getters]) for getters in row_getters])
        self.y += 116

    def values(self):
        return {key: getter() for key, getter in self.getters.items()}

    def set_value(self, key, value):
        control = self.controls.get(key)
        if control is None:
            return
        if isinstance(control, list):
            if key == "after_completion_actions":
                selected = ["exit_game" in value, "exit_aalc" in value]
            else:
                selected = value
            for widget, item in zip(control, selected):
                if key == "opening_bonus":
                    widget.selectItemAtIndex_(int(item))
                else:
                    widget.setState_(int(bool(item)))
            if key == "opening_bonus":
                self.update_starlight_cost()
            return
        if key in OPTIONS:
            control.selectItemAtIndex_(next((i for i, item in enumerate(OPTIONS[key]) if item[1] == value), 0))
        elif isinstance(value, bool):
            control.setState_(int(value))
        else:
            control.setStringValue_("" if value is None else str(value))
