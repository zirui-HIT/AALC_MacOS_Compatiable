"""
utils.schedule_helper: 计划任务的帮助类的实现
"""

import datetime
import getpass
import os
import plistlib
import shlex
import subprocess
import sys

from utils.runtime_paths import data_path

if os.name == "nt":
    import winreg

    import win32com.client
    from pywintypes import com_error

from module.logger import log


class ScheduleHelper:
    """
    计划任务的帮助类
    """

    def __init__(self):
        # 分离平台细节, 如果日后有跨平台需求能少写很多代码
        if os.name == "nt":
            self._impl = ScheduleHelper_Win32()
        elif sys.platform == "darwin":
            self._impl = ScheduleHelper_MacOS()
        else:
            raise RuntimeError("未知平台")

    def register_daily_task(self, task_name: str, cmd_line: str, h: int, m: int):
        """
        注册每日任务

        :param task_name: 任务名称
        :type task_name: str
        :param cmd_line: 命令行
        :type cmd_line: str
        :param h: 时
        :type h: int
        :param m: 分
        :type m: int
        """
        if (h not in range(24)) or (m not in range(60)):
            raise ValueError("无效参数")
        self._impl.register_daily_task(task_name, cmd_line, h, m)

    def register_onstart_task(self, task_name: str, cmd_line: str):
        """
        注册启动任务

        :param task_name: 任务名称
        :type task_name: str
        :param cmd_line: 命令行
        :type cmd_line: str
        """
        self._impl.register_onstart_task(task_name, cmd_line)

    def unregister_task(self, task_name: str):
        """
        注销任务

        :param task_name: 任务名称
        :type task_name: str
        """
        self._impl.unregister_task(task_name)
        log.info("移除每日任务成功")

    def restore_daily_tasks(self, config):
        """Restore portable launchd jobs when AALC enters a new macOS login session."""
        if sys.platform != "darwin":
            return
        for suffix in ("", "2", "3", "4"):
            name = "autodaily" + suffix
            if config.get_value(name, False):
                try:
                    value = config.get_value("autodaily_time" + suffix, "00:00")
                    time = datetime.datetime.strptime(value, "%H:%M")
                    self.register_daily_task("AALC Daily Task" + suffix, f"start --exit {name}", time.hour, time.minute)
                except Exception:
                    log.exception("恢复 macOS 定时任务 %s 失败", name)


class ScheduleHelper_MacOS:
    """User-session launchd adapter; plist files and logs stay in .runtime."""

    _labels = {
        "AALC Daily Task": "io.aalc.PlayCover.daily1",
        "AALC Daily Task2": "io.aalc.PlayCover.daily2",
        "AALC Daily Task3": "io.aalc.PlayCover.daily3",
        "AALC Daily Task4": "io.aalc.PlayCover.daily4",
        "AALC Autostart": "io.aalc.PlayCover.autostart",
    }

    def __init__(self):
        self.directory = data_path("schedules")
        self.domain = f"gui/{os.getuid()}"

    @staticmethod
    def _launchctl(*arguments, check=True):
        return subprocess.run(["/bin/launchctl", *arguments], check=check,
                              capture_output=True, text=True, timeout=10)

    def _definition(self, task_name, cmd_line):
        label = self._labels[task_name]
        # Use main.py's existing resident-instance protocol without starting a
        # second Python/app from launchd's macOS privacy context.
        payload = shlex.quote("|".join(shlex.split(cmd_line)))
        command = f"printf '%s\\n' {payload} | /usr/bin/nc -w 2 -G 1 127.0.0.1 62333"
        return {
            "Label": label,
            "ProgramArguments": ["/bin/sh", "-c", command],
            # AALC resolves its resources/data absolutely. launchd's getcwd in
            # a protected Downloads directory can wait on macOS privacy access.
            "WorkingDirectory": "/",
            "LimitLoadToSessionType": "Aqua",
            "ProcessType": "Interactive",
            "StandardOutPath": str(self.directory / f"{label}.stdout.log"),
            "StandardErrorPath": str(self.directory / f"{label}.stderr.log"),
        }

    def _register(self, definition):
        label = definition["Label"]
        target = f"{self.domain}/{label}"
        path = self.directory / f"{label}.plist"
        loaded = self._launchctl("print", target, check=False).returncode == 0
        if path.is_file() and loaded:
            with path.open("rb") as file:
                if plistlib.load(file) == definition:
                    return
        if loaded:
            self._launchctl("bootout", target)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".plist.tmp")
        try:
            with temporary.open("wb") as file:
                plistlib.dump(definition, file)
            temporary.chmod(0o600)
            temporary.replace(path)
            self._launchctl("bootstrap", self.domain, str(path))
        finally:
            temporary.unlink(missing_ok=True)

    def register_daily_task(self, task_name, cmd_line, h, m):
        definition = self._definition(task_name, cmd_line)
        definition["StartCalendarInterval"] = {"Hour": h, "Minute": m}
        self._register(definition)
        log.info("创建 macOS 每日任务成功，执行时间为每日 %02d:%02d", h, m)

    def register_onstart_task(self, task_name, cmd_line):
        raise NotImplementedError("macOS login autostart is not enabled; start AALC before its daily tasks")

    def unregister_task(self, task_name):
        label = self._labels[task_name]
        target = f"{self.domain}/{label}"
        if self._launchctl("print", target, check=False).returncode == 0:
            self._launchctl("bootout", target)
        (self.directory / f"{label}.plist").unlink(missing_ok=True)


class ScheduleHelper_Win32:
    """
    Schedule Helper 在 Win32 平台的实现
    """

    def __init__(self):
        self.scheduler = win32com.client.Dispatch("Schedule.Service")
        self.scheduler.Connect()
        self.root = self.scheduler.GetFolder("\\")

    def register_daily_task(self, task_name: str, cmd_line: str, h: int, m: int):
        task_def = self.scheduler.NewTask(0)
        task_def.RegistrationInfo.Description = "AALC Daily Task"
        task_def.RegistrationInfo.Author = getpass.getuser()

        trigger = task_def.Triggers.Create(2)  # 每日触发器
        trigger.StartBoundary = datetime.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).isoformat()
        trigger.DaysInterval = 1
        trigger.Enabled = True

        action = task_def.Actions.Create(0)
        action.Path = sys.executable
        action.Arguments = cmd_line
        action.WorkingDirectory = os.path.dirname(sys.executable)

        task_def.Principal.RunLevel = 1  # 管理员权限运行
        task_def.Principal.LogonType = 3
        task_def.Principal.Id = task_name
        task_def.Settings.Enabled = True
        task_def.Settings.Hidden = False
        task_def.Settings.ExecutionTimeLimit = "PT0S"
        task_def.Settings.DisallowStartIfOnBatteries = False
        task_def.Settings.StopIfGoingOnBatteries = False

        try:
            self.root.RegisterTaskDefinition(task_name, task_def, 6, None, None, 3)
            log.info(
                f"创建每日任务成功，执行时间为每日{h:02d}:{m:02d}"
            )
        except com_error as e:
            log.error(f"创建任务 {task_name} 失败")
            raise e

    def register_onstart_task(self, task_name: str, cmd_line: str):
        task_def = self.scheduler.NewTask(0)
        task_def.RegistrationInfo.Description = "AALC OnStart Task"
        task_def.RegistrationInfo.Author = getpass.getuser()

        trigger = task_def.Triggers.Create(9)  # 登录触发器
        trigger.Enabled = True

        action = task_def.Actions.Create(0)
        action.Path = sys.executable
        action.Arguments = cmd_line
        action.WorkingDirectory = os.path.dirname(sys.executable)

        task_def.Principal.RunLevel = 1  # 管理员权限运行
        task_def.Principal.LogonType = 3
        task_def.Principal.Id = task_name
        task_def.Settings.Enabled = True
        task_def.Settings.Hidden = False
        task_def.Settings.ExecutionTimeLimit = "PT0S"
        task_def.Settings.DisallowStartIfOnBatteries = False
        task_def.Settings.StopIfGoingOnBatteries = False

        try:
            self.root.RegisterTaskDefinition(task_name, task_def, 6, None, None, 3)
        except com_error as e:
            log.error(f"创建任务 {task_name} 失败")
            raise e

    def unregister_task(self, task_name: str):
        def unregister_onstart_task_registry(self, task_name):
            """
            删除自启动项
            """
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, task_name)
                winreg.CloseKey(key)
                log.debug(f"已移除启动项: {task_name}")
            except FileNotFoundError:
                pass  # 已经不存在了
            except Exception as e:
                log.debug(f"通过移除注册表移除启动项失败: {e}")

        try:
            if task_name == "AALC Autostart":
                unregister_onstart_task_registry(self, task_name)
            self.root.DeleteTask(task_name, 0)
        except com_error as e:
            log.warning(f"尝试删除不存在的任务 {task_name}")
            raise e
