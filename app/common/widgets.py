"""Platform controls with the existing frontend constructor/signal contracts."""

import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
)
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    PopUpAniStackedWidget,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    ToggleToolButton,
    qconfig,
)

if sys.platform == "darwin":
    CheckBox = QCheckBox
    DoubleSpinBox = QDoubleSpinBox
    LineEdit = QLineEdit
    SpinBox = QSpinBox

    class PopUpAniStackedWidget(QStackedWidget):
        """Keep page routing, without Fluent's large entrance displacement."""

        def addWidget(self, widget, **_):
            return super().addWidget(widget)

    class PushButton(QPushButton):
        """Accept Fluent's optional leading icon without replacing any slots."""

        def __init__(self, *args, **kwargs):
            icon = None
            if args and not isinstance(args[0], str) and len(args) > 1 and isinstance(args[1], str):
                icon, args = args[0], args[1:]
            super().__init__(*args, **kwargs)
            self.setText(QPushButton.text(self))
            if icon is not None:
                self.setIcon(icon if isinstance(icon, QIcon) else icon.icon())

        def text(self):
            # Original task handlers compare this token to decide start/stop.
            return self._source_text

        def setText(self, text):
            self._source_text = text
            if text == "Link Start!":
                self.setDefault(True)
                text = QCoreApplication.translate("PushButton", "开始运行")
            super().setText(text)

    class PrimaryPushButton(PushButton):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.setDefault(True)

    class ToggleToolButton(QToolButton):
        def __init__(self, icon, parent=None):
            super().__init__(parent)
            self._source_icon = icon
            self.setCheckable(True)
            self._refresh_icon()
            qconfig.themeChanged.connect(self._refresh_icon)

        def _refresh_icon(self, *_):
            icon = self._source_icon
            self.setIcon(icon if isinstance(icon, QIcon) else icon.icon())

    class ComboBox(QComboBox):
        """Keep Fluent's (text, icon, userData) item signature on native Qt."""

        dropMenu = None

        def addItem(self, text, icon=None, userData=None):
            if icon is None:
                super().addItem(text, userData)
            else:
                super().addItem(icon if isinstance(icon, QIcon) else icon.icon(), text, userData)

        def showPopup(self):
            self.dropMenu = self.view()
            super().showPopup()

        def hidePopup(self):
            super().hidePopup()
            self.dropMenu = None
