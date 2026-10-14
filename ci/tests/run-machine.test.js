// ci/tests/run-machine.test.js — 运行机器（core/run-machine.js）分派 + 命令构造 + run() 链路守卫。
// run-machine.js = 浏览器 IIFE（挂 window.qqqRunMachine）+ 尾部 module.exports 守卫：
//   · 纯函数直测：runnerFor / buildCommand（引用机 = term-drop 唯一源，require 兜底）/ pickShellType / dirnameOf
//   · run() 链路：window 假体注入（bridge/qoast/qqqEditor/__qqqKmdRun）逐分支断言（组件缺失 / 保存被拒 / 成功 / 终端缺失）
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const path = require('path');

const rm = require(path.join(__dirname, '..', '..', 'server-app', 'core', 'run-machine.js'));
const td = require(path.join(__dirname, '..', '..', 'server-app', 'core', 'term-drop.js'));

test('runnerFor: .py/.pyw → python；.js/.mjs/.cjs → node；其余 null（大小写不敏感）', () => {
  assert.strictEqual(rm.runnerFor('E:/a/tool.py'), 'python');
  assert.strictEqual(rm.runnerFor('E:\\a\\tool.PYW'), 'python');
  assert.strictEqual(rm.runnerFor('/x/app.js'), 'node');
  assert.strictEqual(rm.runnerFor('/x/app.MJS'), 'node');
  assert.strictEqual(rm.runnerFor('a.cjs'), 'node');
  assert.strictEqual(rm.runnerFor('a.ts'), null);
  assert.strictEqual(rm.runnerFor('a.pyx'), null);
  assert.strictEqual(rm.runnerFor('noext'), null);
  assert.strictEqual(rm.runnerFor(''), null);
  assert.strictEqual(rm.runnerFor(null), null);
});

test('buildCommand: 引用规则 = term-drop 唯一源（cmd 双引号 / zsh 单引号转义）', () => {
  assert.strictEqual(rm.buildCommand('C:\\py\\python.exe', 'C:\\a b\\x.py', 'cmd'),
    '"C:\\py\\python.exe" "C:\\a b\\x.py"');
  assert.strictEqual(rm.buildCommand('/opt/py/python3', "/Users/a/it's/x.py", 'zsh'),
    "'/opt/py/python3' '/Users/a/it'\\''s/x.py'");
  assert.strictEqual(rm.buildCommand('C:\\py\\p.exe', "C:\\it's\\y.py", 'cmd'),
    td.quotePath('C:\\py\\p.exe', 'cmd') + ' ' + td.quotePath("C:\\it's\\y.py", 'cmd'));
  assert.strictEqual(rm.buildCommand('', 'x.py', 'cmd'), '');
  assert.strictEqual(rm.buildCommand('py', '', 'cmd'), '');
});

test('pickShellType: 平台 → kmd 默认 shell（win=cmd / mac=zsh / 其余=bash）', () => {
  assert.strictEqual(rm.pickShellType('Win32'), 'cmd');
  assert.strictEqual(rm.pickShellType('MacIntel'), 'zsh');
  assert.strictEqual(rm.pickShellType('Linux x86_64'), 'bash');
});

test('dirnameOf: 反斜杠/正斜杠双式；无目录段 → 空串', () => {
  assert.strictEqual(rm.dirnameOf('E:\\a\\b\\x.py'), 'E:\\a\\b');
  assert.strictEqual(rm.dirnameOf('/a/b/x.py'), '/a/b');
  assert.strictEqual(rm.dirnameOf('x.py'), '');
  assert.strictEqual(rm.dirnameOf(null), '');
});

function withWindow(stub, fn) {
  global.window = stub;
  return Promise.resolve()
    .then(fn)
    .finally(() => { delete global.window; });
}

test('run(): 组件缺失 → 如实拒绝（qoast）且不开终端', async () => {
  const toasts = [];
  let kmdCalls = 0;
  await withWindow({
    qqqideBridge: { components: { getBin: async () => null } },
    qqqideQoast: { show: (t) => toasts.push(t) },
    __qqqKmdRun: () => { kmdCalls++; return true; },
  }, async () => {
    assert.strictEqual(await rm.run({ filePath: 'E:/a/x.py' }), false);
  });
  assert.strictEqual(kmdCalls, 0);
  assert.strictEqual(toasts.length, 1);
});

test('run(): 脏缓冲保存被拒（冲突/失败）→ 中止（不开终端、不弹二次窗）', async () => {
  let kmdCalls = 0;
  let saved = 0;
  const toasts = [];
  await withWindow({
    qqqideBridge: { components: { getBin: async () => 'C:\\py\\python.exe' } },
    qqqideQoast: { show: (t) => toasts.push(t) },
    qqqEditor: { saveIfDirty: async () => { saved++; return false; } },
    __qqqKmdRun: () => { kmdCalls++; return true; },
  }, async () => {
    assert.strictEqual(await rm.run({ filePath: 'E:/a/x.py' }), false);
  });
  assert.strictEqual(saved, 1);
  assert.strictEqual(kmdCalls, 0);
  assert.deepStrictEqual(toasts, []);   // 闸门自报，本机不重复弹窗
});

test('run(): 成功链路 → getBin → 保存 → kmd（cwd=文件目录，命令已引用）', async () => {
  let captured = null;
  const gets = [];
  await withWindow({
    qqqideBridge: { components: { getBin: async (kind) => { gets.push(kind); return 'C:\\py\\python.exe'; } } },
    qqqideQoast: { show: () => { } },
    qqqEditor: { saveIfDirty: async () => true },
    __qqqKmdRun: (cwd, cmd) => { captured = { cwd: cwd, cmd: cmd }; return true; },
  }, async () => {
    assert.strictEqual(await rm.run({ filePath: 'E:/a/x.py' }), true);
  });
  assert.deepStrictEqual(gets, ['python']);
  assert.strictEqual(captured.cwd, 'E:/a');
  assert.ok(captured.cmd.indexOf('x.py') !== -1);
  assert.ok(captured.cmd.indexOf('python.exe') !== -1);
});

test('run(): kmd 入口缺失 → 如实拒绝（qoast，不静默）', async () => {
  const toasts = [];
  await withWindow({
    qqqideBridge: { components: { getBin: async () => 'C:\\py\\python.exe' } },
    qqqideQoast: { show: (t) => toasts.push(t) },
    qqqEditor: { saveIfDirty: async () => true },
  }, async () => {
    assert.strictEqual(await rm.run({ filePath: 'E:/a/x.py' }), false);
  });
  assert.strictEqual(toasts.length, 1);
});
