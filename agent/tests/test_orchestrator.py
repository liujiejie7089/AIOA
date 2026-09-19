"""多任务编排器单元测试：依赖分层、入参引用、并发与失败传播。

这层的断言必须是**确定性**的：分层结果、跳过原因、结果顺序都不依赖调度抖动，
否则一旦偶发变红就会诱导后人「放宽断言」而不是修问题。
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.orchestrator import (DEFAULT_MAX_CONCURRENCY, Orchestrator, PlanError, SubTask,
                                   plan_waves, resolve_refs, stream_run)


def _t(id_: str, *deps: str, tool: str | None = None, args: dict | None = None) -> SubTask:
    return SubTask(id=id_, tool=tool or f"tool_{id_}", arguments=args or {}, depends_on=list(deps))


# ---------- plan_waves：依赖分层 ----------

def test_waves_layer_by_dependency():
    """无依赖的在第 0 层；依赖全部就绪的进下一层。"""
    waves = plan_waves([_t("a"), _t("b"), _t("c", "a", "b"), _t("d", "c")])
    assert [[t.id for t in w] for w in waves] == [["a", "b"], ["c"], ["d"]]


def test_waves_single_task_is_one_wave():
    assert [[t.id for t in w] for w in plan_waves([_t("only")])] == [["only"]]


def test_waves_rejects_duplicate_id():
    with pytest.raises(PlanError, match="重复"):
        plan_waves([_t("a"), _t("a")])


def test_waves_rejects_unknown_dependency():
    with pytest.raises(PlanError, match="不存在"):
        plan_waves([_t("a", "ghost")])


def test_waves_rejects_self_dependency():
    with pytest.raises(PlanError, match="自己"):
        plan_waves([_t("a", "a")])


def test_waves_rejects_cycle():
    with pytest.raises(PlanError, match="循环"):
        plan_waves([_t("a", "b"), _t("b", "a")])


def test_waves_rejects_empty_id():
    with pytest.raises(PlanError, match="不能为空"):
        plan_waves([SubTask(id="")])


# ---------- resolve_refs：入参引用 ----------

def _results(*pairs) -> dict:
    from app.core.orchestrator import TaskResult
    return {tid: TaskResult(id=tid, ok=ok, data=data) for tid, ok, data in pairs}


def test_refs_whole_result_and_field():
    results = _results(("t1", True, {"left": 7, "used": 3}), ("t2", False, {"x": 1}))
    out = resolve_refs({"a": "$t1", "b": "$t1.left", "c": "plain", "d": 3}, results)
    assert out == {"a": {"left": 7, "used": 3}, "b": 7, "c": "plain", "d": 3}


def test_refs_unresolved_becomes_none():
    """依赖失败 / 任务不存在 / 字段缺失 → None（交工具入参校验去报错，编排器不猜默认值）。"""
    results = _results(("t1", True, {"left": 7}), ("bad", False, {"left": 1}))
    out = resolve_refs({"a": "$bad", "b": "$bad.left", "c": "$t1.missing", "d": "$nope"}, results)
    assert out == {"a": None, "b": None, "c": None, "d": None}


# ---------- Orchestrator.run ----------

async def _echo_invoke(name, arguments):
    return True, {"name": name, "args": arguments}, None


def test_run_returns_results_in_plan_order():
    """结果按**计划顺序**返回，而不是完成顺序 —— 调用方靠下标取结果才不会错位。"""
    plan = [_t("slow", args={"wait": 0.05}), _t("fast")]
    results = asyncio.run(Orchestrator(_echo_invoke).run(plan))
    assert [r.id for r in results] == ["slow", "fast"]
    assert all(r.ok for r in results)


def test_run_resolves_refs_from_upstream_result():
    plan = [
        SubTask(id="t1", tool="first", arguments={"n": 1}),
        SubTask(id="t2", tool="second", arguments={"from": "$t1.name"}, depends_on=["t1"]),
    ]
    results = asyncio.run(Orchestrator(_echo_invoke).run(plan))
    assert results[1].data["args"] == {"from": "first"}, results[1].data


def test_run_skips_downstream_when_dependency_failed():
    """依赖失败 → 下游跳过，且写明原因（不带着错误前提继续）。"""
    async def invoke(name, arguments):
        return (False, None, "boom") if name == "tool_a" else (True, name, None)

    plan = [_t("a"), _t("b", "a")]
    results = asyncio.run(Orchestrator(invoke).run(plan))
    assert results[0].ok is False and results[0].error == "boom"
    assert results[1].skipped is True
    assert "tool_a" not in results[1].error  # 原因里写的是前序任务 id
    assert "a" in results[1].error and "跳过" in results[1].error


def test_run_other_branch_survives_sibling_failure():
    """同层一个任务失败，不影响另一个分支 —— 失败不扩散到无关任务。"""
    async def invoke(name, arguments):
        return (False, None, "boom") if name == "tool_a" else (True, "ok", None)

    results = asyncio.run(Orchestrator(invoke).run([_t("a"), _t("b")]))
    assert results[0].ok is False
    assert results[1].ok is True and results[1].data == "ok"


def test_run_concurrent_tasks_overlap():
    """同层任务真并发：3 个 50ms 的慢任务总耗时应接近 50ms 而非 150ms。

    用墙钟总耗时判断（而不是各任务 duration 之和 —— 那个值串行/并发都一样，
    断言恒真，等于没测）。
    """
    async def slow_invoke(name, arguments):
        await asyncio.sleep(0.05)
        return True, name, None

    started = time.perf_counter()
    results = asyncio.run(Orchestrator(slow_invoke, max_concurrency=4).run([_t("a"), _t("b"), _t("c")]))
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert [r.ok for r in results] == [True, True, True]
    assert max(r.duration_ms for r in results) >= 40, [r.duration_ms for r in results]  # 单个确实慢
    assert elapsed_ms < 120, f"3×50ms 串行约 150ms，实际 {elapsed_ms:.0f}ms —— 未并发"


def test_run_serial_when_concurrency_is_one():
    """并发度=1 时严格串行（关闭并发开关后的行为，事件序可预期）。"""
    started: list[str] = []

    async def invoke(name, arguments):
        started.append(name)
        await asyncio.sleep(0.01)
        return True, name, None

    results = asyncio.run(Orchestrator(invoke, max_concurrency=1).run([_t("a"), _t("b")]))
    assert [r.ok for r in results] == [True, True]
    assert started == ["tool_a", "tool_b"], started


def test_run_emits_lifecycle_events():
    events: list[tuple[str, dict]] = []
    results = asyncio.run(
        Orchestrator(_echo_invoke, on_event=lambda t, d: events.append((t, d))).run([_t("a")]))
    types = [t for t, _ in events]
    assert types == ["task.planned", "task.started", "task.completed"], types
    assert results[0].ok is True


def test_run_catches_invoke_exception_as_failed_task():
    """工具抛异常不算编排器崩溃：收敛成该任务失败（带异常类型，便于定位）。"""

    async def boom(name, arguments):
        raise RuntimeError("kaboom")

    results = asyncio.run(Orchestrator(boom).run([_t("a")]))
    assert results[0].ok is False and "RuntimeError" in (results[0].error or "")


def test_default_concurrency_is_bounded():
    """并发有上限：并发的目的是省等待，不是放大下游压力。"""
    assert DEFAULT_MAX_CONCURRENCY == 4
    assert Orchestrator(_echo_invoke, max_concurrency=0)._max_concurrency == 1


# ---------- stream_run：边跑边吐 ----------

def test_stream_run_yields_events_before_result():
    """事件必须在结果之前产出（否则长计划下等于没有流式）。"""
    out = []

    async def main():
        async for item in stream_run(_echo_invoke, [_t("a"), _t("b")]):
            out.append(type(item).__name__)

    asyncio.run(main())
    assert out[0] == "Event" and out[-1] == "list", out
    assert "list" not in out[:-1]


def test_stream_run_renames_events():
    async def main():
        seen = []
        async for item in stream_run(_echo_invoke, [_t("a")], rename={"task.planned": "tasks.planned"}):
            if hasattr(item, "type"):
                seen.append(item.type)
        return seen
    assert asyncio.run(main()) == ["tasks.planned", "task.started", "task.completed"]
