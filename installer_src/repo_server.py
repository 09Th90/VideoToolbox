# -*- coding: utf-8 -*-
"""本地/局域网组件仓库镜像：python installer_src/repo_server.py [端口]

服务 installer_repository/ 目录（repogen 产物），安装器从这里的
Updates.xml + *.7z 下载组件。启动后打印本机局域网地址，同网段机器
可直接把安装器仓库指向 http://<局域网IP>:<端口>/。
"""
import http.server
import socket
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
REPO = Path(__file__).resolve().parent.parent / "installer_repository"


def lan_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    return sorted(ips)


def main():
    if not (REPO / "Updates.xml").exists():
        sys.exit("installer_repository/Updates.xml 不存在，先运行 build_online_installer.py")
    handler = http.server.SimpleHTTPRequestHandler
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(REPO), **kw)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler)
    print(f"仓库根目录: {REPO}")
    print(f"本机访问:   http://127.0.0.1:{PORT}/")
    for ip in lan_ips():
        print(f"局域网访问: http://{ip}:{PORT}/")
    print("Ctrl+C 停止")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
