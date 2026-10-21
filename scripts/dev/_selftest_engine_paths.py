# @version 2.5.0
"""自检：engine_paths 的路径不变量 + 对第三方 config 的属性覆盖率。

P1-B1 config 接缝验收脚本。

判定口径不是「路径能算出来」而是三条硬不变量 + 一条覆盖率：

1. **不落系统盘**：所有可写路径必须在 ``data_dir`` 之下。这是接缝存在的
   全部理由——上游 ``config.py`` 默认写 ``%LOCALAPPDATA%`` / ``Path.home()``。
2. **settings.json 同址**：与既有 ``video_toolbox.vc_settings_path()`` 必须
   同址，否则新旧代码读写两个文件、用户设置「静默丢失」。
3. **纯计算**：构造 ``EnginePaths`` 不碰文件系统（否则自检会污染真实安装
   目录，且无法在临时目录里安全构造）。
4. **覆盖率**：``apply_to`` 必须写满引擎 ``config`` 实际存在的全部路径常量。
   引擎升级新增常量时，这项会失败并指名缺哪个——这正是把接管收敛到
   自研模块换来的东西。

结构
----
正向：不变量 + 与引擎真实常量名交叉比对 + 端到端重定向行为。
负向：故意破坏不变量，确认检查**确实能抓到**（防「绿屏假象」）。

用法
----
    python scripts/dev/_selftest_engine_paths.py

退出码 0 = 通过。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

#: 用随包 CPython 跑（托管 python 无第三方依赖树）
PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):  # 退化：当前解释器
    PYPARSE = sys.executable

#: 必须落在 data_dir 之下的可写路径（防落系统盘）
WRITABLE_ATTRS = [
    "root_path", "appdata_path", "work_path", "log_path", "llm_log_file",
    "settings_path", "cache_path", "model_path", "subtitle_style_path",
    "resource_path", "assets_path", "translations_path", "cli_config_dir",
    "cli_config_file",
]

#: 可写路径在生成代码里的占位符（用 str.replace 注入，避免 % 与代码内 % 打架）
_ATTRS_SLOT = "@@WRITABLE_ATTRS@@"


def _run(code, extra_env=None, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([PYPARSE, "-c", code], env=env, cwd=cwd,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ---------------------------------------------------------------- 正向
def positive_invariants():
    """不变量 + 纯计算 + 引擎常量名覆盖率（不需要第三方包）。"""
    body = r'''
import sys, os, tempfile
from pathlib import Path
from engine_paths import EnginePaths, REDIRECT_FLAG

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

tmp = tempfile.mkdtemp(prefix="vt_paths_")
data = Path(tmp) / "data" / "VideoCaptioner"
tools = Path(tmp) / "tools"
bundled = Path(tmp) / "res"
p = EnginePaths(data_dir=data, tools_dir=tools, bundled_resource_dir=bundled,
                vc_name="VideoCaptioner")

# 1. 构造不得碰文件系统（纯计算）
chk("纯计算-构造不建目录", not data.exists(),
    "构造后目录已存在: " + str(data))

# 2. 可写路径全部在 data_dir 之下
def _under(child, root):
    try:
        Path(child).relative_to(Path(root)); return True
    except ValueError:
        return False
for a in @@WRITABLE_ATTRS@@:
    v = getattr(p, a)
    chk("不落系统盘-" + a, _under(v, data), str(v) + " 不在 data_dir 之下")

# 3. settings.json 直接位于 data_dir 之下，且与 vc_settings_path 同址
chk("settings-同址", Path(p.settings_path) == Path(data) / "settings.json",
    str(p.settings_path))
chk("settings-文件名", Path(p.settings_path).name == "settings.json")
chk("root==appdata", p.root_path == p.appdata_path)
chk("llm_log 在 logs 下", _under(p.llm_log_file, p.log_path))

# 4. 关键路径名与引擎 config 的常量语义对齐
chk("cache-目录名", Path(p.cache_path).name == "cache")
chk("work-dir-目录名", Path(p.work_path).name == "work-dir")
chk("bin_path==tools_dir", Path(p.bin_path) == tools)
chk("fw-path 名", Path(p.faster_whisper_path).name == "Faster-Whisper-XXL")

# 5. 随包资源目录不存在时回退到 data_dir/resource
p2 = EnginePaths(data_dir=data, tools_dir=tools,
                 bundled_resource_dir=Path(tmp) / "不存在")
chk("资源回退", Path(p2.resource_path) == Path(data) / "resource",
    str(p2.resource_path))

# 6. ensure_dirs 幂等 + 返回真实目录；不抛异常
made1 = p.ensure_dirs()
made2 = p.ensure_dirs()
chk("ensure_dirs-建目录", Path(p.log_path).is_dir() and Path(p.cache_path).is_dir())
chk("ensure_dirs-幂等", len(made2) == len(made1),
    str(len(made1)) + " vs " + str(len(made2)))
chk("ensure_dirs-风格目录", Path(p.subtitle_style_path).is_dir())

# 7. apply_to 写入全部契约属性
class FakeCfg:  # 模拟第三方 config 模块
    pass
cfg = FakeCfg()
written = p.apply_to(cfg)
expect = ["ROOT_PATH","APPDATA_PATH","WORK_PATH","LOG_PATH","LLM_LOG_FILE",
          "SETTINGS_PATH","CACHE_PATH","MODEL_PATH","RESOURCE_PATH",
          "ASSETS_PATH","TRANSLATIONS_PATH","SUBTITLE_STYLE_PATH","BIN_PATH",
          "FASTER_WHISPER_PATH"]
missing = [k for k in expect if k not in written]
chk("apply_to-覆盖率", not missing, str(missing))
chk("apply_to-实际生效", str(getattr(cfg, "SETTINGS_PATH")) == str(p.settings_path))
chk("apply_to-CACHE_PATH", str(getattr(cfg, "CACHE_PATH")) == str(p.cache_path))

print()
print("FAIL:", len(fails), fails if fails else "不变量全部成立")
sys.exit(1 if fails else 0)
'''
    body = body.replace(_ATTRS_SLOT, repr(WRITABLE_ATTRS))
    rc, out = _run(body)
    print(out.rstrip())
    return rc == 0

def positive_engine_parity():
    """与第三方 ``videocaptioner.config`` 交叉验证：属性名覆盖率 + 同址。

    这是本接缝的核心验收——``apply_to`` 写出的属性名集合必须**覆盖**引擎
    config 里全部**可重定向**的 Path 常量。引擎升级新增常量时这项会指名缺失。

    三点口径澄清（都踩过）：
    * ``_`` 前缀的常量（``_BUNDLED_FONTS`` / ``_PACKAGE_DIR`` / ``_PROJECT_ROOT``）
      是**引擎包自身位置**，不是可重定向数据路径——必须保持指向包真实位置，
      覆盖它们反而会弄坏引擎。因此只要求「不被误改」，不要求「被覆盖」。
    * ``FONTS_PATH`` 有回退分支（随包 fonts 缺失时用引擎内置字体），比对时
      要接受回退值。
    * 「不落系统盘」必须检查 **apply 之后**的值；检查快照只会看到上游默认值。
    """
    code = r'''
import sys, os, tempfile
from pathlib import Path
from engine_paths import EnginePaths, apply_engine_paths
import videocaptioner.config as vc_cfg

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

tmp = tempfile.mkdtemp(prefix="vt_paths_par_")

# ── 取证：apply 之前引擎默认指向哪里（这正是本接缝要纠正的问题）──
before = {n: str(v) for n, v in vars(vc_cfg).items()
          if isinstance(v, Path) and n.isupper() and not n.startswith("_")}
sys_dir_before = sorted(n for n, v in before.items()
                        if "appdata" in v.lower()
                        or v.lower().startswith(os.path.expanduser("~").lower()))
print("重定向前指向系统盘的常量:", ", ".join(sys_dir_before) or "(无)")
chk("取证-上游确实写系统盘", len(sys_dir_before) >= 5,
    "仅 %d 个：%s" % (len(sys_dir_before), sys_dir_before))

# ── 施加自研路径 ──
p = EnginePaths(data_dir=Path(tmp) / "VideoCaptioner",
                tools_dir=Path(tmp) / "tools",
                bundled_resource_dir=Path(tmp) / "res")
written = apply_engine_paths(vc_cfg, p,
                             fallback_fonts_dir=getattr(vc_cfg, "_BUNDLED_FONTS", None))

# ── 1) 可重定向常量：必须被覆盖且与自研取值同址 ──
redirectable = [n for n in sorted(before)
                if not n.startswith("_") and n != "FONTS_PATH"]
uncovered, mismatched = [], []
for n in redirectable:
    got = getattr(vc_cfg, n, None)
    ours = getattr(p, n.lower(), None)
    if ours is None:
        uncovered.append(n); print("FAIL 未覆盖", n, "->", got); continue
    if Path(got) != Path(ours):
        mismatched.append(n)
        print("FAIL 值不一致", n, got, "!=", ours)
    else:
        print("OK   同址", n)
chk("可重定向常量全覆盖", not uncovered, str(uncovered))
chk("可重定向常量全部同址", not mismatched, str(mismatched))

# ── 2) FONTS_PATH：随包 fonts 缺失 → 允许回退到引擎内置字体 ──
fonts_now = Path(getattr(vc_cfg, "FONTS_PATH"))
fonts_ok = (fonts_now == Path(p.fonts_path)
            or fonts_now == Path(getattr(vc_cfg, "_BUNDLED_FONTS")))
chk("FONTS_PATH-同址或合法回退", fonts_ok, str(fonts_now))

# ── 3) 引擎包内部路径：不得被误改（改了会弄坏引擎）──
internal_ok = True
for n in ("_PACKAGE_DIR", "_PROJECT_ROOT", "_BUNDLED_FONTS"):
    if n in before:
        after = getattr(vc_cfg, n, None)
        if str(after) != before.get(n, str(after)):
            internal_ok = False; print("FAIL 引擎内部路径被误改", n, after)
chk("引擎内部路径未被误改", internal_ok)

# ── 4) 幂等标记 ──
chk("幂等标记已置", getattr(vc_cfg, "_VT_REDIRECT_DONE", False) is True)

# ── 5) apply 之后：可写**数据**常量必须在 data_dir 之下 ──
#    两个口径澄清：
#    a) 不能用「路径里有没有 /users/」来判——自检自身跑在 %TEMP% 下
#       （C:\Users\...\AppData\Local\Temp），会把临时目录误判成系统盘。
#       正确口径是「是否在 data_dir 之下」，与本模块的不变量一致。
#    b) BIN_PATH / FASTER_WHISPER_PATH 指向**随包只读二进制**（tools_dir），
#       按设计就不在 data_dir 下，须排除后再判。
BIN_ATTRS = ("BIN_PATH", "FASTER_WHISPER_PATH")


def _under(child, root):
    try:
        Path(child).relative_to(Path(root)); return True
    except ValueError:
        return False

escaped = [n for n in redirectable if n not in BIN_ATTRS
           and not _under(getattr(vc_cfg, n), p.data_dir)]
chk("重定向后可写数据常量全在 data_dir 下", not escaped, str(escaped))

bin_ok = (Path(getattr(vc_cfg, "BIN_PATH")) == Path(p.tools_dir)
          and Path(getattr(vc_cfg, "FASTER_WHISPER_PATH")).parent
          == Path(p.tools_dir))
chk("二进制常量指向 tools_dir", bin_ok,
    str(getattr(vc_cfg, "BIN_PATH")) + " / "
    + str(getattr(vc_cfg, "FASTER_WHISPER_PATH")))
print("     （对照：重定向前 %d 个常量指向系统盘，重定向后数据类逃逸 %d 个）"
      % (len(sys_dir_before), len(escaped)))

print()
print("FAIL:", len(fails), fails if fails else "与引擎 config 全面同址")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    if "ModuleNotFoundError" in out or "No module named" in out:
        print("SKIP  第三方 videocaptioner 不在当前解释器环境，跳过引擎交叉项")
        return True
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- 负向
def negative():
    """负向：故意破坏不变量，确认正向检查确实会失败。

    做两项：
      ① 把 ``cache_path`` 改成系统盘（模拟「回落成上游默认」）→ 不变量检查须失败；
      ② 把 ``apply_to`` 的属性表删掉一项 → 覆盖率检查须失败。
    """
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vt_paths_neg_")
    src_file = os.path.join(SRC, "engine_paths.py")
    dst = os.path.join(tmp, "engine_paths.py")
    ok = True
    try:
        with open(src_file, encoding="utf-8") as f:
            txt = f.read()

        # ① 污染：cache_path 指向 LOCALAPPDATA
        poisoned1 = txt.replace(
            'self.cache_path = self.data_dir / "cache"',
            'self.cache_path = Path(os.environ.get("LOCALAPPDATA", "C:/Temp")) / "cache"',
            1)
        if poisoned1 == txt:
            print("负向①：未找到注入点，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(poisoned1)

        code = (
            "import sys, tempfile, os\n"
            "from pathlib import Path\n"
            "from engine_paths import EnginePaths\n"
            "tmp = tempfile.mkdtemp()\n"
            "p = EnginePaths(data_dir=Path(tmp)/'d', tools_dir=Path(tmp)/'t',\n"
            "                bundled_resource_dir=Path(tmp)/'r')\n"
            "try:\n"
            "    Path(p.cache_path).relative_to(Path(p.data_dir)); sys.exit(0)\n"
            "except ValueError:\n"
            "    sys.exit(3)\n"
        )
        # 合并进 os.environ 并**保留原有 PYTHONPATH**：直接覆盖会丢掉外部注入的
        # 路径（本机就有 WorkBuddy 的 cli shim），换个环境自检就会莫名失败。
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [tmp, SRC] + ([os.environ["PYTHONPATH"]]
                          if os.environ.get("PYTHONPATH") else []))
        r = subprocess.run([PYPARSE, "-c", code], env={**os.environ, **env},
                           capture_output=True, text=True)
        if r.returncode == 3:
            print("OK   负向①：cache_path 污染到系统盘被成功检出")
        else:
            print("FAIL 负向①：污染后不变量检查仍然通过 —— 检查形同虚设")
            ok = False

        # ② 污染：属性表删掉 CACHE_PATH（模拟「引擎新增常量漏覆盖」的镜像情形）
        poisoned2 = txt.replace('"CACHE_PATH": self.cache_path,', "", 1)
        if poisoned2 == txt:
            print("负向②：未找到注入点，跳过")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(poisoned2)

        code2 = (
            "import sys\n"
            "from engine_paths import EnginePaths\n"
            "class F: pass\n"
            "p = EnginePaths(data_dir='d', tools_dir='t')\n"
            "sys.exit(0 if 'CACHE_PATH' in p.apply_to(F()) else 3)\n"
        )
        r2 = subprocess.run([PYPARSE, "-c", code2], env={**os.environ, **env},
                            capture_output=True, text=True)
        if r2.returncode == 3:
            print("OK   负向②：删掉属性后覆盖率检查成功检出")
        else:
            print("FAIL 负向②：覆盖率检查仍然通过 —— 检查形同虚设")
            ok = False
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("engine_paths 路径契约自检")
    print("=" * 60)
    print("\n[1/3] 正向：不变量 + 纯计算 + apply_to 覆盖率")
    ok1 = positive_invariants()
    print("\n[2/3] 正向：与第三方 videocaptioner.config 交叉验证")
    ok2 = positive_engine_parity()
    print("\n[3/3] 负向校验（故意弄坏）")
    ok3 = negative()
    print("\n" + "=" * 60)
    allok = ok1 and ok2 and ok3
    print("结论：", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
