# -*- coding: utf-8 -*-
# @version 2.5.1
"""在线安装 · **全版本**链路离线自测（不发任何网络请求）。

针对「自研下载器」的三条设计目标逐条验证：
  · 全版本通用 —— index.json 定位任意版本；升 / 降 / 重装走同一套逻辑；
                   降级时目标版本不要的文件被识别为孤儿并安全清理。
  · 无体积上限 —— 资产按字节切卷（.001/.002…），下载后拼接还原，整体
                   sha256 与未切卷时完全一致。
  · 默认 D 盘  —— 默认目录挑选规则（D 盘优先，不可用时退让）。

外加下载引擎本身的可靠性：多线程分块、块级断点续传（取消 → 续跑）、
sha256 校验。

跑法：
    python scripts/dev/_selftest_online_versions.py
    python scripts/dev/_selftest_online_versions.py --keep   # 保留临时目录

⚠ **完全离线**：仓库是本地目录，资产走 `file://` 通道。vt_dl 对
   file:// 与 http(s) 走同一套分块 / 续传 / 校验代码，所以这能覆盖
   真实网络路径的全部逻辑分支。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "packaging", "online_release"))

import vt_dl  # noqa: E402
import vt_update_core as core  # noqa: E402
import vt_version_index as vindex  # noqa: E402

_OK = [0]
_FAIL = [0]


def chk(name, cond, extra=""):
    if cond:
        _OK[0] += 1
        print("  PASS  %s" % name)
    else:
        _FAIL[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def file_url(p):
    """Windows 路径 → file:/// URL。"""
    return "file:///" + str(p).replace("\\", "/")


# ------------------------------------------------------------------ 造仓库

#: 两个版本的文件布局。差异刻意覆盖各种情况：
#:   app.bin  两版内容都变      → 必下
#:   a.py     两版内容都变      → 必下
#:   b.py     两版完全相同      → 不该被重下（增量生效的证据）
#:   c.py     仅 1.20.0 有      → 降级时是**孤儿**
#:
#: ⚠ app.bin 必须是**不可压缩**的随机数据，而且得大于 1MB：
#:   · 用规律字节会被 zip 压到几十 KB，包就切不出卷，分卷用例形同虚设；
#:   · 小于 vt_dl.MIN_CHUNK(1MB) 时整个文件只有 1 块，取消/续传用例
#:     也无从触发（没有"还没下的块"可停）。
import random  # noqa: E402

_RND = random.Random(20261012)
BIG_1 = _RND.randbytes(2 * 1024 * 1024)
BIG_2 = _RND.randbytes(3 * 1024 * 1024)     # 长度也不同
COMMON = b"# common file, never changes\n"
A_1, A_2 = b"# a.py v1.19.0\n", b"# a.py v1.20.0\n"
C_2 = b"# c.py only in 1.20.0\n"

PKG_FILES = {
    "1.19.0": {"app": {"app.bin": BIG_1},
               "code": {"a.py": A_1, "b.py": COMMON}},
    "1.20.0": {"app": {"app.bin": BIG_2},
               "code": {"a.py": A_2, "b.py": COMMON, "c.py": C_2}},
}


def build_zip(path, members):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(members.items()):
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, data)
    return path


def write_asset(repo, name, data, volume_max):
    """写资产；超 volume_max 就按字节切卷（与发布侧同规则）。"""
    p = os.path.join(repo, name)
    with open(p, "wb") as fh:
        fh.write(data)
    asset = {"name": name.split("-")[-1].replace(".zip", ""),
             "file": name, "size": len(data), "sha256": sha(data),
             "entries": 0}
    if len(data) <= volume_max:
        return asset
    parts = []
    off, i = 0, 0
    while off < len(data):
        i += 1
        pn = "%s.%03d" % (name, i)
        with open(os.path.join(repo, pn), "wb") as fh:
            fh.write(data[off:off + volume_max])
        parts.append(pn)
        off += volume_max
    os.remove(p)
    asset["parts"] = parts
    asset["file"] = parts[0].replace(".001", "")
    return asset


def make_repo(root, volume_max):
    os.makedirs(root, exist_ok=True)
    base_url = file_url(root)
    idx = vindex.new_index("视频工具箱", base_url)
    for ver, pkgs in sorted(PKG_FILES.items()):
        assets, files = [], {}
        for pkg, members in pkgs.items():
            zname = "v%s-%s.zip" % (ver, pkg)
            build_zip(os.path.join(root, zname), members)
            with open(os.path.join(root, zname), "rb") as fh:
                data = fh.read()
            asset = write_asset(root, zname, data, volume_max)
            asset["entries"] = len(members)
            assets.append(asset)
            for rel, b in members.items():
                files[rel] = {"size": len(b), "sha256": sha(b), "pkg": pkg}
        mf = {"schema": 2, "app": "视频工具箱", "version": ver,
              "released": "2026-10-12 00:00:00", "base_url": base_url,
              "assets": assets, "files": files, "remove": [],
              "notes": "测试版本 %s" % ver}
        with open(os.path.join(root, vindex.MANIFEST_TEMPLATE % ver),
                  "w", encoding="utf-8") as fh:
            json.dump(mf, fh, ensure_ascii=False)
        vindex.upsert_version(idx, {
            "version": ver, "manifest": vindex.MANIFEST_TEMPLATE % ver,
            "released": mf["released"], "notes": mf["notes"],
            "state": "stable", "pkgs": [a["name"] for a in assets],
            "total_size": sum(a["size"] for a in assets)})
    vindex.save_index(idx, os.path.join(root, vindex.INDEX_NAME))
    # 最新别名（老客户端只认这个名字）
    shutil.copyfile(os.path.join(root, vindex.MANIFEST_TEMPLATE % "1.20.0"),
                    os.path.join(root, "manifest.json"))
    return root


# ------------------------------------------------------------------ 用例


def test_index(root):
    print("== 版本索引（离线仓库） ==")
    idx = vindex.load_index(os.path.join(root, vindex.INDEX_NAME))
    chk("索引含两版且降序",
        [e["version"] for e in idx["versions"]] == ["1.20.0", "1.19.0"],
        [e["version"] for e in idx["versions"]])
    chk("latest = 1.20.0", idx["channels"]["latest"] == "1.20.0")
    chk("stable = 1.20.0", idx["channels"]["stable"] == "1.20.0")
    chk("精确选 1.19.0",
        vindex.resolve(idx, "1.19.0")["version"] == "1.19.0")
    # ^1.19 = >=1.19.0 且 <2.0.0，两版都命中 → 取范围内**最高**的 1.20.0
    chk("^1.19 取范围内最高（1.20.0）",
        vindex.resolve(idx, "^1.19")["version"] == "1.20.0")
    # ~1.19 = >=1.19.0 且 <1.20.0，只命中 1.19.0
    chk("~1.19 只在 1.19.x 内选",
        vindex.resolve(idx, "~1.19")["version"] == "1.19.0")
    chk(">=1.20 取 1.20.0",
        vindex.resolve(idx, ">=1.20")["version"] == "1.20.0")
    chk("latest 走通道", vindex.resolve(idx)["version"] == "1.20.0")
    url = vindex.manifest_url(idx, vindex.resolve(idx, "1.19.0"))
    chk("manifest URL 指向本地 1.19.0",
        url.startswith("file:///") and url.endswith("manifest-1.19.0.json"),
        url)

    m, entry = core.resolve_manifest(
        want="1.19.0", index_url=os.path.join(root, vindex.INDEX_NAME))
    chk("resolve_manifest 取到 1.19.0", m["version"] == "1.19.0")
    chk("返回命中的版本记录", bool(entry) and entry["version"] == "1.19.0")
    m2, e2 = core.resolve_manifest(want="latest",
                                   manifest=os.path.join(root, "manifest.json"))
    chk("latest 走别名路径（不读索引）",
        m2["version"] == "1.20.0" and e2 is None)
    vers = core.list_versions(idx)
    chk("list_versions 返回两版", [v for v, _s, _n in vers]
        == ["1.20.0", "1.19.0"], vers)


def test_download_engine(root):
    print("== 下载引擎：分块 / 续传 / 校验 ==")
    src = os.path.join(root, "v1.20.0-app.zip.001")
    if not os.path.isfile(src):
        src = os.path.join(root, "v1.20.0-app.zip")
    dest = os.path.normpath(os.path.join(root, "..", "_dl_test.bin"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    want = sha(open(src, "rb").read())

    got = vt_dl.download_file(file_url(src), dest, expect_sha256=want,
                              threads=4)
    chk("多线程下载并校验通过", got == dest and os.path.isfile(dest))
    chk("内容 sha256 一致", vt_dl.sha256_file(dest) == want)

    os.remove(dest)

    # 断点续传：中途取消 → 保留 .dlpart/.dlstate → 重跑补完。
    # ⚠ 必须用**多块**的文件（> vt_dl.MIN_CHUNK = 1MB）：单卷只有 512KB，
    #   会退化成 1 块，块完成即文件完成，取消根本没机会生效。
    big = os.path.normpath(os.path.join(root, "..", "_big.bin"))
    with open(big, "wb") as fh:
        fh.write(_RND.randbytes(4 * 1024 * 1024))
    big_sha = sha(open(big, "rb").read())
    chk("续传用例文件确实是多块（>1MB）",
        len(vt_dl.plan_chunks(os.path.getsize(big), 1)) > 1,
        len(vt_dl.plan_chunks(os.path.getsize(big), 1)))

    cancel = threading.Event()

    def prog(done, total):
        # 第一块落地就取消。threads=1 让块串行执行：此时后面还有没下的
        # 块，work() 开头就会看到 cancel 并抛。并行的话其他块可能已经
        # 一并下完，就测不到"停在半路"了。
        cancel.set()

    try:
        vt_dl.download_file(file_url(big), dest, progress=prog,
                            cancel=cancel, threads=1)
        chk("取消应抛 Canceled", False)
    except vt_dl.Canceled:
        chk("取消应抛 Canceled", True)
    chk("取消后保留 .dlpart", os.path.isfile(dest + ".dlpart"))
    chk("取消后保留 .dlstate", os.path.isfile(dest + ".dlstate"))
    got = vt_dl.download_file(file_url(big), dest, expect_sha256=big_sha,
                              threads=4)
    chk("续传后补齐且校验通过",
        got == dest and vt_dl.sha256_file(dest) == big_sha)
    chk("完成后清理 .dlstate", not os.path.isfile(dest + ".dlstate"))
    os.remove(dest)
    os.remove(big)


def test_install_and_downgrade(root):
    print("== 安装 / 重复安装 / 降级 / 升级（同一套逻辑） ==")
    idx_url = os.path.join(root, vindex.INDEX_NAME)
    work = os.path.normpath(os.path.join(root, "..", "_work"))
    inst = os.path.normpath(os.path.join(root, "..", "_install"))
    for d in (work, inst):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    logs = []

    # ---- 1) 全新安装 1.20.0
    m, _ = core.resolve_manifest(want="1.20.0", index_url=idx_url,
                                 log=logs.append)
    res = core.apply_update(m, inst, work, log=logs.append)
    chk("装 1.20.0 成功（4 个文件）",
        res["version"] == "1.20.0" and res["files"] == 4, res)
    chk("1.20.0 独有的 c.py 已落地",
        os.path.isfile(os.path.join(inst, "c.py")))
    chk("a.py 是 1.20.0 内容",
        open(os.path.join(inst, "a.py"), "rb").read() == A_2)
    chk("app.bin 是 1.20.0 内容（且经分卷拼接还原）",
        open(os.path.join(inst, "app.bin"), "rb").read() == BIG_2)
    chk("已写 vt_installed.json",
        os.path.isfile(core.installed_path(inst)))

    # ---- 2) 再装一次：应零下载
    plan = core.plan_update(m, inst, log=logs.append)
    chk("重复安装无需下载",
        not plan["need"] and not plan["orphans"], plan)

    # ---- 3) 降级到 1.19.0（孤儿清理是关键）
    m19, _ = core.resolve_manifest(want="1.19.0", index_url=idx_url,
                                   log=logs.append)
    plan19 = core.plan_update(m19, inst, log=logs.append)
    chk("降级识别到孤儿 c.py",
        plan19["orphans"] == ["c.py"], plan19["orphans"])
    res19 = core.apply_update(m19, inst, work, log=logs.append)
    chk("降级执行成功", res19["version"] == "1.19.0", res19)
    chk("孤儿 c.py 已清理",
        not os.path.exists(os.path.join(inst, "c.py")))
    chk("a.py 回到 1.19.0 内容",
        open(os.path.join(inst, "a.py"), "rb").read() == A_1)
    chk("app.bin 回到 1.19.0 内容",
        open(os.path.join(inst, "app.bin"), "rb").read() == BIG_1)
    chk("b.py 仍在且未变",
        open(os.path.join(inst, "b.py"), "rb").read() == COMMON)

    # ---- 4) 升回去：b.py 不该算变动（增量生效的证据）
    plan20 = core.plan_update(m, inst, log=logs.append)
    chk("升回去时 b.py 不算变动",
        "b.py" not in plan20["changed"], plan20["changed"])
    chk("升回去时无孤儿", not plan20["orphans"])
    res20 = core.apply_update(m, inst, work, log=logs.append)
    chk("升回 1.20.0 成功", res20["version"] == "1.20.0")
    chk("c.py 又回来了", os.path.isfile(os.path.join(inst, "c.py")))

    # ---- 5) 用户改过的文件不能被当孤儿删掉
    with open(os.path.join(inst, "c.py"), "wb") as fh:
        fh.write("# 我改过的内容\n".encode("utf-8"))
    chk("改过的 c.py 不被清理",
        core.plan_update(m19, inst, log=logs.append)["orphans"] == [])

    # ---- 6) 没有 installed.json 时不敢乱删（首次装到已有目录）
    os.remove(core.installed_path(inst))
    chk("无本地清单时不算孤儿",
        core.plan_update(m19, inst, log=logs.append)["orphans"] == [])


def test_volumes(root, volume_max):
    print("== 分卷（无单文件体积上限） ==")
    m = core.load_manifest(os.path.join(root,
                                        vindex.MANIFEST_TEMPLATE % "1.20.0"))
    app = [a for a in m["assets"] if a["name"] == "app"][0]
    parts = app.get("parts") or []
    chk("app 包已切成多卷（volume_max=%s）" % volume_max, len(parts) > 1,
        parts)
    for p in parts:
        chk("卷 %s 存在" % p, os.path.isfile(os.path.join(root, p)))
    chk("每卷不超过上限",
        all(os.path.getsize(os.path.join(root, p)) <= volume_max
            for p in parts))

    work = os.path.normpath(os.path.join(root, "..", "_work_vol"))
    os.makedirs(work, exist_ok=True)
    dest = os.path.join(work, app["file"])
    got = core.download_asset(m, app, dest, log=lambda s: None)
    chk("分卷下载 + 拼接落盘", got == dest and os.path.isfile(dest))
    chk("拼接还原 sha256 与未切卷一致",
        core.sha256_file(dest) == app["sha256"],
        "%s… vs %s…" % (core.sha256_file(dest)[:12], app["sha256"][:12]))
    chk("拼接后大小与清单一致",
        os.path.getsize(dest) == app["size"])
    shutil.rmtree(work, ignore_errors=True)


def test_default_dir():
    print("== 默认安装目录（D 盘优先） ==")
    chk("DEFAULT_DIR 在 D 盘",
        core.DEFAULT_DIR.upper().startswith("D:"), core.DEFAULT_DIR)
    picked = core.pick_default_dir()
    chk("pick_default_dir 首选 D 盘", picked.upper().startswith("D:"), picked)
    chk("default_install_dir 优先既定默认",
        core.default_install_dir().upper().startswith("D:"),
        core.default_install_dir())
    got = core.pick_default_dir(drives=("Z:", "Q:"))
    chk("D 盘不可用时仍有兜底路径（非 D 盘）",
        bool(got) and not got.upper().startswith("D:"), got)


# ------------------------------------------------------------------ 主流程


def main(argv=None):
    ap = argparse.ArgumentParser(description="在线安装全版本链路离线自测")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    ap.add_argument("--volume-max", type=int, default=1 << 19,
                    help="造仓库时的单卷上限（默认 512KB，逼出分卷）")
    args = ap.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="vt_ver_selftest_")
    repo = os.path.join(tmp, "repo")
    print("临时仓库：%s\n" % repo)
    make_repo(repo, args.volume_max)

    try:
        test_index(repo)
        test_download_engine(repo)
        test_install_and_downgrade(repo)
        test_volumes(repo, args.volume_max)
        test_default_dir()
    finally:
        if args.keep:
            print("\n（--keep：保留 %s）" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n== 结果：PASS %d / FAIL %d ==" % (_OK[0], _FAIL[0]))
    return 1 if _FAIL[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
