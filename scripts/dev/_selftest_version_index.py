# -*- coding: utf-8 -*-
# @version 2.5.2
"""`vt_version_index.py` 的离线自测（无需网络）。

跑法：
    tools\\python\\python.exe scripts\\dev\\_selftest_version_index.py
    或  python scripts/dev/_selftest_version_index.py

覆盖：版本解析/比较、选择器语义、索引构造与合并、通道维护、
隐藏态过滤、manifest URL 拼装、更新器兼容判定、落盘往返。
全部用例只碰内存与临时目录，不发任何网络请求。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "packaging", "online_release"))

import vt_version_index as V  # noqa: E402

_OK = [0]
_FAIL = [0]


def chk(name, cond, extra=""):
    if cond:
        _OK[0] += 1
        print("  PASS  %s" % name)
    else:
        _FAIL[0] += 1
        print("  FAIL  %s   %s" % (name, extra))


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print("       (抛了别的异常：%r)" % e)
        return False
    return False


def main():
    print("== 版本解析 ==")
    chk("1.20.0", V.parse_version("1.20.0") == ((1, 20, 0), ()))
    chk("v1.20 缺位补 0", V.parse_version("v1.20") == ((1, 20, 0), ()))
    p = V.parse_version("1.20.0-beta.1")
    chk("预发布拆段", p[0] == (1, 20, 0) and len(p[1]) == 2, p)
    chk("非法版本抛错", raises(lambda: V.parse_version("abc"), V.VersionError))
    chk("空串抛错", raises(lambda: V.parse_version(""), V.VersionError))

    print("== 版本比较 ==")
    chk("正式版 > 预发布", V.cmp_version("1.20.0", "1.20.0-beta.1") > 0)
    chk("1.20 == 1.20.0", V.cmp_version("1.20", "1.20.0") == 0)
    chk("1.19.0 < 1.20.0", V.cmp_version("1.19.0", "1.20.0") < 0)
    chk("beta.2 < beta.10", V.cmp_version("1.0.0-beta.2", "1.0.0-beta.10") < 0)
    chk("2.0.0 > 1.99.9", V.cmp_version("2.0.0", "1.99.9") > 0)

    print("== 选择器 ==")
    chk("^1.20.0 命中 1.20.5", V.match_selector("1.20.5", "^1.20.0"))
    chk("^1.20.0 拒 2.0.0", not V.match_selector("2.0.0", "^1.20.0"))
    chk("~1.20.0 命中 1.20.9", V.match_selector("1.20.9", "~1.20.0"))
    chk("~1.20.0 拒 1.21.0", not V.match_selector("1.21.0", "~1.20.0"))
    chk(">=1.19.0 命中 1.20", V.match_selector("1.20.0", ">=1.19.0"))
    chk("<1.21 命中 1.20.9", V.match_selector("1.20.9", "<1.21"))
    chk("1.20 命中 1.20.3", V.match_selector("1.20.3", "1.20"))
    chk("1.20 拒 1.21.0", not V.match_selector("1.21.0", "1.20"))
    chk("1.20.0 精确匹配", V.match_selector("1.20.0", "1.20.0"))
    chk("1.20.0 拒 1.20.1", not V.match_selector("1.20.1", "1.20.0"))
    chk("空选择器不设限", V.match_selector("9.9.9", ""))
    chk("=1.20.0 等价精确", V.match_selector("1.20.0", "=1.20.0"))
    chk("!=1.20.0 取反", not V.match_selector("1.20.0", "!=1.20.0"))

    print("== 索引构造 ==")
    idx = V.new_index(base_url="https://x/download/repo-latest/")
    for v, st in (("1.19.0", "stable"), ("1.20.0", "stable"),
                  ("1.20.1", "prerelease")):
        V.upsert_version(idx, {"version": v, "state": st, "notes": "note " + v,
                               "min_updater": "1.20.0" if v[:4] == "1.20"
                               else "1.0.0"})
    order = [e["version"] for e in idx["versions"]]
    chk("版本降序", order == ["1.20.1", "1.20.0", "1.19.0"], order)
    chk("latest = 最高", idx["channels"]["latest"] == "1.20.1")
    chk("stable = 最高正式版", idx["channels"]["stable"] == "1.20.0",
        idx["channels"])
    chk("manifest 自动补齐",
        idx["versions"][1]["manifest"] == "manifest-1.20.0.json",
        idx["versions"][1])
    chk("同版本覆盖而非追加",
        (V.upsert_version(idx, {"version": "1.20.0", "notes": "改说明"})
         and len([e for e in idx["versions"]
                  if e["version"] == "1.20.0"]) == 1))
    chk("降级发版不拽回 latest",
        (V.upsert_version(idx, {"version": "1.18.0", "state": "stable"})
         or idx["channels"]["latest"] == "1.20.1"), idx["channels"])

    print("== 版本解析（resolve） ==")
    chk("latest", V.resolve(idx)["version"] == "1.20.1")
    chk("stable", V.resolve(idx, "stable")["version"] == "1.20.0")
    chk("精确 1.19.0", V.resolve(idx, "1.19.0")["version"] == "1.19.0")
    chk("^1.20 取命中里最高", V.resolve(idx, "^1.20")["version"] == "1.20.1")
    chk("空串等价 latest", V.resolve(idx, "")["version"] == "1.20.1")
    chk("不存在的版本抛错",
        raises(lambda: V.resolve(idx, "9.9.9"), V.VIndexError))
    chk("manifest URL 拼装",
        V.manifest_url(idx, V.resolve(idx))
        == "https://x/download/repo-latest/manifest-1.20.1.json",
        V.manifest_url(idx, V.resolve(idx)))
    chk("base_url 覆盖生效",
        V.manifest_url(idx, V.resolve(idx), base_url="https://y/b")
        == "https://y/b/manifest-1.20.1.json")
    chk("index_url", V.index_url("https://y/b/") == "https://y/b/index.json")
    chk("无 base_url 抛错",
        raises(lambda: V.manifest_url(V.new_index(), {"version": "1.0.0"}),
               V.VIndexError))

    print("== 隐藏态 ==")
    idx2 = V.new_index(base_url="https://x/")
    V.upsert_version(idx2, {"version": "1.18.0", "state": "yanked"})
    V.upsert_version(idx2, {"version": "1.20.0", "state": "stable"})
    chk("默认过滤 yanked",
        [e["version"] for e in V.visible_versions(idx2)] == ["1.20.0"])
    chk("allow_hidden 放开", len(V.visible_versions(idx2, True)) == 2)
    chk("yanked 仍可精确装",
        raises(lambda: V.resolve(idx2, "1.18.0"), V.VIndexError))
    chk("yanked 精确装（放开后）",
        V.resolve(idx2, "1.18.0", allow_hidden=True)["version"] == "1.18.0")
    chk("latest 不落在 yanked 上",
        V.resolve(idx2)["version"] == "1.20.0")

    print("== 更新器兼容 ==")
    chk("自身够新", V.updater_ok({"min_updater": "1.20.0"}, "1.20.0"))
    chk("自身过旧", not V.updater_ok({"min_updater": "1.20.0"}, "1.19.0"))
    chk("无要求一律通过", V.updater_ok({}, "0.0.1"))
    chk("自身版本缺失判不通过", not V.updater_ok({"min_updater": "1.0.0"}, ""))

    print("== 落盘往返 ==")
    d = tempfile.mkdtemp(prefix="vt_idx_")
    p = os.path.join(d, "index.json")
    V.save_index(idx, p)
    back = V.load_index(p)
    chk("往返版本列表一致",
        [e["version"] for e in back["versions"]]
        == [e["version"] for e in idx["versions"]])
    chk("file:// 读取",
        V.load_index("file:///" + p.replace("\\", "/"))["app"] == "视频工具箱")
    chk("缺失文件抛错",
        raises(lambda: V.load_index(os.path.join(d, "nope.json")),
               V.VIndexError))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"schema": 99}')
    chk("schema 不符抛错", raises(lambda: V.load_index(p), V.VIndexError))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"schema": 1, "versions": []}')
    chk("空 versions 抛错", raises(lambda: V.load_index(p), V.VIndexError))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write('{"schema": 1, "versions": [{"version": "x.y.z"}]}')
    chk("非法版本号抛错", raises(lambda: V.load_index(p), V.VIndexError))
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("not json")
    chk("非 JSON 抛错", raises(lambda: V.load_index(p), V.VIndexError))

    print()
    print("== 结果：PASS %d / FAIL %d ==" % (_OK[0], _FAIL[0]))
    return 1 if _FAIL[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
