<!-- @version 2.7.0 -->
# 视频工具箱 v2.5.4

> 修复内置更新组件在 onefile 嵌套父进程下报
> `Security validation failure: failed to obtain executable path for parent processes!`
> 的问题；同时包含 v2.5.3 的安装版 QSS 路径修复。

## 修复

- **打包链升级**：PyInstaller 6.22.2 → **6.22.3**。6.22.2 的 onefile
  父进程校验在「更新完成后由替换脚本重启新主程序」这类嵌套子进程场景下
  会无法解析父进程 exe 路径，直接弹出 `Security validation failure` 并退出；
  6.22.3 修复了 intermixed nested sub-processes（上游 #9513）。
- **重建主程序与在线更新器**：两者都换用 6.22.3 的 bootloader；更新完成后的
  自动重启不再被旧 bootloader 拦截。
- **保留 v2.5.3 的 QSS 修复**：`datas` 目标目录修正、构建期硬断言、
  `_selftest_qss_pack.py` 产物自检均继续生效。

## 重要

- 当前 v2.5.3 的内置更新可能在「重启新程序」阶段报此错。**优先安装 v2.5.4
  离线包**最稳妥。
- 已装旧版的用户也可以尝试「设置 → 检查更新」：更新流程会把新主程序落地，
  重启时运行的是已修复的 6.22.3 主程序；若仍报错，请直接用离线包覆盖安装。
- v2.5.4 起更新组件恢复正常，后续可继续使用「检查更新」。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.5.4.exe` | 约 1.0 GB | 离线安装包，新用户/更新组件报错用户首选 |

已装旧版本：打开程序 → 设置 → 检查更新；若更新重启报
`Security validation failure`，请改用离线包。

SHA-256 校验：

```
a5b63d7081e3bda29ed7c9f125580a64b3b55e1c13a4d4c61d8995687b6c1ad4  VideoToolbox_Setup_v2.5.4.exe
```

## 验证

- PyInstaller 6.22.3 重建主程序与在线更新器；主程序正常启动。
- 安装版启动日志无 QSS 读取错误；`_selftest_qss_pack.py` 通过。
- 离线安装与在线更新包自测通过。

## 安装

1. 双击运行安装包，向导全程简体中文
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC
3. 装完从开始菜单或桌面快捷方式启动

---

**发布命令**（维护者用，需先推送 tag；1GB 资产分两步上传）：

```bash
gh release create v2.5.4 --draft --title "视频工具箱 v2.5.4" \
  --notes-file docs/release-notes-v2.5.4.md
gh release upload v2.5.4 "installer/VideoToolbox_Setup_v2.5.4.exe" --clobber
gh release edit v2.5.4 --draft=false --latest
```
