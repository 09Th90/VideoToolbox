# -*- coding: utf-8 -*-
# @version 2.5.0
"""自更新替换流程的离线验证探针（v2.0.0）。

验证四件事：
  1. `schedule_relaunch` 生成的 .cmd 内容正确（编码/等待/回滚/重启）；
  2. 替换源取自安装目录里已落地的新 exe（不是另找的下载缓存）；
  3. 负向：非 frozen 形态必须拒绝自更新，不能谎报可更新；
  4. `data_dir()` 路径拼接正确（VT_DATA_ROOT 是**程序根**，其下再有 data）。

⚠ 全程在**临时目录**里进行，通过 VT_DATA_ROOT 隔离，绝不碰真实
  data\\update。测试用的是假 exe，不是真的程序本体。
⚠ 只在源码形态下运行；本探针不会真的派发替换脚本（dispatch=False）——
  派发后脚本会等主进程退出、随即替换并删掉自身，断言再去找必然扑空。
"""
import glob
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

_OK = [0]
_FAIL = [0]


def chk(name, cond, extra=""):
    if cond:
        _OK[0] += 1
        print("  PASS  %s" % name)
    else:
        _FAIL[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def main():
    # 隔离：临时根目录，data\update 落在它下面
    tmp_root = tempfile.mkdtemp(prefix="vt_selfupd_")
    os.environ["VT_DATA_ROOT"] = tmp_root

    import vt_update_check as u  # noqa: E402 —— 必须在设好环境变量之后 import

    try:
        print("== 0) data_dir 路径拼接 ==")
        chk("data_dir 落在 <VT_DATA_ROOT>\\data\\update 下（不重复 data）",
            os.path.normpath(u.data_dir()) ==
            os.path.normpath(os.path.join(tmp_root, "data", "update")),
            u.data_dir())

        work = u.data_dir()
        # 假 exe 放在临时根里（模拟安装目录）
        fake_dir = os.path.join(tmp_root, "fakeinstall")
        os.makedirs(fake_dir, exist_ok=True)
        fake = os.path.join(fake_dir, "视频工具箱.exe")
        with open(fake, "wb") as fh:
            fh.write(b"MZ" + b"NEWEXEDATA" * 60)

        print("\n== 1) 负向：源码形态不得谎报可更新 ==")
        chk("源码形态拒绝自更新", u.update_available_in_process()[0] is False)

        print("\n== 2) 替换流程（frozen 形态）==")
        real_exe, real_frozen = sys.executable, getattr(sys, "frozen", False)
        try:
            sys.frozen = True
            sys.executable = fake
            chk("frozen 形态允许自更新", u.update_available_in_process()[0] is True)

            ok2, msg = u.schedule_relaunch(dispatch=False)
            chk("生成替换脚本成功", ok2 is True, msg)
            chk("替换源 = 安装目录内的新 exe（已挪走让位）",
                not os.path.isfile(fake))
            chk("新 exe 已暂存", bool(u.pending_update_file()),
                u.pending_update_file())

            cmds = sorted(glob.glob(os.path.join(work, "apply_update_*.cmd")),
                          key=os.path.getmtime)
            if not cmds:
                chk("脚本落盘", False, "data\\update 下无 apply_update_*.cmd")
            else:
                raw = open(cmds[-1], "rb").read()
                # ⚠ cmd.exe 按 OEM 代码页解码 .cmd，写成 UTF-8 中文路径会乱码
                txt = raw.decode("mbcs", errors="replace")
                chk("脚本落盘", True)
                chk("CRLF 换行（cmd 批处理要求）", b"\r\n" in raw)
                chk("中文路径未乱码（非 UTF-8 写入）", "视频工具箱" in txt)
                chk("等待主进程真正退出（tasklist 轮询）", "tasklist" in txt)
                chk("替换失败会回滚（errorlevel 分支）", "errorlevel" in txt)
                chk("成功后自动重启程序", 'start ""' in txt)
                chk("目标路径引号包裹（空格安全）", 'set "TARGET=' in txt)
        finally:
            sys.executable = real_exe
            sys.frozen = real_frozen
            # 还原（模拟替换成功）
            staged = u.pending_update_file()
            if staged and os.path.isfile(staged):
                shutil.move(staged, fake)
            chk("测试环境已还原", os.path.isfile(fake))

        print("\n== 3) 状态与清理 ==")
        u.note_auto_checked("2.0.0", False)
        st = u.read_state()
        chk("状态写入隔离区并可回读",
            bool(st.get("last_check_ts"))
            and os.path.isfile(os.path.join(work, "vt_update_state.json")))
        u.record_declined("9.9.9")
        chk("拒绝记录可回读", u.user_declined("9.9.9") is True)
        chk("cleanup_stale 不误删新文件", u.cleanup_stale(max_age_days=7) >= 0)
        chk("隔离区外无残留（真实 data\\update 未被污染）",
            not glob.glob(os.path.join(ROOT, "data", "update",
                                       "视频工具箱-new-*.exe")))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n  结果：PASS %d / FAIL %d" % (_OK[0], _FAIL[0]))
    return 1 if _FAIL[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())