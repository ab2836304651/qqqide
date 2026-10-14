# -*- coding: utf-8 -*-
"""qdbrowser.py — qd 受控浏览器：确保就绪 / 查询 / 停止（核心，仅用标准库）

qd 自带内核即浏览器：本工具把装包里的 joker（开发树里是 electron 内核）拉起为
「受控浏览器域」—— 独立 profile（登录态持久）、标准 CDP 调试口（8335 段）、
默认可见的浏览器窗口。就绪后端口写进报告文件 + 权威心跳 host.json，
cdp.py / 场景脚本自动读取（跨 TEMP 作用域亦可发现同一实例）。

命令行:
    python qdbrowser.py ensure            # 确保在跑（就绪即复用）→ 打印端点 JSON
    python qdbrowser.py ensure --hidden   # 静默档（无可见窗口；默认 30 分钟空闲自退）
    python qdbrowser.py ensure --url https://example.com   # 首次启动直接加载；复用则导航
    python qdbrowser.py ensure --exit-with <pid>           # 跟随监督进程（监督方退出→浏览器退出）
    python qdbrowser.py ensure --idle-exit 0               # 覆盖空闲自退分钟数（0=关；仅新建时生效）
    python qdbrowser.py status            # 当前端点；未运行 → 退出码 1
    python qdbrowser.py stop              # 停止（关闭浏览器；登录态保留）

找内核（默认自动）:
    QQQIDE_PYTHON_DIR（环境变量，回退注册表）→ 推导
      Windows 打包  <pack>/gh555.com/resources/app/engines/python → <pack>/gh555.com/joker.exe
      macOS   打包  qqqide.app/Contents/**/engines/python 或 qqqide-data/engines/python
                    → qqqide.app/Contents/MacOS/qqqide
      Linux   打包  <容器>/resources/app/engines/python 或 qqqide-data/engines/python → <容器>/qqqide
      开发树        <root>/engines/python → <root>/node_modules/electron/dist/electron[.exe]
    也可显式指定: --shell <内核路径> [--app <应用目录>]

作为库:
    import qdbrowser
    ep = qdbrowser.ensure_started()      # -> {"pid":..., "cdpPort":..., ...}
    ep = qdbrowser.read_live_endpoint()  # 只读现状（未运行 -> None）
    qdbrowser.stop()
"""
import argparse
import glob as _glob
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
_NO_WINDOW = 0x08000000                     # CREATE_NO_WINDOW（taskkill 用）
_DETACHED = 0x00000008 | 0x00000200         # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

# 能力探测词：只存在于「受控浏览器」壳层里（browser-host 的 --qqqide-browser-report）。
# ★ 不可用 'qqqide-browser'——旧包日志文件名（qqqide-browser-launch.log）会撞出假阳性，
#   导致老版本 qd 被误启动成 IDE（实测实锤）。
_PROBE_WORD = b"qqqide-browser-report"


def _norm(p):
    return os.path.normpath(p) if p else p


def _read_win_registry_pydir():
    if not IS_WIN:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v, _ = winreg.QueryValueEx(k, "QQQIDE_PYTHON_DIR")
            return v or None
    except Exception:
        return None


# ── 内核解析（跨平台） ──

def _mac_app_exe(bundle):
    """mac .app → Contents/MacOS 可执行体（优先 qqqide，另外 glob 兜底）。"""
    macos = os.path.join(bundle, "Contents", "MacOS")
    pref = os.path.join(macos, "qqqide")
    if os.path.exists(pref):
        return _norm(pref)
    try:
        for p in sorted(_glob.glob(os.path.join(macos, "*"))):
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return _norm(p)
    except Exception:
        pass
    return None


def _mac_app_exe_in(container):
    """容器目录下的 .app（优先 qqqide.app）→ 可执行体。"""
    b = os.path.join(container, "qqqide.app")
    if os.path.isdir(b):
        e = _mac_app_exe(b)
        if e:
            return e
    try:
        for app in sorted(_glob.glob(os.path.join(container, "*.app"))):
            e = _mac_app_exe(app)
            if e:
                return e
    except Exception:
        pass
    return None


def _kernel_candidates(py):
    """从 python 目录推导内核候选 [(exe, extra[])]（存在性已判定；首个命中的用）。"""
    out = []
    py = os.path.abspath(py)
    nb = py.replace("\\", "/")

    # ① 开发树：<root>/engines/python → node_modules/electron/dist/*
    if "/node_modules/electron/" not in nb.lower():
        dev_root = os.path.dirname(os.path.dirname(py))
        if IS_WIN:
            rel = "node_modules/electron/dist/electron.exe"
        elif IS_MAC:
            rel = "node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
        else:
            rel = "node_modules/electron/dist/electron"
        dev_bin = os.path.join(dev_root, *rel.split("/"))
        if os.path.exists(dev_bin):
            out.append((_norm(dev_bin), [_norm(dev_root)]))

    # ② macOS 打包：…/qqqide.app/Contents/**engines/python 或 …/qqqide-data/engines/python
    m = re.search(r"^(.*\.app)/Contents/(?:Resources/app/)?engines/python$", nb, re.I)
    if m:
        e = _mac_app_exe(_norm(m.group(1)))
        if e:
            out.append((e, []))
    m2 = re.search(r"^(.*)/qqqide-data/engines/python$", nb)
    if m2:
        container = _norm(m2.group(1))
        if IS_MAC:
            e = _mac_app_exe_in(container)
            if e:
                out.append((e, []))
        else:
            for name in ("qqqide", "qqqide-bin"):
                p = os.path.join(container, name)
                if os.path.exists(p):
                    out.append((_norm(p), []))
                    break

    # ③ Windows 打包：<pack>/gh555.com/resources/app/engines/python → joker.exe
    if IS_WIN:
        sh = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(py)))), "joker.exe")
        if os.path.exists(sh):
            out.append((_norm(sh), []))
    return out


def _autodetect_dev_app(exe):
    """显式 --shell 指向 electron 内核且未给 --app 时：向上找 <root>（package.json +
    node_modules/electron 双命中）——防「electron 裸启默认 app」；找不到 → None。"""
    base = os.path.basename(exe).lower()
    if not base.startswith("electron"):
        return None
    d = os.path.dirname(os.path.abspath(exe))
    for _ in range(6):
        try:
            if (os.path.exists(os.path.join(d, "package.json")) and
                    os.path.isdir(os.path.join(d, "node_modules", "electron"))):
                return _norm(d)
        except Exception:
            pass
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def _self_candidates():
    """从本文件位置推导内核候选 [(exe, extra[])]——装包内运行（运行副本/资源副本）、开发树均适用。
    mac/linux 没有 QQQIDE_PYTHON_DIR 注册表广播（那是 Windows 启动器写的）→ 本函数是主发现路径；
    Windows 下作为兜底（env 缺失/指向失效时仍可用）。"""
    out = []
    try:
        nb = os.path.abspath(__file__).replace("\\", "/")
        chain = []
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(14):
            chain.append(d)
            nd = os.path.dirname(d)
            if nd == d:
                break
            d = nd
        in_app_bundle = ".app/contents/" in nb.lower()

        # ① 开发树：…/<root>/server-app/ai-panel/webtools/kit → node_modules/electron
        for d in chain:
            if os.path.basename(d) == "server-app":
                root = os.path.dirname(d)
                rel = ("node_modules/electron/dist/electron.exe" if IS_WIN else
                       "node_modules/electron/dist/Electron.app/Contents/MacOS/Electron" if IS_MAC else
                       "node_modules/electron/dist/electron")
                p = os.path.join(root, *rel.split("/"))
                if os.path.exists(p):
                    out.append((_norm(p), [_norm(root)]))
                break

        # ② macOS 资源副本：…/X.app/Contents/Resources/app/webapp/…
        for d in chain:
            if d.endswith(".app") and os.path.isdir(os.path.join(d, "Contents", "MacOS")):
                e = _mac_app_exe(d)
                if e:
                    out.append((e, []))
                break

        # ③ 托管数据根：…/qqqide-data/Data/webapp/…（mac/linux 运行副本）；
        #    Windows 运行副本：…/gh555.com/Data/webapp/…（Data 父目录带 joker.exe）
        for d in chain:
            base = os.path.basename(d)
            parent = os.path.dirname(d)
            if base == "qqqide-data":
                if IS_MAC:
                    e = _mac_app_exe_in(parent)
                    if e:
                        out.append((e, []))
                elif not IS_WIN:
                    for name in ("qqqide", "qqqide-bin"):
                        p = os.path.join(parent, name)
                        if os.path.exists(p):
                            out.append((_norm(p), []))
                            break
                break
            if base == "Data" and IS_WIN and os.path.exists(os.path.join(parent, "joker.exe")):
                out.append((_norm(os.path.join(parent, "joker.exe")), []))
                break

        # ④ 容器资源副本：<容器>/resources/app/webapp/…（win/linux；mac 已被 ② 覆盖）
        if not in_app_bundle:
            for d in chain:
                if os.path.basename(d).lower() == "resources" and \
                        os.path.basename(os.path.dirname(d)).lower() != "contents":
                    cont = os.path.dirname(d)
                    if IS_WIN and os.path.exists(os.path.join(cont, "joker.exe")):
                        out.append((_norm(os.path.join(cont, "joker.exe")), []))
                    elif not IS_WIN:
                        for name in ("qqqide", "qqqide-bin"):
                            p = os.path.join(cont, name)
                            if os.path.exists(p):
                                out.append((_norm(p), []))
                                break
                    break
    except Exception:
        pass
    return out


def _bundle_main_js(bin_path, extra):
    """包壳层 bundle 路径（能力探测用；不存在 → None）。"""
    if extra:      # 开发树：app 根 = extra[0]
        p = os.path.join(extra[0], "shell-out", "main.js")
        return _norm(p) if os.path.exists(p) else None
    nb = os.path.abspath(bin_path).replace("\\", "/")
    m = re.match(r"^(.*\.app)/Contents/MacOS/[^/]+$", nb, re.I)
    if m:          # mac 打包：资源在 …app/Contents/Resources/app
        p = os.path.join(_norm(m.group(1)), "Contents", "Resources", "app", "shell-out", "main.js")
    else:          # win/linux：<宿主>/resources/app
        p = os.path.join(os.path.dirname(bin_path), "resources", "app", "shell-out", "main.js")
    return _norm(p) if os.path.exists(p) else None


def _supports_browser_host(bin_path, extra):
    """能力探测：包内壳层 bundle 是否含受控浏览器能力——旧包明确报错，而不是拉起旧内核傻等超时。
    布局未知（bundle 不存在）→ 放行尝试（超时提示兜底）。"""
    try:
        bundle = _bundle_main_js(bin_path, extra)
        if not bundle:
            return True
        with open(bundle, "rb") as f:
            return _PROBE_WORD in f.read()
    except Exception:
        return True


def resolve_shell(shell=None, app=None):
    """-> (内核路径, 附加参数[])。找不到抛 RuntimeError（含指引）。"""
    if shell:
        exe = _norm(shell)
        if not os.path.exists(exe):
            raise RuntimeError("--shell 指向的内核不存在: " + exe)
        if app:
            return exe, [_norm(app)]
        auto = _autodetect_dev_app(exe)
        return exe, ([auto] if auto else [])

    tried = []
    # ① 显式环境覆写（服务/脚本场景；跨平台）
    env_shell = os.environ.get("QQQIDE_SHELL")
    if env_shell:
        exe = _norm(env_shell)
        if os.path.exists(exe):
            if app:
                return exe, [_norm(app)]
            auto = _autodetect_dev_app(exe)
            return exe, ([auto] if auto else [])
        tried.append("QQQIDE_SHELL=" + env_shell + "（路径不存在）")
    # ② QQQIDE_PYTHON_DIR（Windows 启动器广播 / 环境预置）→ 推导
    pydir = os.environ.get("QQQIDE_PYTHON_DIR") or _read_win_registry_pydir()
    if pydir:
        py = _norm(pydir)
        tried.append(py)
        for cand, extra in _kernel_candidates(py):
            if os.path.exists(cand):
                return cand, extra
    # ③ 自身位置推导（装包运行副本/资源副本、开发树）——mac/linux 主路径
    for cand, extra in _self_candidates():
        if os.path.exists(cand):
            return cand, extra
    raise RuntimeError(
        "未找到 qd 内核（joker/qqqide）。已尝试: " + ("; ".join(tried) if tried else "无环境线索") +
        "\n请用 --shell 指定，或设置环境变量 QQQIDE_SHELL；例: --shell \"<装包>\\gh555.com\\joker.exe\"")



# ── 端点发现 ──

def default_report_path(shell_bin=None):
    """报告文件路径（按内核路径定名 → 同机多装包互不串）。"""
    try:
        shell_bin = shell_bin or resolve_shell()[0]
    except Exception:
        shell_bin = "qd"
    h = hashlib.sha1(os.path.abspath(shell_bin).lower().encode("utf-8", "replace")).hexdigest()[:8]
    return os.path.join(tempfile.gettempdir(), "qqq-browser-report-%s.json" % h)


def _expected_data_dir(shell_bin, app=None):
    """受控浏览器 userData 目录推导（{hostDir}/Data/browser-host）——同包判定 + 跨 TEMP 发现用。"""
    b = os.path.abspath(shell_bin)
    nb = b.replace("\\", "/")
    low = nb.lower()
    # 开发树：<root>/node_modules/electron/dist/...
    if "/node_modules/electron/" in low or "/electron/dist/" in low:
        root = _norm(app) if app else _norm(nb.split("/node_modules/", 1)[0])
        return os.path.join(root, "Data", "browser-host")
    # macOS bundle：<container>/qqqide.app/Contents/MacOS/<exe>
    m = re.match(r"^(.*\.app)/Contents/MacOS/[^/]+$", nb, re.I)
    if m:
        container = os.path.dirname(_norm(m.group(1)))
        return os.path.join(container, "qqqide-data", "Data", "browser-host")
    d = os.path.dirname(b)
    # Linux 容器（qqqide + qqqide-data 同层）
    if os.path.isdir(os.path.join(d, "qqqide-data")):
        return os.path.join(d, "qqqide-data", "Data", "browser-host")
    # Windows 打包（gh555.com 内）
    return os.path.join(d, "Data", "browser-host")


def _probe(port, timeout=2.5):
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % int(port), timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_report_file(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            ep = json.load(f)
    except Exception:
        return None
    if not isinstance(ep, dict) or not ep.get("ok") or not ep.get("cdpPort"):
        return None
    if not _probe(ep["cdpPort"]):
        return None
    return ep


def read_canonical_endpoint(shell_bin=None, app=None):
    """权威端点（TEMP 无关）：{expectedDataDir}/host.json 心跳文件（4s 刷、原子写）。
    IDE 内跑的 kit 与终端跑的 kit 互见同一实例（报告文件随 TEMP 分裂的根治）；同包判定亦用它。"""
    try:
        sb = shell_bin or resolve_shell(None, app)[0]
        dd = _expected_data_dir(sb, app)
    except Exception:
        return None
    hj = os.path.join(dd, "host.json")
    try:
        with open(hj, "r", encoding="utf-8") as f:
            h = json.load(f)
    except Exception:
        return None
    if not isinstance(h, dict) or not h.get("pid") or not h.get("cdpPort"):
        return None
    if not _probe(h.get("cdpPort"), 1.2):
        return None
    ep = dict(h)
    ep.update({"ok": True, "mode": "browser-host", "reused": True,
               "dataDir": dd, "hostJson": hj})
    return ep


def read_live_endpoint(report=None, shell_bin=None, app=None):
    """读端点（真相 = CDP 探测应答）。未运行 -> None。
    顺序：① 报告文件（显式 / 按内核定名）② 权威 host.json（跨 TEMP 发现）。"""
    rep = report
    if rep is None:
        try:
            shell_bin = shell_bin or resolve_shell(None, app)[0]
            rep = default_report_path(shell_bin)
        except Exception:
            rep = None
    ep = _read_report_file(rep) if rep else None
    if ep:
        return ep
    return read_canonical_endpoint(shell_bin, app)


def _same_dir(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:
        return False


def find_any_live_report(shell_bin=None, app=None):
    """扫描临时目录全部报告，返回仍在运行的端点。
    同包优先：能判定本包预期数据目录时只接受同包实例（防多装包互串）；
    推不出预期时才退回「首个在跑的」。"""
    expected = None
    try:
        expected = _expected_data_dir(shell_bin or resolve_shell(None, app)[0], app)
    except Exception:
        expected = None
    fallback = None
    try:
        for p in sorted(_glob.glob(os.path.join(tempfile.gettempdir(), "qqq-browser-report-*.json"))):
            ep = _read_report_file(p)
            if not ep:
                continue
            ep["reportPath"] = p
            if expected and _same_dir(ep.get("dataDir"), expected):
                return ep
            if fallback is None:
                fallback = ep
    except Exception:
        pass
    return fallback if expected is None else None


# ── 启动 ──

def _spawn_detached(cmd, log_path):
    kwargs = {"cwd": os.path.dirname(cmd[0]) or None, "close_fds": True}
    if IS_WIN:
        kwargs["creationflags"] = _DETACHED
    else:
        kwargs["start_new_session"] = True
    with open(log_path, "ab") as logf:
        return subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, **kwargs)


def _dispatch_navigate(shell_bin, extra, rep, url, hidden=False, wait_sec=8.0):
    """复用路径的 --url：派发一次二次实例导航（fire-and-forget + 轻等待目标页出现）。
    隐藏档实例不会被弹窗（壳层保证）；可见实例会被带到前台。"""
    cmd = [shell_bin] + list(extra) + ["--qqqide-browser", "--qqqide-browser-report=" + rep,
                                       "--qqqide-browser-url=" + url]
    if hidden:
        cmd.append("--qqqide-browser-hidden")
    try:
        _spawn_detached(cmd, rep + ".log")
    except Exception:
        return False
    if not wait_sec:
        return True
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(url).netloc or "").split("@")[-1].split(":")[0]
    except Exception:
        host = ""
    if not host:
        return True
    ep = read_live_endpoint(rep, shell_bin)
    if not ep:
        return True
    end = time.time() + wait_sec
    while time.time() < end:
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % int(ep["cdpPort"]), timeout=2.0) as r:
                tabs = json.loads(r.read().decode("utf-8", "replace"))
            if any(isinstance(t, dict) and host in (t.get("url") or "") for t in tabs):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return True


def ensure_started(hidden=False, url=None, shell=None, app=None, report=None, wait=45.0,
                   exit_with=None, idle_exit=None):
    """确保受控浏览器就绪；返回端点 dict（含 pid/cdpPort）。已在跑 → 复用。
    ★ 复用路径：给了 url 则派发一次导航（隐藏档不弹窗）。
    exit_with / idle_exit 仅在使用新实例时生效（实例级属性）。"""
    shell_bin, extra = resolve_shell(shell, app)
    if not _supports_browser_host(shell_bin, extra):
        raise RuntimeError("这个 qd 版本还不含「受控浏览器」能力（壳层未升级）。\n"
                           "请升级 qd 到最新版；或临时改用外部浏览器: kit/cdp_launch.py")
    rep = report or default_report_path(shell_bin)
    ep = read_live_endpoint(rep, shell_bin, app)
    if ep:
        ep["reused"] = True
        if url and str(url).lower().startswith(("http:", "https:")):
            _dispatch_navigate(shell_bin, extra, rep, url, hidden)
        return ep
    try:
        os.remove(rep)
    except OSError:
        pass
    cmd = [shell_bin] + list(extra) + ["--qqqide-browser", "--qqqide-browser-report=" + rep]
    if hidden:
        cmd.append("--qqqide-browser-hidden")
    if url:
        cmd.append("--qqqide-browser-url=" + url)
    if exit_with:
        cmd.append("--qqqide-browser-exit-with=%d" % int(exit_with))
    if idle_exit is not None:
        cmd.append("--qqqide-browser-idle-exit=%g" % float(idle_exit))
    log_path = rep + ".log"
    _spawn_detached(cmd, log_path)

    end = time.time() + max(5.0, float(wait))
    while time.time() < end:
        time.sleep(0.4)
        try:
            with open(rep, "r", encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            continue
        if isinstance(j, dict) and j.get("ok") is False:
            raise RuntimeError("受控浏览器启动失败: %s（日志: %s）" % (j.get("error"), log_path))
        ep = read_live_endpoint(rep, shell_bin, app)
        if ep:
            # 报告可能是「持锁实例被二次拉起后补写」的（自带 reused:true）——保留其标志
            ep.setdefault("reused", False)
            ep["logFile"] = log_path
            return ep
    raise RuntimeError("等待受控浏览器就绪超时。日志: %s" % log_path)


def stop(report=None, shell=None, app=None):
    """停止受控浏览器（关窗即退出；登录态保留在 profile）。返回是否真的停了。"""
    shell_bin = None
    try:
        shell_bin = resolve_shell(shell, app)[0]
    except Exception:
        shell_bin = None
    rep = report
    if rep is None and shell_bin:
        rep = default_report_path(shell_bin)
    ep = read_live_endpoint(rep, shell_bin, app)
    if not ep:
        return False
    pid = int(ep.get("pid") or 0)
    if pid > 0:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_NO_WINDOW)
        else:
            import signal as _s
            try:
                os.killpg(os.getpgid(pid), _s.SIGTERM)
            except Exception:
                try:
                    os.kill(pid, _s.SIGTERM)
                except Exception:
                    pass
        end = time.time() + 8
        while time.time() < end and _probe(ep.get("cdpPort"), 1.0):
            time.sleep(0.4)
    if rep:
        try:
            os.remove(rep)
        except OSError:
            pass
    return True


# ── CLI ──

def main(argv=None):
    ap = argparse.ArgumentParser(description="qd 受控浏览器：确保/查询/停止")
    sub = ap.add_subparsers(dest="cmd")
    pe = sub.add_parser("ensure", help="确保在跑（就绪即复用）")
    pe.add_argument("--hidden", action="store_true", help="静默档（无可见窗口；默认 30 分钟空闲自退）")
    pe.add_argument("--url", default=None, help="目标网址（新起=直接加载；复用=导航现有实例）")
    pe.add_argument("--exit-with", type=int, default=None, help="跟随监督进程 PID（仅新起时生效）")
    pe.add_argument("--idle-exit", type=float, default=None, help="空闲自退分钟数（0=关；仅新起时生效）")
    pst = sub.add_parser("status", help="打印当前端点（未运行 = 退出码 1）")
    psp = sub.add_parser("stop", help="停止（关闭浏览器）")
    for p in (pe, pst, psp):
        p.add_argument("--shell", default=None, help="内核路径（默认自动从装包推导）")
        p.add_argument("--app", default=None, help="应用目录（开发树用）")
        p.add_argument("--report", default=None, help="报告文件路径（默认按内核定名）")
        p.add_argument("--json", action="store_true", default=None, help="只输出 JSON（位置自由）")
    pe.add_argument("--wait", type=float, default=45.0, help="就绪等待上限（秒）")
    ap.add_argument("--json", action="store_true", default=None, help="只输出 JSON（位置自由）")
    args = ap.parse_args(argv)

    if not args.cmd:
        ap.print_help()
        return 1

    try:
        if args.cmd == "ensure":
            ep = ensure_started(hidden=args.hidden, url=args.url,
                                shell=args.shell, app=args.app, report=args.report, wait=args.wait,
                                exit_with=args.exit_with, idle_exit=args.idle_exit)
            if not args.json:
                print("[ok] 受控浏览器就绪  pid=%s  cdpPort=%s  %s" %
                      (ep.get("pid"), ep.get("cdpPort"), "(复用现有实例)" if ep.get("reused") else ""))
            print(json.dumps(ep, ensure_ascii=False))
            return 0
        if args.cmd == "status":
            sb = None
            try:
                sb = resolve_shell(args.shell, args.app)[0]
            except Exception:
                sb = None
            rep = args.report
            if rep is None and sb:
                rep = default_report_path(sb)
            ep = read_live_endpoint(rep, sb, args.app) or find_any_live_report(sb, args.app)
            if not ep:
                print(json.dumps({"running": False}) if args.json else "[--] 受控浏览器未在运行")
                return 1
            if not args.json:
                print("[ok] 运行中  pid=%s  cdpPort=%s" % (ep.get("pid"), ep.get("cdpPort")))
            print(json.dumps(ep, ensure_ascii=False))
            return 0
        if args.cmd == "stop":
            ok = stop(report=args.report, shell=args.shell, app=args.app)
            print(json.dumps({"stopped": ok}) if args.json else ("[ok] 已停止" if ok else "[--] 本来就没在运行"))
            return 0
    except Exception as e:
        print("[x] " + str(e), file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
