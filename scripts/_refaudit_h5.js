#!/usr/bin/env node
/**
 * H5 内联事件处理器「悬空函数引用」检查（静默缺陷哨兵）。
 *
 * 背景：user-client/index.html 用 onclick="fn(...)" 这类内联处理器绑定行为。
 * 一旦被调用的函数没定义（改名、漏定义、复制粘贴残留），**页面不会在加载期报错** ——
 * 只在用户点到那个按钮时才抛 ReferenceError。而 pageerror 常常没被盯着看，
 * 于是「按钮点了没反应 / 点了没高亮」这类问题会存活很久
 * （历史实例：activateTodoTab 从未定义，导致「返回待办」必抛错）。
 *
 * 用法：node scripts/_refaudit_h5.js [path]      # 默认 user-client/index.html
 * 退出码：0 = 无悬空引用；1 = 存在悬空引用（会把名字打出来）
 */
const fs = require('fs');
const path = process.argv[2] || 'user-client/index.html';

const html = fs.readFileSync(path, 'utf8');

// ---- 被定义的标识符：function 声明 / 变量函数表达式 / window.X = ----
const defined = new Set();
for (const m of html.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)\s*\(/g)) defined.add(m[1]);
for (const m of html.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\()/g)) {
  defined.add(m[1]);
}
for (const m of html.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>/g)) {
  defined.add(m[1]);
}
for (const m of html.matchAll(/window\.([A-Za-z_$][\w$]*)\s*=/g)) defined.add(m[1]);

// ---- 内联事件处理器里被调用的标识符 ----
// 只统计「自由函数调用」：前面不是 `.` 的，才算全局调用；
// xxx.replace(...) / event.stopPropagation() / this.closest(...).remove() 是方法调用，
// 与「函数有没有被定义」无关，混进来会产生假阳性（会让人不再信任这个检查器）。
const called = new Map();
for (const m of html.matchAll(/\son[a-z]+\s*=\s*"([^"]*)"/g)) {
  for (const c of m[1].matchAll(/(^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(/g)) {
    called.set(c[2], (called.get(c[2]) || 0) + 1);
  }
}

// ---- 语言关键字 / 全局内置：不算悬空 ----
const BUILTIN = new Set([
  'if', 'for', 'while', 'switch', 'return', 'typeof', 'catch', 'new', 'delete', 'void', 'in', 'of',
  'Number', 'String', 'Boolean', 'JSON', 'parseInt', 'parseFloat', 'isNaN', 'isFinite',
  'encodeURIComponent', 'decodeURIComponent', 'encodeURI', 'decodeURI',
  'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
  'confirm', 'alert', 'prompt', 'fetch', 'Promise', 'Symbol', 'BigInt',
  'event', 'window', 'document', 'navigator', 'localStorage', 'location', 'history',
  'Array', 'Object', 'Function', 'Math', 'Date', 'RegExp', 'Error', 'Map', 'Set',
  'NaN', 'Infinity', 'undefined', 'null', 'true', 'false', 'this',
]);

const missing = [...called.entries()]
  .filter(([n]) => !defined.has(n) && !BUILTIN.has(n))
  .sort((a, b) => b[1] - a[1]);

console.log(`[refaudit] ${path}：已定义 ${defined.size} 个标识符，内联处理器调用 ${called.size} 个`);
if (missing.length) {
  console.log(`[refaudit] 悬空引用 ${missing.length} 个（点了才报错，属静默缺陷）：`);
  for (const [n, c] of missing) console.log(`  - ${n}  (被引用 ${c} 次)`);
  process.exit(1);
}
console.log('[refaudit] OK：内联处理器无悬空函数引用');
