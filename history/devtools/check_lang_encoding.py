# -*- coding: utf-8 -*-
"""校验 Inno Setup(6.7/LZMA2) 安装包内嵌语言消息编码：GBK(正确) vs UTF-8(乱码)"""
import lzma, struct

exe = r"installer\_编译验证临时包.exe"
data = open(exe, "rb").read()
print("exe 大小", len(data))

words = ["欢迎", "下一步", "上一步", "安装", "取消", "浏览", "完成", "简体中文", "许可协议"]
gbk = {w: w.encode("gbk") for w in words}
u8 = {w: w.encode("utf-8") for w in words}

def lzma2_dict_size(b):
    if b <= 39:
        return b
    return (2 | (b & 1)) << ((b >> 1) + 11)

sig = b"zlb\x1a"
pos = 0
blocks = 0
gtot = utot = 0
sample = None
while True:
    i = data.find(sig, pos)
    if i < 0:
        break
    pos = i + 1
    prop = data[i+4]
    ds = lzma2_dict_size(prop)
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW,
                                   filters=[{"id": lzma.FILTER_LZMA2, "dict_size": max(ds, 1 << 20)}])
        d = dec.decompress(data[i+4:i+4+80_000_000])
    except Exception:
        continue
    if len(d) < 100:
        continue
    blocks += 1
    g = sum(d.count(v) for v in gbk.values())
    u = sum(d.count(v) for v in u8.values())
    gtot += g; utot += u
    if g and sample is None:
        k = d.find(gbk["欢迎"])
        if k < 0: k = d.find(gbk["下一步"])
        sample = d[max(0, k-30):k+120]
    print(f"块@0x{i:X} prop=0x{prop:02X}(dict={ds}) 解压{len(d)}字节 GBK命中{g} UTF8命中{u}")

print("=" * 56)
print("解压块数:", blocks, "| GBK命中:", gtot, "| UTF8命中:", utot)
if sample is not None:
    print("GBK 样例:", sample.decode("gbk", errors="replace"))
if gtot > 0 and utot == 0:
    print("结论: PASS - 内嵌中文消息为GBK(936),界面不会乱码")
elif utot > 0:
    print("结论: FAIL - 含UTF8消息,按936显示会乱码")
else:
    print("结论: 未发现中文,需人工复核")
