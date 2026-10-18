#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""哨兵：agent 代码里 import 的每个第三方包，必须在 `agent/pyproject.toml` 的 dependencies 里声明。

## 这个哨兵防的具体缺陷（真实发生过两次，同一个模式）

**模式**：本地 `.venv` 是**手工** `pip install xxx` 出来的，而镜像走的是 `pip install .`
—— 只装 `pyproject.toml` 里声明的那些。于是「本地全绿、镜像起不来」。

1. **2026-10-17**：`packages.find.include` 只有 `["app*"]` ⇒ 打出的 wheel 里没有 `aioa_ai`，
   容器 `from aioa_ai import entry` 直接 ModuleNotFoundError。
   （由 `_check_agent_image_layout.py` 的 L1/L2/L3 钉住）
2. **2026-10-18**：`dependencies` 里**没有 `langgraph`**。`aioa_ai/graph/*` 全靠它，
   而它只存在于本地 venv 里 ⇒ 生产 `aioa-agent` 无限
   `Restarting`，日志 `ModuleNotFoundError: No module named 'langgraph'` +
   `ERROR: Application startup failed. Exiting.`（用户看到的是「本次未返回内容」）。

⚠️ **为什么本地测试永远发现不了**：pytest 跑在 `.venv` 里，那里什么都有。
   唯一能提前发现的是「拿 pyproject 的声明的集合 与 代码实际 import 的集合做差集」——
   也就是本脚本。**不要再靠「本地能跑」推断镜像能跑。**

## 判据

- D1：`agent/{app,aioa_ai}/**/*.py` 里所有**顶层**第三方 import，其发行包名必须出现在
      `pyproject.toml` 的 `[project].dependencies` 中（或属于显式登记的传递依赖）。
- D2：**负向对照**：喂一个凭空造出的模块名给同一判定函数，必须被判为「缺声明」。
      否则分不清「真的都声明了」与「判据根本没在工作」。
- D3：本清单非空且能解析（防止 tomllib 解析失败被静默当成「全都有」）。

## 用法

    python scripts/_check_agent_deps_declared.py          # 人类可读
    python scripts/_check_agent_deps_declared.py --json   # 机器可读
退出码 = 缺失项数量（0 = 通过）。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
PYPROJECT = AGENT / "pyproject.toml"
SCAN_DIRS = [AGENT / "app", AGENT / "aioa_ai"]
LOCAL_PKGS = {"app", "aioa_ai", "tests"}

# import 名 ≠ 发行包名的少数情况。**只登记确实需要的**，别为了转绿乱加。
IMPORT_TO_DIST = {
    "faster_whisper": "faster-whisper",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "PIL": "pillow",
    "jwt": "pyjwt",
    "dateutil": "python-dateutil",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "fitz": "pymupdf",
    "pypdf": "pypdf",
}

# 由**已声明**的发行包传递提供、不必单独声明的模块。
# 每条都要写清「谁带进来的」，否则半年后没人敢删。
TRANSITIVE_PROVIDED = {
    "starlette": "fastapi 的依赖（FastAPI 本身基于 Starlette）",
    "pydantic_core": "pydantic 的二进制核心",
    "uvicorn": "uvicorn[standard]",
}


def norm(name: str) -> str:
    """PEP 503 规范化：小写 + 连续 [-_.] 归一成 '-'。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_dists() -> set[str]:
    """`[project].dependencies` 里的发行包名（已规范化，去掉版本/extras）。"""
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    out: set[str] = set()
    for spec in data.get("project", {}).get("dependencies", []):
        # "uvicorn[standard]>=0.27" → "uvicorn"
        name = re.split(r"[<>=!~\[;\s]", spec.strip(), maxsplit=1)[0]
        if name:
            out.add(norm(name))
    return out


def scan_imports() -> dict[str, str]:
    """返回 {顶层模块名: 首个出现位置(相对仓库根的路径:行号)}。"""
    found: dict[str, str] = {}
    stdlib = set(sys.stdlib_module_names)
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # level>0 是相对导入（包内），跳过
                    if node.level == 0 and node.module:
                        names = [node.module.split(".")[0]]
                for n in names:
                    if n in stdlib or n in LOCAL_PKGS:
                        continue
                    found.setdefault(n, f"{p.relative_to(ROOT)}:{node.lineno}")
    return found


def missing_of(imports: dict[str, str], dists: set[str]) -> dict[str, str]:
    """纯判定：给一组 import 与一组已声明发行包，返回缺失项 {模块名: 位置/原因}。"""
    missing: dict[str, str] = {}
    for mod, loc in imports.items():
        if mod in TRANSITIVE_PROVIDED:
            continue
        dist = norm(IMPORT_TO_DIST.get(mod, mod))
        if dist not in dists:
            missing[mod] = f"{loc}（发行包 {dist} 未在 pyproject.toml 声明）"
    return missing


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    results: list[tuple[str, str, str]] = []   # (level, name, detail)

    if not PYPROJECT.exists():
        print(f"❌ 找不到 {PYPROJECT}")
        return 1
    try:
        dists = declared_dists()
    except Exception as exc:                    # noqa: BLE001
        print(f"❌ pyproject.toml 解析失败：{exc}")
        return 1

    # D3：清单非空
    if dists:
        results.append(("OK", "D3 能解析出依赖清单", f"{len(dists)} 个发行包"))
    else:
        results.append(("FAIL", "D3 能解析出依赖清单", "解析结果为空 —— 判据会退化成恒真"))

    imports = scan_imports()
    results.append(("OK", "扫描到第三方 import", f"{len(imports)} 个模块，来自 app/ 与 aioa_ai/"))

    # D1：逐条比对
    missing = missing_of(imports, dists)
    if not missing:
        results.append(("OK", "D1 所有第三方 import 都已声明",
                        "、".join(sorted(imports))))
    else:
        detail = "；".join(f"{m} ← {why}" for m, why in sorted(missing.items()))
        results.append(("FAIL", "D1 所有第三方 import 都已声明", detail))

    # D2：负向对照 —— 凭空造一个模块，必须被判缺失
    fake = {"totally_missing_pkg_for_negative_control": "<合成>"}
    if missing_of(fake, dists):
        results.append(("OK", "D2 负向对照（未声明的包必须判红）",
                        "合成模块被判为缺失，D1 有牙"))
    else:
        results.append(("FAIL", "D2 负向对照（未声明的包必须判红）",
                        "合成模块竟被判为已声明 ⇒ D1 是恒真断言"))

    # 附带说明：哪些模块是靠传递依赖过的
    provided = sorted(m for m in imports if m in TRANSITIVE_PROVIDED)
    if provided:
        results.append(("OK", "传递依赖豁免（已登记）",
                        "、".join(f"{m}（{TRANSITIVE_PROVIDED[m]}）" for m in provided)))

    n_fail = sum(1 for lv, _, _ in results if lv == "FAIL")
    if a.json:
        print(json.dumps([{"level": lv, "name": n, "detail": d} for lv, n, d in results],
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 78)
        print("agent 依赖声明完整性自检（pyproject vs 实际 import）")
        print(f"仓库根：{ROOT}")
        print("=" * 78)
        for lv, name, detail in results:
            print(f"[{lv:^4}] {name}\n        {detail}")
        print("-" * 78)
        if n_fail:
            print("修法：把上面缺失的发行包加进 agent/pyproject.toml 的 dependencies，")
            print("      然后**重建镜像**（docker compose build agent）—— 只重启不生效。")
        else:
            print("结论：pyproject 覆盖了代码的全部第三方 import，镜像 `pip install .` 不会缺包。")
        print("=" * 78)
    return n_fail


if __name__ == "__main__":
    raise SystemExit(main())
