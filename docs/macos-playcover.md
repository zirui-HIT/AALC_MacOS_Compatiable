# macOS / PlayCover 使用说明

面向 Apple Silicon、原生 arm64 Python 3.13.6、英文 Limbus Company 和
`hguandl/PlayCover` MaaTools 分支。保留 PySide6、OpenCV、RapidOCR 和 ONNX Runtime。
当前实现和验收进度见 [迁移记录](macos-migration-status.md)。

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

## 功能与权限

目前实现触控点击、拖动、连线、快速列表滑动、双指地图缩放、截图、身份核验和应用生命周期。
战斗使用识别后的 Win Rate/齿轮按钮，资源消耗的战斗入口只点击一次并等待确认。
失败不会自动重开。日常任务复用原有次数拆分、针对性配队、领取范围与任务顺序。
经验本和纽本支持 1–10 次连续战斗，按设定批次拆分总次数，最后不足一批仍会执行。
纽本通过当天可进入类别的 Consecutive Battle 标签定位，不固定星期、属性或卡片序号。
配队支持“按序号”和原有 TEAMS#N 名称；自定义队伍名建议按序号选择。
日常任务保留游戏预设已保存的部署人数，镜牢按配置的罪人顺序与人数部署。

领取奖励支持邮件和通行证日/周任务，沿用原有领取范围设置。
狂气换体沿用“达到今日累计 N 次”的含义，先转换已有体力，换体后再次转换；
支持跳过模组合成与葛朗台模式设置。勾选“跳过合成脑啡肽”时，日常任务不会自动换饼；
狂气换体仍会转换体力，避免溢出，并按今日累计目标执行剩余次数。
页签等待开窗动画完成及目标数据就绪；数量读取使用独立数字区域，最大数量按当前体力核对。
合成 Confirm 后游戏会保留弹窗，成功以 Owned 模组增加确认，随后按调用方要求关闭或继续换体。
2026-10-10 已实测现有体力合成 3 模组、26 狂气换体 1 次、恢复体力合成 7 模组并返回主页。
模组 194→204、狂气 117516→117490、今日次数 0/10→1/10；次日重置、多次购买与葛朗台实际等待尚待覆盖。
邮件为空和通行证已领取状态已实测；有可领取奖励时的确认及纽本战斗结算仍待实测。

普通“体力换饼”在日常任务开始前、每个经验本/纽本单次或连战批次返回主页后、
每轮镜牢结束返回主页后检查；它没有运行中的定时换饼线程，也不等待体力上限。
未勾选“不自动兑换脑啡肽 (?)”且当前体力至少 20 时，合成 `当前体力 // 20` 个模组，保留余数。
该开关位于“狂气换体”齿轮的高级设置，是否勾选狂气购买任务与普通合成开关独立。
单独运行镜牢时，当前 Mac 流程只在整轮结束后检查普通合成。
工具箱的定时“自动体力换饼”是另一项旧工具，目前在 Mac 上禁用。
狂气次数按游戏今日计数判断：目标 2、已用 2 或更多时不买；已用 1 时只补 1；重复运行不会另买 2 次。

任务开始先初始化图片搜索路径，再初始化游戏和识别网络/登录页面。
若日志提示“未找到图片”而文件确实存在，应检查图片路径初始化，而非降低匹配阈值。

普通镜牢已完成一次五层通关、领取奖励并返回主页，模组 207→202。
新入口读取当前队伍设置，包括预设、体系、自选初始饰品顺序、开局卡 0/基础/+/++、
星光换钱、罪人部署，以及商店禁用项。避开/优先三技能、首回合/全程防御、
跨战斗累计的单通防御复用原有战斗实现，已做配置与模拟流程测试，实机仍需覆盖。
开局卡四档与保存的第 8 张基础卡已完成实机预览，Owned 星光均保持 2822；未确认新镜牢入场。
领奖走正常页面识别、Confirm、Pass Level Up 和返回主页。

观测饰品复用 `Mirror.select_observe_ego_gift()` 和 GUI 的配置解析器，
支持 11 个体系、三级、1–10 行、1–8 列，最多三项；开启后入口同步 Activate Gift Search。
例如 `general_3_4_8` 表示泛用、三级、第 4 行、第 8 列，配置从队伍设置读取，不硬编码目标。
已覆盖各体系/等级/位置的模拟页面流程，以及入口开关测试；**没有真实 iOS 观测页截图，实际选择待实测**。
整轮镜牢实机验证含前期分步校准，新配置入口与观测尚未重复验证全新 GUI 入场到领奖。
双指缩放已在真实地图验证两个方向，不能假定反向手势精确恢复原比例。
队伍码文本输入、键盘地图导航在入口明确拒绝。
困难镜牢（包括自动周切换）、普通转困难、三层退出、保存奖励暂未开放。
其他主题、失焦/遮挡/桌面切换/最小化/锁屏尚未验证。
没有默认的系统鼠标模拟，不会通过空实现声称支持文本或缩放。

截图使用游戏内 MaaTools 的普通截图通道；若系统要求屏幕录制权限，应按实际提示授权
PlayCover/游戏相关进程。AALC 的 GUI 停止按钮始终可用；全局热键仅在检测到输入监控
权限时启动，不会代替用户开启系统授权。任务期间使用 caffeinate，结束/取消/异常时清理。
macOS 结束后操作目前只开放退出游戏/AALC，其余电源动作待验证。

## 继续当前镜牢诊断

以下工具默认只读，先在游戏中进入普通镜牢，使用第 1 队；不会从主页开始新一轮。

```sh
.venv/bin/python -m tools.playcover_mirror_resume --output artifacts/mirror-read-only
.venv/bin/python -m tools.playcover_mirror_resume --resume-current \
  --timeout 3600 --output artifacts/mirror-validation
```

显式继续后会持续运行选路/事件/Win Rate 战斗，直至到达奖励页、无法确认页面、报错或超时。
识别失败时保留当前游戏进度，日志、前后截图和结果 JSON 保存到指定目录。
禁止新一轮自动入场、模组奖励、购买、星光升级和主题包刷新；商店只离开。
这是保留的零模组诊断工具；正常 GUI 镜牢任务支持五层完成后的普通领奖。
困难镜牢和其他编队未验收。

## 测试与本地构建

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
