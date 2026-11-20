<!-- @version 3.1.4 -->
# 视频工具箱 v3.1.3 变更说明（2026-11-20）

**主题：三条稳定性修复——no-Lua libmpv 根治播放崩溃、全局拖放路由不再
莫名跳页、自更新被占用文件延迟交换（修 Errno 32 更新失败）。**
延续 v3.1.2：全部改动走我方源码与发布链，引擎 site-packages 本体零改动。

## 修复 · 字幕编辑播放崩溃（LuaJIT SEH 0xE24C4A02）

载入/切换视频后偶发闪退，dump 与 crash.log 签名指向 libmpv 内嵌 LuaJIT：
mpv 事件线程的 Lua 错误传播以 SEH `0xE24C4A02` 逃逸进 Python 宿主，
faulthandler 写栈时二次崩溃（jaseg/python-mpv#305）。`load_scripts=False`
与 VEH 拦截均无效，唯一可靠修复是 no-Lua 构建。

- 自有 fork（09Th90/mpv-winbuild）在 LGPL 补丁链上追加
  `-Dlua=disabled -Djavascript=disabled` 云端构建，发布
  `deps-mpv-nolua-20261120`（mpv v0.42.0-169，client API 2.6）；
  字符串扫描 LuaJIT/Lua 5.1/mujs 零残留。
- 两处下载/校验链同步新 SHA（`8ccd4ce4…`）：运行时 `ensure_mpv_dll`
  按 SHA 不一致自动重下，**老用户升级后下次启动自动换上 no-Lua DLL**；
  旧 `deps-mpv-lgpl-20260914` 保留可回滚。
- `osc=False` 改构造后容错设置（no-Lua 旧版无该选项；0.42 已提为 core
  option，容错写法新旧通吃）。
- 验证：vo=null 与 Qt wid 真实嵌入双冒烟各 12 轮切换 exit 0（旧 DLL 同
  脚本启动即 segfault）；真实平台「全局分派→字幕编辑真实载入→关闭」
  集成探针 exit 0。

## 修复 · 全局拖放路由（其它页面投喂视频跳字幕剪辑）

原则：**拖到页面之外（边缘/导航条/窗口边框）应与拖在页面正中行为一致**。
此前主窗口全局兜底把视频/音频一律送字幕编辑，切片页空白处拖视频必跳页。

- 主窗口全局分派新增「当前页认领」：首页任务创建框 → 字幕工作台语音转录
  分段 → 视频切片源视频槽，按当前页就地接收；全程 `_lazy_real` 不触发
  惰性建页。都没认领才走默认路由（下载子页等无媒体输入口的页面保留原行为）。
- 切片页补页级 dragEnter/dragMove/dropEvent + `accept_media`（共享拖放槽
  注释承诺的页级兜底此前在切片页缺失）；换源自动作废旧预览段表。
- 任务创建/语音转录两接口抽出 `import_dropped_files`，页内拖放与全局
  分派共用同一路径（保留处理中拦截与陈旧状态自愈）。
- 冷态字幕分派守卫放宽：引擎未就绪时走既有 pending 路径（切页占位+构建完
  自动续跑），不再落回字幕编辑；引擎构建失败时退回默认路由防字幕丢失。
- 新门禁 `_selftest_drop_routing.py` 22 项全过（含 v1.16.4 字幕分流与
  手动合并 step 0 回归）。

## 修复 · 自更新被占用文件延迟交换（Errno 32）

进程内自更新时 `base_library.zip → .vtold` 改名抛 WinError 32 整体回滚：
bootloader 以无 FILE_SHARE_DELETE 的数据句柄持有该文件，「运行中可改名」
只对 exe/已加载 DLL 成立。

- `apply_staging` 被锁文件（winerror 32/5）延迟：新版暂存安装目录
  `_vt_pending/` + 清单，退出后批处理交换；reconciling 保证本次已落地的
  rel 作废旧 pending（防退出后拿旧版降级新文件）。
- 主程序 `schedule_relaunch` 批处理嵌入 pending 交换行（wait 循环后、
  exe 替换前）；在线安装器 deferred 时派发等待批处理并自动重启，不再
  offer 立即启动（防双开版本混装）。
- 退出后批处理的 `timeout/tasklist/find` 改走 system32 绝对路径：Git Bash
  环境下 PATH 里 usr/bin 在前，裸名会被 GNU coreutils 劫持（GNU find 把
  `/i` 当路径遍历整盘挂死批处理）——自替换与延迟交换两条批处理同修。
- 新门禁 `_selftest_update_pending.py` 16 项全过（真持锁复现 32、批处理
  真换成功、防降级、回滚回归）。

## 回归门禁

- 静态：check_syntax / check_names / check_secrets / check_entry_isolation /
  check_schema_parity 全过。
- `_selftest_api` 18/18、`_selftest_mcp` 9/9、`_cli_golden` 全部一致、
  `_selftest_core_api` 过（MPV_DLL_URL 刻意变更已 --rebase）、
  `_selftest_pack` 全部通过（顺带修复解耦遗漏：`_CALIB_EVENT_SINK`
  补进 calibrate.ai `__all__`，engine 别名接线恢复）。
- `_selftest_gui` 全部通过；`_selftest_online_setup` / `_selftest_online_xval`
  全部通过；`_selftest_self_update` 18/18。
- 已知基线（不修）：`_selftest_vt_engine` C 组 `FasterWhisperModelEnum`
  差 `small.en`——引擎 site-packages 零改动口径，stash 基线对照确认与本次无关。

## 升级说明

- v3.0.0–v3.1.2 用户经「检查更新」或在线安装器升级；app 层（exe/_internal）
  与 code/docs/tools 本轮一并更新。**进程内更新被 Errno 32 卡住的旧版**，
  可先完全退出程序再跑在线安装器，或直接覆盖安装 v3.1.3 离线包。
- 升级后首次启动自动换 no-Lua libmpv（SHA 校验链驱动）；字幕编辑页
  载入/切换视频不再触发 LuaJIT 崩溃。
- 离线安装包 `VideoToolbox_Setup_v3.1.3.exe` 本轮仅本地留存，不上传 GitHub。