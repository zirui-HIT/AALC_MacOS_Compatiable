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
失败不会自动重开。首次日常验证关闭购买、兑换与附加领取，使用第 1 队。

普通镜牢已完成一次五层通关、领取奖励并返回主页，模组 207→202。GUI 已开放普通镜牢入口：
仅选择第 1 队、游戏预设 #1、流血体系，开启“战斗直至全灭”；关闭开局星光升级、观测/自选初始饰品、困难切换、
三层退出和特殊战斗策略。初始饰品使用 Wound Clerid，商店直接离开。领奖走正常页面识别、
Confirm、Pass Level Up 和返回主页，没有额外的持久化消耗账本或锁。
初始页面由此次真实截图回放验证；整轮实机验证含前期分步校准，尚未重复验证全新 GUI 入场到领奖。
双指缩放已在真实地图验证两个方向，不能假定反向手势精确恢复原比例。
队伍码文本输入、键盘地图导航在入口明确拒绝。
其他主题、纽本、失焦/遮挡/桌面切换/最小化/锁屏尚不能标记为支持。
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
