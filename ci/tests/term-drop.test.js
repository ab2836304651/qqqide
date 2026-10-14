// ci/tests/term-drop.test.js — 终端拖入机（core/term-drop.js）纯函数 + 接收机回归守卫。
// term-drop.js 是浏览器 IIFE（挂 window.qqqTermDrop）+ 尾部 module.exports 守卫：
//   Node 直测引用规则（cmd / powershell / posix）与接收机全分支（Files / text / 内部 / 输入控件 / 无路径）。
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('path');

const td = require(path.join(__dirname, '..', '..', 'server-app', 'core', 'term-drop.js'));

// ── 假体：doc / 事件 / dataTransfer ──

function fakeDoc() {
  const handlers = {};
  const doc = {
    handlers: handlers,
    addEventListener: function (t, f) { (handlers[t] = handlers[t] || []).push(f); },
    defaultView: { addEventListener: function () { } },
    createElement: function () { return { style: {}, setAttribute: function () { }, remove: function () { } }; },
    body: { appendChild: function () { } },
  };
  return doc;
}

function fire(doc, type, e) {
  const list = doc.handlers[type] || [];
  for (const f of list) f(e);
}

function ev(dataTransfer, target) {
  return {
    dataTransfer: dataTransfer,
    target: target || { tagName: 'DIV' },
    defaultPrevented: false,
    stopped: false,
    preventDefault: function () { this.defaultPrevented = true; },
    stopPropagation: function () { this.stopped = true; },
  };
}

function filesDT(files) { return { types: ['Files'], files: files, getData: function () { return ''; } }; }

function textDT(text) {
  return {
    types: ['text/plain'],
    files: [],
    getData: function (k) { return k === 'text/plain' ? text : ''; },
  };
}

// ── 引用规则（唯一源）──

test('quotePath: cmd 双引号 / powershell 单引号倍增 / posix 单引号拼接', () => {
  assert.strictEqual(td.quotePath('C:\\a b\\x.png', 'cmd'), '"C:\\a b\\x.png"');
  assert.strictEqual(td.quotePath('C:\\a b\\x.png', 'powershell'), "'C:\\a b\\x.png'");
  assert.strictEqual(td.quotePath('C:\\a b\\x.png', 'gitbash'), "'C:\\a b\\x.png'");
  // 单引号在名内：cmd 双引号天然安全；PS 恒 '' 倍增；posix 恒 '\'' 拼接
  assert.strictEqual(td.quotePath("C:\\it's.png", 'cmd'), "\"C:\\it's.png\"");
  assert.strictEqual(td.quotePath("C:\\it's.png", 'powershell'), "'C:\\it''s.png'");
  assert.strictEqual(td.quotePath("C:\\it's.png", 'gitbash'), "'C:\\it'\\''s.png'");
  // 其余 posix 方言同式
  assert.strictEqual(td.quotePath('/Users/x/a b.png', 'zsh'), "'/Users/x/a b.png'");
  assert.strictEqual(td.quotePath('/home/x/a b.png', 'bash'), "'/home/x/a b.png'");
  // 空值 / null
  assert.strictEqual(td.quotePath('', 'cmd'), '');
  assert.strictEqual(td.quotePath(null, 'cmd'), '');
});

test('quotePaths: 空格分隔多文件；空项剔除', () => {
  assert.strictEqual(
    td.quotePaths(['C:\\a b\\1.png', 'C:\\c\\2.png'], 'cmd'),
    '"C:\\a b\\1.png" "C:\\c\\2.png"');
  assert.strictEqual(td.quotePaths(['a'], 'gitbash'), "'a'");
  assert.strictEqual(td.quotePaths([], 'cmd'), '');
  assert.strictEqual(td.quotePaths(null, 'cmd'), '');
  assert.strictEqual(td.quotePaths(['', 'x'], 'cmd'), '"x"');
});

test('isEditable: INPUT / TEXTAREA / contenteditable 让路，其余接管', () => {
  assert.strictEqual(td.isEditable({ tagName: 'INPUT' }), true);
  assert.strictEqual(td.isEditable({ tagName: 'textarea' }), true);
  assert.strictEqual(td.isEditable({ tagName: 'DIV', isContentEditable: true }), true);
  assert.strictEqual(td.isEditable({ tagName: 'DIV' }), false);
  assert.strictEqual(td.isEditable(null), false);
  assert.strictEqual(td.isEditable({}), false);
});

// ── 接收机全分支 ──

test('install: 文件拖入 → 按当前 shell 引用的路径文本 → 统一插入通道（不回车）', () => {
  const doc = fakeDoc();
  const got = [];
  let shell = 'cmd';
  td.install(doc, { shell: function () { return shell; }, insert: function (t) { got.push(t); } });

  const e1 = ev(filesDT([{ path: 'C:\\a b\\1.png' }, { path: 'C:\\c\\2.png' }]));
  fire(doc, 'dragenter', e1);
  assert.strictEqual(e1.defaultPrevented, true);          // 外部拖拽一律 preventDefault
  fire(doc, 'dragover', ev(filesDT([])));
  fire(doc, 'drop', e1);
  assert.deepStrictEqual(got, ['"C:\\a b\\1.png" "C:\\c\\2.png"']);
  assert.strictEqual(e1.stopped, true);

  shell = 'powershell';                                    // shell 方言每次 drop 现读
  fire(doc, 'drop', ev(filesDT([{ path: "C:\\it's.png" }])));
  assert.strictEqual(got[1], "'C:\\it''s.png'");

  shell = 'gitbash';
  fire(doc, 'drop', ev(filesDT([{ path: "C:\\it's.png" }])));
  assert.strictEqual(got[2], "'C:\\it'\\''s.png'");
});

test('install: 无本地路径的拖入项 → 只上报不计入插入；文本拖入 → 原样插入（= Ctrl+V 同源）', () => {
  const doc = fakeDoc();
  const got = [];
  const noPath = [];
  td.install(doc, {
    shell: function () { return 'cmd'; },
    insert: function (t) { got.push(t); },
    onNoPath: function (n) { noPath.push(n); },
  });

  fire(doc, 'drop', ev(filesDT([{ name: 'web.png' }])));
  assert.deepStrictEqual(got, []);
  assert.deepStrictEqual(noPath, [1]);

  fire(doc, 'drop', ev(textDT('hello world')));
  assert.deepStrictEqual(got, ['hello world']);

  fire(doc, 'drop', ev(textDT('')));                      // 空文本载荷 = no-op
  assert.deepStrictEqual(got, ['hello world']);
});

test('install: 内部拖拽让路原生（零接管）；输入控件上的文本拖入让路原生', () => {
  const doc = fakeDoc();
  const got = [];
  td.install(doc, { shell: function () { return 'cmd'; }, insert: function (t) { got.push(t); } });

  // 本 doc dragstart 置位 → 内部拖拽：不 preventDefault、不插入
  fire(doc, 'dragstart', {});
  const eInt = ev(textDT('selected text'));
  fire(doc, 'dragenter', eInt);
  fire(doc, 'dragleave', {});
  fire(doc, 'drop', eInt);
  assert.strictEqual(eInt.defaultPrevented, false);
  assert.deepStrictEqual(got, []);

  fire(doc, 'dragend', {});                                // 清内部标记 → 回到外部语义

  // 文本落点 = 输入控件（INPUT/TEXTAREA）→ 原生全权
  const eInp = ev(textDT('x'), { tagName: 'INPUT' });
  fire(doc, 'dragenter', eInp);
  assert.strictEqual(eInp.defaultPrevented, false);
  const eInp2 = ev(textDT('x'), { tagName: 'TEXTAREA' });
  fire(doc, 'drop', eInp2);
  assert.strictEqual(eInp2.defaultPrevented, false);
  assert.deepStrictEqual(got, []);

  // 同一时刻文件拖入输入控件仍接管（文件恒优先）
  const eFile = ev(filesDT([{ path: 'C:\\f.png' }]), { tagName: 'INPUT' });
  fire(doc, 'drop', eFile);
  assert.strictEqual(eFile.defaultPrevented, true);
  assert.deepStrictEqual(got, ['"C:\\f.png"']);
});

test('install: 未知载荷零动作；失焦兜底归零后仍可正常接收', () => {
  const doc = fakeDoc();
  const got = [];
  const winHandlers = {};
  doc.defaultView.addEventListener = function (t, f) { (winHandlers[t] = winHandlers[t] || []).push(f); };
  td.install(doc, { shell: function () { return 'cmd'; }, insert: function (t) { got.push(t); } });

  const eUnknown = ev({ types: ['application/x-custom'], files: [], getData: function () { return ''; } });
  fire(doc, 'dragenter', eUnknown);
  assert.strictEqual(eUnknown.defaultPrevented, false);
  fire(doc, 'drop', eUnknown);
  assert.deepStrictEqual(got, []);

  // 进入会话后失焦（ALT+TAB 取消拖拽无 dragleave）→ 归零；再拖入照常
  fire(doc, 'dragenter', ev(filesDT([])));
  (winHandlers['blur'] || []).forEach(function (f) { f({}); });
  fire(doc, 'drop', ev(filesDT([{ path: 'C:\\z.png' }])));
  assert.deepStrictEqual(got, ['"C:\\z.png"']);
});

test('install: 缺 drag-text 依赖（dtm 不可得）→ 明确拒绝而非半残', () => {
  // Node 下 require('./drag-text.js') 恒可得 → 此分支只能验证「无 doc/无 insert 时安全返回 null」
  assert.strictEqual(td.install(null, { insert: function () { } }), null);
  assert.strictEqual(td.install(fakeDoc(), {}), null);
  assert.strictEqual(td.install(fakeDoc(), null), null);
});
