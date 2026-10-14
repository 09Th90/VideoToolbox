# @version 2.2.5
"""harness_bridge 离线自检（不启动 harness、不联网、可反复跑）。

覆盖：路径解析（默认/env/配置三级）、probe 状态机、web_alive 语义
（401=活 / 拒连=死）、provider 同步落盘内容（凭据 + home 级补丁）、
run_task 的结构化失败（空文本 / harness 不可用都不抛异常、不起进程）。

跑法：  python scripts\\dev\\_selftest_harness_bridge.py
退出码：0 = 全过；1 = 有失败（末尾打印汇总）。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import http.server

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

import harness_bridge as hb  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s%s" % ("[ok]" if cond else "[FAIL]", name,
                       (" —— " + str(detail)) if (detail and not cond) else ""))


def main():
    # ---------- ① 路径解析 ----------
    check("app_root 指向程序根", hb.app_root() == ROOT, hb.app_root())
    check("data_dir 在程序根下", hb.data_dir().startswith(ROOT))

    old_env = dict(os.environ)
    try:
        os.environ["VT_HARNESS_DIR"] = os.path.join(ROOT, "_no_such_harness")
        hb._cache["probe"] = None
        p = hb.probe(force=True)
        check("env 覆盖 harness 目录生效",
              p["dir"].endswith("_no_such_harness"), p["dir"])
        check("目录不存在 → missing", p["state"] == "missing", p["state"])

        os.environ["VT_HARNESS_DISABLED"] = "1"
        p = hb.probe(force=True)
        check("禁用开关 → disabled", p["state"] == "disabled", p["state"])
        del os.environ["VT_HARNESS_DISABLED"]
        del os.environ["VT_HARNESS_DIR"]
        hb._cache["probe"] = None

        # ---------- ② 真实部署探测 ----------
        p = hb.probe(force=True)
        check("本机 harness 探测为 ready（未部署时为 missing 也放行）",
              p["state"] in ("ready", "missing", "not_installed", "no_launcher"),
              p["state"])
        if p["state"] == "ready":
            check("启动器是绝对路径的 node",
                  os.path.isabs(p["launcher"][0]) and len(p["launcher"]) >= 2,
                  p["launcher"])

        # ---------- ③ web_alive 语义 ----------
        class _H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(401)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["VT_HARNESS_PORT"] = str(port)
        hb._cache["probe"] = None
        check("401 的服务算活着", hb.web_alive() is True)
        os.environ["VT_HARNESS_PORT"] = str(port + 1)
        check("无人监听算没活", hb.web_alive() is False)
        check("web_alive 绕过 http_proxy（本机回环）", hb.web_alive() is False)
        del os.environ["VT_HARNESS_PORT"]
        srv.shutdown()

        # ---------- ④ provider 同步 ----------
        tmp_home = tempfile.mkdtemp(prefix="vt_dsh_home_")
        os.environ["VT_HARNESS_DSH_HOME"] = tmp_home
        check("dsh_home 跟随 env", hb.dsh_home() == os.path.abspath(tmp_home))
        r = hb.sync_provider_config(force=True)
        if r["ok"]:
            cred = open(os.path.join(tmp_home, ".credentials.yaml"),
                        encoding="utf-8").read()
            patch = open(os.path.join(tmp_home, "cordis.patch.yml"),
                         encoding="utf-8").read()
            ai = hb._read_toolbox_ai()
            check("凭据写入 api_key", (ai.get("api_key") or "") in cred)
            check("补丁含 provider 路由名", "videotoolbox:" in patch)
            check("补丁含设置页 base_url", (ai.get("base_url") or "") in patch)
            check("补丁含设置页 model", "id: %s" % ai.get("model", "") in patch)
            check("补丁改写默认模型行", "provider: videotoolbox" in patch)
            check("home 级补丁落在 DSH_HOME 内",
                  os.path.isfile(os.path.join(tmp_home, "cordis.patch.yml")))
        else:
            check("本机有可用设置页 AI 配置（未配置时跳过后续断言）", True,
                  r["detail"])

        # ---------- ⑤ run_task 结构化失败（不起进程） ----------
        r = hb.run_task("   ")
        check("空文本 → ok=False 且不抛", r["ok"] is False and "空任务" in r["error"])
        os.environ["VT_HARNESS_DIR"] = os.path.join(ROOT, "_no_such_harness")
        hb._cache["probe"] = None
        r = hb.run_task("测试任务")
        check("harness 缺失 → ok=False 且不抛",
              r["ok"] is False and "不可用" in r["error"], r["error"])
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        hb._cache["probe"] = None

    print("\n通过 %d / %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("失败项：%s" % "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
