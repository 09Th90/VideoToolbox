# @version 2.4.0
"""引擎路径契约（自研，替代 videocaptioner.config 的路径部分）。

P1 接缝之一：``videocaptioner.config`` 在 **import 期**就固化一批路径常量
（``ROOT_PATH`` / ``WORK_PATH`` / ``CACHE_PATH`` / ``SETTINGS_PATH`` …），
并在导入时 ``mkdir`` 四个目录、改 ``PATH`` 环境变量。当前项目靠
``video_toolbox.vc_redirect_paths()`` 事后逐个改写这些属性来纠正——那是
「补丁打在别人家的数据上」，一旦引擎升级新增常量就会静默失效。

本模块把「引擎数据该落在哪」这件事收进本项目自有代码，成为唯一事实来源：

* :class:`EnginePaths` 只做纯路径计算（无副作用、无第三方依赖）；
* :meth:`EnginePaths.apply_to` 是**唯一**允许写第三方 ``config`` 模块的地方，
  调用方不再逐个 ``_vc_cfg.XXX = ...``；
* :func:`ensure_runtime_dirs` 负责建目录，调用时机显式，不再藏在 import 期。

设计约束
--------
1. **零第三方依赖**，仅用标准库 ``os`` / ``pathlib``。可在本项目任意
   打包环境中独立 import 与自检，不需要引擎在场。
2. **纯计算优先**：``EnginePaths(...)`` 构造后不应碰文件系统；建目录是
   独立的 :meth:`ensure_dirs` 显式调用。这样自检可以在临时目录里反复
   构造而不会污染真实安装目录。
3. **不改写第三方原实现**：这里只依据「可观察的路径契约」重新推导取值
   （见 ``docs/引擎自研化替换规格.md`` 风险 1），不复制引擎 ``config.py``
   的代码。
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "EnginePaths",
    "REDIRECT_FLAG",
    "apply_engine_paths",
    "ensure_runtime_dirs",
]

#: 打在第三方 config 模块上的幂等标记。名字带 ``_VT_`` 前缀以便与引擎自身
#: 常量区分；第三方模块不做 ``__slots__``，setattr 可行。
REDIRECT_FLAG = "_VT_REDIRECT_DONE"


class EnginePaths:
    """引擎数据/资源路径的纯计算视图。

    参数
    ----
    data_dir:
        可写数据根（``data\\VideoCaptioner``）。全部运行期产物落在这里。
    tools_dir:
        工具箱自带二进制目录（ffmpeg/ffprobe）。引擎内部裸调 ``"ffmpeg"``
        靠 ``PATH`` 注入命中这里。
    bundled_resource_dir:
        随包分发的只读静态资源目录（assets/fonts/subtitle_style/translations）。
        缺失时按 ``data_dir\\resource`` 回退，保持旧行为、不崩。
    vc_name:
        引擎数据目录名。默认沿用历史值——它同时是**用户已有数据的目录名**，
        改名等于让老用户「设置与历史全丢」，因此固定为常量而非可配置项。

    不变量（由 ``_selftest_engine_paths.py`` 的负向项守护）
    --------------------------------------------------
    * 所有可写路径都在 ``data_dir`` 之下——绝不落系统盘
      （``%LOCALAPPDATA%`` / ``Path.home()``）。
    * ``settings_path`` 直接位于 ``data_dir`` 之下（与既有
      ``video_toolbox.vc_settings_path()`` 同址，保证新旧代码读写同一文件）。
    * ``root_path is appdata_path``：上游把两者指向同一处，本项目沿用。
    """

    def __init__(self, data_dir, tools_dir, bundled_resource_dir=None,
                 vc_name="VideoCaptioner"):
        self.data_dir = Path(data_dir)
        self.tools_dir = Path(tools_dir)
        self.vc_name = str(vc_name)

        # —— 可写运行数据：全部收进软件文件夹 ——
        self.root_path = self.data_dir
        self.appdata_path = self.data_dir
        self.work_path = self.data_dir / "work-dir"
        self.log_path = self.data_dir / "logs"
        self.llm_log_file = self.log_path / "llm_requests.jsonl"
        self.settings_path = self.data_dir / "settings.json"
        self.cache_path = self.data_dir / "cache"
        self.model_path = self.data_dir / "models"
        self.subtitle_style_path = self.data_dir / "resource" / "subtitle_style"

        # —— 只读静态资源：优先随包目录，缺失回退数据目录 ——
        bundled = Path(bundled_resource_dir) if bundled_resource_dir else None
        res_root = bundled if (bundled is not None and bundled.is_dir()) \
            else self.data_dir / "resource"
        self.bundled_resource_dir = bundled
        self.resource_path = res_root
        self.assets_path = res_root / "assets"
        self.translations_path = res_root / "translations"
        self.fonts_path = res_root / "fonts"

        # —— 二进制：复用工具箱自带 ffmpeg/ffprobe ——
        self.bin_path = self.tools_dir
        self.faster_whisper_path = self.tools_dir / "Faster-Whisper-XXL"

        # —— CLI 子模块另有一套 user_config_dir 约定（上游默认 AppData\Roaming）——
        self.cli_config_dir = self.data_dir / "cli"
        self.cli_config_file = self.cli_config_dir / "config.toml"

    # ---------- 副作用：建目录（显式调用，不藏在构造/import 期） ----------
    def ensure_dirs(self, fallback_fonts_dir=None):
        """建齐运行期需要的目录。返回实际成功创建的目录列表。

        ``fallback_fonts_dir``：随包 ``fonts`` 缺失时的回退（上游 wheel 内置
        字体目录）。由调用方决定，因为那是引擎包内部路径，自研模块不该知道。
        单个目录创建失败（权限/只读介质）不抛异常，只从返回列表中略去——
        与旧行为一致：缺目录不该让整个程序起不来。
        """
        fonts = self.fonts_path
        if not fonts.is_dir() and fallback_fonts_dir:
            candidate = Path(fallback_fonts_dir)
            if candidate.is_dir():
                fonts = candidate

        wanted = [
            self.data_dir, self.work_path, self.log_path, self.cache_path,
            self.model_path, self.subtitle_style_path, self.resource_path,
            self.assets_path, self.translations_path, fonts, self.cli_config_dir,
        ]
        made = []
        for d in wanted:
            try:
                d.mkdir(parents=True, exist_ok=True)
                made.append(d)
            except OSError:
                pass
        return made

    def seed_subtitle_styles(self):
        """从随包默认样式补齐用户样式目录里缺失的预设（**不覆盖**已有文件）。

        返回新复制的文件数。上游 pip 形态 wheel 不含 resource，用户样式目录
        初始为空 ⇒ 界面里选不到任何字幕样式预设。
        """
        if self.bundled_resource_dir is None:
            return 0
        seed = self.bundled_resource_dir / "subtitle_style"
        if not seed.is_dir():
            return 0
        n = 0
        try:
            for jf in seed.glob("*.json"):
                dst = self.subtitle_style_path / jf.name
                if not dst.exists():
                    self.subtitle_style_path.mkdir(parents=True, exist_ok=True)
                    self.subtitle_style_path.joinpath(jf.name).write_bytes(
                        jf.read_bytes())
                    n += 1
        except OSError:
            pass
        return n

    def ensure_path_env(self, env=None):
        """把 ``bin_path`` / ``faster_whisper_path`` 前置进 ``PATH``。

        上游 config 导入期那次注入用的是尚未重定向的空目录（不存在即跳过），
        因此必须显式补一次，否则引擎内部裸调 ``"ffmpeg"`` 会找不到二进制。
        返回实际新增进 PATH 的目录数（已存在则不计）。
        """
        env = os.environ if env is None else env
        cur = env.get("PATH", "")
        parts = cur.split(os.pathsep) if cur else []
        added = 0
        for d in (self.faster_whisper_path if self.faster_whisper_path.is_dir()
                  else None, self.bin_path):
            if d is None:
                continue
            s = str(d)
            if s and s not in parts:
                parts.insert(0, s)
                added += 1
        if added:
            env["PATH"] = os.pathsep.join(parts)
        return added

    # ---------- 写第三方模块：唯一出口 ----------
    def apply_to(self, cfg):
        """把本模块算出的路径写进第三方 ``config`` 模块对象。

        这是本项目里**唯一**允许对 ``videocaptioner.config`` 赋值的函数。
        引擎侧新增路径常量时，这里是唯一需要跟进的点——不再散落在
        ``vc_redirect_paths()`` 里靠人肉记忆维护。

        返回实际写入的属性名列表（便于自检断言覆盖率）。
        """
        table = {
            "ROOT_PATH": self.root_path,
            "APPDATA_PATH": self.appdata_path,
            "WORK_PATH": self.work_path,
            "LOG_PATH": self.log_path,
            "LLM_LOG_FILE": self.llm_log_file,
            "SETTINGS_PATH": self.settings_path,
            "CACHE_PATH": self.cache_path,
            "MODEL_PATH": self.model_path,
            "RESOURCE_PATH": self.resource_path,
            "ASSETS_PATH": self.assets_path,
            "TRANSLATIONS_PATH": self.translations_path,
            "SUBTITLE_STYLE_PATH": self.subtitle_style_path,
            "BIN_PATH": self.bin_path,
            "FASTER_WHISPER_PATH": self.faster_whisper_path,
        }
        written = []
        for name, value in table.items():
            try:
                setattr(cfg, name, value)
                written.append(name)
            except Exception:  # noqa: BLE001 - 第三方模块可能是只读代理
                pass
        # 字体目录：随包 fonts 缺失时回退到引擎包内置字体（调用方传入）
        return written


def ensure_runtime_dirs(paths, fallback_fonts_dir=None):
    """建目录 + 补样式预设 + 注 PATH 的组合动作（保持旧调用顺序）。"""
    paths.ensure_dirs(fallback_fonts_dir=fallback_fonts_dir)
    paths.seed_subtitle_styles()
    paths.ensure_path_env()


def apply_engine_paths(cfg, paths, cli_cfg=None, fallback_fonts_dir=None):
    """把 :class:`EnginePaths` 施加到第三方模块组上。

    参数
    ----
    cfg:
        ``videocaptioner.config`` 模块（或任何可 setattr 的对象）。
    paths:
        :class:`EnginePaths` 实例。
    cli_cfg:
        可选。``videocaptioner.cli.config`` 模块——它有自己的
        ``CONFIG_DIR`` / ``CONFIG_FILE`` 约定，上游默认在
        ``AppData\\Roaming``，同样要收进软件文件夹。按需传入即可。
    fallback_fonts_dir:
        可选。随包 fonts 缺失时的引擎包内置字体目录。

    返回本次实际写入的属性名列表（``cfg`` 与 ``cli_cfg`` 合并）。
    """
    written = paths.apply_to(cfg)

    # 字体回退要在 apply 之后：fonts_path 已被写成随包目录，缺失时才用引擎内置。
    if fallback_fonts_dir and not paths.fonts_path.is_dir():
        candidate = Path(fallback_fonts_dir)
        if candidate.is_dir():
            try:
                cfg.FONTS_PATH = candidate
                written.append("FONTS_PATH")
            except Exception:  # noqa: BLE001
                pass
    else:
        written.append("FONTS_PATH")

    if cli_cfg is not None:
        for name, value in (("CONFIG_DIR", paths.cli_config_dir),
                            ("CONFIG_FILE", paths.cli_config_file)):
            try:
                setattr(cli_cfg, name, value)
                written.append("cli." + name)
            except Exception:  # noqa: BLE001
                pass
        try:
            paths.cli_config_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    try:
        setattr(cfg, REDIRECT_FLAG, True)
        written.append(REDIRECT_FLAG)
    except Exception:  # noqa: BLE001
        pass
    return written
