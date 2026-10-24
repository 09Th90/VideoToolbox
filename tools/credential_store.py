# -*- coding: utf-8 -*-
# @version 2.6.0
"""API 凭据独立存储层（2026-10-22 安全整改）。

## 为什么需要这一层

整改前，API Key 与其它配置一起存在 ``data/ai_config.json``，而这份配置会：

  1. 被设置页回填进 ``QLineEdit``（``setText``）→ 控件文本进入 UI 基线快照；
  2. 被 ``vt_ui_golden.py`` 抓进 ``_golden/setting_*.json`` → 随公开仓库泄露；
  3. 被打包/备份脚本当作普通配置复制到各处。

2026-10-15 的事故就是这么发生的：两把有效密钥以明文进了公开仓库，暴露 6 天半。

## 三条设计约束（对应「与程序脱钩」）

1. **独立文件**：凭据只存 ``data/credentials.json``，**绝不写进**
   ``data/ai_config.json``。因此它不进入 qconfig、不进入设置页回填、
   不进入 UI 快照、也不进入 harness 的配置同步链路。
2. **只读**：文件属性置为只读（Windows 去掉写位 / POSIX 0400）。运行期
   任何代码误调 ``save_config`` 都不会把它覆盖掉；写入必须走 :func:`set`，
   写完立即恢复只读。
3. **只调用**：不在导入期读取，不参与配置树。只有真正要发 API 请求前
   才按需 :func:`get`（带 mtime 缓存，文件被外部改动会自动失效）。

## 用法

    from credential_store import get, set, has, status

    key = get("asr_api_key")      # 未配置返回 ""
    set("asr_api_key", "sk-...")  # 原子写 + 恢复只读
    has("api_key")                # 布尔，用于界面显示「已配置」
    status()                      # {"api_key": True, "asr_api_key": False}
"""
import json
import os
import stat
import sys
from datetime import datetime

#: 凭据字段白名单。只允许这些键落盘，避免界面误传杂字段。
SECRET_FIELDS = ("api_key", "asr_api_key")

#: 凭据文件版本号（未来结构变更时用于迁移）。
SCHEMA_VERSION = 1


def _resolve_data_dir():
    """与 ai_client._resolve_data_dir 同口径（便携部署 / 打包 / 源码三形态）。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        from pathlib import Path
        return Path(env) / "data"
    from pathlib import Path
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tools").is_dir() and \
                (parent / "tools" / "ai_client.py").is_file():
            return parent / "data"
    return here.parents[1] / "data"


CRED_PATH = _resolve_data_dir() / "credentials.json"

# mtime 缓存：文件被外部替换（例如用户手工编辑）时自动失效。
_cache = None
_cache_sig = None


def _signature():
    try:
        st = os.stat(CRED_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _load_raw():
    """读凭据文件（带签名缓存）。任何异常都降级为空字典，绝不抛给调用方。"""
    global _cache, _cache_sig
    sig = _signature()
    if _cache is not None and sig == _cache_sig:
        return _cache
    data = {}
    if sig is not None:
        try:
            with open(CRED_PATH, encoding="utf-8-sig") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
    _cache, _cache_sig = data, sig
    return data


def _set_readonly(path, readonly):
    """设置/解除只读属性。Windows 走写位，POSIX 走 0400/0600。"""
    try:
        if not os.path.exists(path):
            return
        if os.name == "nt":
            mode = os.stat(path).st_mode
            if readonly:
                os.chmod(path, mode & ~stat.S_IWRITE)
            else:
                os.chmod(path, mode | stat.S_IWRITE)
        else:
            os.chmod(path, 0o400 if readonly else 0o600)
    except OSError:
        # 只读位设置失败不该阻断功能（例如某些网络盘/受限 ACL），
        # 只是少一层防护；调用方仍可正常读写。
        pass


def is_readonly():
    """凭据文件当前是否只读（供自检/审计使用）。"""
    try:
        return not os.access(CRED_PATH, os.W_OK)
    except OSError:
        return False


def _write_raw(data):
    """原子写：先写临时文件，再 replace，最后恢复只读。"""
    global _cache, _cache_sig
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SCHEMA_VERSION, "updated_at": ""}
    payload.update({k: v for k, v in data.items() if k not in ("version",)})
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _set_readonly(CRED_PATH, False)          # 临时解锁（已存在时）
    tmp = CRED_PATH.with_name(CRED_PATH.name + ".tmp")
    try:
        if os.path.exists(tmp):
            os.chmod(tmp, 0o600) if os.name != "nt" else None
    except OSError:
        pass
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, CRED_PATH)
    _set_readonly(CRED_PATH, True)
    _cache, _cache_sig = payload, _signature()


def get(name, default=""):
    """读取单个凭据；未配置返回 ``default``。"""
    if name not in SECRET_FIELDS:
        return default
    v = _load_raw().get(name)
    return v if isinstance(v, str) and v else default


def has(name):
    """该凭据是否已配置（非空）。供界面显示「已配置」而不回填明文。"""
    return bool(get(name, ""))


def status():
    """全部凭据的配置状态：``{"api_key": bool, "asr_api_key": bool}``。"""
    return {k: has(k) for k in SECRET_FIELDS}


def set(name, value):  # noqa: A001 —— 与 get 对称，语义直观
    """写入/更新单个凭据。``value`` 为空串表示删除该键。"""
    if name not in SECRET_FIELDS:
        raise ValueError("unsupported credential: %s" % name)
    data = dict(_load_raw())
    data.pop("version", None)
    data.pop("updated_at", None)
    if isinstance(value, str) and value:
        data[name] = value
    else:
        data.pop(name, None)
    _write_raw(data)


def delete(name):
    """删除单个凭据。"""
    set(name, "")


def clear_all():
    """清空全部凭据（保留文件与只读属性）。"""
    _write_raw({})


def mask(name, value=None):
    """脱敏展示：``前8位...后4位(len=N)``。日志/报告里只许用这个。"""
    v = get(name) if value is None else value
    if not isinstance(v, str) or not v:
        return "(未配置)"
    if len(v) <= 14:
        return "%s...(len=%d)" % (v[:4], len(v))
    return "%s...%s(len=%d)" % (v[:8], v[-4:], len(v))


if __name__ == "__main__":  # 手工自查：只打印状态与脱敏值，绝不回显明文
    print("凭据文件:", CRED_PATH)
    print("存在:", CRED_PATH.exists(), "只读:", is_readonly())
    for _k in SECRET_FIELDS:
        print("  %-12s %s" % (_k, mask(_k)))
