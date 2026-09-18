/* H5 内联脚本语法自检：避免手改单文件 H5 后带语法错上线（无构建步骤可兜底）。
   用法： node scripts/_syntax_h5.js  [目标 html，默认 user-client/index.html] */
const fs = require('fs');
const path = require('path');

const target = process.argv[2] || path.join('user-client', 'index.html');
const html = fs.readFileSync(target, 'utf8');
const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;
let m, i = 0, bad = 0;
while ((m = re.exec(html))) {
  i++;
  try {
    new Function(m[1]);
  } catch (e) {
    bad++;
    const line = html.slice(0, m.index).split('\n').length;
    console.log(`script#${i} (起始行 ${line}) SYNTAX ERROR: ${e.message}`);
  }
}
console.log(`inline scripts checked: ${i}, errors: ${bad}`);
process.exit(bad ? 1 : 0);
