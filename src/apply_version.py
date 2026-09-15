# -*- coding: utf-8 -*-
# @version 1.12.1
"""一键同步版本号（幂等）：所有「当前版本」标记处一次改到位。

背景：发布前改版本号历史上要手工同步 spec / iss / 在线安装器三件套 / qt VERSION /
文档首行等近十处，漏一处就会出现「安装包名对、关于页版本旧」之类的不一致。
本脚本把这份清单固化下来，只替换**当前版本标记**，不动变更历史里出现的旧版本号。

改完 11 处「当前版本标记」后，会自动调用同目录的 stamp_versions.py，为所有自研
当前版本文件重打首行 `@version <新版本>` 标记并重生成《文件版本清单》（v1.12.1 起）。

用法（在 src 目录）：
    python apply_version.py 1.12.1            # 从当前版本改到 1.12.1
    python apply_version.py 1.12.1 --check    # 只报告会改哪些位置
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: (相对路径, 含 {v} 的精确匹配串, 期望出现次数)
TARGETS = [
    (r"src\video_toolbox_qt.py", 'VERSION = "{v}"', 1),
    (r"视频工具箱.spec", '"""视频工具箱 v{v} ', 1),
    (r"视频工具箱.iss", '; 视频工具箱 v{v} ', 1),
    (r"视频工具箱.iss", '视频工具箱_Setup_v{v}.exe', 1),
    (r"视频工具箱.iss", '#define MyAppVersion "{v}"', 1),
    (r"installer_src\build_online_installer.py", 'APP_VERSION = "{v}"', 1),
    (r"installer_src\config\config.xml", "<Version>{v}</Version>", 1),
    (r"installer_src\config\config.xml", "视频工具箱 v{v}（在线安装）", 1),
    (r"installer_src\packages\com.videotoolbox.base\meta\package.xml",
     "<Version>{v}</Version>", 1),
    (r"docs\使用说明.txt", "视频工具箱 v{v} 使用说明", 1),
    (r"docs\程序说明书.md", "适用版本：v{v}", 1),
]


def _current_version():
    """从 qt 界面源码读当前 VERSION。"""
    p = os.path.join(ROOT, "src", "video_toolbox_qt.py")
    m = re.search(r'VERSION\s*=\s*"([\d.]+)"', open(p, encoding="utf-8").read())
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("new_version")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    old = _current_version()
    new = args.new_version.strip()
    if not old:
        print("无法从 src/video_toolbox_qt.py 读取当前版本")
        return 2
    if old == new:
        print(f"当前已是 v{new}，无需改动")
        return 0
    print(f"版本 {old} → {new}")
    changed = 0
    for rel, pattern, expect in TARGETS:
        path = os.path.join(ROOT, *rel.split("\\"))
        if not os.path.isfile(path):
            print(f"  [跳过] 文件不存在：{rel}")
            continue
        text = open(path, encoding="utf-8").read()
        target_old = pattern.replace("{v}", old)
        target_new = pattern.replace("{v}", new)
        cnt = text.count(target_old)
        if cnt == 0:
            print(f"  [跳过] 未找到 `{target_old}`：{rel}")
            continue
        if cnt != expect:
            print(f"  [!] {rel} 命中 {cnt} 处（预期 {expect}），已一并替换")
        if args.check:
            print(f"  [将改] {rel}：`{target_old}` → `{target_new}` ×{cnt}")
            continue
        open(path, "w", encoding="utf-8", newline="").write(
            text.replace(target_old, target_new))
        print(f"  [已改] {rel} ×{cnt}")
        changed += 1
    if args.check:
        print("（--check 模式，未写入）")
    else:
        print(f"完成，共改动 {changed} 个文件。记得同步变更说明段与重打包。")
        # v1.12.1 起：同步给所有自研当前版本文件打首行版本标记，并重生成
        # 《文件版本清单》（stamp_versions.py 幂等，失败不影响版本号本身）
        stamp = os.path.join(HERE, "stamp_versions.py")
        if os.path.isfile(stamp):
            print("\n== 同步文件版本标记与《文件版本清单》 ==")
            try:
                subprocess.run([sys.executable, stamp], cwd=HERE, check=False)
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] 打标失败：{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
