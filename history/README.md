# 历史文件归档

本目录保存从主程序中移除、但需要留档备查的文件。**所有内容均不参与程序运行与打包**，
仅作历史追溯。归档文件按类别分目录存放，原文件名与版本标记保持不变。

## 目录结构

```
history/
├── source-backups/    旧版本源码快照（被新版本取代的整包/模块代码）
│   ├── backup_v19_vision/        v1.9 视觉/投稿引擎时期的模块源码（7 个文件）
│   ├── backup_v192_pre_calib/    v1.9.2 接入校准前的 GUI 主文件
│   ├── backup_v193_pre_pack/     v1.9.3 打包前的使用说明与安装脚本
│   └── ai_test/                  早期 AI 客户端联调脚本与测试截图
├── devtools/          开发期一次性辅助脚本（截屏、抓界面、编码检查、安装验证等，8 个）
├── release/           发布相关留档
│   ├── legacy-exe/               早期可执行文件备份（v1.2.1 等，仅留档不随包分发）
│   └── installer-checksums/      历史安装包 SHA256 校验值（v1.6 / v1.7 / v1.9.3 / v1.10.1）
├── docs/              旧版开发报告（如 v1.7.1 HTML 报告）
└── tools/             退役的仓库辅助脚本（如早期 Git Data API 推送脚本）
```

## 归档清单（入库部分）

| 类别 | 路径 | 说明 |
| --- | --- | --- |
| 源码快照 | `source-backups/backup_v19_vision/` | v1.9 投稿/视觉引擎 7 模块，约 273 KB |
| 源码快照 | `source-backups/backup_v192_pre_calib/video_toolbox_gui.py` | 校准功能前的 GUI，约 124 KB |
| 源码快照 | `source-backups/backup_v193_pre_pack/` | 旧使用说明 + .iss/.spec，约 17 KB |
| 源码快照 | `source-backups/ai_test/` | AI 联调脚本与截图，2 个文件 |
| 开发脚本 | `devtools/` | 截屏/抓取/编码/安装验证等 8 个脚本，约 20 KB |
| 发布留档 | `release/legacy-exe/` | 旧 exe 备份 ×2，约 22.9 MB |
| 发布留档 | `release/installer-checksums/` | 4 个历史安装包 SHA256 |
| 旧文档 | `docs/开发报告_v1.7.1.html` | v1.7.1 开发报告，约 39 KB |
| 退役脚本 | `tools/push_to_github.py` | 早期推送辅助脚本 |

入库合计 28 个文件、约 23.4 MB（其中两个旧 exe 占 22.9 MB）。

## 仅本机留存、不进 git 的部分

下列历史留档体积大或属运行产物，**只保留在本机磁盘、不纳入 git**（已在 `.gitignore` 忽略，
克隆仓库后不会出现，需要时应从本机备份或 GitHub Releases 取回）：

- `history/build/*.log`、`history/build/*.png`：编译日志与界面截图
- `history/_installer_check/`：安装器验证截图

> 2026-09-17 工作区整理：`_cleanup_20260916\`（废弃 ASR 模型、旧 buildvenv、旧安装器、
> 仓库备份副本，约 3.1GB）、`old_builds\`（v1.11.0–v1.12.2 旧版 exe/安装包，约 2.3GB）、
> `dist\`（旧 exe 副本）与 `logs\`、`data\` 缓存已删除。此后旧版 exe 不再长期留存，
> 重打包前按惯例挪入 `old_builds\`，确认无用即删。

> 说明：仓库只对**体积可控的源码/文档/校验值**做长期留档；大体积二进制与运行日志走
> GitHub Releases 或本机备份，避免仓库与克隆体积膨胀。

## 还原方法

如需取回某个文件，直接从本目录复制回原路径即可，例如：

```bash
# 取回 v1.9 时期的投稿模块
cp history/source-backups/backup_v19_vision/uploader.py tools/
```

## 不归档的内容

以下与构建或运行直接相关，**保留在主目录、不属于历史归档**：

- `src/`：当前程序源码（`video_toolbox.py` 引擎 + `video_toolbox_qt.py` GUI 入口）
- `tools/ai_client.py`、`tools/download_open_source_deps.py`：运行期/构建期仍在使用
- `subtitle_calib_merged.py`：字幕校准脚本，运行期由程序调用，且退出时同步到 GitHub
- `installer_src/`、`视频工具箱.iss`、`视频工具箱.spec`：安装器与打包配置
- `docs/`、`build/Languages/`：当前文档与 Inno Setup 中文语言文件
