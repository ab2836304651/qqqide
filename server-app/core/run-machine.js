// Copyright (C) 2025-2026 Sichuan Dream Technology Co., Ltd. All Rights Reserved.

// ============================================================================
// run-machine.js — 运行机器（编辑器右键「运行」唯一机，2026-10-13）
//
// 定位：把「当前文件用内置解释器跑起来」收敛为唯一实现 —— 编辑器右键「运行」消费方。
//   · 分派：.py/.pyw → 内置 Python；.js/.mjs/.cjs → 内置 Node。
//     解释器解析走 bridge.components.getBin（壳层唯一机器；node = engines/node 门面，
//     非 manifest 组件，由壳层 getBin 同源解析）——禁渲染层自拼路径。
//   · 前置：脏缓冲先过编辑器唯一保存闸门（window.qqqEditor.saveIfDirty）——失败/冲突中止
//     （闸门自报原因，本机零二次弹窗）；运行磁盘旧版 = 用户看不到自己刚改的代码，禁。
//   · 命令构造：按新 kmd tab 的默认 shell 方言引用（win=cmd / mac=zsh / linux=bash）——
//     引用规则复用 term-drop 唯一源（window.qqqTermDrop.quotePath），禁第二套拼装。
//   · 执行：window.__qqqKmdRun(cwd, cmd)（goods/kmd/kmd.js）→ 开新 kmd tab，
//     kmd:init 带 runCmd → 会话就绪即执行（cwd = 文件所在目录）。
//   · 失败一律如实（组件缺失/终端打不开 → qoast），禁静默。
//
// 加载点：server-app/index.html（core/editor.js 之后；core/term-drop.js 同批加载）
// 测试：ci/tests/run-machine.test.js（纯函数 + 分派链路）
// ============================================================================

(function () {
  'use strict';

  // ── 分派表（唯一；大小写不敏感）──
  var RUNNERS = { py: 'python', pyw: 'python', js: 'node', mjs: 'node', cjs: 'node' };

  function runnerFor(filePath) {
    var p = (filePath == null) ? '' : String(filePath);
    var m = /\.([A-Za-z0-9]+)$/.exec(p);
    if (!m) return null;
    return RUNNERS[m[1].toLowerCase()] || null;
  }

  // ── 引用机（唯一源 = term-drop.js；Node 单测直测时 require 兜底）──
  function _quoter() {
    if (typeof window !== 'undefined' && window.qqqTermDrop) return window.qqqTermDrop;
    if (typeof module !== 'undefined' && typeof module.exports === 'object') {
      try { return require('./term-drop.js'); } catch (_) { return null; }
    }
    return null;
  }

  // 平台 → 新 kmd tab 默认 shell（与 goods/kmd/kmd.js _kmdDefShell 同口径）；plat 缺省 = navigator.platform
  function pickShellType(plat) {
    var p = (plat != null) ? String(plat)
      : ((typeof navigator !== 'undefined' && navigator.platform) ? String(navigator.platform) : '');
    if (/Mac/i.test(p)) return 'zsh';
    if (/Win/i.test(p)) return 'cmd';
    return 'bash';
  }

  // 命令 = 引用后的 exe + 空格 + 引用后的文件；引用机缺失 → ''（调用方如实拒绝，禁裸拼）
  function buildCommand(exePath, filePath, shellType) {
    var q = _quoter();
    if (!q || typeof q.quotePath !== 'function') return '';
    var e = q.quotePath(exePath, shellType);
    var f = q.quotePath(filePath, shellType);
    if (!e || !f) return '';
    return e + ' ' + f;
  }

  function dirnameOf(filePath) {
    var p = (filePath == null) ? '' : String(filePath);
    var m = /^([\s\S]*)[\\/][^\\/]*$/.exec(p);
    return m ? m[1] : '';   // 无目录段 → 空串（kmd 端回退工作空间根）
  }

  function _toast(key, fallback) {
    try {
      if (typeof window !== 'undefined' && window.qqqideQoast) {
        var t = (typeof window._i === 'function') ? window._i(key, fallback) : fallback;
        window.qqqideQoast.show(t, { duration: 6000, type: 'warn' });
      }
    } catch (_) { }
  }

  // run({filePath, editor?}) → Promise<boolean>（true = 已发起运行）
  async function run(opts) {
    var fp = opts && opts.filePath;
    var kind = runnerFor(fp);
    if (!kind) return false;                                  // 不可运行类型（菜单项本就不该出现）
    var bridge = (typeof window !== 'undefined' && window.qqqideBridge) || null;
    var exe = null;
    try {
      if (bridge && bridge.components && bridge.components.getBin) exe = await bridge.components.getBin(kind);
    } catch (_) { exe = null; }
    if (!exe) { _toast('editor.runNoInterp', '内置解释器未就绪（组件缺失）'); return false; }
    // 前置：脏缓冲先过唯一保存闸门（失败/冲突 → 中止；闸门已自报，不重复弹窗）
    try {
      if (typeof window !== 'undefined' && window.qqqEditor && typeof window.qqqEditor.saveIfDirty === 'function') {
        var ok = await window.qqqEditor.saveIfDirty(fp);
        if (!ok) return false;
      }
    } catch (_) { return false; }
    var cmd = buildCommand(exe, fp, pickShellType());
    if (!cmd) { _toast('editor.runFail', '运行失败'); return false; }
    if (typeof window !== 'undefined' && typeof window.__qqqKmdRun === 'function') {
      var opened = false;
      try { opened = !!window.__qqqKmdRun(dirnameOf(fp), cmd); } catch (_) { opened = false; }
      if (opened) return true;
    }
    _toast('editor.runNoTerm', '无法打开终端');
    return false;
  }

  var API = { runnerFor: runnerFor, buildCommand: buildCommand, pickShellType: pickShellType, dirnameOf: dirnameOf, run: run };

  if (typeof window !== 'undefined') window.qqqRunMachine = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})();
