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
from frontend_appkit.forms import DISPLAY_LABELS, Form
from frontend_appkit.presentation import (
    TOOLBAR_HEIGHT,
    TOOLBAR_SLOT_WIDTH,
    LayoutView,
    LogResizeHandle,
    SurfaceView,
    TaskRow,
    announcement_html,
    glass,
    icon,
    menu_button,
    segmented,
    subtitle,
    template_image,
    toolbar_glass,
)
from frontend_appkit.starlight_data import bonus_translations
from frontend_appkit.theme_data import (
    CN_OCR_ALTERNATIVES,
    EN_OCR_ALTERNATIVES,
    THEME_PACK_HARD_IMAGE_MAP,
    THEME_PACK_HARD_NAME_MAP,
    THEME_PACK_IMAGE_MAP,
    THEME_PACK_NAME_MAP,
)
from frontend_appkit.theme_draft import ThemeDraft
from frontend_appkit.widgets import (
    FlippedView,
    accessibility_label,
    action,
    attributed_html,
    button,
    choose_path,
    confirm,
    label,
    popup,
    scroll,
    tooltip,
)
from native_contract import FIELDS, GROUPS, HIDDEN_TEAM, STATS, TASK_KEYS
from utils.runtime_paths import data_path, resource_path

PAGE_KEYS = ["daily", "reward", "energy", "mirror", "teams", "theme", "settings", "tools"]
HIDDEN_APP_FIELDS = {"update_prerelease_enable"}  # Official notifications use stable releases.


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

    def toolbarAllowedItemIdentifiers_(self, toolbar):
        return self.owner.toolbar_identifiers

    def toolbarDefaultItemIdentifiers_(self, toolbar):
        return self.owner.toolbar_identifiers

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(self, toolbar, identifier, inserted):
        return self.owner.toolbar_items.get(str(identifier))

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
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((100, 100), (800, 620)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable, A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_(title)
        self.window.setMinSize_((800, 500))
        self.delegate = Delegate.alloc().init()
        self.delegate.owner = self
        self.window.setDelegate_(self.delegate)
        self.root = LayoutView.alloc().initWithFrame_(((0, 0), (800, 620)))
        self.root.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.window.setContentView_(self.root)
        self.scroller, self.document = scroll(self.root, ((0, 60), (800, 560)))
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
        self.deleting_team = False
        self.team_generation = 0
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
        self.last_task_page = 0
        self.mirror_section = 0
        self.settings_section = 0
        self.task_details = {0: 0, 2: 0}
        self.settings_details = {}
        self.expanded_schedules = set()
        self.expanded_daily = set()
        self.logs_expanded = False
        self.log_height = 210
        self.preview_path = None
        self.ui_check = "--ui-check" in arguments
        self.ui_checked = False
        if "--preview-output" in arguments:
            self.preview_path = arguments[arguments.index("--preview-output") + 1]
        self.translations = {}
        for model in ("ConfigModel", "TeamSetting"):
            for key, value in FIELDS[model].items():
                self.translations[value["label"]] = key.replace("_", " ").capitalize()
        self.translations.update({"经验": "EXP", "纽本": "Thread", "关闭": "Off", "本次开启": "This run", "保持开启": "Always", "设置经验本的次数": "EXP runs", "设置纽本的次数": "Thread runs", "设置日常本使用的队伍": "Daily team", "是否使用连续作战": "Continuous combat", "一场连续作战的最大次数": "Maximum consecutive battles", "完成后": "After run", "保持此设置": "Keep this setting", "启用后保留完成后操作；关闭时仅用于本次运行。": "Keep completion actions for future runs; otherwise apply them once.", "高级配置": "Advanced", "购买体力": "Enkephalin refills", "换体策略": "Refill options", "高级连接设置": "Advanced connection", "返回游戏连接": "Back to game", "高级连接设置…": "Advanced connection…", "返回外观设置": "Back to appearance", "配置全局快捷键…": "Global hotkeys…", "输入参数": "Input parameters", "运行偏好": "Runtime preferences", "返回运行偏好": "Back to runtime", "高级输入参数…": "Advanced input…", "日常任务": "Daily tasks", "领取奖励": "Claim rewards", "狂气换体": "Enkephalin", "镜牢任务": "Mirror dungeon", "经验本、纽本与每日配队": "EXP, Thread and daily teams", "选择邮件和日常、周常奖励的领取范围": "Choose mail, daily and weekly rewards", "配置购买体力次数与换体选项": "Configure refills and conversion", "配置镜牢、队伍与主题包": "Configure mirror runs, teams and theme packs", "游戏连接、定时任务与应用偏好": "Game connection, schedules and preferences", "自动战斗与截图": "Automatic battle and screenshots", "设置普通与困难镜牢的主题包权重及各层禁选。": "Configure weights and floor bans for normal and hard mirrors.", "从「队伍配置」中对应队伍的「权重」进入。": "Open Weights for a preset in Teams.", "勾选启用队伍，使用上下移调整已有队伍顺序。": "Enable presets and adjust their order using Move up/down.", "任务": "Tasks", "导航": "Navigation", "状态": "Status", "运行日志": "Run log", "勾选要运行的任务": "Select tasks to run", "常规设置": "General", "队伍配置": "Teams", "主题包设置": "Theme packs", "高级设置": "Advanced", "游戏连接": "Game", "定时任务": "Schedules", "外观与快捷键": "Appearance & keys", "运行参数": "Runtime", "资源与关于": "Resources & about", "日常关卡": "Daily stages", "经验本按日期配队": "EXP teams by day", "纽本按日期配队": "Thread teams by day", "奖励范围": "Reward scope", "换体设置": "Enkephalin", "次数与模式": "Count & mode", "加成与奖励": "Bonuses & rewards", "运行策略": "Run options", "活动与战斗": "Events & combat", "配队与自动困难镜牢": "Team selection & hard mirror", "PlayCover 与游戏连接": "PlayCover connection", "外观与语言": "Appearance & language", "全局快捷键": "Global hotkeys", "运行与输入参数": "Runtime & input", "软件与图片资源": "App & image resources", "全局主题包权重": "Global theme weights", "队伍专属权重": "Team-specific weights", "前往队伍配置": "Open team settings", "上移": "Move up", "下移": "Move down", "队伍体系": "Team system", "购买次数": "Refills", "镜牢次数": "Mirror runs", "队伍与体系": "Team & system", "饰品舍弃": "Discard gifts", "商店与合成": "Shop & fusion", "战斗策略": "Combat strategy", "用途与奖励": "Usage & rewards", "星光与开局": "Starlight & start", "第二体系": "Second system", "观测饰品": "Observed gifts", "技能与刷新": "Skills & refresh", "开始运行": "Start", "停止任务": "Stop", "暂停": "Pause", "继续": "Resume", "就绪": "Ready", "运行中": "Running", "已暂停": "Paused", "停止中…": "Stopping…", "保存": "Save", "取消": "Cancel", "启用": "Enable", "新增队伍": "Add preset", "编辑": "Edit", "权重": "Weights", "复制": "Copy", "删除": "Delete", "设置": "Settings", "工具": "Tools", "队伍": "Teams", "主题包": "Theme packs", "清空日志": "Clear log", "开始自动战斗": "Start automatic battle", "自动战斗": "Automatic battle", "无限守备": "Always defend", "第一回合开启守备": "Defend on turn one", "不处理事件": "Skip events", "截图小工具": "Screenshot", "选择游戏…": "Choose game…", "测试连接与截图": "Test connection and capture", "导出 YAML": "Export YAML", "导入 YAML": "Import YAML", "复制配置码": "Copy configuration code", "粘贴配置码": "Paste configuration code", "保存并关闭": "Save and close", "优选阈值": "Preferred threshold", "本层禁选": "Banned on this floor", "编辑全局主题包权重": "Edit global theme weights", "显示 AALC": "Show AALC", "退出 AALC": "Quit AALC", "检查软件更新": "Check app updates", "检查图片资源": "Check image resources", "打开日志目录": "Open logs", "清空历史统计": "Clear statistics", "剪切": "Cut", "全选": "Select all", "粘贴": "Paste"})
        for context in ET.parse(resource_path("i18n/myapp_en.ts")).getroot().findall("context"):
            for message in context.findall("message"):
                translation = message.findtext("translation")
                if translation:
                    self.translations[message.findtext("source")] = translation
        self.translations.update({"完成后": "After run", "关闭": "Off", "一场连续作战的最大次数": "Maximum consecutive battles", "经验": "EXP", "纽本": "Thread"})
        self.translations.update({cn: en for cn, en in DISPLAY_LABELS.values()})
        self.translations.update({"打开自动战斗…": "Open automatic battle…", "打开截图小工具…": "Open screenshot tool…", "截图": "Capture", "点击截图获取当前游戏画面": "Capture to preview the current game view", "更新时间": "Updated", "暂无公告": "No announcements", "更新为当前时间": "Update to now", "拖动调整日志高度": "Drag to resize the log"})
        for number in range(1, 5):
            self.translations[f"定时任务 {number}"] = f"Schedule {number}"
            self.translations[f"启用定时任务 {number}"] = f"Enable schedule {number}"
        self.translations.update({"更多": "More", "项任务已启用": "tasks enabled", "勾选启用，更多菜单中调整顺序": "Enable presets; reorder in More", "普通与困难镜牢的权重及各层禁选": "Weights and floor bans for both modes", "在队伍配置中编辑各预设的专属权重": "Edit preset weights in Teams", "编辑权重…": "Edit weights…", "队伍配置…": "Teams…", "出战罪人": "Sinners", "使用停止按钮或快捷键结束战斗": "Use Stop or a hotkey to end battle", "截图与预览": "Capture & preview", "从 PlayCover 获取当前游戏画面": "Capture the current PlayCover game view", "-10 至 10，数值越高越优先": "−10 to 10; higher values take priority"})
        self.translations.update(bonus_translations())
        self.translations.update({"日常": "Daily", "领奖": "Rewards", "预设": "Preset", "权重": "Weights", "关闭公告": "Close"})
        self.translations.update({"镜牢 · 已完成 {current} · 剩余 {remaining}": "Mirror · Completed {current} · Remaining {remaining}", "图片同步 · {progress}%": "Image sync · {progress}%"})
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
        if text.startswith("theme-name:"):
            pack, separator, suffix = text[len("theme-name:"):].partition(" · ")
            english = self.data and self.data["config"]["language_in_program"] == "en"
            name = pack if english else (THEME_PACK_NAME_MAP | THEME_PACK_HARD_NAME_MAP).get(pack, pack)
            return name + separator + (self.text(suffix) if separator else "")
        if self.data and self.data["config"]["language_in_program"] == "en":
            if text.startswith("星光总消耗 · "):
                return self.translations.get("星光总消耗", "星光总消耗") + text[len("星光总消耗"):]
            return self.translations.get(text, text)
        return text

    def refresh_language(self):
        from frontend_appkit.widgets import refresh

        refresh(self.root)
        refresh(self.sidebar_content)
        refresh(self.navigation)
        refresh(self.run_controls)
        if hasattr(self, "page_title"):
            self.page_heading.setStringValue_(self.text(self.page_title[0]))
            self.page_description.setStringValue_(self.text(self.page_title[1]))
        self.log_toggle.setTitle_(self.text("运行日志") + (" ▾" if self.logs_expanded else " ▸"))
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
        if hasattr(self, "status_message"):
            source, values = self.status_message
            self.show_status(source, **values)

    def show_status(self, source, **values):
        self.status_message = source, values
        text = self.text(source)
        self.mirror_status.setStringValue_(text.format(**values) if values else text)

    def build_window(self):
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(((100, 100), (920, 500)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable | A.NSWindowStyleMaskResizable, A.NSBackingStoreBuffered, False)
        self.window.setReleasedWhenClosed_(False)
        self.window.setTitle_("AALC")
        self.window.setBackgroundColor_(A.NSColor.windowBackgroundColor())
        self.window.setMinSize_((860, 540))
        self.window.setDelegate_(self.delegate)
        self.window.setToolbarStyle_(A.NSWindowToolbarStyleUnified)
        self.root = LayoutView.alloc().initWithFrame_(((0, 0), (920, 500)))
        self.root.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
        self.window.setContentView_(self.root)
        self.navigation = segmented(None, ["任务", "工具", "设置"], ((0, 0), (3 * TOOLBAR_SLOT_WIDTH, 30)), lambda sender: self.select_primary(sender.selectedSegment()), self.targets, quiet=True)
        self.status = label(self.root, "正在连接后端…", ((0, 0), (TOOLBAR_SLOT_WIDTH, 24)))
        self.status.setFrameSize_((TOOLBAR_SLOT_WIDTH, self.status.intrinsicContentSize().height))
        self.status.removeFromSuperview()
        self.status.setIdentifier_(None)
        self.status.setTextColor_(A.NSColor.secondaryLabelColor())
        self.status.setAlignment_(A.NSTextAlignmentCenter)
        self.start_button = button(self.root, "开始运行", ((0, 0), (44, 32)), lambda sender: self.start_or_stop(), self.targets)
        self.pause_button = button(self.root, "暂停", ((0, 0), (44, 32)), lambda sender: self.client.request("task.pause"), self.targets)
        icon(self.start_button, "play.fill", self.text("开始运行"))
        icon(self.pause_button, "pause.fill", self.text("暂停"))
        self.run_controls = FlippedView.alloc().initWithFrame_(((0, 0), (3 * TOOLBAR_SLOT_WIDTH, TOOLBAR_HEIGHT)))
        for index, control in enumerate((self.status, self.pause_button, self.start_button)):
            control.removeFromSuperview()
            width, height = control.frame().size
            control.setFrameOrigin_((index * TOOLBAR_SLOT_WIDTH + (TOOLBAR_SLOT_WIDTH - width) / 2, (TOOLBAR_HEIGHT - height) / 2))
            control.setAutoresizingMask_(A.NSViewNotSizable)
            if isinstance(control, A.NSButton):
                control.setBezelStyle_(A.NSBezelStyleAccessoryBarAction)
                control.setShowsBorderOnlyWhileMouseInside_(True)
            self.run_controls.addSubview_(control)
        self.toolbar_items = {}
        for identifier, title, control in [("navigation", "导航", self.navigation), ("run", "状态", self.run_controls)]:
            control.removeFromSuperview()
            item = A.NSToolbarItem.alloc().initWithItemIdentifier_(identifier)
            item.setLabel_(self.text(title))
            item.setPaletteLabel_(self.text(title))
            item.setView_(toolbar_glass(control))
            item.setBordered_(False)
            item.setVisibilityPriority_(A.NSToolbarItemVisibilityPriorityUser)
            self.toolbar_items[identifier] = item
        self.toolbar_identifiers = ["navigation", A.NSToolbarFlexibleSpaceItemIdentifier, "run"]
        self.toolbar = A.NSToolbar.alloc().initWithIdentifier_("AALC.main")
        self.toolbar.setDelegate_(self.delegate)
        self.toolbar.setDisplayMode_(A.NSToolbarDisplayModeIconOnly)
        self.toolbar.setAllowsUserCustomization_(False)
        self.window.setToolbar_(self.toolbar)
        self.sidebar, self.sidebar_content = glass(self.root, ((0, 0), (196, 500)))
        if hasattr(self.sidebar, "setCornerRadius_"):
            self.sidebar.setCornerRadius_(0)
        label(self.sidebar_content, "任务", ((18, 20), (160, 22)), size=14, bold=True)
        subtitle(self.sidebar_content, "勾选要运行的任务", ((18, 46), (164, 18)))
        self.task_buttons, self.task_rows, self.task_summaries = [], [], []
        for i, name in enumerate(["日常任务", "领取奖励", "狂气换体", "镜牢任务"]):
            row = TaskRow.alloc().initWithFrame_(((8, 78 + i * 58), (180, 54)))
            row.select_callback = lambda index=i: self.select_page(index)
            row.setAccessibilityElement_(True)
            row.setAccessibilityRole_(A.NSAccessibilityRowRole)
            accessibility_label(row, name)
            self.sidebar_content.addSubview_(row)
            checkbox = button(row, "", ((10, 13), (20, 24)), lambda sender, key=TASK_KEYS[i]: self.patch({key: bool(sender.state())}), self.targets, checkbox=True)
            accessibility_label(checkbox, name)
            select = button(row, name, ((34, 5), (138, 24)), lambda sender, index=i: self.select_page(index), self.targets)
            select.setBordered_(False)
            select.setAlignment_(A.NSTextAlignmentLeft)
            select.setFont_(A.NSFont.systemFontOfSize_weight_(13, A.NSFontWeightSemibold))
            summary = subtitle(row, "", ((36, 30), (136, 18)))
            summary.setIdentifier_(None)
            self.task_buttons.append(checkbox)
            self.task_rows.append(row)
            self.task_summaries.append(summary)
        self.select_all_button = button(self.sidebar_content, "全选", ((18, 326), (70, 26)), lambda sender: self.patch(dict.fromkeys(TASK_KEYS, True)), self.targets)
        self.clear_tasks_button = button(self.sidebar_content, "清空", ((98, 326), (80, 26)), lambda sender: self.patch(dict.fromkeys(TASK_KEYS, False)), self.targets)
        self.sidebar_summary = subtitle(self.sidebar_content, "", ((18, 366), (160, 18)))
        self.sidebar_summary.setIdentifier_(None)
        self.page_heading = label(self.root, "", ((284, 20), (860, 32)), size=17, bold=True)
        self.page_heading.setIdentifier_(None)
        self.page_description = subtitle(self.root, "", ((284, 60), (860, 24)))
        self.page_description.setIdentifier_(None)
        self.section_navigation = segmented(self.root, ["常规设置", "队伍配置", "主题包设置", "高级设置"], ((284, 96), (520, 30)), lambda sender: self.select_mirror_section(sender.selectedSegment()), self.targets, quiet=True)
        self.task_detail_navigation = segmented(self.root, ["常规设置", "高级配置"], ((240, 96), (260, 30)), lambda sender: self.select_task_detail(sender.selectedSegment()), self.targets, quiet=True)
        self.settings_navigation = segmented(self.root, ["游戏连接", "定时任务", "外观与快捷键", "运行参数", "资源与关于"], ((284, 96), (760, 30)), lambda sender: self.select_settings_section(sender.selectedSegment()), self.targets, quiet=True)
        self.page_scroll, self.page = scroll(self.root, ((284, 140), (944, 430)))
        self.log_toggle = button(self.root, "运行日志 ▸", ((284, 790), (126, 30)), lambda sender: self.toggle_logs(), self.targets)
        self.log_toggle.setIdentifier_(None)
        self.mirror_status = label(self.root, "", ((420, 795), (650, 22)))
        self.mirror_status.setIdentifier_(None)
        self.mirror_status.setTextColor_(A.NSColor.secondaryLabelColor())
        self.log_clear = button(self.root, "清空日志", ((1094, 790), (130, 30)), lambda sender: self.client.request("logs.clear"), self.targets)
        self.log_scroll = A.NSScrollView.alloc().initWithFrame_(((284, 600), (944, 200)))
        self.log_scroll.setHasVerticalScroller_(True)
        self.log_scroll.setAutohidesScrollers_(True)
        self.log_view = A.NSTextView.alloc().initWithFrame_(((0, 0), (944, 200)))
        self.log_view.setEditable_(False)
        self.log_view.setFont_(A.NSFont.monospacedSystemFontOfSize_weight_(11, A.NSFontWeightRegular))
        self.log_view.setAutoresizingMask_(A.NSViewWidthSizable)
        self.log_view.setVerticallyResizable_(True)
        self.log_view.setHorizontallyResizable_(False)
        self.log_view.textContainer().setWidthTracksTextView_(True)
        self.log_view.setTextContainerInset_((12, 10))
        self.log_scroll.setDocumentView_(self.log_view)
        self.root.addSubview_(self.log_scroll)
        self.log_resize = LogResizeHandle.alloc().initWithFrame_(((0, 0), (100, 8)))
        self.log_resize.height_getter = lambda: self.log_scroll.frame().size.height + 38
        self.log_resize.resize_handler = self.resize_logs
        tooltip(self.log_resize, "拖动调整日志高度")
        self.root.addSubview_(self.log_resize)
        self.root.layout_handler = self.layout_window
        self.layout_window()
        self.window.setFrame_display_(((100, 100), (920, 580)), True)
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        self.native.activateIgnoringOtherApps_(True)

    def layout_window(self):
        width, height = self.root.bounds().size
        tasks = self.page_index < 6
        x = 212 if tasks else 20
        content_width = width - x - 20
        nested = self.page_index in {0, 2, 3, 4, 5, 6}
        top = 116 if nested else 82
        log_height = max(110, min(getattr(self, "log_height", 210), max(110, height - top - 156))) if self.logs_expanded else 32
        bottom = height - 12 - log_height - 8
        if tasks and self.sidebar.superview() is None:
            self.root.addSubview_(self.sidebar)
        elif not tasks and self.sidebar.superview() is not None:
            self.sidebar.removeFromSuperview()
        self.sidebar.setFrame_(((0, 0), (196, height)))
        self.page_heading.setFrame_(((x, 18), (content_width, 24)))
        self.page_description.setFrame_(((x, 46), (content_width, 18)))
        self.task_detail_navigation.setFrame_(((x, 78), (240, 26)))
        self.task_detail_navigation.setHidden_(self.page_index not in {0, 2})
        self.section_navigation.setFrame_(((x, 78), (min(392, content_width), 26)))
        self.settings_navigation.setFrame_(((x, 78), (min(680, content_width), 26)))
        for control in (self.task_detail_navigation, self.section_navigation, self.settings_navigation):
            for index in range(control.segmentCount()):
                control.setWidth_forSegment_(control.frame().size.width / control.segmentCount(), index)
        self.section_navigation.setHidden_(self.page_index not in {3, 4, 5})
        self.settings_navigation.setHidden_(self.page_index != 6)
        self.page_scroll.setFrame_(((x, top), (content_width, max(100, bottom - top))))
        log_y = height - 12 - log_height
        self.log_toggle.setFrame_(((x, log_y), (126, 30)))
        self.mirror_status.setFrame_(((x + 140, log_y + 5), (max(100, content_width - 290), 22)))
        self.log_clear.setFrame_(((x + content_width - 130, log_y), (130, 30)))
        self.log_scroll.setFrame_(((x, log_y + 38), (content_width, max(0, log_height - 38))))
        self.log_scroll.setHidden_(not self.logs_expanded)
        self.log_clear.setHidden_(not self.logs_expanded)
        self.log_resize.setFrame_(((x, log_y - 8), (content_width, 8)))
        self.log_resize.setHidden_(not self.logs_expanded)

    def resize_logs(self, height):
        if self.logs_expanded:
            self.log_height = height
            self.layout_window()
            self.log_height = self.log_scroll.frame().size.height + 38

    def toggle_logs(self):
        self.logs_expanded = not self.logs_expanded
        self.log_toggle.setTitle_(self.text("运行日志") + (" ▾" if self.logs_expanded else " ▸"))
        self.layout_window()

    def navigate(self, callback):
        def failed(message):
            self.sync_navigation()
            self.error(message)
        try:
            self.commit_current(callback, on_error=failed)
        except (ValueError, TypeError) as exc:
            failed(str(exc))

    def apply_page(self, index):
        self.page_index = index
        self.patch({"default_page": index})
        self.build_page()

    def select_primary(self, index):
        self.select_page(self.last_task_page if index == 0 else 7 if index == 1 else 6)

    def select_mirror_section(self, index):
        def selected():
            self.mirror_section = index
            self.apply_page(4 if index == 1 else 5 if index == 2 else 3)
        self.navigate(selected)

    def select_task_detail(self, index):
        def selected():
            self.task_details[self.page_index] = index
            self.build_page()
        self.navigate(selected)

    def select_settings_detail(self, detail):
        def selected():
            self.settings_details[self.settings_section] = detail
            self.build_page()
        self.navigate(selected)

    def select_settings_section(self, index):
        def selected():
            self.settings_section = index
            self.build_page()
        self.navigate(selected)

    def toggle_group(self, expanded, key):
        def selected():
            expanded.symmetric_difference_update({key})
            self.build_page()
        self.navigate(selected)

    def sync_navigation(self):
        self.navigation.setSelectedSegment_(0 if self.page_index < 6 else 1 if self.page_index == 7 else 2)
        if self.page_index < 6:
            self.last_task_page = self.page_index
        if self.page_index in {4, 5}:
            self.mirror_section = 1 if self.page_index == 4 else 2
        elif self.page_index == 3 and self.mirror_section not in {0, 3}:
            self.mirror_section = 0
        self.section_navigation.setSelectedSegment_(self.mirror_section)
        self.settings_navigation.setSelectedSegment_(self.settings_section)
        self.task_detail_navigation.setSelectedSegment_(self.task_details.get(self.page_index, 0))
        for i, row in enumerate(self.task_rows):
            row.selected = self.page_index == i or (i == 3 and self.page_index in {4, 5})
            if hasattr(row, "setAccessibilitySelected_"):
                row.setAccessibilitySelected_(row.selected)
            row.setNeedsDisplay_(True)
        self.layout_window()

    def build_menus(self):
        menu = A.NSMenu.alloc().init()
        root = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("AALC", None, "")
        submenu = A.NSMenu.alloc().initWithTitle_("AALC")
        self.menu_item(submenu, "显示 AALC", self.restore)
        self.menu_item(submenu, "设置", lambda: (self.restore(), self.select_page(6)), key=",")
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
        image = template_image(resource_path("assets/logo/dante-template.png"))
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
            except OSError:
                return
            with connection:
                try:
                    connection.settimeout(1)
                    parts, size = [], 0
                    while True:
                        part = connection.recv(65536)
                        if not part:
                            break
                        size += len(part)
                        if size > 65536:
                            raise ValueError("Resident command is too long")
                        parts.append(part)
                        if b"\n" in part:
                            break
                    payload = b"".join(parts).partition(b"\n")[0].decode("utf-8")
                except (OSError, ValueError):
                    continue
            args = payload.split("|") if payload else []
            self.client.incoming.put({"event": "command", "data": args})

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
        if event in {"update", "update_status"} and getattr(self, "quitting", False):
            return
        if event in {"ready", "state"}:
            first = self.data is None
            previous_config = self.data["config"] if self.data else None
            self.data = data
            if first:
                self.log_view.setString_("\n".join(data.get("logs", [])))
                self.page_index = min(7, max(0, int(data["config"]["default_page"])))
                if self.page_index == 6:
                    self.page_index = 0  # Settings is an auxiliary detail, not the launch destination.
                self.sync_navigation()
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
                            controls = form.controls.get(key, [])
                            controls = controls if isinstance(controls, list) else [controls]
                            if any(isinstance(control, A.NSTextField) and control.currentEditor() is not None for control in controls):
                                continue
                            try:
                                local_value = form.getters[key]()
                            except (ValueError, TypeError):
                                continue
                            if local_value != previous_config.get(key):
                                continue
                            form.set_value(key, data["config"].get(key))
            for editor in getattr(self, "editors", []):
                if not editor.closed and hasattr(editor, "stats_label"):
                    stats = data["config"].get("teams", {}).get(str(editor.team_scope))
                    if stats is not None:
                        editor.stats_label.setStringValue_(self.team_stats_text(stats))
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
            self.show_status("镜牢 · 已完成 {current} · 剩余 {remaining}" if data else "", **(data or {}))
        elif event == "focus":
            self.restore()
        elif event in {"screenshot", "capture"}:
            self.show_capture(data)
        elif event == "command":
            if not self.quitting:
                self.client.request("command", {"args": data})
                scheduled = len(data) >= 3 and data[:2] == ["start", "--exit"] and data[2] in {"autodaily", "autodaily2", "autodaily3", "autodaily4"}
                if not scheduled:
                    self.restore()
        elif event == "resources":
            if data["changes"] and (not data["startup"] or data["automatic"]) and confirm("图片资源可更新", data["message"] or "下载并同步最新图片资源？", accept="同步"):
                self.client.request("resources.apply")
            else:
                self.show_status(data["message"] or "图片资源已是最新")
                if data["startup"]:
                    self.client.request("resources.skip")
        elif event == "resource_progress":
            self.show_status("图片同步 · {progress}%", progress=data)
        elif event == "resources_applied":
            self.show_status(data["message"])
        elif event == "announcement":
            self.show_announcements(data)
        elif event == "update":
            if data["status"] == "UPDATE_AVAILABLE":
                self.show_text("官方发布新版本 · " + data["version"], data["content"], html=True, source_url=data["release_url"])
            elif data["status"] == "FAILURE":
                if not data.get("automatic", False):
                    self.error(data["message"])
            else:
                self.show_status(data.get("message") or "软件已是最新")
        elif event == "update_status":
            self.update_result = data
        elif event == "completion_suppressed":
            if data:
                self.show_status("定时任务已排队，当前任务完成后继续")
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
        if "after_completion_actions" in values:
            values = values | {"keep_after_completion": True}
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
            if "after_completion_actions" in values:
                values["keep_after_completion"] = True
            self.client.request("config.patch", {"values": values}, lambda result: callback(), on_error=on_error)
        else:
            callback()

    def start_or_stop(self):
        if self.data["state"]["running"]:
            self.client.request("task.stop")
        else:
            self.commit_current(lambda: self.client.request("task.start"))

    def select_page(self, index):
        self.navigate(lambda: self.apply_page(index))

    def build_page(self):
        if not self.data:
            return
        for view in list(self.page.subviews()):
            view.removeFromSuperview()
        self.page_targets = []
        key = PAGE_KEYS[self.page_index]
        self.form = None
        self.connection_controls = []
        self.forms = []
        self.team_order_controls = []
        self.field_actions = []
        titles = {"daily": ("日常任务", "经验本、纽本与每日配队"), "reward": ("领取奖励", "选择邮件和日常、周常奖励的领取范围"), "energy": ("狂气换体", "配置购买体力次数与换体选项"), "mirror": ("镜牢任务", "配置镜牢、队伍与主题包"), "teams": ("镜牢任务", "配置镜牢、队伍与主题包"), "theme": ("镜牢任务", "配置镜牢、队伍与主题包"), "settings": ("设置", "游戏连接、定时任务与应用偏好"), "tools": ("工具", "自动战斗与截图")}
        title, description = titles[key]
        self.page_title = title, description
        self.page_heading.setStringValue_(self.text(title))
        self.page_description.setStringValue_(self.text(description))
        if key == "daily":
            if self.task_details[0]:
                y = 16
                for group, title, keys in [("EXP", "经验本按日期配队", GROUPS[key][5:10]), ("thread", "纽本按日期配队", GROUPS[key][10:])]:
                    form = self.add_collapsible_form(keys, title, self.expanded_daily, group, start=y)
                    y = form.y + 16
            else:
                self.add_form(GROUPS[key][:5], sections={"set_EXP_count": "日常关卡"})
        elif key == "reward":
            self.add_form(GROUPS[key], sections={GROUPS[key][0]: "奖励范围"})
        elif key == "energy":
            self.add_form(GROUPS[key][1:] if self.task_details[2] else GROUPS[key][:1], sections={"Dr_Grandet_mode": "换体策略", "set_lunacy_to_enkephalin": "购买体力"})
        elif key == "mirror":
            if self.mirror_section == 3:
                advanced = ["floor_3_exit", "infinite_dungeons", "select_event_pack", "skip_event_pack", "re_claim_rewards", "fight_to_last_man"]
                form = self.add_form(advanced, sections={"floor_3_exit": "运行策略", "select_event_pack": "活动与战斗"})
                form = self.add_form(["select_team_by_order", "auto_hard_mirror", "hard_mirror_chance", "last_auto_change"], start=form.y + 16, sections={"select_team_by_order": "配队与自动困难镜牢"})
                field = form.controls["last_auto_change"]
                row = field.superview()
                field.setFrame_(((row.frame().size.width - 316, field.frame().origin.y), (160, 28)))
                for caption in row.subviews():
                    if caption.identifier() == FIELDS["ConfigModel"]["last_auto_change"]["label"]:
                        caption.setFrameSize_((field.frame().origin.x - 32, caption.frame().size.height))
                update = button(row, "更新为当前时间", ((row.frame().size.width - 148, field.frame().origin.y), (132, 28)), lambda sender: self.update_mirror_timestamp(form), self.page_targets)
                update.setAutoresizingMask_(A.NSViewMinXMargin)
                self.field_actions.append((update, field))
            else:
                self.add_form([name for name in GROUPS[key] if name not in {"floor_3_exit", "infinite_dungeons", "select_event_pack", "skip_event_pack", "re_claim_rewards", "fight_to_last_man"}], sections={"set_mirror_count": "次数与模式", "no_weekly_bonuses": "加成与奖励"})
        elif key == "teams":
            self.build_teams()
        elif key == "theme":
            width = self.page.frame().size.width - 40
            for y, title, description, action_title, callback in [
                (16, "全局主题包权重", "普通与困难镜牢的权重及各层禁选", "编辑权重…", lambda: self.open_theme()),
                (100, "队伍专属权重", "在队伍配置中编辑各预设的专属权重", "队伍配置…", lambda: self.select_mirror_section(1)),
            ]:
                row = SurfaceView.alloc().initWithFrame_(((20, y), (width, 72)))
                row.kind = "group"
                row.setAutoresizingMask_(A.NSViewWidthSizable)
                self.page.addSubview_(row)
                label(row, title, ((16, 12), (width - 164, 22)), bold=True)
                subtitle(row, description, ((16, 38), (width - 164, 18)))
                control = button(row, action_title, ((width - 132, 21), (116, 28)), lambda sender, callback=callback: callback(), self.page_targets)
                control.setAutoresizingMask_(A.NSViewMinXMargin)
            self.page.setFrameSize_((self.page.frame().size.width, 200))
        elif key == "settings":
            self.build_settings()
        elif key == "tools":
            self.build_tools()
        self.sync_navigation()
        self.update_state()

    def add_form(self, keys, *, start=16, sections=None):
        form = Form(self.page, self.data["config"], keys, self.page_targets, lambda name, value: self.patch({name: value}), start=start, text=self.text, sections=sections, grouped=True)
        self.forms.append(form)
        self.form = form
        return form

    def update_mirror_timestamp(self, form):
        value = time.time()
        field = form.controls["last_auto_change"]
        if field.currentEditor() is not None:
            field.currentEditor().setString_(str(value))
        field.setObjectValue_(value)
        self.patch({"last_auto_change": value})

    def add_collapsible_form(self, keys, title, expanded, key, *, start=16, enable_title=None):
        is_expanded = key in expanded
        form = self.add_form(keys if is_expanded else keys[:1], start=start)
        enabled = form.controls[keys[0]]
        enabled.setTitle_("")
        enabled.setIdentifier_(None)
        enabled.setFrameSize_((20, 28))
        enabled.setAutoresizingMask_(A.NSViewNotSizable)
        accessibility_label(enabled, enable_title or title)
        row = enabled.superview()
        disclosure = button(row, title, ((44, 8), (row.frame().size.width - 60, 28)), lambda sender: self.toggle_group(expanded, key), self.page_targets)
        disclosure.setBordered_(False)
        disclosure.setAlignment_(A.NSTextAlignmentLeft)
        disclosure.setFont_(A.NSFont.systemFontOfSize_weight_(13, A.NSFontWeightSemibold))
        disclosure.setAutoresizingMask_(A.NSViewWidthSizable)
        image = A.NSImage.imageWithSystemSymbolName_accessibilityDescription_("chevron.down" if is_expanded else "chevron.right", self.text(title))
        if image:
            image.setSize_((10, 10))
            disclosure.setImage_(image)
            disclosure.setImagePosition_(A.NSImageLeft)
        return form

    def update_state(self):
        if self.data is None:
            return
        state, config = self.data["state"], self.data["config"]
        running = state["running"]
        self.window.setTitle_("AALC " + self.data["version"])
        self.start_button.setTitle_(self.text("停止中…" if state["stopping"] else "停止任务" if running else "开始运行"))
        icon(self.start_button, "stop.fill" if running else "play.fill", self.start_button.title())
        self.start_button.setEnabled_(not state["stopping"] and not state["startup"] and state["kind"] not in {"connection", "screenshot"})
        self.pause_button.setTitle_(self.text("继续" if state["paused"] else "暂停"))
        icon(self.pause_button, "play.fill" if state["paused"] else "pause.fill", self.pause_button.title())
        self.pause_button.setEnabled_(state["kind"] in {"task", "battle"} and not state["stopping"])
        self.status.setStringValue_(self.text("停止中…" if state["stopping"] else "已暂停" if state["paused"] else "运行中" if running else "就绪") + (f" · 排队 {state['queued']}" if state["queued"] else ""))
        self.status.setToolTip_(self.status.stringValue())
        for i, control in enumerate(self.task_buttons):
            control.setState_(int(config[TASK_KEYS[i]]))
            control.setEnabled_(not running)
        self.select_all_button.setEnabled_(not running)
        self.clear_tasks_button.setEnabled_(not running)
        if hasattr(self, "sidebar_summary"):
            count = sum(bool(config[key]) for key in TASK_KEYS)
            self.sidebar_summary.setStringValue_(f"{count} / {len(TASK_KEYS)} " + self.text("项任务已启用"))
        def enable_tree(view, enabled):
            if isinstance(view, A.NSControl):
                view.setEnabled_(enabled)
            for child in view.subviews():
                enable_tree(child, enabled)

        if PAGE_KEYS[self.page_index] in {"daily", "reward", "energy", "mirror", "teams", "tools", "theme"}:
            deleting_team = self.page_index == 4 and getattr(self, "deleting_team", False)
            enable_tree(self.page, not running and not deleting_team)
        restricted = set(TASK_KEYS + GROUPS["playcover"] + sum([GROUPS[k] for k in ("daily", "reward", "energy", "mirror", "completion")], []))
        for form in self.forms:
            for name, controls in form.controls.items():
                if name in restricted or self.page_index == 6 or (self.page_index == 3 and self.mirror_section == 3):
                    for control in controls if isinstance(controls, list) else [controls]:
                        enable_tree(control, not running if name in restricted else True)
        for control, number in self.team_order_controls:
            control.setEnabled_(not running and not getattr(self, "deleting_team", False) and number in config["teams_active_queue"])
        for control in getattr(self, "connection_controls", []):
            control.setEnabled_(not running)
        for control, field in getattr(self, "field_actions", []):
            control.setEnabled_(field.isEnabled())
        for editor in getattr(self, "editors", []):
            if not getattr(editor, "tool_kind", None) or editor.closed:
                continue
            for control in editor.root.subviews():
                if isinstance(control, A.NSButton):
                    control.setEnabled_(not running)
            if editor.tool_kind == "battle":
                battle = running and state["kind"] == "battle"
                editor.start_button.setTitle_(self.text("停止任务" if battle else "开始自动战斗"))
                editor.start_button.setEnabled_((not running or battle) and not state["stopping"] and not state["startup"])
        summaries = [f"{self.text('经验')} {config['set_EXP_count']} · {self.text('纽本')} {config['set_thread_count']}", str(next((self.text(title) for title, value in FIELDS["options"]["set_get_prize_options"] if value == config["set_get_prize"]), "")), self.text("购买次数") + f" · {config['set_lunacy_to_enkephalin']}", self.text("镜牢次数") + f" · {config['set_mirror_count']}"]
        for view, summary in zip(self.task_summaries, summaries):
            view.setStringValue_(summary)
            view.setToolTip_(summary)
        appearance = config["theme_mode"]
        self.native.setAppearance_(None if appearance == "AUTO" else A.NSAppearance.appearanceNamed_(A.NSAppearanceNameDarkAqua if appearance == "DARK" else A.NSAppearanceNameAqua))

    def build_teams(self):
        values = self.data["config"]
        queue = values["teams_active_queue"]
        button(self.page, "新增队伍", ((20, 10), (112, 30)), lambda sender: self.client.request("team.add"), self.page_targets)
        subtitle(self.page, "勾选启用，更多菜单中调整顺序", ((148, 16), (self.page.frame().size.width - 168, 18)))
        y = 56
        for number, team in sorted(values["teams"].items(), key=lambda item: int(item[0])):
            n = int(number)
            order = f" · #{queue.index(n) + 1}" if n in queue else ""
            width = self.page.frame().size.width - 40
            row = SurfaceView.alloc().initWithFrame_(((20, y), (width, 76)))
            row.kind = "group"
            row.setAutoresizingMask_(A.NSViewWidthSizable)
            self.page.addSubview_(row)
            title = button(row, self.text("预设") + f" {n}{order} · {team['remark_name'] or 'Team ' + str(team['team_number'])}", ((16, 10), (width - 32, 26)), lambda sender, number=n: self.client.request("team.enable", {"number": number, "enabled": bool(sender.state())}), self.page_targets, checkbox=True, checked=n in queue)
            title.setAutoresizingMask_(A.NSViewWidthSizable)
            subtitle(row, self.text("队伍体系") + " · " + self.text(str(FIELDS["options"]["all_systems"][team['team_system']][0])), ((36, 43), (width - 328, 20)))
            for offset, title, callback in [(284, "编辑", lambda n=n: self.edit_team(n)), (192, "权重", lambda n=n: self.open_theme(n))]:
                control = button(row, title, ((width - offset, 40), (84, 28)), lambda sender, callback=callback: callback(), self.page_targets)
                control.setAutoresizingMask_(A.NSViewMinXMargin)
            more = menu_button(row, "更多", ((width - 100, 40), (84, 28)), [
                ("上移", lambda n=n: self.client.request("team.order", {"number": n, "offset": -1})),
                ("下移", lambda n=n: self.client.request("team.order", {"number": n, "offset": 1})),
                ("复制", lambda n=n: self.client.request("team.add", {"copy_from": n})),
                ("删除", lambda n=n: self.delete_team(n)),
            ], self.page_targets)
            more.setAutoresizingMask_(A.NSViewMinXMargin)
            self.team_order_controls.extend((more.itemAtIndex_(index), n) for index in (1, 2))
            y += 88
        self.page.setFrameSize_((self.page.frame().size.width, y + 20))

    def delete_team(self, number):
        if getattr(self, "deleting_team", False) or not confirm("删除队伍？", f"删除预设 {number} 及其专属主题包权重。"):
            return
        self.deleting_team = True
        self.team_generation = getattr(self, "team_generation", 0) + 1

        def finished(_):
            self.deleting_team = False
            self.update_state()

        def failed(message):
            finished(None)
            self.error(message)

        try:
            self.update_state()
            for editor in list(self.editors):
                scope = getattr(editor, "team_scope", getattr(editor, "theme_scope", None))
                if not editor.closed and scope is not None and scope >= number:
                    if not editor.close_window(editor.window):
                        finished(None)
                        return
            self.client.request("team.delete", {"number": number}, finished, on_error=failed)
        except Exception:
            finished(None)
            raise

    def edit_team(self, number):
        if getattr(self, "deleting_team", False):
            return
        if self.team_editor and not self.team_editor.closed:
            self.team_editor.window.makeKeyAndOrderFront_(None)
            return
        draft = TeamDraft(self.data["config"]["teams"][str(number)])
        editor = Editor(self, f"队伍预设 {number}", team=True)
        editor.team_scope = number
        self.team_editor = editor
        self.client.request("draft", {"open": True})
        sinner_controls = []

        def sinner_changed(index, selected):
            draft.select_sinner(index, selected)
            for i, control in enumerate(sinner_controls):
                order = draft.values["sinner_order"][i]
                control.setTitle_(SINNERS[i] + (f" · {order}" if order else ""))

        label(editor.document, "出战罪人", ((20, 12), (740, 20)), size=12, bold=True)
        for i, name in enumerate(SINNERS):
            order = draft.values["sinner_order"][i]
            control = button(editor.document, name + (f" · {order}" if order else ""), ((20 + (i % 4) * 188, 38 + (i // 4) * 34), (182, 28)), lambda sender, i=i: sinner_changed(i, bool(sender.state())), editor.targets, checkbox=True, checked=draft.values["chosen_sinners"][i])
            control.setIdentifier_(None)
            sinner_controls.append(control)

        def change(key, value):
            draft.set(key, value)
            for name in ("avoid_skill_3", "prioritize_skill_3", "defense_first_round", "defense_for_solo", *["system_" + system for system in SYSTEMS]):
                form.set_value(name, draft.values[name])
            for system in SYSTEMS:
                form.controls["system_" + system].setEnabled_(system != SYSTEMS[draft.values["team_system"]])

        form = Form(editor.document, draft.values, [key for key in FIELDS["TeamSetting"] if key not in HIDDEN_TEAM], editor.targets, change, team=True, start=152, text=self.text, sections={"team_system": "队伍与体系", "system_burn": "饰品舍弃", "do_not_heal": "商店与合成", "avoid_skill_3": "战斗策略", "fixed_team_use": "用途与奖励", "opening_bonus": "星光与开局", "second_system": "第二体系", "observe_ego_gift": "观测饰品", "skill_replacement": "技能与刷新"}, grouped=True)
        for system in SYSTEMS:
            form.controls["system_" + system].setEnabled_(system != SYSTEMS[draft.values["team_system"]])

        def collect():
            editor.window.makeFirstResponder_(None)
            for key, value in form.values().items():
                draft.set(key, value)
            return {key: value for key, value in draft.values.items() if key not in STATS and key not in {"use_team_code", "team_code"}}

        def save():
            self.client.request("team.save", {"number": number, "values": collect()}, lambda result: editor.close())

        menu_button(editor.root, "更多", ((20, 14), (112, 30)), [
            ("导出 YAML", lambda: self.export_team(number)),
            ("导入 YAML", lambda: self.import_team(number, editor)),
            ("复制配置码", lambda: self.copy_team(number)),
            ("粘贴配置码", lambda: self.paste_team(number, form, draft)),
        ], editor.targets)
        cancel = button(editor.root, "取消", ((568, 14), (88, 30)), lambda sender: editor.close_window(editor.window), editor.targets)
        save_button = button(editor.root, "保存", ((668, 14), (112, 30)), lambda sender: save(), editor.targets)
        for control in (cancel, save_button):
            control.setAutoresizingMask_(A.NSViewMinXMargin)
        editor.stats_label = label(editor.document, self.team_stats_text(draft.values), ((20, form.y + 16), (740, 26)))
        editor.stats_label.setIdentifier_(None)
        button(editor.document, "清空历史统计", ((20, form.y + 50), (180, 30)), lambda sender: self.clear_stats(number), editor.targets)
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
            if not isinstance(values, dict):
                raise ValueError("队伍配置码必须包含设置对象")
            editor = self.team_editor
            self.client.request("team.save", {"number": number, "values": {key: value for key, value in values.items() if key not in STATS and key not in {"use_team_code", "team_code"}}}, lambda result: editor.close())
        except (ValueError, TypeError) as exc:
            self.error(str(exc))

    @staticmethod
    def team_stats_text(stats):
        return f"普通镜牢 {stats['mirror_normal_count']} 次 · 平均 {(stats['total_mirror_time_normal'] or [0.0])[0]:.1f} 秒    困难镜牢 {stats['mirror_hard_count']} 次 · 平均 {(stats['total_mirror_time_hard'] or [0.0])[0]:.1f} 秒"

    def clear_stats(self, number):
        if confirm("清空历史统计？", "此操作会清空该队伍的镜牢次数和耗时记录。"):
            self.client.request("team.stats.clear", {"number": number})

    def build_settings(self):
        detail = self.settings_details.get(self.settings_section, False)
        if self.settings_section == 0:
            keys = ["playcover_host", "playcover_port", "playcover_bundle_id", "playcover_capture_method"] if detail else ["game_profile", "playcover_app_path"]
            form = self.add_form(keys, sections={keys[0]: "高级连接设置" if detail else "PlayCover 与游戏连接"})
            choose = button(self.page, "选择游戏…", ((20, form.y + 12), (130, 30)), lambda sender: self.choose_game(), self.page_targets)
            test = button(self.page, "测试连接与截图", ((162, form.y + 12), (180, 30)), lambda sender: self.test_connection(), self.page_targets)
            self.connection_controls.extend([choose, test])
            button(self.page, "返回游戏连接" if detail else "高级连接设置…", ((354, form.y + 12), (176, 30)), lambda sender: self.select_settings_detail(not detail), self.page_targets)
            self.page.setFrameSize_((self.page.frame().size.width, form.y + 88))
        elif self.settings_section == 1:
            y = 16
            for suffix in ("", "2", "3", "4"):
                keys = GROUPS["schedule" + suffix]
                form = self.add_collapsible_form(keys, "定时任务 " + (suffix or "1"), self.expanded_schedules, suffix, start=y, enable_title="启用定时任务 " + (suffix or "1"))
                y = form.y + 16
        elif self.settings_section == 2:
            keys = ["shutdown_hotkey", "pause_hotkey", "resume_hotkey"] if detail else ["language_in_program", "theme_mode", "minimize_to_tray"]
            form = self.add_form(keys, sections={keys[0]: "全局快捷键" if detail else "外观与语言"})
            button(self.page, "返回外观设置" if detail else "配置全局快捷键…", ((20, form.y + 12), (230, 32)), lambda sender: self.select_settings_detail(not detail), self.page_targets)
            self.page.setFrameSize_((self.page.frame().size.width, form.y + 72))
        elif self.settings_section == 3:
            keys = ["screenshot_interval", "mouse_action_interval", "mouse_down_duration"] if detail else ["memory_protection", "experimental_keep_screen_awake", "task_stall_timeout"]
            form = self.add_form(keys, sections={keys[0]: "输入参数" if detail else "运行偏好"})
            button(self.page, "返回运行偏好" if detail else "高级输入参数…", ((20, form.y + 12), (230, 32)), lambda sender: self.select_settings_detail(not detail), self.page_targets)
            if detail:
                self.page.setFrameSize_((self.page.frame().size.width, form.y + 72))
            else:
                self.add_form(["after_completion_actions"], start=form.y + 56, sections={"after_completion_actions": "完成后"})
        else:
            form = self.add_form([key for key in ["check_update", "update_prerelease_enable", "image_resource_sync", "image_resource_source"] if key not in HIDDEN_APP_FIELDS], sections={"check_update": "软件与图片资源"})
            y = form.y + 24
            for i, (name, callback) in enumerate([
                ("检查软件更新", lambda: self.client.request("updates.check")),
                ("检查图片资源", lambda: self.client.request("resources.check")),
                ("打开日志目录", lambda: A.NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_(str(data_path("logs"))))),
                ("公告", lambda: self.client.request("announcements")),
                ("GitHub", lambda: self.open_url("https://github.com/KIYI671/AhabAssistantLimbusCompany")),
                ("Discord", lambda: self.open_url("https://discord.gg/vUAw98cEVe")),
                ("反馈", lambda: self.open_url("https://github.com/KIYI671/AhabAssistantLimbusCompany/issues")),
            ]):
                button(self.page, name, ((24 + (i % 3) * 260, y + (i // 3) * 44), (242, 32)), lambda sender, callback=callback: callback(), self.page_targets)
            self.page.setFrameSize_((self.page.frame().size.width, y + 160))

    def test_connection(self):
        try:
            self.commit_current(lambda: self.client.request("connection.test"), on_error=self.error)
        except (ValueError, TypeError) as exc:
            self.error(str(exc))

    def choose_game(self):
        path = choose_path(applications=True)
        if path:
            self.client.request("app.identity", {"path": path}, lambda value: self.patch({"playcover_app_path": value["path"], "playcover_bundle_id": value["bundle_id"]}))

    def build_tools(self):
        width = self.page.frame().size.width - 40
        for index, (kind, title, description, action_title) in enumerate([
            ("battle", "自动战斗", "使用停止按钮或快捷键结束战斗", "打开自动战斗…"),
            ("capture", "截图小工具", "从 PlayCover 获取当前游戏画面", "打开截图小工具…"),
        ]):
            row = SurfaceView.alloc().initWithFrame_(((20, 16 + index * 112), (width, 96)))
            row.kind = "group"
            row.setAutoresizingMask_(A.NSViewWidthSizable)
            self.page.addSubview_(row)
            label(row, title, ((16, 14), (width - 240, 22)), bold=True)
            subtitle(row, description, ((16, 46), (width - 240, 18)))
            control = button(row, action_title, ((width - 208, 34), (192, 28)), lambda sender, tool=kind: self.open_tool(tool), self.page_targets)
            control.setAutoresizingMask_(A.NSViewMinXMargin)
        self.page.setFrameSize_((self.page.frame().size.width, 256))

    def open_tool(self, kind):
        for editor in self.editors:
            if not editor.closed and getattr(editor, "tool_kind", None) == kind:
                editor.window.makeKeyAndOrderFront_(None)
                return editor
        editor = Editor(self, self.text("自动战斗" if kind == "battle" else "截图小工具"))
        editor.tool_kind = kind
        editor.window.setMinSize_((440, 280) if kind == "battle" else (520, 380))
        editor.window.setContentSize_((480, 280) if kind == "battle" else (720, 480))
        editor.scroller.setHidden_(True)
        if kind == "battle":
            label(editor.root, "自动战斗", ((20, 16), (440, 24)), size=16, bold=True)
            subtitle(editor.root, "使用停止按钮或快捷键结束战斗", ((20, 48), (440, 18)))
            options = [button(editor.root, name, ((20, 80 + index * 32), (440, 28)), lambda sender: None, editor.targets, checkbox=True) for index, name in enumerate(["无限守备", "第一回合开启守备", "不处理事件"])]

            def start_or_stop(sender):
                if self.data["state"]["running"] and self.data["state"]["kind"] == "battle":
                    self.client.request("task.stop")
                else:
                    self.client.request("battle.start", dict(zip(["defense", "defense_on_turn1", "not_choose_event"], [bool(control.state()) for control in options])))
            editor.start_button = button(editor.root, "开始自动战斗", ((20, 208), (180, 32)), start_or_stop, editor.targets)
        else:
            button(editor.root, "截图", ((20, 16), (132, 32)), lambda sender: self.client.request("screenshot"), editor.targets)
            editor.bundle_label = subtitle(editor.root, "", ((168, 23), (532, 20)))
            editor.bundle_label.setIdentifier_(None)
            editor.image_view = A.NSImageView.alloc().initWithFrame_(((20, 64), (680, 396)))
            editor.image_view.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
            editor.image_view.setImageFrameStyle_(A.NSImageFrameGrayBezel)
            editor.image_view.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
            editor.root.addSubview_(editor.image_view)
            editor.placeholder = subtitle(editor.image_view, "点击截图获取当前游戏画面", ((12, 190), (656, 16)))
            height = editor.placeholder.intrinsicContentSize().height
            editor.placeholder.setFrame_(((12, (396 - height) / 2), (656, height)))
            editor.placeholder.setAlignment_(A.NSTextAlignmentCenter)
            editor.placeholder.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewMinYMargin | A.NSViewMaxYMargin)
        self.update_state()
        editor.show()
        return editor

    def open_theme(self, number=None):
        if number is not None and getattr(self, "deleting_team", False):
            return
        if self.focus_theme_editor(number):
            return
        generation = getattr(self, "team_generation", 0)

        def received(values):
            if number is None or generation == getattr(self, "team_generation", 0):
                self.edit_theme(number, values)

        self.client.request("theme.get", {"number": number}, received)

    def focus_theme_editor(self, number):
        for editor in self.editors:
            if not editor.closed and hasattr(editor, "theme_scope") and editor.theme_scope == number:
                editor.window.makeKeyAndOrderFront_(None)
                return True
        return False

    def edit_theme(self, number, values):
        if number is not None and getattr(self, "deleting_team", False):
            return
        if self.focus_theme_editor(number):
            return
        draft = ThemeDraft(values)
        editor = Editor(self, "全局主题包权重" if number is None else f"队伍 {number} · 主题包权重")
        editor.theme_scope = number
        mode, floor = [False], [1]
        from frontend_appkit.widgets import textfield

        def threshold_changed(sender):
            value = int(sender.stringValue())
            if not -10 <= value <= 10:
                raise ValueError("优选阈值范围为 -10…10")
            if value != draft.config_data.get("preferred_thresholds", 0):
                draft.config_data["preferred_thresholds"] = value
                draft._has_unsaved_changes = True

        threshold = None
        if number is None:
            label(editor.root, "优选阈值", ((20, 62), (96, 22)))
            threshold = textfield(editor.root, draft.config_data.get("preferred_thresholds", 0), ((116, 58), (76, 28)), threshold_changed, editor.targets, numeric=True)
            subtitle(editor.root, "-10 至 10，数值越高越优先", ((208, 64), (560, 18)))
        else:
            subtitle(editor.root, self.text("优选阈值") + " · " + self.text("全局主题包权重"), ((20, 64), (760, 18)))
        editor.scroller.setFrame_(((0, 98), (800, 522)))
        targets = []
        inputs = []

        def commit():
            editor.window.makeFirstResponder_(None)
            if threshold is not None:
                threshold_changed(threshold)
            for pack, control, hard in inputs:
                weight = int(control.stringValue())
                if not -10 <= weight <= 10:
                    raise ValueError("权重范围为 -10…10")
                config_key = "theme_pack_list_hard" if hard else "theme_pack_list"
                if weight != draft.config_data.get(config_key, {}).get(pack):
                    draft._on_weight_changed(pack, weight, hard, False)

        def save(close=True):
            commit()
            self.client.request("theme.save", {"number": number, "values": draft.config_data}, lambda result: editor.close() if close else None)

        def render():
            for view in list(editor.document.subviews()):
                view.removeFromSuperview()
            targets.clear()
            inputs.clear()
            if threshold is not None:
                threshold.setObjectValue_(draft.config_data.get("preferred_thresholds", 0))
            mapping = THEME_PACK_NAME_MAP | THEME_PACK_HARD_NAME_MAP if mode[0] else THEME_PACK_NAME_MAP
            images = THEME_PACK_IMAGE_MAP | THEME_PACK_HARD_IMAGE_MAP if mode[0] else THEME_PACK_IMAGE_MAP
            policy_key = ("hard" if mode[0] else "normal") + "_" + str(floor[0])
            banned = draft.config_data.setdefault("forbidden_theme_packs", {}).setdefault(policy_key, [])
            label(editor.document, "主题包", ((76, 8), (430, 22)), size=12, bold=True)
            for title, x, width in [("权重", 526, 76), ("本层禁选", 630, 132)]:
                heading = label(editor.document, title, ((x, 8), (width, 22)), size=12, bold=True)
                heading.setAutoresizingMask_(A.NSViewMinXMargin)
            y = 36
            weights = dict(draft.config_data.get("theme_pack_list", {}))
            if mode[0]:
                weights.update(draft.config_data.get("theme_pack_list_hard", {}))
            for pack, weight in weights.items():
                hard = mode[0] and pack in draft.config_data.get("theme_pack_list_hard", {})
                if pack in EN_OCR_ALTERNATIVES:
                    continue
                image = A.NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/app/theme_packs/" + images.get(pack, "Unknown.png"))))
                if image:
                    view = A.NSImageView.alloc().initWithFrame_(((20, y + 4), (40, 56)))
                    view.setImage_(image)
                    view.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
                    editor.document.addSubview_(view)
                label(editor.document, "theme-name:" + pack, ((76, y + 20), (430, 24)))
                from frontend_appkit.widgets import textfield

                def change(sender, pack=pack, hard=hard):
                    try:
                        weight = int(sender.stringValue())
                        if not -10 <= weight <= 10:
                            raise ValueError("权重范围为 -10…10")
                        config_key = "theme_pack_list_hard" if hard else "theme_pack_list"
                        if weight != draft.config_data.get(config_key, {}).get(pack):
                            draft._on_weight_changed(pack, weight, hard, False)
                    except ValueError as exc:
                        self.error(str(exc))

                control = textfield(editor.document, weight, ((526, y + 16), (76, 28)), change, targets, numeric=True)
                control.setAutoresizingMask_(A.NSViewMinXMargin)
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

                ban_control = button(editor.document, "", ((678, y + 16), (28, 28)), ban, targets, checkbox=True, checked=pack in banned or mapping.get(pack) in banned)
                from frontend_appkit.widgets import accessibility_label

                accessibility_label(ban_control, "theme-name:" + pack + " · 本层禁选")
                ban_control.setToolTip_(self.text("本层禁选"))
                ban_control.setAutoresizingMask_(A.NSViewMinXMargin)
                line = A.NSBox.alloc().initWithFrame_(((20, y + 64), (742, 1)))
                line.setBoxType_(A.NSBoxSeparator)
                line.setAutoresizingMask_(A.NSViewWidthSizable)
                editor.document.addSubview_(line)
                y += 68
            editor.document.setFrameSize_((editor.document.frame().size.width, y + 20))

        def choose_mode(sender):
            try:
                commit()
            except (ValueError, TypeError):
                sender.selectItemAtIndex_(int(mode[0]))
                raise
            mode[0] = sender.indexOfSelectedItem() == 1
            render()

        def choose_floor(sender):
            try:
                commit()
            except (ValueError, TypeError):
                sender.selectItemAtIndex_(floor[0] - 1)
                raise
            floor[0] = sender.indexOfSelectedItem() + 1
            render()

        popup(editor.root, [["普通", False], ["困难", True]], False, ((20, 14), (100, 30)), choose_mode, editor.targets)
        popup(editor.root, [[f"第{i}层", i] for i in range(1, 6)], 1, ((132, 14), (100, 30)), choose_floor, editor.targets)
        save_button = button(editor.root, "保存并关闭", ((642, 14), (138, 30)), lambda sender: save(), editor.targets)
        save_button.setAutoresizingMask_(A.NSViewMinXMargin)
        entries = [
            ("全部设为 -5", lambda: (commit(), self.theme_negative(draft, render))),
            ("重置默认", lambda: (commit(), self.client.request("theme.defaults", callback=lambda data: self.replace_theme(draft, data, render)))),
        ]
        if number is not None:
            entries.append(("拉取全局", lambda: (commit(), self.client.request("theme.get", callback=lambda data: self.replace_theme(draft, data, render)))))
            for i, title in enumerate(["导出 YAML", "导入 YAML", "复制配置码", "粘贴配置码"]):
                entries.append((title, lambda i=i: self.theme_transfer(number, i, draft, render, commit, editor)))
        menu_button(editor.root, "更多", ((244, 14), (100, 30)), entries, editor.targets)
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

    def theme_transfer(self, number, index, draft, render, commit, editor):
        generation = getattr(self, "team_generation", 0)

        def current():
            return not editor.closed and generation == getattr(self, "team_generation", 0)

        if not current():
            return
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
        params["values"] = copy.deepcopy(draft.config_data)

        def transfer_done(result):
            if not current():
                return
            if index == 2:
                board = A.NSPasteboard.generalPasteboard()
                board.clearContents()
                board.setString_forType_(result or "", A.NSPasteboardTypeString)
            elif index in {1, 3}:
                self.replace_theme(draft, result, render)

        if current():
            self.client.request("theme.transfer", {"number": number, "action": action_, **params}, transfer_done)

    def show_capture(self, data):
        editor = self.open_tool("capture")
        image = A.NSImage.alloc().initWithContentsOfFile_(data["path"])
        editor.image_view.setImage_(image)
        editor.placeholder.setHidden_(image is not None)
        editor.bundle_label.setStringValue_(data.get("bundle_id", data["path"]))

    def check_native_pages(self, theme):
        # Opt-in UI QA builds every active page/editor without game commands.
        frame = self.window.contentView().superview()
        frame.layoutSubtreeIfNeeded()
        self.window.displayIfNeeded()
        controls = [self.navigation, self.pause_button, self.start_button]
        for control in controls:
            bounds = control.bounds()
            if bounds.size.width < 40 or bounds.size.height < 24:
                raise RuntimeError("Toolbar control collapsed: " + str(control.identifier()))
            xs = [bounds.size.width * (index + 0.5) / control.segmentCount() for index in range(control.segmentCount())] if control is self.navigation else [bounds.size.width / 2]
            for x in xs:
                point = control.convertPoint_toView_((x, bounds.size.height / 2), frame)
                if frame.hitTest_(point) != control:
                    raise RuntimeError("Toolbar control is not reachable: " + str(control.identifier()))
        for index in range(len(PAGE_KEYS)):
            self.page_index = index
            sections = range(5) if index == 6 else [0, 3] if index == 3 else [0, 1] if index in {0, 2} else [0]
            for section in sections:
                if index == 6:
                    self.settings_section = section
                    if section == 1:
                        self.expanded_schedules.update({"", "2", "3", "4"})
                elif index == 3:
                    self.mirror_section = section
                elif index in {0, 2}:
                    self.task_details[index] = section
                    if index == 0 and section == 1:
                        self.expanded_daily.update({"EXP", "thread"})
                for detail in [False, True] if index == 6 and section in {0, 2, 3} else [False]:
                    if index == 6:
                        self.settings_details[section] = detail
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
        for kind in ("battle", "capture"):
            self.open_tool(kind).close()
        self.show_announcements({"Time": "", "Announcement": [{"title": "公告", "content": "- Markdown\n- **AppKit**", "contentType": "markdown"}]})
        self.editors[-1].close()
        self.page_index = 7
        self.sync_navigation()
        self.build_page()
        self.toggle_logs()
        self.resize_logs(getattr(self, "log_height", 210) + 40)
        self.toggle_logs()
        self.ui_checked = True
        sys.stderr.write("NATIVE_UI_CHECK_PASSED\n")

    def show_text(self, title, text, html=False, *, source_url=None):
        editor = Editor(self, title)
        if source_url:
            editor.window.setMinSize_((520, 280))
            editor.window.setContentSize_((560, 280))
            editor.scroller.setFrame_(((0, 60), (560, 220)))
        view = A.NSTextView.alloc().initWithFrame_(((0, 0), (540 if source_url else 760, 220 if source_url else 1000)))
        view.setEditable_(False)
        view.setDrawsBackground_(False)
        view.setTextContainerInset_((20, 16))
        view.setAutoresizingMask_(A.NSViewWidthSizable)
        view.setHorizontallyResizable_(False)
        view.textContainer().setWidthTracksTextView_(True)
        if html:
            view.textStorage().setAttributedString_(attributed_html(text))
        else:
            view.setString_(str(text))
        view.setFont_(A.NSFont.systemFontOfSize_(13))
        view.setTextColor_(A.NSColor.labelColor())
        editor.scroller.setDocumentView_(view)
        button(editor.root, "查看发布页面", ((20, 14), (180, 30)), lambda sender: self.open_url(source_url or "https://github.com/KIYI671/AhabAssistantLimbusCompany/releases"), editor.targets)
        editor.show()

    def show_announcements(self, data):
        editor = Editor(self, self.text("公告"))
        editor.window.setMinSize_((520, 340))
        editor.window.setContentSize_((700, 560))
        label(editor.root, "公告", ((20, 12), (480, 26)), size=17, bold=True)
        stamp = subtitle(editor.root, self.text("更新时间") + " · " + str(data.get("Time", "")), ((20, 42), (560, 18)))
        stamp.setIdentifier_(None)
        close = button(editor.root, "关闭公告", ((596, 18), (84, 28)), lambda sender: editor.close(), editor.targets)
        close.setAutoresizingMask_(A.NSViewMinXMargin)
        editor.scroller.setFrame_(((0, 72), (700, 488)))
        view = A.NSTextView.alloc().initWithFrame_(((0, 0), (680, 488)))
        view.setEditable_(False)
        view.setSelectable_(True)
        view.setDrawsBackground_(False)
        view.setTextContainerInset_((24, 20))
        view.setAutoresizingMask_(A.NSViewWidthSizable)
        view.setVerticallyResizable_(True)
        view.setHorizontallyResizable_(False)
        view.textContainer().setWidthTracksTextView_(True)
        view.textStorage().setAttributedString_(attributed_html(announcement_html(data)))
        view.setTextColor_(A.NSColor.labelColor())
        editor.scroller.setDocumentView_(view)
        view.sizeToFit()
        editor.show()

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
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 62333))
            listener.listen(5)
        except OSError:
            if listener:
                listener.close()
            with socket.create_connection(("127.0.0.1", 62333), timeout=2) as connection:
                connection.sendall(("|".join(arguments).encode() or b"|") + b"\n")
            return 0
    app = Application(arguments, listener)
    AppHelper.runEventLoop()
    return app.exit_code
