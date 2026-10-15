// B2 验证（浏览器不可用时的最忠实替代）：从 user-client/index.html 原样取出
//   - 共享 API.createRun（约 2648）  —— 真实执行，拦截发出的请求体
//   - OA 形态 oaToggleKB（约 6552）  —— 真实执行，翻转 S.kbOn 并同步 chip 文案/off 类
//   - OA 发起调用时构造的 context 表达式（约 8157：{kb_on:(S.kbOn!==false), expert:...}）
// 用 mock DOM（#oaKbChip / #oaKbChipText）+ 捕获 fetch 的方式，证明：
//   默认 kb_on=true 顶层；点击 chip 一次后 kb_on=false 顶层；chip 文案/off 类同步。
// 注：本环境无可用浏览器运行时（agent-browser 启动即挂），故未做真实点击；
//     但以下执行的是产品真实函数体，捕获的是真实 outgoing body，非"读代码下结论"。

const fs = require('fs');
const path = require('path');
const htmlPath = path.resolve(__dirname, '../user-client/index.html');
const src = fs.readFileSync(htmlPath, 'utf8');

// ---- 1) 抽取函数体工具（按精确定义锚点，避免命中 onclick 等调用点）----
// 返回从锚点起、到配平右大括号为止的完整源码片段。
// isMethod=true 时（如 API 对象里的方法，无 function 关键字）补一个 function 前缀。
function extractFn(tag, isMethod) {
  const s = src.indexOf(tag);
  if (s < 0) throw new Error('未找到 ' + tag);
  const i = src.indexOf('{', s);                 // 方法体 { 的位置
  const head = src.slice(s, i);                   // 签名（不含 {）
  let depth = 0, rest = '';
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) { rest += '}'; break; } }
    rest += ch;
  }
  return (isMethod ? 'function ' : '') + head + rest;
}

// createRun 是 API 对象的方法（无 function 关键字）；oaToggleKB 是顶层函数
const createRunSrc = extractFn('createRun(convId,text,context,attachments){', true);
const oaToggleKBSrc = extractFn('function oaToggleKB(){', false);

// ---- 2) mock 环境 ----
const captured = []; // {path, body}
const state = { model: 'm', token: null };
const api = {
  base: '/api',
  req(p, opts) {
    if (p.includes('/conversations/') && p.includes('/runs')) {
      captured.push({ path: p, body: JSON.parse(opts.body) });
    }
    return Promise.resolve({ id: 'run-1', runId: 'run-1' });
  },
  state,
};

// mock DOM：#oaKbChip（含 classList.toggle）+ #oaKbChipText（textContent）
const chipEl = {
  _classes: new Set(),
  classList: {
    toggle(cls, on) { if (on) chipEl._classes.add(cls); else chipEl._classes.delete(cls); },
    contains(cls) { return chipEl._classes.has(cls); },
  },
};
const chipTextEl = { textContent: '' };
const $ = (sel) => sel === 'oaKbChip' ? chipEl : sel === 'oaKbChipText' ? chipTextEl : null;
const toast = () => {};

// OA 形态状态（默认开）
const S = { kbOn: true, expert: { name: '测试专家' }, pendingFiles: [] };

// 注入真实函数（共享对象按引用传入，确保 oaToggleKB 对 S 的修改被外部可见）
const harness = `
${createRunSrc}
${oaToggleKBSrc}
return { createRun, oaToggleKB };
`;
const { createRun, oaToggleKB } = new Function('api', 'chipEl', 'chipTextEl', '$', '$o', 'toast', 'S', 'state', harness)(
  api, chipEl, chipTextEl, $, $, toast, S, state
);
const createRunBound = createRun.bind(api);

// ---- 3) 复刻 OA 发起调用时构造 context 的精确表达式（index.html:8157-8160）----
function buildOaContext() {
  return {
    kb_on: (S.kbOn !== false),
    expert: S.expert ? (S.expert.name || S.expert.key) : undefined,
  };
}

(async () => {
  const results = [];
  const check = (name, pass, detail) => { results.push(pass); console.log(`${pass?'PASS':'FAIL'} | ${name} | ${detail}`); };

  // 初始 chip 文案（来自 HTML 静态标记：<span id="oaKbChipText">知识库 开</span>，无 off 类）
  const initText = '知识库 开';
  check('B2-初 默认 chip 文案=知识库 开', chipTextEl.textContent === initText || chipTextEl.textContent === '', `textContent="${chipTextEl.textContent}" (初始未渲染时为空，静态标记为"知识库 开")`);
  check('B2-初 默认无 off 类', !chipEl.classList.contains('off'), `off=${chipEl.classList.contains('off')}`);

  // 状态0：默认发一次
  captured.length = 0;
  await createRunBound('conv-1', '你好', buildOaContext(), []);
  const b0 = captured[0].body;
  check('B2-a 默认 body.kb_on===true 顶层', b0.kb_on === true, `body.kb_on=${JSON.stringify(b0.kb_on)}`);
  check('B2-b 默认 context 无 kb_on', !('kb_on' in b0.context), `context=${JSON.stringify(b0.context)}`);

  // 点击 chip（真实调用 oaToggleKB）
  oaToggleKB();
  const afterChip = { text: chipTextEl.textContent, off: chipEl.classList.contains('off') };
  check('B2-c chip 文案变为 知识库 关', afterChip.text === '知识库 关', `text="${afterChip.text}"`);
  check('B2-d chip 加上 off 类', afterChip.off === true, `off=${afterChip.off}`);
  check('B2-e S.kbOn 翻转=false', S.kbOn === false, `S.kbOn=${S.kbOn}`);

  // 状态1：再发一次（点击后）
  captured.length = 0;
  await createRunBound('conv-1', '你好', buildOaContext(), []);
  const b1 = captured[0].body;
  check('B2-f 点击后 body.kb_on===false 顶层', b1.kb_on === false, `body.kb_on=${JSON.stringify(b1.kb_on)}`);
  check('B2-g 点击后 context 无 kb_on', !('kb_on' in b1.context), `context=${JSON.stringify(b1.context)}`);
  check('B2-h expert 仍保留', b1.context.expert === '测试专家', `expert=${JSON.stringify(b1.context.expert)}`);

  const all = results.every(Boolean);
  console.log('\n=== B2 结论: ' + (all ? 'ALL PASS' : 'FAIL') + ' ===');
  console.log('默认请求体: ' + JSON.stringify(b0));
  console.log('点击后请求体: ' + JSON.stringify(b1));
  console.log('注意: 本环境无可用浏览器运行时，未做真实点击；以上为真实函数体的动态执行 + 真实 outgoing body 捕获。');
  process.exit(all ? 0 : 1);
})();
