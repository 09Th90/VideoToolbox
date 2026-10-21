# -*- coding: utf-8 -*-
# @version 2.4.1
"""统一文本编解码（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""
import codecs
import os
import sys

# ========== 统一文本编解码：同时兼容 UTF-8 / GBK(GB18030) / ASCII ==========
# 设计原则：读取任何“外部/用户产生”的文本（字幕、.url、第三方子进程输出、远程
# 同步内容等）都走 decode_bytes_any / read_text_any，按 BOM → UTF-8 → GB18030
# 顺序探测，绝不因编码不同而崩溃或乱码；本程序自己写出的文件统一用 UTF-8
# （给用户用记事本看的用 utf-8-sig）。ASCII 是 UTF-8 的子集，天然被覆盖。
# 说明：GB18030 是 GBK 的超集（兼容 GBK/GB2312），用于解码老式中文 Windows、
# 部分播放器与字幕工具导出的 GBK 字幕；另兼容 Big5 与带 BOM 的 UTF-16。
_TEXT_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    # UTF-32 的 BOM 以 UTF-16 BOM 为前缀，必须先判 32 再判 16；
    # 用 utf-16/utf-32（非 -le/-be）可据 BOM 自动定字节序并剥掉 BOM。
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
# 无 BOM 时的探测顺序：先 UTF-8（ASCII 也在此命中），失败再按中文编码回退
TEXT_ENCODINGS = ("utf-8", "gb18030", "big5", "shift_jis", "latin-1")


def decode_bytes_any(data, encodings=TEXT_ENCODINGS):
    """把 bytes 稳健解码为 str：识别 BOM，依次尝试 UTF-8/GB18030/Big5/...。

    - 传入 str 原样返回；None 返回空串；永不抛 UnicodeDecodeError。
    - UTF-8（含纯 ASCII）优先；不是合法 UTF-8 时按 GB18030（GBK 超集）等回退，
      最后才用 replace 兜底，最大化还原中文内容、避免崩溃。
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, (bytes,)):
        return str(data)
    for bom, enc in _TEXT_BOMS:
        if data.startswith(bom):
            try:
                return data.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                break
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def read_text_any(path, encodings=TEXT_ENCODINGS):
    """以二进制读取文件并用 decode_bytes_any 解码（兼容 UTF-8/GBK/ASCII）。"""
    with open(path, "rb") as f:
        return decode_bytes_any(f.read(), encodings)


def write_text_utf8(path, text, bom=False, newline=None):
    """规范写出文本：默认无 BOM 的 UTF-8；bom=True 写 utf-8-sig（记事本友好）。"""
    enc = "utf-8-sig" if bom else "utf-8"
    kw = {} if newline is None else {"newline": newline}
    with open(path, "w", encoding=enc, **kw) as f:
        f.write(text)


def decode_process_output(value):
    """兼容子进程 text/bytes 两种返回：bytes 走智能解码，str 原样返回。"""
    return decode_bytes_any(value)


def configure_stdio_utf8():
    """让标准输出/错误流以 UTF-8、replace 容错，避免在 GBK 控制台打印生僻字/Emoji
    时 UnicodeEncodeError 崩溃。幂等，可重复调用。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass
    # 子进程默认也用 UTF-8 与我们通信（个别工具仍可能输出 GBK，读取侧再智能解码）
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")


__all__ = [
    "TEXT_ENCODINGS",
    "decode_bytes_any",
    "read_text_any",
    "write_text_utf8",
    "decode_process_output",
    "configure_stdio_utf8",
]
