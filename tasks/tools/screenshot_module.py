import time

from backend_host.runtime import Signal
from backend_host.runtime import WorkerThread as QThread
from module.automation import auto
from module.backends.base import BackendCancelled
from module.config import cfg
from module.game_and_screen import screen
from module.logger import log


class ScreenshotGet(QThread):
    on_saved_timestr = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.finished.connect(self.deleteLater)

    def run(self):
        if cfg.backend == "playcover" and auto.task_running:
            log.warning("主任务运行中，请停止任务后再使用截图小工具")
            return
        should_reset_window = False
        try:
            from tasks.base.script_task_scheme import init_game

            if cfg.backend == "playcover" and not auto.task_running:
                from module.backends.factory import get_playcover_session

                session = get_playcover_session()
                session.cancel.clear()
                session.input.is_pause = False
            init_game()
            should_reset_window = cfg.set_windows and cfg.set_reduce_miscontact and cfg.backend == "windows"
        except (Exception, BackendCancelled) as e:
            log.error(f"初始化游戏失败: {str(e)}")
            return
        try:
            img = auto.take_screenshot(gray=False)
            if img:
                timestr = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                from utils.runtime_paths import data_path

                img.save(data_path(f"templates/screenshot_{timestr}.png"))
                log.info(f"图片保存为 AALC > screenshot_{timestr}.png")
                self.on_saved_timestr.emit(timestr)
            else:
                log.error("截图失败，请确认游戏是否处于启动状态")
        except (Exception, BackendCancelled) as e:
            log.error(f"截图错误: {str(e)}")
            return
        finally:
            if should_reset_window:
                screen.reset_win(activate=False)
