# AALC for macOS

基于 [KIYI671/AhabAssistantLimbusCompany](https://github.com/KIYI671/AhabAssistantLimbusCompany) 的 macOS / PlayCover 适配，使用原生 AppKit 界面和独立 Python 后端进程。

支持日常经验本/纽本、领奖、狂气换体、镜牢、队伍与主题包设置、四组定时任务、自动战斗和截图工具。自动战斗提供无限守备、首回合守备、不处理事件三个原有选项，可通过主窗口或全局热键停止。

## 运行

```sh
uv sync --frozen --group dev
uv run main.py
```

在 PlayCover 中开启 Limbus Company 的 MaaTools，然后在 AALC 设置中选择已安装的游戏、确认端口和应用标识，并测试连接与截图。

配置、统计、自定义模板和持久图片资源保存在 `~/Library/Application Support/io.aalc.PlayCover/`，日志在 `~/Library/Logs/io.aalc.PlayCover/`，缓存在 `~/Library/Caches/io.aalc.PlayCover/`，截图在 `~/Pictures/AALC/`，临时文件使用系统临时目录。目录由 macOS API 获取，安装包不记录构建机器的数据路径；更新或移动 `.app` 不影响用户数据。迁移到另一台 Mac 时可复制 Application Support 中的应用目录，失效的游戏路径会按 Bundle ID 在本机重新定位，无法定位时需重新选择游戏。

从旧版升级时，将 `.runtime/` 中的 `config/`、`templates/`、`resources/` 和 `models/` 迁入上述 Application Support 目录；`templates/screenshot_*.png` 可移入图片目录。已有目标文件应保留，缓存、临时文件和旧定时任务注册无需复制。

关闭主窗口会隐藏到菜单栏；菜单或 ⌘Q 才退出。任务运行时退出会先确认，并等待触控与后台线程清理。

## 构建与验证

```sh
uv run python scripts/build.py
AALC_DATA_ROOT="$PWD/.runtime/smoke" uv run main.py --smoke-test --ui-check
AALC_DATA_ROOT="$PWD/.runtime/test-data" uv run pytest -q
```

`uv run python scripts/build.py --install` 会备份原应用并更新 `/Applications/AALC.app`。本地包采用 ad-hoc 签名。

任务、识别、重试、配队、镜牢、领奖和 PlayCover 执行代码保持本次迁移前的函数体。测试同时保留上游流程基线及当前执行代码冻结检查。前后端职责、删除范围和验证限制见 [原生迁移说明](docs/native-appkit.md)。

## 来源与许可

保留上游 AGPL-3.0-or-later 许可，详见 [LICENSE](LICENSE)。游戏图像与其他第三方素材的原有许可、来源声明仍适用；旧使用文档与素材声明保留在 `assets/doc/`。
