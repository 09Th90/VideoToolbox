<!-- @version 3.2.5 -->
# 视频工具箱 v3.1.6 变更说明（2026-11-21）

**主题：修「直播下载卡顿死循环」——EOF 误杀 + 零直播特化 + 代理控制口误记三层病根；
新增通用「下载专用代理内核」模式，出口锁定不再依赖任何第三方客户端的配置。**
延续 v3.1.5：全部改动走我方源码与发布链，引擎 site-packages 本体零改动。

## 修复 · 下载卡顿（P0）

诊断（2026-11-21 安装版取证窗口 11:45–14:05，多路只读探测交叉验证）：直播任务
T2/T12 卡顿 = 直播 1x 实时上限（物理）+「下载→误杀 yt-dlp→重提取→进度清零→重爬」
死循环（异常主因）+ 高延迟节点/退避堆叠/同 IP 限流（放大器）。

- **EOF 误杀根除**（`features/download/page.py`）：`_eof_is_fatal` 重写——缩略图/字幕
  等辅助资源行一律不致命（T12 出生即被一条缩略图 EOF 误杀实录）；新增 `frag_context`
  分片上下文（读流循环按真实分片行累积），直播/HLS 的裸 EOF 重试行不再被误判成直链
  作废；直链场景保留主动结束重提取（2026-10-17 设计不丢）。
- **直播特化**（`core/download/ytdlp_util.py`、`core/download/job.py`、page.py 双入口）：
  `is_live` 识别 → `--live-from-start`（DVR 从头追，可快于实时，断流不再落后窗口跳片
  空转）+ 直播分片并发降 2 防限流；源不支持时剥旗标退回边缘跟随；`[直播]` 日志提示
  百分比/速度仅供参考；`VT_YTDLP_LIVE_FROM_START=0` 可关；非直播参数链零漂移。

## 修复 · 代理层（P1）

- **控制口 403 捷径根除**（`core/shared/proxy.py`）：旧 `_ctl_alive` 把任何回 401/403
  的端口当活控制口（实录：TapTap 的 17120 因此当选并持久化进 config）。改为两步形状
  验证不过即不命中；密钥场景留 `_CTL_SECRET_HINT` 指引。探不到控制口时**自动清除
  config 里失效的 mihomo_controller 记忆**（坏缓存自愈）。
- **锁定失败文案免二次 netstat**：候选数由 `_probe_ctl` 记录复用。

## 新增 · 通用「下载专用代理内核」模式（不绑定任何客户端）

- `config.json` 加 `use_builtin_proxy: true`（或 env `VT_USE_BUILTIN_PROXY=1`）即启用：
  下载流量走内置 mihomo（固定 7897），其控制口 9098 恒可用 → 出口锁定/防漂移天然
  成立，无论机器上跑的是 FlClash / Clash Verge / v2rayN 还是别的。订阅 yaml 由
  `proxy_yaml` 指向**任意**机场导出；内置内核出网校验失败**自动回落系统代理**，
  下载不中断（失败结果 300s 冷却后重试）。
- **残留内核重启**：7897 被上一进程的旧订阅内核占着且节点全死时，结束残留进程按
  当前订阅重启（此前只会复用失败返回 None，新订阅永远没机会生效）。
- **锁定拓扑兼容**（实机验证发现并修复）：`_find_active_group` 兜底与 `_pin_chain`
  三层钉死从「只认 Selector」放宽到全部可切换组类型（Selector 优先）——内置
  runtime 的 AUTO(url-test)+SELECT(fallback) 拓扑此前结构性锁不上；mihomo 对
  Fallback/URLTest 亦可 PUT 钉死。
- **漂移检测修复**：runtime 分流规则置顶 ipify/ifconfig/ipinfo → SELECT——订阅
  模板把回显站判 DIRECT 时出口 IP 探测拿的是本机 IP，old==new 恒成立，漂移检测
  形同虚设。
- **占用警告同进程去重**：命名互斥体对本进程已持有也回 ERROR_ALREADY_EXISTS，
  加 owned 查重，多任务不再自报「另一实例」。
- **密钥提示端口过滤**：401/403 提示只记已知控制口端口表/显式指定/config 记忆，
  全枚举混入的无关服务不再污染 secret_needed 状态。
- **`mihomo_secret` config 键**：任何客户端的 external-controller secret 填进工具箱
  配置即可，不必改系统环境变量（env `VT_MIHOMO_SECRET` 仍优先）。
- **EOF 触发补锁定**：首任务锁定失败后，EOF 事件后台补锁一次（控制口可能中途才
  出现），120s 冷却防风暴。
- UI/翻译路由用 `ensure=False` 取代理，不阻塞主线程拉起内核。

## 修复 · 放大器抑制（P2）

- **EOF 核查异步化**（page.py）：出口 IP 核查移入后台线程，先占位提示探完补发，
  stdout 管道不再被堵；`_egress_ip` 三 URL 并发取首个成功 + 10s TTL（最坏 7.5s→2.5s，
  判漂移强制新鲜值）。
- **重试退避封顶 30s**（job.py/page.py 两处）：原 6→12→24→48s 堆叠重提取循环，
  一次抖动空转数分钟。

## 新增 · 多实例共用下载目录警告（通用）

`core/download/util.py::note_download_dir_owner`：Windows 会话级命名互斥体做占用
标记（目录路径 SHA-256 哈希定名，进程退出自动释放，零文件读写），另一存活实例
占用同一下载目录即告警（不阻断）。job/page 双入口接线。实录背景：两实例同写
D:\原片，实例2 下完的片子被实例1 流水线当自己的素材处理。

## 验证

- 下载修复自测 55 断言全绿（EOF 真值表/403 判死/坏缓存自愈/直播参数/出口 IP 缓存/
  接线静态检查/编译冒烟）；通用机制扩展自测见 data/tmp/general_proxy_selftest.py。
- 真实启动验证：内置内核 7897 出网 204 校验 + 9098 出口锁定（data/tmp/builtin_live_check.py）。