from backend_host.runtime import Signal
from backend_host.runtime import WorkerThread as QThread
from module.automation import auto
from module.config import cfg
from module.logger import log
from tasks.battle.battle import Battle
from utils.path_manager import path_manager


class BattleWorker(QThread):
    """战斗逻辑工作线程，避免阻塞UI"""

    battle_executed = Signal()
    error_occurred = Signal(str)
    initialization_complete = Signal()

    def __init__(
        self,
        defense=False,
        defense_on_turn1=False,
        choice_event_handling=True,
        parent=None,
    ):
        super().__init__(parent)
        self.defense = defense
        self.defense_on_turn1 = defense_on_turn1
        self.choice_event_handling = choice_event_handling
        self.initialized = False
        self.battle = Battle(is_tool=True)  # 复用镜牢战斗逻辑
        self.background_click = cfg.background_click

    def stop(self):
        """停止工作线程"""
        self.battle.running = False
        if self.background_click is False:
            cfg.set_value("background_click", False)

    def run(self):
        """工作线程的主循环"""
        # 首先进行游戏初始化
        if not self.initialized:
            try:
                from tasks.base.script_task_scheme import init_game

                init_game()
                self._set_win()
                path_manager.initialize_paths(reset_eliminations=False)
                auto.clear_img_cache()
                log.debug(f"初始化图片路径: {path_manager.pic_path}")
                self.initialized = True
                self.initialization_complete.emit()
            except Exception as e:
                self.error_occurred.emit(f"游戏初始化错误: {str(e)}")
                self.msleep(2000)
                return
        self.battle.fight(
            infinite_battle=True,
            defense_on_turn1=self.defense_on_turn1,
            defense_all_time=self.defense,
            choice_event_handling=self.choice_event_handling,
        )

    def _set_win(self):
        try:
            from backend_host.platform_window import screen

            if not self.background_click:
                cfg.set_value("background_click", True)
            screen.set_win()
        except Exception as e:
            self.error_occurred.emit(f"窗口设置错误: {str(e)}")
