// ci/tests/floor-clock-multi.test.js — 楼层时钟多目标集 + 收官重放巡检 回归守卫（2026-10-12 q48 f2 客户实锤）。
// 事故机制：建楼中途「活动指针」_activeAiDiv 被切 quest / 跨面板重建卡片等事件夺走（或置空）——
//   屏上正显示的钟表从此无人续画（秒针冻结在绿色相位），封顶的「变黑定格」也打到了被夺走的指针上
//   → 楼已百分百建完，钟永远停在绿色建楼态（截图实锤：钟值卡在建楼第 11 分钟某一秒、费用卡同刻，
//   而 House/Room/FILE 早已是终值——因为那些走的是另一条引用链）。
// 守卫：① 时钟/费用一切书写恒遍历「多目标集」（panel-clock / agent-loop）
//   ② 收官元素打钉（迟到心跳/幽灵钟永不再染回建楼色）
//   ③ 收官重放巡检存在（已完结楼层残留建楼态 → 自动重放黑钟 + 定格）
//   ④ 版本推进（旧缓存会吞掉修复）。
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const R = path.join(__dirname, '..', '..');
const CLOCK = fs.readFileSync(path.join(R, 'server-app', 'ai-panel', 'panel-clock.js'), 'utf8');
const LOOP = fs.readFileSync(path.join(R, 'server-app', 'ai-panel', 'agent-loop.js'), 'utf8');
const PIPE = fs.readFileSync(path.join(R, 'server-app', 'ai-panel', 'panel-pipeline.js'), 'utf8');
const SW = fs.readFileSync(path.join(R, 'server-app', 'service-worker.js'), 'utf8');

test('panel-clock: 多目标集注册（新纪元重置 / 续建追加 / 兜底回退）', () => {
  assert.match(CLOCK, /function _floorClockElsOf\(ag\)/, '缺少多目标解析助手');
  assert.match(CLOCK, /if \(_freshBase \|\| !ag\._floorClockEls\) ag\._floorClockEls = \[\];/, '新纪元未重置全集');
  assert.match(CLOCK, /ag\._floorClockEls\.indexOf\(aiDiv\) < 0\) ag\._floorClockEls\.push\(aiDiv\);/, '入列追加缺失/去重缺失');
  assert.match(CLOCK, /return ag\._activeAiDiv \? \[ag\._activeAiDiv\] : \[\];/, '无集时未回退单指针（旧数据兼容）');
});

test('panel-clock: 秒针/跨面板心跳/收官变黑 三方书写全部遍历全集', () => {
  assert.match(CLOCK, /var _els = _floorClockElsOf\(_ag\);/, '秒针未走全集');
  assert.match(CLOCK, /var _aels = _floorClockElsOf\(aj\);/, '跨面板心跳未走全集（指针被夺后屏上钟表将无人续画）');
  assert.match(CLOCK, /var _elsDone = _floorClockElsOf\(ag\);/, '收官变黑未走全集');
  assert.match(CLOCK, /_floorClockElsOf\(aiDiv\)|_floorClockEls\.push\(aiDiv\)/, '起楼未登记元素（秒针与手续费名无源）');
});

test('panel-clock: 收官钉（迟到者永不染回建楼色）', () => {
  const pins = CLOCK.match(/\._floorDoneTs\) continue;/g) || [];
  assert.ok(pins.length >= 2, '收官钉未挂到秒针/心跳（发现 ' + pins.length + ' 处，需 ≥2）');
  assert.match(CLOCK, /_elD\._floorDoneTs = _doneMs;/, '收官未打钉');
});

test('panel-clock: 收官重放巡检（已完结才重放；未完结绝不触碰）', () => {
  assert.match(CLOCK, /function _healFinishedFloorClocks\(\)/, '缺少收官重放巡检');
  assert.match(CLOCK, /timings\[ti\]\.floorIndex === Number\(fKey\) && timings\[ti\]\.finishedAt/, '巡检收据≠完结记录（finishedAt）');
  assert.match(CLOCK, /if \(!rec\) continue;   \/\/ 未完结 → 不碰/, '未完结楼层保护缺失');
  assert.match(CLOCK, /setInterval\(_healFinishedFloorClocks, 3000\);/, '巡检未挂节拍');
});

test('agent-loop: 三处费用书写（每房 / 最终回复 / 强制收尾）全部遍历全集', () => {
  const uses = LOOP.match(/_floorClockElsOf\(self\)/g) || [];
  assert.ok(uses.length >= 3, '费用书写仍有入口未走全集（发现 ' + uses.length + ' 处，需 ≥3）');
  assert.ok(!/var _aiDivF = self\._activeAiDiv;/.test(LOOP), '旧单指针费用写法回潮（_aiDivF）');
  assert.ok(!/var _aiDiv5 = self\._activeAiDiv;/.test(LOOP), '旧单指针费用写法回潮（_aiDiv5）');
  assert.ok(!/var _aiDivF2 = self\._activeAiDiv;/.test(LOOP), '旧单指针费用写法回潮（_aiDivF2）');
});

test('panel-pipeline: 两处收尾兜底黑钟走多目标助手', () => {
  const calls = PIPE.match(/_blackenFloorClockEls\(agent\)/g) || [];
  assert.ok(calls.length >= 2, '收尾兜底黑钟未接入多目标助手（发现 ' + calls.length + ' 处，需 ≥2）');
  assert.ok(!/_bgAiDiv2\._clockBlock\.className/.test(PIPE), '后台失败旧单指针黑钟回潮');
});

test('service-worker: 版本推进到 v1216（阈值式——后续版本继续推进不再误报）', () => {
  const m = SW.match(/const CACHE_NAME = 'qqq-shell-v(\d+)';/);
  assert.ok(m, 'SW 版本号缺失/形态变更');
  assert.ok(Number(m[1]) >= 1216, 'SW 未推进（旧缓存将吞掉修复）：当前 v' + m[1]);
});
