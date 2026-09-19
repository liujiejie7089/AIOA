"""多任务协同运行时单元测试：计划校验、事件契约、依赖跳过、失败收口。

关注点在「运行时」而非编排器（编排器由 test_orchestrator.py 覆盖）：
本文件验证的是**请求体 → 计划 → SSE 事件**这一段，尤其是失败路径必须给出
可执行的错误码，而不是把异常抛给调用方。
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core import multi_task
from app.core.multi_task import PlanRejected, build_plan
from app.schemas import TaskPlanRequest, UserContext
from app.tools_client import ToolClient, ToolOutcome


def _req(tasks: list[dict], token: str | None = "tok", run_id: str | None = None) -> TaskPlanRequest:
    # 默认每次生成唯一 run_id：run_id 是幂等回放的键，跨用例复用同一 id 会命中缓存而误判
    return TaskPlanRequest(
        run_id=run_id or f"r-{uuid.uuid4().hex[:8]}", conversation_id=1,
        user_context=UserContext(user_id=1, tenant_id=0, roles=["ROLE_ADMIN"]),
        user_token=token,
        tasks=[{"id": t["id"], "tool": t.get("tool", f"tool_{t['id']}"),
                "arguments": t.get("arguments", {}), "dependsOn": t.get("dependsOn", [])}
               for t in tasks],
    )


async def _drain(req: TaskPlanRequest):
    return [ev async for ev in multi_task.run(req)]


def _invoke_by_name(mapping: dict):
    async def invoke(name, arguments):
        outcome = mapping.get(name)
        if outcome is None:
            return ToolOutcome(name=name, arguments=arguments, ok=False, error="未知工具")
        return outcome

    return AsyncMock(side_effect=invoke)


# ---------- build_plan：计划校验（不执行任何工具） ----------

def test_build_plan_rejects_empty():
    with pytest.raises(PlanRejected) as exc:
        build_plan(_req([]))
    assert exc.value.code == "EMPTY_PLAN"


def test_build_plan_rejects_too_large():
    with pytest.raises(PlanRejected) as exc:
        build_plan(_req([{"id": f"t{i}"} for i in range(multi_task.MAX_SUBTASKS + 1)]))
    assert exc.value.code == "PLAN_TOO_LARGE"


def test_build_plan_keeps_dependencies():
    plan = build_plan(_req([{"id": "a"}, {"id": "b", "dependsOn": ["a"]}]))
    assert [(t.id, t.depends_on) for t in plan] == [("a", []), ("b", ["a"])]


# ---------- run：事件契约 ----------

def test_run_emits_full_event_sequence():
    """run.started → tasks.planned → task.started/completed → tasks.completed → run.completed。"""
    req = _req([{"id": "a", "tool": "get_my_quota"}, {"id": "b", "tool": "get_my_quota"}])
    mapping = {"get_my_quota": ToolOutcome(name="get_my_quota", arguments={}, ok=True,
                                           data={"left": 5})}
    with patch.object(ToolClient, "invoke", _invoke_by_name(mapping)):
        events = asyncio.run(_drain(req))

    types = [e.type for e in events]
    assert types[0] == "run.started"
    assert types[1] == "tasks.planned"
    assert types[-2] == "tasks.completed"
    assert types[-1] == "run.completed"
    assert types.count("task.started") == 2 and types.count("task.completed") == 2
    # seq 必须单调递增
    assert [e.seq for e in events] == list(range(1, len(events) + 1))

    planned = events[1].data
    assert planned["waves"] == 1 and planned["maxConcurrency"] > 0
    assert [t["id"] for t in planned["tasks"]] == ["a", "b"]

    summary = events[-2].data
    assert summary["ok"] == 2 and summary["failed"] == 0 and summary["skipped"] == 0
    assert events[-1].data["status"] == "SUCCEEDED"


def test_run_marks_partial_when_any_task_failed():
    req = _req([{"id": "a", "tool": "nope"}, {"id": "b", "tool": "get_my_quota"}])
    mapping = {"get_my_quota": ToolOutcome(name="get_my_quota", arguments={}, ok=True, data=1)}
    with patch.object(ToolClient, "invoke", _invoke_by_name(mapping)):
        events = asyncio.run(_drain(req))

    summary = events[-2].data
    assert summary["ok"] == 1 and summary["failed"] == 1
    assert events[-1].data["status"] == "PARTIAL"


def test_run_skips_downstream_of_failed_dependency():
    """依赖失败 → 下游 task.skipped，并计入 skipped（不计入 failed）。"""
    req = _req([{"id": "a", "tool": "nope"}, {"id": "b", "dependsOn": ["a"]}])
    with patch.object(ToolClient, "invoke", _invoke_by_name({})):
        events = asyncio.run(_drain(req))

    skipped = [e for e in events if e.type == "task.skipped"]
    assert len(skipped) == 1 and skipped[0].data["id"] == "b"
    assert "a" in skipped[0].data["reason"]
    summary = events[-2].data
    assert summary["skipped"] == 1 and summary["failed"] == 1


def test_run_passes_resolved_refs_to_downstream():
    """`$taskId.field` 在下游入参里被替换成前序产出 —— 依赖数据不必靠模型再推理一轮。"""
    req = _req([{"id": "a", "tool": "get_my_quota"},
                {"id": "b", "tool": "echo", "arguments": {"left": "$a.left"}, "dependsOn": ["a"]}])
    seen: dict = {}

    async def invoke(name, arguments):
        seen[name] = arguments
        if name == "get_my_quota":
            return ToolOutcome(name=name, arguments=arguments, ok=True, data={"left": 42})
        return ToolOutcome(name=name, arguments=arguments, ok=True, data=arguments)

    with patch.object(ToolClient, "invoke", AsyncMock(side_effect=invoke)):
        events = asyncio.run(_drain(req))

    assert seen["echo"] == {"left": 42}, seen
    assert events[-2].data["ok"] == 2


def test_run_rejects_cyclic_plan_without_invoking_tools():
    """成环计划：一个工具都不执行，直接 error + run.failed。"""
    req = _req([{"id": "a", "dependsOn": ["b"]}, {"id": "b", "dependsOn": ["a"]}])
    invoke = AsyncMock(return_value=ToolOutcome(name="x", arguments={}, ok=True, data=1))
    with patch.object(ToolClient, "invoke", invoke):
        events = asyncio.run(_drain(req))

    types = [e.type for e in events]
    assert types[-1] == "run.failed"
    assert events[-1].data["error_code"] == "INVALID_PLAN"
    assert "循环" in events[-2].data["message"]
    assert invoke.await_count == 0, "成环计划不应执行任何工具"


def test_run_fails_all_tasks_without_user_token():
    """无用户凭证：任务全部失败且原因明确（工具权限 = 用户权限，不能匿名调用）。"""
    req = _req([{"id": "a"}], token=None)
    invoke = AsyncMock(return_value=ToolOutcome(name="x", arguments={}, ok=True, data=1))
    with patch.object(ToolClient, "invoke", invoke):
        events = asyncio.run(_drain(req))

    summary = events[-2].data
    assert summary["failed"] == 1 and summary["ok"] == 0
    assert invoke.await_count == 0
    result_rows = summary["results"]
    assert result_rows[0]["ok"] is False and "凭证" in (result_rows[0]["error"] or "")


def test_same_run_id_is_replayed_not_reexecuted():
    """同一 run_id 再来一次 → 回放缓存帧，一个工具都不重复执行。

    SSE 断线重连是客户端行为，服务端拦不住；若让它重跑整份计划，有副作用的工具
    就会被执行两次 —— 这正是编排器刻意不做重试的原因。
    """
    req = _req([{"id": "a", "tool": "get_my_quota"}])
    mapping = {"get_my_quota": ToolOutcome(name="get_my_quota", arguments={}, ok=True, data={"left": 5})}
    invoke = _invoke_by_name(mapping)
    with patch.object(ToolClient, "invoke", invoke):
        first = asyncio.run(_drain(req))
        second = asyncio.run(_drain(req))

    assert invoke.await_count == 1, f"第二次应回放而非重跑，实际调用 {invoke.await_count} 次"
    assert [(e.type, e.seq) for e in second] == [(e.type, e.seq) for e in first], second
    assert second[-2].data["ok"] == 1


def test_different_run_ids_execute_separately():
    req1 = _req([{"id": "a", "tool": "get_my_quota"}])
    req2 = _req([{"id": "a", "tool": "get_my_quota"}])
    req2.run_id = "another-run"
    mapping = {"get_my_quota": ToolOutcome(name="get_my_quota", arguments={}, ok=True, data=1)}
    invoke = _invoke_by_name(mapping)
    with patch.object(ToolClient, "invoke", invoke):
        asyncio.run(_drain(req1))
        asyncio.run(_drain(req2))
    assert invoke.await_count == 2, invoke.await_count


def test_replay_cache_is_bounded():
    """缓存有上限：不能让重连帧无限堆积。"""
    multi_task._replay.clear()
    for i in range(multi_task.REPLAY_MAX_ENTRIES + 5):
        multi_task._replay_put(f"r{i}", [])
    assert len(multi_task._replay) == multi_task.REPLAY_MAX_ENTRIES, len(multi_task._replay)
    multi_task._replay.clear()


def test_run_max_concurrency_is_respected():
    """显式指定 maxConcurrency 时写入 tasks.planned 事件（可被调用方观测与断言）。"""
    req = _req([{"id": "a"}])
    req.max_concurrency = 2
    with patch.object(ToolClient, "invoke", _invoke_by_name({})):
        events = asyncio.run(_drain(req))
    assert events[1].data["maxConcurrency"] == 2
