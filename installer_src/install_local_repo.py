# -*- coding: utf-8 -*-
# @version 1.15.3
"""本机 / 局域网「全速」在线安装：把在线安装器的下载源换成内网仓库。

背景：在线安装器的默认源在 GitHub Pages（海外），国内直连常常只有几十 KB/s、
甚至完全不通（走系统代理才勉强能动）。而在线仓库 installer_repository/ 就在
本机，104MB 走内网/本机 HTTP 通常几秒就能装完。

做法：用 IFW 的 `--set-temp-repository <url>` 选项把仓库地址临时替换掉
（该选项图形模式同样生效），必要时顺带把 repo_server.py 拉起来。

用法（在仓库根或 installer_src 下都可以）：
    python installer_src\\install_local_repo.py                 # 本机源（自动起 repo_server）
    python installer_src\\install_local_repo.py --port 9000
    python installer_src\\install_local_repo.py --repo-url http://192.168.1.10:8123/
    python installer_src\\install_local_repo.py --file          # 直接用 file:/// 本地目录（不起服务）
    python installer_src\\install_local_repo.py --dry-run        # 只打印将执行的命令

给同事装（局域网分发）时，在放着仓库的那台机器上跑：
    python installer_src\\repo_server.py 8123
再把上面打印的 http://<局域网IP>:8123/ 用 --repo-url 传给本脚本即可。
"""
import argparse
import glob
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_REPO = ROOT / "installer_repository"
DEFAULT_PORT = 8123


def _direct_opener():
    """强制直连：本机环境里 http_proxy/https_proxy 会让 urllib 把 127.0.0.1 也送进
    代理（实测 502），必须清空 ProxyHandler。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def find_installer(pattern=None):
    """找在线安装器 exe：默认 installer/视频工具箱_在线安装_v*.exe，取版本号最大的。"""
    pat = pattern or str(ROOT / "installer" / "视频工具箱_在线安装_v*.exe")
    cands = glob.glob(pat)
    if not cands:
        sys.exit(f"没找到在线安装器：{pat}\n先运行 python installer_src\\build_online_installer.py")
    return Path(max(cands, key=os.path.getmtime))


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_repo(url, timeout=15.0):
    """轮询 <url>/Updates.xml 直到可用（仓库就绪判定）。"""
    op = _direct_opener()
    probe = url.rstrip("/") + "/Updates.xml"
    deadline = time.time() + timeout
    err = None
    while time.time() < deadline:
        try:
            with op.open(probe, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError) as e:
            err = e
        time.sleep(0.3)
    print(f"  ⚠ 仓库探测失败（{probe}）：{err}")
    return False


def python_exe():
    """优先内置运行时（一定有），退回当前解释器。"""
    for rel in ("tools/python/python.exe", "tools/python/pythonw.exe"):
        p = ROOT / rel
        if p.exists():
            return str(p)
    return sys.executable


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(description="用内网/本机仓库全速安装（替换在线安装器的下载源）")
    ap.add_argument("--installer", help="在线安装器 exe 路径（默认取 installer\\ 下最新版）")
    ap.add_argument("--repo-url", help="直接用这个仓库地址（如局域网 http://192.168.1.10:8123/）")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="本地仓库目录（默认 installer_repository）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"repo_server 端口（默认 {DEFAULT_PORT}）")
    ap.add_argument("--file", action="store_true", help="改用 file:/// 本地目录，不启动 HTTP 服务")
    ap.add_argument("--no-server", action="store_true", help="不起 repo_server（假定已有服务在跑）")
    ap.add_argument("--extra", default="", help="追加传给安装器的其它参数（空格分隔）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    args = ap.parse_args()

    repo_dir = Path(args.repo).resolve()
    installer = Path(args.installer).resolve() if args.installer else find_installer()

    if not args.repo_url and not repo_dir.joinpath("Updates.xml").exists():
        sys.exit(f"仓库目录里没有 Updates.xml：{repo_dir}\n先运行 python installer_src\\build_online_installer.py")

    server = None
    if args.repo_url:
        repo_url = args.repo_url
        print(f"仓库源（指定）：{repo_url}")
    elif args.file:
        repo_url = repo_dir.as_uri()      # 自动对非 ASCII 路径做百分号编码
        print(f"仓库源（本地目录）：{repo_url}")
    else:
        repo_url = f"http://127.0.0.1:{args.port}/"
        if port_in_use(args.port):
            print(f"端口 {args.port} 已有服务，直接复用（如需另起请加 --port）")
        elif args.no_server:
            sys.exit(f"端口 {args.port} 上没有服务，且指定了 --no-server")
        elif args.dry_run:
            print(f"[dry-run] 将启动：{python_exe()} {HERE / 'repo_server.py'} {args.port}")
        else:
            print(f"启动内网仓库服务：http://127.0.0.1:{args.port}/  （安装结束后自动关闭）")
            server = subprocess.Popen(
                [python_exe(), str(HERE / "repo_server.py"), str(args.port)],
                cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    cmd = [str(installer), "--set-temp-repository", repo_url]
    if args.extra:
        cmd += args.extra.split()
    shown = " ".join(f'"{c}"' if (" " in c or c.endswith(".exe")) else c for c in cmd)
    print(f"\n安装器：{installer.name}")
    print(f"命令  ：{shown}\n")

    if args.dry_run:
        if server:
            server.terminate()
        return 0

    if not args.repo_url and not args.file:
        if not wait_repo(repo_url):
            if server:
                server.terminate()
            sys.exit("内网仓库没起来，安装器将无法下载组件")

    try:
        rc = subprocess.call(cmd, cwd=str(installer.parent))
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    print(f"\n安装器退出码：{rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main() or 0)
