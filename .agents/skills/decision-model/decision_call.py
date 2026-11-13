# -*- coding: utf-8 -*-
# @version 2.9.0
r"""decision-model-preview 薄调用器（官方 systemone 端点，标准库 only）。

用法：tools\python\python.exe decision_call.py <payload.json> [--base BASE_URL]
密钥自动读程序根 data/credentials.json 的 asr_api_key（Token Plan 键），不打印。
stdout 只落一个 JSON；失败退出码 1。
"""
import json
import os
import sys
import urllib.request
import urllib.error

DEFAULT_BASE = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def main():
    args = [a for a in sys.argv[1:]]
    base = DEFAULT_BASE
    if "--base" in args:
        i = args.index("--base")
        base = args[i + 1].rstrip("/")
        del args[i:i + 2]
    if len(args) != 1:
        print(json.dumps({"error": "用法: decision_call.py <payload.json> [--base URL]"},
                         ensure_ascii=False))
        return 1
    root = os.environ.get("VIDEO_TOOLBOX_ROOT") or os.getcwd()
    cred_path = os.path.join(root, "data", "credentials.json")
    if not os.path.isfile(cred_path):  # 全局技能场景：cwd 不在工具箱根
        cred_path = r"D:\Agent Work\软件开发\视频工具箱\data\credentials.json"
    try:
        payload = json.load(open(args[0], encoding="utf-8"))
        cred = json.load(open(cred_path, encoding="utf-8"))
        key = cred.get("asr_api_key") or cred.get("api_key")
        if not key:
            raise ValueError("credentials.json 无可用密钥")
        payload.setdefault("model", "decision-model-preview")
        req = urllib.request.Request(
            base + "/systemone", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=90) as r:
            print(json.dumps(json.load(r), ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as e:
        print(json.dumps({"error": "HTTP %d" % e.code,
                          "detail": e.read().decode("utf-8", "replace")[:500]},
                         ensure_ascii=False))
        return 1
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e)[:300]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())