"""Native frameless window, with a QWidget host for Qt offscreen smoke tests.

The macOS frameless library casts winId() to NSView. Offscreen IDs are not
NSViews, so that native operation must never be used on the offscreen plugin.
"""

import os
import sys

from PySide6.QtWidgets import QApplication, QDialog, QWidget
from qfluentwidgets.components.widgets.frameless_window import FramelessWindow
from qframelesswindow import FramelessDialog


class OffscreenWindow(QWidget):
    def setTitleBar(self, title_bar):
        self.titleBar = title_bar
        title_bar.hide()

    def setResizeEnabled(self, enabled):
        self._resize_enabled = enabled

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "titleBar"):
            self.titleBar.resize(self.width(), self.titleBar.height())


class MacWindow(QWidget):
    """Let Cocoa draw the frame; retain the old titleBar UI references."""

    def setTitleBar(self, title_bar):
        self.titleBar = title_bar
        title_bar.hide()

    def setResizeEnabled(self, enabled):
        self._resize_enabled = enabled


class MacDialog(QDialog):
    def setTitleBar(self, title_bar):
        self.titleBar = title_bar
        title_bar.hide()


if sys.platform == "darwin":
    ApplicationWindow = OffscreenWindow if os.environ.get("QT_QPA_PLATFORM") == "offscreen" else MacWindow
    ApplicationDialog = MacDialog
else:
    ApplicationWindow = FramelessWindow
    ApplicationDialog = FramelessDialog


def set_dock_visible(visible: bool) -> None:
    """Switch only native macOS UI between a Dock app and a menu bar app."""
    if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
        return
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular

    policy = NSApplicationActivationPolicyRegular if visible else NSApplicationActivationPolicyAccessory
    NSApplication.sharedApplication().setActivationPolicy_(policy)
