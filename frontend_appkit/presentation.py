"""Native layout and material helpers. No configuration or execution state."""

import json

import AppKit as A
from objc import super

from frontend_appkit import widgets
from frontend_appkit.widgets import FlippedView, action, label

TOOLBAR_SLOT_WIDTH = 88
TOOLBAR_HEIGHT = 36
TOOLBAR_PADDING = 8


def hover_tracking(view, *, moved=False):
    previous = getattr(view, "hover_tracking_area", None)
    if previous:
        view.removeTrackingArea_(previous)
    options = A.NSTrackingMouseEnteredAndExited | A.NSTrackingActiveInKeyWindow | A.NSTrackingInVisibleRect
    if moved:
        options |= A.NSTrackingMouseMoved
    area = A.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(view.bounds(), options, view, None)
    view.addTrackingArea_(area)
    view.hover_tracking_area = area


class QuietSegments(A.NSSegmentedControl):
    """Native segment actions with separate location and pointer feedback."""

    def updateTrackingAreas(self):
        super().updateTrackingAreas()
        hover_tracking(self, moved=True)

    def mouseMoved_(self, event):
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        hovered, x = -1, 0
        if self.isEnabled() and 0 <= point.y <= self.bounds().size.height:
            for index in range(self.segmentCount()):
                width = self.widthForSegment_(index)
                if x <= point.x < x + width:
                    hovered = index
                    break
                x += width
        self.hovered_segment = hovered
        self.setNeedsDisplay_(True)

    def mouseEntered_(self, event):
        self.mouseMoved_(event)

    def mouseExited_(self, event):
        self.hovered_segment = -1
        self.setNeedsDisplay_(True)

    def setEnabled_(self, enabled):
        super().setEnabled_(enabled)
        if not enabled:
            self.hovered_segment = -1
        self.setNeedsDisplay_(True)

    def drawRect_(self, rect):
        height, x = self.bounds().size.height, 0
        for index in range(self.segmentCount()):
            width = self.widthForSegment_(index)
            selected = self.selectedSegment() == index
            hovered = self.isEnabled() and getattr(self, "hovered_segment", -1) == index
            if hovered:
                A.NSColor.labelColor().colorWithAlphaComponent_(0.09).setFill()
                A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x + 2, 2), (width - 4, height - 4)), 12, 12).fill()
            color = A.NSColor.disabledControlTextColor() if not self.isEnabled() else A.NSColor.labelColor() if selected else A.NSColor.secondaryLabelColor()
            title = A.NSAttributedString.alloc().initWithString_attributes_(self.labelForSegment_(index), {A.NSFontAttributeName: A.NSFont.systemFontOfSize_weight_(12, A.NSFontWeightSemibold if selected else A.NSFontWeightRegular), A.NSForegroundColorAttributeName: color})
            size = title.size()
            title.drawAtPoint_((x + (width - size.width) / 2, (height - size.height) / 2))
            if selected:
                color.setFill()
                y = height - 4 if self.isFlipped() else 2
                A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x + (width - 18) / 2, y), (18, 2)), 1, 1).fill()
            x += width


class LayoutView(FlippedView):
    def drawRect_(self, rect):
        dark = self.effectiveAppearance().bestMatchFromAppearancesWithNames_([A.NSAppearanceNameAqua, A.NSAppearanceNameDarkAqua]) == A.NSAppearanceNameDarkAqua
        (A.NSColor.underPageBackgroundColor() if dark else A.NSColor.windowBackgroundColor()).setFill()
        A.NSBezierPath.fillRect_(rect)

    def resizeSubviewsWithOldSize_(self, old_size):
        super().resizeSubviewsWithOldSize_(old_size)
        handler = getattr(self, "layout_handler", None)
        if handler:
            handler()


class SurfaceView(FlippedView):
    def drawRect_(self, rect):
        grouped = getattr(self, "kind", "row") == "group"
        if not grouped and not (getattr(self, "selected", False) or getattr(self, "hovered", False)):
            return
        dark = self.effectiveAppearance().bestMatchFromAppearancesWithNames_([A.NSAppearanceNameAqua, A.NSAppearanceNameDarkAqua]) == A.NSAppearanceNameDarkAqua
        color = (A.NSColor.windowBackgroundColor() if dark else A.NSColor.controlBackgroundColor()) if grouped else A.NSColor.controlAccentColor().colorWithAlphaComponent_(0.22 if getattr(self, "hovered", False) else 0.14) if getattr(self, "selected", False) else A.NSColor.labelColor().colorWithAlphaComponent_(0.06)
        color.setFill()
        path = A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 10 if grouped else 8, 10 if grouped else 8)
        path.fill()

    def viewDidChangeEffectiveAppearance(self):
        self.setNeedsDisplay_(True)


class TaskRow(SurfaceView):
    def updateTrackingAreas(self):
        super().updateTrackingAreas()
        hover_tracking(self)

    def mouseEntered_(self, event):
        self.hovered = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self.hovered = False
        self.setNeedsDisplay_(True)

    def hitTest_(self, point):
        hit = super().hitTest_(point)
        return hit if hit is None or isinstance(hit, A.NSButton) else self

    def mouseDown_(self, event):
        callback = getattr(self, "select_callback", None)
        if callback:
            callback()

    def accessibilityPerformPress(self):
        callback = getattr(self, "select_callback", None)
        if callback:
            callback()
            return True
        return False


def glass(parent, frame):
    cls = getattr(A, "NSGlassEffectView", None)
    if cls:
        panel = cls.alloc().initWithFrame_(frame)
        panel.setCornerRadius_(16)
        content = FlippedView.alloc().initWithFrame_(((0, 0), frame[1]))
        content.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        panel.setContentView_(content)
    else:
        panel = A.NSVisualEffectView.alloc().initWithFrame_(frame)
        panel.setMaterial_(A.NSVisualEffectMaterialSidebar)
        panel.setBlendingMode_(A.NSVisualEffectBlendingModeWithinWindow)
        content = FlippedView.alloc().initWithFrame_(((0, 0), frame[1]))
        content.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        panel.addSubview_(content)
    if parent is not None:
        parent.addSubview_(panel)
    return panel, content


def segmented(parent, titles, frame, callback, targets, *, quiet=False):
    control = (QuietSegments if quiet else A.NSSegmentedControl).alloc().initWithFrame_(frame)
    control.setSegmentCount_(len(titles))
    control.setIdentifier_("segments:" + json.dumps(titles, ensure_ascii=False))
    control.setSegmentStyle_(A.NSSegmentStyleRounded)
    control.setFont_(A.NSFont.systemFontOfSize_(12))
    for index, title in enumerate(titles):
        control.setLabel_forSegment_(widgets.translate(title), index)
        control.setWidth_forSegment_(frame[1][0] / len(titles), index)
    control.setSelectedSegment_(0)
    action(control, callback, targets)
    if parent is not None:
        parent.addSubview_(control)
    return control


def subtitle(parent, title, frame):
    view = label(parent, title, frame, size=11)
    view.setTextColor_(A.NSColor.secondaryLabelColor())
    return view


def icon(control, name, description):
    image = A.NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, description)
    if image:
        image.setSize_((16, 16))
        control.setImage_(image)
        control.setImagePosition_(A.NSImageOnly)
    control.setAccessibilityLabel_(description)
    control.setToolTip_(description)


def menu_button(parent, title, frame, entries, targets):
    control = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(frame, True)
    control.setFont_(A.NSFont.systemFontOfSize_(12))
    control.addItemWithTitle_(widgets.translate(title))
    control.menu().setAutoenablesItems_(False)
    control.setIdentifier_("choices:" + json.dumps([[title, 0]], ensure_ascii=False))
    for label_, callback in entries:
        item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(widgets.translate(label_), None, "")
        item.setRepresentedObject_(label_)
        symbol = {"上移": "arrow.up", "下移": "arrow.down", "复制": "doc.on.doc", "删除": "trash", "导出 YAML": "square.and.arrow.up", "导入 YAML": "square.and.arrow.down", "复制配置码": "doc.on.doc", "粘贴配置码": "doc.on.clipboard", "重置默认": "arrow.counterclockwise", "拉取全局": "arrow.down.circle", "全部设为 -5": "minus.circle"}.get(label_)
        if symbol:
            item.setImage_(A.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, widgets.translate(label_)))
        widgets.action(item, lambda sender, callback=callback: callback(), targets)
        control.menu().addItem_(item)
    if parent is not None:
        parent.addSubview_(control)
    return control


def toolbar_glass(control):
    width, height = control.frame().size
    panel, content = glass(None, ((0, 0), (width + 2 * TOOLBAR_PADDING, TOOLBAR_HEIGHT)))
    # NSToolbar measures custom views through Auto Layout. A glass view with
    # frame-only children has no intrinsic size and otherwise collapses to zero.
    panel.widthAnchor().constraintEqualToConstant_(width + 2 * TOOLBAR_PADDING).setActive_(True)
    panel.heightAnchor().constraintEqualToConstant_(TOOLBAR_HEIGHT).setActive_(True)
    if hasattr(panel, "setCornerRadius_"):
        panel.setCornerRadius_(TOOLBAR_HEIGHT / 2)
    if hasattr(panel, "setEffectIsInteractive_"):
        panel.setEffectIsInteractive_(True)
    control.setFrame_(((TOOLBAR_PADDING, (TOOLBAR_HEIGHT - height) / 2), (width, height)))
    control.setAutoresizingMask_(A.NSViewWidthSizable)
    content.addSubview_(control)
    return panel


def template_image(path):
    image = A.NSImage.alloc().initWithSize_((22, 22))
    for suffix in (".png", "@2x.png"):
        representation = A.NSBitmapImageRep.imageRepWithContentsOfFile_(str(path.with_name(path.stem + suffix)))
        if representation:
            representation.setSize_((22, 22))
            image.addRepresentation_(representation)
    image.setTemplate_(True)
    return image
