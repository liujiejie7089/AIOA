# -*- coding: utf-8 -*-
"""H5 六项修复的静态判据 + script 块语法检查。"""
import os
import re
import subprocess
import tempfile

ROOT = r"D:\aios"
src = open(os.path.join(ROOT, "user-client", "index.html"), encoding="utf-8").read()
checks = []


def chk(name, ok, detail=""):
    checks.append((name, bool(ok), detail))


chk("H3 escJs 用反斜杠转义单引号（非 &#39;）",
    "const escJs = s => esc(s).replace(/\\\\/g,'\\\\\\\\').replace(/'/g,\"\\\\'\")" in src)
chk("H3 三处内联 onclick 改用 escJs",
    src.count("escJs(") == 3, "escJs 使用 %d 处" % src.count("escJs("))
chk("H3 safeUrl 拒绝 javascript: 伪协议",
    "const safeUrl = s =>" in src and "/^(https?:\\/\\/|\\/)/i.test(u)" in src)
chk("H3 附件 href 走 safeUrl + rel=noopener",
    'href="\'+esc(safeUrl(x.url))+\'" target="_blank" rel="noopener"' in src)
chk("M6 上传 50MB 上限",
    "file.size > 50*1024*1024" in src)
chk("M7 SSE 非200 解析信封原因",
    "if(!res.ok){" in src and "envelopeError(eb).message" in src)
chk("L4 token 写 sessionStorage",
    "sessionStorage.setItem('aios_session'" in src)
chk("L4 读回兼容并迁移旧 localStorage",
    "localStorage.getItem('aios_session') || sessionStorage.getItem('aios_session')" in src)
chk("L5 路径参数 encodeURIComponent",
    src.count("encodeURIComponent(convId)") >= 2 and "encodeURIComponent(id)+'/pin'" in src)
chk("L6 流式 rAF 合并 + 防排版回退",
    "requestAnimationFrame(function()" in src and "bubble.classList.contains('ans')" in src)

# script 块语法
blocks = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)
all_ok = True
for i, b in enumerate(blocks):
    if not b.strip():
        continue
    fd, path = tempfile.mkstemp(suffix=".js")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(b)
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        all_ok = False
        print("script block %d SYNTAX FAIL: %s" % (i, r.stderr[:500]))
    os.remove(path)
chk("script 块 node --check 全通过", all_ok, "%d 个非空块" % len([b for b in blocks if b.strip()]))

for name, ok, detail in checks:
    print("%s %s%s" % ("PASS" if ok else "FAIL", name, ("  | " + detail) if detail else ""))
print("TOTAL %d/%d" % (sum(1 for _, ok, _ in checks if ok), len(checks)))
