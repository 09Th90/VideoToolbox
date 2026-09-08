# -*- coding: utf-8 -*-
"""One-shot push of the local repo tree to GitHub via the Git Data API.

Used because github.com:443 (git protocol) is unreachable from this network,
while api.github.com works. Creates blobs -> tree -> commit -> ref on an
empty repository.
"""
import base64
import os
import subprocess
import sys
import time

import requests

OWNER = "09Th90"
REPO = "VideoToolbox"
BRANCH = "main"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"

TOKEN = os.environ["GH_TOKEN"]
SESSION = requests.Session()
SESSION.headers.update({
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
})


def api(method, url, **kwargs):
    """Call the API with retries; return parsed JSON."""
    last = None
    for attempt in range(1, 7):
        try:
            r = SESSION.request(method, url, timeout=60, **kwargs)
            if r.status_code in (500, 502, 503, 504):
                raise requests.HTTPError(f"server {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                print(f"FATAL {method} {url} -> {r.status_code}: {r.text[:500]}")
                sys.exit(1)
            return r.json() if r.content else {}
        except (requests.RequestException,) as e:
            last = e
            wait = min(2 ** attempt, 30)
            print(f"  attempt {attempt} failed ({e}); retry in {wait}s")
            time.sleep(wait)
    print(f"FATAL {method} {url}: {last}")
    sys.exit(1)


def main():
    files = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files"], text=False
    ).decode("utf-8").splitlines()
    files = [f for f in files if f.strip()]
    print(f"{len(files)} files to upload")

    # Empty repos reject blob creation (409); bootstrap with the Contents API.
    r = SESSION.get(f"{API}/git/ref/heads/{BRANCH}", timeout=60)
    if r.status_code == 200:
        head_sha = r.json()["object"]["sha"]
        print(f"existing branch {BRANCH} at {head_sha}")
    else:
        first = files[0]
        with open(first, "rb") as fh:
            first_data = fh.read()
        init = api("PUT", f"{API}/contents/{first}", json={
            "message": "chore: initial commit (bootstrap)",
            "content": base64.b64encode(first_data).decode("ascii"),
            "branch": BRANCH,
        })
        head_sha = init["commit"]["sha"]
        print(f"bootstrap commit {head_sha} with {first}")
        files = files[1:]
    head = api("GET", f"{API}/git/commits/{head_sha}")
    base_tree = head["tree"]["sha"]

    tree_items = []
    for i, path in enumerate(files, 1):
        with open(path, "rb") as fh:
            data = fh.read()
        blob = api("POST", f"{API}/git/blobs", json={
            "content": base64.b64encode(data).decode("ascii"),
            "encoding": "base64",
        })
        tree_items.append({
            "path": path,
            "mode": "100644",
            "type": "blob",
            "sha": blob["sha"],
        })
        print(f"  [{i}/{len(files)}] {path} ({len(data)} B)")

    tree = api("POST", f"{API}/git/trees", json={
        "tree": tree_items,
        "base_tree": base_tree,
    })
    print("tree:", tree["sha"])

    msg = subprocess.check_output(
        ["git", "log", "-1", "--pretty=%B"], text=True
    ).strip()
    name = subprocess.check_output(
        ["git", "config", "user.name"], text=True
    ).strip() or OWNER
    email = subprocess.check_output(
        ["git", "config", "user.email"], text=True
    ).strip() or f"{OWNER}@users.noreply.github.com"

    commit = api("POST", f"{API}/git/commits", json={
        "message": msg,
        "tree": tree["sha"],
        "parents": [head_sha],
        "author": {"name": name, "email": email},
        "committer": {"name": name, "email": email},
    })
    print("commit:", commit["sha"])

    api("PATCH", f"{API}/git/refs/heads/{BRANCH}", json={
        "sha": commit["sha"],
    })
    print(f"DONE: pushed {len(files)} files to {OWNER}/{REPO}@{BRANCH}")


if __name__ == "__main__":
    main()
