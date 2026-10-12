// Copyright (C) 2025-2026 Sichuan Dream Technology Co., Ltd. All Rights Reserved.

// ============================================================================
// qqq-reddirs.js — 恒红目录唯一判定（Roam 文件列表 + AI 视口目录树 两处共用）
//
// 红色 = 「IDE 数据重地」视觉锚点。清单（增删由用户定案，禁擅自扩红）：
//   ① _qqq / _qqqvault  —— 家目录入口（按目录名，任意层级）
//   ② _qqq/quests       —— 对话存档（按路径精确匹配：项目里恰好叫 quests 的
//                          普通目录绝不误标）
// 保持普通色的 _qqq 子目录：alphal / timeline / tmp 等机器区（基本无人浏览，
// 全染红 = 红色失去分辨力）。
//
// 用法：window.qqqRedDir(name, fullPath) → true 时由调用方自行上色/加类。
// 消费方（禁各写一份条件）：core/ai-viewport.js（.aiv-dd-home）、
//                          goods/file-explorer/q2-roam.js（.roam-home-dir）
// ============================================================================
window.qqqRedDir = function (name, fullPath) {
	var n = String(name || '');
	if (n === '_qqq' || n === '_qqqvault') return true;
	if (n !== 'quests') return false;
	var p = String(fullPath || '').replace(/\\/g, '/').replace(/\/+$/, '');
	return /\/_qqq\/quests$/i.test(p);
};
