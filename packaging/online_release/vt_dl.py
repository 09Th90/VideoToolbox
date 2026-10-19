# -*- coding: utf-8 -*-
# @version 2.4.1
"""视频工具箱 · 自研下载引擎（无第三方依赖，可被打进引导安装器单独分发）。

====================================================================
定位
====================================================================
本模块只做一件事：**把一个 URL 可靠地下载到本地文件**。可靠性来自五层设计：

  1. **多线程分块**：HTTP Range 并行下载（默认 8 线程），单文件不再是
     单连接串行——大文件吃满带宽，小文件也不亏（块大 4MB 起）。
  2. **块级断点续传**：下载写 `<dest>.dlpart`，进度写 `<dest>.dlstate`
     （JSON：文件总长 + 每块完成标记）。中断后重跑只补缺失的块，
     不是从头再来。完成时整体 sha256 校验，过卷即重下该文件。
  3. **镜像回退链**：直连 → gh-proxy.com 直连镜像（仅 GitHub URL，
     在线安装形态的生命线）→ 本地代理 7897（用户 clash / 已运行的
     mihomo）。探测阶段就排序，下载中按块自动轮换。
  4. **取消**：`cancel` 事件置位后，正在写的块会在 256KB 边界内停手，
     已完成的块与状态文件保留，下次可续。
  5. **通道无关**：`http(s)://` 与 `file://` 走同一套分块逻辑——
     离线自测可以用本地文件验证「多线程 + 续传 + 分块」全部代码路径。

为什么不用 requests/aiohttp：引导安装器要打成 ~12MB 的单文件 exe，
每多一个第三方库都是用户下载成本；且本模块逻辑必须能被
`_selftest_online_setup.py` 在**无网络**环境下完整单测。

====================================================================
与「体积限制」的关系（设计目标）
====================================================================
· **单文件无上限**：本引擎对文件大小没有内在限制（zip64 规范 16EB）；
  发布侧再把超限资产按字节切卷（见 vt_update_core 的 parts 处理），
  每卷仍是本引擎的一个普通下载任务。
· **总量无上限**：调用方按 manifest diff 只下变化的包，本引擎不关心
  总量，也不需要一次性占两倍空间之外的额外缓冲。
"""

import hashlib
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

#: 默认并行线程数。8 是实测甜点：再高对 GitHub CDN 收益递减，且
#: 线程池排队会让进度回调变毛刺。
DEFAULT_THREADS = 8
#: 单块下限。太小则每块固定开销（建连、重定向）占比上升。
MIN_CHUNK = 1 << 20
#: 单块上限。太大则尾块不均、取消时的浪费变多。
MAX_CHUNK = 64 << 20
#: 读取粒度：取消标志在这个边界内生效（同时也是进度回调的节流基础）。
READ_BLOCK = 256 << 10
#: 目标块数 ≈ 线程数 × 该倍数。块多一些，负载均衡更细。
CHUNKS_PER_THREAD = 16
#: 连接/读取超时（秒）。镜像站 23KB/s 时 256KB 块约 11s，120s 足够宽裕。
HTTP_TIMEOUT = 120
#: 探测超时（秒）。探测只求「活着吗 + 多大」，不值得等满 HTTP_TIMEOUT：
#   网络黑洞时每源 120s、三源两轮 = 数分钟无响应（2026-10-13 审查修复）。
PROBE_TIMEOUT = 15
#: 探测总时限（秒）：探到可用源就收手，别把整条链都拖完。
PROBE_DEADLINE = 45
#: 本地代理端口（clash / 已运行的 mihomo）。命中即作为最后一个源。
LOCAL_PROXY_PORT = 7897
#: 整体 sha256 不符时的整文件重下次数（续传状态里的坏块只能这样救）。
RESHUFFLE_TRIES = 1

_UA = "VideoToolbox-downloader/2.4.1"


class Canceled(Exception):
    """用户/调用方取消。已下载的块与状态文件保留，可续传。"""


class DlError(RuntimeError):
    """可预期的下载失败（网络、校验、磁盘…），UI 直接显示其文本。"""


# ------------------------------------------------------------------ 工具


def human(n):
    """字节数转人类可读。"""
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return "%.1f %s" % (n, u)
        n /= 1024


def sha256_file(path, progress=None):
    """算文件 sha256；progress 为 (已读, 总数) 回调（可为 None）。"""
    total = os.path.getsize(path)
    h = hashlib.sha256()
    done = 0
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done, total)
    return h.hexdigest()


def port_listening(port, host="127.0.0.1", timeout=0.3):
    """本地端口是否有进程在 listen（探测 clash/mihomo 是否在跑）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ 数据源


class Source:
    """一个可尝试的下载源：标签 + 实际 URL + opener。

    opener 决定「走不走代理」：直连与镜像是 ProxyHandler({})（显式不走），
    代理源是 ProxyHandler({'http': …, 'https': …})。
    """

    __slots__ = ("label", "url", "opener")

    def __init__(self, label, url, opener):
        self.label = label
        self.url = url
        self.opener = opener

    def __repr__(self):  # pragma: no cover - 调试用
        return "Source(%s, %s)" % (self.label, self.url[:60])


def _direct_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _proxy_opener(proxy):
    return urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy}))


def _src_open(src, req, timeout=HTTP_TIMEOUT):
    """用下载源自带的 opener 发请求。

    Source.opener 决定「走不走代理」：直连与镜像是显式
    ProxyHandler({})（绕过进程环境变量里的代理），代理源指向
    127.0.0.1:7897。**必须走 src.opener**——裸 urlopen 用的是
    进程级默认 opener，环境里没代理时全部请求都直连，「本地代理」
    这个源就名存实亡（探测成功、数据请求全直连）。
    opener 为 None（file:// 源不会走到这；外部手搓的 Source）时
    退化到 urllib 默认 opener，行为与接线前一致。
    """
    op = getattr(src, "opener", None)
    if op is None:
        return urllib.request.urlopen(req, timeout=timeout)
    return op.open(req, timeout=timeout)


def is_github_url(url):
    """是否 GitHub 系 URL（决定要不要给它套 gh-proxy 镜像前缀）。

    ⚠ 必须按 **host** 判，不能子串包含：`https://example.com/github.com/x`
    里确实含 `github.com/`，但它根本不是 GitHub——给它套镜像前缀等于把
    本不该经过镜像站的请求送出去（对方站点收到一个莫名其妙的 path，
    镜像站也白挨一次）。按 host 判则 `raw.githubusercontent.com` 这类
    子域照样能命中。
    """
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001 —— 畸形 URL 一律按非 GitHub 处理
        return False
    if not host:
        return False
    return (host == "github.com" or host.endswith(".github.com")
            or host == "githubusercontent.com"
            or host.endswith(".githubusercontent.com"))


def source_chain(url, log=None, allow_proxy=True):
    """为 url 生成下载源链（按优先级排好）。

    顺序（与 tools/download_open_source_deps.py 的既有口径一致）：
      1. 直连
      2. gh-proxy.com 前缀镜像（**仅**含 github.com/ 的 URL；
         在线安装形态不随包分发 mihomo，镜像是第一道兜底）
      3. 本地代理 127.0.0.1:7897（用户在跑 clash 或 mihomo 时命中）

    file:// 直接返回单源，不套镜像（镜像只对 HTTP 有意义）。
    """
    def say(msg):
        if log:
            log(msg)

    if url.startswith("file://"):
        return [Source("本地文件", url, None)]

    direct = _direct_opener()
    chain = [Source("直连", url, direct)]
    if is_github_url(url):
        chain.append(Source("gh-proxy 镜像", "https://gh-proxy.com/" + url,
                            direct))
    if allow_proxy and port_listening(LOCAL_PROXY_PORT):
        chain.append(Source("本地代理 :%d" % LOCAL_PROXY_PORT, url,
                            _proxy_opener("http://127.0.0.1:%d" % LOCAL_PROXY_PORT)))
        say("检测到本地代理 :%d，已加入下载源链" % LOCAL_PROXY_PORT)
    return chain


# ------------------------------------------------------------------ 探测


class Probe:
    """探测结果：文件总长 + 该源是否支持 Range。"""

    __slots__ = ("size", "ranged", "err")

    def __init__(self, size, ranged, err=None):
        self.size = size
        self.ranged = ranged
        self.err = err


def probe_source(src, cancel=None):
    """探测单个源：拿 size 与 Range 支持情况。不抛异常，失败写进 .err。

    `cancel` 置位时立刻返回带 err 的 Probe——探测阶段没有取消点的话，
    网络黑洞时每个源各挂 HTTP_TIMEOUT（120s），取消按钮会假死数分钟
    （2026-10-13 审查修复）。
    """
    if cancel is not None and cancel.is_set():
        return Probe(0, False, "已取消")
    if src.url.startswith("file://"):
        try:
            p = urllib.request.url2pathname(
                urllib.parse.urlparse(src.url).path)
            return Probe(os.path.getsize(p), True)
        except OSError as e:
            return Probe(0, False, str(e))

    # 要 0-0 两个字节：206 → 支持 Range 且拿到总长；200 → 不支持 Range。
    req = urllib.request.Request(src.url, headers={
        "User-Agent": _UA, "Range": "bytes=0-0"})
    try:
        with _src_open(src, req, timeout=PROBE_TIMEOUT) as r:
            status = getattr(r, "status", 200)
            cr = r.headers.get("Content-Range")
            if status == 206 and cr:
                total = cr.split("/")[-1]
                if total.isdigit():
                    return Probe(int(total), True)
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit():
                # 不支持 Range 的单源也能下（退化成整文件流）。
                return Probe(int(cl), False)
            return Probe(0, False, "既无 Content-Range 也无 Content-Length")
    except urllib.error.HTTPError as e:
        # 416 等：多半是不认 0-0，换 0-99 再试一次再判死刑
        if e.code == 416:
            req2 = urllib.request.Request(src.url, headers={
                "User-Agent": _UA, "Range": "bytes=0-99"})
            try:
                with _src_open(src, req2, timeout=PROBE_TIMEOUT) as r:
                    cl = r.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        return Probe(int(cl), False)
            except Exception:  # noqa: BLE001
                pass
        return Probe(0, False, "HTTP %s" % e.code)
    except Exception as e:  # noqa: BLE001
        return Probe(0, False, repr(e)[:120])


# ------------------------------------------------------------------ 分块计划


def plan_chunks(size, threads=DEFAULT_THREADS):
    """把 [0, size) 切成块列表 [(start, end_exclusive)]。

    块数 ≈ threads × 16，块长夹在 [MIN_CHUNK, MAX_CHUNK]。
    文件小于 MIN_CHUNK 时单块。空文件返回空列表。
    """
    if size <= 0:
        return []
    n = max(1, threads * CHUNKS_PER_THREAD)
    csize = -(-size // n)  # 向上取整
    csize = max(MIN_CHUNK, min(MAX_CHUNK, csize))
    out = []
    start = 0
    while start < size:
        out.append((start, min(start + csize, size)))
        start += csize
    return out


# ------------------------------------------------------------------ 状态文件


class DlState:
    """断点续传状态：`<dest>.dlstate`。

    记录总长、**分块几何**（csize/nchunks）与已完成的块下标。几何必须
    一起记：换 threads 参数、或升级引擎改了分块常量，都会让 done 下标
    指向别的字节区间——不校验几何就续传，拼出来的是带洞的文件，
    而 .dlpart 是预分配全长的，大小校验看不出来（静默损坏）。
    故意**不记每块哈希**——服务端没有分块校验值可对，记了也是假的；
    真正的正确性保证是完成时的整体 sha256（不符则整文件重下，
    见 download_file 的 RESHUFFLE_TRIES）。
    """

    def __init__(self, path, size, csize=0, nchunks=0):
        self.path = path
        self.size = size
        self.csize = csize
        self.nchunks = nchunks
        self.done = {}          # chunk_idx -> True
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path, size, csize=0, nchunks=0):
        st = cls(path, size, csize, nchunks)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            if int(d.get("size", -1)) != size:
                return st        # 长度变了，旧状态作废（done 为空）
            if (int(d.get("csize", -1)) != int(csize)
                    or int(d.get("nchunks", -1)) != int(nchunks)):
                return st        # 分块几何变了，done 下标全部错位，作废
            for k in d.get("done", []):
                st.done[int(k)] = True
        except Exception:  # noqa: BLE001 —— 损坏/不存在都从头下
            pass
        return st

    def mark(self, idx):
        with self._lock:
            self.done[idx] = True

    def missing(self, chunks):
        return [i for i in range(len(chunks)) if i not in self.done]

    def save(self):
        tmp = self.path + ".tmp"
        with self._lock:
            data = {"size": self.size, "csize": self.csize,
                    "nchunks": self.nchunks, "done": sorted(self.done)}
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def drop(self):
        for p in (self.path, self.path + ".tmp"):
            try:
                os.remove(p)
            except OSError:
                pass


# ------------------------------------------------------------------ 核心下载


def _read_range(src, start, end, cancel):
    """从 src 读 [start, end) 字节，返回 bytes。取消/失败抛异常。

    file:// 通道直接 seek+read；HTTP 通道带 Range 头，并对 200（服务端
    无视 Range）做降级判断——只有「要的就是整个文件」时才收下。
    """
    if src.url.startswith("file://"):
        if cancel is not None and cancel.is_set():
            raise Canceled()
        p = urllib.request.url2pathname(urllib.parse.urlparse(src.url).path)
        with open(p, "rb") as fh:
            fh.seek(start)
            return fh.read(end - start)

    req = urllib.request.Request(src.url, headers={
        "User-Agent": _UA, "Range": "bytes=%d-%d" % (start, end - 1)})
    with _src_open(src, req) as r:
        status = getattr(r, "status", 200)
        want = end - start
        if status != 206:
            if start == 0:
                # 服务端无视 Range 返回整个身体：仅当只要整文件时可用
                data = r.read()
                if len(data) == want:
                    return data
            raise DlError("源 %s 不支持 Range（HTTP %s）" % (src.label, status))
        parts = []
        got = 0
        while got < want:
            if cancel is not None and cancel.is_set():
                raise Canceled()
            b = r.read(min(READ_BLOCK, want - got))
            if not b:
                raise DlError("源 %s 数据流意外中断（%d/%d）"
                              % (src.label, got, want))
            parts.append(b)
            got += len(b)
        return b"".join(parts)


def _probe_best(chain, log, cancel=None):
    """按优先级探测源链，返回 ([(源, 是否支持 Range)], 总长)。

    探测失败的源直接剔除；全部失败抛 DlError（带各源失败原因）。
    同一文件在多个源上长度不一致时，弃掉长度不对的那个。
    `cancel` 置位即抛 Canceled；已有可用源后不再拖过总时限。
    """
    def say(msg):
        if log:
            log(msg)

    ok, size = [], 0
    why = []
    deadline = time.time() + PROBE_DEADLINE
    for src in chain:
        if cancel is not None and cancel.is_set():
            raise Canceled()
        pr = probe_source(src, cancel)
        if pr.err:
            why.append("%s：%s" % (src.label, pr.err))
            continue
        if not ok:
            size = pr.size
        if pr.size != size and ok:
            # 同一条链上出现两种长度，说明某个源给错了，弃之
            why.append("%s：长度不符（%d ≠ %d）" % (src.label, pr.size, size))
            continue
        ok.append((src, pr.ranged))
        if time.time() > deadline:
            # 已有可用源就别再耗：剩下的源留给换源重试时再探
            break
    if not ok:
        raise DlError("所有下载源均不可用：\n  " + "\n  ".join(why))
    if size <= 0:
        raise DlError("远端文件长度为 0（源：%s）" % ok[0][0].label)
    say("下载源就绪：%s（%s）"
        % (" → ".join("%s%s" % (s.label, "" if r else "·无Range")
                      for s, r in ok), human(size)))
    return ok, size


def download_file(url, dest, progress=None, log=None, cancel=None,
                  threads=DEFAULT_THREADS, expect_sha256=None,
                  stats=None, allow_proxy=True):
    """把 url 下载到 dest。成功返回 dest；失败抛 DlError/Canceled。

    参数：
        progress   (done, total) 回调，UI 线程外调用，约 5 次/秒节流。
        log        文本日志回调。
        cancel     threading.Event；置位 → 抛 Canceled，保留续传状态。
        expect_sha256  期望的整体 sha256；不符则整文件重下后仍不符才报错。
        stats      可选 dict，引擎实时写入 {"speed": B/s, "source": 标签}。
    副作用：
        · 下载中：`<dest>.dlpart`（数据）+ `<dest>.dlstate`（进度）
        · 成功后：dest 就位，两个临时文件删除
        · 取消后：两个临时文件保留（供续传）
    """
    if stats is None:
        stats = {}
    stats.setdefault("speed", 0.0)
    stats.setdefault("source", "")

    def say(msg):
        if log:
            log(msg)

    chain = source_chain(url, log=log, allow_proxy=allow_proxy)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)

    for round_no in range(RESHUFFLE_TRIES + 1):
        probed, size = _probe_best(chain, log, cancel)
        ranged = [(s, r) for s, r in probed if r]
        if not ranged:
            # 没有任何源支持 Range：退化成单连接整文件流（仍走源链择优）
            say("下载源均不支持 Range，改用单连接通道")
            return download_simple(probed[0][0].url, dest, progress=progress,
                                   log=log, cancel=cancel,
                                   expect_sha256=expect_sha256,
                                   opener=probed[0][0].opener)
        srcs = [s for s, _r in ranged]

        # 换源游标：整文件级。某源连续失败就把游标推给下一个。
        cur = {"i": 0}
        cur_lock = threading.Lock()

        def pick_source():
            with cur_lock:
                return srcs[min(cur["i"], len(srcs) - 1)]

        def bump_source(reason):
            with cur_lock:
                if cur["i"] < len(srcs) - 1:
                    cur["i"] += 1
                    nxt = srcs[cur["i"]].label
                else:
                    nxt = None
            if nxt:
                say("切换到下载源：%s（%s）" % (nxt, reason))
                stats["source"] = nxt
            return nxt

        chunks = plan_chunks(size, threads)
        part = dest + ".dlpart"
        state_path = dest + ".dlstate"
        # 分块几何随状态一起落盘：续跑时几何对不上（调用方换了 threads、
        # 或升级引擎改了分块常量）宁可整文件重下，也不能按错位的下标
        # 拼出带洞的文件——.dlpart 预分配全长，大小校验看不出来。
        csize = (chunks[0][1] - chunks[0][0]) if chunks else 0
        state = DlState.load(state_path, size, csize, len(chunks))

        if round_no == 0 and os.path.isfile(part):
            have = os.path.getsize(part)
            if have != size:
                say("发现不完整的续传文件（%s/%s），截断重对齐"
                    % (human(have), human(size)))
                with open(part, "r+b") as fh:
                    fh.truncate(size)
        if not os.path.isfile(part):
            with open(part, "wb") as fh:
                if size:
                    fh.truncate(size)

        missing = state.missing(chunks)
        if missing:
            say("开始下载：%s，%d/%d 块待传"
                % (human(size), len(missing), len(chunks)))
        else:
            say("续传文件已完整，直接校验")

        # 进度：完成字节数 + 节流回调 + 速度估计
        # ⚠ 续传时把已完成的字节预填进来：done_bytes 从 0 起算会让
        # 90% 已下的文件在 UI 上从 0% 重新爬，速度统计同样失真
        # （2026-10-13 审查修复）。
        done_bytes = [sum(chunks[i][1] - chunks[i][0]
                          for i in state.done if i < len(chunks))]
        prog_lock = threading.Lock()
        last_cb = [0.0]
        speed_win = []          # [(t, done_bytes)]

        def add_done(n):
            with prog_lock:
                done_bytes[0] += n
                speed_win.append((time.time(), done_bytes[0]))
                del speed_win[:-8]
                now = time.time()
                if now - last_cb[0] >= 0.2:
                    last_cb[0] = now
                    if progress:
                        progress(done_bytes[0], size)
                    if len(speed_win) >= 2:
                        dt = speed_win[-1][0] - speed_win[0][0]
                        if dt > 0.05:
                            stats["speed"] = ((speed_win[-1][1] - speed_win[0][1])
                                              / dt)

        fail = {"err": None}

        def work(idx):
            s, e = chunks[idx]
            n = e - s
            tries = 0          # 当前源上已失败次数（换源后重置）
            while True:
                if cancel is not None and cancel.is_set():
                    raise Canceled()
                src = pick_source()
                try:
                    data = _read_range(src, s, e, cancel)
                    if len(data) != n:
                        raise DlError("块 %d 长度不符（%d/%d）"
                                      % (idx, len(data), n))
                    with open(part, "r+b") as fh:
                        fh.seek(s)
                        fh.write(data)
                    state.mark(idx)
                    add_done(n)
                    return
                except Canceled:
                    raise
                except Exception as ex:  # noqa: BLE001
                    tries += 1
                    if tries >= 3:
                        # 同源三次不过：换源再给三次；无源可换才记失败。
                        # ⚠ 曾经的 bug：`for attempt in range(3)` 写法在
                        # 最后一次 attempt 触发换源后循环即结束，该块被
                        # 静默跳过，靠最终 sha256 不符→整文件重下自愈，
                        # 白浪费一轮全量下载。
                        if bump_source(repr(ex)[:80]) is None:
                            # 必须包成 DlError：原始异常（HTTPError /
                            # URLError / timeout…）调用方一律 catch 不到，
                            # 会以裸 traceback 崩掉安装器；包一层还能落进
                            # 下面的 except DlError → 整文件重下分支。
                            fail["err"] = DlError(
                                "所有下载源均失败：%s" % repr(ex)[:200])
                            return
                        tries = 0
                    else:
                        time.sleep(0.5 * tries)

        try:
            if missing:
                with ThreadPoolExecutor(max_workers=threads) as pool:
                    for f in [pool.submit(work, i) for i in missing]:
                        f.result()
            if fail["err"] is not None:
                raise fail["err"]
            # 收尾：进度归位、整体校验
            if progress:
                progress(size, size)
            stats["speed"] = 0.0
            if os.path.getsize(part) != size:
                raise DlError("下载后文件大小不符：%d ≠ %d"
                              % (os.path.getsize(part), size))
            say("下载完成，正在校验 sha256 …")
            try:
                got = sha256_file(part)
            except OSError as e:
                raise DlError("读取已下载数据失败：%s" % e)
            if expect_sha256 and got != expect_sha256:
                raise DlError("sha256 校验不通过：\n  期望 %s\n  实际 %s"
                              % (expect_sha256, got))
            # 磁盘满/路径过长等 OSError 一律包成 DlError：docstring 承诺
            # 调用方只需处理 DlError/Canceled（2026-10-13 审查修复）
            try:
                os.replace(part, dest)
            except OSError as e:
                state.drop()
                _quiet_remove(part)
                raise DlError("下载文件落地失败：%s" % e)
            state.drop()
            stats["source"] = srcs[0].label
            return dest
        except Canceled:
            state.save()
            stats["speed"] = 0.0
            say("已取消（进度已保留，可续传）")
            raise
        except DlError:
            stats["speed"] = 0.0
            if round_no < RESHUFFLE_TRIES:
                say("本轮失败，清空续传状态后重下整文件")
                state.drop()
                continue
            # 末轮仍失败：绝不能把「done=全部块」的假状态写回盘——
            # 下次运行会打印"续传文件已完整，直接校验"，白跑一遍整体
            # sha256 才失败。连 .dlpart 一起清掉，失败即无残留
            # （2026-10-13 审查修复）。
            state.drop()
            _quiet_remove(part)
            raise


def download_simple(url, dest, progress=None, log=None, cancel=None,
                    expect_sha256=None, opener=None):
    """单连接整文件下载（服务端不支持 Range 时的退化通道）。

    仍然先写 .part 再改名；不提供块级续传（没有 Range 就无从续起）。
    opener 为 None 时用 urllib 默认 opener（环境代理语义，兼容旧调用）。
    """
    def say(msg):
        if log:
            log(msg)

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    op = opener or urllib.request.build_opener()
    try:
        with op.open(req, timeout=HTTP_TIMEOUT) as r:
            total = int(r.headers.get("Content-Length") or 0) or -1
            done = 0
            with open(tmp, "wb") as fh:
                while True:
                    if cancel is not None and cancel.is_set():
                        _quiet_remove(tmp)
                        raise Canceled()
                    b = r.read(READ_BLOCK)
                    if not b:
                        break
                    fh.write(b)
                    done += len(b)
                    if progress:
                        progress(done, total)
    except Canceled:
        raise
    except Exception as e:  # noqa: BLE001
        _quiet_remove(tmp)
        raise DlError("下载失败：%s\n（%s）" % (e, url))
    if expect_sha256:
        got = sha256_file(tmp)
        if got != expect_sha256:
            _quiet_remove(tmp)
            raise DlError("sha256 校验不通过：\n  期望 %s\n  实际 %s"
                          % (expect_sha256, got))
    os.replace(tmp, dest)
    return dest


def _quiet_remove(p):
    try:
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass
