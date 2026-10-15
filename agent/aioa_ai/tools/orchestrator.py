"""多任务协同编排器（Agent 运行层 · 四期）。

它解决的问题
------------
改造前，一次 run 里的多个工具调用是**串行**执行的（`for call in calls: await invoke(...)`）。
模型一次吐出 3 个互不相关的查询，就要付 3 倍的等待时间；而「先查 A、再用 A
的结果查 B」这种真实依赖又无处表达 —— 只能靠模型多轮往返去凑。

本模块把「多个子任务 + 它们之间的依赖」变成一等公民：

    plan（依赖分层） → 同层并发执行 → 依赖失败则下游跳过并写明原因 → 汇总

设计取舍
--------
1. **按依赖分层（wave）而不是来一个跑一个**：分层的执行计划是可枚举、可测试的；
   「谁和谁真的并行」在执行前就确定，不会因为调度抖动而每次不同。
2. **同层用 asyncio.gather + 信号量**：并发是真并发，但并发度有上限
   （默认 4），避免一次把业务网关打满 —— 并发的目的是省等待，不是放大压力。
3. **依赖失败 = 下游跳过，并写明原因**：不是「照跑然后拿到空数据」。
   用一个失败任务的结果当入参去调下一个工具，只会得到一个看似成功、
   实则建立在错误前提上的答案，比明确失败更难发现。
4. **入参引用用 `$taskId` / `$taskId.field`**：让「B 依赖 A 的结果」这层
   关系写在计划里，而不是靠模型在中间再推理一轮。

不做什么
--------
- 不做「LLM 自动拆解目标」：拆解结果不可复现，无法断言。规划器留给上层，
  本模块只负责**忠实地执行一份给定的计划**。
- 不做重试：重试策略属工具网关与治理层，编排器重复触发会导致副作用翻倍。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

logger = logging.getLogger("aioa.agent.orchestrator")

# 同层并发上限：省等待时间，但不把下游打满
DEFAULT_MAX_CONCURRENCY = 4


@dataclass
class SubTask:
    """一个子任务。"""

    id: str
    title: str = ""
    # 调用方式：给 tool（走业务工具网关）；缺省时把 id 当工具名
    tool: str | None = None
    arguments: dict = field(default_factory=dict)
    # 依赖的子任务 id；全部成功才开始本任务
    depends_on: list[str] = field(default_factory=list)

    def label(self) -> str:
        return self.title or self.tool or self.id


@dataclass
class TaskResult:
    """一个子任务的产出。"""

    id: str
    title: str = ""
    ok: bool = False
    data: object = None
    error: str | None = None
    skipped: bool = False
    duration_ms: int = 0

    def summary(self) -> str:
        if self.skipped:
            return f"{self.id} skipped: {self.error}"
        if not self.ok:
            return f"{self.id} failed: {self.error}"
        text = str(self.data)
        return f"{self.id} ok: {text[:120]}{'…' if len(text) > 120 else ''}"

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "ok": self.ok, "data": self.data,
                "error": self.error, "skipped": self.skipped, "durationMs": self.duration_ms}


class PlanError(ValueError):
    """计划本身不合法：重复 id / 未知依赖 / 循环依赖。属于调用方错误，必须早失败。"""


def plan_waves(tasks: list[SubTask]) -> list[list[SubTask]]:
    """把任务按依赖关系分成若干「可并行层」。

    第 0 层 = 无依赖的任务；其后每层 = 依赖已全部出现在更早层的任务。

    @throws PlanError 重复 id、依赖未知、或存在环
    """
    by_id: dict[str, SubTask] = {}
    for t in tasks:
        if not t.id:
            raise PlanError("子任务 id 不能为空")
        if t.id in by_id:
            raise PlanError(f"子任务 id 重复：{t.id}")
        by_id[t.id] = t
    for t in tasks:
        for dep in t.depends_on:
            if dep not in by_id:
                raise PlanError(f"子任务 {t.id} 依赖了不存在的任务：{dep}")
            if dep == t.id:
                raise PlanError(f"子任务 {t.id} 不能依赖自己")

    done: set[str] = set()
    waves: list[list[SubTask]] = []
    remaining = list(tasks)
    while remaining:
        wave = [t for t in remaining if all(d in done for d in t.depends_on)]
        if not wave:
            raise PlanError("任务依赖存在循环：" + "、".join(t.id for t in remaining))
        waves.append(wave)
        done.update(t.id for t in wave)
        remaining = [t for t in remaining if t.id not in done]
    return waves


def resolve_refs(arguments: dict, results: dict[str, TaskResult]) -> dict:
    """把入参里的 `$taskId` / `$taskId.field` 替换成前序任务的产出。

    引用不到（任务不存在 / 失败 / 字段缺失）时给 None —— 由工具的入参校验去报错，
    编排器不做「猜一个默认值」这种事。
    """
    return {key: _resolve_value(value, results) for key, value in arguments.items()}


def _resolve_value(value, results: dict[str, TaskResult]):
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    ref = value[1:]
    task_id, _, path = ref.partition(".")
    r = results.get(task_id)
    if r is None or not r.ok:
        return None
    data = r.data
    if path:
        return data.get(path) if isinstance(data, dict) else None
    return data


@dataclass
class Event:
    """编排器产出的一个事件（供外部转成 SSE / 日志）。"""

    type: str
    data: dict


async def stream_run(invoke_tool, plan: list[SubTask], max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
                     rename: dict[str, str] | None = None) -> AsyncIterator[Event | list[TaskResult]]:
    """边跑边吐事件：产出 Event×N，最后产出 list[TaskResult]（执行完的结果）。

    编排器的 `on_event` 是同步回调（在子任务协程里触发），而调用方是 async generator、
    必须在产出侧 await。这里用队列把两者解耦 —— 否则事件只能等整份计划跑完再一起发，
    长计划下等于没有流式。
    """
    queue: asyncio.Queue[Event] = asyncio.Queue()
    orchestrator = Orchestrator(invoke_tool, max_concurrency=max_concurrency,
                                on_event=lambda t, d: queue.put_nowait(Event(t, d)))
    runner = asyncio.ensure_future(orchestrator.run(plan))
    while True:
        getter = asyncio.ensure_future(queue.get())
        await asyncio.wait({runner, getter}, return_when=asyncio.FIRST_COMPLETED)
        if getter.done():
            event = getter.result()
            yield Event(rename.get(event.type, event.type) if rename else event.type, event.data)
        else:
            getter.cancel()
        if runner.done() and queue.empty():
            break
    yield runner.result()  # 计划错误（PlanError）在此抛出，由调用方转成错误事件


class Orchestrator:
    """按计划并发执行多个子任务。"""

    def __init__(self,
                 invoke_tool,
                 max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
                 on_event=None):
        """
        @param invoke_tool `async (name, arguments) -> (ok, data, error)`
        @param max_concurrency 同层并发上限
        @param on_event 事件回调 (type, data)，供 SSE 流使用
        """
        self._invoke_tool = invoke_tool
        self._max_concurrency = max(1, int(max_concurrency or 1))
        self._on_event = on_event

    async def run(self, tasks: list[SubTask]) -> list[TaskResult]:
        """执行全部子任务，返回按**计划顺序**（而非完成顺序）排列的结果。"""
        waves = plan_waves(tasks)
        self._emit("task.planned", {"tasks": [{"id": t.id, "title": t.label(),
                                               "tool": t.tool, "dependsOn": t.depends_on}
                                              for t in tasks],
                                     "waves": len(waves),
                                     "maxConcurrency": self._max_concurrency})
        results: dict[str, TaskResult] = {}
        semaphore = asyncio.Semaphore(self._max_concurrency)

        for wave in waves:
            pending: list[SubTask] = []
            for t in wave:
                failed_dep = next((d for d in t.depends_on if not results[d].ok), None)
                if failed_dep is not None:
                    r = TaskResult(id=t.id, title=t.label(), ok=False, skipped=True,
                                   error=f"依赖的前序任务「{failed_dep}」未成功，已跳过"
                                         f"（不带着错误前提继续）")
                    results[t.id] = r
                    self._emit("task.skipped", {"id": t.id, "title": r.title,
                                                "tool": t.tool, "reason": r.error})
                    continue
                pending.append(t)

            if pending:
                gathered = await asyncio.gather(
                    *(self._run_one(t, results, semaphore) for t in pending),
                    return_exceptions=True,
                )
                for t, got in zip(pending, gathered):
                    if isinstance(got, BaseException):
                        results[t.id] = TaskResult(id=t.id, title=t.label(), ok=False,
                                                   error=f"{type(got).__name__}: {got}")
                        self._emit("task.completed",
                                   {"id": t.id, "title": t.label(), "tool": t.tool,
                                    "ok": False, "summary": str(got)})
                    else:
                        results[t.id] = got

        return [results[t.id] for t in tasks]

    async def _run_one(self, task: SubTask, results: dict[str, TaskResult],
                       semaphore: asyncio.Semaphore) -> TaskResult:
        started = time.perf_counter()
        args = resolve_refs(task.arguments, results)
        self._emit("task.started", {"id": task.id, "title": task.label(), "tool": task.tool,
                                    "arguments": args})
        async with semaphore:
            try:
                ok, data, error = await self._invoke_tool(task.tool or task.id, args)
            except Exception as exc:  # 单个任务失败不影响其它分支
                logger.warning("subtask %s failed: %s", task.id, exc)
                ok, data, error = False, None, f"{type(exc).__name__}: {exc}"
        duration = int((time.perf_counter() - started) * 1000)
        r = TaskResult(id=task.id, title=task.label(), ok=bool(ok), data=data,
                       error=error if not ok else None, duration_ms=duration)
        self._emit("task.completed", {"id": task.id, "ok": r.ok, "summary": r.summary(),
                                      "durationMs": duration})
        return r

    def _emit(self, event_type: str, data: dict) -> None:
        if self._on_event is not None:
            try:
                self._on_event(event_type, data)
            except Exception as exc:  # 事件回调失败不应中断执行
                logger.warning("orchestrator event callback failed: %s", exc)
