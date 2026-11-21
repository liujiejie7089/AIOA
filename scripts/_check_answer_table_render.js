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
// 图表引擎整块（var CHART_PALETTE → chartWrap），作为 formatAnswer 的依赖一并注入
const chartStart = src.indexOf('var CHART_PALETTE =');
const chartEnd = src.indexOf('/* 逐行判定层级');
if (chartStart < 0 || chartEnd < 0 || chartEnd <= chartStart) throw new Error('未找到图表引擎代码块');
const chartBlockSrc = src.slice(chartStart, chartEnd);
const formatAnswerSrc = extractFn('function formatAnswer(raw){');

// 注入同一函数作用域：formatAnswer 直接调用 esc / ansInline / 图表引擎
const harness = `
${escSrc}
${ansInlineSrc}
${chartBlockSrc}
${formatAnswerSrc}
return { formatAnswer, chartDetect, chartNum, chartBarSvg, chartPieSvg, chartLineSvg };
`;
const { formatAnswer, chartDetect, chartNum, chartBarSvg, chartPieSvg, chartLineSvg } = new Function(harness)();

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

// ---- T6~T13：图表自动渲染 ----
// 统计表（分类+数值）+ 正文「柱状图」→ 出 SVG 柱状图，保留折叠原始表格
const t6 = '成都市非遗工坊电商平台销量柱状图数据\n| 维度层级 | 数量 | 数据来源·备注 |\n| --- | --- | --- |\n| 淘宝 | 14 | shop_bar_chart |\n| 京东 | 6 | 同上 |\n| 抖音 | 3 | 同上 |';
const o6 = formatAnswer(t6);
check('T6 统计表+柱状图意图→SVG柱状图', o6.includes('<svg') && o6.includes('role="img"') && o6.includes('柱状图'), o6.slice(0, 200));
check('T6 图例/轴映射（横轴维度层级 纵轴数量）', o6.includes('横轴：维度层级') && o6.includes('纵轴：数量'), o6.slice(0, 220));
check('T6 标题取自表格上方文本', o6.includes('成都市非遗工坊电商平台销量柱状图数据'), o6.slice(0, 120));
check('T6 原始表格折叠保留（可核对来源）', o6.includes('<details>') && o6.includes('查看原始数据') && o6.includes('shop_bar_chart'), o6.slice(-180));

// T7 饼图意图 + 0~100 数值 → 饼图
const t7 = '学历构成饼图\n| 维度 | 占比 |\n| --- | --- |\n| 大学 | 40 |\n| 高中 | 35 |\n| 初中 | 25 |';
const o7 = formatAnswer(t7);
check('T7 饼图意图→SVG饼图（path 扇形 + 图例百分比）', o7.includes('<path') && o7.includes('%') && o7.includes('饼图'), o7.slice(0, 200));

// T8 非绘图表格（首列外无纯数值列：说明列）→ 保持原样，不出现 svg
const t8 = '| 维度 | 说明 |\n| --- | --- |\n| 办理量 | 若干 |\n| 在办 | 未知 |';
const o8 = formatAnswer(t8);
check('T8 非绘图表格不渲染 svg，保持原表格', !o8.includes('<svg') && o8.includes('<table class="ans-table">'), o8.slice(0, 160));

// T9 无数据（只有表头）→ 不渲染图表
const t9 = '柱状图统计\n| 维度 | 数量 |\n| --- | --- |';
const o9 = formatAnswer(t9);
check('T9 无数据行不渲染 svg', !o9.includes('<svg') && o9.includes('ans-table'), o9);

// T10 数值格式异常（数量列含非数字）→ 回退表格，不出图
const t10 = '| 维度 | 数量 |\n| --- | --- |\n| 甲 |  twelve |\n| 乙 | unknown |';
const o10 = formatAnswer(t10);
check('T10 数值解析失败回退原表格', !o10.includes('<svg') && o10.includes('ans-table'), o10);

// T11 XSS：分类名含 <img> → SVG 中必须转义
const t11 = '| 维度 | 数量 |\n| --- | --- |\n| <img src=x onerror=alert(1)> | 5 |\n| 正常 | 3 |';
const o11 = formatAnswer(t11);
check('T11 图表中分类名 XSS 转义', o11.includes('&lt;img') && !o11.includes('<img src=x'), o11.slice(0, 240));

// T12 chartNum 纯函数：千分位/单位/加粗 剥离
check('T12 chartNum 解析 "1,234人" →1234', chartNum('1,234人') === 1234, String(chartNum('1,234人')));
check('T12 chartNum 解析 "**27**" →27', chartNum('**27**') === 27, String(chartNum('**27**')));
check('T12 chartNum 拒绝非数字 "twelve"', chartNum('twelve') === null, String(chartNum('twelve')));

// T13b 真实截图场景：用户要「柱状图」，正文另有「占比最高」描述 → 必须仍是柱状图不被改成饼图
const t13b = '成都市非遗工坊电商平台销量柱状图数据\n| 维度层级 | 数量 | 数据来源·备注 |\n| --- | --- | --- |\n| 其他 | 27 | shop_bar_chart |\n| 淘宝 | 14 | 同上 |\n| 京东 | 6 | 同上 |\n说明：其他为接口原样给出的未归类平台项，占比最高（27/58）。柱状图按上表数值渲染即可。';
const o13b = formatAnswer(t13b);
const lb13b = o13b.match(/aria-label="([^"]+)"/);
check('T13b 显式「柱状图」优先于正文「占比」描述→柱状图',
  !!lb13b && lb13b[1].endsWith('柱状图') && o13b.includes('<rect'),
  lb13b ? lb13b[1] : o13b.slice(0,120));

// T13 合计行不进图表数据
const t13 = '柱状图\n| 维度 | 数量 |\n| --- | --- |\n| 淘宝 | 14 |\n| 京东 | 6 |\n| 合计 | 20 |';
const d13 = chartDetect(
  t13.split('\n').filter(function(x){return /^\s*\|/.test(x);}), 1,
  function(r){ var s=r.trim(); if(s[0]==='|')s=s.slice(1); if(s[s.length-1]==='|')s=s.slice(0,-1); return s.split('|').map(function(c){return c.trim();}); },
  '柱状图', t13);
check('T13 合计行不入图表 categories', d13 && d13.cats.indexOf('合计') === -1 && d13.cats.length === 2, JSON.stringify(d13 && d13.cats));

// T14 真实回答标题带（工具名/路径）括注+冒号 → 仍取到干净标题
const t14 = '成都市非遗工坊电商平台销量柱状图数据（shop_bar_chart，/show/shop/barChart）：\n| 维度层级 | 数量 |\n| --- | --- |\n| 淘宝 | 14 |\n| 京东 | 6 |';
const o14 = formatAnswer(t14);
const d14 = chartDetect(
  t14.split('\n').filter(function(x){return /^\s*\|/.test(x);}), 1,
  function(r){ var s=r.trim(); if(s[0]==='|')s=s.slice(1); if(s[s.length-1]==='|')s=s.slice(0,-1); return s.split('|').map(function(c){return c.trim();}); },
  '成都市非遗工坊电商平台销量柱状图数据（shop_bar_chart，/show/shop/barChart）：', t14);
check('T14 标题去掉（括注）：后仍取到干净标题', d14 && d14.title === '成都市非遗工坊电商平台销量柱状图数据', d14 && d14.title);

const all = results.every(Boolean);
console.log('\n[STATUS] ' + (all ? 'PASS' : 'FAIL'));
process.exit(all ? 0 : 1);
