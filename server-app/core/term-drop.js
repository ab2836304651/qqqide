// Copyright (C) 2025-2026 Sichuan Dream Technology Co., Ltd. All Rights Reserved.

// ============================================================================
// term-drop.js — 终端拖入机（kmd / qmd 共用唯一真理源，2026-10-12）
//
// 定位: kmd（行模式）/ qmd（ConPTY 真终端）两个 iframe 的拖入接收共用机——
//   「拖入 = 粘贴」（与真终端同语义）：系统文件/图片/文件夹 → 按当前 shell 方言引用成
//   路径文本 → 走各自现成粘贴通道插入（kmd = 键入行 insertToInput；qmd = PTY
//   _sendPastedText），绝不自动回车；外拖文本 → 原样插入（提取机 drag-text.js 三级兜底）。
//   终端消费不了像素：图片/文件在终端眼里 = 一个路径字符串（cmd / PowerShell / Git Bash /
//   Windows Terminal 同口径，拖入只翻译成文本，不预览不执行）。
//
// 引用规则（唯一源，防第二套拼装）:
//   cmd          → "路径"                （Windows 文件名恒不含 "，无需转义）
//   powershell   → '路径'                （内部 ' → '' 倍增）
//   gitbash/zsh/bash（posix 系）→ '路径' （内部 ' → '\'' 拼接）
//   多文件 = 空格分隔（Windows Terminal 同款口径）
//
// 契约:
//   · 内部拖拽（本 doc 发起的 dragstart）→ 零接管：让路原生（键入行原生落点插入等）
//   · Files 恒优先于文本（classify 同 drag-text.js）；无本地路径的拖入项（浏览器虚拟文件）如实上报
//   · 文本拖入落点是他方输入控件（INPUT/TEXTAREA/contenteditable）→ 让路原生（拖到哪插哪）
//   · 对外部拖拽一律 preventDefault（防链接/文件拖入 iframe 默认导航）
//   · 拖拽悬停 → 橙色虚线接收框（覆盖 iframe 视口 = 接收范围；与 AI 三面板/roam/inbox 同款协议）
//   · 拖拽深度的 enter/leave 计数防闪烁；失焦归零（ALT+TAB 取消拖拽可能无 dragleave）
//   · 光标纪律：全程不写 cursor、不写 dataTransfer.dropEffect
//
// 依赖: core/drag-text.js（classify / extractText / installInternalGuard）—— 加载序先于本件
// 加载点: goods/kmd/kmd-ui.html + goods/qmd/qmd-ui.html
// ============================================================================

(function () {
  'use strict';

  // 文本机解析：浏览器恒取 window.qqqDragText；Node 单测直测机器时 require 兜底解同目录 drag-text
  function _dt() {
    if (typeof window !== 'undefined' && window.qqqDragText) return window.qqqDragText;
    if (typeof module !== 'undefined' && typeof module.exports === 'object') {
      try { return require('./drag-text.js'); } catch (_) { return null; }
    }
    return null;
  }

  // ── 路径引用（shell 方言 → 引用文本）──
  function quotePath(path, shellType) {
    var p = (path == null) ? '' : String(path);
    if (!p) return '';
    var t = (shellType == null) ? '' : String(shellType);
    if (t === 'cmd') return '"' + p + '"';
    if (t === 'powershell') return "'" + p.replace(/'/g, "''") + "'";
    return "'" + p.replace(/'/g, "'\\''") + "'";   // posix 系（gitbash / zsh / bash）
  }

  function quotePaths(paths, shellType) {
    var out = [];
    if (paths && paths.length) {
      for (var i = 0; i < paths.length; i++) {
        var q = quotePath(paths[i], shellType);
        if (q) out.push(q);
      }
    }
    return out.join(' ');
  }

  // 可编辑元素判定（文本拖入让路原生：改名框/查找框等输入控件保留浏览器默认「拖到哪插哪」）
  function isEditable(t) {
    if (!t || !t.tagName) return false;
    var tag = String(t.tagName).toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || t.isContentEditable === true;
  }

  // ── 接收机安装 ──
  // opts: { shell(): 当前 shell 方言, insert(text): 统一插入通道（= 各终端粘贴同源）,
  //         onNoPath?(n): 无本地路径项如实上报, onError?(err) }
  function install(doc, opts) {
    if (!doc || !opts || typeof opts.insert !== 'function') return null;
    var dtm = _dt();
    if (!dtm) {
      try { console.warn('[term-drop] core/drag-text.js 未加载 — 终端拖入未启用'); } catch (_) { }
      return null;
    }
    var win = null;
    try { win = doc.defaultView || null; } catch (_) { }

    var isInternal = dtm.installInternalGuard(doc);
    var depth = 0;
    var kind = null;

    // 橙色接收框（fixed 覆盖 iframe 视口；pointer-events:none 零交互）
    var ov = null;
    try {
      ov = doc.createElement('div');
      ov.setAttribute('data-qqq-term-drop', '');
      ov.style.cssText =
        'position:fixed;left:0;top:0;right:0;bottom:0;display:none;pointer-events:none;' +
        'z-index:999999;border:3px dashed #e07020;border-radius:4px;' +
        'box-shadow:inset 0 0 0 2px rgba(224,112,32,0.12),0 0 0 2px rgba(224,112,32,0.18);';
      doc.body.appendChild(ov);
    } catch (_) { ov = null; }

    function show() { if (ov) ov.style.display = 'block'; }
    function hide() { if (ov) ov.style.display = 'none'; }
    function classify(e) {
      try { return dtm.classify(e && e.dataTransfer, isInternal()); } catch (_) { return null; }
    }

    doc.addEventListener('dragenter', function (e) {
      var k = classify(e);
      if (!k) return;
      if (k === 'text' && isEditable(e.target)) return;   // 输入控件：原生全权
      e.preventDefault();
      depth++;
      kind = k;
      show();
    }, true);

    doc.addEventListener('dragover', function (e) {
      var k = classify(e) || kind;
      if (!k) return;
      if (k === 'text' && isEditable(e.target)) { hide(); return; }
      e.preventDefault();      // 允许 drop + 防默认导航（链接/文件拖入不进导航）
      show();
    }, true);

    doc.addEventListener('dragleave', function () {
      if (!kind) return;
      depth--;
      if (depth <= 0) { depth = 0; kind = null; hide(); }
    }, true);

    if (win) win.addEventListener('blur', function () { depth = 0; kind = null; hide(); });

    doc.addEventListener('drop', function (e) {
      var k = kind || classify(e);   // 极少数无 dragenter 的直达 drop 兜底
      depth = 0;
      kind = null;
      hide();
      if (!k) return;                              // 内部拖拽 → 原生语义
      if (k === 'text' && isEditable(e.target)) return;   // 输入控件 → 原生 drop
      e.preventDefault();
      e.stopPropagation();

      var shell = (typeof opts.shell === 'function') ? opts.shell() : '';
      var dt = e.dataTransfer;

      // 文件分支：完整路径 → 按 shell 引用 → 统一插入通道（无本地路径项计入上报）
      if (k === 'files') {
        var paths = [];
        var noPath = 0;
        try {
          var fl = (dt && dt.files) ? dt.files : [];
          for (var i = 0; i < fl.length; i++) {
            var f = fl[i];
            if (f && f.path) paths.push(String(f.path));
            else noPath++;
          }
        } catch (_) { }
        if (paths.length) {
          try { opts.insert(quotePaths(paths, shell)); }
          catch (err) { if (typeof opts.onError === 'function') opts.onError(err); }
        }
        if (noPath > 0 && typeof opts.onNoPath === 'function') opts.onNoPath(noPath);
        return;
      }

      // 文本分支：等同各终端 Ctrl+V（空载荷 = no-op；默认导航已由 preventDefault 封死）
      var txt = '';
      try { txt = dtm.extractText(dt) || ''; } catch (_) { txt = ''; }
      if (txt) {
        try { opts.insert(txt); }
        catch (err2) { if (typeof opts.onError === 'function') opts.onError(err2); }
      }
    }, true);

    return { destroy: function () { try { if (ov) ov.remove(); } catch (_) { } } };
  }

  var API = { quotePath: quotePath, quotePaths: quotePaths, isEditable: isEditable, install: install };

  if (typeof window !== 'undefined') window.qqqTermDrop = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})();
