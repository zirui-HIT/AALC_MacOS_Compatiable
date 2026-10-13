# AALC for macOS

基于 [KIYI671/AhabAssistantLimbusCompany](https://github.com/KIYI671/AhabAssistantLimbusCompany) 的 macOS / PlayCover 适配，使用原生 AppKit 界面和独立 Python 后端进程。

支持日常经验本/纽本、领奖、狂气换体、镜牢、队伍与主题包设置、四组定时任务、自动战斗和截图工具。自动战斗提供无限守备、首回合守备、不处理事件三个原有选项，可通过主窗口或全局热键停止。

## 运行

```sh
uv sync --frozen --group dev
uv run main.py
```

在 PlayCover 中开启 Limbus Company 的 MaaTools，然后在 AALC 设置中选择已安装的游戏、确认端口和应用标识，并测试连接与截图。

配置、日志、图片资源和截图继续使用现有 `.runtime/`。安装包记录本仓库的数据位置，更新 `/Applications/AALC.app` 不会重新创建用户配置。

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
