# -*- coding: utf-8 -*-
# @version 2.6.0
"""下载域（core/download）：yt-dlp 全链（8 阶段可中止）/ NPE fallback /
cookie 与 CDP 导出 / 信息与画质探测 / 音画合并 / 媒体扫描配对。

子模块：
  · ``deps``       依赖引导（yt-dlp/ffmpeg/deno/libmpv）
  · ``urls``       链接识别与 yt-dlp 字幕语言参数
  · ``ytdlp_util`` yt-dlp 参数、信息探测、下载模式、输出模板
  · ``cookies``    cookie 三通道（游客/浏览器/CDP）
  · ``npe``        NPE 第二解析引擎
  · ``media``      媒体扫描/配对/音画合并
  · ``util``       格式化/命名/产物文件

依赖规则：只准依赖 ``core.shared`` 与包内兄弟模块（链：cookies ← npe ← ytdlp_util；
media/util → ytdlp_util 不成立的反向由 __init__ 汇总层解开）。
"""
from .deps import *  # noqa: F401,F403
from .urls import *  # noqa: F401,F403
from .util import *  # noqa: F401,F403
from .cookies import *  # noqa: F401,F403
from .npe import *  # noqa: F401,F403
from .ytdlp_util import *  # noqa: F401,F403
from .media import *  # noqa: F401,F403

from .deps import __all__ as _deps_all
from .urls import __all__ as _urls_all
from .util import __all__ as _util_all
from .cookies import __all__ as _cookies_all
from .npe import __all__ as _npe_all
from .ytdlp_util import __all__ as _ytdlp_all
from .media import __all__ as _media_all

__all__ = sorted(set(
    _deps_all + _urls_all + _util_all + _cookies_all
    + _npe_all + _ytdlp_all + _media_all
))
