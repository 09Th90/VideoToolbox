<!-- @version 2.6.0 -->
# 视频工具箱 v2.5.3

> 补丁版：修复安装版 QSS 皮肤未加载导致的 UI 退化。v2.5.2 的安装包与在线更新包保留不删；
> 已装 v2.5.2 的用户通过程序内「检查更新」即可升级到本版。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.5.3.exe` | 约 1.0 GB | 离线安装包，新用户首选 |

已装旧版本：打开程序 → 设置 → 检查更新，内置更新器按文件差异增量下载。

SHA-256 校验：

```
ddc800d815e95f265a149ce0336189a1b2d50be062502a49552df8a03daeeab5  VideoToolbox_Setup_v2.5.3.exe
```

## 修复

- **安装版 QSS 路径**：`packaging/视频工具箱.spec` 的 `datas` 第二项必须是**目录**
  `vt_fluent/_qss`，此前误写成完整文件路径，导致 PyInstaller 把皮肤打成
  `vt_fluent/_qss/app.qss/app.qss`。冻结后 `_theme._QSS_DIR` 按
  `_MEIPASS/vt_fluent/_qss/app.qss` 读取，四个 QSS 全部失败，安装版自绘控件族
  退化为 Fusion 原生样式（开发版正常，构建日志却不报错）。
- **构建期硬断言**：spec 在 `Analysis` 后校验 QSS 目标路径；路径不对直接
  `SystemExit`，不再让错误包「构建成功」。
- **产物级自检**：新增 `scripts/dev/_selftest_qss_pack.py`，读取 onefile
  CArchive，确认 4 个 QSS 均在 `vt_fluent/_qss/<name>.qss` 且无嵌套 `.qss/` 目录。

## 验证

- 旧包负向验证：`_selftest_qss_pack.py` 复现 `app.qss/app.qss` 并 FAIL。
- 新包：archive 内 4 个 QSS 路径正确；安装版 `logs/startup.log` 无
  `QSS 读取失败` / `QSS 文件缺失`；安装版 UI 与开发版一致。
- 其余校验同 v2.5.2：语法、文档漂移、密钥扫描、ISCC 日志审计、安装闭环。

## 安装

1. 双击运行安装包，向导全程简体中文
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC
3. 装完从开始菜单或桌面快捷方式启动

---

**发布命令**（维护者用，需先推送 tag；1GB 资产分两步上传）：

```bash
gh release create v2.5.3 --draft --title "视频工具箱 v2.5.3" \
  --notes-file docs/release-notes-v2.5.3.md
gh release upload v2.5.3 "installer/VideoToolbox_Setup_v2.5.3.exe" --clobber
gh release edit v2.5.3 --draft=false --latest
```
