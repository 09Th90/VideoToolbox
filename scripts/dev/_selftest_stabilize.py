# -*- coding: utf-8 -*-
# @version 2.3.1
"""calib_stabilize 自检（离线，不联网、不起 ffmpeg 子进程以外的外部依赖）。

覆盖：套话语速幽灵丢弃 / 正常语速套话观测 / 英文套话观测 / 复读丢弃 /
续句合并（含说话人与方括号阻断）/ filler 三明治 / 超长拆分 / CRLF+BOM 保全 /
序号重排与结构不变量。

用法：tools\\python\\python.exe scripts\\dev\\_selftest_stabilize.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
#: 脚本位于 <仓库根>/scripts/dev/ ⇒ 上两层才是仓库根（勿多剥一层）
_VT_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(_VT_ROOT, "src"))
import calib_stabilize as st  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + extra) if extra else ""))
    if not cond:
        FAIL.append(name)


def cue(num, s, e, lines):
    return st.Cue(num, s, e, lines, 0, 0)


# ---------- 1. 套话语速幽灵（JA，>20 字/秒）----------
c = cue("1", 0, 300, ["おわり"])          # 3 加权字 / 0.3s = 10 字/秒 → 不丢
drops, obs = st.find_drop_candidates([c], "mono")
check("正常语速套话不丢弃", not drops and any(o["kind"] == "套话语速正常" for o in obs),
      str([o["kind"] for o in obs]))
c = cue("1", 0, 100, ["おわり"])          # 3 / 0.1s = 30 字/秒 → 丢
drops, obs = st.find_drop_candidates([c], "mono")
check("语速幽灵丢弃", len(drops) == 1 and drops[0]["reason"] == "套话幽灵·语速不可能",
      str(drops[:1]))
c = cue("1", 0, 100, ["それではまた"])     # 6 / 0.1 = 60 字/秒 → 丢
drops, _ = st.find_drop_candidates([c], "mono")
check("それではまた 语速幽灵", len(drops) == 1)
c = cue("1", 0, 11600, ["Thank you."])    # 英文族：拉长形态，只观测
drops, obs = st.find_drop_candidates([c], "mono")
check("英文套话只观测", not drops and any(o["kind"] == "英文套话疑似" for o in obs))
c = cue("1", 0, 100, ["Thank you."])      # 英文族：即使压缩也不自动丢（证据门控）
drops, obs = st.find_drop_candidates([c], "mono")
check("英文套话压缩也只观测", not drops)

# ---------- 2. 复读幻觉（tandem ≥4 轮 ≥32 单位）----------
c = cue("1", 0, 2000, ["测试" * 16])          # 32 符号 / 32 单位，motif×16
drops, _ = st.find_drop_candidates([c], "mono")
check("复读幻觉丢弃", len(drops) == 1 and drops[0]["reason"] == "复读幻觉", str(drops[:1]))
c = cue("1", 0, 2000, ["测试" * 8])           # 16 单位 < 32 → 不丢（门槛原值）
drops, _ = st.find_drop_candidates([c], "mono")
check("跨度不足 32 单位不丢弃", not drops)
c = cue("1", 0, 2000, ["测试测试测试"])     # 3 轮 < 4 → 不丢
drops, _ = st.find_drop_candidates([c], "mono")
check("三轮复读不丢弃", not drops)
c = cue("1", 0, 2000, ["哈哈哈哈哈哈哈哈哈哈哈哈"])  # 12 次 > 7 → 观测
_, obs = st.find_drop_candidates([c], "mono")
check("复读超 7 次只观测", any(o["kind"] == "复读超 7 次未塌缩" for o in obs))

# ---------- 3. 续句合并 ----------
def bi(num, s, e, zh, ref):
    return cue(num, s, e, [zh, ref])

a = bi("1", 0, 1100, "メミじゃなくて、", "メミじゃなくて、")
b = bi("2", 1100, 2400, "ユメじゃなくて", "ユメじゃなくて")
applies, specials = st.find_merge_candidates([a, b], "bi")
check("续句合并候选", len(applies) == 1 and applies[0]["kind"] == "续句合并"
      and applies[0]["cues"] == ("1", "2"), str(applies))
a2 = bi("1", 0, 1100, "我说完了。", "I done.")
applies, _ = st.find_merge_candidates([a2, b], "bi")
check("上条收句不合并", not applies)
a3 = bi("1", 0, 1100, ">>主播：你好", "hello")
b3 = bi("2", 1100, 2400, ">>嘉宾：你好", "hi")
applies, _ = st.find_merge_candidates([a3, b3], "bi")
check("换人不合并", not applies)
a4 = bi("1", 0, 1100, "[音乐]前奏", "[music]")
applies, _ = st.find_merge_candidates([a4, b], "bi")
check("方括号标记不合并", not applies)
a5 = bi("1", 0, 1100, "嗯", "um")
applies, _ = st.find_merge_candidates([a5, b], "bi")
check("纯填充词不向前合并", not applies)
# 越硬门槛 → 特批候选（不自动应用）
a6 = bi("1", 0, 2000, "这是一个很长的没有标点的句子碎片", "long frag")
b6 = bi("2", 2000, 4300, "然后继续另一个同样很长的碎片", "long frag2")
applies, specials = st.find_merge_candidates([a6, b6], "bi")
check("越硬门槛只列特批候选", not applies and len(specials) == 1, str(specials))
# 越过绝对门槛 → 连候选都没有
a7 = bi("1", 0, 7000, "超长" * 30, "x")
b7 = bi("2", 7000, 14000, "超长" * 30, "y")
applies, specials = st.find_merge_candidates([a7, b7], "bi")
check("越绝对门槛无候选", not applies and not specials)

# ---------- 4. filler 三明治 ----------
f1 = bi("1", 0, 1000, "这句话还没说完", "frag")
f2 = bi("2", 1000, 1300, "嗯", "um")
f3 = bi("3", 1300, 2600, "马上就要说完了", "frag2")
applies, _ = st.find_merge_candidates([f1, f2, f3], "bi")
check("filler 三明治合并", len(applies) == 1 and applies[0]["kind"] == "filler 三明治"
      and applies[0]["cues"] == ("1", "2", "3"), str(applies))

# ---------- 5. 超长拆分 ----------
long_zh = "不同的视野和扭曲的噩梦至今仍深深烙印在我的眼睛里。那扭曲的景象依然清晰地留在脑海之中。"
long_ref = "The distorted vision remains clear in my mind even now."
c = bi("1", 0, 3000, long_zh, long_ref)
splits, obs = st.find_split_candidates([c], "bi")
check("超长 cue 拆分候选", len(splits) == 1 and len(splits[0]["pieces"]) >= 2,
      str(splits[:1]))
check("参考行同步拆", bool(splits and splits[0]["ref_pieces"]))
c2 = bi("1", 0, 3000, "短句", "short")
splits, _ = st.find_split_candidates([c2], "bi")
check("正常 cue 不拆", not splits)
c3 = bi("1", 0, 9000, "没有标点的超长台词" * 8, "no punct " * 8)
splits, obs = st.find_split_candidates([c3], "bi")
check("超长无标点只观测", not splits and any(o["kind"] == "超长无标点" for o in obs))

# ---------- 6. 应用：合并 + CRLF/BOM 保全 ----------
raw = ("1\r\n00:00:00,000 --> 00:00:01,100\r\nメミじゃなくて、\r\nメミじゃなくて、\r\n"
       "\r\n2\r\n00:00:01,100 --> 00:00:02,400\r\nユメじゃなくて\r\nユメじゃなくて\r\n")
_tmp = tempfile.mkdtemp(prefix="vt_stabilize_")
path = os.path.join(_tmp, "in.srt")
with open(path, "wb") as f:
    f.write(b"\xef\xbb\xbf" + raw.encode("utf-8"))
rc = st.run(path, out=os.path.join(_tmp, "out.srt"))
out_raw = open(os.path.join(_tmp, "out.srt"), "rb").read()
check("应用退出码 0", rc == 0, str(rc))
check("BOM 保全", out_raw.startswith(b"\xef\xbb\xbf"))
check("CRLF 保全", b"\r\n" in out_raw and out_raw.count(b"\n") == out_raw.count(b"\r\n"))
out_text = out_raw.decode("utf-8-sig").replace("\r\n", "\n")
check("合并后单 cue", out_text.count("-->") == 1, out_text)
check("序号重排为 1", out_text.startswith("1\n"), repr(out_text[:20]))
check("时间轴取首尾跨度", "00:00:00,000 --> 00:00:02,400" in out_text)
check("参考行依次保留", "メミじゃなくて、ユメじゃなくて" in out_text)
# 结构自检：非 cue 行（无）与空行分隔
check("无连续空行", "\r\n\r\n\r\n" not in out_text)

# ---------- 7. 报告退出码 ----------
rc2 = st.run(path)          # 不带 --out：纯报告
check("报告模式退出码 1（有候选）", rc2 == 1, str(rc2))

for p in ("_st_test_in.srt", "_st_test_out.srt"):
    fp = os.path.join(_tmp, p)
    if os.path.exists(fp):
        os.remove(fp)
shutil.rmtree(_tmp, ignore_errors=True)

print()
print("FAILED: %d" % len(FAIL) if FAIL else "ALL PASS")
sys.exit(1 if FAIL else 0)
