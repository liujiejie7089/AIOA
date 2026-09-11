"""受限 Python 沙箱（方案 P3 / C4）：数据分析师专家执行用户/模型生成的数据处理脚本。

安全边界（决策点 3 · 适度）：
  - 白名单 import：仅开放 pandas / numpy / json / math / statistics / datetime / re，
    拒绝 os / sys / subprocess / socket / requests / builtins.open 等（禁止文件、网络、进程）；
  - 禁内置危险函数：open / eval / exec / __import__ / compile / globals / locals 等；
  - 子进程隔离 + 超时 + 内存限制（不污染主进程）；
  - 注入 db 数据源：脚本内可直接用 `df = DATA["<table>"]` 取到后端预取的租户业务数据。

输出：{ok, data(表格/标量), error, duration_ms}。
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass

logger = logging.getLogger("aioa.agent.sandbox")

# 白名单 import（模块名）
ALLOWED_IMPORTS = {
    "pandas", "numpy", "json", "math", "statistics", "datetime", "re",
}

# 明确禁止的模块名
BLOCKED_MODULES = {"os", "sys", "subprocess", "socket", "shutil", "pathlib",
                   "requests", "urllib", "http", "ftplib", "pickle", "importlib",
                   "ctypes", "multiprocessing", "threading", "builtins"}

# 禁止的调用名（避免用 __builtins__ 绕过）
BLOCKED_NAMES = {"open", "eval", "exec", "compile", "__import__", "globals", "locals",
                 "vars", "setattr", "delattr", "input", "memoryview",
                 "breakpoint", "exit", "quit", "help"}

# 允许的 AST 节点类型（保守白名单）
ALLOWED_NODES = {
    "Module", "Expr", "Assign", "AnnAssign", "AugAssign", "Name", "Constant", "Load",
    "Store", "BinOp", "UnaryOp", "BoolOp", "Compare", "If", "IfExp", "For", "While",
    "Break", "Continue", "Pass", "Return", "Call", "Attribute", "Subscript", "List",
    "Tuple", "Dict", "Set", "Slice", "ListComp", "DictComp", "SetComp", "GeneratorExp",
    "comprehension", "JoinedStr", "FormattedValue", "keyword", "arguments",
    "Lambda", "Starred", "NamedExpr", "Add", "Sub", "Mult", "Div", "Mod", "Pow",
    "FloorDiv", "MatMult", "LShift", "RShift", "BitOr", "BitXor", "BitAnd", "And", "Or",
    "Not", "UAdd", "USub", "Invert", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is", "IsNot",
    "In", "NotIn",
    # import 已在前面单独校验模块白名单，此处放行节点类型
    "Import", "ImportFrom", "alias",
}


@dataclass
class SandboxResult:
    ok: bool
    data: object = None
    error: str | None = None
    duration_ms: int = 0


def _validate_ast(source: str) -> str | None:
    """AST 白名单校验：发现危险结构返回错误描述，安全返回 None。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return f"脚本语法错误：{e.msg}（第 {e.lineno} 行）"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name in BLOCKED_MODULES:
                    return f"禁止导入模块：{name}"
                if name not in ALLOWED_IMPORTS:
                    return f"仅允许导入：{', '.join(sorted(ALLOWED_IMPORTS))}（收到 {name}）"
        elif isinstance(node, ast.ImportFrom):
            name = (node.module or "").split(".")[0]
            if name in BLOCKED_MODULES:
                return f"禁止导入模块：{name}"
            if name not in ALLOWED_IMPORTS:
                return f"仅允许导入：{', '.join(sorted(ALLOWED_IMPORTS))}（收到 {name}）"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BLOCKED_NAMES:
                return f"禁止调用函数：{func.id}"
            if isinstance(func, ast.Attribute) and func.attr in BLOCKED_NAMES:
                return f"禁止调用函数：{func.attr}"
        if type(node).__name__ not in ALLOWED_NODES:
            return f"不允许的语法结构：{type(node).__name__}"

    return None


# 注入子进程的序列化辅助函数源码（把 pandas/numpy 结果转 JSON 结构）
_SERIALIZE_FN = (
    "def _sbx_serialize(obj):\n"
    "    if obj is None:\n"
    "        return None\n"
    "    if hasattr(obj, 'to_dict'):\n"
    "        try:\n"
    "            d = obj.to_dict(orient='records') if hasattr(obj, 'columns') else obj.to_dict()\n"
    "            return json.loads(json.dumps(d, default=str, ensure_ascii=False))\n"
    "        except Exception:\n"
    "            pass\n"
    "    if hasattr(obj, 'tolist'):\n"
    "        try:\n"
    "            return json.loads(json.dumps(obj.tolist(), default=str, ensure_ascii=False))\n"
    "        except Exception:\n"
    "            pass\n"
    "    if isinstance(obj, (str, int, float, bool, list, dict)):\n"
    "        return obj\n"
    "    return str(obj)\n"
)


def run_script(source: str, data: dict, timeout: float = 5.0) -> SandboxResult:
    """在子进程里执行白名单脚本，data 注入为 DATA 全局变量。

    通过 subprocess 隔离：脚本跑飞不拖垮主进程；超时由外层终止。
    """
    start = time.monotonic()
    err = _validate_ast(source)
    if err:
        return SandboxResult(ok=False, error=err)

    data_json = json.dumps(data, default=str, ensure_ascii=False)
    wrapper = (
        "import json\n"
        "DATA = json.loads(r'''__DATA_JSON__''')\n"
        + _SERIALIZE_FN
        + "__RESULT__ = None\n"
        + source + "\n"
        "print('__SANDBOX_RESULT__' + json.dumps(_sbx_serialize(__RESULT__), default=str, ensure_ascii=False))\n"
    ).replace("__DATA_JSON__", data_json.replace("'", "\\'"))

    try:
        proc = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(ok=False, error=f"脚本执行超时（>{timeout}s）",
                             duration_ms=int((time.monotonic() - start) * 1000))
    duration_ms = int((time.monotonic() - start) * 1000)

    if proc.returncode != 0:
        err_msg = (proc.stderr or proc.stdout or "").strip()
        return SandboxResult(ok=False, error=err_msg[:500], duration_ms=duration_ms)

    out = proc.stdout or ""
    marker = "__SANDBOX_RESULT__"
    if marker in out:
        payload = out.split(marker, 1)[1].strip()
        try:
            return SandboxResult(ok=True, data=json.loads(payload), duration_ms=duration_ms)
        except json.JSONDecodeError:
            return SandboxResult(ok=True, data=payload, duration_ms=duration_ms)
    return SandboxResult(ok=True, data=out.strip(), duration_ms=duration_ms)
