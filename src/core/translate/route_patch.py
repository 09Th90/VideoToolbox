# -*- coding: utf-8 -*-
# @version 2.3.1
"""翻译请求路由补丁（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

2026-10-17 增强（用户在途）：双重保险——除 __init__ 外再包一层
translate_subtitle，治「实例早于补丁存在」导致的 trust_env 遗留。
"""
import os

from core.shared.log import _vc_log
from core.shared.proxy import translate_session_proxies


def _patch_translator_route(mod, cls_name):
    """给某个翻译器类上**双重**保险：`__init__` 包一层 + `translate_subtitle` 包一层。

    为什么不能只包 `__init__`（2026-10-17 实测教训）：
    补丁只影响**之后创建**的实例。若引擎在 GUI 启动早期（补丁挂载前）就
    建好了 translator 实例，那个实例的 session 仍是默认的
    `trust_env=True` → 跟随环境变量里的 `https_proxy`（本机 IDE 代理
    127.0.0.1:14901，对微软/国内站点一律不通）→ 全部片段失败。
    用户看到的是「Translation failed: 252/252 segments failed (100%)」，
    而那个时候 BingTranslator 明明已经被「补丁已挂」的日志覆盖过——
    坑就在于实例早于补丁存在。

    故 `translate_subtitle` 也包一层：**每次翻译前**重新钉死路由，
    无论实例何时创建都有效；同时若发现 `trust_env` 仍为 True（说明该实例
    绕过了构造补丁），往日志里写一条，让这类问题以后有迹可循。
    """
    cls = getattr(mod, cls_name, None)
    if cls is None or getattr(cls, "_vt_route_patched", False):
        return False
    orig_init = cls.__init__

    def _pin_route(self):
        """把 session 路由钉死；返回是否发生了修正（用于日志）。"""
        session = getattr(self, "session", None)
        if session is None:
            return False
        fixed = False
        if getattr(session, "trust_env", False):
            session.trust_env = False      # 关键：不读环境/系统代理
            fixed = True
        want = translate_session_proxies(getattr(self, "endpoint", ""))
        if getattr(session, "proxies", None) != want:
            session.proxies = want
            fixed = True
        return fixed

    def _route_snapshot(self):
        """路由快照：端点 / session 状态 / 代理环境变量（排障用，一次性写盘）。

        2026-10-17 用户报「252/252 segments failed」，静态排查全绿却无法解释，
        缺的就是这份现场。现在每次翻译前落一条，失败时直接对照。
        """
        try:
            ep = str(getattr(self, "endpoint", "") or "")
            s = getattr(self, "session", None)
            envs = {k: os.environ.get(k) for k in
                    ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
                     "ALL_PROXY", "all_proxy") if os.environ.get(k)}
            _vc_log("翻译路由快照（%s）：endpoint=%s｜trust_env=%s｜proxies=%r｜"
                    "代理环境变量=%s"
                    % (cls_name, ep[:60],
                       getattr(s, "trust_env", "<无session>"),
                       getattr(s, "proxies", "<无session>"),
                       envs or "无"))
        except Exception:  # noqa: BLE001
            pass

    def _init(self, *a, **kw):
        orig_init(self, *a, **kw)
        try:
            if _pin_route(self):
                _route_snapshot(self)
        except Exception as e:  # noqa: BLE001
            _vc_log(f"翻译会话路由设置失败（{cls_name}）：{e}")

    cls.__init__ = _init
    orig_translate = getattr(cls, "translate_subtitle", None)
    if callable(orig_translate):
        def _translate(self, subtitle_data):
            try:
                if _pin_route(self):
                    _vc_log(f"翻译前重新钉死 {cls_name} 请求路由"
                            "（该实例早于补丁创建，已修正）")
                _route_snapshot(self)
            except Exception as e:  # noqa: BLE001
                _vc_log(f"翻译前路由钉死失败（{cls_name}）：{e}")
            return orig_translate(self, subtitle_data)

        cls.translate_subtitle = _translate
    cls._vt_route_patched = True
    return True


def vc_translate_route_patch():
    """把「翻译请求路由」钉死（幂等运行期补丁，理由见 `translate_session_proxies`）。"""
    try:
        import videocaptioner.core.translate.bing_translator as _bt
        import videocaptioner.core.translate.google_translator as _gt
    except Exception as e:  # noqa: BLE001
        _vc_log(f"翻译路由补丁导入失败：{e}")
        return False
    done = []
    if _patch_translator_route(_bt, "BingTranslator"):
        done.append("微软")
    if _patch_translator_route(_gt, "GoogleTranslator"):
        done.append("谷歌")
    if done:
        _vc_log("翻译路由补丁已挂：%s 请求显式路由（微软直连 / 谷歌走本地代理，"
                "不再跟随系统代理）" % "+".join(done))
    return True


__all__ = [
    "vc_translate_route_patch",
    "_patch_translator_route",
]
