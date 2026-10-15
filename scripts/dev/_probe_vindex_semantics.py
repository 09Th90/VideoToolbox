# -*- coding: utf-8 -*-
# @version 2.3.1
"""验证 vt_version_index 修复后的关键语义（2026-10-13 审查反例回归）。"""
import sys

sys.path.insert(0, r"D:\Agent Work\软件开发\视频工具箱\packaging\online_release")
import vt_version_index as vindex  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want
    print("%s %-58s got=%r want=%r" % ("PASS" if ok else "FAIL", name, got, want))
    if not ok:
        fails.append(name)


# 1. vkey 与 cmp_version 次序一致（reverse=True 下同号正式版在预发布前）
order = sorted(["1.20.0", "1.20.0-rc.2", "2.0.0", "2.0.0-beta.1"],
               key=vindex.vkey, reverse=True)
check("vkey stable-before-prerelease", order,
      ["2.0.0", "2.0.0-beta.1", "1.20.0", "1.20.0-rc.2"])

# 2. v 前缀段数：v1.20 ≡ ~1.20（[1.20, 1.21)），不命中 1.99.0
check("v1.20 not hit 1.99.0", vindex.match_selector("1.99.0", "v1.20"), False)
check("v1.20 hit 1.20.5", vindex.match_selector("1.20.5", "v1.20"), True)
check("v1.20.0 exact hit 1.20.0", vindex.match_selector("1.20.0", "v1.20.0"), True)
check("v1.20.0 not hit 1.20.1", vindex.match_selector("1.20.1", "v1.20.0"), False)

# 3. ^0.x 递进次版本（npm 语义）
check("^0.2 not hit 0.9.0", vindex.match_selector("0.9.0", "^0.2"), False)
check("^0.2 hit 0.2.9", vindex.match_selector("0.2.9", "^0.2"), True)
check("^1.2 hit 1.9.0", vindex.match_selector("1.9.0", "^1.2"), True)
check("^1.2 not hit 2.0.0", vindex.match_selector("2.0.0", "^1.2"), False)

# 4. ~ 一段递进主版本（与裸写一致）
check("~1 hit 1.99.0", vindex.match_selector("1.99.0", "~1"), True)
check("~1 not hit 2.0.0", vindex.match_selector("2.0.0", "~1"), False)
check("~1.20 not hit 1.21.0", vindex.match_selector("1.21.0", "~1.20"), False)

# 5. 无运算符裸写回归
check("bare 1 hits 1.99", vindex.match_selector("1.99.0", "1"), True)
check("bare 1 not hit 2.0", vindex.match_selector("2.0.0", "1"), False)

# 6. resolve "取最高" 不吃预发布 + VersionError 归一
idx = vindex.new_index()
vindex.upsert_version(idx, {"version": "1.20.0-rc.2", "state": "prerelease"})
vindex.upsert_version(idx, {"version": "1.20.0", "state": "stable"})
check("stable channel stays stable",
      idx["channels"].get("stable"), "1.20.0")
check("resolve >=rc1 picks 1.20.0",
      vindex.resolve(idx, ">=1.20.0-rc.1")["version"], "1.20.0")
try:
    vindex.resolve(idx, ">abc")
    check("resolve wraps VersionError", "no-raise", "VIndexError")
except vindex.VIndexError:
    check("resolve wraps VersionError", "VIndexError", "VIndexError")
except Exception as e:  # noqa: BLE001
    check("resolve wraps VersionError", type(e).__name__, "VIndexError")

# 7. v 前缀版本身份：find/upsert 去重
i2 = vindex.new_index()
vindex.upsert_version(i2, {"version": "v1.20.0"})
check("upsert v-prefix dedup", len(i2["versions"]), 1)
check("find_version v-prefix", vindex.find_version(i2, "1.20.0") is not None, True)

# 8. state 白名单
try:
    vindex.normalize_entry({"version": "1.0.0", "state": "Stable"})
    check("bad state rejected", "no-raise", "VIndexError")
except vindex.VIndexError:
    check("bad state rejected", "VIndexError", "VIndexError")

print("\n== %s ==" % ("ALL PASS" if not fails else "FAILED: %s" % fails))
sys.exit(1 if fails else 0)
