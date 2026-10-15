"""AIOA AI 层顶层门面：一次 run 的分派（回声 / LangGraph 图）。

这是「服务接入层（``agent/app``）」调用 AI 能力的**唯一入口**，也是整个 ``aioa_ai``
包对外的收口点：

  - ``provider.driver == "echo"`` → ``aioa_ai.runtimes.echo.run``（离线兜底）
  - 其它（openai_compatible）      → ``aioa_ai.graph.facade.run``（LangGraph 图运行时）

另有 ``resume(run_id, answer)``：HITL 澄清回填（模型调 ``ask_user`` 暂停后，用户选择
经此塞回图里继续），恒定走图门面。

两条路径产出的 SSE 事件序列完全一致（``run.started`` → … → ``run.completed``），
``seq`` 从 1 单调递增 —— 契约与重建前一致，Java / H5 零改动。

设计约定：
  - 分派逻辑只在这里判定一次（守卫单一判定点）；图内不再判定 echo；
  - 对 ``aioa_ai.graph`` 采用**延迟导入**：echo 路径不加载 langgraph，
    离线/最小部署不必拉起图运行时依赖。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from aioa_ai.contracts import RunRequest, SseEvent
from aioa_ai.llm import resolve
from aioa_ai.runtimes import echo

# 首个事件的 seq（契约要求 seq 从 1 单调递增）
FIRST_SEQ = 1


async def run(req: RunRequest, seq_start: int = FIRST_SEQ) -> AsyncIterator[SseEvent]:
    """执行一次 agent 运行，返回事件流（回声 / 图运行时按 provider 自动分派）。"""
    provider = resolve(req.model_ref)
    if provider.driver == "echo":
        async for event in echo.run(req, seq_start=seq_start):
            yield event
        return

    # 延迟导入：把 langgraph 的加载推迟到真正走图运行时的那一刻
    from aioa_ai.graph import facade

    async for event in facade.run(req, seq_start=seq_start):
        yield event


async def resume(run_id: str, answer: Any, seq_start: int = FIRST_SEQ) -> AsyncIterator[SseEvent]:
    """HITL 澄清回填：把用户选择塞回暂停中的 run，从断点继续（仅图运行时支持）。

    回声路径无暂停语义，因此这里恒定走图门面 —— 不在本处再判定 provider（
    「是否真能恢复」由挂起态是否存在决定，见 facade.resume）。
    """
    from aioa_ai.graph import facade

    async for event in facade.resume(run_id, answer, seq_start=seq_start):
        yield event
