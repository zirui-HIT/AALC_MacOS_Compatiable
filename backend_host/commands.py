"""Original command parser; GUI checkbox assignments call the same config setter."""
from module.after_completion_types import (
    LEGACY_AFTER_COMPLETION_TO_CONFIG,
    POWER_ACTION_NONE,
    normalize_after_completion_config,
)
from module.config import cfg
from module.logger import log
from module.system_actions import autodaily_exit_to_after_completion_config


def parse_command(argv):
    skip_arg_times = 0
    start_flag = False
    exit_flag = False
    exit_type = 0
    parsed_actions = None
    parsed_power_action = None
    last_cmd = ""
    # 读取输入参数
    for index, arg in enumerate(argv):
        if index == 0:
            # 跳过第一个参数（程序路径）
            continue
        if skip_arg_times > 0:
            # 读取参数后可以跳过的次数
            # 运行一个控制语句读取多个参数
            skip_arg_times -= 1
            continue
        if arg == "start":
            start_flag = True
            last_cmd = "start"
            continue
        if arg == "--exit" and last_cmd == "start":
            exit_flag = True
            skip_arg_times = 1
            exit_type = 5
            try:
                if isinstance(argv[index + 1], str) and argv[index + 1].startswith("autodaily"):
                    exit_task = cfg.get_value(argv[index + 1] + "_task_exit")
                    actions, power_action = autodaily_exit_to_after_completion_config(exit_task)
                    parsed_actions = actions
                    parsed_power_action = power_action
                    exit_type = 0
                    autodaily_task = cfg.get_value(argv[index + 1] + "_task")
                    if autodaily_task[0]:
                        cfg.set_value("daily_task", True)
                    else:
                        cfg.set_value("daily_task", False)
                    if autodaily_task[1]:
                        cfg.set_value("get_reward", True)
                    else:
                        cfg.set_value("get_reward", False)
                    if autodaily_task[2]:
                        cfg.set_value("buy_enkephalin", True)
                    else:
                        cfg.set_value("buy_enkephalin", False)
                    if autodaily_task[3]:
                        cfg.set_value("mirror", True)
                    else:
                        cfg.set_value("mirror", False)
                else:
                    exit_type = int(argv[index + 1])
                    if exit_type < 0 or exit_type > 8:
                        exit_type = 0
                        log.error(f'命令行参数 --exit 后输入值"{argv[index + 1]}"越界')
            except (IndexError, ValueError):
                # 由于输入值为可选, 所以在强制int失败或缺少时将跳过参数数值重置为0
                skip_arg_times = 0
                log.info("命令行参数 --exit 后缺少退出类型，默认为5, 即退出AALC")
            except Exception as e:
                exit_type = 0
                skip_arg_times = 0
                log.error(f"命令行参数 --exit 未知错误: {e}")
            continue

    # 最终执行操作
    completion = None
    if exit_flag:
        if parsed_actions is not None and parsed_power_action is not None:
            actions, power_action = parsed_actions, parsed_power_action
        else:
            actions, power_action = normalize_after_completion_config(
                *LEGACY_AFTER_COMPLETION_TO_CONFIG.get(exit_type, ((), POWER_ACTION_NONE))
            )
        completion = actions, power_action
    return start_flag, completion
