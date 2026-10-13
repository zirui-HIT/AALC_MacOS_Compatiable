"""UI drafts; no configuration singleton, game access or task scheduling."""

import copy

SINNERS = ["李箱", "浮士德", "堂吉诃德", "良秀", "默尔索", "鸿璐", "希斯克利夫", "以实玛利", "罗佳", "辛克莱", "奥提斯", "格里高尔"]
SYSTEMS = ["burn", "bleed", "tremor", "rupture", "poise", "sinking", "charge", "slash", "pierce", "blunt"]


class TeamDraft:
    def __init__(self, values):
        self.original = copy.deepcopy(values)
        self.values = copy.deepcopy(values)
        self.set("team_system", self.values["team_system"])

    def select_sinner(self, index, selected):
        values = self.values
        if bool(values["chosen_sinners"][index]) == selected:
            return
        if selected:
            values["sinners_be_select"] += 1
            values["chosen_sinners"][index] = 1
            values["sinner_order"][index] = values["sinners_be_select"]
        else:
            order = values["sinner_order"][index]
            values["sinners_be_select"] -= 1
            values["chosen_sinners"][index] = 0
            for i in range(12):
                if values["sinner_order"][i] > order:
                    values["sinner_order"][i] -= 1
            values["sinner_order"][index] = 0

    def set(self, key, value):
        if key == "system_" + SYSTEMS[self.values["team_system"]]:
            value = False
        self.values[key] = value
        pairs = {"avoid_skill_3": "prioritize_skill_3", "prioritize_skill_3": "avoid_skill_3", "defense_first_round": "defense_for_solo", "defense_for_solo": "defense_first_round"}
        if key in pairs and value:
            self.values[pairs[key]] = False
        if key == "team_system":
            self.values["system_" + SYSTEMS[value]] = False

    def dirty(self):
        return self.original != self.values
