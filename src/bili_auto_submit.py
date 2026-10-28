#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.8.0
"""B 站投稿 · 后台通用自动化（UIA 定位 + PostMessage 输入 + 系统文件对话框）。

设计约束（用户口径）：
  · 独立鼠标信号：只用 PostMessage，不动真实光标、不切前台；
  · 不移动/不激活窗口：窗口被遮挡也能操作；
  · 不注入脚本/DOM：所有动作都是鼠标点击、键盘输入、系统文件对话框；
  · 通用定位：控件位置全部来自 Windows UI Automation 的 Name/Rect（实时计算），
    不写死投稿页坐标；滚动也是按控件矩形判断方向。

用法：
  tools\\python\\python.exe src\\bili_auto_submit.py "<素材目录>" [--dry-run]
  tools\\python\\python.exe src\\bili_auto_submit.py "<素材目录>" --visibility self
  tools\\python\\python.exe src\\bili_auto_submit.py --probe
"""

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.getcwd()
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
sys.path.insert(0, os.path.join(ROOT, "src"))
import auto_vision_core as av  # noqa: E402
from PIL import Image  # noqa: E402

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:  # noqa: BLE001
    pass

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEWHEEL = 0x020A
MK_LBUTTON = 0x0001

VK = {
    "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "delete": 0x2E, "pgup": 0x21, "pgdn": 0x22,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
}

UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"
SHOT_DIR = os.path.join(ROOT, "data", "bili_upload", "shots")
STATE_PATH = os.path.join(ROOT, "data", "bili_upload", "auto_state.json")
PS1_PATH = os.path.join(ROOT, "data", "tmp", "uia_auto.ps1")

UIA_PS = r'''
param(
  [Parameter(Mandatory=$true)][string]$Hwnd,
  [Parameter(Mandatory=$true)][string]$Mode,
  [string]$Query = "",
  [string]$Type = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class DpiFix {
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
}
"@
[DpiFix]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][Int64]$Hwnd)
if (-not $root) { Write-Output "[]"; exit 0 }
function Get-El($e) {
  $ct = $e.Current.ControlType.ProgrammaticName -replace 'ControlType\.', ''
  $name = $e.Current.Name
  if ($null -eq $name) { $name = "" }
  $v = ""
  try {
    $p = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if ($p) { $v = [string]$p.Current.Value }
  } catch {}
  if (-not $v) {
    try {
      $tp = $e.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
      if ($tp) { $v = [string]$tp.DocumentRange.GetText(200) }
    } catch {}
  }
  $r = $e.Current.BoundingRectangle
  $rx = [double]$r.X; $ry = [double]$r.Y; $rw = [double]$r.Width; $rh = [double]$r.Height
  $bad = $false
  foreach ($q in @($rx, $ry, $rw, $rh)) {
    if ([double]::IsNaN($q) -or [double]::IsInfinity($q)) { $bad = $true }
  }
  if ($bad) { $rx = 0; $ry = 0; $rw = 0; $rh = 0 }
  [pscustomobject]@{
    type = $ct; name = $name; value = $v
    x = [int]$rx; y = [int]$ry; w = [int]$rw; h = [int]$rh
    offscreen = [bool]$e.Current.IsOffscreen; enabled = [bool]$e.Current.IsEnabled
    focused = [bool]$e.Current.HasKeyboardFocus
  }
}
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.Condition]::TrueCondition)
$out = @()
if ($Mode -eq "url") {
  foreach ($e in $all) {
    if ($e.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit) {
      $val = ""
      try {
        $p = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($p) { $val = [string]$p.Current.Value }
      } catch {}
      if ($val -match '^https?://') { $out += Get-El $e; break }
    }
  }
} elseif ($Mode -eq "find") {
  foreach ($e in $all) {
    $n = [string]$e.Current.Name
    if ($n -and $n -match $Query) {
      if ($Type) {
        $ct = $e.Current.ControlType.ProgrammaticName -replace 'ControlType\.', ''
        if ($ct -ne $Type) { continue }
      }
      $out += Get-El $e
    }
  }
} elseif ($Mode -eq "edits") {
  foreach ($e in $all) {
    if ($e.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit) {
      $out += Get-El $e
    }
  }
} else {
  foreach ($e in $all) {
    $n = [string]$e.Current.Name
    if ($n) { $out += Get-El $e }
    if ($out.Count -ge 600) { break }
  }
}
$out | ConvertTo-Json -Compress -Depth 4
'''


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def _lparam(x, y):
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


class Win:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.info = av.window_info(hwnd)
        if self.info is None:
            raise RuntimeError(f"窗口 {hwnd} 不存在")
        self.ox, self.oy = self.info.client_rect[0], self.info.client_rect[1]

    @staticmethod
    def find_edge():
        wins = []
        for w in av.list_windows(min_size=(400, 300)):
            if "哔哩哔哩" in w.title or "创作中心" in w.title:
                wins.append(w)
        return max(wins, key=lambda w: w.size[0] * w.size[1]) if wins else None

    def _post(self, msg, wp, lp):
        ctypes.windll.user32.PostMessageW(
            ctypes.c_void_p(self.hwnd), msg, ctypes.c_size_t(wp),
            ctypes.c_size_t(lp))

    def wake(self):
        self._post(0x0006, 1, 0)
        self._post(0x001C, 1, 0)
        self._post(0x0007, 0, 0)
        time.sleep(0.05)

    def click_client(self, x, y):
        self.wake()
        self._post(WM_MOUSEMOVE, 0, _lparam(x, y))
        time.sleep(0.03)
        self._post(WM_LBUTTONDOWN, MK_LBUTTON, _lparam(x, y))
        time.sleep(0.05)
        self._post(WM_LBUTTONUP, 0, _lparam(x, y))
        time.sleep(0.12)

    def click_screen(self, sx, sy):
        self.click_client(int(sx) - self.ox, int(sy) - self.oy)

    def drag_client(self, x0, y0, x1, y1, steps=14):
        self.wake()
        self._post(WM_MOUSEMOVE, 0, _lparam(x0, y0))
        time.sleep(0.04)
        self._post(WM_LBUTTONDOWN, MK_LBUTTON, _lparam(x0, y0))
        time.sleep(0.06)
        for i in range(1, steps + 1):
            x = int(x0 + (x1 - x0) * i / steps)
            y = int(y0 + (y1 - y0) * i / steps)
            self._post(WM_MOUSEMOVE, MK_LBUTTON, _lparam(x, y))
            time.sleep(0.02)
        time.sleep(0.04)
        self._post(WM_LBUTTONUP, 0, _lparam(x1, y1))
        time.sleep(0.12)

    def drag_screen(self, x0, y0, x1, y1, steps=14):
        self.drag_client(int(x0) - self.ox, int(y0) - self.oy,
                         int(x1) - self.ox, int(y1) - self.oy, steps)

    def wheel_client(self, x, y, delta):
        self.wake()
        sx, sy = self.ox + int(x), self.oy + int(y)
        self._post(WM_MOUSEWHEEL, (int(delta) & 0xFFFF) << 16,
                   _lparam(sx, sy))
        time.sleep(0.15)

    def ime_text(self, text, per_char=0.012):
        self.wake()
        data = str(text).encode("utf-16-le")
        for i in range(0, len(data), 2):
            ch = int.from_bytes(data[i:i + 2], "little")
            if ch == 10:
                self._post(0x0290, 0x0D, 1)
                time.sleep(0.02)
                self._post(0x0291, 0x0D, 1)
            else:
                self._post(0x0286, ch, 1)
            time.sleep(per_char)
        time.sleep(0.12)

    def ime_key(self, name, times=1, gap=0.05):
        self.wake()
        vk = VK.get(str(name).lower())
        if vk is None:
            vk = int(name, 0)
        for _ in range(times):
            self._post(0x0290, vk, 1)
            time.sleep(0.02)
            self._post(0x0291, vk, 1)
            time.sleep(gap)
        time.sleep(0.08)

    def capture(self):
        frame, _, _ = av.capture_window(self.info, True)
        return frame

    def save_shot(self, tag):
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            frame = self.capture()
            if frame is not None:
                path = os.path.join(
                    SHOT_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.png")
                Image.fromarray(frame).save(path)
                log(f"截图 → {path}")
        except Exception as exc:  # noqa: BLE001
            log(f"截图失败：{exc}")


# ---------------------------------------------------------------------- #
# 系统文件对话框（视频/封面/字幕上传共用）
# ---------------------------------------------------------------------- #
def _class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
    return buf.value


def _proc_of(hwnd):
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(
        ctypes.c_void_p(hwnd), ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        n = wintypes.DWORD(512)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(n))
        return os.path.basename(buf.value).lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def find_dialog(timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _):
            try:
                if _class_of(hwnd) != "#32770":
                    return True
                if _proc_of(hwnd) != "msedge.exe":
                    return True
                if not ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                    return True
                found.append(int(hwnd))
            except Exception:  # noqa: BLE001
                pass
            return True
        ctypes.windll.user32.EnumWindows(_cb, None)
        if found:
            return found[0]
        time.sleep(0.3)
    return None


def _focus_child(hwnd):
    class GTI(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT)]
    tid = ctypes.windll.user32.GetWindowThreadProcessId(
        ctypes.c_void_p(hwnd), None)
    gti = GTI()
    gti.cbSize = ctypes.sizeof(GTI)
    if ctypes.windll.user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
        return int(gti.hwndFocus or 0) or hwnd
    return hwnd


def dialog_choose(path, timeout=8.0):
    hwnd = find_dialog(timeout)
    if not hwnd:
        return False
    target = _focus_child(hwnd)
    data = str(path).encode("utf-16-le")
    for i in range(0, len(data), 2):
        ch = int.from_bytes(data[i:i + 2], "little")
        ctypes.windll.user32.PostMessageW(
            ctypes.c_void_p(target), 0x0102, ch, 1)
        time.sleep(0.008)
    time.sleep(0.25)
    scan = ctypes.windll.user32.MapVirtualKeyW(0x0D, 0)
    ctypes.windll.user32.PostMessageW(
        ctypes.c_void_p(target), 0x0100, 0x0D, 1 | (scan << 16))
    time.sleep(0.03)
    ctypes.windll.user32.PostMessageW(
        ctypes.c_void_p(target), 0x0101, 0x0D,
        1 | (scan << 16) | (1 << 30) | (1 << 31))
    time.sleep(0.5)
    return find_dialog(1.0) is None


# ---------------------------------------------------------------------- #
# UI Automation（只读定位，不做 ValuePattern.SetValue）
# ---------------------------------------------------------------------- #
class Uia:
    def __init__(self, hwnd, ps1_path=PS1_PATH):
        self.hwnd = hwnd
        self.ps1 = ps1_path
        os.makedirs(os.path.dirname(ps1_path), exist_ok=True)
        with open(ps1_path, "w", encoding="utf-8") as f:
            f.write(UIA_PS)

    def _run(self, mode, query="", type_=""):
        args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", self.ps1, "-Hwnd", str(self.hwnd), "-Mode", mode]
        if query:
            args += ["-Query", query]
        if type_:
            args += ["-Type", type_]
        try:
            proc = subprocess.run(args, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            log("UIA 查询超时")
            return []
        raw = proc.stdout.decode("utf-8", "replace").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [data] if isinstance(data, dict) else data

    def url(self):
        els = self._run("url")
        return els[0]["value"] if els else ""

    def find(self, pattern, type_=None):
        return self._run("find", pattern, type_ or "")

    def edits(self):
        return self._run("edits")

    def dump(self):
        return self._run("dump")


class Auto:
    def __init__(self, material, args):
        self.material = material
        self.args = args
        self.task = load_material(material) if material else {}
        self.win = None
        self.uia = None
        self.doc = None
        self.report = {"stages": {}, "bv": "", "title": "", "material": material}

    # ---- 基础 -------------------------------------------------------- #
    def connect(self):
        info = Win.find_edge()
        if info is None:
            log("未找到创作中心窗口，启动 Edge…")
            try:
                subprocess.Popen(["msedge.exe", "--new-window", UPLOAD_URL])
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"启动 Edge 失败：{exc}") from exc
            for _ in range(30):
                time.sleep(1)
                info = Win.find_edge()
                if info is not None:
                    break
        if info is None:
            raise RuntimeError("找不到哔哩哔哩创作中心窗口（请确认已登录）")
        self.win = Win(info.hwnd)
        self.uia = Uia(info.hwnd)
        self.refresh_doc()
        self.report["hwnd"] = info.hwnd
        self.report["window"] = info.title

    def refresh_doc(self):
        docs = [e for e in self.uia.find("创作中心|哔哩哔哩|upload", "Document")]
        if not docs:
            docs = [e for e in self.uia.dump() if e["type"] == "Document"]
        if not docs:
            docs = [e for e in self.uia.dump() if e["type"] == "Pane"]
        if docs:
            docs.sort(key=lambda e: -e["w"] * e["h"])
            self.doc = docs[0]
        else:
            cl, ct, cr, cb = self.win.info.client_rect
            self.doc = {"x": cl, "y": ct, "w": cr - cl, "h": cb - ct}

    def visible(self, e):
        if not e or e["w"] <= 0 or e["h"] <= 0:
            return False
        if e["offscreen"]:
            return False
        return (self.doc["y"] + 4 <= e["y"] + e["h"] / 2
                <= self.doc["y"] + self.doc["h"] - 8)

    def page_center(self):
        return (self.doc["x"] + self.doc["w"] // 2,
                self.doc["y"] + self.doc["h"] // 2)

    def wheel_page(self, delta):
        cx, cy = self.page_center()
        self.win.wheel_client(cx - self.win.ox, cy - self.win.oy, delta)

    def scroll_to(self, pattern, type_=None, max_steps=16, prefer_exact=False):
        last = None
        for _ in range(max_steps):
            els = self.uia.find(pattern, type_)
            if prefer_exact:
                exact = [e for e in els if e["name"] == pattern]
                els = exact or els
            if not els:
                return None
            e = els[0]
            last = e
            if self.visible(e):
                return e
            center = self.doc["y"] + self.doc["h"] / 2
            self.wheel_page(-600 if e["y"] > center else 600)
            time.sleep(0.45)
        return last

    def click(self, e):
        if not e:
            return False
        if not self.visible(e):
            e = self.scroll_to(re.escape(e["name"]), e["type"])
            if not e or not self.visible(e):
                log(f"控件不在可见区：{e and e['name']}")
                return False
        self.win.click_screen(e["x"] + e["w"] / 2, e["y"] + e["h"] / 2)
        return True

    def click_xy(self, label, dx, dy):
        self.win.click_screen(label["x"] + dx, label["y"] + dy)

    def label(self, name, type_="Text"):
        e = self.scroll_to(f"^{re.escape(name)}$", type_, max_steps=18,
                           prefer_exact=True)
        if e and e["name"].strip() != name:
            e = None
        return e

    def edit_near(self, label, max_dy=90):
        best = None
        for e in self.uia.edits():
            if e["w"] <= 20 or e["h"] <= 8:
                continue
            dy = abs((e["y"] + e["h"] / 2) - (label["y"] + label["h"] / 2))
            if e["x"] > label["x"] + 60 and dy <= max_dy:
                if best is None or dy < best[0]:
                    best = (dy, e)
        return best[1] if best else None

    def wait_text(self, pattern, timeout=60, type_=None):
        end = time.time() + timeout
        while time.time() < end:
            els = [e for e in self.uia.find(pattern, type_) if e["name"]]
            if els:
                return els[0]
            time.sleep(1.0)
        return None

    def shot(self, tag):
        self.win.save_shot(tag)

    # ---- 页面导航 ---------------------------------------------------- #
    def dismiss_leave(self):
        if not self.uia.find("确定要离开吗"):
            return False
        for e in self.uia.find("^确定$"):
            if not e["offscreen"] and e.get("enabled", True):
                self.click(e)
                time.sleep(1)
                return True
        return False

    def ensure_upload_page(self, force_upload=False):
        url = self.uia.url()
        log(f"当前 URL：{url}")
        if "/upload/video/frame" in url and "type=edit" not in url:
            return "upload"
        if "type=edit" in url and not force_upload:
            return "edit"
        link = self.scroll_to("投稿", "Hyperlink", prefer_exact=False)
        if link:
            self.click(link)
            time.sleep(2)
            self.dismiss_leave()
            time.sleep(1)
            self.refresh_doc()
            return self.ensure_upload_page(force_upload)
        raise RuntimeError(f"无法进入投稿页（当前 {url}）")

    def dismiss_drafts(self):
        for name in ("不用了", "继续编辑"):
            els = self.uia.find(f"^{name}$")
            if els and els[0].get("enabled", True):
                if name == "不用了":
                    log("丢弃本地草稿提示")
                    self.click(els[0])
                    time.sleep(1)
                return

    # ---- 素材上传 ---------------------------------------------------- #
    def upload_video(self):
        log("上传视频…")
        entry = self.scroll_to("^上传视频$", "Text", prefer_exact=True)
        if not entry:
            entry = self.scroll_to("点击上传或将视频拖拽到此区域", "Text")
        if not entry:
            raise RuntimeError("找不到上传视频入口")
        self.click(entry)
        if not dialog_choose(self.task["video"]):
            raise RuntimeError("视频文件对话框未出现/未被接受")
        log("等待上传完成…")
        ok = self.wait_text("^上传完成$", timeout=self.args.upload_timeout)
        if not ok:
            self.shot("upload_timeout")
            raise RuntimeError("等待上传完成超时")
        time.sleep(1.5)
        self.refresh_doc()
        self.report["stages"]["upload"] = "ok"

    def set_title(self, title):
        label = self.label("标题")
        if not label:
            raise RuntimeError("找不到标题标签")
        edit = self.edit_near(label)
        if not edit:
            raise RuntimeError("找不到标题输入框")
        log(f"标题：{title}")
        self.click(edit)
        self.win.ime_key("end")
        self.win.ime_key("backspace", times=len(edit.get("value") or "") + 6)
        self.win.ime_text(title)
        time.sleep(0.6)
        label2 = self.label("标题")
        edit2 = self.edit_near(label2) if label2 else None
        got = (edit2 or {}).get("value") or ""
        if got and title not in got:
            log(f"标题回读不一致：{got[:40]}")
        self.report["title"] = title

    def set_zone(self, zone):
        label = self.label("分区")
        if not label:
            log("找不到分区标签，跳过")
            return
        trigger = self.edit_near(label, max_dy=80)
        if trigger:
            self.click(trigger)
        else:
            self.click_xy(label, 260, 18)
        time.sleep(0.8)
        opt = None
        for e in self.uia.find(f"^{re.escape(zone)}$", "Text"):
            if e["y"] >= label["y"] - 20 and e["x"] < label["x"] + 700:
                opt = e
                break
        if opt is None:
            self.wheel_page(-500)
            time.sleep(0.5)
            for e in self.uia.find(f"^{re.escape(zone)}$", "Text"):
                if e["y"] >= label["y"] - 20:
                    opt = e
                    break
        if opt is None:
            log(f"分区选项中找不到 {zone}")
            return
        self.click(opt)
        time.sleep(0.6)
        log(f"分区：{zone}")

    def tag_slots(self):
        for e in self.uia.find(r"还可以添加\d+个标签", "Text"):
            m = re.search(r"(\d+)", e["name"])
            if m:
                return int(m.group(1))
        return None

    def clear_and_add_tags(self, tags):
        label = self.label("标签")
        if not label:
            log("找不到标签区，跳过")
            return
        edit = None
        for e in self.uia.edits():
            if "创建标签" in e["name"] or "标签" in e["name"]:
                edit = e
                break
        if edit is None:
            edit = self.edit_near(label, max_dy=110)
        if edit is None:
            log("找不到标签输入框，跳过")
            return
        self.click(edit)
        self.win.ime_key("backspace", times=20)
        time.sleep(0.4)
        slots = self.tag_slots()
        if slots is not None and slots != 10:
            log(f"清空后仍占用 {10 - slots} 个旧标签，继续追加")
        added = 0
        for tag in tags:
            self.win.ime_text(tag)
            self.win.ime_key("enter")
            time.sleep(0.35)
            added += 1
        left = self.tag_slots()
        log(f"标签：{added}/{len(tags)}，剩余空位 {left}")
        self.report["tags"] = tags
        self.report["tag_slots_left"] = left

    def desc_counter(self):
        return None, None

    def clear_description(self, top, bottom, left, right):
        bx = (left + right) / 2 - self.win.ox
        by = (top + bottom) / 2 - self.win.oy
        self.win.wheel_client(bx, by, -1200)
        time.sleep(0.3)
        texts = [e for e in self.uia.find(".", "Text")
                 if left < e["x"] < right and top - 40 < e["y"] < bottom + 40
                 and e["name"] and not re.match(r"^\d+/\d+$", e["name"])]
        total = sum(len(e["name"]) for e in texts)
        if total <= 0:
            return
        last = max(texts, key=lambda e: e["y"])
        self.win.click_screen(last["x"] + last["w"] + 6,
                              last["y"] + last["h"] / 2)
        time.sleep(0.2)
        self.win.ime_key("end")
        log(f"清空简介：约 {total} 字")
        self.win.ime_key("backspace", times=total + 40, gap=0.025)
        time.sleep(0.3)

    def set_description(self, desc):
        if not desc:
            return
        label = self.label("简介")
        if not label:
            log("找不到简介区，跳过")
            return
        for _ in range(8):
            if label["y"] + 170 <= self.doc["y"] + self.doc["h"] - 20:
                break
            self.wheel_page(-300)
            time.sleep(0.4)
            els = [e for e in self.uia.find("^简介$", "Text") if e["name"] == "简介"]
            if els:
                label = els[0]
        x0, y0 = label["x"] + 180, label["y"] - 20
        x1 = label["x"] + 1050
        y1 = min(label["y"] + 160, self.doc["y"] + self.doc["h"] - 30)
        if y1 - y0 < 60:
            log(f"简介框可见高度不足：{y1 - y0}")
            return
        self.clear_description(y0, y1, x0, x1)
        self.win.click_screen(label["x"] + 400, label["y"] + 45)
        time.sleep(0.25)
        self.win.ime_text(desc)
        log(f"简介：写入 {len(desc)} 字")
        self.report["desc_len"] = len(desc)

    def expand_more(self):
        if self.uia.find("章节管理"):
            return True
        more = self.scroll_to("更多设置", "Text", prefer_exact=False)
        if not more:
            return False
        self.click(more)
        time.sleep(1.2)
        return bool(self.uia.find("章节管理"))

    def set_visibility(self, want):
        if not want:
            return
        target = "仅自己可见" if want == "self" else "公开可见"
        if not self.uia.find("^仅自己可见$|^公开可见$"):
            self.expand_more()
        label = self.scroll_to(f"^{target}$", "Text", prefer_exact=True)
        if not label:
            log(f"找不到可见范围选项：{target}")
            return
        if not label.get("enabled", True):
            log(f"可见范围当前不可改（{target}）")
            return
        self.click(label)
        time.sleep(0.5)
        log(f"可见范围：{target}")
        self.report["visibility"] = want

    def upload_cover(self, cover):
        if not cover:
            return
        label = self.label("封面")
        if not label:
            log("找不到封面区，跳过")
            return
        self.click_xy(label, 300, 100)
        time.sleep(2)
        title = self.wait_text("^封面制作$", timeout=8)
        if not title:
            log("封面编辑器未打开")
            return
        scroll_pt = (title["x"] + 120, self.doc["y"] + self.doc["h"] - 120)
        entry = None
        for _ in range(10):
            els = [e for e in self.uia.find("^上传封面$") if e["name"] == "上传封面"]
            if els:
                entry = els[0]
                if self.visible(entry):
                    break
            self.win.wheel_client(scroll_pt[0] - self.win.ox,
                                  scroll_pt[1] - self.win.oy, -400)
            time.sleep(0.5)
        if not entry or not self.visible(entry):
            log("封面编辑器里找不到上传入口")
            return
        self.click(entry)
        if not dialog_choose(cover):
            log("封面文件对话框未出现")
            return
        log("封面已载入，等待预览…")
        time.sleep(3)
        done = None
        for _ in range(10):
            els = [e for e in self.uia.find("^完成$", "Text") if e["name"] == "完成"]
            if els:
                done = els[0]
                if self.visible(done):
                    break
            self.win.wheel_client(scroll_pt[0] - self.win.ox,
                                  scroll_pt[1] - self.win.oy, -400)
            time.sleep(0.5)
        if done:
            self.click(done)
            time.sleep(1.5)
            self.report["stages"]["cover"] = "ok"
        else:
            log("找不到封面完成按钮")

    def add_chapters(self, chapters):
        if not chapters:
            return
        if not self.expand_more():
            log("更多设置无法展开，跳过章节")
            return
        btn = self.scroll_to("^编辑章节$", "Button", prefer_exact=True)
        if not btn:
            log("找不到编辑章节按钮")
            return
        if not btn.get("enabled", True):
            log("编辑章节当前不可用")
            return
        self.click(btn)
        time.sleep(2)
        text_ed = self.wait_text("章节文本编辑器", timeout=8)
        if text_ed:
            self.click(text_ed)
            time.sleep(1)
        edits = [e for e in self.uia.edits() if e["w"] * e["h"] > 40000]
        if not edits:
            log("找不到章节文本框")
            return
        box = max(edits, key=lambda e: e["w"] * e["h"])
        self.click(box)
        self.win.ime_text("\n".join(chapters))
        conv = self.scroll_to("转换成章节列表", None)
        if not conv:
            log("找不到转换按钮")
            return
        self.click(conv)
        time.sleep(2)
        save = self.scroll_to("^保存$", "Button", prefer_exact=True)
        if save:
            self.click(save)
            time.sleep(2)
            self.report["stages"]["chapters"] = len(chapters)
        else:
            log("找不到章节保存按钮")

    def add_topic(self, topic):
        if not topic:
            return
        link = self.scroll_to("搜索更多话题", "Text")
        if not link:
            log("找不到话题入口")
            return
        self.click(link)
        time.sleep(1)
        opt = None
        for _ in range(6):
            els = [e for e in self.uia.find(re.escape(topic))
                   if e["name"] == topic]
            if els:
                opt = els[0]
                if self.visible(opt):
                    break
            self.wheel_page(-400)
            time.sleep(0.5)
        if not opt:
            log(f"话题列表里找不到 {topic}")
            return
        self.click(opt)
        time.sleep(0.5)
        ok = self.scroll_to("^确定$", "Button", prefer_exact=True)
        if ok:
            self.click(ok)
            time.sleep(1)
            self.report["topic"] = topic
        else:
            log("找不到话题确定按钮")

    def upload_subtitle(self, srt):
        if not srt:
            return
        btn = self.scroll_to("^上传字幕$", None, prefer_exact=True)
        if not btn:
            log("找不到上传字幕按钮")
            return
        if not btn.get("enabled", True):
            log("上传字幕当前不可用")
            return
        self.click(btn)
        time.sleep(1.5)
        up = self.wait_text("^上传文件$", timeout=6)
        if not up:
            log("字幕对话框里找不到上传文件")
            return
        self.click(up)
        if not dialog_choose(srt):
            log("字幕文件对话框未出现")
            return
        time.sleep(2)
        ok = self.wait_text("^确认$", timeout=6)
        if ok:
            self.click(ok)
            time.sleep(1.5)
            self.report["stages"]["subtitle"] = "ok"
        else:
            log("找不到字幕确认按钮")

    def submit(self):
        btn = self.scroll_to("立即投稿", "Text", prefer_exact=True)
        if not btn:
            raise RuntimeError("找不到立即投稿按钮")
        self.click(btn)
        log("已点击立即投稿，等待结果…")
        ok = self.wait_text("稿件投递成功", timeout=self.args.submit_timeout)
        if not ok:
            self.shot("submit_timeout")
            raise RuntimeError("未检测到稿件投递成功")
        self.report["stages"]["submit"] = "ok"
        time.sleep(1)
        detail = self.wait_text("查看进度", timeout=6)
        if detail:
            self.click(detail)
            time.sleep(3)
        for _ in range(10):
            url = self.uia.url()
            m = re.search(r"bvid=(BV[0-9A-Za-z]+)", url)
            if m:
                self.report["bv"] = m.group(1)
                break
            time.sleep(1)
        self.report["url"] = self.uia.url()
        log(f"BV：{self.report['bv'] or '未读取到'}")

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self.report, f, ensure_ascii=False, indent=1)
        except Exception:  # noqa: BLE001
            pass

    # ---- 主流程 ------------------------------------------------------ #
    def run(self):
        self.connect()
        page = self.ensure_upload_page(force_upload=not self.args.edit)
        self.report["page"] = page
        if page == "upload":
            self.dismiss_drafts()
            self.upload_video()
        if not self.args.only or "basic" in self.args.only:
            self.set_title(self.task["title"])
            self.set_zone(self.task.get("zone", "游戏"))
            self.clear_and_add_tags(self.task.get("tags", []))
            self.set_description(self.task.get("desc", ""))
        if not self.args.only or "chapters" in self.args.only:
            self.add_chapters(self.task.get("chapters", []))
        if not self.args.only or "cover" in self.args.only:
            self.upload_cover(self.args.cover or self.task.get("cover"))
        if not self.args.only or "topic" in self.args.only:
            self.add_topic(self.args.topic or self.task.get("topic"))
        if not self.args.only or "subtitle" in self.args.only:
            self.upload_subtitle(self.args.subtitle or self.task.get("subtitle"))
        if not self.args.only or "visibility" in self.args.only:
            self.set_visibility(self.args.visibility)
        if self.args.dry_run:
            log("dry-run：停在提交前")
            self.save_state()
            return self.report
        self.submit()
        self.save_state()
        return self.report


# ---------------------------------------------------------------------- #
# 素材解析
# ---------------------------------------------------------------------- #
def _read(path):
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


def _after(text, key):
    m = re.search(rf"{re.escape(key)}\s*[:：]\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _after_multiline(text, key):
    m = re.search(rf"{re.escape(key)}\s*[:：][ \t]*\r?\n\s*(.+)", text)
    if m:
        return m.group(1).strip()
    return _after(text, key)


def _section(text, start_marker, end_markers):
    i = text.find(start_marker)
    if i < 0:
        return ""
    body = text[i + len(start_marker):]
    end = len(body)
    for mark in end_markers:
        j = body.find(mark)
        if 0 <= j < end:
            end = j
    return body[:end].strip()


def load_material(folder):
    folder = os.path.abspath(folder)
    info_path = os.path.join(folder, "投稿信息.txt")
    video_info_path = os.path.join(folder, "视频信息.txt")
    info = _read(info_path) if os.path.isfile(info_path) else ""
    vinfo = _read(video_info_path) if os.path.isfile(video_info_path) else ""
    task = {
        "folder": folder,
        "title": _after_multiline(info, "中文标题") or _after(vinfo, "标题"),
        "zone": "",
        "tags": [],
        "chapters": [],
        "desc": "",
        "topic": "",
        "video": "",
        "cover": "",
        "subtitle": "",
    }
    zone = _after(vinfo, "分区") or _after(info, "分区") or "游戏"
    task["zone"] = re.split(r"[；;]", zone)[0].strip()
    m = re.search(r"标签[^\n]*[:：]\s*\n?\s*(.+)", info)
    if m:
        raw = m.group(1).strip()
        task["tags"] = [t.strip() for t in re.split(r"[,，]", raw) if t.strip()]
    for line in info.splitlines():
        s = line.strip()
        if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s+\S", s):
            task["chapters"].append(s)
    desc_block = _section(vinfo, "投稿物料", ["标签：", "分区：", "话题："])
    dm = re.search(r"简介\s*[:：]\s*(.+?)(?:\n标签\s*[:：]|\Z)", desc_block, re.S)
    if dm:
        task["desc"] = dm.group(1).strip()
    if not task["desc"]:
        dm = re.search(r"简介\s*[:：]\s*(.+?)(?:\n标签\s*[:：]|\Z)", vinfo, re.S)
        if dm:
            task["desc"] = dm.group(1).strip()
    files = os.listdir(folder) if os.path.isdir(folder) else []
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".mov"))]
    if videos:
        task["video"] = os.path.join(
            folder, max(videos, key=lambda f: os.path.getsize(os.path.join(folder, f))))
    covers = [f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    if covers:
        task["cover"] = os.path.join(folder, covers[0])
    subs = [f for f in files if f.lower().endswith(".srt")]
    if subs:
        subs.sort(key=lambda f: ("校准" not in f, f))
        task["subtitle"] = os.path.join(folder, subs[0])
    topic_map = [
        ("鸣潮", "鸣潮创作激励计划"),
        ("终末地", "明日方舟创作者应援计划"),
        ("明日方舟", "明日方舟创作者应援计划"),
        ("星穹铁道", "崩坏：星穹铁道创作者激励计划"),
        ("绝区零", "绝区零UP主激励计划"),
        ("王者荣耀", "王者荣耀UP主激励计划"),
        ("三角洲", "三角洲欢乐剧场"),
        ("蛋仔", "蛋仔奇思妙想计划"),
    ]
    for key, topic in topic_map:
        if key in task["title"]:
            task["topic"] = topic
            break
    return task


def probe(args):
    info = Win.find_edge()
    if info is None:
        print(json.dumps({"error": "找不到 Edge 创作中心窗口"}, ensure_ascii=False))
        return 1
    win = Win(info.hwnd)
    uia = Uia(info.hwnd)
    doc = uia.find("创作中心|哔哩哔哩", "Document")
    out = {
        "hwnd": info.hwnd,
        "title": info.title,
        "client": list(win.info.client_rect),
        "url": uia.url(),
        "doc": doc[0] if doc else None,
        "edits": uia.edits(),
        "labels": [e for e in uia.find("标题|简介|标签|分区|封面|更多设置|立即投稿|字幕设置|章节管理")
                   if e["name"]],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="B站后台自动投稿（UIA 通用定位）")
    ap.add_argument("material", nargs="?", help="素材目录（含 投稿信息.txt/视频信息.txt/视频/封面/SRT）")
    ap.add_argument("--probe", action="store_true", help="只输出当前页面的 UIA 结构")
    ap.add_argument("--title", default="")
    ap.add_argument("--desc", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--topic", default="")
    ap.add_argument("--zone", default="")
    ap.add_argument("--cover", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--visibility", choices=["self", "public"], default="self")
    ap.add_argument("--edit", action="store_true",
                    help="修复当前编辑页（不新上传视频）；默认新投稿")
    ap.add_argument("--only", default="", help="只跑某些阶段，逗号分隔：basic,chapters,cover,topic,subtitle,visibility")
    ap.add_argument("--dry-run", action="store_true", help="填完但不点立即投稿")
    ap.add_argument("--upload-timeout", type=int, default=900)
    ap.add_argument("--submit-timeout", type=int, default=180)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.probe:
        return probe(args)
    if not args.material:
        ap.error("需要素材目录（或使用 --probe）")
    args.only = [s.strip() for s in args.only.split(",") if s.strip()]
    auto = Auto(args.material, args)
    try:
        report = auto.run()
    except Exception as exc:  # noqa: BLE001
        log(f"失败：{exc}")
        if auto.win:
            auto.shot("fail")
        report = {"error": str(exc), **auto.report}
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=1))
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        log(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
