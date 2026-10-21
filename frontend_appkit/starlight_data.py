"""Original starlight labels, costs and explanations."""

import re

def QT_TRANSLATE_NOOP(context, text):
    return text

STARLIGHT_BONUS_NAMES = [
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "起始之星"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "层积星云"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "星际旅行"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "倾落的流星雨"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "双星商店"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "卫星商店"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "星云的宠爱"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "星芒的引导"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "偶然的彗星"),
    QT_TRANSLATE_NOOP("CustomizeSettingsModule", "全面的可能性"),
]

STARLIGHT_BONUS_COSTS = [10, 10, 20, 20, 30, 30, 40, 40, 50, 60]

STARLIGHT_BONUS_TIPS = [
    {
        "buff": "buff：\n初始经费 +150\n主题卡包出现数量 +1\n商店里展出的饰品数量 +1\n可免费进行商店普通刷新 1次",
        "buff+": "buff+：\n初始经费 \\yellow{+250}\n主题卡包出现数量 +1\n商店里展出的饰品数量 +1\n可免费进行商店普通刷新 1次",
        "buff++": "buff++：\n初始经费 \\yellow{+250}\n主题卡包出现数量 +1\n商店里展出的饰品数量 +1\n可免费进行商店普通刷新 \\yellow{2次}",
    },
    {
        "buff": "buff：\n进入下个阶段时，增加当前经费的10%(最多100)\n售卖饰品所得经费增加50%(每个商店1次)",
        "buff+": "buff+：\n进入下个阶段时，增加当前经费的\\yellow{20%(最多125)}\n售卖饰品所得经费增加\\yellow{75%(每个商店1次)}",
        "buff++": "buff++：\n进入下个阶段时，增加当前经费的\\yellow{30%(最多150)}\n售卖饰品所得经费增加\\yellow{100%(每个商店1次)}",
    },
    {
        "buff": "buff：\n主题卡包出现数量 +1\n主题卡包刷新次数 +2\n选择未记录的主题卡包时，所有人格等级 +3(最多9级)",
        "buff+": "buff+：\n主题卡包出现数量 +1\n主题卡包刷新次数 \\yellow{+3}\n选择未记录的主题卡包时，所有人格等级 +3(最多9级)\n\\yellow{如果解锁了45个及以上主题卡包图鉴中的主题卡包，获得1层拼点威力提升}",
        "buff++": "buff++：\n主题卡包出现数量 +1\n主题卡包刷新次数 \\yellow{+4}\n选择未记录的主题卡包时，所有人格等级 +3(最多9级)\n\\yellow{如果解锁了45个及以上主题卡包图鉴中的主题卡包，获得2层拼点威力提升}",
    },
    {
        "buff": "buff：\n初始经费 +400\n初始饰品可选择数 +1",
        "buff+": "buff+：\n初始经费 \\yellow{+500}\n初始饰品可选择数 +1\n\\yellow{选择遭遇战奖励卡中的星芒选项时，经费 +75}",
        "buff++": "buff++：\n初始经费 \\yellow{+700}\n初始饰品可选择数 +1\n\\yellow{选择遭遇战奖励卡中的星芒选项时，经费 +150}",
    },
    {
        "buff": "buff：\n商店里展出的饰品数量 +1\n战斗胜利时获得的经费 +20%\n提升商店里更高等级饰品的展出概率",
        "buff+": "buff+：\n商店里展出的饰品数量 +1\n战斗胜利时获得的经费 \\yellow{+30%}\n提升商店里更高等级饰品的展出概率\n\\yellow{进入商店时，获得等同于当前持有的饰品等级之和的经费(最多75)}",
        "buff++": "buff++：\n商店里展出的饰品数量 +1\n战斗胜利时获得的经费 \\yellow{+40%}\n提升商店里更高等级饰品的展出概率\n\\yellow{进入商店时，获得等同于当前持有的饰品等级之和的经费(最多150)}",
    },
    {
        "buff": "buff：\n可免费进行商店关键词刷新 1次\n进入第1层时，随机获得1件1级饰品",
        "buff+": "buff+：\n可免费进行商店关键词刷新 1次\n进入第1层时，随机获得\\yellow{2件}1级饰品\n\\yellow{特殊商店出现概率 +10%}",
        "buff++": "buff++：\n可免费进行商店关键词刷新 \\yellow{2次}\n进入第1层时，随机获得\\yellow{3件}1级饰品\n\\yellow{特殊商店出现概率 +25%}",
    },
    {
        "buff": "buff：\n进入第1层时，人格等级 +3\n通过阶段时，人格等级 +1(最多+5)",
        "buff+": "buff+：\n进入第1层时，人格等级 +3\n通过阶段时，人格等级 +1\\yellow{(最多+9)}",
        "buff++": "buff++：\n进入第1层时，人格等级 +3\n\\yellow{进入第6层时，人格等级 +3}\n通过阶段时，人格等级 +1\\yellow{(最多+9)}",
    },
    {
        "buff": "buff：\n最大速度值 +2\n获得1层 拼点威力提升\n获得1层 伤害强化\n获得1层 守护",
        "buff+": "buff+：\n最大速度值 \\yellow{+3}\n获得\\yellow{2层} 拼点威力提升\n获得1层 伤害强化\n获得1层 守护",
        "buff++": "buff++：\n最大速度值 \\yellow{+3}\n获得\\yellow{2层} 拼点威力提升\n获得\\yellow{2层} 伤害强化\n获得\\yellow{2层} 守护",
    },
    {
        "buff": "buff：\n进入商店时，随机获得1件3级及以下的合成/售卖专用饰品\n进入第3层时，随机获得1件3级饰品\n合成时，随机获得比合成产物(3级及以上)低2级的饰品(每个商店最多1次)",
        "buff+": "buff+：\n进入商店时，随机获得1件3级及以下的合成・售卖专用E.G.O饰品\n第5层及以下：\\yellow{1~3级}\n第6层及以上：\\yellow{2~3级}\n进入第3层\\yellow{与第5层}时，随机获得1件所选关键词的3级E.G.O饰品\n合成时，可随机获得比合成产物(3级及以上)低2级的E.G.O饰品(每个商店1次)",
        "buff++": "buff++：\n进入商店时，随机获得1件3级及以下的合成・售卖专用E.G.O饰品\n第5层及以下：\\yellow{2~3级}\n第6层及以上：\\yellow{3~4级}\n进入第3层、第5层\\yellow{与第7层}时，随机获得1件所选关键词的\\yellow{4级}E.G.O饰品\n合成时，可随机获得比合成产物(3级及以上)低\\yellow{1级}的E.G.O饰品(每个商店1次)",
    },
    {
        "buff": "buff：\n主题卡包出现数量 +1\n初始饰品可选择数 +1\n进入镜像迷宫时，选择获得1件所选关键词对应的随机3级饰品(若无该等级的饰品，则会出现更低等级的饰品)\n进入镜像迷宫时，获得1个黯淡的残影",
        "buff+": "buff+：\n主题卡包出现数量 +1\n初始饰品可选择数 +1\n进入镜像迷宫时，选择获得\\yellow{2件}所选关键词对应的随机3级饰品(若无该等级的饰品，则会出现更低等级的饰品)\n进入镜像迷宫时，获得1个黯淡的残影、\\yellow{1个微茫的残影}",
        "buff++": "buff++：\n主题卡包出现数量 +1\n初始饰品可选择数 +1\n进入镜像迷宫时，选择获得\\yellow{3件}所选关键词对应的随机3级饰品(若无该等级的饰品，则会出现更低等级的饰品)\n进入镜像迷宫时，获得1个黯淡的残影、\\yellow{1个微茫的残影}与\\yellow{1个闪耀的残影}",
    },
]

STARLIGHT_BONUS_NAMES_EN = [
    "Star of the Beginning",
    "Cumulating Starcloud",
    "Interstellar Travel",
    "Star-shower",
    "Binary Star-shop",
    "Moon Star-shop",
    "Favor of the Nebulae",
    "Starlight Guidance",
    "Chance Comet",
    "Perfected Possibility",
]

STARLIGHT_BONUS_TIPS_EN = [
    {
        "buff": "buff:\nStarting Cost +150\nTheme Pack Selection +1\nShop E.G.O Gift Choice +1\n1 Free normal Refresh(es) for Shops",
        "buff+": "buff+:\nStarting Cost \\yellow{+250}\nTheme Pack Selection +1\nShop E.G.O Gift Choice +1\n1 Free normal Refresh(es) for Shops",
        "buff++": "buff++:\nStarting Cost \\yellow{+250}\nTheme Pack Selection +1\nShop E.G.O Gift Choice +1\n\\yellow{2} Free normal Refresh(es) for Shops",
    },
    {
        "buff": "buff:\nWhen moving to the next floor, increase current Cost balance by 10% (max 100)\nIncrease E.G.O Gift sale price by 50% (once per Shop)",
        "buff+": "buff+:\nWhen moving to the next floor, increase current Cost balance by \\yellow{20% (max 125)}\nIncrease E.G.O Gift sale price by \\yellow{75% (once per Shop)}",
        "buff++": "buff++:\nWhen moving to the next floor, increase current Cost balance by \\yellow{30% (max 150)}\nIncrease E.G.O Gift sale price by \\yellow{100% (once per Shop)}",
    },
    {
        "buff": "buff:\nTheme Pack Selection +1\nTheme Pack Refresh Chance +2\nWhen choosing a new Theme Pack for the first time, all Identities gain +3 Level(s) (max 9)",
        "buff+": "buff+:\nTheme Pack Selection +1\nTheme Pack Refresh Chance \\yellow{+3}\nWhen choosing a new Theme Pack for the first time, all Identities gain +3 Level(s) (max 9)\n\\yellow{If 45+ Theme Packs are unlocked in the Theme Pack Compendium, gain 1 Clash Power Up}",
        "buff++": "buff++:\nTheme Pack Refresh Chance \\yellow{+4}\nWhen choosing a new Theme Pack for the first time, all Identities gain +3 Level(s) (max 9)\n\\yellow{If 45+ Theme Packs are unlocked in the Theme Pack Compendium, gain 2 Clash Power Up}",
    },
    {
        "buff": "buff:\nStarting Cost +400\nStarting E.G.O Gift Choice +1",
        "buff+": "buff+:\nStarting Cost \\yellow{+500}\nStarting E.G.O Gift Choice +1\n\\yellow{When Choosing Starlight from Encounter Reward Cards, Cost +75}",
        "buff++": "buff++:\nStarting Cost \\yellow{+700}\nStarting E.G.O Gift Choice +1\n\\yellow{When Choosing Starlight from Encounter Reward Cards, Cost +150}",
    },
    {
        "buff": "buff:\nShop E.G.O Gift Choice +1\nEncounter Reward Cost +20%\nGreater chance for high Tier E.G.O Gifts to appear in Shops",
        "buff+": "buff+:\nShop E.G.O Gift Choice +1\nEncounter Reward Cost \\yellow{+30%}\nGreater chance for high Tier E.G.O Gifts to appear in Shops\n\\yellow{Upon entering a Shop, add up all the Tier numbers of currently owned E.G.O Gifts}",
        "buff++": "buff++:\nEncounter Reward Cost \\yellow{+40%}\nGreater chance for high Tier E.G.O Gifts to appear in Shops\n\\yellow{Upon entering a Shop, add up all the Tier numbers of currently owned E.G.O Gifts}",
    },
    {
        "buff": "buff:\n1 Free Keyword Refresh(es) for Shops\nUpon entering Floor 1, gain 1 random Tier 1 E.G.O Gift(s)",
        "buff+": "buff+:\n1 Free Keyword Refresh(es) for Shops\nUpon entering Floor 1, gain \\yellow{2} random Tier 1 E.G.O Gift(s)\n\\yellow{+10% chance for Super Shop to appear}",
        "buff++": "buff++:\n\\yellow{2} Free Keyword Refresh(es) for Shops\nUpon entering Floor 1, gain \\yellow{3} random Tier 1 E.G.O Gift(s)\n\\yellow{+25% chance for Super Shop to appear}",
    },
    {
        "buff": "buff:\nUpon entering Floor 1, all Identities gain 3 Level(s)\nUpon Floor clear, all Identities gain 1 Level(s) (max 5)",
        "buff+": "buff+:\nUpon entering Floor 1, all Identities gain 3 Level(s)\nUpon Floor clear, all Identities gain 1 Level(s) \\yellow{(max 9)}",
        "buff++": "buff++:\nUpon entering Floor 1, all Identities gain 3 Level(s)\n\\yellow{Upon entering Floor 6, all Identities gain 3 Level(s)}\nUpon Floor clear, all Identities gain 1 Level(s) \\yellow{(max 9)}",
    },
    {
        "buff": "buff:\nMax Speed +2\nGain 1 Clash Power Up\nGain 1 Damage Up\nGain 1 Protection",
        "buff+": "buff+:\nMax Speed \\yellow{+3}\nGain \\yellow{2} Clash Power Up\nGain 1 Damage Up\nGain 1 Protection",
        "buff++": "buff++:\nMax Speed \\yellow{+3}\nGain \\yellow{2} Clash Power Up\nGain \\yellow{2} Damage Up\nGain \\yellow{2} Protection",
    },
    {
        "buff": "buff:\nFuse or Sale only E.G.O Gift(s)\nUpon entering Floor 3, gain 1 random Tier 3 E.G.O Gift(s)\nWhen Fusing, gain a random additional E.G.O Gift 2 Tiers below the Fusion result(must be Tier 3 or higher) (once per Shop)",
        "buff+": "buff+:\nFuse or Sale only E.G.O Gift(s)\nFloor 5 or lower : \\yellow{Tier 1~3}\nFloor 6 or higher : \\yellow{Tier 2~3}\nUpon entering Floor 3/Floor 5, gain 1 random Tier 3 E.G.O Gift(s) from the selected Keyword category\nWhen Fusing, gain a random additional E.G.O Gift 2 Tiers below the Fusion result(must be Tier 3 or higher) (once per Shop)",
        "buff++": "buff++:\nFuse or Sale only E.G.O Gift(s)\nFloor 5 or lower : \\yellow{Tier 2~3}\nFloor 6 or higher : \\yellow{Tier 3~4}\nUpon entering Floor 3/Floor 5/Floor 7, gain 1 random Tier \\yellow{4} E.G.O Gift(s) from the selected Keyword category\nWhen Fusing, gain a random additional E.G.O Gift \\yellow{1 Tier below} the Fusion result(must be Tier 3 or higher) (once per Shop)",
    },
    {
        "buff": "buff:\nTheme Pack Selection +1\nStarting E.G.O Gift Choice +1\nUpon entry, gain 1 Tier 3 E.G.O Gift(s) of your choice for the selected Keyword (if no remaining Gifts meet the conditions, a lower Tier one will appear instead)\nUpon entry, gain 1 Dark Vestige",
        "buff+": "buff+:\nTheme Pack Selection +1\nStarting E.G.O Gift Choice +1\nUpon entry, gain \\yellow{2} Tier 3 E.G.O Gift(s) of your choice for the selected Keyword (if no remaining Gifts meet the conditions, a lower Tier one will appear instead)\nUpon entry, gain 1 Dark Vestige and \\yellow{1 Dim Vestige}",
        "buff++": "buff++:\nTheme Pack Selection +1\nStarting E.G.O Gift Choice +1\nUpon entry, gain \\yellow{3} Tier 3 E.G.O Gift(s) of your choice for the selected Keyword (if no remaining Gifts meet the conditions, a lower Tier one will appear instead)\nUpon entry, gain 1 Dark Vestige, 1 Dim Vestige, and \\yellow{1 Shining Vestige}",
    },
]


def bonus_tooltip(index, *, english=False):
    tips = STARLIGHT_BONUS_TIPS_EN if english else STARLIGHT_BONUS_TIPS
    return re.sub(r"\\yellow\{([^{}]*)\}", r"\1", "\n\n".join(tips[index].values()))


def bonus_translations():
    # Preserve Chinese source identifiers so existing editors refresh both ways.
    result = {
        f"{cn} · {level}": f"{en} · {level}"
        for cn, en in zip(STARLIGHT_BONUS_NAMES, STARLIGHT_BONUS_NAMES_EN)
        for level in range(4)
    }
    result.update({bonus_tooltip(i): bonus_tooltip(i, english=True) for i in range(len(STARLIGHT_BONUS_NAMES))})
    result.update({"星光总消耗": "Total starlight cost", "全选 · 清空": "All · Clear",
                   "全选 · 基础": "All · Base", "全选 · +": "All · +", "全选 · ++": "All · ++"})
    return result
