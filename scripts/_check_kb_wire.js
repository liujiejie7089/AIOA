#!/usr/bin/env node
/*
 * 哨兵：知识库开关 `kb_on` 在 H5 → Java 两层接口契约是否正确。
 * （智能体侧另有 scripts/_check_kb_toggle.py）
 *
 * 为什么需要它：`kb_on` 曾经是个**死开关**，而「死」的第一段就发生在 H5——
 * 共享 createRun 把第 3 个参数整体当 context，`kb_on` 被埋进 context 而不是顶层；
 * 后端 DTO 又没有该字段 ⇒ 值必死。这类缺陷只在集成时才暴露。
 *
 * 判据有效性（铁律 12）：--selftest 会用 `git show HEAD:user-client/index.html`
 * 取出**修复前**的 createRun 函数体，跑同一套断言，必须变红。
 *
 * 关键手法：把 createRun 的**函数体原样取出并真实执行**（不是读代码下结论）。
 *
 * 用法：
 *   node scripts/_check_kb_wire.js            # 验当前工作区
 *   node scripts/_check_kb_wire.js --selftest # 额外跑负向对照
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const REPO = path.resolve(__dirname, '..');
const INDEX = path.join(REPO, 'user-client', 'index.html');

let FAILS = [];
let last = { body: null };

function chk(name, cond, detail) {
  if (cond) console.log('PASS  ' + name);
  else { FAILS.push(name); console.log('FAIL  ' + name + '   <<< ' + (detail === undefined ? '' : detail)); }
}

/** 从 index.html 里抽出共享 createRun 的源码（含函数体）。找不到则抛错。 */
function extractCreateRun(src) {
  const m = src.match(/createRun\s*\([^)]*\)\s*\{[\s\S]*?\n\s*\},/);
  if (!m) throw new Error('未能在源码中定位 createRun');
  return m[0];
}

/** 真实执行被抽出的函数体：桩一个 API 对象捕获 req 的 body。 */
function buildCreateRun(fnSrc) {
  const API = {
    state: { model: 'm1' },
    req: function (url, opts) {
      last.body = JSON.parse(opts.body);
      last.url = url;
      return Promise.resolve({ code: 0, data: {} });
    },
  };
  // 函数体里引用 state.model ⇒ 通过闭包注入；createRun 是方法简写，包进对象字面量才合法
  const state = API.state;
  // eslint-disable-next-line no-new-func
  const factory = new Function('API', 'state',
    'return ({' + fnSrc.replace(/,\s*$/, '') + '}).createRun;');
  const fn = factory(API, state);
  return fn.bind(API);  // 函数体用 this.req ⇒ 必须绑定 this
}

const DISCRIMINATING = ['B1.1 kb_on 位于 body 顶层', 'B1.2 context 内无 kb_on'];

function runAsserts(label, createRun) {
  console.log('--- ' + label + ' ---');
  const before = FAILS.length;

  // 正向：kb_on=false + expert 同时存在
  const orig = { kb_on: false, expert: 'x' };
  const snapshot = JSON.stringify(orig);
  createRun(7, 'hi', orig, null);

  chk('B1.1 kb_on 位于 body 顶层', last.body.kb_on === false, JSON.stringify(last.body.kb_on));
  chk('B1.2 context 内无 kb_on', !last.body.context || !('kb_on' in last.body.context),
    JSON.stringify(last.body.context));
  chk('B1.3 context 其它键保留', !!last.body.context && last.body.context.expert === 'x',
    JSON.stringify(last.body.context));
  chk('B1.4 调用方原对象未被改写（浅拷贝生效）', JSON.stringify(orig) === snapshot,
    JSON.stringify(orig));
  chk('B1.5 text 仍在顶层', last.body.text === 'hi', JSON.stringify(last.body.text));
  chk('B1.6 model_ref 仍在顶层', last.body.model_ref === 'm1', JSON.stringify(last.body.model_ref));
  chk('B1.7 无附件时不发 attachments 字段', !('attachments' in last.body), JSON.stringify(last.body));

  // 带附件
  createRun(7, 'hi', { kb_on: true, expert: 'y' }, [{ id: 9 }]);
  chk('B1.8 有附件时 attachments 下传', Array.isArray(last.body.attachments) && last.body.attachments[0].id === 9,
    JSON.stringify(last.body.attachments));
  chk('B1.9 kb_on=true 同样位于顶层', last.body.kb_on === true, JSON.stringify(last.body.kb_on));

  // 旧调用方（不带 kb_on）不应被凭空塞进该字段
  createRun(7, 'plain', { expert: 'z' }, null);
  chk('B1.10 旧调用方不被凭空补 kb_on', !('kb_on' in last.body), JSON.stringify(last.body));

  // 请求 URL 形状
  chk('B1.11 打到 /v1/conversations/<id>/runs', /\/v1\/conversations\/7\/runs$/.test(last.url || ''),
    String(last.url));

  return FAILS.length - before;
}

function checkJava() {
  console.log('--- Java 契约 ---');
  const rq = fs.readFileSync(path.join(REPO, 'server/aioa-chat/src/main/java/cn/aioa/chat/dto/CreateRunRequest.java'), 'utf8');
  const ar = fs.readFileSync(path.join(REPO, 'server/aioa-chat/src/main/java/cn/aioa/chat/dto/AgentRunRequest.java'), 'utf8');
  const sv = fs.readFileSync(path.join(REPO, 'server/aioa-chat/src/main/java/cn/aioa/chat/service/RunService.java'), 'utf8');

  chk('B3.1 CreateRunRequest 有 @JsonProperty("kb_on")', /@JsonProperty\("kb_on"\)/.test(rq));
  chk('B3.2 AgentRunRequest 有 @JsonProperty("kb_on")', /@JsonProperty\("kb_on"\)/.test(ar));
  chk('B3.3 两层字段名一致为 kb_on（无 kbOn 误用为 JSON 名）',
    !/@JsonProperty\("kbOn"\)/.test(rq + ar));
  chk('B3.4 RunService 读取 kb_on（顶层/context）', /kb_on/.test(sv) || /getKbOn|setKbOn/.test(sv));
}

function selftest() {
  console.log('\n--- 修复前（HEAD=负向对照，预期变红）---');
  let old;
  try {
    old = execSync('git show HEAD:user-client/index.html', { cwd: REPO, maxBuffer: 64 * 1024 * 1024 }).toString('utf8');
  } catch (e) {
    console.log('[SELFTEST] git show 失败：' + e.message);
    return 2;
  }
  let n;
  try {
    n = runAsserts('HEAD 版 createRun', buildCreateRun(extractCreateRun(old)));
  } catch (e) {
    console.log('[SELFTEST] 修复前无法构造/执行：' + e.message);
    console.log('[SELFTEST] 修复前连函数形状都对不上 ⇒ 判据有判别力');
    return 0;
  }
  const reds = DISCRIMINATING.filter(function (k) { return FAILS.indexOf(k) >= 0; });
  console.log('\n[SELFTEST] 修复前失败 ' + n + ' 项；判别性断言变红 ' + reds.length + '/' + DISCRIMINATING.length + ' ' + JSON.stringify(reds));
  return reds.length >= 2 ? 0 : 1;
}

(function main() {
  const wantSelf = process.argv.indexOf('--selftest') >= 0;
  const src = fs.readFileSync(INDEX, 'utf8');
  const fnSrc = extractCreateRun(src);
  console.log('提取到的 createRun 源码：\n' + fnSrc.split('\n').map(function (l) { return '  ' + l; }).join('\n') + '\n');

  runAsserts('工作区 index.html', buildCreateRun(fnSrc));
  checkJava();

  let rc = FAILS.length ? 1 : 0;
  console.log('\n结果：失败 ' + FAILS.length + ' 项 ' + (FAILS.length ? JSON.stringify(FAILS) : ''));

  if (wantSelf) {
    const st = selftest();
    if (st !== 0) { rc = 1; console.log('[SELFTEST] FAIL —— 判据无判别力'); }
    else console.log('[SELFTEST] PASS —— 修复前会红、修复后全绿');
  }
  console.log('[STATUS] ' + (rc === 0 ? 'PASS' : 'FAIL'));
  process.exit(rc);
})();
