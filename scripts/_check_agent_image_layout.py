#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""哨兵：agent 镜像布局与 HITL 透传自检（离线，无需任何服务）。

## 这个哨兵防的具体缺陷（都真实发生过）

1. **镜像丢包 ⇒ 容器起不来**（2026-10-17 实测）
   AI 能力整体迁到 `agent/aioa_ai/` 后，`deploy/Dockerfile.agent` 仍只 `COPY app ./app`，
   且 `agent/pyproject.toml` 的 `packages.find.include` 仍是 `["app*"]`。
   两者任一单独存在就足够让镜像里的 `app/main.py:14 from aioa_ai import entry` 抛
   `ModuleNotFoundError: No module named 'aioa_ai'` → uvicorn 起不来 → 整个对话不可用。
   **本地永远看不出来**：`uvicorn`/`python -m` 把 cwd（`agent/`）塞进 sys.path，
   `aioa_ai` 恰好在 cwd 下，于是「本机好的，镜像炸的」。

2. **HITL 开关进不了容器 ⇒ 数字人不调自定义表单**
   `aioa_ai/config.py` 里 `agent_hitl` 默认 **False**，而 `agent/.env` 被 `.gitignore`
   和 `.dockerignore` 双重排除、进不了镜像。部署侧（compose / k8s）若不显式透传
   `AIOA_HITL`，容器内恒为 false ⇒ `ask_user` / `request_form` 不进模型工具表
   ⇒ 数字人只会写操作步骤、永远不弹表单。**本地改 .env 修不好生产。**

## 判据设计（正反都有）

- L1/L2 静态：打包清单与 Dockerfile 必须覆盖 `aioa_ai`。
- L3 动态：在临时目录里**按 Dockerfile 的拷贝结果**重建布局，真跑 `import app.main`。
- **L4 是 L3 的负向对照**：同一套逻辑，只拷 `app/` 不拷 `aioa_ai/`，必须**失败**。
  如果 L4 也「成功」，说明 L3 其实没在检验隔离布局（比如误用了 agent/ 的 cwd），
  L3 的绿灯不算数 —— 这条防「测试自己骗自己」。
- L5–L7 部署面：compose / k8s / .env.example 三处都得有 AIOA_HITL。

用法：
    python scripts/_check_agent_image_layout.py
    python scripts/_check_agent_image_layout.py --verbose
退出码：0 全绿；1 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"
RESULTS: list[tuple[str, str, str]] = []  # (level, name, detail)
VERBOSE = False


def ok(name: str, detail: str = "") -> None:
    RESULTS.append(("OK", name, detail))
    print(f"[ OK ] {name}" + (f" — {detail}" if detail and VERBOSE else ""))


def bad(name: str, detail: str) -> None:
    RESULTS.append(("FAIL", name, detail))
    print(f"[FAIL] {name} — {detail}")


def skip(name: str, reason: str) -> None:
    RESULTS.append(("SKIP", name, reason))
    print(f"[SKIP] {name} — {reason}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def python_exe() -> str | None:
    """优先用 agent/.venv（镜像里装的依赖都在那儿），否则退回当前解释器。"""
    for cand in (AGENT / ".venv" / "Scripts" / "python.exe",
                 AGENT / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


# ---------------------------------------------------------------- L1 打包清单
def l1_pyproject_include() -> None:
    p = AGENT / "pyproject.toml"
    if not p.exists():
        bad("L1 pyproject 打包清单", f"找不到 {p}")
        return
    txt = read(p)
    m = re.search(r"\[tool\.setuptools\.packages\.find\](.*?)(?:\n\[|\Z)", txt, re.S)
    if not m:
        bad("L1 pyproject 打包清单", "缺 [tool.setuptools.packages.find] 段")
        return
    inc = re.search(r"include\s*=\s*\[(.*?)\]", m.group(1), re.S)
    if not inc:
        bad("L1 pyproject 打包清单", "include 不是列表字面量，无法静态判定")
        return
    items = re.findall(r"[\"']([^\"']+)[\"']", inc.group(1))
    if any(i.rstrip("*") .startswith("aioa_ai") for i in items):
        ok("L1 pyproject 打包清单含 aioa_ai", f"include={items}")
    else:
        bad("L1 pyproject 打包清单缺 aioa_ai",
            f"include={items}；`pip install .`（非 editable，即镜像构建）产出的 wheel 里"
            "没有 aioa_ai，容器 import 必失败")


# ---------------------------------------------------------------- L2 Dockerfile
def l2_dockerfile_copies() -> None:
    p = ROOT / "deploy" / "Dockerfile.agent"
    if not p.exists():
        bad("L2 Dockerfile 拷贝 aioa_ai", f"找不到 {p}")
        return
    txt = read(p)
    copies_app = re.search(r"^COPY\s+app\s+", txt, re.M) is not None
    copies_ai = re.search(r"^COPY\s+aioa_ai\s+", txt, re.M) is not None
    if not copies_app:
        bad("L2 Dockerfile 拷贝 aioa_ai", "连 COPY app 都没有，Dockerfile 结构可能已变，需人工复核")
    elif copies_ai:
        ok("L2 Dockerfile 拷贝 aioa_ai", "COPY aioa_ai 存在")
    else:
        bad("L2 Dockerfile 拷贝 aioa_ai",
            "Dockerfile.agent 只有 COPY app，没有 COPY aioa_ai ⇒ 容器内 `from aioa_ai import entry` "
            "抛 ModuleNotFoundError，uvicorn 起不来")


# ---------------------------------------------------------------- L3/L4 隔离布局
def _dockerfile_copied_pkgs() -> list[str]:
    """从 Dockerfile.agent 的 COPY 行**推导**镜像里实际有哪些顶层目录。

    这一步必须推导而不是写死：写死 ["app","aioa_ai"] 的话，L3 检验的是「我猜镜像里有
    什么」，而不是「镜像里真的有什么」—— 那正是当年漏掉 aioa_ai 的原因。
    只取 `COPY <目录> ./<目录>` 形态（复制包目录），跳过 pyproject.toml 这类单文件。
    """
    p = ROOT / "deploy" / "Dockerfile.agent"
    if not p.exists():
        return []
    out: list[str] = []
    for line in read(p).splitlines():
        m = re.match(r"^COPY\s+(\S+)\s+\./(\S+)\s*$", line.strip())
        if not m:
            continue
        src = m.group(1).rstrip("/")
        if (AGENT / src).is_dir():
            out.append(src)
    return out


def _simulate(image_pkgs: list[str]) -> tuple[bool, str]:
    """在临时目录里按 Dockerfile 的拷贝结果重建，跑 `import app.main`。"""
    py = python_exe()
    tmp = Path(tempfile.mkdtemp(prefix="aioa_imgsim_"))
    try:
        for pkg in image_pkgs:
            src = AGENT / pkg
            if not src.exists():
                return False, f"源目录不存在：{src}"
            shutil.copytree(src, tmp / pkg,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = {"PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1",
               "PATH": "/usr/bin:/bin:/usr/local/bin",
               "SYSTEMROOT": "C:\\Windows",  # Windows 下 python 启动需要
               "PATH_EXTRA": ""}
        import os
        full_env = dict(os.environ)
        full_env["PYTHONPATH"] = ""
        full_env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [py, "-c", "import app.main"],
            cwd=str(tmp), capture_output=True, text=True, timeout=120, env=full_env,
        )
        tail = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, tail.strip().splitlines()[-1] if tail.strip() else ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def l3_image_layout_imports() -> None:
    pkgs = _dockerfile_copied_pkgs()
    if not pkgs:
        bad("L3 镜像布局可导入 app.main",
            "从 Dockerfile.agent 的 COPY 行推导不出任何包目录，Dockerfile 结构可能已变，需人工复核")
        return
    okk, tail = _simulate(pkgs)
    if okk:
        ok("L3 镜像布局可导入 app.main", f"按 Dockerfile 实际拷贝的 {pkgs} 重建，导入成功")
    else:
        bad("L3 镜像布局可导入 app.main",
            f"按 Dockerfile 实际拷贝的 {pkgs} 重建后导入失败：{tail}")


def l4_negative_control() -> None:
    """负向对照：只拷 app/ 必须失败。若也成功，L3 的绿灯不可信。"""
    okk, tail = _simulate(["app"])
    if okk:
        bad("L4 负向对照（只拷 app 应失败）",
            "只拷 app/ 竟然导入成功 ⇒ 说明 `import app.main` 没在隔离布局里跑"
            "（很可能 aioa_ai 从别处被解析到了），L3 的结论不成立")
    elif "aioa_ai" in tail:
        ok("L4 负向对照（只拷 app 应失败）", tail)
    else:
        bad("L4 负向对照（只拷 app 应失败）",
            f"失败原因不是缺 aioa_ai，需人工复核：{tail}")


# ---------------------------------------------------------------- L5–L7 部署透传
def _compose_agent_block() -> str:
    p = ROOT / "deploy" / "docker-compose.yml"
    if not p.exists():
        return ""
    txt = read(p)
    m = re.search(r"^  agent:\s*$(.*?)(?=^  [A-Za-z0-9_-]+:\s*$)", txt, re.S | re.M)
    return m.group(1) if m else ""


def l5_compose_hitl() -> None:
    blk = _compose_agent_block()
    if not blk:
        bad("L5 compose 透传 AIOA_HITL", "解析不到 docker-compose.yml 的 agent 服务块")
        return
    if re.search(r"^\s+AIOA_HITL\s*:", blk, re.M):
        ok("L5 compose 透传 AIOA_HITL")
    else:
        bad("L5 compose 透传 AIOA_HITL",
            "agent.environment 没有 AIOA_HITL ⇒ 容器内恒为 false ⇒ 数字人不弹自定义表单"
            "（本地改 .env 无效，.env 被 .dockerignore 排除）")


def l6_k8s_hitl() -> None:
    p = ROOT / "deploy" / "k8s" / "00-namespace-config.yaml"
    if not p.exists():
        skip("L6 k8s ConfigMap 有 AIOA_HITL", f"找不到 {p}（可能未用 k8s 部署）")
        return
    if re.search(r"^\s+AIOA_HITL\s*:\s*[\"']?true[\"']?", read(p), re.M):
        ok("L6 k8s ConfigMap 有 AIOA_HITL=true")
    else:
        bad("L6 k8s ConfigMap 有 AIOA_HITL=true",
            "aioa-config 未设 AIOA_HITL=true，agent Pod 的 ask_user/request_form 不会注入")


def l7_env_example() -> None:
    p = AGENT / ".env.example"
    if not p.exists():
        bad("L7 .env.example 记录 AIOA_HITL", "找不到 agent/.env.example")
        return
    if "AIOA_HITL" in read(p):
        ok("L7 .env.example 记录 AIOA_HITL")
    else:
        bad("L7 .env.example 记录 AIOA_HITL",
            "模板里没提 AIOA_HITL ⇒ 新克隆的人不知道有这个开关，会再次踩「数字人不弹表单」")


def _pip_source_ok(txt: str) -> tuple[bool, str]:
    """纯判定：Dockerfile 文本里的 pip 安装行是否「源可覆盖且未被硬编码」。

    为什么单独抽成纯函数：L8b 要拿**合成的坏文本**喂它，证明判据真的会红
    （铁律 7：恒真断言比没断言更危险）。抽不出来就只能对着真文件干瞪眼。
    """
    lines = [ln.strip() for ln in txt.splitlines() if re.match(r"^RUN\b", ln.strip())]
    pip_lines = [ln for ln in lines if "pip install" in ln]
    if not pip_lines:
        return False, "Dockerfile 里找不到 RUN ... pip install 行，结构可能已变，需人工复核"
    bad_lines = [ln for ln in pip_lines
                 if re.search(r"(?:-i|--index-url)\s+https?://", ln)]
    if bad_lines:
        return False, ("pip 源被硬编码进 Dockerfile：" + bad_lines[0][:90] +
                       "\n⇒ 服务器手改这一行后工作区永远有未提交改动，"
                       "之后每次 git pull 都被 `local changes would be overwritten` 挡住。"
                       "镜像源应走 .env 的 PIP_EXTRA_ARGS / --build-arg")
    if not any("${PIP_EXTRA_ARGS}" in ln for ln in pip_lines):
        return False, ("pip install 行没有 ${PIP_EXTRA_ARGS} 口子 ⇒ 国内服务器无法在不改文件的前提下"
                       "换源（只能手改，然后 pull 冲突）")
    return True, f"pip 行已用 ${{PIP_EXTRA_ARGS}} 占位，共 {len(pip_lines)} 条"


def l8_dockerfile_pip_source() -> None:
    p = ROOT / "deploy" / "Dockerfile.agent"
    if not p.exists():
        bad("L8 pip 源可覆盖（不硬编码）", f"找不到 {p}")
        return
    good, detail = _pip_source_ok(read(p))
    (ok if good else bad)("L8 pip 源可覆盖（不硬编码）", detail)

    # L8b 负向对照：把同一份文本的 pip 行换成硬编码镜像源，判定必须翻转成 False。
    fake = read(p).replace(
        "RUN pip install ${PIP_EXTRA_ARGS}",
        "RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple")
    if fake == read(p):
        skip("L8b 负向对照", "没能在真文件里定位 ${PIP_EXTRA_ARGS} 占位行，无法构造对照")
        return
    fake_good, _ = _pip_source_ok(fake)
    if fake_good:
        bad("L8b 负向对照（硬编码源必须判红）",
            "把 pip 行换成硬编码镜像源后判据仍为绿 ⇒ L8 没有判别力")
    else:
        ok("L8b 负向对照（硬编码源必须判红）", "合成坏文本被判红，L8 有牙")


def l9_compose_pip_build_arg() -> None:
    blk = _compose_agent_block()
    if not blk:
        bad("L9 compose 透传 PIP_EXTRA_ARGS", "解析不到 docker-compose.yml 的 agent 服务块")
        return
    if re.search(r"^\s+PIP_EXTRA_ARGS\s*:", blk, re.M):
        ok("L9 compose 透传 PIP_EXTRA_ARGS", "agent.build.args 已带该变量")
    else:
        bad("L9 compose 透传 PIP_EXTRA_ARGS",
            "Dockerfile 留了 ARG 口子但 compose 没透传 ⇒ 在 .env 里写 PIP_EXTRA_ARGS 是空转，"
            "运维只能回去手改 Dockerfile（又是 pull 冲突）")


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()
    VERBOSE = a.verbose

    print("=" * 78)
    print("agent 镜像布局 / HITL 透传自检")
    print(f"仓库根：{ROOT}")
    print("=" * 78)
    l1_pyproject_include()
    l2_dockerfile_copies()
    l3_image_layout_imports()
    l4_negative_control()
    l5_compose_hitl()
    l6_k8s_hitl()
    l7_env_example()
    l8_dockerfile_pip_source()
    l9_compose_pip_build_arg()

    n_ok = sum(1 for lv, _, _ in RESULTS if lv == "OK")
    n_bad = sum(1 for lv, _, _ in RESULTS if lv == "FAIL")
    n_skip = sum(1 for lv, _, _ in RESULTS if lv == "SKIP")
    print("-" * 78)
    print(f"合计 {len(RESULTS)} 项：OK {n_ok} / FAIL {n_bad} / SKIP {n_skip}")
    if n_bad:
        print("\n失败项明细：")
        for lv, name, detail in RESULTS:
            if lv == "FAIL":
                print(f"  - {name}: {detail}")
    if a.json:
        print(json.dumps([{"level": lv, "name": n, "detail": d} for lv, n, d in RESULTS],
                         ensure_ascii=False, indent=2))
    print("=" * 78)
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
