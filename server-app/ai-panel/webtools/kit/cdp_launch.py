# -*- coding: utf-8 -*-
"""cdp_launch.py — 一键：找到浏览器 → 以调试模式启动（专用 profile）→ 等就绪 → 打印标签。

用法：
    python cdp_launch.py                   # 默认端口 63788，专用 profile ~/.cdp-kit/profile
    python cdp_launch.py --url https://www.baidu.com
    python cdp_launch.py --attach-only     # 只检查连接（已在跑就复用，不新开）
    python cdp_launch.py --port 63800 --browser "D:\\Chrome\\chrome.exe"
    python cdp_launch.py --headless        # 无头（不建议：风控易触发 / 人看不见）

重复运行是安全的：检测到已有调试浏览器会直接复用。
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request


def _req(method, url, timeout=10):
    r = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEF_PORT = 63788

CANDIDATES_WIN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Chromium\Application\chrome.exe",
]
CANDIDATES_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
CANDIDATES_NIX = ["google-chrome", "google-chrome-stable", "chromium",
                  "chromium-browser", "microsoft-edge", "brave-browser"]


def find_browser(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("CDP_BROWSER")
    if env and os.path.exists(env):
        return env
    sysname = platform.system()
    if sysname == "Windows":
        cands = CANDIDATES_WIN
    elif sysname == "Darwin":
        cands = CANDIDATES_MAC
    else:
        cands = CANDIDATES_NIX
    from shutil import which
    for c in cands:
        if os.path.isabs(c):
            if os.path.exists(c):
                return c
        else:
            p = which(c)
            if p:
                return p
    return None


def http_get(url, timeout=3):
    try:
        return _req("GET", url, timeout)
    except Exception:
        return None


def wait_ready(port, budget=40):
    end = time.time() + budget
    while time.time() < end:
        v = http_get("http://127.0.0.1:%d/json/version" % port)
        if v:
            return v
        time.sleep(0.8)
    return None


def show_tabs(port):
    tabs = http_get("http://127.0.0.1:%d/json/list" % port) or []
    for i, t in enumerate(tabs):
        if t.get("type") == "page":
            print("  ", i, "|", (t.get("title") or "")[:50], "|", (t.get("url") or "")[:100])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEF_PORT)
    ap.add_argument("--profile", default=os.path.join(os.path.expanduser("~"), ".cdp-kit", "profile"))
    ap.add_argument("--url", default=None)
    ap.add_argument("--browser", default=None, help="浏览器可执行文件路径（默认自动找）")
    ap.add_argument("--attach-only", action="store_true")
    ap.add_argument("--headless", action="store_true", help="无头模式（不建议）")
    args = ap.parse_args()

    # 1) 已有调试浏览器？直接复用（重复运行安全）
    v = http_get("http://127.0.0.1:%d/json/version" % args.port)
    if v:
        print("[ok] 已有调试浏览器在运行:", v.get("Browser"))
        print("     复用现有实例，不新开。")
        if args.url:
            try:
                _req("PUT", "http://127.0.0.1:%d/json/new?%s" % (args.port, args.url))
            except Exception as e:
                print("[!] 开新页失败:", e)
        show_tabs(args.port)
        return 0
    if args.attach_only:
        print("[--] 没有检测到调试浏览器（端口 %d）" % args.port)
        return 1

    # 2) 找浏览器
    exe = find_browser(args.browser)
    if not exe:
        print("找不到 Chrome/Edge/Brave/Chromium。")
        print("请用 --browser 指定路径，或设环境变量 CDP_BROWSER。")
        return 2

    # 3) 启动
    os.makedirs(args.profile, exist_ok=True)
    cmd = [exe,
           "--remote-debugging-port=%d" % args.port,
           "--user-data-dir=%s" % args.profile,
           "--remote-allow-origins=*",
           "--no-first-run", "--no-default-browser-check",
           "--disable-popup-blocking"]
    if args.headless:
        cmd.append("--headless=new")
    if args.url:
        cmd.append(args.url)
    print("[*] 启动:", exe)
    print("     端口 %d | profile %s" % (args.port, args.profile))
    kwargs = {}
    if platform.system() == "Windows":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP —— 与当前控制台解耦，脚本退出浏览器还活着
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    subprocess.Popen(cmd, **kwargs)

    # 4) 等就绪
    v = wait_ready(args.port)
    if not v:
        print("[x] 等待就绪超时 —— 检查：端口被占用？浏览器弹了确认框？")
        return 3
    print("[ok] 已就绪:", v.get("Browser"))
    print("[i] 首次使用：在弹出的窗口里把目标网站登录一遍 —— 登录态长期保留。")
    show_tabs(args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
