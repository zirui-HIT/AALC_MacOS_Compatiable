# macOS / PlayCover 使用说明

面向 Apple Silicon、原生 arm64 Python 3.13.6、英文 Limbus Company 和
`hguandl/PlayCover` MaaTools 分支。保留 PySide6、OpenCV、RapidOCR 和 ONNX Runtime。
当前实现和验收进度见 [迁移记录](macos-migration-status.md)。
日文字库汉化的独立图像配置见 [iOS 中文适配](ios-zh-cn.md)，其中说明已验证范围与待验收场景。

## 在本工作目录运行

用户要求所有写入留在当前目录，故本次采用便携路径，**不写入**用户的
Library/Application Support、Logs 或 Caches。源码和本仓库 `dist/` 构建共享
`.runtime/`：配置在 `config/`，日志在 `logs/`，缓存和下载在 `cache/`，用户模板在
`templates/`，更新后的通用资源在 `resources/images/`。只读资源从源码或应用包内读取。
移到其他目录的便携 `.app` 将使用其旁边的 `.runtime/`；本次只在当前目录测试。

以下命令均在仓库根目录执行。已有工具位于 `.runtime/tooling/bin/uv`：

```sh
export UV_CACHE_DIR="$PWD/.runtime/cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.runtime/python"
export TMPDIR="$PWD/.runtime/tmp"
mkdir -p "$TMPDIR"
.runtime/tooling/bin/uv sync --frozen --group dev
.venv/bin/python main.py
```

`main.py` 不依赖工作目录；也可以从父目录用 `.venv/bin/python` 和 `main.py` 的绝对路径启动。
首次启动无需启动游戏。macOS 不需要 UAC 或管理员启动。

### 界面字体与缩放

Mac 默认 UI 缩放为 125%，旧的 50% / 75% / 90% 和“跟随系统”设置会在启动时迁移到 125%。
Retina 像素密度由 Qt 自动处理；窗口不足以容纳内容时不再自动保存 50% 的缩放配置。
导航与日志使用 16px 字体，日志增大行距和对比度；任务区压缩空白，窗口支持拖动边缘调整大小与最大化。
可在“设置 → 个性化 → 缩放”中选择 100%–200%，重启后生效；游戏识别的 1920×1080 分辨率独立管理。

## 游戏与连接设置

1. 使用指定 PlayCover 构建及配套 PlayTools，安装 IPA 的步骤不在本项目范围。
2. 在 **Limbus 自己的** PlayCover 设置中开启 MaaTools，设置独占端口并重启游戏。
   本机实测端口为 **1718**；1717 当前属于明日方舟，身份检查会拒绝控制它。
3. 游戏使用英文、横屏 16:9，先保持窗口可见且未最小化，手动进入主页。
4. AALC 设置页选择 PlayCover 后端、实际游戏 `.app`、端口、BGR 截图方式，使用
   连接测试和截图预览。选择应用时读取 Info.plist，连接后以 BNDL 再次核验身份。

本机确认的 Bundle ID 为 `com.ProjectMoon.LimbusCompany`，游戏版本为 `1.116.2`。
应用路径为 PlayCover 容器 Applications 目录下相应 `.app`，不要选择 PlayCover 自身。
应用路径为空时，自动启动会从 macOS 已注册应用中解析配置的 Bundle ID，读取 Info.plist 复核后启动；无法解析时需要选择实际 `.app`。
保持 `simulator: false`；PlayCover 不是 Android 模拟器。
配置字段为 `backend`、`game_profile`、`playcover_host`、`playcover_port`、
`playcover_app_path`、`playcover_bundle_id`、`playcover_capture_method`、逻辑宽高。
逻辑分辨率固定 1920×1080，对应模板高度 1080。

客户端仅接受回环地址。MaaTools v4 无认证；服务器本身可能监听外部接口，
应在宿主防火墙/网络环境限制该端口的外部访问。本工具不会修改 PlayCover 配置或防火墙。

## 诊断与截图

```sh
.venv/bin/python -m tools.playcover_probe \
  --port 1718 --expect-bundle-id com.ProjectMoon.LimbusCompany \
  --samples 100 --output artifacts/limbus-playcover-probe
```

默认只读，生成诊断 JSON 和最后一张截图，输出平均及 p95 耗时。
截图可能包含账号资料，请只在本地保存，分享前脱敏；仓库忽略 `artifacts/`。
只有显式 `--tap-native X Y` 或 `--drag-native X1 Y1 X2 Y2` 才发出触控，
这两个参数使用 SIZE 的原生触控像素坐标，并要求提供预期 Bundle ID。
诊断触控应选无资源消耗的页面；不要试点购买、兑换、Skip Battle 或战斗确认。

支持协议 v4：MAA/OKAY 握手、VERN/BNDL/SIZE、普通 BGR、显式 SCRN、TUCH、TERM。
不发送 MTL。普通 BGR 解码为 RGB，再按需转灰度；不将原始字节当成 PNG。
实测 SIZE 5120×2880、BGR 3942×2216；二者无需相同。由帧几何统一换算输入，
不采用桌面位置或固定 Retina 除二。窗口尺寸取整产生的小于 4 像素误差使用等比缩放
及亚像素填充；明显非 16:9 会报错，不强制拉伸。

页面切换的完整空 BGR 响应有最多 5 秒的只读重试；超时、半包和畸形报文会断开。
重连只恢复握手和只读查询，不重放点击或 TERM。丢失触点只向同一已核对进程补发抬起。
连接正常不代表已经进入主页。标题页按真实 Touch to Start 模板点击，等待闪烁文字的可识别帧；
本机重启后仍需手动 Google / Apple 登录，任务会明确提示登录后再继续。
2026-10-11 实测发现点击后进入主页的过渡帧会使标题页辅助函数误报超时。
PlayCover 分支现于新帧不再包含标题页标志时返回原重试流程，保留标题页闪烁等待及点击阈值。
中文配置显式复用现有 iOS Google 登录标志，避免初始化时反复报缺少模板；
回放验证登录页可识别且不会误匹配标题页，日文登录控件仍未单独采样。

## 功能与权限

当前任务实现以原始 AALC `b0f439321987f5f7b126ebbc424f6ef144c1bff0` 为基线。
日常、采光、兑换、领奖、战斗、镜牢准备、观测、寻路、主题包、商店、失败恢复和重开
均使用原来的任务代码。次数、顺序、策略、重试和领取条件由原配置及原流程决定。
不再提供独立的 PlayCover 任务循环或诊断执行器，也不额外限制主题包刷新、重开、商店或领奖。

2026-10-11 用户另行授权扩展 YAML 并以最小代码改动实现速刷选包。
新增复刻/号线关键词匹配，以及刷新入口不可用时按可见最高权重兜底；
随后按用户表格增加按层硬禁选：禁选独立于权重，全禁选且刷新耗尽时停止任务并保留选包页面。
本机已启用的配置和验证范围见 [镜牢速刷主题包策略](theme-pack-speedrun.md)。

保留的适配只有 macOS 启动/停止/防休眠/通知、MaaTools 截图与触控、坐标转换、
资源路径和英文 iOS 图片。PC 的 P、Enter、Esc 通过识别对应按钮执行触控；
执行时机与失败后的后续处理仍由原任务控制。iOS 页面相对坐标记录在 `assets/ios_en/layout.json`，采用原模板的 1440 高度基准；普通截图仍遵循保存的截图间隔。原地图滚轮缩放在触控后端使用已验证的双指手势。
MaaTools v4 不支持文本输入，因此队伍码仍需在入口说明能力限制。
键盘寻路选项、配置字段及按键分支已按用户要求删除，继续使用原有触控寻路。

普通模组合成、狂气换体、连续战斗和观测均恢复原始函数。
狂气目标仍是今日累计次数：价格 26/52/78 对应原流程第 1/2/3 次；
回归测试覆盖已用次数达到目标时不再购买，以及重复运行同一目标不额外购买。
跳过普通合成的设置在“狂气换体”齿轮的高级设置中；兑换任务仍按原流程调用合成。

**当前实机状态：2026-10-11 已按保存配置完成一次原始任务全流程验收。**
使用源码原来的 `my_script_task`，通过只读观察器记录截图和日志；未替换执行策略、修改任务设置或绕过原任务。
经验本 1 次、纽本 1 次、日/周任务与邮件领奖、狂气兑换至今日 2 次、普通镜牢 1 次（完整 5 层）均完成。
最终领取 30 通行证经验，狂气减少 78；5 次连续防御计数按原流程跨战斗消耗，未重复开始。
约 37 分 40 秒后工作线程无异常退出，游戏进程已退出且无遗留观察或 caffeinate 进程；
配置只更新原流程产生的镜牢次数（16→17）和耗时统计，自动保存成功。
本次运行的是源码工作线程；原生 GUI 的自动退出与打包应用检查见已有离线/隔离验收记录。
详细结果见 [原始流程核对记录](original-flow-audit.md)。
后续识别失败只校准模板、截图、输入与坐标，不另写执行策略或任务状态机。
其他主题、困难镜牢、失焦/遮挡/桌面切换/最小化/锁屏仍需实测。

截图使用游戏内 MaaTools 的普通截图通道；若系统要求屏幕录制权限，应按实际提示授权
PlayCover/游戏相关进程。AALC 的 GUI 停止按钮始终可用；全局热键仅在检测到输入监控
权限时启动，不会代替用户开启系统授权。任务期间使用 caffeinate，结束/取消/异常时清理。
macOS 结束后操作目前只开放退出游戏/AALC，其余电源动作待验证。

## 每日定时与常驻

macOS 设置页已开放原有“定时执行”卡片。每日任务通过 `launchd` 的
`StartCalendarInterval` 触发原来的 `start --exit autodaily` 等命令；常驻主实例
通过原有本机 socket 接收参数，任务排队、游戏启动、兑换和结束后动作均沿用原流程。
定时进程使用系统自带 `sh`/`nc` 发送现有 socket 协议，源码和打包主实例均可接收；
不再从 `launchd` 直接执行下载目录中的 Python/应用，以避免等待 macOS 文件访问权限。

任务 plist 和标准输出日志保存在仓库 `.runtime/schedules/`，通过 `launchctl`
加载到当前用户 GUI 会话，不写入系统 LaunchAgents 目录。启用项在 AALC 下次启动时
恢复注册，因此重新登录后需要先启动 AALC。界面关闭定时开关会卸载对应任务。

本机 2026-10-12 配置为：08:00 日常（经验本 1 次、纽本 3 次）、邮件及日/周常领奖、
狂气兑换至当天 2 次；20:00 仅启用狂气兑换任务。兑换函数包含普通模组合成，
若早晨未达到当天目标，晚上按原流程补足。两项均仅退出游戏，不退出 AALC。
槽位保存四类任务的开关，次数、队伍和策略继续共用主配置；早晨槽位不启用镜牢。

本机正常启动打包 AALC 主进程；常驻防休眠项
`.runtime/schedules/io.aalc.PlayCover.resident.plist` 使用 `caffeinate -i -w <AALC PID>`
跟随该进程，阻止空闲系统睡眠，允许显示器息屏。主进程启动不携带 `start` 参数，
不会立即执行游戏任务。主动睡眠、关机及退出登录仍会中断常驻；
`launchd` 的日历任务在睡眠期间错过时会于唤醒后触发。

2026-10-11 选择性整合上游 PR：

- [#942](https://github.com/KIYI671/AhabAssistantLimbusCompany/pull/942)：未截图、空图或异常维度直接返回未识别结果。
- [#847](https://github.com/KIYI671/AhabAssistantLimbusCompany/pull/847)：同一张截图共享 NumPy 视图及模板匹配结果，最多缓存 128 项。
  新图、触控（包括失败）、资源刷新使缓存失效；识别参数、分辨率、图像配置及主题/语言路径分别作为缓存条件。
  未确定主题/语言时继续运行原路径推断；保留已有 OCR 缓存，不调整截图间隔、点击间隔、任务轮询或 ORB 裁剪/缩放顺序。
- [#921](https://github.com/KIYI671/AhabAssistantLimbusCompany/pull/921)：组件注册到同一个全局热键监听器，编辑快捷键只暂停派发，关闭/销毁时注销。
  自动战斗工具的回调通过 Qt 信号回到 GUI 线程；macOS 输入监控权限检查保留。热键只控制 AALC，不向触屏版游戏发送键盘输入。

同时删除被统一输入包装覆盖的重复绑定、旧监听器及未执行的旧 UI 片段，将任务界面的星号导入改为实际使用的名称。

## 测试与本地构建

macOS 应用图标和菜单栏图标来自仓库根目录的 `icon.png`，随包提供 PNG 与多尺寸 ICNS。
点击主窗口关闭按钮会隐藏窗口并移除 Dock 图标，仅保留右上角菜单栏入口；后台任务继续运行。
菜单栏“打开主窗口”恢复窗口及 Dock 图标，“退出 AALC”、⌘Q 和 Dock 退出沿用原有确认与清理。
任务完成后的“退出 AALC”仍按原有完成流程退出。“最小化到托盘”开启时也使用菜单栏常驻模式。
原生验证：`AALC_NATIVE_UI_TEST=1 .venv/bin/python -m pytest tests/test_macos_tray.py -q`，
需要 WindowServer 访问；普通回归使用 offscreen 与隔离配置，不连接游戏。

```sh
.venv/bin/python -m pytest tests/playcover -q --basetemp .runtime/tmp/pytest-playcover
.venv/bin/python -m pytest -q --basetemp .runtime/tmp/pytest-all
QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --smoke-test
.venv/bin/python main.py --ocr-smoke-test
export PYINSTALLER_CONFIG_DIR="$PWD/.runtime/cache/pyinstaller"
.venv/bin/pyinstaller main_macos.spec --clean --noconfirm
dist/AALC.app/Contents/MacOS/AALC --smoke-test
dist/AALC.app/Contents/MacOS/AALC --ocr-smoke-test
```

默认测试使用合成图像/本地假服务，不连接游戏。脱敏实机截图回放在
`tests/fixtures/playcover/`，记录版本、语言、原始/逻辑/触控尺寸与脱敏范围。
CI 增加纯协议和 macOS arm64 测试/构建，保留现有 Windows 工作流；本机不冒称已跑 Windows。

目录式 `dist/AALC.app` 包含 Qt 插件、OCR 模型、YAML、字体和图片资源。
这是本地 ad-hoc 签名构建，尚无 Developer ID 签名或公证。发布者需要自己的凭据执行
`codesign --force --deep --options runtime --sign '<Developer ID Application identity>' dist/AALC.app`，
再按 Apple notarization 流程提交和装订；须重新验证嵌套二进制签名与启动。
Mac 软件更新仅提示，禁止下载安装上游 Windows `.7z`/`.exe`。
图片更新来源是 [AALCImageResources](https://github.com/KIYI671/AALCImageResources) 的
`main/manifest.json` 和清单中的 `packages/images.7z`，另有 Gitee 镜像。
macOS 图片同步独立于软件版本门禁，不要求安装上游 Windows 包；更新写入 `.runtime/resources/images/`。
查找顺序为本地 iOS 覆盖→英文→通用；英文/通用路径优先使用更新副本，缺失时回退随包图片。
`assets/ios_en/` 和用户 iOS 模板保持独立。
2026-10-09 核对远端清单 491 张，与本地通用图片逐张哈希全部一致；真实资源包在 macOS 原生解压并校验通过。

## 协议源码依据

实现核对 PlayTools `0c09900de12106091ead308642a8b2d1434982ef` 的
[MaaTools.swift](https://github.com/hguandl/PlayTools/blob/0c09900de12106091ead308642a8b2d1434982ef/PlayTools/Utils/MaaTools.swift)、
[普通截图](https://github.com/hguandl/PlayTools/blob/0c09900de12106091ead308642a8b2d1434982ef/AKPlugin.swift)、
[Metal 限制](https://github.com/hguandl/PlayTools/blob/0c09900de12106091ead308642a8b2d1434982ef/PlayTools/Captures/ArknightsMetalCapture.swift)。
换装 PlayCover/PlayTools 后重新运行 VERN/BNDL 和截图诊断，不能根据窗口标题推测兼容。

## 白棉花设置变更（2026-10-10）

白棉花专用名称识别与跳过/保护判断已移除，按现有通用饰品规则处理。
镜牢高级设置不再显示“不跳过白棉花”；旧配置中的该字段由现有加载器忽略。
更新源码或本地 `.app` 后重新打开 AALC，界面与执行行为一并生效。

## 镜牢追加回归（2026-10-11 23:07）

使用原 `my_script_task` 完成五层镜牢并领取 30 通行证经验，返回主页后按原收尾配置退出游戏。
保存的队伍设置为第 4 层切换困难，因此本轮为 1–3 层普通、4–5 层困难；普通奖励资格不变。
单次镜牢任务耗时 29 分 04 秒，工作线程无异常退出。记录在忽略的
`artifacts/mirror-pr-live-20261011/run2/`，包含日志、画面、设置快照和性能记录。

先复现并修复 iOS 标题页过渡后仍等待 Touch to Start 的误报；本轮原恢复流程重启时，
新标题页分支自动点击继续并回到主页，无需人工点击。第 4 层事件“继续”文字未匹配，
触发了一次原重启恢复；随后补充实机按钮模板并通过原事件循环回放。此次验收包含恢复，
新增事件模板未在同一轮再次遇到该事件时实测，不能标为全程无干预首次运行。
领奖首次 OCR 命中过渡画面，原流程再次进入领奖页后识别出 30 并正常领取，结算逻辑未修改。
商店子页面 `return_assets.png` 在上游中文资源中仍缺失，本轮未进入该子页面，离店正常。

布局 JSON 改为复用现有进程缓存，避免每次图片锚点查询都读取文件。
1000 次查询的中位耗时由 36.71 ms 降至 12.41 ms，仅代表该查询的约 2.96 倍提升，
不能据此声称整轮镜牢提速相同比例。同时删除截图校验的重复分支和未执行的旧 stop 字符串。
全量回归为 627 passed、1 个可选原生 OCR 回放 skipped、7 subtests passed；
原生中文 OCR 回放已另行通过。最终应用包重新构建，启动/OCR 自检通过，事件图片与源码一致。
用户设置仅同步原任务生成的队伍 1 次数 18→19 和普通镜牢耗时历史，其余设置保持验收前内容。

## 再次镜牢与游戏重启验收（2026-10-12）

本轮原 `my_script_task` 于 10 月 11 日 23:26:58 开始镜牢，10 月 12 日 00:05:39 完成。
完整五层、完成度 100%，领取 30 通行证经验，返回主页后按原配置退出游戏。
镜牢任务耗时 38 分 41 秒，工作线程耗时 39 分 06 秒，无异常和遗留游戏/观察/caffeinate 进程。
保存设置仍为 1–3 层普通、4–5 层困难。各层日志计时为 7:18、8:17、4:48、7:39、9:27；
第 2 层包含用户要求的重启验证，因此本轮不能称作全程无干预运行，也不能与上轮直接比较速度。
证据保存在忽略的 `artifacts/mirror-pr-live-20261011/run4/`。

按用户要求回滚 `ae510cc` 的截图复制优化，提交为 `7eead07`，恢复上次完成整轮验收的截图实现。
上次启动空图发生在该优化之前，且本次回滚前再次查询已经恢复有效图，不能将恢复归因于回滚。
游戏的 PlayTools 日志记录了 ScreenCaptureKit 内部错误 `-3811`；具体触发原因仍未确认，
不能据此要求窗口保持前台。未新增焦点依赖、截图替代通道或修改原任务控制逻辑。

第 2 层临时暂停同一个 AALC 进程，使用现有 MaaTools TERM 正常退出游戏，然后由已有启动接口重新启动。
本次启动检查取得有效截图；恢复原工作线程后，原重试流程自动点击 TOUCH TO START，进入主页并接续镜牢。
无需手动点击或重新登录，5 次连续防御计数没有重置或重复消耗。此次冷启动未复现空图；
首次启动失败记录保留在 `run3/`，重启操作、启动/主页画面和进程信息在 `run4/requested-restart.json`。

第 3 层事件结果“继续”按钮以 0.93 相似度匹配新增 iOS 模板，原事件循环成功继续，补齐上轮缺少的实机验证。
领奖首次 OCR 未识别数量，原流程再次进入领奖页后成功识别并领取 30，未更改结算时序。
商店子页面的上游中文 `return_assets.png` 仍缺失，本轮未进入该子页面，五次离店均正常。
没有发现需要新增适配或删除原功能代码的问题。回滚后截图/坐标测试 9 项、原任务流程核对 44 项均通过；
应用包已按回滚后的源码重建，启动/OCR 自检通过。
仅将原任务产生的队伍 1 次数 19→20 和普通镜牢耗时历史同步回用户配置，其余偏好与运行前完全一致。
