#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aioa_ai 边界静态哨兵脚本（stdlib only，Python 3.10+）。

用途：在不运行业务代码的前提下，静态校验「app -> aioa_ai」单向依赖契约：
  C1  aioa_ai 内不得反向 import app.*
  C2  真正的 langgraph import 仅能出现在 aioa_ai/graph/ 之下（注释/文档字符串提及不算）
  C3  app/** 下（除白名单四文件外）必须是纯 shim / 仅文档字符串
  C4  app/main.py 不得再 import app.core / model_gateway / schemas / tools_client / asr
  C5  新包 aioa_ai 能干净地 import（实际拉起解释器验证）

同时提供 --selftest：用合成的已知坏输入喂给同一个检查函数，
断言其能报出违规，从而证明各检查不是橡皮图章。

用法（仓库根目录执行）：
  python scripts/_check_aioa_ai_boundary.py
  python scripts/_check_aioa_ai_boundary.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径常量：以本脚本所在目录反推仓库根
# ---------------------------------------------------------------------------
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
AGENT_DIR = REPO_ROOT / "agent"
AIOA_AI_DIR = AGENT_DIR / "aioa_ai"
APP_DIR = AGENT_DIR / "app"

# C3 豁免的白名单：这些 app 下文件允许保留真实实现
C3_EXEMPT = {
    APP_DIR / "main.py",
    APP_DIR / "__init__.py",
    APP_DIR / "tools" / "__init__.py",
    APP_DIR / "core" / "__init__.py",
}

# C4 禁止出现在 main.py 中的导入片段
C4_BANNED = [
    "from app.core",
    "from app.model_gateway",
    "from app.schemas",
    "from app.tools_client",
    "from app.asr",
]

# C1 反向导入的正则：行首可有缩进，"from app." 或 "import app"（单词边界）
APP_IMPORT_RE = re.compile(r"^\s*(?:from app\.|import app\b)")


# ---------------------------------------------------------------------------
# 各检查函数：统一接收「文本 / 路径」并返回违规项列表，便于单测
# ---------------------------------------------------------------------------
def find_app_imports(text: str) -> list[tuple[int, str]]:
    """C1：返回文本中命中反向 app 导入的 (行号, 行内容)。"""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if APP_IMPORT_RE.search(line):
            out.append((i, line.strip()))
    return out


def _is_graph_file(path) -> bool:
    """路径是否位于 aioa_ai/graph/ 之下（跨平台归一化）。"""
    p = str(path).replace("\\", "/")
    return "/aioa_ai/graph/" in p


def find_langgraph_outside_graph(text: str, path) -> list[tuple[int, str]]:
    """C2：仅当文件不在 graph/ 之下时，返回其中**真正的 langgraph import 语句**。

    只认 import 语句（走 AST），**注释与文档字符串里提到 `langgraph` 不算违规** ——
    否则「只有 graph/ 允许 import langgraph」这句说明本身就会把检查弄红（恒红哨兵 = 无哨兵）。
    """
    if _is_graph_file(path):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:  # 语法坏文件交给别的检查去报，这里不误伤
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        if any(m == "langgraph" or m.startswith("langgraph.") for m in mods):
            out.append((node.lineno, (ast.get_source_segment(text, node) or "").strip()))
    return out


def _is_type_checking(node) -> bool:
    """判断 if 的判断式是否为 TYPE_CHECKING 或 typing.TYPE_CHECKING。"""
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _target_name(target) -> str | None:
    """从赋值目标中取出简单名字；非简单名字返回 None。"""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def find_shim_violations(path) -> list[tuple[int, str]]:
    """C3：解析单个 .py，返回非纯 shim 的 (行号, 说明)。

    纯 shim 约束：
      - 模块顶层不得有 def / class（TYPE_CHECKING 守卫内允许）
      - 模块级赋值目标只能是 __all__ / __doc__，其余赋值视为违规
      - import 语句（import / from ... import）一律允许
    """
    violations: list[tuple[int, str]] = []
    src = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))

    def _scan(nodes):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = type(node).__name__
                name = getattr(node, "name", "?")
                violations.append((node.lineno, f"{kind} {name}"))
            elif isinstance(node, ast.If) and _is_type_checking(node.test):
                # TYPE_CHECKING 守卫内的 def/class 视为类型标注，跳过
                continue
            elif isinstance(node, ast.If):
                _scan(node.body)
                _scan(node.orelse)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if getattr(node, "target", None) else []
                )
                for t in targets:
                    nm = _target_name(t)
                    if nm and nm not in ("__all__", "__doc__"):
                        violations.append((node.lineno, f"模块级赋值 {nm}"))
            # 其余节点（Expr/docstring、Import、ImportFrom 等）忽略

    _scan(tree.body)
    return violations


def find_main_bad_imports(text: str) -> list[str]:
    """C4：返回 main.py 文本中命中的违禁导入片段。"""
    return [s for s in C4_BANNED if s in text]


# ---------------------------------------------------------------------------
# 汇总运行
# ---------------------------------------------------------------------------
def _print(ok: bool, cid: str, detail: str) -> bool:
    tag = "[PASS]" if ok else "[FAIL]"
    print(f"{tag} {cid} {detail}")
    return ok


def run_checks() -> int:
    """执行 C1~C5，返回非零表示存在失败。"""
    failures = 0

    # ---- C1 ----
    c1: list[tuple[Path, int, str]] = []
    for p in AIOA_AI_DIR.rglob("*.py"):
        for ln, line in find_app_imports(p.read_text(encoding="utf-8")):
            c1.append((p, ln, line))
    if c1:
        failures += 1
        _print(False, "C1", f"aioa_ai 内发现 {len(c1)} 处反向 import app：")
        for p, ln, line in c1:
            print(f"      {p.relative_to(REPO_ROOT)}:{ln}  {line}")
    else:
        _print(True, "C1", "aioa_ai 内未发现任何反向 import app")

    # ---- C2 ----
    c2: list[tuple[Path, int, str]] = []
    for p in AIOA_AI_DIR.rglob("*.py"):
        for ln, line in find_langgraph_outside_graph(p.read_text(encoding="utf-8"), p):
            c2.append((p, ln, line))
    if c2:
        failures += 1
        _print(False, "C2", f"aioa_ai/graph 之外发现 {len(c2)} 处真 langgraph import：")
        for p, ln, line in c2:
            print(f"      {p.relative_to(REPO_ROOT)}:{ln}  {line}")
    else:
        _print(True, "C2", "真 langgraph import 仅出现在 aioa_ai/graph/ 之下")

    # ---- C3 ----
    c3: list[tuple[Path, list[tuple[int, str]]]] = []
    for p in APP_DIR.rglob("*.py"):
        if p in C3_EXEMPT:
            continue
        v = find_shim_violations(p)
        if v:
            c3.append((p, v))
    if c3:
        failures += 1
        _print(False, "C3", f"app 下有 {len(c3)} 个非 shim 文件：")
        for p, v in c3:
            locs = ", ".join(f"L{ln}:{desc}" for ln, desc in v)
            print(f"      {p.relative_to(REPO_ROOT)}  ->  {locs}")
    else:
        _print(True, "C3", "app 下（除白名单外）均为纯 shim")

    # ---- C4 ----
    main_path = APP_DIR / "main.py"
    c4 = find_main_bad_imports(main_path.read_text(encoding="utf-8"))
    if c4:
        failures += 1
        _print(False, "C4", f"main.py 含违禁导入：{', '.join(c4)}")
    else:
        _print(True, "C4", "main.py 未残留 app.core/model_gateway/schemas/tools_client/asr 导入")

    # ---- C5 ----
    venv_py = AGENT_DIR / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        failures += 1
        _print(False, "C5", f"未找到 venv 解释器：{venv_py}")
    else:
        cmd = [
            str(venv_py), "-c",
            "import aioa_ai.entry, aioa_ai.graph.facade, aioa_ai.graph.builder",
        ]
        r = subprocess.run(cmd, cwd=str(AGENT_DIR), capture_output=True, text=True)
        if r.returncode == 0:
            _print(True, "C5", "aioa_ai.entry / graph.facade / graph.builder 导入成功")
        else:
            failures += 1
            _print(False, "C5", f"导入失败（exit={r.returncode}）：{r.stderr.strip()[:300]}")

    return failures


# ---------------------------------------------------------------------------
# 自检：用已知坏输入喂给同一检查函数，断言能报出违规
# ---------------------------------------------------------------------------
def run_selftest() -> int:
    failures = 0

    def check(ok: bool, cid: str) -> None:
        nonlocal failures
        if not ok:
            failures += 1
        _print(ok, cid, "" if ok else "自检未能检出已知坏输入！")

    # SELFTEST-C1：含反向 import 的文本必须被检出
    bad_c1 = "from app.core import Foo\nimport app.bar\n"
    check(bool(find_app_imports(bad_c1)), "SELFTEST-C1")

    # SELFTEST-C2：graph 之外的文件含**真 langgraph import** 必须被检出
    bad_c2 = "from langgraph.graph import StateGraph\n"
    hit = find_langgraph_outside_graph(bad_c2, "agent/aioa_ai/runtimes/echo.py")
    check(bool(hit), "SELFTEST-C2")
    # 反向验证：graph 内文件不应被报（确保不是无差别命中）
    hit_graph = find_langgraph_outside_graph(bad_c2, "agent/aioa_ai/graph/builder.py")
    check(not hit_graph, "SELFTEST-C2-NEG")
    # 反向验证 2：只在注释/文档字符串里提到 langgraph 的文件不应被报
    only_mention = (
        '"""说明：只有 aioa_ai/graph/ 允许 import langgraph。"""\n'
        "# 延迟导入：echo 路径不加载 langgraph\n"
        "from aioa_ai.contracts import RunRequest\n"
    )
    check(not find_langgraph_outside_graph(only_mention, "agent/aioa_ai/entry.py"),
          "SELFTEST-C2-NEG-MENTION")

    # SELFTEST-C3：含顶层 def 的临时文件必须被检出；纯 shim 不应被报
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write('"""doc"""\nfrom aioa_ai.x import Y\n\ndef leftover():\n    pass\n')
        bad_path = f.name
    try:
        bad_hit = find_shim_violations(bad_path)
    finally:
        os.unlink(bad_path)
    check(bool(bad_hit), "SELFTEST-C3")

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write('"""纯 shim"""\nfrom aioa_ai.x import Y, Z\n__all__ = ["Y", "Z"]\n')
        good_path = f.name
    try:
        good_hit = find_shim_violations(good_path)
    finally:
        os.unlink(good_path)
    check(not good_hit, "SELFTEST-C3-NEG")

    # SELFTEST-C4：main.py 文本含违禁导入必须被检出
    bad_c4 = "from app.core import Something\n"
    check(bool(find_main_bad_imports(bad_c4)), "SELFTEST-C4")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="aioa_ai 边界静态哨兵")
    ap.add_argument("--selftest", action="store_true", help="仅运行自检，证明各检查非橡皮图章")
    args = ap.parse_args()

    if args.selftest:
        print("=== SELFTEST ===")
        return 1 if run_selftest() else 0

    print("=== aioa_ai 边界检查 ===")
    return 1 if run_checks() else 0


if __name__ == "__main__":
    sys.exit(main())
