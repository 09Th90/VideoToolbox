<!-- @version 3.2.5 -->
# 视频工具箱 v3.1.5 变更说明（2026-11-21）

**主题：修「启动约 25 秒后界面连续冻结 1.5 分钟以上被强杀」——主线程周期全量磁盘扫描 +
启动窗口多路 CPU 密集后台任务抢 GIL 三层叠加；一并堵住三个独立真崩缺陷。**
延续 v3.1.4：全部改动走我方源码与发布链，引擎 site-packages 本体零改动。

## 修复 · 卡死（P0，三层根因）

诊断（安装版 logs\hang_watchdog.log 全线程栈 + 源码静态分析交叉验证）：进程未自崩，
是 UI 主线程被自己每 5 秒一次的全量磁盘扫描，与 T+25s 涌进的校准 AST 合并/声纹同步/
引擎预热同时抢占 GIL，连续冻结。

- **第 1 层｜媒体库周期扫描移出主线程**（`features/library/media_registry.py`）：
  全量 `os.walk`+逐文件 `stat` 改由后台合并式 worker 执行（复用 pipeline 评估线程范式），
  扫描 IO **完全不持索引锁**（仅合并结果短暂持锁），主线程查询/事件循环不再被占住或等锁；
  Qt 亲和尾部（watcher 增删路径、变更通知）经 queued 信号回主线程。`refresh/poll_once`
  保留同步语义（CLI 自检与流水线 evaluate 同步链依赖）。`os.scandir`+`DirEntry.stat()`
  替代 `os.walk`+独立 stat（省一半 syscall）；新增目录 mtime 纳秒精度快路径，空闲且全部
  落盘时跳过整轮扫描。
- **第 2 层｜校准合并去 GIL 开销**（`features/calibrate/calib_merge_core.py`、
  `core/calibrate/sync.py`）：`_canon_map` 逐 Entity 的 `ast.get_source_segment`
  （O(N×文件大小) 全源切行）换成预切行索引 `_source_segment`（逐字节复刻 stdlib，含
  UTF-8 字节偏移）；`_ast_module_tables` 加 sha256 有界 LRU 缓存；`_pull_and_merge`
  接住此前被丢弃的远端 blob sha，新增 `calib_sync_state.json` 三方 sha 前置比对——
  无人提交时整轮跳过 AST parse。实测 ~1MB 脚本合并 8282ms→137ms（60×）。
- **第 3 层｜启动后台任务串行+错峰**（`vt_app/boot.py`、`video_toolbox_qt.py`、
  `vt_app/main_window.py`）：校准/声纹同步由并行双线程改单线程顺序；startup_sync
  25s→45s、prewarm_import 30s→75s，拉开 30s 窗口。

## 修复 · 独立真崩缺陷（P1）

- **事件过滤器生命周期**（`vt_fluent/_theme.py`）：保存 watcher 引用、destroyed 回调
  改弱引用消除强引用滞留、deregister 显式 `removeEventFilter`、销毁回调只清表不触碰
  垂死控件——收敛「无父过滤器 + 强引用滞留」的 access violation 暴露面。
- **decision 动态 import 加固**（`core/shared/decision.py`）：优先 `sys.path` 注入 +
  常规 `import_module`，回退按文件加载先 `isfile` 守卫并抛清晰错误（不再裸
  FileNotFoundError）。`tools/decision_client.py` 三处发布清单已同步（v3.1.4 补齐）。
- **同步进程锁 + 重入防护**（`core/calibrate/sync.py`、`vt_app/settings_page.py`）：
  五个同步顶层入口套 `_synchronized`（进程内 RLock + 跨进程 msvcrt 文件锁，可重入、
  失败降级），杜绝启动/设置页/退出子进程三入口并发写坏 2MB 校准库；设置页「立即更新」
  加 `_sync_running` 守卫并置灰。

## 回归门禁

- 合并 golden：361 个 Call 节点指纹与 stdlib 逐字节一致、5 场景合并结果完全相同。
- sha 前置跳过 6 场景内存测试全过；扫描等价（max_depth 2/3/4）路径集合完全一致。
- 流水线自检 77/77（轮询兜底点火 0.60s）；同步锁进程内峰值并发 1、可重入、跨进程阻塞
  2.02s；主题切档自检 54/54、GUI 整机自检全过、设置页韧性 FAIL 0、声纹同步全过。
- 启动冒烟 EXIT 0：首帧 T+2.99s、首扫 0.04s（后台线程）、无看门狗停摆。
- 过程中捕获并修复自身回归：目录 mtime 快路径初版整秒截断漏检同秒新增文件（点火 6.03s），
  改 `st_mtime_ns` 纳秒精度后恢复 0.60s。

## 升级说明

- frozen 主程序 core 烘焙进 PYZ，**必须重打包主程序**方生效（本轮 onedir+Inno 离线包
  `视频工具箱_Setup_v3.1.5.exe` 静默安装到 D:\VideoToolbox，check_install_sync 校验
  exe 版本指纹=3.1.5）。
- 离线安装包本轮仅本地留存，不上传 GitHub；在线 Release 与 README 在线包名/发布链接
  更新留待后续在线发布线。
- 本安装包按 runbook 口径含工作树并行会话的 `--wuwa40ign` 校准模式（鸣潮 4.0 IGN 韩语
  反应片，自洽合法、import 闭包门禁绿）；如需「仅卡死修复」纯净包，须待并行会话结束后
  整体还原 calib_core 系文件再构建。