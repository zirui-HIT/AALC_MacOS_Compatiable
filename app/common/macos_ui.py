"""macOS presentation only: colors, compact rows and public AppKit materials."""

import sys

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QFrame
from qfluentwidgets import isDarkTheme, qconfig

from utils.runtime_paths import resource_path


def colors(dark):
    return {
        "window": "#202022" if dark else "#f4f4f6",
        "surface": "#2b2b2e" if dark else "#ffffff",
        "text": "#f2f2f7" if dark else "#242426",
        "secondary": "#b0b0b8" if dark else "#64646c",
        "line": "#3b3b40" if dark else "#e2e2e7",
        "selection": "#3c3c44" if dark else "#e5e5eb",
    }


def apply_macos_theme(dark):
    """A shared palette also covers native Qt controls in separate dialogs."""
    if sys.platform != "darwin":
        return
    app = QApplication.instance()
    c = colors(dark)
    palette = app.palette()
    for role, key in ((QPalette.Window, "window"), (QPalette.Base, "surface"),
                      (QPalette.Button, "surface"), (QPalette.WindowText, "text"),
                      (QPalette.Text, "text"), (QPalette.ButtonText, "text")):
        palette.setColor(role, QColor(c[key]))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(c["secondary"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["secondary"]))
    app.setPalette(palette)


def surface_qss(dark):
    c = colors(dark)
    variant = "dark" if dark else "light"
    down = resource_path(f"assets/app/svgs/macos/chevron-down-{variant}.svg").as_posix()
    up = resource_path(f"assets/app/svgs/macos/chevron-up-{variant}.svg").as_posix()
    accent = "#78aaff" if dark else "#2874e5"
    return f"""
        QFrame#taskPanel, QWidget#parameterPanel, QWidget#logPanel {{
            background: {c['surface']}; border: 1px solid {c['line']}; border-radius: 12px;
        }}
        QLabel#sectionTitle {{ color: {c['text']}; font-size: 16px; font-weight: 600; }}
        QLabel#secondaryLabel {{ color: {c['secondary']}; font-size: 13px; }}
        QFrame#actionFooter {{ background: {c['surface']}; border-top: 1px solid {c['line']}; }}
        QPushButton, QToolButton {{ background: {c['surface']}; color: {c['text']};
            border: 1px solid {c['line']}; border-radius: 7px; padding: 5px 12px; font-size: 14px; }}
        QPushButton:hover, QToolButton:hover {{ background: {c['selection']}; }}
        QPushButton:disabled {{ color: {c['secondary']}; }}
        #link_start QPushButton {{ background: {accent}; border-color: {accent};
            color: {"#152b4d" if dark else "#ffffff"}; padding: 7px 16px; }}
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {c['surface']};
            color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px;
            padding: 4px 8px; font-size: 14px; min-height: 18px; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox::down-arrow {{ image: url('{down}'); width: 12px; height: 12px; }}
        QToolButton#toolbarTools {{ padding-right: 25px; }}
        QToolButton#toolbarTools::menu-indicator {{ image: url('{down}');
            subcontrol-origin: padding; subcontrol-position: center right;
            width: 12px; height: 12px; right: 7px; }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border;
            subcontrol-position: top right; width: 22px; border: none; }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border;
            subcontrol-position: bottom right; width: 22px; border: none; }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url('{up}'); width: 12px; height: 12px; }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url('{down}'); width: 12px; height: 12px; }}
        QCheckBox {{ font-size: 14px; spacing: 8px; color: {c['text']}; }}
        QFrame#taskPanel CheckBoxWithButton {{ border: none; border-radius: 7px; }}
        QFrame#taskPanel CheckBoxWithButton:hover {{ background: {c['selection']}; }}
        QFrame#taskPanel ToggleToolButton {{ border: none; background: transparent; }}
        QFrame#taskPanel ToggleToolButton:checked {{ background: {c['selection']}; }}
        QFrame#taskPanel QToolButton:checked {{ background: {c['selection']}; }}
        QWidget#logPanel QToolButton {{ background: transparent; border: none; padding: 4px 0; }}
        QFrame#navFrame {{ background: {c['surface']}; border: none; border-radius: 10px; }}
        QFrame#navFrame QPushButton {{ border: none; background: transparent;
            text-align: left; padding: 9px 12px; color: {c['secondary']}; border-radius: 7px; }}
        QFrame#navFrame QPushButton:checked {{ background: {c['selection']}; color: {c['text']}; }}
    """


class MacSettingRow:
    """Restyle existing setting-card wrappers, leaving their slots intact."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if sys.platform != "darwin":
            return
        self.iconLabel.hide()
        self.hBoxLayout.setContentsMargins(14, 6, 0, 6)
        self.hBoxLayout.setSpacing(0)
        # Remove the spacer belonging to the decorative icon.
        self.hBoxLayout.takeAt(1)
        self.hBoxLayout.setStretch(1, 1)
        self.hBoxLayout.setStretch(3, 0)
        self.vBoxLayout.setAlignment(self.titleLabel, Qt.Alignment())
        self.vBoxLayout.setAlignment(self.contentLabel, Qt.Alignment())
        self.titleLabel.setWordWrap(True)
        self.contentLabel.setWordWrap(True)
        self.titleLabel.setMaximumWidth(430)
        self.contentLabel.setMaximumWidth(430)
        self.setToolTip(self.contentLabel.text())
        if len(self.contentLabel.text()) > 60:
            self.contentLabel.hide()
        self.setFixedHeight(82 if not self.contentLabel.isHidden() else 58)
        self.setStyleSheet("QLabel { font-size: 14px; background: transparent; } "
                           "QLabel#contentLabel { font-size: 12px; }")
        self._mac_row_ready = True

    def setContent(self, content):
        super().setContent(content)
        if sys.platform == "darwin":
            self.setToolTip(content or "")
            if len(content or "") > 60:
                self.contentLabel.hide()
            self._fit_text()

    def _fit_text(self):
        if not getattr(self, "_mac_row_ready", False) or getattr(self, "_fitting_text", False):
            return
        self._fitting_text = True
        try:
            self._fit_text_geometry()
        finally:
            self._fitting_text = False

    def _fit_text_geometry(self):
        controls = sum(self.hBoxLayout.itemAt(i).widget().sizeHint().width()
                       for i in range(self.hBoxLayout.count())
                       if self.hBoxLayout.itemAt(i).widget() is not None
                       and not self.hBoxLayout.itemAt(i).widget().isHidden())
        spacers = sum(self.hBoxLayout.itemAt(i).spacerItem().sizeHint().width()
                      for i in range(self.hBoxLayout.count())
                      if self.hBoxLayout.itemAt(i).spacerItem() is not None)
        margins = self.hBoxLayout.contentsMargins()
        width = max(120, self.width() - controls - spacers - margins.left() - margins.right())
        self.titleLabel.setMaximumWidth(width)
        self.contentLabel.setMaximumWidth(width)
        height = self._text_height(self.titleLabel, width)
        self.titleLabel.setFixedHeight(height)
        if not self.contentLabel.isHidden():
            content_height = self._text_height(self.contentLabel, width)
            self.contentLabel.setFixedHeight(content_height)
            height += content_height
        height = max(58, height + 20)
        if self.height() != height:
            self.setFixedHeight(height)
            group = self.parentWidget()
            if group is not None and hasattr(group, "cardLayout"):
                QTimer.singleShot(0, group.adjustSize)

    @staticmethod
    def _text_height(label, width):
        # QLabel.heightForWidth includes its minimum height; measuring the text
        # directly avoids feeding a previous layout's fixed height back into it.
        metrics = label.fontMetrics()
        measured = metrics.boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, label.text()).height()
        return max(metrics.height(), measured) + 4

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if sys.platform == "darwin":
            self._fit_text()

    def event(self, event):
        handled = super().event(event)
        if event.type() == QEvent.LayoutRequest and getattr(self, "_mac_row_ready", False):
            self._fit_text()
        return handled

    def paintEvent(self, event):
        if sys.platform != "darwin":
            return super().paintEvent(event)
        c = colors(isDarkTheme())
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(c["surface"]))
        painter.setPen(QColor(c["line"]))
        painter.drawLine(14, self.height() - 1, self.width() - 14, self.height() - 1)


class GlassPanel(QFrame):
    """A transparent Qt control layer above a sibling AppKit material view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("glassToolbar")
        self._native_effect = None
        self.material_name = "solid"
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)
        qconfig.themeChanged.connect(self._update_appearance)
        self._update_appearance()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._attach_material)

    def _attach_material(self):
        if self._native_effect is not None or QApplication.platformName() != "cocoa":
            return
        import AppKit
        import objc

        try:
            view = objc.objc_object(c_void_p=int(self.winId()))
            parent = view.superview()
            if parent is None:
                return
            try:
                effect_class = objc.lookUpClass("NSGlassEffectView")
            except objc.nosuchclass_error:
                effect_class = AppKit.NSVisualEffectView
            effect = effect_class.alloc().initWithFrame_(view.frame())
            if effect_class == AppKit.NSVisualEffectView:
                effect.setMaterial_(AppKit.NSVisualEffectMaterialSidebar)
                effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
                self.material_name = "NSVisualEffectView"
            else:
                effect.setCornerRadius_(14.0)
                self.material_name = "NSGlassEffectView"
            parent.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, view)
            self._native_effect = effect
            self._update_appearance()
        except (ImportError, AttributeError, RuntimeError, ValueError, objc.error):
            # A solid toolbar is still usable on older/offscreen Qt hosts.
            self.material_name = "solid"

    def _update_appearance(self, *_):
        c = colors(isDarkTheme())
        background = "transparent" if self._native_effect is not None else c["surface"]
        self.setStyleSheet(f"QFrame#glassToolbar {{ background: {background}; border-radius: 14px; }}")
        if self._native_effect is not None:
            import AppKit

            name = AppKit.NSAppearanceNameDarkAqua if isDarkTheme() else AppKit.NSAppearanceNameAqua
            self._native_effect.setAppearance_(AppKit.NSAppearance.appearanceNamed_(name))

    def _sync_material(self):
        if self._native_effect is not None:
            import objc

            view = objc.objc_object(c_void_p=int(self.winId()))
            self._native_effect.setFrame_(view.frame())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_material()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._sync_material()


def system_font():
    font = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    font.setPixelSize(16)
    return font


class LogResizeHandle(QFrame):
    """Resize only the visible log pane, without reparenting task widgets."""

    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.setFixedHeight(6)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(self.tr("拖动调整日志高度"))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._start_y = event.globalPosition().y()
            self._start_height = self.target.height()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, "_start_y"):
            height = self._start_height - int(event.globalPosition().y() - self._start_y)
            self.target.setFixedHeight(max(80, min(self.window().height() - 400, height)))
            event.accept()
