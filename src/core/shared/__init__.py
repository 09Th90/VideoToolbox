# -*- coding: utf-8 -*-
# @version 2.5.2
"""共享底座域（core/shared）：被多域共用的基础设施。

子模块与职责：
  · ``textio``    统一文本编解码（UTF-8/GBK/BOM 探测）
  · ``paths``     路径与数据根（运行期产物不落系统盘）+ 路径规范化
  · ``log``       日志卫生（轮转/去重/级别/自检隔离）
  · ``runtime``   内置运行时（tools\\python）与字幕引擎环境探测/资源接驳
  · ``proc``      子进程工具与中止原语（进程树杀灭/可取消睡眠）
  · ``config``    设置持久化（config.json）
  · ``ai``        全局 AI/LLM 配置与通道（ai_client 加载器）
  · ``vcsettings``引擎 settings.json 读写 + 全局 LLM 注入
  · ``proxy``     内置 mihomo 代理（引导/选节点/代理参数/节点锁定）

依赖规则：本域**不依赖任何其他 core 域**；只准依赖标准库与
``engine_*`` 自研引擎模块（函数内延迟 import）。
"""
from .textio import *  # noqa: F401,F403
from .paths import *  # noqa: F401,F403
from .runtime import *  # noqa: F401,F403
from .proc import *  # noqa: F401,F403
from .proxy import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .ai import *  # noqa: F401,F403
from .vcsettings import *  # noqa: F401,F403
from .env import *  # noqa: F401,F403
from .uibrand import *  # noqa: F401,F403
from .log import *  # noqa: F401,F403 —— LOG_MAX_BYTES（其余私有，见下方显式导）

# 私有名再导出（* 不收下划线；facade 与其余 core 域按需引用）
from .log import (_LOG_ERR_WORDS, _LOG_WARN_WORDS, _append_log,  # noqa: F401
                  _is_selftest_run, _log_level_tag, _rotate_log, _vc_log)
from .runtime import _is_self_exe, _VC_LEGACY_DIRS  # noqa: F401
from .proxy import _mihomo_log  # noqa: F401
from .vcsettings import (_path_on_system_drive, _vc_force_local_paths,  # noqa: F401
                         _vc_read_settings, _vc_write_settings)
from .env import _move_data_to  # noqa: F401
from .uibrand import (_patch_task_creation, _patch_video_widget)  # noqa: F401
from .proc import (_BOOTSTRAP_LOCK, _hide_console_kwargs,  # noqa: F401
                   _SUBPROCESS_POPEN, _SUBPROCESS_RUN)
from .ai import _AI_LAST_AUTO_NOTES, _AI_MOD  # noqa: F401
from .config import _fallback_config_path  # noqa: F401

from .textio import __all__ as _textio_all
from .paths import __all__ as _paths_all
from .runtime import __all__ as _runtime_all
from .proc import __all__ as _proc_all
from .proxy import __all__ as _proxy_all
from .config import __all__ as _config_all
from .ai import __all__ as _ai_all
from .vcsettings import __all__ as _vcsettings_all
from .log import __all__ as _log_all
from .env import __all__ as _env_all
from .uibrand import __all__ as _uibrand_all

__all__ = sorted(set(
    _textio_all + _paths_all + _runtime_all + _proc_all
    + _proxy_all + _config_all + _ai_all + _vcsettings_all + _log_all
    + _env_all + _uibrand_all
))
