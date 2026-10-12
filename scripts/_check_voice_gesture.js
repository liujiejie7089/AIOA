#!/usr/bin/env node
/*
 * _check_voice_gesture.js —— 语音输入「手势状态机」哨兵（无浏览器、无麦克风）
 *
 * 为什么要有它：真机「拿麦克风」在本环境无法验证（需要 HTTPS + 真实设备，
 * 见 docs/47 §0 第一风险）。但本轮要修的缺陷**不在浏览器 API，而在状态机**：
 *   「点击录音按钮后无法正常结束录音」有两个根因，都在纯 JS 状态机里，可脱离浏览器用桩跑出来：
 *     (1) 旧 bindVoice 的 pointerup 里 `if(Date.now() - pressAt < 300){ handsFree = true; ... return; }`
 *         —— 短按会进入一个**隐藏的免提模式**继续录音，要再点一次才结束（S3 要抓住的偏离）。
 *     (2) 旧 bindVoice 的 pointerdown 第一行 `if(state.busy) return;` ——
 *         一旦 state.busy 为 true 就再也进不到「结束」分支，录音停不下来（S6 要抓住的偏离）。
 * 这段逻辑是纯 JS 状态机，可以脱离浏览器用桩跑出来，所以这里做**可复跑的判别力证明**。
 *
 * 用法：
 *   node scripts/_check_voice_gesture.js user-client/_backup_index_pre_oa.html      # 期望全绿（实现落地后）
 *   node scripts/_check_voice_gesture.js /tmp/old.html                              # 旧版（HEAD）：S3/S6 必红
 * 退出码 = 失败用例数（0 才算通过）。没有 `chk(name, true, '')` 这类恒真断言。
 *
 * ★ 判据不读界面副本：断言的是**MediaRecorder 是否真的被 start/stop**、
 *   **asrTranscribe 被调用几次、拿到的 blob 是不是 null、toast 桩被调了什么** ——
 *   直接盯被测对象的行为事实，而不是 placeholder 文案（文案只是提示，不是事实源）。
 *
 * 修正后的手势语义（本哨兵要证明的「正确」）：
 *   1. 纯「按住说话」：pointerdown 开始 → pointerup 结束并发送（免提/短按进免提已删除）。
 *   2. VoiceInput 内 MIN_MS=300；end() 若已开始录音且 now-t0<MIN_MS ⇒ 误触(cancelled, why='too-short')
 *      ⇒ 不发送（asrTranscribe 不调用），并由 bindVoice 用 toast 提示「按住说话…」。
 *   3. done 回调签名 done(blob, why)，why ∈ 'too-short'|'cancelled'|'no-media'|null。
 *   4. 「结束」优先于 busy：pointerdown 先判 if(isLive()){end();return;} 再判 if(state.busy) return;
 *      ⇒ state.busy===true 时仍然必须能结束录音。
 *   5. pointercancel ⇒ 丢弃该段(abort())，不发请求；isLive() 语义不变。
 *   6. 「松手早于麦克风返回」仍不得启动录音、不发请求（上一轮已修好的 S2，别回退）。
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const htmlPath = process.argv[2] || 'user-client/_backup_index_pre_oa.html';
const html = fs.readFileSync(path.resolve(htmlPath), 'utf8');

/* ---------- 从 HTML 里切出 VoiceInput + bindVoice 这一段（不跑整页） ---------- */
const START = 'var VoiceInput = (function(){';
const END = '/* 录音中按钮变红（两形态共用） */';
const a = html.indexOf(START);
const b = html.indexOf(END);
if (a < 0 || b < 0 || b <= a) {
  console.error('[FATAL] 在 ' + htmlPath + ' 里找不到 VoiceInput/bindVoice 段落。');
  console.error('        START=' + a + ' END=' + b + '（文件被改名或结构被改？）');
  process.exit(99);
}
const seg = html.slice(a, b);

/* ---------- 桩：一个可控的极简 DOM / MediaRecorder / 时钟 ---------- */
function makeSandbox() {
  const log = { asrCalls: 0, asrBlobs: [], toasts: [], doneBlob: [] };
  const ctl = { now: 1000000, timers: 0 };

  let mediaResolve = null, mediaReject = null;
  const recorders = [];          // 每次 new MediaRecorder 都留痕（用于断言「有没有开始录」）

  function FakeMediaRecorder(stream, opts) {
    this.stream = stream;
    this.mimeType = (opts && opts.mimeType) || 'audio/webm';
    this.state = 'inactive';
    this.started = false;
    this.stopped = false;
    this.onstop = null;
    this.ondataavailable = null;
    recorders.push(this);
  }
  FakeMediaRecorder.isTypeSupported = function () { return true; };
  FakeMediaRecorder.prototype.start = function () { this.state = 'recording'; this.started = true; };
  FakeMediaRecorder.prototype.stop = function () {
    if (this.state !== 'recording') return;
    this.state = 'inactive';
    this.stopped = true;
    if (this.ondataavailable) this.ondataavailable({ data: { size: 128 } }); // 假装录到了一点数据
    if (this.onstop) this.onstop();
  };

  function El() {
    const handlers = {};
    const classes = new Set();
    return {
      disabled: false, title: '', placeholder: '说点什么…', value: '',
      classList: {
        toggle: (c, on) => { if (on === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); } else if (on) classes.add(c); else classes.delete(c); },
        add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c)
      },
      _classes: classes,
      addEventListener: (t, fn) => { handlers[t] = fn; },
      _fire: (t, ev) => { if (handlers[t]) handlers[t](Object.assign({ preventDefault() {}, pointerId: 1 }, ev || {})); },
      setPointerCapture: () => {},
      _has: (t) => !!handlers[t]
    };
  }

  const sandbox = {
    console,
    Promise, Blob, Set, Object, String, Date: { now: () => ctl.now },
    setTimeout, clearTimeout,
    /* 定时器桩：不让 tick 真的跑，避免进程挂住 */
    setInterval: () => (++ctl.timers), clearInterval: () => {},
    window: { isSecureContext: true },
    navigator: { mediaDevices: { getUserMedia: () => new Promise((res, rej) => { mediaResolve = res; mediaReject = rej; }) } },
    MediaRecorder: FakeMediaRecorder,
    document: { createElement: () => ({ textContent: '' }), head: { appendChild: () => {} } },
    API: {
      asrTranscribe: (blob) => { log.asrCalls++; log.asrBlobs.push(blob); return Promise.resolve({ text: '你好，这是识别结果' }); }
    },
    toast: (m) => log.toasts.push(String(m)),
    state: { busy: false },
    __probe: () => ({ recorders, log, ctl, mediaResolve, mediaReject })
  };
  sandbox.window.MediaRecorder = FakeMediaRecorder;
  sandbox.globalThis = sandbox;

  vm.createContext(sandbox);
  vm.runInContext(seg + '\n;globalThis.__api = { VoiceInput: VoiceInput, bindVoice: bindVoice };', sandbox);

  return {
    sandbox,
    VoiceInput: sandbox.__api.VoiceInput,
    bindVoice: sandbox.__api.bindVoice,
    recorders, log, ctl,
    btn: El(), input: El(),
    resolveMedia: (err) => { const p = sandbox.__probe(); if (err) p.mediaReject(err); else p.mediaResolve({ getTracks: () => [{ stop() {} }] }); },
    pendingMedia: () => !!sandbox.__probe().mediaResolve
  };
}

const tick = () => new Promise(r => setImmediate(r));
const flush = async (n = 6) => { for (let i = 0; i < n; i++) await tick(); };
/* 旧版没有 isLive()：访问要安全，让断言自然判红，而不是把哨兵自己搞崩 */
const isLiveOf = (h) => (typeof h.VoiceInput.isLive === 'function' ? h.VoiceInput.isLive() : '(旧版无 isLive)');
const startedCount = (h) => h.recorders.filter(r => r.started).length;

/* ---------- 断言（失败即记名，绝不恒真） ---------- */
let fails = 0;
function chk(name, cond, detail) {
  if (cond) { console.log('  PASS  ' + name); }
  else { fails++; console.log('  FAIL  ' + name + '   ← ' + (detail || '')); }
}

/* ---------- 各场景 ---------- */
async function S1_hold_then_release() {
  console.log('S1 按住 600ms 后松手 → 应录到一段并自动发送（asr 恰好 1 次，blob 非空，.rec 复位）');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 1000000; h.btn._fire('pointerdown');
  h.resolveMedia(); await flush();                 // 麦克风先到
  chk('S1.1 麦克风到位后确实开始录音(started)', h.recorders.length === 1 && h.recorders[0].started === true,
    'recorders=' + h.recorders.length + ' started=' + (h.recorders[0] && h.recorders[0].started) +
    ' toasts=' + JSON.stringify(h.log.toasts) + ' isLive=' + isLiveOf(h));
  h.ctl.now = 1000600; h.btn._fire('pointerup'); await flush();   // 600ms(≥MIN_MS)后松手
  chk('S1.2 松手后录音被停止(stopped)', h.recorders[0].stopped === true, 'stopped=' + h.recorders[0].stopped);
  chk('S1.3 段被送出（asr 恰好 1 次）', h.log.asrCalls === 1, 'asrCalls=' + h.log.asrCalls);
  chk('S1.4 送出的不是空 blob', !!h.log.asrBlobs[0], 'blob=' + h.log.asrBlobs[0]);
  chk('S1.5 录音视觉态已复位（.rec 移除）', h.btn._classes.has('rec') === false, 'classes=' + [...h.btn._classes]);
}

async function S2_release_before_media() {
  console.log('S2 ★松手早于麦克风返回 → 不得开始录音、不发请求、不卡态（上一轮已修好的回归点）');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 2000000; h.btn._fire('pointerdown');        // 麦克风仍在途中
  h.ctl.now = 2000700; h.btn._fire('pointerup');          // 700ms 后松手（这时 rec 还不存在）
  await flush();
  h.resolveMedia(); await flush();                        // 麦克风终于回来了
  chk('S2.1 麦克风迟到后【没有】启动录音', startedCount(h) === 0,
    '已启动的录音器=' + startedCount(h));
  chk('S2.2 没有向 asr 发请求（空段不发送）', h.log.asrCalls === 0, 'asrCalls=' + h.log.asrCalls);
  chk('S2.3 状态机已收摊（isLive=false，可再次按下）', isLiveOf(h) === false, 'isLive=' + isLiveOf(h));
  chk('S2.4 视觉态未卡在「录音中」', h.btn._classes.has('rec') === false, 'classes=' + [...h.btn._classes]);
}

async function S3_tap_must_stop_no_send() {
  console.log('S3 ★本哨兵核心：短按 100ms（麦克风已到位）再松手 → 必须停止录音、asr 0 次、用 toast 提示「按住说话」');
  console.log('   （旧实现会进入隐藏免提继续录音且不停止 ⇒ 这条在 HEAD 上必红，正是断言要抓住的缺陷）');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 3000000; h.btn._fire('pointerdown'); h.resolveMedia(); await flush();
  h.ctl.now = 3000100; h.btn._fire('pointerup'); await flush();   // 100ms：短按，< MIN_MS
  chk('S3.1 短按后录音【必须被停止】(stopped)', h.recorders[0] && h.recorders[0].stopped === true,
    'started=' + (h.recorders[0] && h.recorders[0].started) + ' stopped=' + (h.recorders[0] && h.recorders[0].stopped));
  chk('S3.2 短按是误触 ⇒ asr 恰好 0 次（不发请求）', h.log.asrCalls === 0, 'asrCalls=' + h.log.asrCalls);
  chk('S3.3 给出含「按住说话」的提示（读 toast 桩，非 placeholder）',
    h.log.toasts.some(t => /按住说话/.test(t)), 'toasts=' + JSON.stringify(h.log.toasts));
  chk('S3.4 状态机收摊（isLive=false）', isLiveOf(h) === false, 'isLive=' + isLiveOf(h));
}

async function S4_pointer_cancel_discards() {
  console.log('S4 手势被浏览器接管（pointercancel）→ 丢弃这一段，不发请求');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 4000000; h.btn._fire('pointerdown'); h.resolveMedia(); await flush();
  chk('S4.1 已开始录音', h.recorders[0] && h.recorders[0].started === true, 'started=' + (h.recorders[0] && h.recorders[0].started));
  h.ctl.now = 4000600; h.btn._fire('pointercancel'); await flush();
  chk('S4.2 取消后录音停止', h.recorders[0].stopped === true, 'stopped=' + h.recorders[0].stopped);
  chk('S4.3 取消不发请求（asr 0 次）', h.log.asrCalls === 0, 'asrCalls=' + h.log.asrCalls);
  chk('S4.4 取消后不卡在录音态', h.btn._classes.has('rec') === false, 'classes=' + [...h.btn._classes]);
}

async function S5_permission_denied() {
  console.log('S5 用户拒绝授权 → 提示权限问题、不发请求、未启动录音、状态机收摊');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 5000000; h.btn._fire('pointerdown');
  const e = new Error('denied'); e.name = 'NotAllowedError';
  h.resolveMedia(e); await flush();
  chk('S5.1 给出权限/未获得提示', h.log.toasts.some(t => /未获得|麦克风|权限|授权/.test(t)),
    'toasts=' + JSON.stringify(h.log.toasts));
  chk('S5.2 不发请求', h.log.asrCalls === 0, 'asrCalls=' + h.log.asrCalls);
  chk('S5.3 未启动任何录音', startedCount(h) === 0, 'started=' + startedCount(h));
  chk('S5.4 状态机收摊', isLiveOf(h) === false, 'isLive=' + isLiveOf(h));
}

async function S6_end_even_when_busy() {
  console.log('S6 ★新增：state.busy===true 时也必须能结束录音（「结束」优先于 busy）');
  console.log('   （旧实现 pointerdown 第一行 if(state.busy) return; 把结束拦掉 ⇒ 这条在 HEAD 上必红）');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  h.ctl.now = 6000000; h.btn._fire('pointerdown'); h.resolveMedia(); await flush(); // 正常起录
  h.sandbox.state.busy = true;                          // 把环境置为 busy（模拟正在对话中）
  chk('S6.0 起录成功（先已 started）', h.recorders[0] && h.recorders[0].started === true,
    'started=' + (h.recorders[0] && h.recorders[0].started) + ' busy=' + h.sandbox.state.busy);
  h.ctl.now = 6000600; h.btn._fire('pointerdown'); await flush();  // 再按一次 = 结束（≥MIN_MS）
  chk('S6.1 busy 下录音【仍被停止】(stopped)', h.recorders[0] && h.recorders[0].stopped === true,
    'stopped=' + (h.recorders[0] && h.recorders[0].stopped));
  chk('S6.2 busy 下结束段被送出（asr 恰好 1 次）', h.log.asrCalls === 1, 'asrCalls=' + h.log.asrCalls);
  chk('S6.3 状态机收摊', isLiveOf(h) === false, 'isLive=' + isLiveOf(h));
}

async function S7_empty_gesture_no_crash() {
  console.log('S7 空手势：未按下就 pointerup/pointercancel → 不应崩、不应发请求');
  const h = makeSandbox(); h.bindVoice(h.btn, h.input, () => {});
  let crashed = false;
  try {
    h.btn._fire('pointerup'); await flush();
    h.btn._fire('pointercancel'); await flush();
  } catch (e) { crashed = true; }
  chk('S7.1 未按下直接 pointerup/pointercancel 不抛异常', crashed === false, '');
  chk('S7.2 空手势不发任何请求', h.log.asrCalls === 0, 'asrCalls=' + h.log.asrCalls);
  chk('S7.3 空手势未启动录音', startedCount(h) === 0, 'started=' + startedCount(h));
}

/* ---------- 跑 ---------- */
(async () => {
  console.log('哨兵：scripts/_check_voice_gesture.js   被测文件：' + htmlPath);
  console.log('（纯状态机；不依赖 HTTPS/麦克风，故可在本环境复跑）\n');
  await S1_hold_then_release();
  await S2_release_before_media();
  await S3_tap_must_stop_no_send();
  await S4_pointer_cancel_discards();
  await S5_permission_denied();
  await S6_end_even_when_busy();
  await S7_empty_gesture_no_crash();
  console.log('\n结果：失败 ' + fails + ' 项');
  console.log('说明：S3(短按必须停止且用 toast 提示「按住说话」)与 S6(busy 下仍须能结束)在**旧版**' +
              '(HEAD，含隐藏免提 / pointerdown 首行 if(state.busy) return)上必然为红 —— 这就是判别力证明。');
  process.exit(fails);
})().catch(e => { console.error('[CRASH] ' + (e && e.stack || e)); process.exit(98); });
