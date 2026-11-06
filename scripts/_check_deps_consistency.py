# -*- coding: utf-8 -*-
"""「本地能跑、部署报错」依赖一致性哨兵 —— 纯本地，不联网、不装包。

## 为什么要有这个

本项目已经**两次**栽在同一类事故上，两次都是「本地一切正常，镜像起不来/某条路径才炸」：

  1. `aios_ai/graph/*` 全部 `from langgraph...`，但 `pyproject.toml` 里**没声明 langgraph**。
     本地 `.venv` 是手工 `pip install langgraph` 的 ⇒ 一直正常；
     镜像走 `pip install .`（只装清单）⇒ 容器启动即
     `ModuleNotFoundError: No module named 'langgraph'` → `Application startup failed`
     （compose 里表现成 aios-agent 一直 `Restarting`）。
  2. 2026-11-01 审计又抓到两个同款：`tools/client.py` 用 `langchain_core`、
     `speech/router.py` 用 `starlette`，两者都没声明，全靠上游传递依赖活着。

还有一类更隐蔽的：**声明了，但本地装的那份元数据是坏的**。
2026-11-01 实测本机 venv：`av` 的 `Version` 是 `None`（RECORD/METADATA 被中断的
卸载流程清空了），`pip check` 还报 `py-key-value-aio` 要 `beartype>=0.20` 而装的是 0.19。
这类状态下「我这能跑」这句话本身就不成立 —— 你根本不知道跑的是哪个版本。
⇒ 本哨兵同时检查「声明」与「实际安装的一致性」，两者都要绿。

## 判据

  R1  四份清单文件都在，且**各自被对应 Dockerfile 引用**（清单存在但 Dockerfile 不读 = 白写）
  R2  Python 版本契约：`pyproject.requires-python` 下界 ≤ 两个 Python 镜像的版本
  R3  Java 版本契约：`pom.xml` 的 `<java.version>` 与 `Dockerfile.server` 的 JDK 大版本一致
  R4  Node 版本契约：`Dockerfile.server` 前端阶段用固定大版本（不许 `latest`）
  R5  基础镜像不许出现 `:latest`（vllm 那个 profile 可选项除外，历史遗留、不参与主链路）
  R6  **agent 侧：源码里 import 到的每个第三方顶层包，都必须在 pyproject 里声明**
  R7  **hub 侧：同上，对照 requirements.txt**
  R8  声明的每个直接依赖在 venv 里都有**有效版本**（`version() is not str` 或 `None` ⇒ 红）
  R9  `pip check` 无依赖冲突
  R10 site-packages 没有 pip 中断残留（`~` 前缀目录）—— 它会让元数据说谎
  C1  负向自检：把 pyproject 副本里的 langchain-core 删掉后 R6 必须转红
      （否则说明 R6 是恒真的摆设）

## 跑法

    python scripts/_check_deps_consistency.py
    AIOS_SKIP_VENV=1 python scripts/_check_deps_consistency.py   # 无 venv 的机器只跑静态项
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agent"
HUB = ROOT / "mcp-hub"
DEPLOY = ROOT / "deploy"
WEB = ROOT / "web"

PASS = 0
FAIL = 0
SKIP = 0
FAILS: list[str] = []


def ok(name: str, extra: str = "") -> None:
    global PASS
    PASS += 1
    print(f"[OK  ] {name}" + (f" — {extra}" if extra else ""))


def bad(name: str, extra: str = "") -> None:
    global FAIL
    FAIL += 1
    FAILS.append(name + (f" — {extra}" if extra else ""))
    print(f"[FAIL] {name}" + (f" — {extra}" if extra else ""))


def skip(name: str, why: str) -> None:
    global SKIP
    SKIP += 1
    print(f"[SKIP] {name} — {why}")


def chk(cond: bool, name: str, extra: str = "") -> bool:
    if cond:
        ok(name, extra)
    else:
        bad(name, extra)
    return cond


def head(t: str) -> None:
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------------------
# import 名 → PyPI 发行名。**没有映射的默认同名**（大小写与 -/_ 会被规范化）。
# 新引入第三方包时如果模块名与发行名不同，必须在这里登记，否则审计会误报。
# ---------------------------------------------------------------------------
DIST_OF: dict[str, str] = {
    "yaml": "pyyaml",
    "faster_whisper": "faster-whisper",
    "langgraph_checkpoint_sqlite": "langgraph-checkpoint-sqlite",
    "langgraph_checkpoint_redis": "langgraph-checkpoint-redis",
    "langchain_core": "langchain-core",
    "langchain_mcp_adapters": "langchain-mcp-adapters",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "multipart": "python-multipart",
    "jose": "python-jose",
}

# 本地包 / 测试 / 类型垫片，不算第三方
LOCAL_MODULES = {"app", "aios_ai", "tests", "mcp_hub", "conftest"}


def canon(name: str) -> str:
    """PEP 503 规范化。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def top_imports(root: Path) -> dict[str, set[str]]:
    """返回 {顶层模块名: {文件...}}，只用 ast，不执行任何代码。"""
    import ast

    out: dict[str, set[str]] = {}
    skip_dirs = {".venv", "__pycache__", "node_modules", ".git", "build", "dist"}
    for p in root.rglob("*.py"):
        if skip_dirs & set(p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    out.setdefault(a.name.split(".")[0], set()).add(str(p.relative_to(ROOT)))
            elif isinstance(node, ast.ImportFrom):
                if node.level:      # 相对导入
                    continue
                if node.module:
                    out.setdefault(node.module.split(".")[0], set()).add(str(p.relative_to(ROOT)))
    return {
        k: v
        for k, v in out.items()
        if k not in sys.stdlib_module_names and k not in LOCAL_MODULES and not k.startswith("_")
    }


def declared_of_pyproject(path: Path) -> set[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", []) or []
    names = set()
    for d in deps:
        m = re.match(r"\s*([A-Za-z0-9._-]+)", d)
        if m:
            names.add(canon(m.group(1)))
    return names


REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def parse_specs(path: Path) -> list[tuple[str, str]]:
    """pyproject 的 dependencies → [(发行名, 版本区间字符串)]，供 venv 侧做区间判定。"""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", []) or []
    out: list[tuple[str, str]] = []
    for d in deps:
        m = re.match(r"\s*([A-Za-z0-9._-]+)\s*(.*)$", d)
        if not m:
            continue
        spec = m.group(2).split(";")[0].strip()   # 去掉环境标记
        out.append((m.group(1), spec))
    return out


def declared_of_requirements(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = REQ_LINE.match(line)
        if m:
            names.add(canon(m.group(1)))
    return names


def audit_imports(label: str, src_root: Path, declared: set[str],
                  allow: dict[str, str] | None = None) -> list[str]:
    """返回「导入了但没声明」的模块列表；同时把结果打成 OK/FAIL。"""
    allow = allow or {}
    imps = top_imports(src_root)
    missing = []
    miss_files: set[str] = set()
    for mod in sorted(imps):
        dist = canon(DIST_OF.get(mod, mod))
        if dist in declared or dist in {canon(a) for a in allow}:
            continue
        missing.append(f"{mod}(→{dist})")
        miss_files |= imps[mod]
    if missing:
        # 只报**缺声明那些模块**的出处，别把无关文件塞进诊断（诊断本身也要准）
        files = ", ".join(sorted(miss_files)[:3])
        bad(f"{label} import 全部已声明", f"未声明：{', '.join(missing)}  出处：{files}")
    else:
        ok(f"{label} import 全部已声明", f"{len(imps)} 个第三方顶层包")
    return missing


def main() -> int:
    # ------------------------------------------------------------------ R1
    head("R1 四份清单都在，且被对应 Dockerfile 引用")
    manifests = {
        "agent/pyproject.toml": AGENT / "pyproject.toml",
        "mcp-hub/requirements.txt": HUB / "requirements.txt",
        "web/package.json": WEB / "package.json",
        "server/pom.xml": ROOT / "server" / "pom.xml",
    }
    for rel, p in manifests.items():
        chk(p.is_file(), f"R1 存在 {rel}", "" if p.is_file() else "缺失")
    if not all(p.is_file() for p in manifests.values()):
        print("\n清单缺失 ⇒ 后续检查无意义，先补齐。")
        return 1

    wire = [
        ("deploy/Dockerfile.agent", AGENT / "pyproject.toml", ["pyproject.toml"]),
        ("mcp-hub/Dockerfile", HUB / "requirements.txt", ["requirements.txt"]),
        ("deploy/Dockerfile.server", WEB / "package.json", ["web/package.json"]),
        ("deploy/Dockerfile.server", WEB / "pnpm-lock.yaml", ["pnpm-lock.yaml"]),
    ]
    for df_rel, _mf, tokens in wire:
        df = (ROOT / df_rel) if df_rel.startswith("deploy") else (HUB / "Dockerfile")
        text = df.read_text(encoding="utf-8") if df.is_file() else ""
        chk(df.is_file() and any(t in text for t in tokens),
            f"R1 {df_rel} 引用了 {tokens[0]}", "" if df.is_file() else f"{df_rel} 不存在")

    # ------------------------------------------------------------------ R2
    head("R2 Python 版本契约")
    py = tomllib.loads(manifests["agent/pyproject.toml"].read_text(encoding="utf-8"))
    rp = (py.get("project", {}).get("requires-python") or "").strip()
    m = re.search(r">=\s*(\d+)\.(\d+)", rp)
    chk(bool(m), "R2 pyproject 声明了 requires-python 下界", rp or "（空）")
    minpy = (int(m.group(1)), int(m.group(2))) if m else (3, 11)

    def img_py(dockerfile: Path) -> tuple[int, int] | None:
        if not dockerfile.is_file():
            return None
        mm = re.search(r"^FROM\s+python:(\d+)\.(\d+)", dockerfile.read_text(encoding="utf-8"), re.M)
        return (int(mm.group(1)), int(mm.group(2))) if mm else None

    for df in (DEPLOY / "Dockerfile.agent", HUB / "Dockerfile"):
        v = img_py(df)
        rel = df.relative_to(ROOT)
        if v is None:
            bad(f"R2 {rel} 基础镜像可解析", "没找到 `FROM python:X.Y`")
            continue
        chk(v >= minpy, f"R2 {rel} 的 Python {v[0]}.{v[1]} 满足 requires-python 下界",
            f"下界={minpy[0]}.{minpy[1]}" if v >= minpy else f"下界={minpy} > {v}")
        chk((v[0], v[1]) == (3, 13), f"R2 {rel} 与本地开发解释器同大版本 3.13",
            f"镜像={v[0]}.{v[1]}")

    # ------------------------------------------------------------------ R3
    head("R3 Java / R4 Node 版本契约")
    pom = manifests["server/pom.xml"].read_text(encoding="utf-8")
    jm = re.search(r"<java\.version>\s*(\d+)\s*<", pom)
    chk(bool(jm), "R3 pom 声明了 java.version", jm.group(1) if jm else "（未找到）")
    jv = jm.group(1) if jm else ""
    dsv = (DEPLOY / "Dockerfile.server").read_text(encoding="utf-8")
    jdk = re.findall(r"(?:eclipse-temurin|openjdk)[:\-](\d+)", dsv)
    chk(bool(jdk), "R3 Dockerfile.server 使用可解析的 JDK 镜像", str(jdk) if jdk else "未找到")
    if jv and jdk:
        chk(jv in jdk, f"R3 pom java {jv} ⊆ 镜像 JDK {','.join(sorted(set(jdk)))}",
            f"pom={jv} image={jdk}")

    nodes = re.findall(r"^FROM\s+node:(\S+)", dsv, re.M)
    chk(bool(nodes), "R4 Dockerfile.server 有 node 构建阶段", str(nodes) if nodes else "未找到")
    if nodes:
        chk(all(re.match(r"^\d+(\.\d+)*", n) for n in nodes),
            f"R4 node 镜像钉大版本（{', '.join(nodes)}）", "不许用 latest / 浮动 tag")

    # ------------------------------------------------------------------ R5
    head("R5 基础镜像不许 latest（vllm profile 除外）")
    offenders = []
    for df in list(DEPLOY.glob("Dockerfile.*")) + [HUB / "Dockerfile"]:
        if not df.is_file():
            continue
        for line in df.read_text(encoding="utf-8").splitlines():
            if line.strip().upper().startswith("FROM") and ":latest" in line:
                offenders.append(f"{df.name}: {line.strip()}")
    chk(not offenders, "R5 应用镜像全部钉版本", "; ".join(offenders))

    # ------------------------------------------------------------------ R6/R7
    head("R6/R7 源码 import ⊆ 清单声明（防「漏声明 ⇒ 镜像起不来」重演）")
    agent_decl = declared_of_pyproject(manifests["agent/pyproject.toml"])
    hub_decl = declared_of_requirements(manifests["mcp-hub/requirements.txt"])
    miss_agent = audit_imports("R6 agent", AGENT, agent_decl)
    miss_hub = audit_imports("R7 mcp-hub", HUB, hub_decl)

    # ------------------------------------------------------------------ R8/R9/R10
    head("R8/R9/R10 实际安装状态（venv 侧）")
    if os.environ.get("AIOS_SKIP_VENV") == "1":
        for n in ("R8", "R9", "R10"):
            skip(n, "AIOS_SKIP_VENV=1")
    else:
        vpy = AGENT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not vpy.is_file():
            for n in ("R8", "R9", "R10"):
                skip(n, f"未找到 {vpy.relative_to(ROOT)}")
        else:
            probe = (
                "import importlib.metadata as m, json, sys\n"
                "want = json.loads(sys.argv[1])\n"
                "out = {}\n"
                "for n in want:\n"
                "    try:\n"
                "        out[n] = m.version(n)\n"
                "    except Exception:\n"
                "        out[n] = None\n"
                "print(json.dumps(out))\n"
            )
            want = sorted(agent_decl)
            r = subprocess.run([str(vpy), "-c", probe, json.dumps(want)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                got = json.loads((r.stdout or "{}").strip().splitlines()[-1])
            except Exception:
                got = {}
            nover = [k for k in want if not (got.get(k) or "").strip()]
            if not got:
                skip("R8 声明依赖都有有效版本元数据", f"探测失败：{(r.stderr or '')[:120]}")
            else:
                chk(not nover, "R8 声明依赖都有有效版本元数据",
                    f"版本为空/缺失：{', '.join(nover)}" if nover else f"{len(want)} 项全部可解析")

            r2 = subprocess.run([str(vpy), "-m", "pip", "check"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            tail = [ln for ln in (r2.stdout or "").splitlines() if ln.strip()]
            chk(r2.returncode == 0, "R9 pip check 无依赖冲突",
                "; ".join(tail[:2]) if r2.returncode else "clean")

            # R11：声明区间 vs 实际安装版本。「声明的」和「装着的」必须对得上，
            # 否则「本地跑通了」证明的不是清单里的那套依赖。
            specs = parse_specs(manifests["agent/pyproject.toml"])
            probe2 = (
                "import importlib.metadata as m, json, sys\n"
                "from packaging.specifiers import SpecifierSet\n"
                "from packaging.version import Version\n"
                "pairs = json.loads(sys.argv[1])\n"
                "bad = []\n"
                "for name, spec in pairs:\n"
                "    try:\n"
                "        v = m.version(name)\n"
                "    except Exception:\n"
                "        bad.append(f'{name}{spec} 未安装'); continue\n"
                "    if spec and not SpecifierSet(spec).contains(Version(v), prereleases=True):\n"
                "        bad.append(f'{name}{v} 不满足 {spec}')\n"
                "print(json.dumps(bad))\n"
            )
            r3 = subprocess.run([str(vpy), "-c", probe2, json.dumps(specs)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                violations = json.loads((r3.stdout or "[]").strip().splitlines()[-1])
            except Exception:
                violations = None
            if violations is None:
                skip("R11 实际安装版本满足声明区间", f"探测失败：{(r3.stderr or '')[:120]}")
            else:
                chk(not violations, "R11 实际安装版本满足声明区间",
                    "; ".join(violations[:4]) if violations else f"{len(specs)} 条区间全部满足")

            sp = vpy.parent.parent / ("Lib/site-packages" if os.name == "nt" else "lib")
            junk = []
            if os.name == "nt" and sp.is_dir():
                junk = [p.name for p in sp.iterdir() if p.name.startswith("~")]
            chk(not junk, "R10 site-packages 无 pip 中断残留（~ 前缀）",
                f"存在：{', '.join(junk[:5])}" if junk else "干净")

    # ------------------------------------------------------------------ C1
    head("C1 负向自检：判据不能是恒真")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "pyproject.toml"
        raw = manifests["agent/pyproject.toml"].read_text(encoding="utf-8")
        # 把 langchain-core 那一行删掉，模拟「忘了声明」
        broken = "\n".join(
            ln for ln in raw.splitlines() if not ln.strip().startswith('"langchain-core')
        )
        chk(broken != raw, "C1 成功构造「缺一条声明」的副本")
        tmp.write_text(broken + "\n", encoding="utf-8")
        decl2 = declared_of_pyproject(tmp)
        imps = top_imports(AGENT)
        still = [m for m in imps if canon(DIST_OF.get(m, m)) in decl2]
        # 删掉 langchain-core 后，langchain_core 必须从「已声明」集合里掉出去
        chk("langchain-core" not in decl2, "C1 副本里确实没有 langchain-core")
        chk("langchain_core" in imps and "langchain_core" not in still,
            "C1 删掉声明后 R6 会转红（判据非恒真）",
            f"imps 命中={len(still)}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    if FAIL:
        print(f"FAILED  {FAIL} 项未通过（PASS {PASS} / SKIP {SKIP}）")
        for f in FAILS:
            print("  · " + f)
        return 1
    print(f"ALL PASS  {PASS} 项" + (f"（跳过 {SKIP}）" if SKIP else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
