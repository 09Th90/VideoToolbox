# -*- coding: utf-8 -*-
"""构建「视频工具箱」Qt Installer Framework 在线安装器。

流程（对应在线安装架构）：
  1. 把各组件文件暂存到 build/ifw_packages/<组件>/data（优先硬链接，秒级完成）
  2. repogen 打包 data 为 7z 组件仓库 installer_repository/（含 Updates.xml 校验和）
  3. binarycreator --online-only 生成只含向导、不含组件数据的在线安装器 exe

v1.10.4 说明：界面与设置整合（导航宽度自适应、导航底部统一「设置」页、
  跨屏拖拽修正、字幕引擎界面后台预热），改动均在主程序内，分发方式不变。
v1.10.3 说明：字幕引擎已内嵌进主程序 exe（videocaptioner 及其资源打进
  dist/视频工具箱.exe），在线安装器只分发 exe + 校准脚本 + 源码/文档，
  「字幕处理」页开箱可用，不再依赖 tools/python 运行时。
  docs/ 下的 VideoCaptioner 许可全文与组件来源声明仍随组件分发，以尽合规义务。

用法：
  python installer_src/build_online_installer.py
  python installer_src/build_online_installer.py --repo-url http://192.168.1.10:8123/
  python installer_src/build_online_installer.py --force-copy   # 不用硬链接
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IFW_BIN = ROOT / ".buildvenv/qtifw/Tools/QtInstallerFramework/4.7/bin"
STAGE = ROOT / "build/ifw_packages"
REPO = ROOT / "installer_repository"
CONFIG_OUT = ROOT / "build/ifw_config"
INSTALLER_OUT = ROOT / "installer"

APP_VERSION = "1.10.4"
EXCLUDES = {"__pycache__", "*.pyc", "*.pyo"}

# 组件 -> 文件来源映射：(源路径, data 内相对位置)
# 说明：仅打包自研内容。Python/Chromium/ffmpeg/yt-dlp/Whisper 等开源组件
# 一律不参与安装包构建，由 tools/download_open_source_deps.py 运行时从网上拉取。
COMPONENTS = {
    "com.videotoolbox.base": [
        ("dist/视频工具箱.exe", "视频工具箱.exe"),
        ("subtitle_calib_merged.py", "subtitle_calib_merged.py"),
        ("src", "src"),
        ("docs", "docs"),
        ("tools/ai_client.py", "tools/ai_client.py"),
        ("tools/download_open_source_deps.py", "tools/download_open_source_deps.py"),
        # 内置代理核心（mihomo/ClashMeta，与 FlClash 同源）：程序连接
        # GitHub/HuggingFace 等开源库下载依赖时自动启用，不依赖本机任何代理软件。
        ("tools/mihomo", "tools/mihomo"),
    ],
}


def stage_one(src: Path, dest: Path, force_copy: bool) -> int:
    """把 src 暂存到 dest，返回复制的文件数。目录做排除过滤，文件优先硬链接。"""
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            return 0
        link_or_copy(src, dest, force_copy)
        return 1
    n = 0
    for cur, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in EXCLUDES]
        rel = Path(cur).relative_to(src)
        (dest / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                continue
            s, d = Path(cur) / f, dest / rel / f
            if not d.exists():
                link_or_copy(s, d, force_copy)
                n += 1
    return n


def link_or_copy(s: Path, d: Path, force_copy: bool):
    if not force_copy:
        try:
            os.link(s, d)
            return
        except OSError:
            pass
    shutil.copy2(s, d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", help="重写 config.xml 里的仓库地址（局域网部署用）")
    ap.add_argument("--force-copy", action="store_true", help="禁用硬链接，使用真实复制")
    ap.add_argument("--compression", type=int, default=0, choices=[0, 1, 3, 5, 7, 9],
                    help="repogen 7z 压缩级别（0 不压缩/存储 / 1 快 / 9 小，默认 0）")
    ap.add_argument("--skip-staging", action="store_true", help="跳过组件暂存")
    ap.add_argument("--skip-repo", action="store_true", help="跳过 repogen（仓库已存在时用）")
    ap.add_argument("--skip-installer", action="store_true", help="跳过 binarycreator")
    args = ap.parse_args()

    if not IFW_BIN.exists():
        sys.exit("未找到 IFW 工具链，先执行: aqt install-tool windows desktop "
                 "tools_ifw qt.tools.ifw.47 --outputdir .buildvenv/qtifw "
                 "-b https://mirrors.aliyun.com/qt/")

    # 1. 暂存组件数据 + meta
    if not args.skip_staging:
        print("== 暂存组件数据 ==")
        for comp, items in COMPONENTS.items():
            data_dir = STAGE / comp / "data"
            if data_dir.exists():
                shutil.rmtree(data_dir)
            n = sum(stage_one(ROOT / s, data_dir / d, args.force_copy) for s, d in items)
            meta_src = ROOT / "installer_src/packages" / comp / "meta"
            meta_dst = STAGE / comp / "meta"
            if meta_dst.exists():
                shutil.rmtree(meta_dst)
            shutil.copytree(meta_src, meta_dst)
            size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
            print(f"  {comp}: {n} 项, {size / 1048576:.0f}MB")

    # 2. 仓库地址写进 config 副本（源文件保持默认本机镜像）
    CONFIG_OUT.mkdir(parents=True, exist_ok=True)
    cfg = (ROOT / "installer_src/config/config.xml").read_text(encoding="utf-8")
    if args.repo_url:
        import re
        cfg = re.sub(r"<Url>[^<]*</Url>", f"<Url>{args.repo_url}</Url>", cfg, count=1)
    config_xml = CONFIG_OUT / "config.xml"
    config_xml.write_text(cfg, encoding="utf-8")

    # 3. repogen 生成在线仓库
    if args.skip_repo:
        print("== 跳过 repogen ==")
    else:
        print("== repogen 生成组件仓库（大组件压缩需要几分钟）==")
        REPO.mkdir(exist_ok=True)
        r = subprocess.run([str(IFW_BIN / "repogen.exe"), "-r", "--unite-metadata",
                            "--ac", str(args.compression), "--af", "7z",
                            "-p", str(STAGE), str(REPO)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        print((r.stdout or "")[-3000:], (r.stderr or "")[-2000:] if r.returncode else "")
        if r.returncode:
            sys.exit("repogen 失败")
        if not (REPO / "Updates.xml").exists():
            sys.exit("Updates.xml 未生成")

    if args.skip_installer:
        return

    # 4. binarycreator 生成在线安装器（--online-only：组件全部走仓库下载）
    print("== binarycreator 生成在线安装器 ==")
    INSTALLER_OUT.mkdir(exist_ok=True)
    out = INSTALLER_OUT / f"视频工具箱_在线安装_v{APP_VERSION}.exe"
    r = subprocess.run([str(IFW_BIN / "binarycreator.exe"), "--online-only",
                        "-p", str(STAGE),
                        "-c", str(config_xml), str(out)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    print((r.stdout or "")[-2000:], (r.stderr or "")[-2000:])
    if r.returncode or not out.exists():
        sys.exit("binarycreator 失败")
    print(f"完成: {out} ({out.stat().st_size / 1048576:.1f}MB)")
    print(f"仓库: {REPO.resolve()}  （python installer_src/repo_server.py 启动镜像）")


if __name__ == "__main__":
    main()
