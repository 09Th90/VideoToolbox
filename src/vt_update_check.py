# -*- coding: utf-8 -*-
# @version 2.3.0
"""视频工具箱 · 主程序侧「检查更新」与自更新（v2.0.0 起）。

定位
====================================================================
本模块是**主程序（PySide6 界面）**与自研在线安装器
（`packaging\\online_release\\`）之间的接线层。安装器那边已经把
「下载 / 清单 / 增量计划 / 原子落地」做完了，本模块只做三件事：

  1. **检测**：跑一次 `resolve_manifest` + `plan_update`，回答
     「有没有新版本、要下多大、涉及哪些包」。启动时静默跑，设置页
     按钮手动跑，同一份代码两个入口。
  2. **决策**：把检测结果整理成给界面看的文案（版本对比 + 体积 +
     组件清单 + 降级/回滚提示）。
  3. **自更新**：用户确认后下载新 exe，并**在主进程退出后**替换自身。

⚠ 为什么复用而不是重写
--------------------------------------------------------------------
安装器侧已经过了 16 组交叉验证（块级续传、镜像回退、原子落地回滚、
暂存区逐文件校验……）。主程序侧再写一套下载逻辑，等于凭空多出一份
没有验证过的实现——两条实现漂移起来更难查。故此处只做「接线」，
下载/校验/落地一律委托 `vt_update_core`。

⚠ 打包形态的接入（PyInstaller spec 必须同步改）
--------------------------------------------------------------------
`vt_update_core` / `vt_dl` / `vt_version_index` 三个模块在
`packaging\\online_release\\` 下，**不在 `src/`**，所以：

  · 打包时必须收进 PYZ（见 `packaging\\视频工具箱.spec` 的
    `hiddenimports` / pathex），否则运行时报 ModuleNotFoundError；
  · 开发期（未打包）运行时，本模块用 `_locate_orel()` 从
    `APP_DIR\\packaging\\online_release` 找它们；
  · 找不到时**降级为「无可用更新」而不是抛异常**——更新功能挂掉
    绝不该让主程序起不来。

自更新的 Windows 约束（v2.0.0 实证）
--------------------------------------------------------------------
运行中的 exe 文件被独占，**无法覆盖**；但可以改名。行业通行解法是
「下载新文件 → 写一个 .cmd/.bat 脚本 → 主进程退出后由脚本换名替换
→ 重新启动」。本模块用 `subprocess.Popen` 派发那个脚本，脚本本身
是唯一能在主进程退出后继续跑的东西。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

#: 主程序自身版本。与 src\video_toolbox_qt.py 的 VERSION 同源；
#: 这里独立存一份是因为更新逻辑必须在**不 import Qt** 的前提下可用
#: （子进程脚本、自检都要能读）。
#: ⚠ 改版本号时须一并改——scripts/dev/apply_version.py 覆盖不到这里。
SELF_VERSION = "2.3.0"

#: 远端清单与版本索引（与安装器默认值一致，固定 tag repo-latest）
DEFAULT_MANIFEST_URL = ("https://github.com/09Th90/VideoToolbox/releases/"
                        "download/repo-latest/manifest.json")
DEFAULT_INDEX_URL = ("https://github.com/09Th90/VideoToolbox/releases/"
                     "download/repo-latest/index.json")

#: 启动自动检测的节流：同一天内最多自动问一次（用户手动点不受限）
_AUTO_CHECK_INTERVAL = 12 * 3600

#: 更新状态文件（记上次自动检测时间与用户是否拒绝过某个版本）
_STATE_NAME = "vt_update_state.json"


# --------------------------------------------------------------- 依赖定位

def _locate_orel():
    """定位 packaging\\online_release 目录，返回路径或 ""。

    打包后这三个模块在 PYZ 里，`__file__` 不指向磁盘目录；但那时
    import 直接成功，本函数不会被调用。仅开发期需要找。
    """
    cands = [
        os.path.join(os.path.dirname(_HERE), "packaging", "online_release"),
        os.path.join(_HERE, "online_release"),
    ]
    for c in cands:
        if os.path.isfile(os.path.join(c, "vt_update_core.py")):
            return c
    return ""


def load_core():
    """导入安装器侧的三个模块，返回 (core, dl, vindex)；失败返回 None。

    ⚠ **绝不在这里抛异常**：在线发布链路（GitHub / 镜像 / 本地代理）
    出问题时，主程序仍必须能正常启动。调用方一律先判 None。
    """
    if load_core._cache is None:
        load_core._cache = _load_core_impl()
    return load_core._cache


load_core._cache = None


def _load_core_impl():
    try:
        import vt_dl
        import vt_update_core
        import vt_version_index
    except ImportError:
        d = _locate_orel()
        if not d:
            return None
        if d not in sys.path:
            sys.path.insert(0, d)
        try:
            import vt_dl
            import vt_update_core
            import vt_version_index
        except Exception:  # noqa: BLE001 —— 任何异常都只降级，不上抛
            return None
    return (vt_update_core, vt_dl, vt_version_index)


# --------------------------------------------------------------- 本地状态

def app_dir():
    """程序根目录：打包后 = exe 目录，开发期 = 仓库根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(_HERE)


def exe_path():
    """主程序 exe 的绝对路径；源码模式下返回 ""（无可替换对象）。"""
    if not getattr(sys, "frozen", False):
        return ""
    return os.path.abspath(sys.executable)


def data_dir():
    """用户数据目录下的本模块工作目录（放状态文件与下载暂存）。

    ⚠ `VT_DATA_ROOT` 的语义是**程序根**（与 engine.DATA_ROOT 一致，
    `data/` 在它下面），不是数据目录本身。这里若再拼一层 `data`，
    传 `VT_DATA_ROOT=<根>/data` 就会得到 `.../data/data/update`——
    与主程序其余部分（data/、logs/）分家，更新状态就散到别处去了。
    """
    root = os.environ.get("VT_DATA_ROOT")
    base = root if root else app_dir()
    d = os.path.join(base, "data", "update")
    os.makedirs(d, exist_ok=True)
    return d


def _state_path():
    return os.path.join(data_dir(), _STATE_NAME)


def read_state():
    """读本模块状态；损坏/不存在返回空 dict（绝不抛）。"""
    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def write_state(st):
    """原子写状态（先写 .tmp 再 replace，中途崩溃不留半截文件）。"""
    p = _state_path()
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except Exception:  # noqa: BLE001
        return False


#: 本地版本识别不到时的占位符
_NO_VER = "未安装"


def _v(v):
    """版本号加 "v" 前缀；占位符 / 空值原样返回，别拼出「v未安装」。

    曾经无条件拼 "v"，本地未安装时界面出现「当前版本 v未安装」——
    与设置页顶上的「当前版本 v2.0.0」自相矛盾。前缀只加给真实版本号。
    """
    s = str(v or "").strip()
    if not s or s == _NO_VER:
        return _NO_VER
    return "v" + s


def _vnewer(a, b):
    """a 的版本号是否比 b 新；解析不了按 False（不抛）。"""
    mods = load_core()
    if not mods:
        return False
    try:
        return mods[0].ver_tuple(a) > mods[0].ver_tuple(b)
    except Exception:  # noqa: BLE001
        return False


def _wrap(text, width=30):
    """把一行文本折成不超过 width 个字符的若干行。

    QMessageBox 的 informativeText 不保证按中文断行——一行撑爆框宽
    就被直接裁掉（曾出现「全新安装状」这种半个词的截断）。故展示前
    自行折行。断点优先级：① 空格；② 中西文边界；③ 硬断（中文没有
    词边界，硬断可读性可接受）。

    ⚠ 按**字符数**而不是「CJK 记 1、ASCII 记 0.5」的估算列数：后者
    在 ASCII 回退字体（Helvetica 下中西文等宽）下会把长路径行少算
    一半，实测 612px 撞穿 597px 的标签宽。
    """
    out = []
    for line in str(text).split("\n"):
        cur = ""
        for ch in line:
            if len(cur) >= width:
                cut = cur.rfind(" ")
                if cut < width // 2:
                    cut = -1
                    for i in range(len(cur) - 1, 0, -1):
                        if (ord(cur[i - 1]) > 0x2E7F) != (ord(cur[i]) > 0x2E7F):
                            cut = i
                            break
                    if cut < width // 2:
                        cut = len(cur)
                out.append(cur[:cut].rstrip())
                cur = cur[cut:].lstrip()
            cur += ch
        out.append(cur)
    return out


def wrap_lines(lines, width=30):
    """把多行文本逐行折行后展平（界面拼装正文时统一走这里）。"""
    out = []
    for ln in lines:
        out.extend(_wrap(ln, width))
    return out


# --------------------------------------------------------------- 检测

class CheckResult(object):
    """一次检查的结果。

    字段：
        ok        检测是否成功（False 时 err 有值，其余字段无意义）
        err       失败原因文本
        update    是否有可安装的新版本
        local_ver 本地版本（"未安装" 表示识别不到）
        remote_ver 远端目标版本
        download_bytes 本次需要下载的字节数
        packages  [(包名, 人类可读大小)]，只列要下的包
        changed   文件级变更数
        orphans   降级/回滚时会被清理的文件数
        install_dir  目标安装目录
        full      是否为全新安装（本地什么都没装）
        manifest  解析到的清单原文（更新时要用）
        baseline_ver  版本对比基准：**已装版本与当前运行的程序版本里
                      较新的那个**。本地没装时退回 SELF_VERSION——
                      否则开发版 v2.0.0 面对远端 v1.19.0 会被提示成
                      「发现新版本」，而它其实比运行中的程序还旧。
    """

    __slots__ = ("ok", "err", "update", "local_ver", "remote_ver",
                 "download_bytes", "packages", "changed", "orphans",
                 "install_dir", "full", "manifest", "entry",
                 "baseline_ver")

    def __init__(self):
        self.ok = False
        self.err = ""
        self.update = False
        self.local_ver = _NO_VER
        self.remote_ver = ""
        self.download_bytes = 0
        self.packages = []
        self.changed = 0
        self.orphans = 0
        self.install_dir = ""
        self.full = False
        self.manifest = None
        self.entry = None
        self.baseline_ver = SELF_VERSION

    def summary(self):
        """给日志/界面用的一行摘要。"""
        if not self.ok:
            return "检查失败：" + self.err
        if not self.update:
            if self.local_ver == _NO_VER:
                return "远端暂无可安装的组件"
            return "当前已是最新版本 %s" % _v(self.local_ver)
        return "%s %s（当前 %s），需下载 %s" % (
            self.action_label(), _v(self.remote_ver),
            _v(self.baseline_ver), _human(self.download_bytes))

    def action_label(self):
        """确认框标题用的动作短语：区分 全新安装 / 升级 / 降级。

        ⚠ 曾经一律弹「发现新版本」（本地未安装时 downgrade() 恒为
        False），于是开发版 v2.0.0 面对远端 v1.19.0 也被告知「发现
        新版本」——比运行中的程序还旧的版本不可能是新版本。方向必须
        拿 baseline_ver（当前运行版本参与比较）来判。
        """
        down = self.downgrade()
        if self.full:
            return "安装较旧版本" if down else "全新安装"
        return "回滚到旧版本" if down else "发现新版本"

    def detail_lines(self):
        """确认对话框里的多行说明（已按显示宽度折好行，不会截断）。"""
        if not self.ok:
            return _wrap(self.err)
        if not load_core():
            return ["更新组件未随程序分发，无法展示更新详情"]
        lines = []
        # 当前版本：本地已装优先；正在运行的程序更新时并列说明——别让
        # 「设置页写着 v2.0.0、弹窗写着 v未安装」这种自相矛盾再出现
        if self.local_ver == _NO_VER:
            lines.append("当前版本：%s（正在运行 %s）"
                         % (_NO_VER, _v(SELF_VERSION)))
        elif _vnewer(SELF_VERSION, self.local_ver):
            lines.append("当前版本：%s（正在运行 %s）"
                         % (_v(self.local_ver), _v(SELF_VERSION)))
        else:
            lines.append("当前版本：%s" % _v(self.local_ver))
        if self.downgrade():
            lines.append("目标版本：%s（低于当前 %s，属降级）"
                         % (_v(self.remote_ver), _v(self.baseline_ver)))
        else:
            lines.append("最新版本：%s" % _v(self.remote_ver))
        lines.append("需要下载：%s" % _human(self.download_bytes))
        if self.packages:
            lines.append("包含组件：" + "、".join(
                "%s（%s）" % (n, s) for n, s in self.packages))
        if self.changed:
            lines.append("变更文件：%d 个" % self.changed)
        if self.full:
            lines.append("本地未检测到已安装版本，将执行全新安装")
        if self.orphans:
            lines.append("注意：本次会清理 %d 个旧版本残留文件" % self.orphans)
        if self.downgrade():
            lines.append("")
            lines.append("确认后将替换为较旧的版本，数据与配置不受影响。")
        lines.append("")
        lines.append("更新将在你确认后开始，下载期间可随时取消。")
        lines.append("更新完成后需要重启程序。")
        return wrap_lines(lines)

    def downgrade(self):
        """目标版本是否低于当前基准版本（= 降级/回滚）。"""
        if not self.ok:
            return False
        mods = load_core()
        if not mods:
            return False
        try:
            return mods[0].ver_tuple(self.remote_ver) < \
                mods[0].ver_tuple(self.baseline_ver or SELF_VERSION)
        except Exception:  # noqa: BLE001
            return False


def _human(n):
    """字节数转人类可读。**直接用安装器侧的 human()**，不自己复刻一份。

    理由是「单一真相源」而非「这里有 bug」：这类量级换算函数一旦
    两处各写一份，改了一边忘了另一边，界面上就会出现同一个数字在
    两处显示不同量级。安装器侧的 human() 已随 16 组交叉验证。
    （开发期曾误判这里有量级 bug，实际是构造测试数据时 size 写错。）
    """
    mods = load_core()
    if mods:
        try:
            return mods[0].human(n)
        except Exception:  # noqa: BLE001
            pass
    try:
        n = float(n)
    except Exception:  # noqa: BLE001
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024
    return "%.1f TB" % n


def check_update(install_dir="", want="latest", manifest_url=None,
                 index_url=None, base_url=None, log=None):
    """检查是否有可安装的新版本。返回 CheckResult。

    参数：
        install_dir  目标目录；空则自动探测（注册表 → 默认 D 盘）
        want         目标版本（latest / stable / 精确版本 / ^1.20 等）
        manifest_url / index_url  自定义源（离线自测指向本地文件）
        base_url     **资产根地址**。给了 index_url 却不给它时，索引里
                      记的仍是 GitHub 地址，于是解析出版本后去线上找
                      manifest —— 本地验证与离线场景一律 404（镜像兜底
                      也救不回来）。传本地目录（file:///…）即可整条链路离线跑通。
        log          日志回调

    ⚠ 本函数**不下载任何东西**，只读 manifest（几百字节到几十 KB）。
    """
    res = CheckResult()
    mods = load_core()
    if not mods:
        res.err = "更新组件未随程序分发（packaging/online_release 缺失）"
        return res
    core = mods[0]

    def say(msg):
        if log:
            log(str(msg))

    try:
        m, entry = core.resolve_manifest(
            want=want or "latest",
            index_url=index_url or None,
            manifest=manifest_url or None,
            base_url=base_url or None)
    except Exception as e:  # noqa: BLE001
        res.err = str(e)
        return res

    d = (install_dir or "").strip()
    if not d:
        try:
            d = core.detect_install_dir() or core.default_install_dir()
        except Exception:  # noqa: BLE001
            d = ""
    res.install_dir = d
    res.manifest = m
    res.entry = entry
    res.remote_ver = m.get("version") or ""

    try:
        plan = core.plan_update(m, d, log=log)
    except Exception as e:  # noqa: BLE001
        res.err = "比对本地文件失败：%s" % e
        return res

    res.local_ver = plan.get("local_version") or _NO_VER
    res.full = res.local_ver == _NO_VER
    # 版本对比基准 = 已装版本与**当前运行的程序版本**里较新的那个：
    # 1) 本地没装 → 退回 SELF_VERSION（安装方向要与运行版本比，不能
    #    拿空目录比，否则永远「全新安装」、永远「发现新版本」）；
    # 2) 运行的是开发版（高于已装/高于远端发布版）→ 以运行版本为准，
    #    检测方向判「降级」而不是「发现新版本」。
    res.baseline_ver = res.local_ver
    if res.local_ver == _NO_VER or _vnewer(SELF_VERSION, res.local_ver):
        res.baseline_ver = SELF_VERSION
    res.download_bytes = int(plan.get("download_bytes") or 0)
    res.changed = len(plan.get("changed") or [])
    res.orphans = len(plan.get("orphans") or [])
    res.packages = [(a.get("name") or a.get("file"),
                    _human(int(a.get("size") or 0)))
                    for a in (plan.get("need") or [])]
    res.ok = True
    # 有包要下、或有残留要清，才算「有更新」
    res.update = bool(plan.get("need")) or bool(plan.get("orphans"))
    say(res.summary())
    return res


def should_auto_check():
    """启动自动检测是否该跑（距上次成功询问已超过节流间隔）。"""
    st = read_state()
    last = st.get("last_check_ts")
    if not last:
        return True
    try:
        return (time.time() - float(last)) > _AUTO_CHECK_INTERVAL
    except Exception:  # noqa: BLE001
        return True


def note_auto_checked(version, had_update):
    """记下「已询问过」，供下次启动节流判断。"""
    st = read_state()
    st["last_check_ts"] = time.time()
    st["last_seen_version"] = version or ""
    st["last_had_update"] = bool(had_update)
    write_state(st)


def user_declined(version):
    """用户是否已经拒绝过这个版本（拒绝过就别每次启动都来烦）。"""
    st = read_state()
    return str(st.get("declined_version") or "") == str(version or "")


def record_declined(version):
    """记住「用户拒绝了这一版」，下次启动不再提示同一版本。"""
    st = read_state()
    st["declined_version"] = version or ""
    st["declined_ts"] = time.time()
    write_state(st)


# --------------------------------------------------------------- 更新执行

def update_available_in_process():
    """主进程能否原地更新自己。

    必须同时满足：打包形态（源码模式没有可替换的 exe）、
    exe 不在只读位置、且不是通过 onefile 临时目录运行。
    ⚠ PyInstaller onefile 运行时 exe 在 `_MEI***` 解包目录之外，
    但 `sys.executable` 始终是真实 exe 路径——这里用它判定即可。
    """
    if not getattr(sys, "frozen", False):
        return False, "当前是源码运行模式，没有可更新的程序本体"
    p = exe_path()
    if not p or not os.path.isfile(p):
        return False, "找不到程序本体 exe"
    try:
        with open(p, "rb") as fh:
            fh.read(1)
        if not os.access(os.path.dirname(p), os.W_OK):
            return False, "程序所在目录不可写（可能装在受保护位置）"
    except OSError as e:
        return False, "程序本体不可访问：%s" % e
    return True, ""


def apply_update(res, progress=None, log=None, cancel=None):
    """执行更新：下载 + 原子落地到 res.install_dir。

    progress(log 同) 与 `vt_update_core.apply_update` 一致：
    progress(阶段文本, 已完成, 总数)、log(文本)。
    返回安装器侧的结果 dict。

    ⚠ **不处理 exe 自身的替换**：运行中的 exe 无法覆盖，替换由
    `schedule_relaunch()` 在主进程退出后完成。
    """
    mods = load_core()
    if not mods:
        raise RuntimeError("更新组件未随程序分发")
    core = mods[0]
    if not res or not res.ok or not res.manifest:
        raise RuntimeError("没有可执行的更新计划")
    if not res.install_dir:
        raise RuntimeError("没有确定的安装目录")
    return core.apply_update(res.manifest, res.install_dir,
                             data_dir(), progress=progress, log=log,
                             cancel=cancel)


# --------------------------------------------------------------- 自替换

_REPLACE_SCRIPT = """@echo off
rem 视频工具箱 · 自更新替换脚本（由主程序在退出后派发）
rem ⚠ 生成时把路径写死成引号包裹，避免空格导致拆成多个参数。
setlocal
set "TARGET=%(target)s"
set "NEW=%(new)s"
set "OLD=%(old)s"
set "BACKUP=%(backup)s"
rem 等主进程彻底退出（onefile 父进程可能比界面进程活得更久）
:wait
timeout /t 1 /nobreak >nul
tasklist /fi "imagename eq %(image)s" 2>nul | find /i "%(image)s" >nul
if not errorlevel 1 goto wait
if exist "%%TARGET%%" (
    move /y "%%TARGET%%" "%%BACKUP%%" >nul 2>&1
)
move /y "%%NEW%%" "%%TARGET%%" >nul 2>&1
if errorlevel 1 (
    rem 替换失败：回滚，绝不留下没有主程序的目录
    if exist "%%BACKUP%%" move /y "%%BACKUP%%" "%%TARGET%%" >nul 2>&1
    echo FAILED > "%(done)s"
    exit /b 1
)
if exist "%%BACKUP%%" del /q "%%BACKUP%%" >nul 2>&1
echo OK > "%(done)s"
start "" "%%TARGET%%"
exit /b 0
"""


def schedule_relaunch(done_path=None, dispatch=True):
    """主进程退出后替换 exe 并重新启动。返回 (ok, 提示)。

    在**当前进程即将退出前**调用：脚本会等主进程真正从任务管理器消失
    （onefile 有父/子两个进程，直接启动脚本会抢不到改名时机），
    然后 备份 → 替换 → 删备份 → 重新拉起。

    ⚠ 替换源不是「下载缓存里的某个文件」，而是 **apply_update 刚落到
    安装目录里的那份新 exe**——本函数先把它挪到暂存区（此时主进程还在
    跑，改名合法），脚本再在主进程退出后挪回原位并重启。

    done_path 指定的文件会被写入 `OK` 或 `FAILED`，供下次启动读取结果。
    """
    ok, why = update_available_in_process()
    if not ok:
        return False, why

    target = exe_path()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = data_dir()
    new = os.path.join(work, "视频工具箱-new-%s.exe" % stamp)
    backup = os.path.join(work, "视频工具箱-old-%s.exe" % stamp)
    script = os.path.join(work, "apply_update_%s.cmd" % stamp)
    done = done_path or os.path.join(work, "last_update_result.txt")

    # ⚠ **替换源就是安装目录里那份已落地的新 exe**（apply_update 刚写
    # 进去的），这里把它挪到暂存区让出原文件名，不另找「已下载的新版本
    # 文件」。曾经去找 `视频工具箱-new-<时间戳>.exe`，而 apply_update
    # 从不产出这种名字的文件，于是每次都报「找不到已下载的新版本文件」，
    # 自更新永远走不到替换这一步。
    # Windows 上运行中的 exe 不能被覆盖、但可以改名，故必须两段式：
    # 主进程退出 → 目标改名让位 → 新文件就位。现在（主进程还在跑）先
    # 挪走：被独占锁挡住的只有覆盖与删除，改名是允许的。挪不动即说明
    # 落地根本没生效，明确失败而不是静默继续。
    if not os.path.isfile(target):
        return False, "找不到程序本体：%s" % target
    try:
        shutil.move(target, new)
    except Exception as e:  # noqa: BLE001
        return False, "无法暂存新版本文件（%s）：%s" % (new, e)

    body = _REPLACE_SCRIPT % {
        "target": target,
        "new": new,
        "old": backup,
        "backup": backup,
        "image": os.path.basename(target),
        "done": done,
    }
    try:
        # ⚠ 必须编码成 ANSI/系统代码页：cmd.exe 读 .cmd 时按 OEM 解码，
        #   写成 UTF-8 的话中文路径会变成乱码，move 直接失败。
        with open(script, "w", encoding="mbcs", errors="replace",
                  newline="\r\n") as fh:
            fh.write(body)
    except OSError as e:
        return False, "写入替换脚本失败：%s" % e

    if not dispatch:
        # 自测用：只生成脚本、不真的执行。派发后脚本会等主进程退出，
        # 紧接着替换并删掉备份与自身——探针再去找文件必然扑空。
        return True, script

    try:
        subprocess.Popen(["cmd", "/c", script],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         close_fds=True)
    except OSError as e:
        return False, "无法启动替换脚本：%s" % e
    return True, "程序即将退出并完成替换，完成后会自动重新打开"


def pending_update_file():
    """上次更新是否已下载好新 exe（等主程序起来后替换）。

    主程序启动时先看这个：非空说明上次更新器下载完了但没替换成功
    （比如用户当时强制关掉了程序）。
    """
    work = data_dir()
    try:
        names = [n for n in os.listdir(work)
                 if n.startswith("视频工具箱-new-") and n.endswith(".exe")]
    except OSError:
        return ""
    if not names:
        return ""
    return os.path.join(work, max(names, key=lambda n: os.path.getmtime(
        os.path.join(work, n))))


def consume_last_result():
    """读取并清掉上次的替换结果，供界面提示。返回 ""/"OK"/"FAILED"。"""
    p = os.path.join(data_dir(), "last_update_result.txt")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            txt = fh.read().strip()
    except Exception:  # noqa: BLE001
        return ""
    try:
        os.remove(p)
    except OSError:
        pass
    return txt


def cleanup_stale(max_age_days=7):
    """清理过期的新旧 exe 暂存（避免 data\\update 越攒越大）。"""
    work = data_dir()
    cut = time.time() - max_age_days * 86400
    n = 0
    try:
        names = os.listdir(work)
    except OSError:
        return 0
    for nm in names:
        if not (nm.startswith("视频工具箱-new-") or nm.startswith("视频工具箱-old-")
                or nm.startswith("apply_update_")):
            continue
        p = os.path.join(work, nm)
        try:
            if os.path.getmtime(p) < cut:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n