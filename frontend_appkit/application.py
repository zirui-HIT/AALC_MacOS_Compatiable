"""AppKit windows and menus. Business state is received only through BackendClient."""

import copy
import json
import os
import socket
import sys
import threading
import time
import xml.etree.ElementTree as ET

import AppKit as A
from Foundation import NSURL, NSObject, NSRunLoop, NSRunLoopCommonModes, NSTimer
from PyObjCTools import AppHelper

from frontend_appkit.client import BackendClient
from frontend_appkit.edit_models import SINNERS, SYSTEMS, TeamDraft
from frontend_appkit.forms import Form
from frontend_appkit.theme_data import (
    CN_OCR_ALTERNATIVES,
    EN_OCR_ALTERNATIVES,
    THEME_PACK_HARD_IMAGE_MAP,
    THEME_PACK_HARD_NAME_MAP,
    THEME_PACK_IMAGE_MAP,
    THEME_PACK_NAME_MAP,
)
from frontend_appkit.theme_draft import ThemeDraft
from frontend_appkit.widgets import FlippedView, action, button, choose_path, confirm, label, popup, scroll
from native_contract import FIELDS, GROUPS, HIDDEN_TEAM, STATS, TASK_KEYS
from utils.runtime_paths import data_path, resource_path

PAGE_NAMES = ["日常任务", "领取奖励", "狂气换体", "镜牢设置", "队伍", "主题包", "设置", "工具"]
PAGE_KEYS = ["daily", "reward", "energy", "mirror", "teams", "theme", "settings", "tools"]


class Delegate(NSObject):
    def poll_(self, timer):
        try:
            self.owner.poll()
        except Exception:
            import traceback

            traceback.print_exc()
            self.owner.exit_code = 1
            if self.owner.smoke:
                AppHelper.stopEventLoop()

    def windowDidMiniaturize_(self, notification):
        owner = self.owner
        if isinstance(owner, Application) and owner.data and owner.data["config"]["minimize_to_tray"]:
            owner.close_window(notification.object())

    def applicationShouldTerminate_(self, sender):
        return self.owner.request_quit()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, visible):
        self.owner.restore()
        return True

    def windowShouldClose_(self, sender):
        return self.owner.close_window(sender)

    def statusClicked_(self, sender):
        self.owner.status_clicked()

    def openStatusMenu_(self, timer):
        self.owner.tray_click_timer = None
        self.owner.open_status_menu()


class Editor:
    def __init__(self, app, title, *, team=False):
        self.app, self.is_team = app, team
        self.targets = []
        self.dirty = lambda: False
        self.closed = False
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((100, 100), (900, 740)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable, A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_(title)
        self.window.setMinSize_((830, 500))
        self.delegate = Delegate.alloc().init()
        self.delegate.owner = self
        self.window.setDelegate_(self.delegate)
        self.root = FlippedView.alloc().initWithFrame_(((0, 0), (900, 740)))
        self.root.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.window.setContentView_(self.root)
        self.scroller, self.document = scroll(self.root, ((0, 60), (900, 680)))
        app.editors.append(self)

    def show(self):
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)

    def close_window(self, window):
        self.window.makeFirstResponder_(None)
        if self.dirty() and not confirm("放弃修改？", "尚有未保存的设置。", accept="放弃修改"):
            return False
        self.close()
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.is_team:
            self.app.client.request("draft", {"open": False})
        self.window.orderOut_(None)
        self.window.setDelegate_(None)
        self.window.close()
        if self in self.app.editors:
            self.app.editors.remove(self)


class Application:
    def __init__(self, arguments, listener=None):
        self.arguments, self.listener = arguments, listener
        self.smoke = "--smoke-test" in arguments
        self.started_at = time.monotonic()
        self.smoke_delay = float(os.environ.get("AALC_SMOKE_DELAY", "2"))
        self.targets, self.page_targets, self.editors = [], [], []
        self.data = None
        self.team_editor = None
        self.quitting = False
        self.backend_closed = False
        self.exit_code = 0
        self.polling = False
        self.page_index = 0
        self.preview_path = None
        self.ui_check = "--ui-check" in arguments
        self.ui_checked = False
        if "--preview-output" in arguments:
            self.preview_path = arguments[arguments.index("--preview-output") + 1]
        self.translations = {}
        for model in ("ConfigModel", "TeamSetting"):
            for key, value in FIELDS[model].items():
                self.translations[value["label"]] = key.replace("_", " ").capitalize()
        self.translations.update({"开始运行": "Start", "停止任务": "Stop", "暂停": "Pause", "继续": "Resume", "就绪": "Ready", "运行中": "Running", "已暂停": "Paused", "停止中…": "Stopping…", "保存": "Save", "取消": "Cancel", "启用": "Enable", "新增队伍": "Add preset", "编辑": "Edit", "权重": "Weights", "复制": "Copy", "删除": "Delete", "设置": "Settings", "工具": "Tools", "队伍": "Teams", "主题包": "Theme packs", "清空日志": "Clear log", "开始自动战斗": "Start automatic battle", "自动战斗": "Automatic battle", "无限守备": "Always defend", "第一回合开启守备": "Defend on turn one", "不处理事件": "Skip events", "截图小工具": "Screenshot", "选择游戏…": "Choose game…", "测试连接与截图": "Test connection and capture", "导出 YAML": "Export YAML", "导入 YAML": "Import YAML", "复制配置码": "Copy configuration code", "粘贴配置码": "Paste configuration code", "保存并关闭": "Save and close", "优选阈值": "Preferred threshold", "本层禁选": "Banned on this floor", "编辑全局主题包权重": "Edit global theme weights", "显示 AALC": "Show AALC", "退出 AALC": "Quit AALC", "检查软件更新": "Check app updates", "检查图片资源": "Check image resources", "打开日志目录": "Open logs", "清空历史统计": "Clear statistics", "剪切": "Cut", "全选": "Select all", "粘贴": "Paste"})
        for context in ET.parse(resource_path("i18n/myapp_en.ts")).getroot().findall("context"):
            for message in context.findall("message"):
                translation = message.findtext("translation")
                if translation:
                    self.translations[message.findtext("source")] = translation
        from frontend_appkit import widgets

        widgets.translate = self.text
        self.client = BackendClient(smoke=self.smoke)
        from Foundation import NSOperationQueue

        self.client.wake = lambda: NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self.delegate.poll_(None))
        self.delegate = Delegate.alloc().init()
        self.delegate.owner = self
        self.native = A.NSApplication.sharedApplication()
        self.native.setDelegate_(self.delegate)
        self.native.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
        self.build_window()
        self.build_menus()
        self.start_button.setEnabled_(False)
        self.pause_button.setEnabled_(False)
        for control in self.task_buttons:
            control.setEnabled_(False)
        self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(0.05, self.delegate, "poll:", None, True)
        NSRunLoop.mainRunLoop().addTimer_forMode_(self.timer, NSRunLoopCommonModes)
        if listener:
            threading.Thread(target=self.listen, daemon=True).start()

    def text(self, text):
        if self.data and self.data["config"]["language_in_program"] == "en":
            return self.translations.get(text, text)
        return text

    def refresh_language(self):
        from frontend_appkit.widgets import refresh

        refresh(self.root)
        for editor in self.editors:
            refresh(editor.root)
        def menu_text(menu):
            for item in menu.itemArray():
                original = item.representedObject()
                if original:
                    item.setTitle_(self.text(original))
                if item.submenu():
                    menu_text(item.submenu())

        menu_text(self.native.mainMenu())
        menu_text(self.tray_menu)

    def build_window(self):
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((100, 100), (1120, 800)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable | A.NSWindowStyleMaskResizable, A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("AALC")
        self.window.setMinSize_((1120, 640))
        self.window.setDelegate_(self.delegate)
        self.root = FlippedView.alloc().initWithFrame_(((0, 0), (1120, 800)))
        self.root.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.window.setContentView_(self.root)
        label(self.root, "Ahab Assistant", ((20, 17), (240, 26)), size=20, bold=True)
        self.navigation, _ = popup(self.root, [[name, i] for i, name in enumerate(PAGE_NAMES)], 0, ((270, 16), (210, 30)), lambda sender: self.select_page(sender.indexOfSelectedItem()), self.targets)
        self.status = label(self.root, "正在连接后端…", ((500, 22), (570, 24)))
        self.task_buttons = []
        for i, name in enumerate(["日常任务", "领取奖励", "狂气换体", "镜牢任务"]):
            control = button(self.root, name, ((20 + i * 152, 62), (150, 30)), lambda sender, key=TASK_KEYS[i]: self.patch({key: bool(sender.state())}), self.targets, checkbox=True)
            self.task_buttons.append(control)
        self.start_button = button(self.root, "开始运行", ((650, 60), (140, 32)), lambda sender: self.start_or_stop(), self.targets)
        self.pause_button = button(self.root, "暂停", ((800, 60), (100, 32)), lambda sender: self.client.request("task.pause"), self.targets)
        self.select_all_button = button(self.root, "全选", ((920, 60), (80, 32)), lambda sender: self.patch(dict.fromkeys(TASK_KEYS, True)), self.targets)
        self.clear_tasks_button = button(self.root, "清空", ((1010, 60), (80, 32)), lambda sender: self.patch(dict.fromkeys(TASK_KEYS, False)), self.targets)
        self.page_scroll, self.page = scroll(self.root, ((0, 110), (1120, 445)))
        self.page_scroll.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.log_scroll = A.NSScrollView.alloc().initWithFrame_(((16, 595), (1088, 188)))
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewMinYMargin)
        self.log_view = A.NSTextView.alloc().initWithFrame_(((0, 0), (1088, 188)))
        self.log_view.setEditable_(False)
        self.log_view.setFont_(A.NSFont.monospacedSystemFontOfSize_weight_(11, A.NSFontWeightRegular))
        self.log_view.setAutoresizingMask_(A.NSViewWidthSizable)
        self.log_view.setVerticallyResizable_(True)
        self.log_view.setHorizontallyResizable_(False)
        self.log_view.textContainer().setWidthTracksTextView_(True)
        self.log_scroll.setDocumentView_(self.log_view)
        self.root.addSubview_(self.log_scroll)
        self.mirror_status = label(self.root, "", ((20, 565), (760, 22)))
        self.mirror_status.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewMinYMargin)
        clear = button(self.root, "清空日志", ((950, 560), (145, 30)), lambda sender: self.client.request("logs.clear"), self.targets)
        clear.setAutoresizingMask_(A.NSViewMinYMargin | A.NSViewMinXMargin)
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        self.native.activateIgnoringOtherApps_(True)

    def build_menus(self):
        menu = A.NSMenu.alloc().init()
        root = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("AALC", None, "")
        submenu = A.NSMenu.alloc().initWithTitle_("AALC")
        self.menu_item(submenu, "显示 AALC", self.restore)
        submenu.addItem_(A.NSMenuItem.separatorItem())
        self.menu_item(submenu, "退出 AALC", lambda: self.native.terminate_(None), key="q")
        root.setSubmenu_(submenu)
        menu.addItem_(root)
        edit = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("编辑", None, "")
        edit.setRepresentedObject_("编辑")
        edit_menu = A.NSMenu.alloc().initWithTitle_("编辑")
        for title, selector, key in [("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")]:
            item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, key)
            item.setRepresentedObject_(title)
            edit_menu.addItem_(item)
        edit.setSubmenu_(edit_menu)
        menu.addItem_(edit)
        self.native.setMainMenu_(menu)
        self.status_item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        image = A.NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/logo/aalc_tray.png")))
        image.setSize_((19, 19))
        image.setTemplate_(True)
        self.status_item.button().setImage_(image)
        tray = A.NSMenu.alloc().initWithTitle_("AALC")
        self.menu_item(tray, "显示 AALC", self.restore)
        self.menu_item(tray, "暂停 / 继续", lambda: self.client.request("task.pause"))
        self.menu_item(tray, "停止任务", lambda: self.client.request("task.stop"))
        tray.addItem_(A.NSMenuItem.separatorItem())
        self.menu_item(tray, "退出 AALC", lambda: self.native.terminate_(None))
        self.tray_menu = tray
        self.tray_click_timer = None
        self.status_item.button().setTarget_(self.delegate)
        self.status_item.button().setAction_("statusClicked:")
        self.status_item.button().sendActionOn_(A.NSEventMaskLeftMouseUp | A.NSEventMaskRightMouseUp)

    def status_clicked(self):
        event = self.native.currentEvent()
        if self.tray_click_timer:
            self.tray_click_timer.invalidate()
            self.tray_click_timer = None
        if event.type() == A.NSEventTypeRightMouseUp:
            self.open_status_menu()
        elif event.clickCount() >= 2:
            self.restore()
        else:
            self.tray_click_timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(A.NSEvent.doubleClickInterval(), self.delegate, "openStatusMenu:", None, False)
            NSRunLoop.mainRunLoop().addTimer_forMode_(self.tray_click_timer, NSRunLoopCommonModes)

    def open_status_menu(self):
        control = self.status_item.button()
        self.tray_menu.popUpMenuPositioningItem_atLocation_inView_(None, (0, control.bounds().size.height), control)

    def menu_item(self, menu, title, callback, key=""):
        item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, key)
        item.setRepresentedObject_(title)
        action(item, lambda sender: callback(), self.targets)
        menu.addItem_(item)

    def listen(self):
        while not self.backend_closed:
            try:
                connection, _ = self.listener.accept()
                with connection:
                    connection.settimeout(1)
                    payload = connection.recv(65536).decode("utf-8")
                args = payload.split("|") if payload else []
                self.client.incoming.put({"event": "command", "data": args})
            except OSError:
                return

    def poll(self):
        if self.polling:
            return
        self.polling = True
        try:
            self.client.drain(self.event, self.error)
        finally:
            self.polling = False
        if self.smoke and self.data and (not self.ui_check or self.ui_checked) and time.monotonic() - self.started_at > self.smoke_delay and not self.quitting:
            if self.preview_path:
                self.preview()
            self.request_quit()
        if self.smoke and time.monotonic() - self.started_at > max(20, self.smoke_delay + 10) and not self.backend_closed:
            self.exit_code = 1
            self.native.stop_(None)

    def preview(self):
        view = self.window.contentView()
        bitmap = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
        view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), bitmap)
        bitmap.representationUsingType_properties_(A.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(self.preview_path, True)

    def event(self, event, data):
        if event in {"ready", "state"}:
            first = self.data is None
            previous_config = self.data["config"] if self.data else None
            self.data = data
            if first:
                self.log_view.setString_("\n".join(data.get("logs", [])))
                self.page_index = min(7, max(0, int(data["config"]["default_page"])))
                self.navigation.selectItemAtIndex_(self.page_index)
                self.window.setFrameOrigin_((data["config"]["window_position_x"], data["config"]["window_position_y"]))
                if not self.smoke:
                    self.client.request("startup", {"args": self.arguments})
                elif self.ui_check:
                    self.client.request("theme.get", callback=self.check_native_pages)
            if first or (PAGE_KEYS[self.page_index] == "teams" and previous_config != data["config"]):
                self.build_page()
            else:
                for form in self.forms:
                    for key in form.getters:
                        if previous_config.get(key) != data["config"].get(key):
                            form.set_value(key, data["config"].get(key))
            if first or previous_config.get("language_in_program") != data["config"]["language_in_program"]:
                self.refresh_language()
            self.update_state()
        elif event == "log":
            text = self.log_view.string() + ("\n" if self.log_view.string() else "") + "\n".join(data)
            self.log_view.setString_("\n".join(text.splitlines()[-10000:]))
            self.log_view.scrollRangeToVisible_((len(self.log_view.string()), 0))
        elif event == "log_clear":
            self.log_view.setString_("")
        elif event == "warning":
            self.error(data["message"])
        elif event == "mirror":
            self.mirror_status.setStringValue_(f"镜牢 · 已完成 {data['current']} · 剩余 {data['remaining']}" if data else "")
        elif event == "focus":
            self.restore()
        elif event in {"screenshot", "capture"}:
            self.show_capture(data)
        elif event == "command":
            if not self.quitting:
                self.client.request("command", {"args": data})
                self.restore()
        elif event == "resources":
            if data["changes"] and (not data["startup"] or data["automatic"]) and confirm("图片资源可更新", data["message"] or "下载并同步最新图片资源？", accept="同步"):
                self.client.request("resources.apply")
            else:
                self.mirror_status.setStringValue_(data["message"] or "图片资源已是最新")
                if data["startup"]:
                    self.client.request("resources.skip")
        elif event == "resource_progress":
            self.mirror_status.setStringValue_(f"图片同步 · {data}%")
        elif event == "resources_applied":
            self.mirror_status.setStringValue_(data["message"])
        elif event == "announcement":
            self.show_announcements(data)
        elif event == "update":
            if data["status"] == "UPDATE_AVAILABLE":
                self.show_text("发现新版本 · " + data["version"], data["content"], html=True)
            elif data["status"] == "FAILURE":
                self.error(data["message"])
            else:
                self.mirror_status.setStringValue_("软件已是最新")
        elif event == "completion_suppressed":
            if data:
                self.mirror_status.setStringValue_("定时任务已排队，当前任务完成后继续")
        elif event == "exit":
            self.native.terminate_(None)
        elif event == "shutdown_failed":
            self.quit_failed(data["message"])
        elif event == "closed":
            self.backend_closed = True
            if self.listener:
                self.listener.close()
            self.client.close_pipes()
            if self.quitting:
                if self.smoke:
                    AppHelper.stopEventLoop()
                else:
                    self.native.replyToApplicationShouldTerminate_(True)
        elif event == "disconnected" and not self.backend_closed:
            self.backend_closed = True
            if self.listener:
                self.listener.close()
            self.exit_code = 1
            self.start_button.setEnabled_(False)
            self.error("后端进程已退出。\n" + str(data))
            if self.quitting:
                if self.smoke:
                    AppHelper.stopEventLoop()
                else:
                    self.native.replyToApplicationShouldTerminate_(True)

    def error(self, message):
        if self.smoke:
            sys.stderr.write(str(message) + "\n")
            self.exit_code = 1
            self.native.terminate_(None)
            return
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_("AALC")
        alert.setInformativeText_(str(message))
        alert.runModal()

    def patch(self, values):
        self.client.request("config.patch", {"values": values})

    def commit_current(self, callback, on_error=None):
        self.window.makeFirstResponder_(None)
        values = {}
        if self.data:
            for form in self.forms:
                for key, value in form.values().items():
                    if value != self.data["config"].get(key):
                        values[key] = value
        if values:
            self.client.request("config.patch", {"values": values}, lambda result: callback(), on_error=on_error)
        else:
            callback()

    def start_or_stop(self):
        if self.data["state"]["running"]:
            self.client.request("task.stop")
        else:
            self.commit_current(lambda: self.client.request("task.start"))

    def select_page(self, index):
        def selected():
            self.page_index = index
            self.patch({"default_page": index})
            self.build_page()

        def failed(message):
            self.navigation.selectItemAtIndex_(self.page_index)
            self.error(message)

        self.commit_current(selected, on_error=failed)

    def build_page(self):
        if not self.data:
            return
        for view in list(self.page.subviews()):
            view.removeFromSuperview()
        self.page_targets = []
        key = PAGE_KEYS[self.page_index]
        values = self.data["config"]
        self.form = None
        self.forms = []
        if key in GROUPS and key not in {"settings", "playcover"}:
            self.form = Form(self.page, values, GROUPS[key], self.page_targets, lambda name, value: self.patch({name: value}), text=self.text)
            self.forms.append(self.form)
            if key == "mirror":
                self.form = Form(self.page, values, GROUPS["completion"], self.page_targets, lambda name, value: self.patch({name: value}), start=self.form.y, text=self.text)
                self.forms.append(self.form)
        elif key == "teams":
            self.build_teams()
        elif key == "theme":
            button(self.page, self.text("编辑全局主题包权重"), ((20, 20), (240, 34)), lambda sender: self.open_theme(), self.page_targets)
            label(self.page, "队伍自定义权重可从队伍列表打开。", ((20, 70), (600, 24)))
        elif key == "settings":
            self.build_settings()
        elif key == "tools":
            self.build_tools()
        self.update_state()

    def update_state(self):
        if self.data is None:
            return
        state, config = self.data["state"], self.data["config"]
        running = state["running"]
        self.window.setTitle_("AALC " + self.data["version"])
        self.start_button.setTitle_(self.text("停止中…" if state["stopping"] else "停止任务" if running else "开始运行"))
        self.start_button.setEnabled_(not state["stopping"] and not state["startup"] and state["kind"] not in {"connection", "screenshot"})
        self.pause_button.setTitle_(self.text("继续" if state["paused"] else "暂停"))
        self.pause_button.setEnabled_(state["kind"] in {"task", "battle"} and not state["stopping"])
        self.status.setStringValue_(self.text("停止中…" if state["stopping"] else "已暂停" if state["paused"] else "运行中" if running else "就绪") + (f" · 排队 {state['queued']}" if state["queued"] else ""))
        for i, control in enumerate(self.task_buttons):
            control.setState_(int(config[TASK_KEYS[i]]))
            control.setEnabled_(not running)
        self.select_all_button.setEnabled_(not running)
        self.clear_tasks_button.setEnabled_(not running)
        if PAGE_KEYS[self.page_index] in {"daily", "reward", "energy", "mirror", "teams", "tools", "theme"}:
            for control in self.page.subviews():
                if isinstance(control, A.NSControl):
                    control.setEnabled_(not running)
        appearance = config["theme_mode"]
        self.native.setAppearance_(None if appearance == "AUTO" else A.NSAppearance.appearanceNamed_(A.NSAppearanceNameDarkAqua if appearance == "DARK" else A.NSAppearanceNameAqua))

    def build_teams(self):
        values = self.data["config"]
        queue = values["teams_active_queue"]
        button(self.page, "新增队伍", ((20, 16), (130, 32)), lambda sender: self.client.request("team.add"), self.page_targets)
        y = 65
        for number, team in sorted(values["teams"].items(), key=lambda item: int(item[0])):
            n = int(number)
            order = f" · #{queue.index(n) + 1}" if n in queue else ""
            button(self.page, f"预设 {n}{order} · {team['remark_name'] or 'Team ' + str(team['team_number'])}", ((20, y), (350, 30)), lambda sender, number=n: self.client.request("team.enable", {"number": number, "enabled": bool(sender.state())}), self.page_targets, checkbox=True, checked=n in queue)
            for i, (title, callback) in enumerate([
                ("编辑", lambda n=n: self.edit_team(n)), ("权重", lambda n=n: self.open_theme(n)),
                ("↑", lambda n=n: self.client.request("team.order", {"number": n, "offset": -1})),
                ("↓", lambda n=n: self.client.request("team.order", {"number": n, "offset": 1})),
                ("复制", lambda n=n: self.client.request("team.add", {"copy_from": n})),
                ("删除", lambda n=n: self.delete_team(n)),
            ]):
                control = button(self.page, title, ((385 + i * 105, y), (100, 30)), lambda sender, cb=callback: cb(), self.page_targets)
                if title in {"↑", "↓"}:
                    control.setEnabled_(n in queue)
            y += 44
        self.page.setFrameSize_((self.page.frame().size.width, y + 20))

    def delete_team(self, number):
        if confirm("删除队伍？", f"删除预设 {number} 及其专属主题包权重。"):
            self.client.request("team.delete", {"number": number})

    def edit_team(self, number):
        if self.team_editor and not self.team_editor.closed:
            self.team_editor.window.makeKeyAndOrderFront_(None)
            return
        draft = TeamDraft(self.data["config"]["teams"][str(number)])
        editor = Editor(self, f"队伍预设 {number}", team=True)
        self.team_editor = editor
        self.client.request("draft", {"open": True})
        sinner_controls = []

        def sinner_changed(index, selected):
            draft.select_sinner(index, selected)
            for i, control in enumerate(sinner_controls):
                order = draft.values["sinner_order"][i]
                control.setTitle_(SINNERS[i] + (f" · {order}" if order else ""))

        for i, name in enumerate(SINNERS):
            order = draft.values["sinner_order"][i]
            control = button(editor.document, name + (f" · {order}" if order else ""), ((20 + (i % 4) * 210, 16 + (i // 4) * 34), (205, 28)), lambda sender, i=i: sinner_changed(i, bool(sender.state())), editor.targets, checkbox=True, checked=draft.values["chosen_sinners"][i])
            sinner_controls.append(control)

        def change(key, value):
            draft.set(key, value)
            for name in ("avoid_skill_3", "prioritize_skill_3", "defense_first_round", "defense_for_solo", *["system_" + system for system in SYSTEMS]):
                form.set_value(name, draft.values[name])
            for system in SYSTEMS:
                form.controls["system_" + system].setEnabled_(system != SYSTEMS[draft.values["team_system"]])

        form = Form(editor.document, draft.values, [key for key in FIELDS["TeamSetting"] if key not in HIDDEN_TEAM], editor.targets, change, team=True, start=130, text=self.text)
        for system in SYSTEMS:
            form.controls["system_" + system].setEnabled_(system != SYSTEMS[draft.values["team_system"]])

        def collect():
            editor.window.makeFirstResponder_(None)
            for key, value in form.values().items():
                draft.set(key, value)
            return {key: value for key, value in draft.values.items() if key not in STATS and key not in {"use_team_code", "team_code"}}

        def save():
            self.client.request("team.save", {"number": number, "values": collect()}, lambda result: editor.close())

        button(editor.root, "保存", ((16, 14), (100, 32)), lambda sender: save(), editor.targets)
        button(editor.root, "取消", ((126, 14), (100, 32)), lambda sender: editor.close_window(editor.window), editor.targets)
        button(editor.root, "导出 YAML", ((250, 14), (130, 32)), lambda sender: self.export_team(number), editor.targets)
        button(editor.root, "导入 YAML", ((390, 14), (130, 32)), lambda sender: self.import_team(number, editor), editor.targets)
        button(editor.root, "复制配置码", ((530, 14), (140, 32)), lambda sender: self.copy_team(number), editor.targets)
        button(editor.root, "粘贴配置码", ((680, 14), (140, 32)), lambda sender: self.paste_team(number, form, draft), editor.targets)
        stats = draft.values
        label(editor.document, f"普通镜牢 {stats['mirror_normal_count']} 次 · 平均 {(stats['total_mirror_time_normal'] or [0.0])[0]:.1f} 秒    困难镜牢 {stats['mirror_hard_count']} 次 · 平均 {(stats['total_mirror_time_hard'] or [0.0])[0]:.1f} 秒", ((20, form.y), (800, 26)))
        button(editor.document, "清空历史统计", ((20, form.y + 34), (180, 32)), lambda sender: self.clear_stats(number), editor.targets)
        editor.document.setFrameSize_((editor.document.frame().size.width, form.y + 100))
        def dirty():
            try:
                collect()
            except (ValueError, TypeError):
                return True
            return draft.dirty()

        editor.dirty = dirty
        editor.show()

    def export_team(self, number):
        path = choose_path(save=True)
        if path:
            self.client.request("team.export", {"number": number, "path": path})

    def import_team(self, number, editor):
        path = choose_path()
        if not path or not confirm("导入队伍设置？", "导入会应用到已保存配置，当前草稿将关闭。"):
            return

        def done(result):
            if result["missing"]:
                if confirm("配置缺少字段", "使用默认值补齐缺少的设置？"):
                    self.client.request("team.import", {"number": number, "path": path, "confirm": True}, lambda result: editor.close())
            else:
                editor.close()

        self.client.request("team.import", {"number": number, "path": path}, done)

    def copy_team(self, number):
        import base64

        data = self.data["config"]["teams"][str(number)]
        code = base64.b64encode(("||AALC_TEAM_SETTING||" + json.dumps(data)).encode()).decode()
        pasteboard = A.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(code, A.NSPasteboardTypeString)

    def paste_team(self, number, form, draft):
        import base64

        code = A.NSPasteboard.generalPasteboard().stringForType_(A.NSPasteboardTypeString) or ""
        try:
            prefix = "||AALC_TEAM_SETTING||"
            code = base64.b64decode(code).decode()
            if not code.startswith(prefix):
                raise ValueError("剪贴板中没有队伍配置码")
            values = json.loads(code[len(prefix):])
            self.client.request("team.save", {"number": number, "values": {key: value for key, value in values.items() if key not in STATS and key not in {"use_team_code", "team_code"}}}, lambda result: self.team_editor.close())
        except (ValueError, TypeError) as exc:
            self.error(str(exc))

    def clear_stats(self, number):
        if confirm("清空历史统计？", "此操作会清空该队伍的镜牢次数和耗时记录。"):
            self.client.request("team.stats.clear", {"number": number})

    def build_settings(self):
        values = self.data["config"]
        playcover = Form(self.page, values, GROUPS["playcover"], self.page_targets, lambda name, value: self.patch({name: value}), text=self.text)
        self.forms.append(playcover)
        y = playcover.y
        button(self.page, "选择游戏…", ((20, y), (160, 32)), lambda sender: self.choose_game(), self.page_targets)
        button(self.page, "测试连接与截图", ((200, y), (200, 32)), lambda sender: self.client.request("connection.test"), self.page_targets)
        main = Form(self.page, values, GROUPS["settings"], self.page_targets, lambda name, value: self.patch({name: value}), start=y + 60, text=self.text)
        self.forms.append(main)
        y = main.y
        for suffix in ("", "2", "3", "4"):
            label(self.page, "定时任务 " + (suffix or "1"), ((20, y), (400, 26)), size=15, bold=True)
            form = Form(self.page, values, GROUPS["schedule" + suffix], self.page_targets, lambda name, value: self.patch({name: value}), start=y + 40, text=self.text)
            self.forms.append(form)
            y = form.y + 20
        for i, (name, callback) in enumerate([
            ("检查软件更新", lambda: self.client.request("updates.check")),
            ("检查图片资源", lambda: self.client.request("resources.check")),
            ("打开日志目录", lambda: A.NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(data_path("logs"))))),
            ("公告", lambda: self.client.request("announcements")),
            ("GitHub", lambda: self.open_url("https://github.com/KIYI671/AhabAssistantLimbusCompany")),
            ("Discord", lambda: self.open_url("https://discord.gg/vUAw98cEVe")),
            ("反馈", lambda: self.open_url("https://github.com/KIYI671/AhabAssistantLimbusCompany/issues")),
        ]):
            button(self.page, name, ((20 + (i % 3) * 280, y + (i // 3) * 42), (260, 32)), lambda sender, callback=callback: callback(), self.page_targets)
        self.page.setFrameSize_((self.page.frame().size.width, y + 160))

    def choose_game(self):
        path = choose_path(applications=True)
        if path:
            self.client.request("app.identity", {"path": path}, lambda value: self.patch({"playcover_app_path": value["path"], "playcover_bundle_id": value["bundle_id"]}))

    def build_tools(self):
        label(self.page, "自动战斗", ((20, 20), (400, 28)), size=16, bold=True)
        options = []
        for i, name in enumerate(["无限守备", "第一回合开启守备", "不处理事件"]):
            options.append(button(self.page, name, ((20, 60 + i * 38), (450, 30)), lambda sender: None, self.page_targets, checkbox=True))
        button(self.page, "开始自动战斗", ((20, 185), (200, 34)), lambda sender: self.client.request("battle.start", dict(zip(["defense", "defense_on_turn1", "not_choose_event"], [bool(control.state()) for control in options]))), self.page_targets)
        label(self.page, "使用主窗口的停止按钮或已配置热键停止。", ((20, 240), (800, 26)))
        button(self.page, "截图小工具", ((20, 290), (200, 34)), lambda sender: self.client.request("screenshot"), self.page_targets)
        self.page.setFrameSize_((self.page.frame().size.width, 360))

    def open_theme(self, number=None):
        self.client.request("theme.get", {"number": number}, lambda values: self.edit_theme(number, values))

    def edit_theme(self, number, values):
        draft = ThemeDraft(values)
        editor = Editor(self, "全局主题包权重" if number is None else f"队伍 {number} · 主题包权重")
        mode, floor = [False], [1]
        from frontend_appkit.widgets import textfield

        def threshold_changed(sender):
            value = int(sender.stringValue())
            if not -10 <= value <= 10:
                raise ValueError("优选阈值范围为 -10…10")
            draft.config_data["preferred_thresholds"] = value
            draft._has_unsaved_changes = True

        label(editor.root, "优选阈值", ((16, 92), (100, 24)))
        threshold = textfield(editor.root, draft.config_data.get("preferred_thresholds", 0), ((130, 88), (90, 28)), threshold_changed, editor.targets, numeric=True)
        editor.scroller.setFrame_(((0, 130), (900, 610)))
        targets = []
        inputs = []

        def commit():
            editor.window.makeFirstResponder_(None)
            threshold_changed(threshold)
            for pack, control, hard in inputs:
                weight = int(control.stringValue())
                if not -10 <= weight <= 10:
                    raise ValueError("权重范围为 -10…10")
                draft._on_weight_changed(pack, weight, hard, False)

        def save(close=True):
            commit()
            self.client.request("theme.save", {"number": number, "values": draft.config_data}, lambda result: editor.close() if close else None)

        def render():
            for view in list(editor.document.subviews()):
                view.removeFromSuperview()
            targets.clear()
            inputs.clear()
            threshold.setStringValue_(str(draft.config_data.get("preferred_thresholds", 0)))
            mapping = THEME_PACK_NAME_MAP | THEME_PACK_HARD_NAME_MAP if mode[0] else THEME_PACK_NAME_MAP
            images = THEME_PACK_IMAGE_MAP | THEME_PACK_HARD_IMAGE_MAP if mode[0] else THEME_PACK_IMAGE_MAP
            policy_key = ("hard" if mode[0] else "normal") + "_" + str(floor[0])
            banned = draft.config_data.setdefault("forbidden_theme_packs", {}).setdefault(policy_key, [])
            y = 16
            weights = dict(draft.config_data.get("theme_pack_list", {}))
            if mode[0]:
                weights.update(draft.config_data.get("theme_pack_list_hard", {}))
            for pack, weight in weights.items():
                hard = mode[0] and pack in draft.config_data.get("theme_pack_list_hard", {})
                if pack in EN_OCR_ALTERNATIVES:
                    continue
                image = A.NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/app/theme_packs/" + images.get(pack, "Unknown.png"))))
                if image:
                    view = A.NSImageView.alloc().initWithFrame_(((20, y), (42, 66)))
                    view.setImage_(image)
                    view.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
                    editor.document.addSubview_(view)
                label(editor.document, mapping.get(pack, pack), ((80, y + 15), (360, 25)))
                from frontend_appkit.widgets import textfield

                def change(sender, pack=pack, hard=hard):
                    try:
                        weight = int(sender.stringValue())
                        if not -10 <= weight <= 10:
                            raise ValueError("权重范围为 -10…10")
                        draft._on_weight_changed(pack, weight, hard, False)
                    except ValueError as exc:
                        self.error(str(exc))

                control = textfield(editor.document, weight, ((470, y + 12), (100, 28)), change, targets, numeric=True)
                inputs.append((pack, control, hard))

                def ban(sender, pack=pack):
                    names = {pack}
                    cn = mapping.get(pack)
                    if cn:
                        names.add(cn)
                        names.update(alias for alias, main in CN_OCR_ALTERNATIVES.items() if main == cn)
                    names.update(alias for alias, main in EN_OCR_ALTERNATIVES.items() if main == pack)
                    for name in names:
                        if sender.state() and name not in banned:
                            banned.append(name)
                        elif not sender.state() and name in banned:
                            banned.remove(name)
                    draft._has_unsaved_changes = True

                button(editor.document, "本层禁选", ((610, y + 12), (180, 28)), ban, targets, checkbox=True, checked=pack in banned or mapping.get(pack) in banned)
                y += 78
            editor.document.setFrameSize_((editor.document.frame().size.width, y + 20))

        def choose_mode(sender):
            commit()
            mode[0] = sender.indexOfSelectedItem() == 1
            render()

        def choose_floor(sender):
            commit()
            floor[0] = sender.indexOfSelectedItem() + 1
            render()

        popup(editor.root, [["普通", False], ["困难", True]], False, ((16, 14), (120, 30)), choose_mode, editor.targets)
        popup(editor.root, [[f"第{i}层", i] for i in range(1, 6)], 1, ((145, 14), (120, 30)), choose_floor, editor.targets)
        button(editor.root, "保存并关闭", ((275, 14), (140, 32)), lambda sender: save(), editor.targets)
        button(editor.root, "全部设为 -5", ((425, 14), (150, 32)), lambda sender: (commit(), self.theme_negative(draft, render)), editor.targets)
        button(editor.root, "重置默认", ((585, 14), (125, 32)), lambda sender: (commit(), self.client.request("theme.defaults", callback=lambda data: self.replace_theme(draft, data, render))), editor.targets)
        if number is not None:
            button(editor.root, "拉取全局", ((720, 14), (125, 32)), lambda sender: (commit(), self.client.request("theme.get", callback=lambda data: self.replace_theme(draft, data, render))), editor.targets)
            for i, title in enumerate(["导出 YAML", "导入 YAML", "复制配置码", "粘贴配置码"]):
                button(editor.root, title, ((16 + i * 180, 54), (170, 30)), lambda sender, i=i: self.theme_transfer(number, i, draft, render, commit), editor.targets)
            editor.scroller.setFrame_(((0, 130), (900, 610)))
        editor.dirty = lambda: draft._has_unsaved_changes
        render()
        editor.show()

    @staticmethod
    def replace_theme(draft, values, render):
        draft.config_data = copy.deepcopy(values)
        draft._has_unsaved_changes = True
        render()

    @staticmethod
    def theme_negative(draft, render):
        for key in ("theme_pack_list", "theme_pack_list_hard", "theme_pack_list_cn", "theme_pack_list_hard_cn"):
            draft.config_data[key] = {pack: -5 for pack in draft.config_data.get(key, {})}
        draft._has_unsaved_changes = True
        render()

    def theme_transfer(self, number, index, draft, render, commit):
        commit()
        if index in {0, 1}:
            path = choose_path(save=index == 0)
            if not path:
                return
            action_, params = ("export" if index == 0 else "import"), {"path": path}
        elif index == 2:
            action_, params = "copy", {}
        else:
            action_, params = "paste", {"code": A.NSPasteboard.generalPasteboard().stringForType_(A.NSPasteboardTypeString) or ""}

        def transfer_done(result):
            if index == 2:
                board = A.NSPasteboard.generalPasteboard()
                board.clearContents()
                board.setString_forType_(result or "", A.NSPasteboardTypeString)
            elif index in {1, 3}:
                self.client.request("theme.get", {"number": number}, lambda data: self.replace_theme(draft, data, render))

        def transfer(result):
            self.client.request("theme.transfer", {"number": number, "action": action_, **params}, transfer_done)

        if index in {0, 2}:
            self.client.request("theme.save", {"number": number, "values": draft.config_data}, transfer)
        else:
            transfer(None)

    def show_capture(self, data):
        editor = Editor(self, "截图预览")
        image = A.NSImage.alloc().initWithContentsOfFile_(data["path"])
        view = A.NSImageView.alloc().initWithFrame_(((0, 0), (860, 520)))
        view.setImage_(image)
        view.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
        editor.document.addSubview_(view)
        label(editor.root, data.get("bundle_id", data["path"]), ((16, 16), (850, 28)))
        editor.show()

    def check_native_pages(self, theme):
        # Opt-in UI QA builds every active page/editor without game commands.
        for index in range(len(PAGE_KEYS)):
            self.page_index = index
            self.build_page()
            for form in self.forms:
                form.values()
        number = int(next(iter(self.data["config"]["teams"])))
        self.edit_team(number)
        self.team_editor.close()
        self.edit_theme(None, theme)
        self.editors[-1].close()
        self.edit_theme(number, theme)
        self.editors[-1].close()
        self.page_index = 7
        self.navigation.selectItemAtIndex_(7)
        self.build_page()
        self.ui_checked = True
        sys.stderr.write("NATIVE_UI_CHECK_PASSED\n")

    def show_text(self, title, text, html=False):
        editor = Editor(self, title)
        view = A.NSTextView.alloc().initWithFrame_(((0, 0), (860, 1000)))
        view.setEditable_(False)
        if html:
            from Foundation import NSData

            data = NSData.dataWithBytes_length_(text.encode(), len(text.encode()))
            attributed, _ = A.NSAttributedString.alloc().initWithHTML_documentAttributes_(data, None)
            view.textStorage().setAttributedString_(attributed)
        else:
            view.setString_(str(text))
        editor.scroller.setDocumentView_(view)
        button(editor.root, "查看发布页面", ((16, 14), (180, 32)), lambda sender: self.open_url("https://github.com/KIYI671/AhabAssistantLimbusCompany/releases"), editor.targets)
        editor.show()

    def show_announcements(self, data):
        parts = []
        for key, value in data.items():
            if key == "Time":
                continue
            if isinstance(value, dict):
                parts.append(str(value.get("title", key)) + "\n" + str(value.get("content", value.get("Content", ""))))
            else:
                parts.append(str(value))
        self.show_text("公告", "\n\n".join(parts))

    @staticmethod
    def open_url(url):
        A.NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def restore(self):
        self.native.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
        self.window.deminiaturize_(None)
        self.window.makeKeyAndOrderFront_(None)
        self.native.activateIgnoringOtherApps_(True)
        for editor in self.editors:
            editor.window.orderFront_(None)

    def close_window(self, window):
        position = window.frame().origin
        self.patch({"window_position_x": int(position.x), "window_position_y": int(position.y)})
        window.orderOut_(None)
        for editor in self.editors:
            editor.window.orderOut_(None)
        self.native.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
        return False

    def request_quit(self):
        if self.backend_closed:
            return A.NSTerminateNow
        if self.quitting:
            return A.NSTerminateLater
        if self.data and self.data["state"]["running"] and not self.smoke:
            self.restore()
            if not confirm("有正在进行的任务", "停止任务并在清理完成后退出 AALC？", accept="停止并退出"):
                return A.NSTerminateCancel
        for editor in list(self.editors):
            if not editor.closed and not editor.close_window(editor.window):
                return A.NSTerminateCancel
        self.quitting = True
        position = self.window.frame().origin
        self.patch({"window_position_x": int(position.x), "window_position_y": int(position.y)})
        def shutdown():
            self.client.request("shutdown", on_error=self.quit_failed)

        try:
            self.commit_current(shutdown, on_error=self.quit_failed)
        except (ValueError, TypeError) as exc:
            self.quitting = False
            self.error(str(exc))
            return A.NSTerminateCancel
        return A.NSTerminateLater

    def quit_failed(self, message):
        self.quitting = False
        if self.smoke:
            self.exit_code = 1
            sys.stderr.write(str(message) + "\n")
            AppHelper.stopEventLoop()
        else:
            self.native.replyToApplicationShouldTerminate_(False)
            self.error(message)


def run(arguments):
    listener = None
    if "--smoke-test" not in arguments:
        try:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 62333))
            listener.listen(5)
        except OSError:
            if listener:
                listener.close()
            with socket.create_connection(("127.0.0.1", 62333), timeout=2) as connection:
                connection.sendall("|".join(arguments).encode() or b"|")
            return 0
    app = Application(arguments, listener)
    AppHelper.runEventLoop()
    return app.exit_code
