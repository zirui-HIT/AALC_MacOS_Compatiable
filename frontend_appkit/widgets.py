"""Small native view builders; presentation only."""

import json

import AppKit as A
from Foundation import NSData, NSMapTable, NSObject, NSUTF8StringEncoding

_tooltip_sources = NSMapTable.weakToStrongObjectsMapTable()
_accessibility_sources = NSMapTable.weakToStrongObjectsMapTable()


def translate(text):
    return text


def tooltip(control, source):
    _tooltip_sources.setObject_forKey_(source, control)
    control.setToolTip_(translate(source))


def accessibility_label(control, source):
    _accessibility_sources.setObject_forKey_(source, control)
    control.setAccessibilityLabel_(translate(source))


def attributed_html(source):
    encoded = source.encode("utf-8")
    data = NSData.dataWithBytes_length_(encoded, len(encoded))
    attributed, _ = A.NSAttributedString.alloc().initWithHTML_options_documentAttributes_(data, {A.NSCharacterEncodingDocumentAttribute: NSUTF8StringEncoding}, None)
    return attributed


def refresh(view):
    tooltip_source = _tooltip_sources.objectForKey_(view)
    if tooltip_source is not None:
        view.setToolTip_(translate(tooltip_source))
    accessibility_source = _accessibility_sources.objectForKey_(view)
    if accessibility_source is not None:
        view.setAccessibilityLabel_(translate(accessibility_source))
    source = view.identifier()
    if source and str(source).startswith("segments:"):
        for index, title in enumerate(json.loads(str(source)[9:])):
            view.setLabel_forSegment_(translate(title), index)
    if source is not None and not str(source).startswith("choices:"):
        if isinstance(view, A.NSButton):
            view.setTitle_(translate(source))
        elif isinstance(view, A.NSTextField):
            view.setStringValue_(translate(source))
    choices = json.loads(str(source)[8:]) if source and str(source).startswith("choices:") else None
    if choices:
        for index, item in enumerate(choices):
            view.itemAtIndex_(index).setTitle_(translate(str(item[0])))
    if isinstance(view, A.NSPopUpButton) and view.pullsDown():
        for item in view.itemArray():
            if item.representedObject():
                item.setTitle_(translate(str(item.representedObject())))
    for child in view.subviews():
        refresh(child)


class FlippedView(A.NSView):
    def isFlipped(self):
        return True


class ActionTarget(NSObject):
    def invoke_(self, sender):
        try:
            self.callback(sender)
        except (ValueError, TypeError) as exc:
            alert = A.NSAlert.alloc().init()
            alert.setMessageText_("设置值无效")
            alert.setInformativeText_(str(exc))
            alert.runModal()

    def controlTextDidEndEditing_(self, notification):
        self.invoke_(notification.object())


def action(control, callback, targets, *, text=False):
    target = ActionTarget.alloc().init()
    target.callback = callback
    targets.append(target)
    control.setTarget_(target)
    control.setAction_("invoke:")
    if text:
        control.setDelegate_(target)
    return control


def label(parent, title, frame, *, size=13, bold=False):
    control = A.NSTextField.labelWithString_(translate(str(title)))
    control.setIdentifier_(str(title))
    control.setFrame_(frame)
    control.setFont_(A.NSFont.systemFontOfSize_weight_(size, A.NSFontWeightSemibold if bold else A.NSFontWeightRegular))
    control.setLineBreakMode_(A.NSLineBreakByTruncatingTail)
    control.setAutoresizingMask_(A.NSViewWidthSizable)
    tooltip(control, str(title))
    parent.addSubview_(control)
    return control


def button(parent, title, frame, callback, targets, *, checkbox=False, checked=False):
    control = A.NSButton.alloc().initWithFrame_(frame)
    control.setIdentifier_(title)
    control.setTitle_(translate(title))
    control.setFont_(A.NSFont.systemFontOfSize_(13))
    if checkbox:
        control.setButtonType_(A.NSButtonTypeSwitch)
        control.setState_(int(bool(checked)))
    else:
        control.setBezelStyle_(A.NSBezelStyleRounded)
    action(control, callback, targets)
    parent.addSubview_(control)
    return control


def popup(parent, choices, value, frame, callback, targets):
    control = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(frame, False)
    control.setFont_(A.NSFont.systemFontOfSize_(13))
    control.setIdentifier_("choices:" + json.dumps(choices, ensure_ascii=False))
    control.addItemsWithTitles_([translate(str(item[0])) for item in choices])
    selected = next((i for i, item in enumerate(choices) if item[1] == value), 0)
    control.selectItemAtIndex_(selected)
    action(control, callback, targets)
    parent.addSubview_(control)
    return control, lambda: choices[control.indexOfSelectedItem()][1]


def textfield(parent, value, frame, callback, targets, *, numeric=False):
    control = A.NSTextField.alloc().initWithFrame_(frame)
    control.setFont_(A.NSFont.systemFontOfSize_(13))
    control.setBezelStyle_(A.NSTextFieldRoundedBezel)
    control.setStringValue_(str(value or "") if not numeric else str(value))
    if numeric:
        formatter = A.NSNumberFormatter.alloc().init()
        formatter.setAllowsFloats_(isinstance(value, float))
        formatter.setUsesGroupingSeparator_(False)
        control.setFormatter_(formatter)
    action(control, callback, targets, text=True)
    parent.addSubview_(control)
    return control


def scroll(parent, frame):
    control = A.NSScrollView.alloc().initWithFrame_(frame)
    control.setHasVerticalScroller_(True)
    control.setDrawsBackground_(False)
    control.setAutohidesScrollers_(True)
    control.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
    document = FlippedView.alloc().initWithFrame_(((0, 0), (frame[1][0] - 18, frame[1][1])))
    document.setAutoresizingMask_(A.NSViewWidthSizable)
    control.setDocumentView_(document)
    parent.addSubview_(control)
    return control, document


def confirm(title, message, *, accept="确定", cancel="取消"):
    alert = A.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    alert.addButtonWithTitle_(accept)
    alert.addButtonWithTitle_(cancel)
    return alert.runModal() == A.NSAlertFirstButtonReturn


def choose_path(*, save=False, applications=False):
    panel = A.NSSavePanel.savePanel() if save else A.NSOpenPanel.openPanel()
    if not save:
        panel.setAllowsMultipleSelection_(False)
        panel.setTreatsFilePackagesAsDirectories_(False)
    if applications:
        panel.setAllowedFileTypes_(["app"])
    if panel.runModal() == A.NSModalResponseOK:
        return str(panel.URL().path())
    return None
