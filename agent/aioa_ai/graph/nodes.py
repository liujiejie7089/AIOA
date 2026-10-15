"""图的节点实现：把原 `agent_runtime.run()` 的线性循环拆成 4 个职责单一的节点。

对照关系（重建前后行为必须一致）：
  prepare  ← run() 开头：护栏 / 解析 provider / 合并专家配置 / 构造 messages / 拉工具 / KB 预检索
  agent    ← 循环内的「决策轮」：调模型、逐字产出 message.delta、解析 tool_calls
  tools    ← 循环内的「执行轮」：同层并发执行工具、产出 tool.call / tool.result、结果回注
  finalize ← run() 结尾：message.completed + run.completed

事件通过 `get_stream_writer()` 以 custom 流实时写出，由 facade 按到达顺序编号 seq——
顺序即图执行顺序，因此 message.delta 与 tool.* 的先后关系与重建前一致。
"""
from __future__ import annotations

import json
import logging
import time

import httpx
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from aioa_ai.config import settings
from aioa_ai.contracts import RunRequest
from aioa_ai.guard import WallClock, check_text_len
from aioa_ai.knowledge import retrieval
from aioa_ai.knowledge.kb import _citations_from_tool
from aioa_ai.llm import gateway
from aioa_ai.llm.upstream import UpstreamError, _post_non_stream, _post_stream
from aioa_ai.prompt.builder import build_messages
from aioa_ai.tools import ask_user as ask_user_tool
from aioa_ai.tools.client import MAX_TOOL_ROUNDS, ToolClient, ToolOutcome
from aioa_ai.tools.orchestrator import SubTask, stream_run

logger = logging.getLogger("aioa.ai.graph")


def _req(state: dict) -> RunRequest:
    """从状态还原 RunRequest。

    状态里存的是 dict（可序列化，见 state.py）；这里还原成模型对象，供各节点沿用
    原有的属性式访问（``req.text`` 等），避免把「dict 化」扩散到全部消费点。
    """
    raw = state["req"]
    return raw if isinstance(raw, RunRequest) else RunRequest.model_validate(raw)


def _hitl_enabled() -> bool:
    """HITL 开关的**唯一**判定点。

    用 ``getattr`` 兜底：本项目既有哨兵会把 ``aioa_ai.graph.nodes.settings`` 换成一个精简
    shim（只带它自己关心的字段），缺 ``agent_hitl`` 时按「关」处理 —— 与安全默认一致，
    也让「新增配置读取」不会把既有哨兵以 AttributeError 逼红。
    """
    return bool(getattr(settings, "agent_hitl", False))


def _emit(type_: str, data: dict) -> None:
    """把事件写进 custom 流（facade 负责编号 seq）。非流式上下文下静默降级。"""
    try:
        writer = get_stream_writer()
    except Exception:  # 不在流式上下文（如单测直接 ainvoke）：不产出事件，逻辑照跑
        return
    writer({"type": type_, "data": data})


def _clock(state: dict) -> WallClock:
    """从状态里的墙钟起点重建护栏对象（状态里只存 float，保证可序列化）。"""
    clock = WallClock()
    clock.started = float(state.get("started_at") or time.monotonic())
    return clock


def _parse_tool_calls(message: dict) -> list[dict]:
    """从 assistant message 提取 tool_calls：[{id,name,arguments(dict)}]。"""
    out: list[dict] = []
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        out.append({"id": call.get("id") or "", "name": fn.get("name") or "", "arguments": args})
    return out


# --------------------------------------------------------------------------- prepare

async def prepare(state: dict) -> dict:
    """准备阶段：护栏 → provider → 专家配置 → messages → 工具 → 知识库预检索。"""
    req = _req(state)
    check_text_len(req.text)
    started_at = time.monotonic()

    provider = gateway.resolve(req.model_ref)
    api_key = provider.api_key()
    if not api_key:
        _emit("error", {
            "code": "MODEL_PROVIDER_NOT_CONFIGURED",
            "message": f"provider '{provider.key}' 未配置 api_key（请设置环境变量 {provider.api_key_env}）",
            "retryable": False,
        })
        _emit("run.failed", {"reason": "provider not configured",
                             "error_code": "MODEL_PROVIDER_NOT_CONFIGURED"})
        return {"fatal": {"code": "MODEL_PROVIDER_NOT_CONFIGURED"}, "started_at": started_at}

    _emit("run.started", {"run_id": req.run_id, "conversation_id": req.conversation_id,
                          "model": provider.model, "gateway_key": provider.key})

    # 专家生效配置（方案 P4 / B5）：后端 resolve 后经 expert_settings 下发，
    # 温度/topK/threshold/检索模式/知识库范围/工具开关全部从这里取，不再硬编码。
    es = req.expert_settings or {}
    # 温度优先级：专家配置（会话级）> 模型配置（管理端）> 默认值 0.3
    temperature = float(es.get("temperature") or getattr(provider, "temperature", 0.3) or 0.3)
    top_k = int(es.get("topK") or 5)
    threshold = float(es.get("threshold") or 0.0)
    retrieval_mode = str(es.get("retrievalMode") or "hybrid")
    kb_scope = es.get("kbScope") or "ALL"
    enabled_tools = es.get("tools") or {}
    effective = {
        "model": provider.model,
        "temperature": temperature,
        "topK": top_k,
        "threshold": threshold,
        "retrievalMode": retrieval_mode,
        "kbScope": kb_scope,
        "tools": enabled_tools,
        "enabled": es.get("enabled", True),
    }

    messages = build_messages(req, getattr(provider, "max_context", 0) or 0)
    tool_client = ToolClient.from_request(req.user_token)
    tools = await tool_client.list_tools()

    # HITL：注入内置澄清工具（不由业务工具网关执行，命中即暂停等待用户选择）。
    # 只在开关打开时注入 —— 关闭时工具表与既有实现逐字节一致（零回归）。
    if _hitl_enabled():
        tools = [ask_user_tool.ASK_USER_TOOL] + list(tools)

    # 对话级知识库开关（KB）：由 Java 后端从 CreateRunRequest 透传，缺省视为 True。
    # False = 本次 run 完全不使用知识库（剔除检索工具，模型无法发起检索）；
    # True（或缺省）= 知识库可用且优先（进入工具循环前先做预检索并注入参考上下文）。
    kb_on = req.kb_on if req.kb_on is not None else True
    effective["kbOn"] = kb_on

    citations: list[dict] = []
    if not kb_on:
        tools = retrieval.strip_kb_tool(tools)
    elif tool_client.enabled and retrieval.has_kb_tool(tools):
        kb_block, kb_citations = await retrieval.pre_retrieve(
            tool_client, req.text, top_k, threshold, retrieval_mode, kb_scope)
        if kb_block and messages:
            messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + kb_block
        citations.extend(kb_citations)

    logger.info("run %s: history=%d turns, tools=%d, kbOn=%s, temperature=%s, topK=%s, mode=%s",
                req.run_id, len(req.history or []), len(tools), kb_on, temperature, top_k, retrieval_mode)

    return {
        "messages": messages,
        "tools": tools,
        "provider_key": provider.key,
        "provider_model": provider.model,
        "temperature": temperature,
        "search_params": (top_k, threshold, retrieval_mode, kb_scope),
        "effective": effective,
        "citations": citations,
        "started_at": started_at,
        "agent_rounds": 0,
        "content_parts": [],
        "tool_calls_log": [],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "fatal": None,
    }


# --------------------------------------------------------------------------- agent

async def agent(state: dict) -> dict:
    """决策轮：调模型（可流式），逐字产出 message.delta，解析 tool_calls。"""
    req = _req(state)
    clock = _clock(state)
    rounds = int(state.get("agent_rounds") or 0)
    allow_tools = rounds < MAX_TOOL_ROUNDS
    provider = gateway.resolve(req.model_ref)
    api_key = provider.api_key()
    temperature = float(state.get("temperature") or 0.3)
    messages = list(state.get("messages") or [])
    use_tools = (state.get("tools") or None) if allow_tools else None

    stream = bool(settings.agent_stream)
    content_parts = list(state.get("content_parts") or [])
    usage = dict(state.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0})

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        message: dict = {}
        u: dict = {}
        if stream:
            async for item in _post_stream(http, provider, api_key, messages, use_tools, temperature):
                if item[0] == "delta":
                    clock.check()
                    content_parts.append(item[1])
                    _emit("message.delta", {"text": item[1]})
                else:  # ("done", message, usage)
                    message, u = item[1], item[2]
        else:
            message, u = await _post_non_stream(http, provider, api_key, messages, use_tools, temperature)

    usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
    usage["completion_tokens"] += int(u.get("completion_tokens") or 0)

    calls = _parse_tool_calls(message)
    if not calls and not stream:
        # 非流式：该 message 即最终回答，本地切片为 delta（保持事件契约）
        content = str(message.get("content") or "")
        for ch in content:
            clock.check()
            _emit("message.delta", {"text": ch})
        content_parts.append(content)

    if calls:
        # 本轮是「要调工具 / 要追问」的轮次：assistant 消息在这里并入上下文。
        # tools 与 clarify 两个节点因此都**只追加工具结果**、不自行追加 assistant 消息，
        # 保证 assistant 消息只出现一次（否则会出现「同一 tool_calls 重复」的非法消息序列）。
        messages.append({"role": "assistant", "content": message.get("content"),
                         "tool_calls": message.get("tool_calls")})

    return {
        "agent_rounds": rounds + 1,
        "allow_tools": allow_tools,
        "pending_calls": calls,
        "content_parts": content_parts,
        "usage": usage,
        "messages": messages,
        # 记下本轮 assistant 原始消息（调试用；上下文注入已在上面的 messages 里完成）
        "_assistant_message": message,
    }


# --------------------------------------------------------------------------- tools

async def tools(state: dict) -> dict:
    """执行轮：同层并发执行本轮工具调用，产出 tool.call / tool.result，结果回注消息。"""
    # 防御性过滤：ask_user 是内置控制工具、不由业务网关执行（正常路由不会送到这里，
    # 但从 clarify 交回的「本轮其余调用」若混入也一律剔除，避免误打网关）。
    calls = [c for c in (state.get("pending_calls") or [])
             if not ask_user_tool.is_ask_user(c.get("name"))]
    clock = _clock(state)
    # 运行期对象不进状态（checkpointer 要求纯数据）：按入参重建工具客户端
    tool_client = ToolClient.from_request(_req(state).user_token)
    top_k, threshold, retrieval_mode, kb_scope = state["search_params"]
    parallel = bool(settings.agent_parallel_tools)
    max_concurrency = max(1, int(settings.agent_max_concurrency or 1))

    # assistant 消息已由 agent 节点并入上下文（见 nodes.agent）；此处只追加工具结果。
    messages = list(state.get("messages") or [])

    search_params = (top_k, threshold, retrieval_mode, kb_scope)
    tool_calls_log = list(state.get("tool_calls_log") or [])
    citations = list(state.get("citations") or [])

    outcomes: list[ToolOutcome] = []
    async for item in _run_tool_calls(calls, tool_client, search_params, parallel, max_concurrency):
        if item[0] == "event":
            clock.check()
            _emit(item[1], item[2])
        else:  # ("done", outcomes)
            outcomes = item[1]

    for call, outcome in zip(calls, outcomes):
        tool_calls_log.append({"name": outcome.name, "arguments": outcome.arguments, "ok": outcome.ok})
        seen = {x["docId"] for x in citations}
        citations.extend(c for c in _citations_from_tool(outcome.name, outcome)
                         if c["docId"] not in seen)
        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({"ok": outcome.ok,
                                   "data": None if outcome.data is None else outcome.data,
                                   "error": outcome.error}, ensure_ascii=False),
        })

    return {"messages": messages, "tool_calls_log": tool_calls_log,
            "citations": citations, "pending_calls": []}


async def _run_tool_calls(calls: list[dict], tool_client: ToolClient, search_params: tuple,
                          parallel: bool, max_concurrency: int):
    """执行一轮内的全部工具调用：产出 ("event", type, data)×N，末项 ("done", outcomes)。

    走编排器：彼此独立时并发执行（省等待），并发度有上限（不把业务网关打满）。
    parallel=False 时 max_concurrency=1，等价于原串行语义。
    """
    top_k, threshold, retrieval_mode, kb_scope = search_params
    subtasks = [
        # 检索类工具透传专家配置参数（真实生效），其他工具原样透传
        SubTask(id=call["id"] or f"call_{i}", tool=call["name"],
                arguments=retrieval.inject_search_params(call["name"], dict(call["arguments"]),
                                                         top_k, threshold, retrieval_mode, kb_scope))
        for i, call in enumerate(calls)
    ]

    async def invoke_tool(name: str, arguments: dict):
        outcome = await tool_client.invoke(name, arguments)
        return outcome.ok, outcome.data, outcome.error

    outcomes: list[ToolOutcome] = []
    async for item in stream_run(invoke_tool, subtasks,
                                 max_concurrency=1 if not parallel else max_concurrency,
                                 rename={"task.started": "tool.call",
                                         "task.completed": "tool.result",
                                         "task.skipped": "tool.result"}):
        if isinstance(item, list):  # 末项：编排结果（与 calls 同序）
            for sub, r in zip(subtasks, item):
                outcomes.append(ToolOutcome(name=sub.tool or sub.id, arguments=sub.arguments,
                                            ok=r.ok, data=r.data, error=r.error))
            break
        if item.type == "tool.call":
            yield ("event", "tool.call",
                   {"name": item.data.get("tool"), "arguments": item.data.get("arguments")})
        elif item.type == "tool.result":
            ok = item.data.get("ok")
            yield ("event", "tool.result",
                   {"name": item.data.get("tool"), "ok": bool(ok),
                    "summary": item.data.get("summary") if ok
                    else (item.data.get("reason") or item.data.get("summary"))})
    yield ("done", outcomes)


# --------------------------------------------------------------------------- clarify

async def clarify(state: dict) -> dict:
    """澄清轮：模型调用了 ``ask_user`` ⇒ 暂停等待用户选择，再带着答案继续。

    为什么必须是**独立节点**（不能塞进 tools 节点）
    -----------------------------------------------
    LangGraph ``interrupt()`` 的语义是：暂停时保存状态；**恢复时整个节点函数从头重跑**，
    并在当初 ``interrupt()`` 的位置返回用户的选择。若把中断塞进 tools 节点，恢复时同一轮里
    **已经执行过的其它工具会被再执行一遍**（有副作用的工具直接翻倍）—— 这正是
    `docs/50 §7` 的 **Q3 精确恢复**判据要防的事。
    所以这里只把 ask_user 交给本节点，且本节点**在做任何有副作用的动作之前就中断**，
    重跑成本恒为零。暂停态由 checkpointer 按 thread_id(=run_id) 落盘，恢复时取回。
    """
    calls = state.get("pending_calls") or []
    ask_call = next((c for c in calls if ask_user_tool.is_ask_user(c.get("name"))), None)
    if ask_call is None:                     # 正常不会发生（路由保证），兜底直接放行
        return {"pending_calls": calls}

    # —— 中断点之前：不做任何副作用（不调模型、不调工具、不发事件）。——
    # need_clarification 事件由 facade 在「观察到暂停」后统一发出，避免恢复重跑时重复发事件。
    spec = ask_user_tool.build_clarification(ask_call.get("arguments"))
    answer = interrupt(spec)                 # 首次执行：暂停于此；resume 后：返回用户的选择

    # —— 以下代码只在 resume 之后执行一次。——
    messages = list(state.get("messages") or [])   # assistant 消息已由 agent 节点并入
    messages.append({
        "role": "tool",
        "tool_call_id": ask_call.get("id") or "",
        "content": json.dumps({"ok": True, "data": {"answer": answer}}, ensure_ascii=False),
    })
    clarifications = list(state.get("clarifications") or [])
    clarifications.append({"question": spec.get("question"), "answer": answer})

    # 本轮若还夹带了其它（非 ask_user）调用，交回 tools 执行 —— 它们此前从未执行过，
    # 不会重复；反之直接回到 agent，让模型带着澄清答案继续。
    remaining = [c for c in calls if not ask_user_tool.is_ask_user(c.get("name"))]
    return {"messages": messages, "pending_calls": remaining, "clarifications": clarifications}


# --------------------------------------------------------------------------- finalize

async def finalize(state: dict) -> dict:
    """收尾：产出 message.completed + run.completed。"""
    content = "".join(state.get("content_parts") or [])
    tool_calls_log = list(state.get("tool_calls_log") or [])
    usage = dict(state.get("usage") or {})

    if not content and tool_calls_log:
        # 工具轮数用尽仍未产出正文：汇总已获取的数据直接作答（与原行为一致）
        content = "已完成的工具查询结果：\n" + "\n".join(
            f"· {c['name']}：{'成功' if c['ok'] else '失败'}" for c in tool_calls_log)
        for ch in content:
            _emit("message.delta", {"text": ch})

    _emit("message.completed", {
        "content": content,
        "citations": state.get("citations") or [],
        "tool_calls": tool_calls_log,
        "usage": usage,
        "effective_params": state.get("effective") or {},
    })
    _emit("run.completed", {"status": "SUCCEEDED", "usage": usage})
    return {}


# --------------------------------------------------------------------------- routing

def route_after_prepare(state: dict) -> str:
    """prepare 之后：致命错误直接结束，否则进入决策轮。"""
    return "end" if state.get("fatal") else "agent"


def route_after_agent(state: dict) -> str:
    """agent 之后：含 ask_user 且 HITL 已开 ⇒ 先澄清；否则有工具调用且未达上限 ⇒ 执行工具；否则收尾。

    ``ask_user`` 的分支必须同时看开关：关闭时模型本不该拿到该工具，但若它（或因缓存/伪造）
    仍返回了同名调用，绝不能进 ``clarify`` —— 那里会 ``interrupt()``，而关闭态没有
    checkpointer，会直接抛错。开关必须是唯一权威。
    """
    calls = state.get("pending_calls") or []
    if _hitl_enabled() and any(ask_user_tool.is_ask_user(c.get("name")) for c in calls):
        return "clarify"
    if calls and state.get("allow_tools"):
        return "tools"
    return "finalize"


def route_after_clarify(state: dict) -> str:
    """澄清之后：本轮若还夹带其它工具调用 → 去执行；否则带着答案回到 agent 继续跑。"""
    return "tools" if state.get("pending_calls") else "agent"
