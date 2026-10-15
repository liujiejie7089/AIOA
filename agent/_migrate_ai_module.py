"""一次性迁移工具：把 agent/app 下的 AI 能力复制到统一模块 agent/aioa_ai。

设计要点（为什么这样做）：
  1. **复制而非移动**：app/ 是已推送到 GitHub 的备份（tag `backup/pre-langgraph-2026-10-15`），
     保留它可随时回滚；迁移期两棵树共存。
  2. **显式映射表**：每个源文件 -> 目标路径写死在 MAP 里，不靠猜目录结构。
  3. **有序 sed**：长前缀先替换（`app.model_gateway.mock_llm` 必须先于 `app.model_gateway`），
     否则会产出 `aioa_ai.llm.mock_llm` 这类半截路径。
  4. **自校验**：改完 grep 全树，任何残留 `app.` 引用都当失败，逐条打印，不静默。

只做机械搬运与改引用；新逻辑（LangGraph 图）由人工编写，不在本脚本职责内。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent
APP = AGENT / "app"
DEST = AGENT / "aioa_ai"

# 源文件 -> 目标文件
MAP: dict[str, str] = {
    "config.py": "config.py",
    "schemas.py": "contracts.py",
    "core/events.py": "events.py",
    "core/guards.py": "guard.py",
    "core/answer_shape.py": "prompt/answer.py",
    "core/orchestrator.py": "tools/orchestrator.py",
    "core/intent_router.py": "intent/router.py",
    "core/worker_intake.py": "intent/intake.py",
    "core/echo_runtime.py": "runtimes/echo.py",
    "core/multi_task.py": "runtimes/multi_task.py",
    "model_gateway/__init__.py": "llm/__init__.py",
    "model_gateway/mock_llm.py": "llm/mock.py",
    "model_gateway/gateway.py": "llm/gateway.py",
    "tools_client.py": "tools/client.py",
    "tools/sandbox.py": "tools/sandbox.py",
    "tools/gateway_client.py": "tools/gateway_client.py",
    "asr/engine.py": "speech/engine.py",
    "asr/router.py": "speech/router.py",
}

# 有序替换：长前缀优先。命中即改，不区分行。
REWRITES: list[tuple[str, str]] = [
    # —— from app.X import ... 的具名形式（必须最先，形态特殊）——
    ("from app.core import answer_shape", "from aioa_ai.prompt import answer as answer_shape"),
    ("from app.core import worker_intake", "from aioa_ai.intent import intake as worker_intake"),
    ("from app.core import multi_task, runtime", "from aioa_ai.runtimes import multi_task"),
    # 共享辅助函数：原寄居在 agent_runtime 里，现按职责拆到 knowledge / llm
    ("from app.core.agent_runtime import _citations_from_tool",
     "from aioa_ai.knowledge.kb import _citations_from_tool"),
    ("from app.core.agent_runtime import UpstreamError, _post_non_stream",
     "from aioa_ai.llm.upstream import UpstreamError, _post_non_stream"),
    # —— 具体模块路径 ——
    ("app.model_gateway.mock_llm", "aioa_ai.llm.mock"),
    ("app.model_gateway.gateway", "aioa_ai.llm.gateway"),
    ("app.model_gateway", "aioa_ai.llm"),
    ("app.core.answer_shape", "aioa_ai.prompt.answer"),
    ("app.core.worker_intake", "aioa_ai.intent.intake"),
    ("app.core.intent_router", "aioa_ai.intent.router"),
    ("app.core.orchestrator", "aioa_ai.tools.orchestrator"),
    ("app.core.echo_runtime", "aioa_ai.runtimes.echo"),
    ("app.core.multi_task", "aioa_ai.runtimes.multi_task"),
    ("app.core.events", "aioa_ai.events"),
    ("app.core.guards", "aioa_ai.guard"),
    ("app.tools_client", "aioa_ai.tools.client"),
    ("app.tools.sandbox", "aioa_ai.tools.sandbox"),
    ("app.tools.gateway_client", "aioa_ai.tools.gateway_client"),
    ("app.tools", "aioa_ai.tools"),
    ("app.asr.engine", "aioa_ai.speech.engine"),
    ("app.asr.router", "aioa_ai.speech.router"),
    ("app.asr", "aioa_ai.speech"),
    ("app.schemas", "aioa_ai.contracts"),
    ("app.config", "aioa_ai.config"),
]

# 需要生成 __init__.py 的包目录（内容为简短职责说明 + 必要再导出）
INIT_FILES: dict[str, str] = {
    "prompt/__init__.py": (
        '"""提示词与回答结构约束。"""\n'
        "from aioa_ai.prompt.answer import audit, audit_hint, card, rules\n\n"
        '__all__ = ["audit", "audit_hint", "card", "rules"]\n'
    ),
    "tools/__init__.py": '"""工具层：Java 工具网关客户端 + 同层并发编排 + 沙箱。"""\n',
    "knowledge/__init__.py": '"""知识库检索与引用溯源。"""\n',
    "intent/__init__.py": '"""意图识别（纯规则，不调模型）。"""\n',
    "speech/__init__.py": '"""语音（ASR）能力。"""\n',
    "runtimes/__init__.py": '"""非图运行时：回声演示、显式计划执行。"""\n',
    "graph/__init__.py": (
        '"""LangGraph 运行时：本包是**唯一**允许 import langgraph 的地方。"""\n'
        "from aioa_ai.graph.facade import run\n\n"
        '__all__ = ["run"]\n'
    ),
}


def main() -> int:
    if not APP.is_dir():
        print(f"FAIL: 源目录不存在 {APP}")
        return 1
    DEST.mkdir(exist_ok=True)

    copied = 0
    for src_rel, dst_rel in MAP.items():
        src = APP / src_rel
        dst = DEST / dst_rel
        if not src.is_file():
            print(f"FAIL: 源文件缺失 {src_rel}")
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        for old, new in REWRITES:
            text = text.replace(old, new)
        dst.write_text(text, encoding="utf-8")
        copied += 1

    for rel, content in INIT_FILES.items():
        p = DEST / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(content, encoding="utf-8")

    print(f"copied={copied} files")

    # —— 自校验：新树内不得残留 app.* 引用 ——
    leftovers: list[str] = []
    pat = re.compile(r"\bapp\.(config|schemas|core\.|tools_client|tools|asr|model_gateway)")
    for py in DEST.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if pat.search(line) and not line.strip().startswith("#"):
                leftovers.append(f"{py.relative_to(DEST)}:{i}: {line.strip()}")
    if leftovers:
        print(f"\nFAIL: 仍有 {len(leftovers)} 处 app.* 引用未改写：")
        for item in leftovers:
            print("  " + item)
        return 2
    print("OK: 新树内无残留 app.* 引用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
