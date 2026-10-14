"""Native typed forms shared by config pages and team drafts."""

import AppKit as A

from frontend_appkit.observe_selection import (
    OBSERVE_SYSTEM_KEYS,
    ObserveGiftSelection,
    parse_observe_ego_gift_values,
    serialize_observe_ego_gift_values,
)
from frontend_appkit.presentation import SurfaceView
from frontend_appkit.starlight_data import STARLIGHT_BONUS_COSTS, STARLIGHT_BONUS_NAMES, STARLIGHT_BONUS_TIPS
from frontend_appkit.widgets import button, label, popup, textfield, tooltip
from native_contract import FIELDS, OPTIONS

DISPLAY_LABELS = {
    "set_EXP_count": ("经验本次数", "EXP runs"),
    "set_thread_count": ("纽本次数", "Thread runs"),
    "daily_teams": ("日常队伍", "Daily team"),
    "use_continuous_combat": ("连续战斗", "Continuous combat"),
    "use_continuous_combat_select": ("最大连续次数", "Maximum consecutive battles"),
    "set_mirror_count": ("镜牢次数", "Mirror runs"),
    "hard_mirror": ("困难镜牢", "Hard mirror"),
    "game_profile": ("游戏版本", "Game version"),
    "playcover_app_path": ("游戏应用路径", "Game app path"),
    "playcover_host": ("连接地址", "Connection address"),
    "playcover_port": ("端口", "Port"),
    "playcover_bundle_id": ("游戏标识", "Game identifier"),
    "playcover_capture_method": ("截图方式", "Capture method"),
    "check_update": ("启动时检查官方更新", "Check official updates at launch"),
    "after_completion_actions": ("完成后操作", "After-run actions"),
}
for suffix in ("", "2", "3", "4"):
    DISPLAY_LABELS.update({
        "autodaily" + suffix: ("启用定时任务", "Enable schedule"),
        "autodaily_time" + suffix: ("执行时间（HH:mm）", "Time (HH:mm)"),
        "autodaily" + suffix + "_task": ("执行任务", "Tasks to run"),
    })


class Form:
    def __init__(self, parent, values, keys, targets, on_change, *, team=False, start=16, text=lambda s: s, sections=None, grouped=False):
        self.parent, self.targets, self.on_change = parent, targets, on_change
        self.getters, self.controls = {}, {}
        self.text = text
        self.y = start
        self.grouped = grouped
        self.inset, self.control_x = (16 if grouped else 20), 232
        self.container, self.offset_y = parent, 0
        self.group_rows = 0
        metadata = FIELDS["TeamSetting" if team else "ConfigModel"]
        for key in keys:
            section = sections.get(key) if sections else None
            if grouped and (self.container is parent or section):
                if self.container is not parent:
                    self.close_group()
                    self.y += 16
                self.begin_group(section)
            elif section:
                if self.y > start:
                    self.y += 16
                heading = label(self.parent, section, ((self.inset, self.y), (self.width - self.inset * 2, 24)), size=14, bold=True)
                tooltip(heading, section)
                self.y += 30
            title = DISPLAY_LABELS[key][0] if key in DISPLAY_LABELS else metadata[key]["label"]
            if key.endswith("_task_exit"):
                title = "完成后"
            self.add(key, values.get(key), title)
        if grouped and self.container is not parent:
            self.close_group()
        self.resize()

    def begin_group(self, title):
        if title:
            heading = label(self.parent, title, ((20, self.y), (self.parent.frame().size.width - 40, 18)), size=12)
            heading.setFont_(A.NSFont.systemFontOfSize_weight_(12, A.NSFontWeightSemibold))
            heading.setTextColor_(A.NSColor.secondaryLabelColor())
            tooltip(heading, title)
            self.y += 26
        self.container = SurfaceView.alloc().initWithFrame_(((20, self.y), (self.parent.frame().size.width - 40, 1)))
        self.container.kind = "group"
        self.container.setAutoresizingMask_(A.NSViewWidthSizable)
        self.parent.addSubview_(self.container)
        self.offset_y = self.y
        self.group_rows = 0
        self.y += 8

    def close_group(self):
        self.container.setFrameSize_((self.width, self.y - self.offset_y))
        self.container, self.offset_y = self.parent, 0

    def separator(self):
        if self.grouped and self.group_rows:
            line = A.NSBox.alloc().initWithFrame_(((self.inset, self.local_y - 4), (self.width - self.inset * 2, 1)))
            line.setBoxType_(A.NSBoxSeparator)
            line.setAutoresizingMask_(A.NSViewWidthSizable)
            self.container.addSubview_(line)
        self.group_rows += 1

    @property
    def local_y(self):
        return self.y - self.offset_y

    @property
    def width(self):
        return self.container.frame().size.width

    @property
    def control_width(self):
        return max(260, self.width - self.control_x - self.inset)

    def row(self, y, columns, *, width=None):
        x = self.inset if self.grouped else self.control_x
        fixed_width = width is not None
        width = width if fixed_width else self.width - self.inset * 2 if self.grouped else self.control_width
        row = A.NSStackView.alloc().initWithFrame_(((x, y - self.offset_y), (width, 28)))
        row.setOrientation_(A.NSUserInterfaceLayoutOrientationHorizontal)
        row.setDistribution_(A.NSStackViewDistributionFillEqually)
        row.setAlignment_(A.NSLayoutAttributeCenterY)
        row.setSpacing_(8)
        row.setEdgeInsets_((0, 3, 0, 3))
        row.setAutoresizingMask_(0 if fixed_width else A.NSViewWidthSizable)
        self.container.addSubview_(row)
        return row, (width - (columns - 1) * 8) / columns

    def resize(self):
        self.parent.setFrameSize_((self.parent.frame().size.width, max(self.y + 20, 200)))

    def changed(self, key):
        if key == "opening_bonus":
            self.update_starlight_cost()
        self.on_change(key, self.getters[key]())

    def add(self, key, value, title):
        self.separator()
        if isinstance(value, bool) and key not in OPTIONS:
            control = button(self.container, title, ((self.inset, self.local_y), (self.width - self.inset * 2, 28)), lambda sender: self.changed(key), self.targets, checkbox=True, checked=value)
            control.setFont_(A.NSFont.systemFontOfSize_(13))
            tooltip(control, title)
            control.setAutoresizingMask_(A.NSViewWidthSizable)
            self.controls[key], self.getters[key] = control, lambda: bool(control.state())
            self.y += 36
            return
        stacked = self.grouped and (isinstance(value, list) or key == "observe_ego_gift_selected" or key.endswith("_path"))
        numeric = isinstance(value, (int, float))
        control_width = 80 if numeric and key not in OPTIONS else 220
        if key.startswith("autodaily_time"):
            control_width = 88
        x = self.width - self.inset - control_width if self.grouped else self.control_x
        caption_width = self.width - self.inset * 2 if stacked else x - self.inset - 16
        caption = label(self.container, title, ((self.inset, self.local_y + 4), (caption_width, 22)), size=13)
        caption.setAutoresizingMask_(A.NSViewWidthSizable if self.grouped else 0)
        tooltip(caption, title)
        if stacked:
            self.y += 28
        frame = ((x, self.local_y), (control_width if self.grouped else self.control_width, 28))
        if key == "observe_ego_gift_selected":
            self._observe(key, value)
            return
        if isinstance(value, list):
            self._array(key, value, frame)
            return
        if key in OPTIONS:
            choices = OPTIONS[key]
            control, getter = popup(self.container, choices, value, frame, lambda sender: self.changed(key), self.targets)
        else:
            if stacked:
                frame = ((self.inset, self.local_y), (self.width - self.inset * 2, 28))
            elif numeric and not self.grouped:
                frame = ((self.control_x, self.y), (124, 28))
            control = textfield(self.container, value, frame, lambda sender: self.changed(key), self.targets, numeric=numeric)
            if numeric:
                def getter():
                    number = control.formatter().numberFromString_(control.stringValue())
                    if number is None:
                        raise ValueError("数值无效")
                    return float(number) if isinstance(value, float) else int(number)
            else:
                getter = (lambda: str(control.stringValue()) or None) if value is None else (lambda: str(control.stringValue()))
        control.setFont_(A.NSFont.systemFontOfSize_(13))
        tooltip(control, title)
        control.setAutoresizingMask_(A.NSViewWidthSizable if stacked else A.NSViewMinXMargin if self.grouped else 0 if numeric and key not in OPTIONS else A.NSViewWidthSizable)
        self.controls[key], self.getters[key] = control, getter
        self.y += 36

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
        columns = 3
        width = None
        if self.grouped and key.endswith("_task"):
            columns = 4
        elif self.grouped and (key == "after_completion_actions" or key.endswith("_task_exit")):
            columns = 2
            width = min(304, self.width - self.inset * 2)
        controls, getters = [], []
        for i, (name, selected_value) in enumerate(zip(names, selected)):
            if i % columns == 0:
                row, cell_width = self.row(self.y + (i // columns) * 34, columns, width=width)
            frame = ((0, 0), (cell_width, 28))
            if key == "opening_bonus":
                choices = [[f"{name} · {level}", level] for level in range(4)]
                control, getter = popup(row, choices, selected_value, frame, lambda sender: self.changed(key), self.targets)
                control.setToolTip_("\n\n".join(STARLIGHT_BONUS_TIPS[i].values()))
            else:
                control = button(row, name, frame, lambda sender: self.changed(key), self.targets, checkbox=True, checked=selected_value)
                tooltip(control, name)
                def getter(c=control):
                    return int(bool(c.state()))
            control.setFont_(A.NSFont.systemFontOfSize_(13))
            row.addArrangedSubview_(control)
            controls.append(control)
            getters.append(getter)

        # Keep the final row on the same column grid.
        for _ in range((-len(controls)) % columns):
            row.addArrangedSubview_(A.NSView.alloc().initWithFrame_(((0, 0), (cell_width, 28))))

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
        self.y += max(1, (len(names) + columns - 1) // columns) * 34 + (4 if self.grouped else 12)
        if key == "opening_bonus":
            x = self.inset if self.grouped else self.control_x
            width = self.width - self.inset * 2 - 240 if self.grouped else self.control_width
            self.starlight_cost = label(self.container, "", ((x, self.local_y + (4 if self.grouped else 0)), (width, 24)))
            self.starlight_cost.setIdentifier_(None)
            self.starlight_cost.setTextColor_(A.NSColor.secondaryLabelColor())

            def set_all(sender):
                level = sender.indexOfSelectedItem()
                for control in controls:
                    control.selectItemAtIndex_(level)
                self.changed(key)

            frame = ((self.width - self.inset - 220, self.local_y), (220, 28)) if self.grouped else ((self.control_x, self.y + 30), (260, 28))
            bulk, _ = popup(self.container, [["全选 · 清空", 0], ["全选 · 基础", 1], ["全选 · +", 2], ["全选 · ++", 3]], 0, frame, set_all, self.targets)
            if self.grouped:
                bulk.setAutoresizingMask_(A.NSViewMinXMargin)
            self.y += 36 if self.grouped else 72
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
            container, cell_width = self.row(self.y + i * 34, 4)
            choices = [["—", None], *[[system, system] for system in OBSERVE_SYSTEM_KEYS]]
            for col, (choices_, selected) in enumerate([(choices, row.system), ([["等级", None], *[[str(n), n] for n in range(1, 4)]], row.level), ([["行", None], *[[str(n), n] for n in range(1, 11)]], row.row), ([["列", None], *[[str(n), n] for n in range(1, 9)]], row.col)]):
                control, getter = popup(container, choices_, selected, ((0, 0), (cell_width, 28)), lambda sender: self.changed(key), self.targets)
                control.setToolTip_(self.text(["体系", "等级", "行", "列"][col]))
                control.setFont_(A.NSFont.systemFontOfSize_(13))
                container.addArrangedSubview_(control)
                getters.append(getter)
            row_getters.append(getters)
        self.getters[key] = lambda: serialize_observe_ego_gift_values([ObserveGiftSelection(*[get() for get in getters]) for getters in row_getters])
        self.y += 106 if self.grouped else 116

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
        elif control.formatter() is not None:
            control.setObjectValue_(value)
        else:
            control.setStringValue_("" if value is None else str(value))
