"""多任务协同运行时（Agent 运行层 · 四期）：一份显式计划 → 依赖分层 → 同层并发 → 汇总。

为什么单独成一个运行时
----------------------
`agent_runtime` 是「模型驱动」的：模型每轮吐什么工具，就执行什么，依赖靠多轮往返凑。
这对开放问答是对的，但对**已知步骤的复合任务**（「先取额度、再检索制度、再按额度判断
能不能办」）就慢且不可复现：同样的诉求，模型每次拆出的步骤和顺序都可能不同。

本模块反过来：**调用方先把计划写出来**（子任务 + 依赖 + 入参引用），运行时只负责忠实地
并发执行它。可复现、可断言、可审计 —— 这正是「主 agent 编排式（Planner → 子 agent →
汇总）」架构里 Planner 之外的执行侧。

事件序列（与 run 同源，SSE 契约向后兼容）
-----------------------------------------
    run.started{run_id}
    → tasks.planned{tasks,waves,maxConcurrency}          # 执行前先说清计划
    → [task.started{id,tool,arguments} → task.completed{id,ok,summary,durationMs}]×N
      或 task.skipped{id,reason}
    → tasks.completed{results,ok,failed,skipped,durationMs}
    → run.completed{status,usage}

失败语义
--------
单个子任务失败**不影响同层其它分支**；但它的下游一律跳过并写明原因 —— 拿一个失败任务的
结果当入参继续跑，只会得到「看似成功、实则建立在错误前提上」的答案，比明确失败更难发现。

幂等（按 run_id 回放）
----------------------
编排器刻意不做重试：重复触发会让有副作用的工具被执行两次。但 SSE 断线重连是
**客户端行为**，服务端拦不住 —— 本平台的 SseEmitter 结束时不发终止 chunk，
浏览器侧会判为连接中断并重连，而重连会把整份计划再跑一遍。

因此这里按 run_id 缓存一次执行产出的全部帧：同一个 run_id 再来，直接回放缓存帧，
不再执行任何工具。有副作用的计划才敢交给前端长连接用。
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator

from app.core.orchestrator import DEFAULT_MAX_CONCURRENCY, PlanError, SubTask, stream_run
from app.schemas import SseEvent, TaskPlanRequest
from app.tools_client import ToolClient

logger = logging.getLogger("aioa.agent.multi_task")

# 单份计划允许的子任务上限：防爆内存/防把业务网关打满，超了直接拒（属调用方错误）
MAX_SUBTASKS = 50

# 回放缓存：TTL 秒 + 最多保留份数（够覆盖一次断线重连即可，不做长期存储）
REPLAY_TTL_SECONDS = 300
REPLAY_MAX_ENTRIES = 64
_replay: "OrderedDict[str, tuple[float, list[SseEvent]]]" = OrderedDict()


def _replay_get(run_id: str) -> list[SseEvent] | None:
    """命中且未过期则返回缓存帧（并刷新 LRU 位置）。"""
    hit = _replay.get(run_id)
    if hit is None:
        return None
    at, frames = hit
    if time.time() - at > REPLAY_TTL_SECONDS:
        _replay.pop(run_id, None)
        return None
    _replay.move_to_end(run_id)
    return frames


def _replay_put(run_id: str, frames: list[SseEvent]) -> None:
    _replay[run_id] = (time.time(), frames)
    _replay.move_to_end(run_id)
    while len(_replay) > REPLAY_MAX_ENTRIES:
        _replay.popitem(last=False)


class PlanRejected(ValueError):
    """计划本身不合法（id 重复 / 依赖成环 / 空计划）：拒绝执行，不进入事件流。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def build_plan(req: TaskPlanRequest) -> list[SubTask]:
    """请求体 → 子任务列表；不合法直接抛 PlanRejected（不会执行任何工具）。"""
    if not req.tasks:
        raise PlanRejected("EMPTY_PLAN", "计划为空：至少需要 1 个子任务")
    if len(req.tasks) > MAX_SUBTASKS:
        raise PlanRejected("PLAN_TOO_LARGE", f"子任务过多：{len(req.tasks)} > {MAX_SUBTASKS}")
    try:
        return [
            SubTask(id=t.id, title=t.title or "", tool=t.tool,
                    arguments=dict(t.arguments or {}), depends_on=list(t.dependsOn or []))
            for t in req.tasks
        ]
    except PlanError as exc:  # orchestrator 侧已判定为计划错误
        raise PlanRejected("INVALID_PLAN", str(exc)) from exc


async def run(req: TaskPlanRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """执行一份多任务计划，产出 SSE 事件流。

    同一个 run_id 的重复请求（SSE 断线重连）直接回放缓存帧，不重复执行工具。
    """
    cached = _replay_get(req.run_id)
    if cached is not None:
        logger.info("run %s replayed (%d frames) —— 不重复执行", req.run_id, len(cached))
        for event in cached:
            yield event
        return

    frames: list[SseEvent] = []
    async for event in _execute(req, seq_start=seq_start):
        frames.append(event)
        yield event
    _replay_put(req.run_id, frames)


async def _execute(req: TaskPlanRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """真正执行一次计划（run() 的幂等外壳之下）。"""
    seq = seq_start
    started_at = time.perf_counter()

    yield SseEvent(seq=seq, type="run.started",
                   data={"run_id": req.run_id, "conversation_id": req.conversation_id,
                         "model": "orchestrator", "gateway_key": "orchestrator"})
    seq += 1

    try:
        plan = build_plan(req)
    except PlanRejected as exc:
        logger.warning("run %s plan rejected: %s", req.run_id, exc.message)
        yield SseEvent(seq=seq, type="error",
                       data={"code": exc.code, "message": exc.message, "retryable": False})
        seq += 1
        yield SseEvent(seq=seq, type="run.failed",
                       data={"reason": exc.message, "error_code": exc.code})
        return

    client = ToolClient.from_request(req.user_token)

    async def invoke_tool(name: str, arguments: dict):
        """编排器回调：走业务工具网关（用户 token 透传，工具权限 = 用户权限）。"""
        if not client.enabled:
            return False, None, "工具网关不可用（缺少用户凭证）"
        outcome = await client.invoke(name, arguments)
        return outcome.ok, outcome.data, outcome.error

    results: list = []
    try:
        async for item in stream_run(invoke_tool, plan,
                                     max_concurrency=req.max_concurrency or DEFAULT_MAX_CONCURRENCY,
                                     rename={"task.planned": "tasks.planned"}):
            if isinstance(item, list):  # 末项：执行结果
                results = item
                break
            yield SseEvent(seq=seq, type=item.type, data=item.data)
            seq += 1
    except PlanError as exc:  # build_plan 未能覆盖的边界：仍按计划错误处理
        yield SseEvent(seq=seq, type="error",
                       data={"code": "INVALID_PLAN", "message": str(exc), "retryable": False})
        seq += 1
        yield SseEvent(seq=seq, type="run.failed",
                       data={"reason": str(exc), "error_code": "INVALID_PLAN"})
        return
    except Exception as exc:  # 编排器本身异常：按流内错误收口，不中断服务
        logger.exception("run %s orchestration failed", req.run_id)
        yield SseEvent(seq=seq, type="error",
                       data={"code": "INTERNAL_ERROR", "message": str(exc)[:200], "retryable": True})
        seq += 1
        yield SseEvent(seq=seq, type="run.failed",
                       data={"reason": str(exc)[:200], "error_code": "INTERNAL_ERROR"})
        return

    rows = [r.as_dict() for r in results]
    ok = sum(1 for r in results if r.ok)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.ok and not r.skipped)
    duration = int((time.perf_counter() - started_at) * 1000)
    logger.info("run %s orchestrated: total=%d ok=%d failed=%d skipped=%d in %dms",
                req.run_id, len(results), ok, failed, skipped, duration)

    yield SseEvent(seq=seq, type="tasks.completed",
                   data={"results": rows, "ok": ok, "failed": failed, "skipped": skipped,
                         "durationMs": duration})
    seq += 1
    yield SseEvent(seq=seq, type="run.completed",
                   data={"status": "SUCCEEDED" if failed == 0 else "PARTIAL",
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0}})
