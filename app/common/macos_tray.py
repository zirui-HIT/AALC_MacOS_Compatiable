"""AppKit status button for Qt versions that read clickCount on non-mouse events."""

import weakref

import objc
from AppKit import (
    NSApplication,
    NSEvent,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventTypeRightMouseDown,
    NSEventTypeRightMouseUp,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSSquareStatusItemLength,
    NSStatusBar,
)
from Foundation import NSData, NSObject
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon


class AALCStatusItemTarget(NSObject):
    @objc.IBAction
    def clicked_(self, sender):
        tray = self.tray_ref()
        if tray is None:
            return
        event = NSApplication.sharedApplication().currentEvent()
        # macOS 27 can deliver a gesture action with a non-mouse currentEvent.
        # Never ask it for clickCount; the Qt timer distinguishes two clicks.
        right_click = (event is not None and event.type() in (NSEventTypeRightMouseDown, NSEventTypeRightMouseUp))
        right_click = right_click or bool(NSEvent.pressedMouseButtons() & 2)
        reason = QSystemTrayIcon.ActivationReason.Context if right_click else QSystemTrayIcon.ActivationReason.Trigger
        tray.activated.emit(reason)

    @objc.IBAction
    def menuAction_(self, sender):
        tray = self.tray_ref()
        if tray is not None:
            # AppKit can send the selection after menuDidClose cleared tracking.
            # The selected item owns its action independently of the open menu.
            action = sender.representedObject()
            if action is not None:
                QTimer.singleShot(0, action.trigger)

    def menuWillOpen_(self, menu):
        tray = self.tray_ref()
        if tray is not None and tray._qt_menu is not None:
            tray._qt_menu.aboutToShow.emit()

    def menuDidClose_(self, menu):
        tray = self.tray_ref()
        if tray is not None and tray._qt_menu is not None:
            tray._qt_menu.aboutToHide.emit()
            tray._finish_menu()


class MacSystemTrayIcon(QSystemTrayIcon):
    """Retain the existing tray interface without creating Qt's Cocoa delegate."""

    def __init__(self, parent):
        super().__init__(parent)
        self._status_item = None
        self._native_menu = None
        self._qt_menu = None
        self._target = AALCStatusItemTarget.alloc().init()
        self._target.tray_ref = weakref.ref(self)
        QApplication.instance().aboutToQuit.connect(self.hide)

    def show(self):
        if self._status_item is not None:
            return
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        self.icon().pixmap(44, 44).save(buffer, "PNG")
        encoded = bytes(data)
        image = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(encoded, len(encoded)))
        image.setTemplate_(True)
        size = NSStatusBar.systemStatusBar().thickness() - 4
        image.setSize_((size, size))
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSSquareStatusItemLength)
        button = self._status_item.button()
        button.setImage_(image)
        button.setToolTip_(self.toolTip())
        button.setTarget_(self._target)
        button.setAction_("clicked:")
        button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)

    def popup_menu(self, menu):
        """Use the system menu material and keep the existing QAction callbacks."""
        if self._status_item is None or self._native_menu is not None:
            return
        native_menu = NSMenu.alloc().initWithTitle_("AALC")
        native_menu.setAutoenablesItems_(False)
        native_menu.setMinimumWidth_(220)
        native_menu.setDelegate_(self._target)
        self._qt_menu = menu
        for index, action in enumerate(menu.actions()):
            if action.isSeparator():
                item = NSMenuItem.separatorItem()
            else:
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(action.text(), "menuAction:", "")
                item.setTarget_(self._target)
                item.setRepresentedObject_(action)
                item.setEnabled_(action.isEnabled())
                if index == 0:
                    item.setImage_(NSImage.imageWithSystemSymbolName_accessibilityDescription_("macwindow", action.text()))
            native_menu.addItem_(item)
        # Attach only after the double-click interval; AppKit anchors the menu
        # to the current status item position, including screen-edge adjustment.
        self._native_menu = native_menu
        self._status_item.setMenu_(native_menu)
        try:
            self._status_item.button().performClick_(None)
        except BaseException:
            self._finish_menu()
            raise

    def _finish_menu(self):
        # An assigned menu intercepts button clicks; detach it after tracking.
        if self._status_item is not None:
            self._status_item.setMenu_(None)
        self._native_menu = None
        self._qt_menu = None

    def hide(self):
        if self._status_item is not None:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None

    def isVisible(self):
        return self._status_item is not None

    def geometry(self):
        if self._status_item is None or self._status_item.button().window() is None:
            return QRect()
        frame = self._status_item.button().window().frame()
        top = QApplication.primaryScreen().geometry().height()
        return QRect(round(frame.origin.x), round(top - frame.origin.y - frame.size.height),
                     round(frame.size.width), round(frame.size.height))
