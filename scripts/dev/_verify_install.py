# -*- coding: utf-8 -*-
# @version 2.5.4
"""安装包实测验证：把离线安装器装到暂存目录，逐项核对「源码 → 安装产物」闭环。

用法：
  tools\\python\\python.exe scripts\\dev\\_verify_install.py <安装目录> [安装器exe]

没有第二参数时跳过安装步骤，只校验已存在的安装目录（可重复跑）。

校验项
------
1. 主程序 exe：字节级 md5/size 与 dist\\视频工具箱.exe 全等（证明装的是刚构建的版本）
2. src 模块闭包：AST 传递闭包里每个自研模块都在 {app}\\src 下（与
   check_iss_sources.py 同一套闭包，互为镜像）
3. src\\ 方式运行导入冒烟：用**安装目录自带**的 tools\\python 跑
   `import video_toolbox_qt` 等，验证安装版能按开发版说明书的脚本方式启动
4. docs / 许可等静态资产在位
"""
import ast
import hashlib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJ_SRC = os.path.join(ROOT, "src")
PROJ_DIST = os.path.join(ROOT, "dist", "视频工具箱.exe")


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def closure():
    """src 下自研模块的传递闭包（与 check_iss_sources.py 同源）。"""
    srcmods = {f[:-3] for f in os.listdir(PROJ_SRC) if f.endswith(".py")}

    def imports_of(mod):
        tree = ast.parse(open(os.path.join(PROJ_SRC, mod + ".py"),
                              encoding="utf-8").read())
        out = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                out |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and n.col_offset == 0:
                out.add(n.module.split(".")[0])
        return out

    seen, stack = set(), ["video_toolbox_qt", "video_toolbox"]
    while stack:
        m = stack.pop()
        if m in seen or m not in srcmods:
            continue
        seen.add(m)
        stack += [d for d in imports_of(m) if d in srcmods and d not in seen]
    return seen


def install(silent_installer, dest):
    if os.path.isdir(dest) and os.listdir(dest):
        print("!! 目标目录非空，拒绝覆盖：", dest)
        return False
    log = dest + "_install.log"
    cmd = [silent_installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
           "/DIR=" + dest, "/LOG=" + log]
    print("安装中：%s\n  → %s" % (os.path.basename(silent_installer), dest))
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True)
    # Inno 退出码 0 = 成功；1 = 静默被拒（互斥进程/权限等）
    print("安装器退出码 =", r.returncode)
    if r.returncode != 0:
        print((r.stderr or b"")[-2000:].decode("utf-8", "replace"))
    if os.path.isfile(log):
        tail = open(log, encoding="utf-8", errors="replace").read().splitlines()
        for ln in tail[-8:]:
            print("   | " + ln)
    return os.path.isfile(os.path.join(dest, "视频工具箱.exe"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dest = os.path.abspath(sys.argv[1])
    if len(sys.argv) >= 3:
        if not install(os.path.abspath(sys.argv[2]), dest):
            print("!! 安装失败或主程序未就位")
            return 1

    fails = []
    print("\n== 1) 主程序 exe ==")
    exe = os.path.join(dest, "视频工具箱.exe")
    if os.path.isfile(exe) and os.path.isfile(PROJ_DIST):
        a, b = md5(exe), md5(PROJ_DIST)
        same = a == b
        print("   %s  %d 字节  md5=%s" % (exe, os.path.getsize(exe), a))
        print("   仓库 dist\\视频工具箱.exe md5=%s  →  %s"
              % (b, "一致" if same else "不一致"))
        if not same:
            fails.append("主程序 exe 与 dist 不一致")
    else:
        fails.append("安装目录或 dist 缺主程序 exe")

    print("\n== 2) src 模块闭包 ==")
    mods = sorted(closure())
    absent = []
    for m in mods:
        p = os.path.join(dest, "src", m + ".py")
        if not os.path.isfile(p):
            absent.append(m)
        else:
            # 内容一致性：与仓库 src 逐字节比对
            with open(p, "rb") as f1, open(os.path.join(PROJ_SRC, m + ".py"), "rb") as f2:
                if f1.read() != f2.read():
                    fails.append("src\\%s.py 与仓库内容不一致" % m)
    print("   闭包 %d 个模块，安装目录缺 %d 个" % (len(mods), len(absent)))
    for m in absent:
        print("   [缺] src\\%s.py" % m)
        fails.append("src\\%s.py 未随包分发" % m)
    if not absent:
        print("   全部就位")

    print("\n== 3) src\\ 方式运行导入冒烟（用安装目录自带 python） ==")
    py = os.path.join(dest, "tools", "python", "python.exe")
    if os.path.isfile(py):
        probe = ("import os,sys;"
                 "sys.path.insert(0, os.path.join(os.getcwd(),'src'));"
                 "mods=%r;"
                 "bad=[]\n"
                 "for m in mods:\n"
                 "    try: __import__(m)\n"
                 "    except Exception as e: bad.append((m, type(e).__name__, str(e)[:120]))\n"
                 "print('OK' if not bad else ('BAD '+repr(bad)))" % (mods,))
        r = subprocess.run([py, "-c", probe], cwd=dest, capture_output=True)
        out = (r.stdout or b"").decode("utf-8", "replace")
        # qfluentwidgets 等库会往 stdout 打 banner，只认最后一行标记
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        verdict = lines[-1] if lines else "(无输出)"
        print("   " + out.strip().replace("\n", "\n   "))
        if not verdict.startswith("OK"):
            fails.append("src\\ 方式导入冒烟失败：" + verdict[:300])
    else:
        print("   [跳过] 安装目录未随包 tools\\python（在线安装形态）")

    print("\n== 4) 静态资产 ==")
    for rel in ["docs\\使用说明.txt", "docs\\开源许可_GPL-3.0.txt",
                "docs\\第三方组件来源与许可声明.txt", "tools\\ai_client.py",
                "subtitle_calib_merged.py"]:
        p = os.path.join(dest, *rel.split("\\"))
        ok = os.path.isfile(p)
        print("   %s %s" % ("[OK]" if ok else "[缺]", rel))
        if not ok:
            fails.append("静态资产缺失：" + rel)

    print("\n" + "=" * 60)
    if fails:
        print("失败 %d 项：" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("全部通过（%d 项校验）" % (len(mods) + 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
