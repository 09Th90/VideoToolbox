<!-- @version 2.5.3 -->
# 视频工具箱 v2.5.2

> 本版以**安全整改收尾**为主：密钥与程序彻底脱钩、UI 快照脱敏、提交与推送门禁入库；
> 同时完成说明书重写、校准脚本 `--pkm` 模式与一批术语纠偏。v2.5.2 是首个包含
> 2026-10-22 安全整改的正式版本。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| `VideoToolbox_Setup_v2.5.2.exe` | 约 1.0 GB | 离线安装包，新用户首选。一次下载，装完不依赖网络 |

已安装 v2.5.1 或更早版本的用户：打开程序 → 设置 → 检查更新，
内置更新器会从 `repo-latest` 按文件差异增量下载，不需要重下整个安装包。

SHA-256 校验：

```
cbbd349b4669baf63ef11f73dc83d4e31929250596037be4e9936495270bad79  VideoToolbox_Setup_v2.5.2.exe
```

## 本版包含

### 安全整改

- **密钥与程序脱钩**：新增 `tools/credential_store.py`，`api_key` / `asr_api_key`
  等凭据改存 `data\credentials.json`（只读、按需读取、不参与配置树）；
  `ai_config.json` 不再落明文，旧配置中的明文在首次保存时自动迁移并抹除。
- **设置页不回显密钥**：密钥控件只显示「已配置」占位；留空保存表示沿用原凭据，
  不会清空。控件文本不会再进入 UI 快照与截图。
- **UI 快照脱敏**：采集 `text` / `placeholderText` / `windowTitle` 时统一替换密钥
  与本机绝对路径；新增 `scrub` 子命令；落盘前残留密钥直接拒绝写盘。
- **密钥门禁**：新增 `scripts/dev/check_secrets.py`（工作区 / 暂存区 / 全历史三模式）
  与 `pre-commit` / `pre-push` 钩子，提交/推送前自动扫描。
- 2026-10-15 泄露的两把密钥已于 2026-10-22 在平台吊销（实测 401）；本版不重写历史。

### 分发修复

- **补齐 `tools/credential_store.py` 的三处分发清单**：离线安装包 `视频工具箱.iss`、
  在线更新 `PACKAGES["tools"]`、IFW `COMPONENTS`。缺少它时，安装版/在线升级后
  首次调用 AI 或语音识别会报 `ImportError`。
- 在线安装器源方案回退：GitHub Release 资产名无法承载 IFW 的目录式仓库
  （`/` 被规范化为 `.`，斜杠 URL 实测 404）。新用户改走离线安装包；已装用户
  走程序内置更新器（`repo-latest` schema-2 manifest）。IFW 在线通道暂不可用。

### 文档

- 《程序说明书（开发版）》按「架构 → 业务域 → 表现层 → 契约 → 配置 → 构建 → 门禁」
  重写，事实基准日 2026-10-21；《程序说明书（用户版）》按任务重写。
- README、官网五个页面、`使用说明.txt`、`User_Manual_EN.md` 的下载区与版本引用
  统一到 v2.5.2；修正历史版本残留与「无离线安装包」的过期表述。
- 新增本发布说明。

### 字幕校准

- 新增 `--pkm` 宝可梦片源模式：`POKEMON_TERMS` 统一城镇/作品名，
  `POKEMON_CONTEXT` 用英文参考行锚定歧义词；与其它片源严格隔离。
- 术语纠偏：NTE = 《无限大》、Ananta = 《异环》、Imyth = 爱弥斯、
  Nod Cry = 挪德卡莱、Thurnodian = 鸣式等；修复裸键误伤
  （「金时」→「今汐」、`Shin` / 心月狐、呼啸波 等）。
- `subtitle_learned_kb.json` 记录 Shinku 裸键拒绝原因，恢复规范 `indent=1` 格式。

### 校验

- 发布前：`check_syntax`、`check_names`、`check_secrets`、`check_doc_drift --ci`、
  `_selftest_readme_facts`、`_selftest_online_xval`、`_check_vt_fluent_icons`。
- 构建后：`check_iss_sources`、ISCC 编译日志审计、`_verify_install`、
  `check_install_sync`、安装版 `import ai_client` 冒烟、`VT_GUI_SELFTEST=1`。
- 在线更新：manifest dry-run 校验、`file://` 本地自测、repo-latest 上传后版本索引核对。

## 已知限制

- 未做代码签名，少数开启应用控制策略的电脑会拦截 exe
- 离线包约 1.0 GB，首次下载耗时；已装用户走增量更新
- 自检脚本覆盖语法、文档一致性与密钥扫描，未做 GUI 自动化测试

## 安装

1. 双击运行安装包，向导全程简体中文
2. 默认装到 `D:\VideoToolbox`，可以改；不需要管理员权限，不会弹 UAC
3. 装完从开始菜单或桌面快捷方式启动

---

**发布命令**（维护者用，需先推送 tag；1GB 资产分两步上传，避免超时）：

```bash
gh release create v2.5.2 --draft --title "视频工具箱 v2.5.2" \
  --notes-file docs/release-notes-v2.5.2.md
gh release upload v2.5.2 "installer/VideoToolbox_Setup_v2.5.2.exe" --clobber
gh release edit v2.5.2 --draft=false --latest
```
