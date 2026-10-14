# -*- coding: utf-8 -*-
"""pin.py — 把 HTML 片段写进系统剪贴板，供富文本站点「原生粘贴」（03-操作模式库 M7）。

跨平台能力：
    Windows  CF_HTML + CF_UNICODETEXT 双格式（ctypes/Win32；64 位句柄声明 = 04-坑9）
    macOS    AppleScript「«class HTML» + string」双格式；失败自动降级 pbcopy 纯文本
    Linux    wl-copy --type text/html（有则优先）或 xclip -t text/html；
             ★ rich 与 plain 无法同服务（xclip 单 target）——rich 模式写入后，请求纯文本的
               粘贴方会落空；要贴纯文本请显式调用 set_clipboard_text()

用法：
    import pin
    pin.set_clipboard_html("<h2>标题</h2><p>段落</p>", "标题\\n段落")
    # 然后把光标放进页面编辑器 → tab.paste()（见 03-M7）

能力探测：pin.supports_html() / pin.supports_text()；能力缺失时抛明确 RuntimeError（import 不报错）。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

_IS_WIN = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")

GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13

_user32 = None
_kernel32 = None


# ── Windows（ctypes/Win32） ──

def _win_load():
    """加载 Win32 绑定（仅首次；非 Windows 调用由公共入口拦截）。"""
    global _user32, _kernel32
    if _user32 is not None:
        return
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.RegisterClipboardFormatW.restype = wintypes.UINT
    _user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]


def _win_open_clipboard():
    for _ in range(30):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(0.1)
    return False


def _win_set_html(data_bytes):
    import ctypes
    fmt = _user32.RegisterClipboardFormatW("HTML Format")
    h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data_bytes))
    assert h, "alloc1"
    p = _kernel32.GlobalLock(h)
    ctypes.memmove(p, data_bytes, len(data_bytes))
    _kernel32.GlobalUnlock(h)
    assert _win_open_clipboard(), "open clipboard failed"
    _user32.EmptyClipboard()
    assert _user32.SetClipboardData(fmt, h), "set html failed"
    _user32.CloseClipboard()
    return True


def _win_set_text(txt):
    import ctypes
    tb = txt.encode("utf-16-le") + b"\x00\x00"
    h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(tb))
    p = _kernel32.GlobalLock(h)
    ctypes.memmove(p, tb, len(tb))
    _kernel32.GlobalUnlock(h)
    assert _win_open_clipboard(), "open clipboard failed"
    _user32.SetClipboardData(CF_UNICODETEXT, h)     # 不清空 —— 与 CF_HTML 双格式共存
    _user32.CloseClipboard()


# ── 能力探测 ──

def supports_text():
    """本机是否支持纯文本写入剪贴板。"""
    if _IS_WIN or _IS_MAC:
        return True
    if _IS_LINUX:
        return bool(shutil.which("xclip") or shutil.which("wl-copy"))
    return False


def supports_html():
    """本机是否支持富文本（HTML）写入剪贴板（mac 失败时自动降级纯文本）。"""
    if _IS_WIN or _IS_MAC:
        return True
    if _IS_LINUX:
        return bool(shutil.which("wl-copy") or shutil.which("xclip"))
    return False


# ── 公共入口 ──

def set_clipboard_text(text):
    """纯文本写入系统剪贴板（跨平台）。返回写入长度。"""
    text = "" if text is None else str(text)
    if _IS_WIN:
        _win_load()
        _win_set_text(text)
        return len(text)
    if _IS_MAC:
        p = subprocess.run(["pbcopy"], input=text.encode("utf-8"))
        if p.returncode != 0:
            raise RuntimeError("pbcopy 失败（rc=%s）" % p.returncode)
        return len(text)
    if _IS_LINUX:
        if shutil.which("xclip"):
            p = subprocess.run(["xclip", "-selection", "clipboard", "-i"],
                               input=text.encode("utf-8"))
            if p.returncode == 0:
                return len(text)
        if shutil.which("wl-copy"):
            p = subprocess.run(["wl-copy"], input=text.encode("utf-8"))
            if p.returncode == 0:
                return len(text)
        raise RuntimeError("Linux 剪贴板工具缺失：请安装 xclip（apt install xclip）或 wl-clipboard")
    raise RuntimeError("不支持的平台: " + sys.platform)


def set_clipboard_html(fragment, plain=None):
    """把 HTML 片段写进剪贴板（富文本站点的原生粘贴源）。plain = 纯文本兜底（None → 取 fragment）。
    返回写入字节数。"""
    fragment = "" if fragment is None else str(fragment)
    plain_txt = fragment if plain is None else str(plain)
    if _IS_WIN:
        return _win_set_clipboard_html(fragment, plain_txt)
    if _IS_MAC:
        return _mac_set_clipboard_html(fragment, plain_txt)
    if _IS_LINUX:
        return _linux_set_clipboard_html(fragment)
    raise RuntimeError("不支持的平台: " + sys.platform)


# ── 各平台实现 ──

def _cf_html(fragment):
    """构造 CF_HTML 载荷。偏移量按 UTF-8 字节数精确计算（不是字符数）。"""
    html = "<html><body><!--StartFragment-->" + fragment + "<!--EndFragment--></body></html>"
    header_t = ("Version:0.9\r\n"
                "StartHTML:{sh:010d}\r\n"
                "EndHTML:{eh:010d}\r\n"
                "StartFragment:{sf:010d}\r\n"
                "EndFragment:{ef:010d}\r\n")
    base = len(header_t.format(sh=0, eh=0, sf=0, ef=0).encode("utf-8"))
    pre = "<html><body><!--StartFragment-->"
    sf = base + len(pre.encode("utf-8"))
    ef = sf + len(fragment.encode("utf-8"))
    eh = base + len(html.encode("utf-8"))
    header = header_t.format(sh=base, eh=eh, sf=sf, ef=ef)
    return (header + html).encode("utf-8") + b"\x00"


def _win_set_clipboard_html(fragment, plain_txt):
    _win_load()
    data = _cf_html(fragment)
    _win_set_html(data)
    _win_set_text(plain_txt)
    return len(data)


def _mac_set_clipboard_html(fragment, plain_txt):
    """AppleScript 双格式（«class HTML» + string）；任何失败 → pbcopy 纯文本兜底。"""
    html = "<html><body><!--StartFragment-->" + fragment + "<!--EndFragment--></body></html>"
    hp = tp = None
    try:
        fd, hp = tempfile.mkstemp(prefix="qqqpin_", suffix=".html")
        os.close(fd)
        with open(hp, "wb") as f:
            f.write(html.encode("utf-8"))
        fd, tp = tempfile.mkstemp(prefix="qqqpin_", suffix=".txt")
        os.close(fd)
        with open(tp, "wb") as f:
            f.write(plain_txt.encode("utf-8"))
        script = (
            'set h to (read (POSIX file "%s") as «class HTML»)\n'
            'set t to (read (POSIX file "%s") as «class utf8»)\n'
            'set the clipboard to {«class HTML»:h, «class utf8»:t, string:t}'
        ) % (hp.replace("\\", "/"), tp.replace("\\", "/"))
        p = subprocess.run(["osascript", "-e", script],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 0:
            return len(html.encode("utf-8"))
        set_clipboard_text(plain_txt)      # 富文本失败 → 行为永不低于纯文本
        return len(plain_txt.encode("utf-8"))
    finally:
        for f in (hp, tp):
            if f:
                try:
                    os.unlink(f)
                except OSError:
                    pass


def _linux_set_clipboard_html(fragment):
    """wl-copy / xclip 写 text/html。★ 单 target 限制见模块 docstring。"""
    html = ("<html><body><!--StartFragment-->" + fragment +
            "<!--EndFragment--></body></html>").encode("utf-8")
    if shutil.which("wl-copy"):
        try:
            p = subprocess.run(["wl-copy", "--type", "text/html"], input=html)
            if p.returncode == 0:
                return len(html)
        except OSError:
            pass
    if shutil.which("xclip"):
        p = subprocess.run(["xclip", "-selection", "clipboard", "-t", "text/html", "-i"],
                           input=html)
        if p.returncode == 0:
            return len(html)
        raise RuntimeError("xclip 写入 text/html 失败（rc=%s）" % p.returncode)
    raise RuntimeError("Linux 剪贴板工具缺失：请安装 xclip（apt install xclip）或 wl-clipboard")


if __name__ == "__main__":
    n = set_clipboard_html("<p>clipboard test 段落</p>", "clipboard test 段落")
    print("html bytes:", n, "| platform:", sys.platform,
          "| supports_html:", supports_html())
