from backend_host.notifications import mediator
from backend_host.translation import translate
from module.config import TeamSetting, cfg
from module.logger import log
from utils.utils import check_hard_mirror_time


def validate_theme(values):
    if not isinstance(values, dict):
        raise ValueError("Theme weights must be a mapping")
    for key in ("theme_pack_list", "theme_pack_list_hard", "theme_pack_list_cn", "theme_pack_list_hard_cn"):
        weights = values.get(key, {})
        if not isinstance(weights, dict) or any(
            not isinstance(pack, str) or not pack or not isinstance(weight, int) or isinstance(weight, bool) or not -10 <= weight <= 10
            for pack, weight in weights.items()
        ):
            raise ValueError("Theme weights must map names to integers from -10 to 10")
    threshold = values.get("preferred_thresholds", 0)
    if not isinstance(threshold, int) or isinstance(threshold, bool) or not -10 <= threshold <= 10:
        raise ValueError("Preferred threshold must be an integer from -10 to 10")
    forbidden = values.get("forbidden_theme_packs", {})
    if not isinstance(forbidden, dict) or any(
        not isinstance(scope, str) or not isinstance(names, list)
        or any(not isinstance(name, str) or not name for name in names)
        for scope, names in forbidden.items()
    ):
        raise ValueError("Forbidden theme packs must map scopes to lists of names")


def check_setting():
    self = _Translations()
    if cfg.mirror:
        # 判断是否启用了自动切换困牢
        if cfg.auto_hard_mirror:
            from datetime import datetime

            if cfg.last_auto_change == 1715990400:
                cfg.set_value("last_auto_change", datetime.now().timestamp())
                cfg.flush()
            if check_hard_mirror_time():
                log.info("识别到新的困牢周期，自动切换困难镜牢，设置困牢次数为3")
                cfg.set_value("last_auto_change", datetime.now().timestamp())
                cfg.set_value("hard_mirror", True)
                cfg.set_value("hard_mirror_chance", 3)
                cfg.flush()
            # 自动切换到困难模式时，同步保留困难模式开关状态
            if cfg.hard_mirror_chance > 0:
                cfg.set_value("hard_mirror", True)
                log.debug(f"困难镜牢模式启用中，剩余次数：{cfg.hard_mirror_chance}")

        # 检查队伍配置状况
        teams_be_select = sum(1 for team in cfg.teams_be_select if team)
        if teams_be_select != cfg.teams_be_select_num:
            cfg.normalize_and_sync_team_state()
            cfg.flush()

        if cfg.teams_be_select_num == 0:
            message = self.tr("没有启用任何队伍，请选择一个队伍进行镜牢任务")
            mediator.warning.emit(message)
            return False

        # 检测是否有未配置角色选择的队伍
        teams_be_select = cfg.get_value("teams_be_select")
        for index in (i for i, t in enumerate(teams_be_select) if t is True):
            team_setting: TeamSetting = cfg.config.teams[f"{index + 1}"]
            if team_setting.sinners_be_select == 0:
                message = self.tr("存在未配置角色选择的队伍：TEAM_{0}")
                mediator.warning.emit(message.format(index + 1))
                return False

        # 检测配置的队伍能否顺利执行
        useful = False
        hard = bool(cfg.hard_mirror)
        teams_be_select = cfg.get_value("teams_be_select")
        for index in (i for i, t in enumerate(teams_be_select) if t is True):
            team_setting: TeamSetting = cfg.config.teams[f"{index + 1}"]
            if team_setting.fixed_team_use is False:
                useful = True
                break
            if team_setting.fixed_team_use_select == 1 and hard is False:
                useful = True
                break
            if team_setting.fixed_team_use_select == 0 and hard is True:
                useful = True
                break
        if useful is False:
            if hard:
                message = self.tr("启用了困牢，但是无可用于困牢的队伍")
            else:
                message = self.tr("启用了普牢，但是无可用于普牢的队伍")
            mediator.warning.emit(message)
            return False

    if cfg.daily_task is False and cfg.get_reward is False and cfg.buy_enkephalin is False and cfg.mirror is False:
        mediator.tasks_warning.emit()
        return False

class _Translations:
    def tr(self, text):
        return translate("FarmingInterfaceLeft", text)
