"""macOS connection settings and a read-only capture test."""

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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
        layout.addRow(QLabel("PlayCover / MaaTools · 1920×1080"))
        self.profile = QComboBox()
        self.profile.addItem("English", "ios_en")
        self.profile.addItem("中文（日文字库汉化）", "ios_zh_cn")
        self.profile.setCurrentIndex(max(0, self.profile.findData(cfg.game_profile)))
        layout.addRow("Game image language", self.profile)
        self.host = QLineEdit(cfg.playcover_host)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(cfg.playcover_port)
        self.path = QLineEdit(cfg.playcover_app_path)
        self.bundle = QLineEdit(cfg.playcover_bundle_id)
        self.method = QComboBox()
        self.method.addItems(["bgr", "scrn"])
        self.method.setCurrentText(cfg.playcover_capture_method)
        for label, field in (("Host (loopback only)", self.host), ("Port", self.port), ("Installed game .app", self.path), ("Bundle ID", self.bundle), ("Capture method", self.method)):
            layout.addRow(label, field)
        pick = QPushButton("Choose installed .app")
        pick.clicked.connect(self.choose_app)
        layout.addRow(pick)
        save = QPushButton("Save connection settings")
        save.clicked.connect(self.save)
        layout.addRow(save)
        self.test = QPushButton("Test connection and preview screenshot (read only)")
        self.test.clicked.connect(self.test_connection)
        layout.addRow(self.test)
        self.status = QLabel("Start the game manually, then test. Enable MaaTools in PlayCover first.")
        self.status.setWordWrap(True)
        layout.addRow(self.status)
        self.setMinimumHeight(self.sizeHint().height())

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
