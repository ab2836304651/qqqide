// ci/tests/byok-max-tokens.test.js — BYOK 输出上限策略回归守卫（2026-10-12 q433）。
// ① 请求默认【不发送】max_tokens（仅用户显式配置才发）——防「继承平台量级默认值」回潮
//    （旧行为：上限更小的服务商每次对话必 400「Range of max_tokens should be [1, 131072]」）。
// ② 400 范围自愈：报文含 [min,max] → 钳到上限原样重发一次（直连/平台代理双通道接入）。
// ③ 0-house 耗尽提示优先拼真实错误末条（禁通用归因「计费/配额或服务器故障」掩盖真因）。
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const R = path.join(__dirname, '..', '..');
const BYOK = fs.readFileSync(path.join(R, 'server-app', 'ai-panel', 'byok.js'), 'utf8');
const PANEL_SEND = fs.readFileSync(path.join(R, 'server-app', 'ai-panel', 'panel-send.js'), 'utf8');
const ZH = JSON.parse(fs.readFileSync(path.join(R, 'server-app', 'locales', 'zh.json'), 'utf8'));

test('byok: 输出上限默认不发送（仅显式配置才发）+ 旧继承路径已清', () => {
  assert.match(BYOK, /var _mt = parseInt\(cfg && cfg\.maxTokens, 10\) \|\| 0;/, '缺少 cfg.maxTokens 读取');
  assert.match(BYOK, /if \(_mt > 0\) out\.max_tokens = _mt;/, '仅在用户显式配置时才发送');
  assert.ok(!/max_tokens: \(body && body\.max_tokens\)/.test(BYOK),
    '禁继承平台 body 的 max_tokens（旧行为回潮）');
});

test('byok: 400 范围自愈正则与双通道接入', () => {
  const m = BYOK.match(/var _MT_RANGE_RE = (\/[^\n]+?\/i);/);
  assert.ok(m, '未找到 _MT_RANGE_RE 正则字面量');
  const re = eval(m[1]); // eslint-disable-line no-eval
  const hit = re.exec('InternalError.Algo.InvalidParameter: Range of max_tokens should be [1, 131072]');
  assert.ok(hit, '典型 400 报文必须命中');
  assert.deepStrictEqual([hit[1], hit[2]], ['1', '131072']);
  assert.ok(re.test('error: max_tokens must be within [1, 131072]'), '变体措辞需命中');
  assert.ok(!re.test('some unrelated 400 without the token name'), '无关报文不得误命中');
  const calls = BYOK.match(/_sniffMaxTokensRange\(await _readBodyText\(resp\)\)/g) || [];
  assert.ok(calls.length >= 2, '直连/平台代理两条通道都必须接入自愈');
});

test('byok: Z 弹窗最大输出 tokens 字段（标签/占位/读取/回填全链）', () => {
  assert.match(BYOK, /id="byok-maxtokens"/, '弹窗缺少输入框');
  assert.match(BYOK, /'byok-baseurl', 'byok-key', 'byok-model', 'byok-maxtokens'/, 'change 监听未挂');
  assert.match(BYOK, /function _readMaxTokensField\(/, '缺少读取助手');
  assert.match(BYOK, /\$\('byok-maxtokens'\)\.value = c\.maxTokens > 0 \? String\(c\.maxTokens\) : '';/, '打开弹窗未回填');
});

test('panel-send: 耗尽提示优先拼楼层真实错误末条', () => {
  assert.match(PANEL_SEND, /ai\.retryExhaustedDetail/, '缺少带真实的错误详情句');
  assert.match(PANEL_SEND, /_rxSt\.log\[_rxSt\.log\.length - 1\]/, '未取错误日志末条');
});

test('zh 源: 耗尽文案去通用归因 + 新键在位', () => {
  assert.ok(ZH.ai && ZH.ai.retryExhausted, '缺少 ai.retryExhausted');
  assert.ok(!/可能是计费\/配额耗尽或服务器故障/.test(ZH.ai.retryExhausted), '旧误导句回潮');
  assert.ok(String(ZH.ai.retryExhaustedDetail || '').indexOf('{msg}') >= 0, 'detail 键需带 {msg} 插值位');
  assert.ok(ZH.ai.byok && ZH.ai.byok.maxTokens && ZH.ai.byok.maxTokensPh, '缺 byok 新键');
});
