# -*- coding: utf-8 -*-
# @version 2.4.1
"""P4 合规确证自检：NewPipe Extractor（GPL-3.0）的随包分发义务是否被完整履行。

为什么要有这个
--------------
NewPipe Extractor 是 **GPL-3.0** 且**随安装包分发二进制**（``tools\\
newpipe-cli\\dist\\npe-cli.jar``，4MB）。GPL-3.0 对「分发二进制」有硬性义务：
随包提供**许可全文** + 给出**对应源码获取途径**。这些义务不随代码改动自动
重新满足——任何一次改iss / 改声明 / 挪 jar 位置，都可能让合规悄悄失效。

因此把「义务是否被履行」做成**可复验的检查**，而不是写在文档里的一句话。

判定口径
--------
只检查**义务项**，不检查「该不该用这个组件」——用不用是产品决策（规格 P4），
这里是「既然用了，义务有没有做到」。

结构
----
正向：七项义务逐条确证。
负向：故意破坏（删声明条目 / 撤 iss 分发行）确认检查**确实能抓到**。

用法
----
    python scripts/dev/_selftest_npe_compliance.py

退出码 0 = 合规义务全部履行。
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

JAR = os.path.join(ROOT, "tools", "newpipe-cli", "dist", "npe-cli.jar")
ISS = os.path.join(ROOT, "packaging", "视频工具箱.iss")
DECL = os.path.join(ROOT, "docs", "第三方组件来源与许可声明.txt")
GPL = os.path.join(ROOT, "docs", "开源许可_GPL-3.0.txt")
MAIN_JAVA = os.path.join(ROOT, "tools", "newpipe-cli", "src", "main",
                         "java", "videotoolbox", "npe", "Main.java")
NPE_DL = os.path.join(ROOT, "tools", "newpipe-cli", "src", "main",
                      "java", "videotoolbox", "npe", "NpeDownloader.java")
PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable

#: 上游官方源码地址（GPL-3.0 的「对应源码」必须能拿到）
UPSTREAM = "github.com/TeamNewPipe/NewPipeExtractor"


def _read(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def positive():
    """七项义务逐条确证。"""
    fails = []

    def chk(name, cond, detail=""):
        if cond:
            print("OK   %s" % name)
        else:
            fails.append(name)
            print("FAIL %s  %s" % (name, detail))

    jar = os.path.isfile(JAR)
    chk("jar 存在（组件实际在用）", jar, JAR)
    if not jar:
        print("\nFAIL jar 不存在——组件未随包，本自检无意义")
        print("FAIL: 1")
        return False

    size_mb = os.path.getsize(JAR) / (1024.0 * 1024.0)
    print("     jar 体积：%.2f MB" % size_mb)

    iss = _read(ISS)
    decl = _read(DECL)

    # 义务 1：二进制随包分发（由 iss 的 Source 行落实）
    chk("iss 分发 jar", "npe-cli.jar" in iss,
        "iss 里找不到 npe-cli.jar 的 Source 行")
    chk("iss 指向正确的产物路径",
        "newpipe-cli" in iss and "npe-cli.jar" in iss)

    # 义务 2：许可全文随包（GPL-3.0 硬性义务）
    chk("GPL-3.0 全文文件存在", os.path.isfile(GPL), GPL)
    chk("iss 分发许可全文", "开源许可_GPL-3.0.txt" in iss)
    gpl_txt = _read(GPL)
    chk("许可全文非空", len(gpl_txt) > 10000, "%d 字符" % len(gpl_txt))
    chk("许可全文确为 GPL-3.0",
        "GNU GENERAL PUBLIC LICENSE" in gpl_txt
        and "Version 3" in gpl_txt)

    # 义务 3：声明文件登记该组件
    chk("声明登记了 NewPipe Extractor", "NewPipe Extractor" in decl)
    chk("声明标注许可为 GPL-3.0", "GPL-3.0" in decl)

    # 义务 4：给出对应源码获取途径
    chk("声明给出上游源码地址", UPSTREAM in decl,
        "缺 %s" % UPSTREAM)
    chk("声明给出源码压缩包地址", "archive/refs/heads" in decl)

    # 义务 5：声明与实际一致（发行包路径须指向真实存在的 jar）
    m = re.search(r"发行包\s*：([^\n]+)", decl)
    chk("声明写了发行包路径", bool(m), "声明里没有「发行包」行")
    if m:
        seg = m.group(1)
        chk("声明的发行包路径含实际文件名", "npe-cli.jar" in seg, seg.strip())
    chk("声明提到构建脚本随仓库分发",
        "build.py" in decl or "newpipe-cli" in decl)

    # 义务 6：交互方式为子进程调用（不静态链接进 exe）
    backend = _read(os.path.join(ROOT, "src", "npe_backend.py"))
    chk("Python 侧经子进程调用 jar", '"-jar"' in backend or "'-jar'" in backend)
    chk("自研封装 npe_backend.py 存在", bool(backend))

    # 义务 7：未修改上游源码（Java 侧只用公开 API）
    main_java = _read(MAIN_JAVA)
    dl_java = _read(NPE_DL)
    chk("Java 侧源码存在", bool(main_java) and bool(dl_java))
    chk("只用 org.schabi.newpipe.extractor 公开包",
        "org.schabi.newpipe.extractor" in main_java
        and not re.search(r"org\.schabi\.newpipe\.extractor\.[a-z_]+\.[a-z_]+\.",
                          main_java),
        "疑似用了 internal 子包")
    chk("Downloader 实现走标准扩展点（@Override execute）",
        "@Override" in dl_java and "execute(Request request)" in dl_java)
    chk("声明如实写了「未修改其源码」", "未修改其源码" in decl)

    print()
    print("FAIL: %d %s" % (len(fails), fails if fails else "合规义务全部履行"))
    return not fails


def negative():
    """故意破坏两项，确认检查能抓到。

    ① 从声明里删掉上游源码地址 —— 最容易被改坏的一项（重写文档时手滑）。
    ② 从 iss 里撤掉 jar 的 Source 行 —— 有人可能改打包范围时顺手删掉。
    """
    ok = True
    tmp = tempfile.mkdtemp(prefix="vt_npe_compl_")
    try:
        decl = _read(DECL)
        iss = _read(ISS)

        # ① 删源码地址
        if UPSTREAM not in decl:
            print("负向①：声明里本就找不到源码地址，跳过（不代表检查无效）")
            return False
        polluted = decl.replace(UPSTREAM, "github.com/example/placeholder")
        env = dict(os.environ)
        env["NPE_DECL_OVERRIDE"] = os.path.join(tmp, "decl.txt")
        with io.open(env["NPE_DECL_OVERRIDE"], "w", encoding="utf-8") as f:
            f.write(polluted)
        rc = _run_probe(env["NPE_DECL_OVERRIDE"], ISS)
        if rc == 3:
            print("OK   负向①：源码地址被抹掉后成功检出")
        else:
            print("FAIL 负向①：抹掉源码地址仍判合规 —— 检查形同虚设")
            ok = False

        # ② 撤 iss 分发行
        lines = [ln for ln in iss.splitlines(True)
                 if "npe-cli.jar" not in ln]
        stripped = "".join(lines)
        env2 = dict(os.environ)
        env2["NPE_ISS_OVERRIDE"] = os.path.join(tmp, "iss.iss")
        with io.open(env2["NPE_ISS_OVERRIDE"], "w", encoding="utf-8") as f:
            f.write(stripped)
        rc2 = _run_probe(DECL, env2["NPE_ISS_OVERRIDE"])
        if rc2 == 3:
            print("OK   负向②：iss 撤掉 jar 分发行后成功检出")
        else:
            print("FAIL 负向②：撤掉分发仍判合规 —— 检查形同虚设")
            ok = False
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


#: 注入点常量（供 _run_probe 覆盖用，避免真改仓库文件）
DECL_OVERRIDE = "NPE_DECL_OVERRIDE"
ISS_OVERRIDE = "NPE_ISS_OVERRIDE"

PROBE = r'''
import os, sys
HERE = %r
ROOT = %r
sys.path.insert(0, os.path.join(ROOT, "scripts", "dev"))
import _selftest_npe_compliance as M
if os.environ.get(M.DECL_OVERRIDE):
    M.DECL = os.environ[M.DECL_OVERRIDE]
if os.environ.get(M.ISS_OVERRIDE):
    M.ISS = os.environ[M.ISS_OVERRIDE]
sys.argv = ["probe"]
ok = M.positive()
sys.exit(0 if ok else 3)
'''


def _run_probe(decl_path, iss_path):
    env = dict(os.environ)
    env[DECL_OVERRIDE] = decl_path
    env[ISS_OVERRIDE] = iss_path
    env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "src")] +
        ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    code = PROBE % (HERE, ROOT)
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode


def main():
    print("=" * 62)
    print("P4 合规确证：NewPipe Extractor（GPL-3.0）随包分发义务")
    print("=" * 62)
    print("\n[1/2] 正向：七项义务逐条确证")
    ok1 = positive()
    print("\n[2/2] 负向校验（故意弄坏）")
    ok2 = negative()
    print("\n" + "=" * 62)
    allok = ok1 and ok2
    print("结论：", "PASS（合规义务完整履行）" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())