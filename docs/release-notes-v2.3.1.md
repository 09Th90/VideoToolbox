# 视频工具箱 v2.3.1

> v2.x 系列的第一个正式 Release。此前所有 v2.x 构建只存在于 `repo-latest`
> 这个预发布 tag 里，Releases 页面最高只到 v1.12.0 —— README 指向的产物因此
> 长期落空。本次把这一环补上：tag、Release、附件三者对齐。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `视频工具箱_在线安装_v2.3.1.exe` | 12.5 MB | 当前唯一发布形态。安装时从本仓库 Releases 拉取约 127 MB 组件 |

SHA-256 校验：

```
51985fa81c38ede85196b029d0858838ffc5040f8540431f8f758dbf6ab03be1  视频工具箱_在线安装_v2.3.1.exe
```

**本版没有离线安装包。** onefile 单体打包后超过 1 GB，已超出可维护的分发体积；
完全断网的环境请按 README 的「源码方式」运行。

## 本版包含

- **PySide6 迁移完成**（v2.1.0 起）：界面框架由 PyQt5 换成 PySide6，
  PyQt-Fluent-Widgets 1.8.4 随之停用，改用 PySide6-Fluent-Widgets 1.11.3
- **自研主题引擎 `vt_fluent` 落地**：QSS 主题引擎、图标引擎、合并 QSS（B0），
  纯控件族迁移并四门 parity 校验通过（B1）
- **核心引擎拆分**：`src/video_toolbox.py` 由 5475 行降至 1337 行，
  ASR / 下载 / 共享底座三个域模块迁入 `src/core/`，单体退化为 facade
- 下载依赖链路修复；harness 配套解耦
- 术语底表 3174 条（鸣潮 1650 · 终末地 1002 · 明日方舟 453 · 战双帕弥什 69）

## 许可

- 本软件源码单独分发：CC BY-SA 4.0
- 随安装包分发的组合作品（含 GPL-3.0 组件）：整体按 GPL-3.0 提供
- 详见仓库 `LICENSE` 与 `docs/第三方组件来源与许可声明.txt`

## 已知限制

- 未做代码签名，少数开启应用控制策略的电脑会拦截 exe
- 不提供离线安装包
- 无自动化测试，仅 `scripts/dev/` 下的人工自检脚本

## 安装

1. 双击运行安装器，向导全程简体中文（不会弹语言选择框）
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC
3. 装完从开始菜单或桌面快捷方式启动

---

**发布命令**（维护者用，需先推送 tag）：

```bash
gh release create v2.3.1 \
  "installer_online/视频工具箱_在线安装_v2.3.1.exe" \
  --title "视频工具箱 v2.3.1" \
  --notes-file docs/release-notes-v2.3.1.md \
  --latest
```
