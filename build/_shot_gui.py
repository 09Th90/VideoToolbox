# -*- coding: utf-8 -*-
"""临时工具：启动 GUI（投稿页演示模式）→ 按 PID 找窗口 → 截图 → 关闭。"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

os.environ["VT_SHOT_TAB"] = sys.argv[1] if len(sys.argv) > 1 else "upload"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, "tools", "python", "python.exe")
GUI = os.path.join(ROOT, "src", "video_toolbox_gui.py")
OUT = os.path.join(ROOT, "build", "gui_upload_tab_v192.png")

proc = subprocess.Popen([PY, GUI], cwd=ROOT)

user32 = ctypes.windll.user32


def find_window(pid, timeout=25):
    deadline = time.time() + timeout
    found = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        p = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "视频工具箱" in buf.value:
                found.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    while time.time() < deadline:
        found.clear()
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        if found:
            return found[0]
        time.sleep(0.5)
    return None


hwnd = find_window(proc.pid)
if not hwnd:
    print("FAIL: 未找到 GUI 窗口")
    proc.terminate()
    sys.exit(1)

time.sleep(8.0 if sys.argv[1:] == ["calib_run"] else 2.5)  # 校准演示需等子进程跑完

rect = wt.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
w, h = rect.right - rect.left, rect.bottom - rect.top

# PrintWindow 直接绘制窗口内容到内存 DC：即使被全屏游戏遮挡也能截到本窗口
from PIL import Image
gdi32 = ctypes.windll.gdi32
hwnd_dc = user32.GetWindowDC(hwnd)
mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
gdi32.SelectObject(mfc_dc, bmp)
ok = user32.PrintWindow(hwnd, mfc_dc, 2)  # PW_RENDERFULLCONTENT
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
bmi = BITMAPINFOHEADER()
bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bmi.biWidth, bmi.biHeight = w, -h   # 负高度 = 自上而下
bmi.biPlanes, bmi.biBitCount = 1, 32
buf = ctypes.create_string_buffer(w * h * 4)
gdi32.GetDIBits(mfc_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
gdi32.DeleteObject(bmp)
gdi32.DeleteDC(mfc_dc)
user32.ReleaseDC(hwnd, hwnd_dc)
print("PrintWindow:", ok)
img.convert("RGB").save(OUT)
print("OK:", OUT, img.size)

proc.terminate()
try:
    proc.wait(timeout=5)
except Exception:
    proc.kill()
