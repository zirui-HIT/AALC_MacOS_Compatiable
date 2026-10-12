"""macOS connection settings and a read-only capture test."""

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.language_manager import LanguageManager
from module.backends.playcover.lifecycle import read_app_identity
from module.config import cfg


class ConnectionTest(QThread):
    result = Signal(object)
    error = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings

    def run(self):
        from module.backends.playcover.session import PlayCoverSession
        from module.backends.playcover.transport import CaptureUnavailable

        session = None
        try:
            session = PlayCoverSession(self.settings)
            session.connect()
            frame = session.capture()
            self.result.emit((session.transport.bundle_id, session.transport.version, frame))
        except (OSError, ValueError, CaptureUnavailable, RuntimeError) as exc:
            self.error.emit(str(exc))
        finally:
            if session is not None:
                session.disconnect()


class PlayCoverSettings(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        layout = QFormLayout(self)
        self.form_layout = layout
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(20)
        layout.setVerticalSpacing(10)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        heading = QLabel("MaaTools · 1920 × 1080")
        heading.setObjectName("secondaryLabel")
        layout.addRow(heading)
        self.profile = QComboBox()
        self.profile.addItem("English", "ios_en")
        self.profile.addItem("中文（日文字库汉化）", "ios_zh_cn")
        self.profile.setCurrentIndex(max(0, self.profile.findData(cfg.game_profile)))
        layout.addRow(self.tr("游戏图像语言"), self.profile)
        self.host = QLineEdit(cfg.playcover_host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(cfg.playcover_port)
        self.path = QLineEdit(cfg.playcover_app_path)
        self.bundle = QLineEdit(cfg.playcover_bundle_id)
        self.method = QComboBox()
        self.method.addItems(["bgr", "scrn"])
        self.method.setCurrentText(cfg.playcover_capture_method)
        for label, field in ((self.tr("本机地址"), self.host), (self.tr("端口"), self.port), (self.tr("游戏应用"), self.path), (self.tr("应用标识"), self.bundle), (self.tr("截图方式"), self.method)):
            layout.addRow(label, field)
        pick = QPushButton(self.tr("选择游戏…"))
        self.pick_button = pick
        pick.clicked.connect(self.choose_app)
        save = QPushButton(self.tr("保存连接设置"))
        self.save_button = save
        save.clicked.connect(self.save)
        save.setDefault(True)
        actions = QHBoxLayout()
        actions.addWidget(pick)
        actions.addStretch()
        actions.addWidget(save)
        layout.addRow(actions)
        self.test = QPushButton(self.tr("测试连接与截图"))
        self.test.clicked.connect(self.test_connection)
        layout.addRow(self.test)
        self.status = QLabel(self.tr("先在 PlayCover 中启用 MaaTools，再启动游戏并测试连接。"))
        self.status.setObjectName("secondaryLabel")
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.setMinimumHeight(self.sizeHint().height())
        self._initial_status = self.status.text()
        LanguageManager().register_component(self)

    def retranslateUi(self):
        labels = [(self.profile, "游戏图像语言"), (self.host, "本机地址"), (self.port, "端口"),
                  (self.path, "游戏应用"), (self.bundle, "应用标识"), (self.method, "截图方式")]
        for field, text in labels:
            self.form_layout.labelForField(field).setText(self.tr(text))
        self.pick_button.setText(self.tr("选择游戏…"))
        self.save_button.setText(self.tr("保存连接设置"))
        self.test.setText(self.tr("测试连接与截图"))
        if self.status.text() == self._initial_status:
            self._initial_status = self.tr("先在 PlayCover 中启用 MaaTools，再启动游戏并测试连接。")
            self.status.setText(self._initial_status)

    def choose_app(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose installed Limbus Company", "", "Applications (*.app)")
        if path:
            try:
                identity = read_app_identity(path)
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))
                return
            self.path.setText(str(identity.path))
            self.bundle.setText(identity.bundle_id)

    def settings(self):
        return {
            "game_profile": self.profile.currentData(),
            "playcover_host": self.host.text().strip(), "playcover_port": self.port.value(),
            "playcover_app_path": self.path.text().strip(), "playcover_bundle_id": self.bundle.text().strip(),
            "playcover_capture_method": self.method.currentText(),
        }

    def save(self):
        from module.automation import auto
        from module.backends.configuration import migrate_backend

        try:
            if auto.task_running:
                raise ValueError("Stop the task before changing connection settings")
            settings = self.settings()
            if settings["playcover_app_path"]:
                identity = read_app_identity(settings["playcover_app_path"])
                if settings["playcover_bundle_id"] and settings["playcover_bundle_id"] != identity.bundle_id:
                    raise ValueError("Bundle ID differs from the selected app")
                settings["playcover_bundle_id"] = identity.bundle_id
                self.bundle.setText(identity.bundle_id)
            migrate_backend({**cfg.config.model_dump(), **settings})
            for key, value in settings.items():
                cfg.set_value(key, value)
            self.status.setText("Saved. Restart the game if MaaTools settings were changed in PlayCover.")
            return True
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))
            return False

    def test_connection(self):
        from module.automation import auto

        if auto.task_running or (self.worker is not None and self.worker.isRunning()):
            self.status.setText("Stop the current task/test before testing the connection")
            return
        if not self.save():
            return
        self.test.setEnabled(False)
        self.worker = ConnectionTest(self.settings(), self)
        self.worker.error.connect(self.status.setText)
        self.worker.result.connect(self.show_preview)
        self.worker.finished.connect(lambda: self.test.setEnabled(True))
        self.worker.start()

    def show_preview(self, result):
        bundle, version, frame = result
        self.status.setText(f"{bundle} · protocol {version} · raw {frame.raw_size} · touch {frame.touch_size} · logical {frame.logical_size}")
        dialog = QDialog(self)
        dialog.setWindowTitle("PlayCover capture preview")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(QPixmap.fromImage(ImageQt(frame.image)).scaledToWidth(960))
        layout.addWidget(label)
        dialog.exec()
