#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.3.0
"""自研「在线引导安装器」交叉验证自检（独立于 _selftest_online_setup.py 的深度套件）。

定位：_selftest_online_setup.py 覆盖基础解析与总流程；本套件专啃**并发、故障与
回滚**路径——多线程分块、断点续传、取消、重试、换源、代理源真实性、缓存自愈、
原子落地回滚、孤儿清理三重判据、分卷拼接、更新器自更新、全版本定位、CLI 契约。

全部走本地 HTTP（自建支持 Range 的服务器 + 故障模式）+ file://，不发外网请求。

运行（必须用带 tkinter 的解释器，如 tools\\python\\python.exe）：
    tools\\python\\python.exe scripts\\dev\\_selftest_online_xval.py
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OREL = os.path.join(ROOT, "packaging", "online_release")
sys.path.insert(0, OREL)

FAILS = []
_SKIPS = []


def check(name, cond, extra=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                          (" -> " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print("  [SKIP] %s（%s）" % (name, why))
    _SKIPS.append(name)


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print("      （抛了别的异常：%r）" % e)
        return False
    return False


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


import vt_update_core as core  # noqa: E402
import vt_dl  # noqa: E402
import vt_version_index as vindex  # noqa: E402


# ================================================================ HTTP 服务器
class ModeHandler(BaseHTTPRequestHandler):
    """支持 Range 的静态服务器；路径前缀切换故障模式：

      /flaky/<f>   探测(0-0)放行，其余 Range 前 fail_first 次返回 503
      /dead/<f>    探测(0-0)放行，其余 Range 永远 503（换源测试）
      /norange/<f> 无视 Range，永远 200 整文件（退化成 download_simple）
      /<f>         正常 206
    """
    server_root = ""
    fail_first = 0
    counter = {"n": 0}
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def do_GET(self):
        name = self.path.lstrip("/")
        mode, rel = "ok", name
        for pre in ("flaky/", "dead/", "norange/"):
            if name.startswith(pre):
                mode, rel = pre.rstrip("/"), name[len(pre):]
                break
        p = os.path.join(self.server_root, rel)
        if not os.path.isfile(p):
            self.send_error(404)
            return
        size = os.path.getsize(p)
        rng = self.headers.get("Range")
        if mode == "norange" or not rng:
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with open(p, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile)
            return
        m = re.match(r"bytes=(\d+)-(\d+)", rng)
        if not m:
            self.send_error(400)
            return
        s, e = int(m.group(1)), int(m.group(2))
        if mode in ("flaky", "dead") and rng != "bytes=0-0":
            with ModeHandler.lock:
                ModeHandler.counter["n"] += 1
                n = ModeHandler.counter["n"]
            limit = 10 ** 9 if mode == "dead" else ModeHandler.fail_first
            if n <= limit:
                self.send_error(503)
                return
        self.send_response(206)
        self.send_header("Content-Range", "bytes %d-%d/%d" % (s, e, size))
        self.send_header("Content-Length", str(e - s + 1))
        self.end_headers()
        with open(p, "rb") as fh:
            fh.seek(s)
            left = e - s + 1
            while left > 0:
                b = fh.read(min(65536, left))
                if not b:
                    break
                self.wfile.write(b)
                left -= len(b)


def start_server(root):
    ModeHandler.server_root = root
    ModeHandler.fail_first = 0
    ModeHandler.counter["n"] = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ModeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


# ================================================================ 迷你代理
def start_proxy(record):
    """一个只会转发 GET 的迷你 HTTP 代理，用于验证「代理源真的走了代理」。"""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(16)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                conn.settimeout(30)
                head = b""
                while b"\r\n\r\n" not in head:
                    b = conn.recv(4096)
                    if not b:
                        break
                    head += b
                line = head.split(b"\r\n", 1)[0].decode("latin1")
                m = re.match(r"GET (\S+) HTTP/", line)
                if not m:
                    conn.close()
                    continue
                abs_url = m.group(1)
                record.append(abs_url)
                um = re.match(r"http://([^/:]+)(?::(\d+))?(.*)", abs_url)
                host, prt, path = um.group(1), int(um.group(2) or 80), \
                    um.group(3) or "/"
                up = socket.create_connection((host, prt), timeout=30)
                req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\n"
                       "Connection: close\r\n\r\n" % (path, host, prt))
                up.sendall(req.encode("latin1"))
                while True:
                    b = up.recv(65536)
                    if not b:
                        break
                    conn.sendall(b)
                up.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return srv, port


# ================================================================ 发布物构造
def make_release(tmp, version, files, pkg_of=None, base=None):
    """按 schema 2 造发布目录：各包 zip。files: {相对路径: bytes}。"""
    pkg_of = pkg_of or {}
    pkgs = {}
    for rel, data in files.items():
        pkgs.setdefault(pkg_of.get(rel, "base"), {})[rel] = data
    assets, files_all = [], {}
    for pkg, items in pkgs.items():
        zp = os.path.join(tmp, "v%s-%s.zip" % (version, pkg))
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, data in items.items():
                zi = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
                zf.writestr(zi, data)
                files_all[rel] = {"size": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest(),
                                  "pkg": pkg}
        assets.append({"name": pkg, "file": os.path.basename(zp),
                       "size": os.path.getsize(zp), "sha256": sha(zp),
                       "entries": len(items), "target": "", "desc": pkg})
    man = {"schema": 2, "app": "视频工具箱", "version": version,
           "released": "2026-10-12 00:00:00",
           "base_url": base or ("file:///" + tmp.replace("\\", "/")),
           "assets": assets, "files": files_all, "remove": [],
           "notes": "test %s" % version}
    return man, tmp


# ================================================================ 用例
def t_dl_engine(tmp):
    print("\n== 1) 下载引擎：多线程分块 / file:// / 无 Range 退化 ==")
    srv, base = start_server(tmp)
    try:
        big = os.path.join(tmp, "big.bin")
        data = os.urandom(3 * 1024 * 1024) + b"TAIL"
        open(big, "wb").write(data)
        url = base + "/big.bin"

        dst = os.path.join(tmp, "o1", "big.bin")
        vt_dl.download_file("file:///" + big.replace("\\", "/"), dst)
        check("file:// 下载一致", sha(dst) == sha(big))
        check("不残留 .dlpart/.dlstate",
              not os.path.exists(dst + ".dlpart")
              and not os.path.exists(dst + ".dlstate"))

        dst2 = os.path.join(tmp, "o2", "big.bin")
        orig_plan = vt_dl.plan_chunks
        vt_dl.plan_chunks = lambda size, threads=8: [
            (s, min(s + 256 * 1024, size))
            for s in range(0, size, 256 * 1024)]
        try:
            stats = {}
            vt_dl.download_file(url, dst2, stats=stats)
        finally:
            vt_dl.plan_chunks = orig_plan
        check("HTTP 多线程分块下载一致", sha(dst2) == sha(big))
        check("stats 记录了源标签", bool(stats.get("source")), stats)
        check("完成后状态文件清理", not os.path.exists(dst2 + ".dlstate"))

        dst3 = os.path.join(tmp, "o3", "big.bin")
        vt_dl.download_file(url, dst3, expect_sha256=sha(big))
        check("expect_sha256 一致时成功", os.path.isfile(dst3))

        dst4 = os.path.join(tmp, "o4", "big.bin")
        vt_dl.download_file(base + "/norange/big.bin", dst4)
        check("无 Range 源退化成整文件流", sha(dst4) == sha(big))
    finally:
        srv.shutdown()


def t_dl_resume_cancel(tmp):
    print("\n== 2) 断点续传与取消 ==")
    srv, base = start_server(tmp)
    try:
        big = os.path.join(tmp, "big.bin")
        if not os.path.isfile(big):
            open(big, "wb").write(os.urandom(3 * 1024 * 1024) + b"TAIL")
        url = base + "/big.bin"
        dst = os.path.join(tmp, "o5", "big.bin")

        orig_plan = vt_dl.plan_chunks
        vt_dl.plan_chunks = lambda size, threads=8: [
            (s, min(s + 256 * 1024, size))
            for s in range(0, size, 256 * 1024)]
        cancel = threading.Event()
        got = {"n": 0}

        def on_prog(d, t):
            got["n"] += 1
            cancel.set()

        try:
            cancelled = False
            try:
                vt_dl.download_file(url, dst, progress=on_prog, cancel=cancel)
            except vt_dl.Canceled:
                cancelled = True
            check("取消抛 Canceled", cancelled)
            check("进度回调确实来过（至少一块落地）", got["n"] >= 1, got)
            check("取消后 .dlpart 保留（可续传）",
                  os.path.isfile(dst + ".dlpart"))
            check("取消后 .dlstate 保留", os.path.isfile(dst + ".dlstate"))
            check("续传文件已预分配全长",
                  os.path.getsize(dst + ".dlpart") == os.path.getsize(big))

            # —— 同几何续传：真的只补缺失块，不是从头再来 ——
            cancel.clear()
            logs_b = []
            vt_dl.download_file(url, dst, cancel=cancel, log=logs_b.append)
            check("续传后完整一致", sha(dst) == sha(big))
            check("续传后状态文件清理", not os.path.exists(dst + ".dlstate"))
            m = re.search(r"(\d+)/(\d+) 块待传", "\n".join(logs_b))
            check("续传只补缺失块（非全量重下）",
                  m is None or int(m.group(1)) < int(m.group(2)),
                  m.group(0) if m else "无待传信息（续传文件已完整）")

            # —— 回归：续传时若分块几何变了（调用方换了 threads，或升级
            # 引擎改了分块常量），.dlstate 必须整体作废重下——否则 done
            # 下标错位，.dlpart 是预分配全长的，拼出带洞文件且大小校验
            # 看不出来（静默损坏）。本用例即复现该故障。 ——
            dst2 = os.path.join(tmp, "o5b", "big.bin")
            cancel2 = threading.Event()
            n2 = {"n": 0}

            def on_prog2(d, t):
                n2["n"] += 1
                cancel2.set()

            try:
                vt_dl.download_file(url, dst2, progress=on_prog2,
                                    cancel=cancel2)
            except vt_dl.Canceled:
                pass
            check("几何回归：取消阶段留下了 .dlpart",
                  os.path.isfile(dst2 + ".dlpart"))
        finally:
            vt_dl.plan_chunks = orig_plan   # 续传换回真实几何（1MB 块）

        cancel2.clear()
        vt_dl.download_file(url, dst2, cancel=cancel2)
        check("换几何续传后完整一致（无字节洞）", sha(dst2) == sha(big))
        check("换几何续传后状态文件清理",
              not os.path.exists(dst2 + ".dlstate"))
    finally:
        srv.shutdown()


def t_dl_negative(tmp):
    print("\n== 3) 负向：校验不符 / 全源失败 / 单源重试 ==")
    srv, base = start_server(tmp)
    try:
        good = os.path.join(tmp, "g.bin")
        open(good, "wb").write(b"G" * 65536)

        dst = os.path.join(tmp, "o6", "g.bin")
        check("sha256 不符抛 DlError",
              raises(vt_dl.DlError, vt_dl.download_file, base + "/g.bin",
                     dst, None, None, None, 8, "0" * 64))
        check("不符时 dest 不落地", not os.path.isfile(dst))

        dst2 = os.path.join(tmp, "o7", "g.bin")
        t0 = time.time()
        ok = raises(vt_dl.DlError, vt_dl.download_file,
                    base + "/dead/g.bin", dst2)
        check("全源失败抛 DlError", ok)
        check("失败不挂死（<40s）", time.time() - t0 < 40,
              "%.1fs" % (time.time() - t0))
        check("全源失败 dest 不落地", not os.path.isfile(dst2))

        ModeHandler.fail_first = 2
        ModeHandler.counter["n"] = 0
        dst3 = os.path.join(tmp, "o8", "g.bin")
        vt_dl.download_file(base + "/flaky/g.bin", dst3)
        check("单源内重试后成功", sha(dst3) == sha(good))
        ModeHandler.fail_first = 0
        ModeHandler.counter["n"] = 0

        check("404 抛 DlError",
              raises(vt_dl.DlError, vt_dl.download_file,
                     base + "/missing.bin", os.path.join(tmp, "o9.bin")))
    finally:
        srv.shutdown()


def t_dl_source_switch(tmp):
    print("\n== 4) 换源：坏源三次不过 → 换好源补齐该块（回归） ==")
    srv, base = start_server(tmp)
    try:
        good = os.path.join(tmp, "g.bin")
        if not os.path.isfile(good):
            open(good, "wb").write(b"G" * 65536)
        orig_chain = vt_dl.source_chain
        direct = vt_dl._direct_opener()
        vt_dl.source_chain = lambda url, log=None, allow_proxy=True: [
            vt_dl.Source("坏源", base + "/dead/g.bin", direct),
            vt_dl.Source("好源", base + "/g.bin", direct),
        ]
        try:
            dst = os.path.join(tmp, "o10", "g.bin")
            vt_dl.download_file(base + "/g.bin", dst)
            check("坏源切换后好源补齐，文件完整", sha(dst) == sha(good))
        finally:
            vt_dl.source_chain = orig_chain
    finally:
        srv.shutdown()


def t_dl_proxy_source(tmp):
    print("\n== 5) 代理源真实性：ProxyHandler opener 必须真正生效 ==")
    srv, base = start_server(tmp)
    try:
        good = os.path.join(tmp, "g.bin")
        if not os.path.isfile(good):
            open(good, "wb").write(b"G" * 65536)
        record = []
        pxy, pport = start_proxy(record)
        try:
            orig_chain = vt_dl.source_chain
            vt_dl.source_chain = lambda url, log=None, allow_proxy=True: [
                vt_dl.Source("代理源", url,
                             vt_dl._proxy_opener("http://127.0.0.1:%d" % pport)),
            ]
            # Windows 的 proxy_bypass 对 127.0.0.1 恒为 True（IE「绕过
            # 本地地址」默认开着），ProxyHandler.proxy_open 会因此跳过
            # 代理直连——不 patch 掉它，这个用例永远绿不了，而真实场景
            # 里代理源打的是 github.com，不在绕过名单里。patch 后才能
            # 真正验证「src.opener 被用上了」。
            real_bypass = urllib.request.proxy_bypass
            urllib.request.proxy_bypass = lambda _h: False
            try:
                dst = os.path.join(tmp, "o11", "g.bin")
                vt_dl.download_file(base + "/g.bin", dst)
                check("经代理源下载成功", sha(dst) == sha(good))
                check("代理服务器确实被连接过（opener 生效）",
                      len(record) >= 1, record[:2])
            finally:
                urllib.request.proxy_bypass = real_bypass
                vt_dl.source_chain = orig_chain
        finally:
            pxy.close()
    finally:
        srv.shutdown()


def t_schema2_install(tmp):
    print("\n== 6) schema 2 全新安装 ==")
    rel = os.path.join(tmp, "rel1")
    os.makedirs(rel)
    man, _ = make_release(rel, "1.0.0",
                          {"视频工具箱.exe": b"EXE" * 1000,
                           "src/a.py": b"x=1",
                           "docs/readme.txt": b"hi"},
                          pkg_of={"视频工具箱.exe": "app", "src/a.py": "code",
                                  "docs/readme.txt": "docs"})
    tgt = os.path.join(tmp, "i1")
    logs = []
    res = core.apply_update(man, tgt, os.path.join(tmp, "c1"), log=logs.append)
    check("三个文件全部落地", res["files"] == 3, res)
    check("exe 内容一致",
          sha(os.path.join(tgt, "视频工具箱.exe"))
          == hashlib.sha256(b"EXE" * 1000).hexdigest())
    check("子目录文件到位", os.path.isfile(os.path.join(tgt, "src", "a.py")))
    check("vt_installed.json 已写入",
          os.path.isfile(os.path.join(tgt, "vt_installed.json")))
    inst = core.read_installed(tgt)
    check("本地清单含版本号", bool(inst) and inst.get("version") == "1.0.0")
    check("本地清单覆盖全部文件", bool(inst) and len(inst["files"]) == 3)
    check("下载完成后清掉 zip 缓存",
          not os.path.isfile(os.path.join(tmp, "c1", "v1.0.0-app.zip")))
    check("日志有内容", len(logs) > 5, len(logs))


def t_schema2_incremental(tmp):
    print("\n== 7) 增量更新：只下变化的包 / 本地被改重下 / 缓存自愈 ==")
    rel = os.path.join(tmp, "rel2")
    os.makedirs(rel)
    man1, _ = make_release(rel, "1.0.0",
                           {"视频工具箱.exe": b"EXE" * 1000,
                            "src/a.py": b"x=1"},
                           pkg_of={"视频工具箱.exe": "app", "src/a.py": "code"})
    tgt = os.path.join(tmp, "i2")
    core.apply_update(man1, tgt, os.path.join(tmp, "c2a"))

    man2, _ = make_release(rel, "1.1.0",
                           {"视频工具箱.exe": b"EXE" * 1000,
                            "src/a.py": b"x=2"},
                           pkg_of={"视频工具箱.exe": "app", "src/a.py": "code"})
    plan = core.plan_update(man2, tgt)
    check("只规划 code 包", [a["name"] for a in plan["need"]] == ["code"],
          [a["name"] for a in plan["need"]])
    check("app 包计入跳过字节", plan["skip_bytes"] > 0, plan["skip_bytes"])
    check("识别出本地版本 1.0.0", plan["local_version"] == "1.0.0",
          plan["local_version"])
    # app zip 删掉也能更新 → 证明没下 app 包
    os.remove(os.path.join(rel, "v1.0.0-app.zip"))
    res = core.apply_update(man2, tgt, os.path.join(tmp, "c2b"))
    check("增量更新落地 1 个文件", res["files"] == 1, res)
    check("新内容到位",
          open(os.path.join(tgt, "src", "a.py"), "rb").read() == b"x=2")
    check("版本号已刷新", core.read_installed(tgt).get("version") == "1.1.0")

    plan2 = core.plan_update(man2, tgt)
    check("无变化时 need 为空", plan2["need"] == [], plan2["need"])

    with open(os.path.join(tgt, "src", "a.py"), "wb") as fh:
        fh.write(b"x=hacked")
    plan3 = core.plan_update(man2, tgt)
    check("本地被改动的文件重新纳入计划",
          [a["name"] for a in plan3["need"]] == ["code"],
          [a["name"] for a in plan3["need"]])

    # 缓存 zip 损坏（sha 不符）→ 应自愈重下，而非永久失败
    zp = os.path.join(tmp, "c2c")
    os.makedirs(zp, exist_ok=True)
    shutil.copy2(os.path.join(rel, "v1.1.0-code.zip"),
                 os.path.join(zp, "v1.1.0-code.zip"))
    with open(os.path.join(zp, "v1.1.0-code.zip"), "r+b") as fh:
        fh.seek(5)
        fh.write(b"\x00\x00\x00\x00")
    try:
        res2 = core.apply_update(man2, tgt, zp)
        check("缓存损坏后能重下自愈", res2["files"] == 1, res2)
        check("自愈后内容正确",
              open(os.path.join(tgt, "src", "a.py"), "rb").read() == b"x=2")
    except core.UpdateError as e:
        check("缓存损坏后能重下自愈", False, str(e)[:120])


def t_schema2_orphan(tmp):
    print("\n== 8) 降级 / 孤儿清理三重判据 ==")
    rel = os.path.join(tmp, "rel3")
    os.makedirs(rel)
    man_new, _ = make_release(rel, "2.0.0", {"a.txt": b"A2", "b.txt": b"B2"})
    tgt = os.path.join(tmp, "i3")
    core.apply_update(man_new, tgt, os.path.join(tmp, "c3a"))

    man_old, _ = make_release(rel, "1.0.0", {"a.txt": b"A1"})
    plan = core.plan_update(man_old, tgt)
    check("降级识别出孤儿 b.txt", plan["orphans"] == ["b.txt"], plan["orphans"])
    core.apply_update(man_old, tgt, os.path.join(tmp, "c3b"))
    check("孤儿文件已清理", not os.path.isfile(os.path.join(tgt, "b.txt")))
    check("保留文件已降级",
          open(os.path.join(tgt, "a.txt"), "rb").read() == b"A1")

    core.apply_update(man_new, tgt, os.path.join(tmp, "c3c"))
    with open(os.path.join(tgt, "b.txt"), "wb") as fh:
        fh.write(b"user-data")
    plan2 = core.plan_update(man_old, tgt)
    check("被用户改动的文件不进孤儿表", plan2["orphans"] == [],
          plan2["orphans"])
    core.apply_update(man_old, tgt, os.path.join(tmp, "c3d"))
    check("用户文件原样保留",
          open(os.path.join(tgt, "b.txt"), "rb").read() == b"user-data")

    os.remove(os.path.join(tgt, "vt_installed.json"))
    plan3 = core.plan_update(man_old, tgt)
    check("无本地清单时不算孤儿（宁留不删）", plan3["orphans"] == [],
          plan3["orphans"])


def t_staging_rollback(tmp):
    print("\n== 9) 原子落地失败整体回滚 ==")
    rel = os.path.join(tmp, "rel4")
    os.makedirs(rel)
    man1, _ = make_release(rel, "1.0.0", {"a.txt": b"A1", "b.txt": b"B1"})
    tgt = os.path.join(tmp, "i4")
    core.apply_update(man1, tgt, os.path.join(tmp, "c4a"))

    man2, _ = make_release(rel, "1.1.0", {"a.txt": b"A2", "b.txt": b"B2"})
    real_move = core.shutil.move
    calls = {"n": 0}

    def flaky_move(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("模拟磁盘故障")
        return real_move(src, dst, *a, **kw)

    core.shutil.move = flaky_move
    try:
        ok = raises(core.UpdateError, core.apply_update, man2, tgt,
                    os.path.join(tmp, "c4b"))
    finally:
        core.shutil.move = real_move
    check("落地失败抛 UpdateError", ok)
    check("回滚后 a.txt 是旧内容",
          open(os.path.join(tgt, "a.txt"), "rb").read() == b"A1")
    check("回滚后 b.txt 是旧内容",
          open(os.path.join(tgt, "b.txt"), "rb").read() == b"B1")
    check("回滚后无 .vtold 残留",
          not os.path.exists(os.path.join(tgt, "a.txt.vtold"))
          and not os.path.exists(os.path.join(tgt, "b.txt.vtold")))
    check("回滚后版本清单未被改写",
          core.read_installed(tgt).get("version") == "1.0.0")

    res = core.apply_update(man2, tgt, os.path.join(tmp, "c4c"))
    check("故障恢复后可正常更新", res["files"] == 2, res)


def t_verify_staging_negative(tmp):
    print("\n== 10) 暂存区逐文件校验（负向） ==")
    rel = os.path.join(tmp, "rel4b")
    os.makedirs(rel)
    man, _ = make_release(rel, "1.0.0", {"a.txt": b"A1", "b.txt": b"B1"})
    tgt = os.path.join(tmp, "i4b")
    # 先手工解出暂存区，再改坏一个文件 → verify_staging 必须抓到
    stg = os.path.join(tmp, "stg4b")
    os.makedirs(stg)
    with zipfile.ZipFile(os.path.join(rel, "v1.0.0-base.zip")) as zf:
        zf.extractall(stg)
    with open(os.path.join(stg, "a.txt"), "wb") as fh:
        fh.write(b"tampered")
    check("暂存区文件被改坏后 verify 报错",
          raises(core.UpdateError, core.verify_staging, stg, man, {"base"}))
    check("verify 报错信息含文件名",
          "a.txt" in _err_text(core.verify_staging, stg, man, {"base"}))


def _err_text(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return str(e)
    return ""


def t_parts(tmp):
    print("\n== 11) 分卷下载与拼接 ==")
    rel = os.path.join(tmp, "rel5")
    os.makedirs(rel)
    whole = os.urandom(300 * 1024) + b"MID" + os.urandom(300 * 1024)
    zp = os.path.join(rel, "v1.0.0-base.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", whole)
    vol = 200 * 1024
    parts = []
    with open(zp, "rb") as fh:
        i = 0
        while True:
            b = fh.read(vol)
            if not b:
                break
            i += 1
            pname = "v1.0.0-base.zip.%03d" % i
            open(os.path.join(rel, pname), "wb").write(b)
            parts.append(pname)
    os.remove(zp)
    joined = b"".join(open(os.path.join(rel, p), "rb").read() for p in parts)
    asset = {"name": "base", "file": "v1.0.0-base.zip", "parts": parts,
             "size": len(joined),
             "sha256": hashlib.sha256(joined).hexdigest()}
    man = {"schema": 2, "version": "1.0.0",
           "base_url": "file:///" + rel.replace("\\", "/"),
           "assets": [asset],
           "files": {"a.txt": {"size": len(whole),
                               "sha256": hashlib.sha256(whole).hexdigest(),
                               "pkg": "base"}},
           "remove": []}
    dest = os.path.join(tmp, "parts.bin")
    core.download_asset(man, asset, dest)
    check("分卷拼回与源一致", sha(dest) == asset["sha256"])
    check("分卷临时文件已清理", not os.path.exists(dest + ".part001"))
    with zipfile.ZipFile(dest) as zf:
        check("拼回后是合法 zip 且内容一致", zf.read("a.txt") == whole)

    bad_rel = os.path.join(tmp, "rel5b")
    shutil.copytree(rel, bad_rel)
    with open(os.path.join(bad_rel, parts[0]), "r+b") as fh:
        fh.seek(3)
        fh.write(b"\xff")
    man_bad = json.loads(json.dumps(man))
    man_bad["base_url"] = "file:///" + bad_rel.replace("\\", "/")
    check("分卷损坏抛 UpdateError",
          raises(core.UpdateError, core.download_asset, man_bad, asset,
                 os.path.join(tmp, "parts_bad.bin")))


def t_updater(tmp):
    print("\n== 12) 更新器自身 ensure_updater ==")
    rel = os.path.join(tmp, "rel6")
    os.makedirs(rel)
    up_name = "视频工具箱_在线安装_v9.9.9.exe"
    up_data = b"UPDATER-BINARY" * 100
    open(os.path.join(rel, up_name), "wb").write(up_data)
    man = {"schema": 2, "version": "9.9.9",
           "base_url": "file:///" + rel.replace("\\", "/"),
           "assets": [], "files": {}, "remove": [],
           "updater": {"file": up_name, "size": len(up_data),
                       "sha256": hashlib.sha256(up_data).hexdigest()}}
    tgt = os.path.join(tmp, "i6")
    os.makedirs(tgt)
    p = core.ensure_updater(man, tgt, os.path.join(tmp, "c6"))
    check("更新器已下载", os.path.isfile(p))
    check("更新器内容一致", sha(p) == hashlib.sha256(up_data).hexdigest())
    logs2 = []
    p2 = core.ensure_updater(man, tgt, os.path.join(tmp, "c6"), log=logs2.append)
    check("已是最新时原地返回", p2 == p)
    check("已是最新时不产生下载日志",
          not any("更新在线安装器" in x for x in logs2), logs2)
    check("无 updater 条目返回 None",
          core.ensure_updater({"updater": {}}, tgt,
                              os.path.join(tmp, "c6")) is None)
    check("find_updater_exe 能找到", core.find_updater_exe(tgt).endswith(up_name))


def t_version_resolve(tmp):
    print("\n== 13) 全版本定位 resolve_manifest ==")
    rel = os.path.join(tmp, "rel7")
    os.makedirs(rel)
    for v, tag in (("1.0.0", "OLD"), ("1.5.0", "MID"), ("2.0.0", "NEW")):
        man, _ = make_release(rel, v, {"a.txt": tag.encode()})
        with open(os.path.join(rel, "manifest-%s.json" % v), "w",
                  encoding="utf-8") as fh:
            json.dump(man, fh, ensure_ascii=False)
    idx = vindex.new_index("视频工具箱", "file:///" + rel.replace("\\", "/"))
    for v in ("1.0.0", "1.5.0", "2.0.0"):
        vindex.upsert_version(idx, {"version": v,
                                    "manifest": "manifest-%s.json" % v,
                                    "released": "2026-10-01 00:00:00",
                                    "state": "stable", "min_updater": ""})
    idx["channels"] = {"latest": "2.0.0", "stable": "1.5.0"}
    idx_path = os.path.join(rel, "index.json")
    vindex.save_index(idx, idx_path)

    def res(want, **kw):
        return core.resolve_manifest(want, index_url=idx_path, **kw)[0]

    check("latest → 2.0.0", res("latest")["version"] == "2.0.0")
    check("stable → 1.5.0", res("stable")["version"] == "1.5.0")
    check("精确版本 1.0.0", res("1.0.0")["version"] == "1.0.0")
    check("范围 ^1 → 1.5.0", res("^1")["version"] == "1.5.0")
    check("范围 <2.0.0 → 1.5.0", res("<2.0.0")["version"] == "1.5.0")
    check("次版本写法 1 → 1.5.0", res("1")["version"] == "1.5.0")
    check("空串等价 latest", res("")["version"] == "2.0.0")

    mf = os.path.join(rel, "manifest.json")
    with open(mf, "w", encoding="utf-8") as fh:
        json.dump(res("latest"), fh, ensure_ascii=False)
    m, entry = core.resolve_manifest("latest", manifest=mf)
    check("老路径（无 index）直读 manifest.json",
          m["version"] == "2.0.0" and entry is None)

    idx2 = json.loads(json.dumps(idx))
    idx2["versions"][0]["min_updater"] = "9.9.9"
    p2 = os.path.join(rel, "index2.json")
    with open(p2, "w", encoding="utf-8") as fh:
        json.dump(idx2, fh, ensure_ascii=False)
    check("更新器过旧装不了新版本（明确报错）",
          raises(core.UpdateError, core.resolve_manifest, "2.0.0",
                 index_url=p2))

    idx3 = json.loads(json.dumps(idx))
    for e in idx3["versions"]:
        if e["version"] == "2.0.0":
            e["state"] = "yanked"
    p3 = os.path.join(rel, "index3.json")
    with open(p3, "w", encoding="utf-8") as fh:
        json.dump(idx3, fh, ensure_ascii=False)
    m3, _ = core.resolve_manifest("latest", index_url=p3)
    check("latest 不落在 yanked 上", m3["version"] == "1.5.0", m3["version"])
    m4, _ = core.resolve_manifest("2.0.0", index_url=p3, allow_hidden=True)
    check("yanked 版本显式可装", m4["version"] == "2.0.0")


def t_build_side(tmp):
    print("\n== 14) 打包侧 build_online_release ==")
    bor = load("_bor", os.path.join(OREL, "build_online_release.py"))
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    ver = re.search(r'VERSION\s*=\s*"([\d.]+)"',
                    open(p, encoding="utf-8").read()).group(1)
    check("读到的版本号与 qt 源码一致", bor.read_version() == ver,
          bor.read_version())
    bor.check_packages_in_sync()
    check("组件清单与 IFW 版一致（未退出即通过）", True)

    out = os.path.join(tmp, "rel8")
    os.makedirs(out)
    src1 = os.path.join(tmp, "s1.txt")
    open(src1, "wb").write(b"hello " * 1000)
    src2 = os.path.join(tmp, "sub", "s2.bin")
    os.makedirs(os.path.dirname(src2))
    open(src2, "wb").write(os.urandom(4096))
    asset, files = bor.build_package("test", [(src1, "t/s1.txt"),
                                              (src2, "t/sub/s2.bin")],
                                     out, 10 ** 9)
    check("资产字段齐全",
          asset["name"] == "test" and asset["entries"] == 2
          and asset["sha256"] == sha(os.path.join(out, asset["file"])))
    check("文件清单含 size/sha256/pkg",
          files["t/s1.txt"]["pkg"] == "test"
          and files["t/s1.txt"]["sha256"] == sha(src1))
    with zipfile.ZipFile(os.path.join(out, asset["file"])) as zf:
        check("zip 内路径正确",
              sorted(zf.namelist()) == ["t/s1.txt", "t/sub/s2.bin"],
              zf.namelist())

    out2 = os.path.join(tmp, "rel9")
    os.makedirs(out2)
    big = os.path.join(tmp, "big2.bin")
    open(big, "wb").write(os.urandom(600 * 1024))
    asset2, _ = bor.build_package("vol", [(big, "big.bin")], out2, 200 * 1024)
    # 切卷逻辑 = 按 volume_max 逐段读，卷数应恰为 ceil(size/limit)。
    # 不写死 3——zip 压缩后体积随内容浮动，写死会在边界上误报。
    expect_parts = -(-asset2["size"] // (200 * 1024))
    check("超限自动分卷", bool(asset2.get("parts"))
          and len(asset2["parts"]) == expect_parts,
          "%d 卷（期望 %d）" % (len(asset2.get("parts") or []), expect_parts))
    check("分卷后 file 去掉 .001",
          asset2["file"] == "v%s-vol.zip" % ver, asset2["file"])
    joined = b"".join(open(os.path.join(out2, p), "rb").read()
                      for p in asset2["parts"])
    check("分卷拼回字节数一致", len(joined) == asset2["size"])
    check("分卷 sha 与整包一致",
          hashlib.sha256(joined).hexdigest() == asset2["sha256"])

    out3 = os.path.join(tmp, "rel10")
    os.makedirs(out3)
    bad = os.path.join(tmp, "tools", "github_proxy.yaml")
    os.makedirs(os.path.dirname(bad))
    open(bad, "w").write("x: 1")
    okf = os.path.join(tmp, "tools", "ok.py")
    open(okf, "w").write("y = 2")
    # v2.0.0 起语义升级：FORBIDDEN 命中不再「静默跳过」而是**拒绝发布**（exit 2）
    # ——被跳过的文件既不进 zip 也不进清单，客户端校验发现不了「从未存在的文件」。
    # 故此处断言"抛 SystemExit(2)"，而非旧语义的"跳过后其余文件正常入库"。
    rc = 0
    try:
        bor.build_package("tools",
                          [(bad, "tools/github_proxy.yaml"),
                           (okf, "tools/ok.py")], out3, 10 ** 9)
    except SystemExit as e:
        rc = e.code
    check("禁止项命中即拒绝发布", rc == 2, "exit=%r" % rc)
    check("拒绝时未产出半成品清单",
          not os.path.exists(os.path.join(out3, "manifest.json")))

    idx = vindex.new_index("视频工具箱", "file:///" + out.replace("\\", "/"))
    # P0 语义（v2.0.0 起）：只有 **404** 才算首次发版；网络错/不存在的路径
    # 一律**拒绝发布**——旧实现按首次发版处理，空索引上传会整体覆盖抹掉
    # 远端全版本目录。此处 file:// 走到的是 FileNotFoundError（非 404）。
    rc2 = None
    try:
        got = bor.fetch_remote_index("file:///" + out.replace("\\", "/"),
                                     tries=1)
    except SystemExit as e:
        got, rc2 = None, e.code
    check("取远端索引失败按拒绝发布（非首次发版）",
          rc2 is not None and "拒绝发布" in str(rc2), str(rc2)[:80])
    # --force-first 显式放行 → 才按首次发版造空索引
    gotf = bor.fetch_remote_index("file:///" + out.replace("\\", "/"),
                                  force_first=True, tries=1)
    check("--force-first 放行后按首次发版",
          gotf.get("versions") == [], gotf.get("versions"))
    bor.merge_remote_versions(idx, {"versions": [
        {"version": "0.9.0", "manifest": "manifest-0.9.0.json"}]})
    vindex.upsert_version(idx, {"version": ver, "manifest": "m.json",
                                "min_updater": ""})
    bor.prune_index(idx, 5)
    ip = os.path.join(out, "index.json")
    vindex.save_index(idx, ip)
    back = vindex.load_index(ip)
    check("index 落盘往返一致",
          [e["version"] for e in back["versions"]] ==
          [e["version"] for e in idx["versions"]],
          [e["version"] for e in back["versions"]])
    check("channels.latest 已维护", back["channels"].get("latest") == ver,
          back["channels"])


def t_conventions(tmp):
    print("\n== 15) 产品口径与目录约定 ==")
    check("默认安装目录在 D 盘（硬性口径）",
          core.DEFAULT_DIR == r"D:\VideoToolbox", core.DEFAULT_DIR)
    # 版本号单一真相源：apply_version.py 覆盖不到在线模块里的硬编码，
    # SELF_VERSION 若滞留旧版，发布侧写 min_updater="2.0.0" 会把装 2.0.0
    # 的用户直接挡在门外（updater_ok 返回 False）——这类漂移静默且致命。
    src_ver = re.search(r'VERSION\s*=\s*"([\d.]+)"',
                        open(os.path.join(ROOT, "src", "video_toolbox_qt.py"),
                             encoding="utf-8").read()).group(1)
    check("SELF_VERSION 与源码 VERSION 一致",
          core.SELF_VERSION == src_ver,
          "SELF_VERSION=%s 源码=%s" % (core.SELF_VERSION, src_ver))
    check("下载 UA 含当前主次版本",
          "/%s.%s" % tuple(src_ver.split(".")[:2]) in vt_dl._UA,
          "%s vs 源码 %s" % (vt_dl._UA, src_ver))
    check("默认 manifest 指向固定 tag repo-latest",
          "/releases/download/repo-latest/manifest.json"
          in core.DEFAULT_MANIFEST_URL, core.DEFAULT_MANIFEST_URL)
    check("默认 index 指向固定 tag repo-latest",
          "/releases/download/repo-latest/index.json"
          in core.DEFAULT_INDEX_URL, core.DEFAULT_INDEX_URL)
    d = core.pick_default_dir()
    check("pick_default_dir 返回可用路径",
          isinstance(d, str) and d.endswith("VideoToolbox"), d)
    check("default_install_dir 返回字符串",
          isinstance(core.default_install_dir(), str))
    check("detect_install_dir 返回 str",
          isinstance(core.detect_install_dir(), str))
    check("app_running 返回 bool", isinstance(core.app_running(tmp), bool))
    check("空间检查：需要 1 字节时通过", core.free_space_ok(tmp, 1))
    check("空间检查：需要 1PB 时不通过",
          core.free_space_ok(tmp, 1 << 50) is False)
    check("create_shortcuts 空参数不炸",
          core.create_shortcuts(tmp, desktop=False, start_menu=False) == 0)


def t_cli_contract(tmp):
    print("\n== 16) CLI 契约（--check / --list-versions / --silent）==")
    rel = os.path.join(tmp, "relcli")
    os.makedirs(rel)
    man, _ = make_release(rel, "3.0.0", {"a.txt": b"A" * 1000})
    mfp = os.path.join(rel, "manifest.json")
    with open(mfp, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False)
    idx = vindex.new_index("视频工具箱", "file:///" + rel.replace("\\", "/"))
    vindex.upsert_version(idx, {"version": "3.0.0",
                                "manifest": "manifest.json",
                                "state": "stable", "min_updater": ""})
    vindex.upsert_version(idx, {"version": "2.0.0",
                                "manifest": "manifest.json",
                                "state": "stable", "min_updater": ""})
    idxp = os.path.join(rel, "index.json")
    vindex.save_index(idx, idxp)

    py = sys.executable
    setup_py = os.path.join(OREL, "vt_online_setup.py")

    def run_cli(*extra):
        return subprocess.run([py, setup_py, *extra],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)

    # 16a. --check：未安装 → 有更新（退出码 10）
    r = run_cli("--check", "--manifest", mfp, "--dir",
                os.path.join(tmp, "cli_i1"))
    check("--check 未安装时报有更新（rc=10）", r.returncode == 10,
          (r.returncode, (r.stdout or "")[-200:]))
    check("--check 输出 UPDATE-AVAILABLE",
          "UPDATE-AVAILABLE" in (r.stdout or ""), (r.stdout or "")[-200:])

    # 16b. --check：装到最新后 → 已最新（rc=0）
    tgt = os.path.join(tmp, "cli_i2")
    core.apply_update(man, tgt, os.path.join(tmp, "cli_c2"))
    r = run_cli("--check", "--manifest", mfp, "--dir", tgt)
    check("--check 已最新时 rc=0", r.returncode == 0,
          (r.returncode, (r.stdout or "")[-200:]))
    check("--check 输出 UP-TO-DATE", "UP-TO-DATE" in (r.stdout or ""))

    # 16c. --check：清单不可达 → rc=2
    r = run_cli("--check", "--manifest",
                os.path.join(tmp, "no_such_manifest.json"),
                "--dir", tgt)
    check("--check 失败时 rc=2", r.returncode == 2, r.returncode)

    # 16d. --list-versions：列出全版本目录
    r = run_cli("--list-versions", "--index", idxp)
    check("--list-versions rc=0", r.returncode == 0,
          (r.returncode, (r.stderr or "")[-200:]))
    check("--list-versions 输出含两个版本",
          "3.0.0" in (r.stdout or "") and "2.0.0" in (r.stdout or ""),
          (r.stdout or "")[-300:])

    # 16e. --silent 全流程（真装一次）
    tgt2 = os.path.join(tmp, "cli_i3")
    r = run_cli("--manifest", mfp, "--dir", tgt2, "--silent",
                "--no-shortcuts")
    check("--silent 安装 rc=0", r.returncode == 0,
          (r.returncode, (r.stdout or "")[-300:], (r.stderr or "")[-300:]))
    check("--silent 安装后文件到位",
          os.path.isfile(os.path.join(tgt2, "a.txt")))
    check("--silent 输出 OK 行", "OK v3.0.0" in (r.stdout or ""),
          (r.stdout or "")[-200:])


def main():
    print("=" * 66)
    print("  在线引导安装器 交叉验证（vt_dl / vt_update_core / vindex / CLI）")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="vt_xval_")
    try:
        t_dl_engine(tmp)
        t_dl_resume_cancel(tmp)
        t_dl_negative(tmp)
        t_dl_source_switch(tmp)
        t_dl_proxy_source(tmp)
        t_schema2_install(tmp)
        t_schema2_incremental(tmp)
        t_schema2_orphan(tmp)
        t_staging_rollback(tmp)
        t_verify_staging_negative(tmp)
        t_parts(tmp)
        t_updater(tmp)
        t_version_resolve(tmp)
        t_build_side(tmp)
        t_conventions(tmp)
        t_cli_contract(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    if FAILS:
        print("  结果：%d 项失败%s" % (len(FAILS),
              "，%d 项跳过" % len(_SKIPS) if _SKIPS else ""))
        for f in FAILS:
            print("   · " + f)
    else:
        print("  结果：全部通过%s" % ("（%d 项跳过）" % len(_SKIPS)
                                    if _SKIPS else ""))
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
