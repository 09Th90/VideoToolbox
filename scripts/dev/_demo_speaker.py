# -*- coding: utf-8 -*-
# @version 1.18.3
"""生成「说话人分离」功能的可视化演示（演示用脚本，非程序运行依赖）。

跑法（任意目录）：
    tools\\python\\python.exe scripts\\dev\\_demo_speaker.py
产出到 <仓库根>/outputs/：
    说话人分离-演示.srt              合并单文件（行首带 [说话人N] 前缀）
    说话人分离-演示-说话人1.srt     独立轨（每人一份）
    说话人分离-演示-说话人2.srt
    说话人分离-演示.ass              彩色多人字幕（每说话人一条 Style）
    说话人分离-预览.html             可视化预览（用同一份配色板渲染）
"""
import html
import os
import sys

#: 脚本位于 <仓库根>/scripts/dev/，主程序源码在 <仓库根>/src
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src"))
import subtitle_editor_core as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "outputs")

# 播客式多人对话（用户原话里的例子 + 一段补充）
DIALOG = [
    (1000, 3200, "说话人1", "我觉得这个方案不行"),
    (3400, 5200, "说话人2", "我也这么看"),
    (5400, 7600, "说话人1", "那你们说怎么办"),
    (7800, 11200, "说话人3", "我建议先把数据跑一遍，别急着下结论"),
    (11400, 14600, "说话人2", "同意。上次就是因为没验证，返工了两周"),
    (14800, 17600, "说话人1", "行，那我今天把脚本写好"),
    (17800, 20400, "说话人3", "需要我帮忙就说"),
]


def ms_to_clock(ms):
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, milli)


def main():
    os.makedirs(OUT, exist_ok=True)
    cues = [C.Cue(a, b, t, spk) for a, b, spk, t in DIALOG]
    doc = C.SubtitleDoc(cues=list(cues))

    # 1) 合并单文件（前缀形态）
    with open(os.path.join(OUT, "说话人分离-演示.srt"), "wb") as fh:
        fh.write(doc.to_bytes())

    # 2) 独立轨（每人一份）
    tracks = C.split_by_speaker(cues)
    for spk, cs in tracks:
        if not cs:
            continue
        name = "说话人分离-演示-%s.srt" % spk
        with open(os.path.join(OUT, name), "wb") as fh:
            fh.write(C.SubtitleDoc(cues=list(cs)).to_bytes())

    # 3) 彩色 ASS
    ass = C.render_ass(cues, {"size": 46, "margin_v": 60})
    with open(os.path.join(OUT, "说话人分离-演示.ass"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(ass)

    # 4) 可视化预览（配色与 ASS 同源）
    cmap = C.speaker_color_map(C.cue_speakers(cues))
    rows, prev = [], None
    for a, b, spk, t in DIALOG:
        side = "left" if spk != prev else "left"
        rows.append(
            '<div class="row">'
            '<div class="t">%s</div>'
            '<div class="bub"><span class="who" style="color:%s">%s</span>'
            '<span class="say">%s</span></div></div>' % (
                ms_to_clock(a)[3:], cmap[spk], spk, html.escape(t)))
        prev = spk
    stats = "".join(
        "<tr><td><span class='dot' style='background:%s'></span>%s</td>"
        "<td>%d</td><td>%.1fs</td><td>%d</td></tr>"
        % (cmap[s], s, n, dur / 1000.0, ch)
        for s, n, dur, ch in C.speaker_stats(cues))
    styles = "".join(
        "<li><span class='dot' style='background:%s'></span>%s"
        " → <code>Style: Spk%d</code> / <code>Name=%s</code></li>"
        % (col, spk, i + 1, spk) for i, (spk, col) in enumerate(cmap.items()))

    page = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>说话人分离 · 演示</title><style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--fg:#1f2328;--mut:#6b7280}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);
 font:14px/1.6 "Microsoft YaHei",-apple-system,sans-serif}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:26px 0 10px}
.sub{color:var(--mut);font-size:13px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:18px 20px;max-width:880px}
.stage{background:#111418;border-radius:10px;padding:22px 20px;max-width:880px}
.row{display:flex;gap:12px;align-items:baseline;margin:9px 0}
.t{color:#7b8494;font-size:12px;width:52px;flex:none;font-variant-numeric:tabular-nums}
.bub{display:flex;gap:10px;align-items:baseline}
.who{font-weight:700;font-size:13px;flex:none}
.say{color:#fff;font-size:19px;font-weight:600;
 text-shadow:0 2px 0 #000,0 -2px 0 #000,2px 0 0 #000,-2px 0 0 #000}
table{border-collapse:collapse;width:100%;max-width:560px;font-size:13px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;
 margin-right:7px;vertical-align:-1px}
ul{margin:8px 0 0;padding-left:18px}li{margin:5px 0}
code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}
.f{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
.f span{background:#eef1f4;border:1px solid var(--line);border-radius:6px;
 padding:4px 9px;font-size:12px}
</style></head><body>
<h1>说话人分离（Diarization）· 效果演示</h1>
<div class="sub">同一份 cues，同时产出「合并单文件 / 独立轨 / 彩色多人字幕」三种形态。
配色由 <code>speaker_color_map()</code> 统一给出，预览与导出的 ASS 严格同色。</div>

<h2>① 彩色多人字幕（画面上看到的效果）</h2>
<div class="stage">__ROWS__</div>

<h2>② 说话人 → 颜色 / ASS Style 映射</h2>
<div class="card"><ul>__STYLES__</ul></div>

<h2>③ 逐人分析（speaker_stats）</h2>
<div class="card"><table>
<tr><th>说话人</th><th>条数</th><th>发言时长</th><th>字数</th></tr>__STATS__</table></div>

<h2>④ 导出产物</h2>
<div class="card">
<div class="f"><span>说话人分离-演示.srt（合并，带 [说话人N] 前缀）</span>
<span>说话人分离-演示-说话人1.srt</span><span>说话人分离-演示-说话人2.srt</span>
<span>说话人分离-演示-说话人3.srt</span>
<span>说话人分离-演示.ass（每说话人一条 Style）</span></div>
</div>
</body></html>"""
    page = (page.replace("__ROWS__", "".join(rows))
                .replace("__STYLES__", styles)
                .replace("__STATS__", stats))

    with open(os.path.join(OUT, "说话人分离-预览.html"), "w",
              encoding="utf-8") as fh:
        fh.write(page)

    print("已生成到", OUT)
    for f in sorted(os.listdir(OUT)):
        print("  ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
