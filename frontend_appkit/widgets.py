"""Small native view builders; presentation only."""

import json

import AppKit as A
from Foundation import NSObject


def translate(text):
    return text


def refresh(view):
    source = view.identifier()
    if source is not None and not str(source).startswith("choices:"):
        if isinstance(view, A.NSButton):
            view.setTitle_(translate(source))
        elif isinstance(view, A.NSTextField):
            view.setStringValue_(translate(source))
    choices = json.loads(str(source)[8:]) if source and str(source).startswith("choices:") else None
    if choices:
        for index, item in enumerate(choices):
            view.itemAtIndex_(index).setTitle_(translate(str(item[0])))
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
    control.setFont_(A.NSFont.boldSystemFontOfSize_(size) if bold else A.NSFont.systemFontOfSize_(size))
    control.setAutoresizingMask_(A.NSViewWidthSizable)
    parent.addSubview_(control)
    return control


def button(parent, title, frame, callback, targets, *, checkbox=False, checked=False):
    control = A.NSButton.alloc().initWithFrame_(frame)
    control.setIdentifier_(title)
    control.setTitle_(translate(title))
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
    control.setIdentifier_("choices:" + json.dumps(choices, ensure_ascii=False))
    control.addItemsWithTitles_([translate(str(item[0])) for item in choices])
    selected = next((i for i, item in enumerate(choices) if item[1] == value), 0)
    control.selectItemAtIndex_(selected)
    action(control, callback, targets)
    parent.addSubview_(control)
    return control, lambda: choices[control.indexOfSelectedItem()][1]


def textfield(parent, value, frame, callback, targets, *, numeric=False):
    control = A.NSTextField.alloc().initWithFrame_(frame)
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
