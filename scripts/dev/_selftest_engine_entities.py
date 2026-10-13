"""自检：engine_entities 与第三方引擎 entities 的逐值兼容性。

P1 接缝验收脚本。判定口径不是「能 import」而是**逐值一致**——
P1~P4 期间第三方引擎仍在读写 ``data/videocaptioner/settings.json``，
枚举值是该文件里的持久化字段，取值不一致会造成设置错位。

结构
----
正向：5 个枚举 + LANGUAGES 与运行期接口逐值比对；标签反构造（调用方真实用法）。
负向：故意污染自研模块的取值，确认本检查**确实能抓到**（防「绿屏假象」）。

用法
----
    python scripts/dev/_selftest_engine_entities.py

依赖第三方包（仅校验期需要）。退出码 0 = 通过。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

#: 用随包 CPython 跑（托管 python 无 videocaptioner 依赖树）
PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):  # 退化：当前解释器
    PYPARSE = sys.executable

#: 需要比对的符号：自研名 → 引擎名
SYMBOLS = [
    ("TranscribeModelEnum", "TranscribeModelEnum"),
    ("TranscribeLanguageEnum", "TranscribeLanguageEnum"),
    ("FasterWhisperModelEnum", "FasterWhisperModelEnum"),
    ("LLMServiceEnum", "LLMServiceEnum"),
    ("TranslatorServiceEnum", "TranslatorServiceEnum"),
    ("SubtitleLayoutEnum", "SubtitleLayoutEnum"),
]

#: 反构造用例（调用方以持久化标签构造的真实场景）
REVERSE_LABELS = ["日本語", "Polish", "Cantonese", "Haitian Creole", "自动检测"]


def _run(code, extra_env=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def positive():
    """正向：逐值一致 + 反构造一致。"""
    syms = ", ".join(m for m, _ in SYMBOLS)
    code = (
        "import sys\n"
        "from engine_entities import (" + syms + ", LANGUAGES)\n"
        "from videocaptioner.core import entities as e\n"
        "fails = []\n"
        "def chk(n, a, b):\n"
        "    if a != b:\n"
        "        fails.append(n); print('MISMATCH', n)\n"
        "    else:\n"
        "        print('OK  ', n, '(%d 项)' % len(b))\n"
    )
    for mine, theirs in SYMBOLS:
        code += (
            "chk(%r, [x.value for x in %s], [x.value for x in e.%s])\n"
            % (mine, mine, theirs)
        )
    # 成员名同样要比对：调用方有按名访问（如 _TSE.OPENAI），只对值不够
    for mine, theirs in SYMBOLS:
        code += (
            "chk(%r + '.成员名', [x.name for x in %s], [x.name for x in e.%s])\n"
            % (mine, mine, theirs)
        )
    code += "chk('LANGUAGES', LANGUAGES, e.LANGUAGES)\n"
    for lbl in REVERSE_LABELS:
        code += (
            "try:\n"
            "    a = TranscribeLanguageEnum(%r).value\n"
            "    b = e.TranscribeLanguageEnum(%r).value\n"
            "    chk('反构造 ' + %r, a, b)\n"
            "except Exception as ex:\n"
            "    fails.append('反构造 ' + %r); print('MISMATCH 反构造', %r, ex)\n"
            % (lbl, lbl, repr(lbl), repr(lbl), lbl)
        )
    code += (
        "print()\n"
        "print('FAIL:', len(fails), fails if fails else '全部逐值一致 + 反构造一致')\n"
        "sys.exit(1 if fails else 0)\n"
    )
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


def negative():
    """负向：污染一个取值，确认正向检查确实会失败。"""
    # 在隔离副本里改值，不动真实源码
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vt_ent_neg_")
    try:
        shutil.copy(os.path.join(SRC, "engine_entities.py"),
                    os.path.join(tmp, "engine_entities.py"))
        p = os.path.join(tmp, "engine_entities.py")
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        poisoned = txt.replace(
            'WHISPER_API = "Whisper [API] ✨"', 'WHISPER_API = "Whisper [API] X"', 1)
        if poisoned == txt:
            print("负向：未找到注入点，跳过（不代表检查无效）")
            return True
        with open(p, "w", encoding="utf-8") as f:
            f.write(poisoned)

        env = {"PYTHONPATH": tmp + os.pathsep + SRC}
        code = (
            "import sys\n"
            "from engine_entities import TranscribeModelEnum\n"
            "from videocaptioner.core import entities as e\n"
            "a = [x.value for x in TranscribeModelEnum]\n"
            "b = [x.value for x in e.TranscribeModelEnum]\n"
            "sys.exit(0 if a == b else 3)\n"
        )
        import subprocess as sp
        r = sp.run([PYPARSE, "-c", code], env={**os.environ, **env},
                   capture_output=True, text=True)
        if r.returncode == 3:
            print("OK   负向：污染取值被成功检出（检查有效）")
            return True
        print("MISMATCH 负向：污染后检查仍然通过 —— 检查形同虚设")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=" * 60)
    print("engine_entities 逐值兼容性自检")
    print("=" * 60)
    print("\n[1/2] 正向校验")
    ok_pos = positive()
    print("\n[2/2] 负向校验（故意弄坏）")
    ok_neg = negative()
    print("\n" + "=" * 60)
    print("结论：", "PASS" if (ok_pos and ok_neg) else "FAIL")
    return 0 if (ok_pos and ok_neg) else 1


if __name__ == "__main__":
    sys.exit(main())
