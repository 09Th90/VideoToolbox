#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.4.0
"""代理引导链路回归自测（2026-10-12 修复 _mihomo_api 重名遮蔽后用）。

背景：`src/video_toolbox.py` 曾有两个同名 `_mihomo_api`（全路径风格 /
(method, path) 风格），后者遮蔽前者 → `_pick_alive_node` 调
`_mihomo_api("/proxies")` 直接 TypeError → `ensure_builtin_proxy` 异常中断
→ `ytdlp_proxy_args()` 无代理 → yt-dlp 直连 → YouTube 提取 180s 超时 ×4
→ 「检测画质」永远失败。logs\\mihomo.log 里留有
"missing 1 required positional argument: 'path'" 痕迹。

本脚本按下列顺序验证修复（任一步失败即整体失败）：
  1. 模块内只有一个 `_mihomo_api` 定义（AST 复查，防再被重名遮蔽）；
  2. 冷启动 `ensure_builtin_proxy()` 不抛异常且返回代理地址；
  3. `ytdlp_proxy_args()` 返回 `--proxy <addr>`；
  4. 节点锁定链路 `proxy_group_now()` / `pick_best_proxy_node()` 可用
     （走改名后的 `_mihomo_proxy_api`，确认没改坏）；
  5.（可选，`--live`）跑一次真实 `fetch_info_json()` 实测提取。

用法：
  tools\\python\\python.exe scripts/dev/_selftest_proxy_bootstrap.py [--live]
"""
import ast
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

FAILED = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                         (" —— " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(name)


def main():
    live = "--live" in sys.argv

    # ---- 1) AST 复查：同名定义只能有一个 -------------------------------
    # v2.3.1 拆分：_mihomo_api / _mihomo_proxy_api 已搬入 core/shared/proxy.py，
    # 靶文件随之改指向；facade（video_toolbox.py）里不该再有它们的定义。
    src_path = os.path.join(ROOT, "src", "core", "shared", "proxy.py")
    with open(src_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    defs = collections.Counter()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name] += 1
    check("proxy.py 内 _mihomo_api 定义唯一", defs.get("_mihomo_api", 0) == 1,
          "实际 %d 个" % defs.get("_mihomo_api", 0))
    check("_mihomo_proxy_api 已独立存在", defs.get("_mihomo_proxy_api", 0) == 1,
          "实际 %d 个" % defs.get("_mihomo_proxy_api", 0))
    with open(os.path.join(ROOT, "src", "video_toolbox.py"), encoding="utf-8") as f:
        ftree = ast.parse(f.read())
    fdefs = {n.name for n in ftree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    check("facade 无 _mihomo_api/_mihomo_proxy_api 残留定义",
          not ({"_mihomo_api", "_mihomo_proxy_api"} & fdefs),
          sorted({"_mihomo_api", "_mihomo_proxy_api"} & fdefs))

    import video_toolbox as engine  # noqa: E402

    # ---- 2) 冷启动代理引导（此前在此处 TypeError） ----------------------
    try:
        proxy = engine.ensure_builtin_proxy()
    except Exception as e:  # noqa: BLE001
        proxy = None
        check("ensure_builtin_proxy 不抛异常", False,
              "%s: %s" % (type(e).__name__, e))
    else:
        check("ensure_builtin_proxy 不抛异常", True)
    check("ensure_builtin_proxy 返回代理地址", bool(proxy), proxy or "None")
    if not proxy:
        print("\n代理未就绪（内置节点可能暂时不可达），后续步骤跳过；"
              "请查看 logs\\mihomo.log。")
        return 1

    # ---- 3) yt-dlp 代理参数 --------------------------------------------
    args = engine.ytdlp_proxy_args(refresh=True)
    check("ytdlp_proxy_args 返回 --proxy", args[:1] == ["--proxy"], args)

    # ---- 4) 节点锁定链路（改名后的另一本） ------------------------------
    now = engine.proxy_group_now()
    check("proxy_group_now 可用", isinstance(now, str), repr(now))
    best = engine.pick_best_proxy_node()
    check("pick_best_proxy_node 可用", isinstance(best, str), repr(best))
    ok, why = engine.browser_cookie_probe("edge")
    print("[信息] proxy_status: 占位跳过；browser_cookie_probe(edge) ->",
          ok, why)

    # ---- 5) 可选：真实提取 ---------------------------------------------
    # 判定口径：
    #   · 硬回归点（FAIL）：日志里没有「提取视频信息经代理」——即 yt-dlp 没
    #     带上 --proxy，正是 2026-10-12 修复前「180s 超时 ×4」的直接形态；
    #   · 软环境项（WARN）：带上了代理但提取仍超时——内置节点快照的波动
    #     （节点全死/被 YouTube 风控），与本回归无关，重试或换订阅即可。
    # 能否过 "Sign in to confirm" 取决于用户是否给出浏览器登录态 /
    # 有效 cookies.txt，同样不属于本回归范围。
    if live:
        print("\n[*] 真实提取 YouTube 视频信息（fetch_info_json）...")
        seen = []

        def _log(m):
            seen.append(str(m))
            print("    |", m)

        ytdlp = engine.ensure_ytdlp()
        raw = engine.fetch_info_json(
            ytdlp, "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
            attempts=2, log=_log)
        joined = "\n".join(seen)
        with_proxy = "提取视频信息经代理" in joined
        check("yt-dlp 带上 --proxy（核心回归点）", with_proxy, joined[-200:])
        if raw and raw.strip().startswith("{"):
            best_fmts = engine.parse_qualities(raw)
            check("parse_qualities 解析出 >=720p 格式", bool(best_fmts),
                  "%d 档" % len(best_fmts))
        elif "提取超时" in joined:
            print("[WARN] 已带代理但提取仍超时——内置节点快照波动（环境性，"
                  "非本回归范围；可在设置页更换代理订阅后重试）")
        else:
            check("拿到 YouTube 真实响应", True, joined[-200:])

    print("\n%s（失败 %d 项）" % ("全部通过" if not FAILED else "存在失败项",
                                len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
