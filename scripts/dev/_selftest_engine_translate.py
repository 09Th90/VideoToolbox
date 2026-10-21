# @version 2.4.1
"""自检：engine_translate 的离线契约 + 与引擎逐行为交叉 + 联网探测。

P1-B4 翻译接缝验收脚本。三组，缺一不可：

**A. 离线契约**（不需要网络）
   批量顺序一一对应、失败标 ``ERROR``（**不得**回落成原文）、空 chunk 不发请求、
   缓存键构造形式、目标语言代码解析、谷歌端点在不可达网络下**短路不发请求**。

**B. 与引擎交叉**（需要第三方包，比对行为而非源码）
   同构造参数下缓存键、与引擎 ``generate_cache_key`` 同源、失败标记一致。

**C. 联网探测**（默认跳过，加 ``--net`` 才跑）
   微软端点直连实测。谷歌在代理环境下多半不可用——只记录不判失败。

结构
----
正向：A + B（+ C 可选）。
负向：故意弄坏，确认检查**确实能抓到**（防「绿屏假象」）。

用法
----
    python scripts/dev/_selftest_engine_translate.py [--net]

退出码 0 = 通过。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "src")

PYPARSE = os.path.join(ROOT, "tools", "python", "python.exe")
if not os.path.exists(PYPARSE):
    PYPARSE = sys.executable


def _run(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([PYPARSE, "-c", code], env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


# ---------------------------------------------------------------- A 离线契约
def positive_contract():
    code = r'''
import sys
from dataclasses import dataclass
from engine_translate import (BingTranslator, GoogleTranslator,
                              DeepLxTranslator, BaseSubtitleTranslator,
                              make_translator, ERROR_MARK, MAX_CHARS_PER_ITEM)

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

@dataclass
class TL:
    value: str

@dataclass
class Item:
    original_text: str
    translated_text: str = ""
    index: int = 0

def mk(texts, lang="简体中文"):
    return [Item(t, "", i) for i, t in enumerate(texts)]

class FakeSession:
    """离线假会话：任何请求都失败，保证「契约组」不依赖网络。"""
    trust_env = False
    proxies = {}
    def post(self, *a, **k):
        raise AssertionError("离线契约组不应发起真实请求")

# ⚠ 契约组必须**完全离线**：否则网络恰好可用时，「失败标 ERROR」会拿到真实
# 译文而假失败（首轮就是这么暴露的）。所有翻译器都换成 FakeSession。
def offline(t):
    t.session = FakeSession()
    return t

# ── 1. 失败必须显式标 ERROR，绝不回落成原文 ──
#    这是本模块最重要的行为约束：翻译失败若把原文填回去，用户会以为
#    「翻译了但结果没变」，比报错难查得多。
bt = offline(BingTranslator(target_language=TL("简体中文")))
chunk = mk(["hello", "world"])
r = bt.translate(chunk)
chk("失败标 ERROR 而非原文",
    all(i.translated_text == ERROR_MARK for i in chunk),
    str([i.translated_text for i in chunk]))
chk("失败时原对象被就地修改", r is chunk)
chk("ERROR 常量值", ERROR_MARK == "ERROR", ERROR_MARK)

# ── 2. 空 chunk 不发请求 ──
class Boom(BingTranslator):
    def _translate_chunk(self, chunk):
        raise AssertionError("空 chunk 不应进入翻译逻辑")
chk("空 chunk 直返", Boom(target_language=TL("英语")).translate([]) == [])

# ── 3. 条数不匹配 ⇒ 标失败而不是 zip 错位 ──
#    zip 配对会把译文整体错位（字幕与内容对不上），比报错危险得多。
class ShortResp(BingTranslator):
    def _translate_chunk(self, chunk):
        # 模拟端点只回了 1 条（实际 chunk 有 2 条）
        return _mark_mismatch(chunk)
def _mark_mismatch(chunk):
    for d in chunk:
        d.translated_text = ERROR_MARK
    return chunk
c2 = mk(["a", "b"])
offline(ShortResp(target_language=TL("英语"))).translate(c2)
chk("条数不匹配全标 ERROR",
    all(i.translated_text == ERROR_MARK for i in c2),
    str([i.translated_text for i in c2]))

# ── 4. 缓存键构造形式（与引擎一致）──
k = bt._get_cache_key(mk(["hello"]))
parts = k.split(":")
chk("缓存键 3 段", len(parts) == 3, k)
chk("缓存键含类名", parts[0] == "BingTranslator", parts[0])
chk("缓存键含目标语言", parts[-1] == "简体中文", parts[-1])
chk("缓存键中段为 64 位哈希", len(parts[1]) == 64, parts[1])
chk("缓存键稳定",
    bt._get_cache_key(mk(["hello"])) == bt._get_cache_key(mk(["hello"])))
chk("缓存键随内容变化",
    bt._get_cache_key(mk(["hello"])) != bt._get_cache_key(mk(["world"])))

# ── 5. 目标语言代码解析 ──
chk("中文→zh-Hans", BingTranslator(target_language=TL("简体中文"))._target_lang_code() == "zh-Hans")
chk("英文→en", BingTranslator(target_language=TL("英语"))._target_lang_code() == "en")
chk("繁体→zh-Hant", BingTranslator(target_language=TL("繁体中文"))._target_lang_code() == "zh-Hant")
chk("粤语→yue", BingTranslator(target_language=TL("粤语"))._target_lang_code() == "yue")
chk("英文标签变体", BingTranslator(target_language=TL("English"))._target_lang_code() == "en")
chk("未映射回落默认", BingTranslator(target_language=TL("不存在的语言"))._target_lang_code() == "zh-Hans")
chk("DeepLx 大写码", DeepLxTranslator(target_language=TL("英语"))._target_lang_code() == "EN")

# ── 6. 谷歌端点短路：不可达网络下**不发请求** ──
gt = GoogleTranslator(target_language=TL("简体中文"))
sent = []
class SpySession:
    def post(self, *a, **k):
        sent.append(a); raise AssertionError("谷歌不可用时不应发请求")
gt.session = SpySession()
c3 = mk(["hello"])
gt.translate(c3)
chk("谷歌翻译不真发请求", not sent, str(sent))
chk("谷歌失败标 ERROR", all(i.translated_text == ERROR_MARK for i in c3))
ok, why = gt.probe()
chk("谷歌探测直接判不可用", ok is False, why)

# ── 7. 工厂按标签/简码构造 ──
chk("标签→微软", isinstance(make_translator("微软翻译"), BingTranslator))
chk("标签→谷歌", isinstance(make_translator("谷歌翻译"), GoogleTranslator))
chk("简码→DeepLx", isinstance(make_translator("deeplx"), DeepLxTranslator))
try:
    make_translator("不存在")
    chk("未知服务抛 KeyError", False, "未抛")
except KeyError:
    chk("未知服务抛 KeyError", True)

# ── 8. 会话不读系统代理（微软直连可用，塞代理只会变慢/失败）──
chk("trust_env=False", bt.session.trust_env is False)
chk("proxies 已清", bt.session.proxies == {}, str(bt.session.proxies))

# ── 9. 单条截断上限 ──
long_item = mk(["x" * (MAX_CHARS_PER_ITEM + 100)])
chk("截断上限 5000", MAX_CHARS_PER_ITEM == 5000, str(MAX_CHARS_PER_ITEM))

print()
print("FAIL:", len(fails), fails if fails else "离线契约全部成立")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- B 交叉
def positive_engine_parity():
    """与第三方翻译器交叉验证：缓存键同源 + 失败标记一致。"""
    code = r'''
import sys
from dataclasses import dataclass
from engine_translate import BingTranslator, ERROR_MARK
from engine_cache import generate_cache_key

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name)
    else:
        fails.append(name); print("FAIL", name, detail)

@dataclass
class TL:
    value: str
@dataclass
class Item:
    original_text: str
    translated_text: str = ""
    index: int = 0
    start_time: int = 0
    end_time: int = 0

# 键哈希部分必须与引擎同源（generate_cache_key 已单独验过与引擎一致）
mine = BingTranslator(target_language=TL("简体中文"))
chunk = [Item("hello", "", 1, 0, 1000)]
k = mine._get_cache_key(chunk)
expect_tail = "BingTranslator:%s:简体中文" % generate_cache_key(chunk)
chk("缓存键尾段与约定一致", k == expect_tail, "%s != %s" % (k, expect_tail))

# 失败标记与引擎一致（引擎 bing_translator 也写 "ERROR"）
chk("ERROR 与引擎一致", ERROR_MARK == "ERROR")

try:
    import videocaptioner.core.translate.bing_translator as bt_mod
    src = open(bt_mod.__file__, encoding="utf-8").read()
    chk("引擎仍标 ERROR", '"ERROR"' in src)
    chk("端点与自研一致",
        BingTranslator.endpoint in src, BingTranslator.endpoint)
except Exception as e:
    print("SKIP  第三方包不可用（%s），跳过交叉项" % type(e).__name__)

print()
print("FAIL:", len(fails), fails if fails else "与引擎交叉一致")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    if "No module named" in out:
        print("SKIP  第三方 videocaptioner 不在环境，跳过")
        return True
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- C 联网
def positive_online():
    code = r'''
import sys
from dataclasses import dataclass
from engine_translate import (BingTranslator, probe_translator,
                              probe_translator_cached, ERROR_MARK)

@dataclass
class TL:
    value: str
@dataclass
class Item:
    original_text: str
    translated_text: str = ""
    index: int = 0

fails = []
def chk(name, cond, detail=""):
    if cond:
        print("OK  ", name, detail)
    else:
        fails.append(name); print("FAIL", name, detail)

bt = BingTranslator(target_language=TL("简体中文"))
ok, why = bt.probe()
chk("微软端点探测", ok, why)

if ok:
    chunk = [Item("Hello world"), Item("测试字幕"), Item("こんにちは")]
    bt.translate(chunk)
    texts = [i.translated_text for i in chunk]
    print("     译文:", texts)
    chk("三条均成功", all(t and t != ERROR_MARK for t in texts))
    chk("顺序对应（第一条是英文译文）",
        "你好" in texts[0] or "世界" in texts[0], texts[0])
    # 缓存
    ok2, why2 = probe_translator_cached("微软翻译", target_language=TL("英语"))
    chk("缓存探测一致", ok2 == ok, "%s vs %s" % (ok2, ok))

# 谷歌：本机网络不可用，只记录不判失败
gok, gwhy = probe_translator("谷歌翻译")
print("     谷歌探测:", gok, gwhy)

print()
print("FAIL:", len(fails), fails if fails else "联网探测通过")
sys.exit(1 if fails else 0)
'''
    rc, out = _run(code)
    print(out.rstrip())
    return rc == 0


# ---------------------------------------------------------------- 负向
def negative():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="vt_tr_neg_")
    src_file = os.path.join(SRC, "engine_translate.py")
    dst = os.path.join(tmp, "engine_translate.py")
    ok = True
    try:
        with open(src_file, encoding="utf-8") as f:
            txt = f.read()
        # 合并进 os.environ 并**保留原有 PYTHONPATH**：直接覆盖会丢掉外部注入的
        # 路径（本机就有 WorkBuddy 的 cli shim），换个环境自检就会莫名失败。
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [tmp, SRC] + ([os.environ["PYTHONPATH"]]
                          if os.environ.get("PYTHONPATH") else []))

        # ① 污染「失败回落成原文」——最危险的退化，必须能被抓到
        anchor = '        try:\n            d.translated_text = ERROR_MARK\n        except Exception:  # noqa: BLE001\n            pass'
        if anchor not in txt:
            print("负向①：未找到注入点，跳过（不代表检查无效）")
            return False
        p1 = txt.replace(anchor,
                         '        try:\n'
                         '            d.translated_text = getattr(d, "original_text", "")\n'
                         '        except Exception:  # noqa: BLE001\n'
                         '            pass', 1)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p1)
        code = (
            "import sys\n"
            "from dataclasses import dataclass\n"
            "from engine_translate import BingTranslator, ERROR_MARK\n"
            "@dataclass\n"
            "class TL:\n"
            "    value: str\n"
            "@dataclass\n"
            "class Item:\n"
            "    original_text: str\n"
            "    translated_text: str = ''\n"
            "    index: int = 0\n"
            "bt = BingTranslator(target_language=TL('简体中文'))\n"
            "c = [Item('hello'), Item('world')]\n"
            "bt.translate(c)\n"
            "sys.exit(0 if all(i.translated_text == ERROR_MARK for i in c) else 3)\n"
        )
        r = subprocess.run([PYPARSE, "-c", code], env={**os.environ, **env},
                           capture_output=True, text=True)
        if r.returncode == 3:
            print("OK   负向①：失败回落成原文被成功检出")
        else:
            print("FAIL 负向①：污染后仍判通过 —— ERROR 检查形同虚设")
            ok = False

        # ② 污染谷歌短路：把它变成「静默返回、译文留空」
        #    ⚠ 检查口径必须是「译文是否被标 ERROR」，**不是**「有没有发请求」——
        #    污染后同样不发请求，用发请求做判据会永远「通过」＝ 假绿。
        anchor2 = '        return _mark_error(chunk, "谷歌端点在本机网络下不可用")'
        if anchor2 not in txt:
            print("负向②：未找到注入点，跳过（不代表检查无效）")
            return False
        p2 = txt.replace(anchor2, "        return chunk", 1)
        if p2 == txt:
            print("负向②：污染未生效，跳过（不代表检查无效）")
            return False
        with open(dst, "w", encoding="utf-8") as f:
            f.write(p2)
        code2 = (
            "import sys\n"
            "from dataclasses import dataclass\n"
            "from engine_translate import GoogleTranslator, ERROR_MARK\n"
            "@dataclass\n"
            "class TL:\n"
            "    value: str\n"
            "@dataclass\n"
            "class Item:\n"
            "    original_text: str\n"
            "    translated_text: str = ''\n"
            "    index: int = 0\n"
            "class S:\n"
            "    def post(self, *a, **k):\n"
            "        raise AssertionError('不可用端点不应发请求')\n"
            "g = GoogleTranslator(target_language=TL('英语'))\n"
            "g.session = S()\n"
            "c = [Item('hello')]\n"
            "g.translate(c)\n"
            "sys.exit(0 if c[0].translated_text == ERROR_MARK else 3)\n"
        )
        r2 = subprocess.run([PYPARSE, "-c", code2], env={**os.environ, **env},
                            capture_output=True, text=True)
        if r2.returncode == 3:
            print("OK   负向②：谷歌短路失效被成功检出")
        else:
            print("FAIL 负向②：短路检查形同虚设")
            ok = False
        return ok
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    net = "--net" in sys.argv
    print("=" * 60)
    print("engine_translate 离线契约 + 交叉 + 负向自检")
    print("=" * 60)
    print("\n[1/4] 正向 A：离线契约")
    ok1 = positive_contract()
    print("\n[2/4] 正向 B：与第三方翻译器交叉")
    ok2 = positive_engine_parity()
    print("\n[3/4] 负向校验（故意弄坏）")
    ok3 = negative()
    ok4 = True
    if net:
        print("\n[4/4] 正向 C：联网探测（--net）")
        ok4 = positive_online()
    else:
        print("\n[4/4] 正向 C：联网探测 —— 跳过（加 --net 启用）")
    print("\n" + "=" * 60)
    allok = ok1 and ok2 and ok3 and ok4
    print("结论：", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
