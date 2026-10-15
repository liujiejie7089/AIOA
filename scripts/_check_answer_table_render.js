// 答案 markdown 表格渲染验证：从构建产物 user-client/index.html 原样取出
//   - esc（约 2883，单行箭头函数）
//   - ansInline（约 6059）
//   - formatAnswer（约 6067，两种形态与回放共用的唯一收口）
// 真实执行这三个函数体，验证 pipe 表格被安全渲染为 <table>，且不引入 HTML 注入面。
// 手法同 scripts/_check_kb_chip.js（抽取真实函数体 + new Function 执行）。

const fs = require('fs');
const path = require('path');
const htmlPath = path.resolve(__dirname, '../user-client/index.html');
const src = fs.readFileSync(htmlPath, 'utf8');

// ---- 1) 抽取函数体工具 ----
// 多行函数（含 { 块体）：按精确定义锚点，到配平右大括号为止。
function extractFn(tag) {
  const s = src.indexOf(tag);
  if (s < 0) throw new Error('未找到 ' + tag);
  const i = src.indexOf('{', s);
  let depth = 0, rest = '';
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) { rest += '}'; break; } }
    rest += ch;
  }
  return src.slice(s, i) + rest;
}
// 单行箭头函数（esc）：无块体，直接取到行尾。
function extractLine(tag) {
  const s = src.indexOf(tag);
  if (s < 0) throw new Error('未找到 ' + tag);
  const e = src.indexOf('\n', s);
  return src.slice(s, e < 0 ? src.length : e);
}

const escSrc = extractLine('const esc = s =>');
const ansInlineSrc = extractFn('function ansInline(s){');
const formatAnswerSrc = extractFn('function formatAnswer(raw){');

// 注入同一函数作用域：formatAnswer 直接调用 esc / ansInline
const harness = `
${escSrc}
${ansInlineSrc}
${formatAnswerSrc}
return { formatAnswer };
`;
const { formatAnswer } = new Function(harness)();

// ---- 2) 断言 ----
const results = [];
const check = (name, pass, detail) => {
  results.push(pass);
  console.log(`${pass ? 'PASS' : 'FAIL'} | ${name} | ${detail}`);
};

// T1 合法 2 列 pipe 表格 → 含 <table class="ans-table"> 且含 <th>/<td> 与单元格文本
const t1 = '| 维度 | 数量 |\n| --- | --- |\n| 办理量 | 128 |\n| 在办 | 12 |';
const o1 = formatAnswer(t1);
check('T1 合法2列表格→含 <table class="ans-table">', o1.includes('<table class="ans-table">'), o1.slice(0, 140));
check('T1 含 <thead>/<th>/<tbody>/<td> 与单元格文本',
  o1.includes('<th>') && o1.includes('<td>') && o1.includes('维度') && o1.includes('办理量') && o1.includes('128'),
  o1.slice(0, 140));

// T2 负向对照：含 | 但没有分隔行的行 → 不得含 <table（落回普通段落）
const t2 = '| 这只是一个 | 普通含竖线的句子，不是表格 |';
const o2 = formatAnswer(t2);
check('T2 无分隔行的 pipe 行不得含 <table', !o2.includes('<table'), o2);

// T3 XSS：单元格内容为 <img src=x onerror=alert(1)> → 必须含 &lt;img、不得含裸 <img
const t3 = '| 风险项 | 说明 |\n| --- | --- |\n| <img src=x onerror=alert(1)> | 注入尝试 |';
const o3 = formatAnswer(t3);
check('T3 XSS 转义：含 &lt;img', o3.includes('&lt;img'), o3.slice(0, 160));
check('T3 不得含裸 <img（先转义不变式未被破坏）', !o3.includes('<img'), o3.slice(0, 160));

// T4 普通无竖线段落 → 结构不变（含 <div>）、无 <table>
const t4 = '这是一段普通的回答，含重点 **关键结论** 与数字 12 个工作日。';
const o4 = formatAnswer(t4);
check('T4 普通段落含 <div> 且不含 <table>', o4.includes('<div>') && !o4.includes('<table'), o4);

// T5 分隔行 | --- | :---: | 不得作为数据行出现
const t5 = '| 项目 | 占比 |\n| --- | :---: |\n| A | B |';
const o5 = formatAnswer(t5);
check('T5 分隔行不作为数据行（无 >---< 或 >:---:<）',
  !o5.includes('>---<') && !o5.includes('>:---:<'), o5);
check('T5 对齐冒号被消费为 style 而非格文本',
  o5.includes('text-align:center') && !o5.includes(':---:'), o5);

const all = results.every(Boolean);
console.log('\n[STATUS] ' + (all ? 'PASS' : 'FAIL'));
process.exit(all ? 0 : 1);
