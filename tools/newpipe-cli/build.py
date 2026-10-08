# -*- coding: utf-8 -*-
"""
newpipe-cli 构建脚本（零构建工具依赖，只用 JDK 自带的 javac / jar）。

为什么不用 Gradle：services.gradle.org 在国内只有数 KB/s（131MB 分发包需数小时），
而本项目依赖总量不到 4MB，直接用 javac + jar 反而更快、可离线复现。

用法：
    python tools/newpipe-cli/build.py            # 下载依赖(若缺) + 编译 + 打 fat jar
    python tools/newpipe-cli/build.py --no-fetch # 只编译打包，不联网
    python tools/newpipe-cli/build.py --java <java_home>

产物：tools/newpipe-cli/dist/npe-cli.jar
运行时需求：任何 Java 17+ 的 java 可执行文件（编译产物 target=17）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(HERE, "libs")
SRC = os.path.join(HERE, "src", "main", "java")
BUILD = os.path.join(HERE, "build")
DIST = os.path.join(HERE, "dist")
JAR_NAME = "npe-cli.jar"

NPE_VERSION = "v0.26.5"
NANOJSON_SHA = "e9d656ddb49a412a5a0a5d5ef20ca7ef09549996"

MAVEN = "https://repo1.maven.org/maven2"
JITPACK = "https://jitpack.io"

#: (保存文件名, 下载 URL)
DEPENDENCIES = [
    ("NewPipeExtractor-%s.jar" % NPE_VERSION,
     "%s/com/github/TeamNewPipe/NewPipeExtractor/%s/NewPipeExtractor-%s.jar"
     % (JITPACK, NPE_VERSION, NPE_VERSION)),
    ("nanojson-%s.jar" % NANOJSON_SHA,
     "%s/com/github/TeamNewPipe/nanojson/%s/nanojson-%s.jar"
     % (JITPACK, NANOJSON_SHA, NANOJSON_SHA)),
    ("jsoup-1.22.2.jar", "%s/org/jsoup/jsoup/1.22.2/jsoup-1.22.2.jar" % MAVEN),
    ("jsr305-3.0.2.jar",
     "%s/com/google/code/findbugs/jsr305/3.0.2/jsr305-3.0.2.jar" % MAVEN),
    ("protobuf-javalite-4.35.1.jar",
     "%s/com/google/protobuf/protobuf-javalite/4.35.1/protobuf-javalite-4.35.1.jar" % MAVEN),
    ("rhino-1.8.1.jar", "%s/org/mozilla/rhino/1.8.1/rhino-1.8.1.jar" % MAVEN),
    ("rhino-engine-1.8.1.jar",
     "%s/org/mozilla/rhino-engine/1.8.1/rhino-engine-1.8.1.jar" % MAVEN),
    ("gson-2.11.0.jar",
     "%s/com/google/code/gson/gson/2.11.0/gson-2.11.0.jar" % MAVEN),
]


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_deps(force: bool = False) -> None:
    os.makedirs(LIBS, exist_ok=True)
    for name, url in DEPENDENCIES:
        path = os.path.join(LIBS, name)
        if os.path.isfile(path) and os.path.getsize(path) > 1024 and not force:
            continue
        log("[deps] %s" % name)
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                data = r.read()
            if len(data) < 1024:
                raise RuntimeError("响应过小(%d字节)，疑似失败页面" % len(data))
            with open(path, "wb") as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001
            log("[deps] 失败：%s（%s）" % (name, e))
            if os.path.isfile(path) and os.path.getsize(path) < 1024:
                os.remove(path)
            raise


def _decode(b: bytes) -> str:
    """javac / jar 在中文 Windows 上输出 GBK，直接按 utf-8 解码会炸。"""
    for enc in ("utf-8", "gbk", "cp936", "mbcs", "latin-1"):
        try:
            return b.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return b.decode("utf-8", "replace")


def _run(cmd: list) -> tuple:
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode, _decode(r.stdout or b""), _decode(r.stderr or b"")


def find_javac(java_home: str | None):
    """返回 (javac, jar) 可执行文件路径。"""
    cands = []
    if java_home:
        cands.append(java_home)
    if os.environ.get("JAVA_HOME"):
        cands.append(os.environ["JAVA_HOME"])
    cands += [
        r"C:\Users\LENOVO\devtools\jdk21\jdk-21.0.12+8",
        r"C:\Program Files\Java\jdk-26.0.1",
    ]
    for home in cands:
        for rel in (("bin", "javac.exe"), ("bin", "javac")):
            p = os.path.join(home, *rel)
            if os.path.isfile(p) or shutil.which(p):
                jarp = os.path.join(home, "bin",
                                    "jar.exe" if rel[1].endswith(".exe") else "jar")
                return p, jarp
    for n in ("javac", "javac.exe"):
        w = shutil.which(n)
        if w:
            return w, shutil.which("jar") or "jar"
    raise RuntimeError("找不到 javac，请用 --java 指定 JDK 根目录")


def build(java_home: str | None, no_fetch: bool) -> str:
    if not no_fetch:
        fetch_deps()

    javac, jar = find_javac(java_home)
    log("[javac] %s" % javac)

    classes = os.path.join(BUILD, "classes")
    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(classes, exist_ok=True)

    jars = [os.path.join(LIBS, n) for n, _ in DEPENDENCIES]
    missing = [j for j in jars if not os.path.isfile(j)]
    if missing:
        raise RuntimeError("缺少依赖 jar：%s" % ", ".join(missing))

    # 1) 编译
    srcs = []
    for root, _, files in os.walk(SRC):
        for fn in files:
            if fn.endswith(".java"):
                srcs.append(os.path.join(root, fn))
    if not srcs:
        raise RuntimeError("没有找到 Java 源文件：%s" % SRC)

    cp = os.pathsep.join(jars)
    cmd = [javac, "-encoding", "UTF-8", "--release", "17",
           "-nowarn", "-cp", cp, "-d", classes] + srcs
    rc, so, se = _run(cmd)
    if rc != 0:
        sys.stderr.write(so)
        sys.stderr.write(se)
        raise RuntimeError("javac 编译失败")
    log("[javac] 编译通过：%d 个源文件" % len(srcs))

    # 2) 把依赖解压进同一目录，打成单文件 fat jar
    for j in jars:
        with zipfile.ZipFile(j) as z:
            for info in z.infolist():
                n = info.filename
                # 跳过签名与模块描述，避免打包后 java 启动报错
                if n.startswith("META-INF/") and (
                        n.endswith(".SF") or n.endswith(".DSA")
                        or n.endswith(".RSA") or n.endswith(".MF")):
                    continue
                if n == "module-info.class" or n.endswith("/module-info.class"):
                    continue
                try:
                    z.extract(info, classes)
                except Exception:  # noqa: BLE001  # 同名文件冲突直接跳过
                    pass

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, JAR_NAME)
    if os.path.isfile(out):
        os.remove(out)
    cmd = [jar, "--create", "--file", out,
           "--main-class", "videotoolbox.npe.Main", "-C", classes, "."]
    rc, so, se = _run(cmd)
    if rc != 0:
        sys.stderr.write(so)
        sys.stderr.write(se)
        raise RuntimeError("jar 打包失败")

    size = os.path.getsize(out)
    log("[jar ] %s（%.1f MB）" % (out, size / 1048576.0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 newpipe-cli fat jar")
    ap.add_argument("--java", default=None, help="JDK 根目录（含 bin/javac）")
    ap.add_argument("--no-fetch", action="store_true", help="不联网，只用现有 libs/")
    ap.add_argument("--force-fetch", action="store_true", help="强制重新下载依赖")
    a = ap.parse_args()

    if a.force_fetch:
        fetch_deps(force=True)
    out = build(a.java, a.no_fetch)
    log("[done] %s" % out)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("[fail] %s\n" % e)
        sys.exit(1)
