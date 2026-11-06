# -*- coding: utf-8 -*-
"""数据脚本沙箱「数据注入方式」哨兵 —— 纯本地，真子进程跑，不联网。

## 为什么要有这个

`agent/aios_ai/tools/sandbox.py::run_script` 把**工具返回的数据**（邮箱正文、
知识库片段、表格内容）和一个沙箱脚本一起送进子进程。加固前 data 是这样进去的：

    DATA = json.loads(r'''<data>''')      # data 先做过 replace("'", "\\'")

2026-11-01 实测（见 C1，跑的就是旧实现）：

  · data 里只要**有一个撇号** —— `don't`、`it's`、英文邮件正文 —— json 里的 `'`
    被改成 `\'`，而外层是 **raw 字符串** ⇒ 字面量里留下 `\'` ⇒ `json.loads` 抛
    `Invalid \\escape` ⇒ **整个数据脚本工具失败**，报错还长得像「脚本语法错误」。
  · 反斜杠不受影响（json 里本来就叫 `\\\\`，是合法转义）—— 这条也实测过，
    写在这里是为了别把结论说过头。

注：三引号也被一并转义掉了，所以**没有**构成沙箱逃逸（这点必须说准，别夸大）。
但要命的是「用字符串转义把数据塞进代码」这个方案本身：任何一处转义规则对不上，
就是一个必炸的输入。改成 **stdin 传数据**后，源码里只剩常量，转义层彻底消失。

## 判据

  R1  含撇号的 data 能正常执行并**原样往返**（旧实现必失败）
  R2  含反斜杠的 Windows 路径 / 正则原样往返（正向对照，不是回归项）
  R3  含 `'''` 的 data 仍能往返，且**没有**任何代码被执行（写标记文件验证）
  R4  中文往返不乱码（显式 encoding=utf-8）
  R5  data 以反斜杠结尾也正常
  R6  正例：正常脚本照常算出结果（确认没改坏对的路径）
  R7  白名单仍生效：脚本里 `import os` / `open()` 必须被拒
  C1  负向自检：**实跑旧实现**，证明撇号那条确实会炸（判据非恒真）
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from aios_ai.tools.sandbox import run_script  # noqa: E402

PASS = 0
FAIL = 0
FAILS: list[str] = []


def ok(n: str, extra: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[OK  ] {n}" + (f" — {extra}" if extra else ""))


def bad(n: str, extra: str = "") -> None:
    global FAIL
    FAIL += 1
    FAILS.append(n + (f" — {extra}" if extra else ""))
    print(f"[FAIL] {n}" + (f" — {extra}" if extra else ""))


def chk(cond: bool, n: str, extra: str = "") -> bool:
    (ok if cond else bad)(n, extra)
    return cond


def head(t: str) -> None:
    print(f"\n=== {t} ===")


def echo(key: str, value, label: str) -> None:
    """跑一次 `__RESULT__ = DATA[key]` 并断言原样往返。"""
    r = run_script(f"__RESULT__ = DATA.get({key!r})", {key: value})
    chk(r.ok, f"{label} 执行成功", (r.error or "ok")[:80])
    chk(r.ok and r.data == value, f"{label} 原样往返", repr(r.data)[:80] if r.ok else "—")


def main() -> int:
    head("R1 含撇号（'don't' / 'it's'）")
    echo("s", "don't stop, it's fine", "R1 撇号")

    head("R2 含反斜杠的路径 / 正则")
    echo("p", "C:\\Users\\刘尖尖\\WorkBuddy\\aioa", "R2 Windows 路径")
    echo("re", "^\\d+\\s+\\w+$", "R2 正则字面量")

    head("R3 含三引号：要能往返，且不得执行任何代码")
    with tempfile.TemporaryDirectory() as td:
        marker = Path(td) / "pwned.txt"
        evil = "正文'''\n__import__('pathlib').Path(r'%s').write_text('x')\n'''" % marker
        r = run_script("__RESULT__ = DATA.get('body')", {"body": evil})
        chk(r.ok, "R3 含三引号的 data 执行成功", (r.error or "ok")[:80])
        chk(r.ok and r.data == evil, "R3 含三引号的 data 原样往返")
        chk(not marker.exists(), "R3 没有任何代码被执行（标记文件不存在）",
            "标记文件被写出" if marker.exists() else "干净")

    head("R4 中文往返")
    echo("s", "企业微信·连接器·测试", "R4 中文")

    head("R5 反斜杠结尾")
    echo("p", "C:\\temp\\", "R5 反斜杠结尾")

    head("R6 正例：正常脚本照常工作")
    r6 = run_script(
        "rows = DATA.get('rows', [])\n__RESULT__ = {'n': len(rows), 'sum': sum(rows)}",
        {"rows": [1, 2, 3, 4]},
    )
    chk(r6.ok and r6.data == {"n": 4, "sum": 10}, "R6 正常脚本结果正确", str(r6.data))

    head("R7 白名单仍生效")
    r7 = run_script("import os\n__RESULT__ = os.getcwd()", {})
    chk(not r7.ok, "R7 脚本里的 import os 被拒", (r7.error or "")[:60])
    r7b = run_script("__RESULT__ = open('/etc/passwd').read()", {})
    chk(not r7b.ok, "R7 脚本里的 open() 被拒", (r7b.error or "")[:60])

    # -------------------------------------------------------------------- C1
    head("C1 负向自检：实跑旧实现，撇号必须炸")
    src = (ROOT / "agent" / "aios_ai" / "tools" / "sandbox.py").read_text(encoding="utf-8")
    chk("input=data_json" in src, "C1 当前实现用 stdin 传数据")
    chk("__DATA_JSON__" not in src, "C1 源码里已无 __DATA_JSON__ 拼接")

    def old_wrapper(data) -> str:
        dj = json.dumps(data, default=str, ensure_ascii=False)
        tpl = ("import json\nDATA = json.loads(r'''__DATA_JSON__''')\n"
               "print('OK', len(str(DATA)))\n")
        return tpl.replace("__DATA_JSON__", dj.replace("'", "\\'"))

    for label, val in (("撇号", "don't stop"), ("撇号+反斜杠", "it's C:\\temp\\x")):
        p = subprocess.run([sys.executable, "-c", old_wrapper(val)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        err = (p.stderr or "").strip().splitlines()[-1] if p.returncode else ""
        chk(p.returncode != 0, f"C1 旧实现下「{label}」确实失败（判据非恒真）", err[:70])

    # 对照组：只有反斜杠、没有撇号时旧实现是好的 —— 别把结论说过头
    p = subprocess.run([sys.executable, "-c", old_wrapper("C:\\temp\\x")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    chk(p.returncode == 0, "C1 对照：纯反斜杠在旧实现下本来就能过（结论不外扩）",
        (p.stderr or "").strip()[:60])

    print("\n" + "=" * 60)
    if FAIL:
        print(f"FAILED  {FAIL} 项未通过（PASS {PASS}）")
        for f in FAILS:
            print("  · " + f)
        return 1
    print(f"ALL PASS  {PASS} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
