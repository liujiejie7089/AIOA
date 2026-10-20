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

from aios_ai.config import settings
from aios_ai.contracts import RunRequest
from aios_ai.guard import WallClock, check_text_len
from aios_ai.intent import intake as worker_intake
from aios_ai.knowledge import retrieval
from aios_ai.knowledge.kb import _citations_from_tool
from aios_ai.llm import gateway
from aios_ai.llm.upstream import UpstreamError, _post_non_stream, _post_stream
from aios_ai.prompt.builder import build_messages
from aios_ai.tools import ask_user as ask_user_tool
from aios_ai.tools import request_form as request_form_tool
from aios_ai.tools.client import MAX_TOOL_ROUNDS, ToolClient, ToolOutcome
from aios_ai.tools.orchestrator import SubTask, stream_run

logger = logging.getLogger("aios.ai.graph")

# 「有动作意图」的轮次下必须对模型隐藏的写操作工具。名称与 Java 侧
# `PermissionGrantToolHandler.TOOL_APPLY` 保持一致（该工具是 V36 需求①「用户通过 AI 提交申请」的入口）。
#
# 为什么是**这一件事**而不是某几个动作：`detect_action` 只可能返回 `_ACTION_RULES` 里的码
# （UPLOAD_FILE / REPORT_EXPENSE / CREATE_WORKER / APPLY_LEAVE），而这四个动作的**确认入口都在界面**
# （由 H5 打开窗口/卡片，用户点了才算数）。所以「本轮有动作意图」≡「界面拥有确认权」⇒ 模型不得写。
#
# 只拦 `apply_permission` 一个：这条链上外部工具只有两个 Bean —— `apply_permission`（**写**）
# 与 `list_my_permission_grants`（**读**）。读工具**必须保留**（模型要能回答「我申请到哪一步了」），
# 所以这里是白名单式地剔一个，不是按前缀扫。
_BLOCKED_WRITE_TOOL_ON_ACTION_INTENT = "apply_permission"

# 工具清单拉取失败时追加到 system 的降级声明（2026-10-18）。
# 为什么不直接让 run 失败：网关一次抖动不该把整轮问答打死；但**绝不能静默**——
# 旧行为是返回 [] 后照常推理，用户得到一段「看起来查过资料」的回答。
KB_DEGRADED_NOTE = (
    "\n\n【本轮知识库不可用】工具网关本轮拉取失败，你**没有**任何检索工具可用。"
    "若回答需要内部资料（制度、流程、数据、文件），必须明确说明「本轮未能检索到内部资料」，"
    "禁止虚构制度条款、数字或来源。"
)

# MCP 连接器（邮箱 / 企业微信等）拉取失败时追加到 system 的降级声明（契约 docs/59 §10.4 判据 4）。
# 与 KB_DEGRADED_NOTE 同口径：hub 抖动不该打死整轮，但**绝不能静默**——
# 旧行为是返回 [] 后照常推理，模型会假装查过邮件/企微消息，用户得到一段编造的连接器结果。
MCP_DEGRADED_NOTE = (
    "\n\n【本轮连接器不可用】MCP 连接器服务（邮箱 / 企业微信等）本轮拉取失败，你**没有**任何连接器工具可用。"
    "若用户询问邮件、企业微信等连接器相关事宜，必须如实说明「连接器服务暂时不可用，我无法查询」，"
    "禁止假装已查询、禁止编造邮件内容或消息记录。"
)


def _tool_name(t: dict) -> str | None:
    """工具名提取（兼容两种 schema 形态，与 knowledge.retrieval 同口径）。"""
    return t.get("function", {}).get("name") or t.get("name")


def filter_intent_write_tools(tools: list[dict], action: str | None) -> list[dict]:
    """按动作意图收敛写工具（**纯函数**，便于单测与被测面直接引用）。

    本轮有动作意图（``action`` 非 None）⇒ 界面是唯一确认入口 ⇒ 剔除写工具。
    ``action is None``（普通对话）时**原样返回**，保证零回归。
    """
    if action is None:
        return tools
    return [t for t in tools if _tool_name(t) != _BLOCKED_WRITE_TOOL_ON_ACTION_INTENT]


def filter_expert_tools(tools: list[dict], expert: dict | None, scope: dict | None) -> list[dict]:
    """专家会话（有 expert、无 scope）不向模型暴露 request_form。

    专家 AI 是「顾问」不是「办事员」：它该用文字澄清与给意见，业务表单是**数字员工**的能力。
    实测缺陷（2026-10-18）：法律专家被问「试用期最长多久」，模型调 request_form 弹出了
    「合同起草」表（别的数字人的表），正文为空 —— 用户既没拿到法律意见，还看到一张莫名其妙的表。
    与 filter_intent_write_tools 同口径：这是**确定性**闸（不给工具），不是提示词软约束；
    绑了数字员工（scope 非空）的会话**原样返回**，保证办理类会话零回归。
    """
    if not expert or scope:
        return tools
    return [t for t in tools if _tool_name(t) != request_form_tool.REQUEST_FORM_TOOL_NAME]


def _req(state: dict) -> RunRequest:
    """从状态还原 RunRequest。

    状态里存的是 dict（可序列化，见 state.py）；这里还原成模型对象，供各节点沿用
    原有的属性式访问（``req.text`` 等），避免把「dict 化」扩散到全部消费点。
    """
    raw = state["req"]
    return raw if isinstance(raw, RunRequest) else RunRequest.model_validate(raw)


def _hitl_enabled() -> bool:
    """HITL 开关的**唯一**判定点。

    用 ``getattr`` 兜底：本项目既有哨兵会把 ``aios_ai.graph.nodes.settings`` 换成一个精简
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

    # MCP 连接器独立通道（契约 docs/59 §10）：manifest 不可达时内部已吞异常，
    # 失败通过 tool_client.mcp_error 反映，工具表与改造前逐字节一致（关闭开关时整段不进入）。
    # 关闭 mcp_hub_enabled 时不连 hub、不发 manifest 请求 ⇒ tools 与既有实现完全相同。
    mcp_tools = await tool_client.list_mcp_tools()
    if mcp_tools:
        tools = list(mcp_tools) + list(tools)
    mcp_degraded = bool(settings.mcp_hub_enabled and tool_client.enabled and tool_client.mcp_error)
    if mcp_degraded:
        effective["mcpDegraded"] = True
        if messages:
            messages[0]["content"] = (messages[0].get("content") or "") + MCP_DEGRADED_NOTE
        logger.error("run %s: MCP 连接器清单不可用（%s）⇒ 本轮连接器工具不可用，已在提示中显式降级",
                     req.run_id, tool_client.mcp_error)

    # HITL：注入内置澄清工具（不由业务工具网关执行，命中即暂停等待用户选择）。
    # 只在开关打开时注入 —— 关闭时工具表与既有实现逐字节一致（零回归）。
    if _hitl_enabled():
        # 两个内置控制工具都在此注入：ask_user（标量澄清）/ request_form（表单请求）。
        # 二者都不由业务网关执行，命中即暂停等待用户选择/填表。关闭时工具表与既有实现逐字节一致。
        tools = [ask_user_tool.ASK_USER_TOOL, request_form_tool.REQUEST_FORM_TOOL] + list(tools)

    # 对话级知识库开关（KB）：由 Java 后端从 CreateRunRequest 透传，缺省视为 True。
    # False = 本次 run 完全不使用知识库（剔除检索工具，模型无法发起检索）；
    # True（或缺省）= 知识库可用且优先（进入工具循环前先做预检索并注入参考上下文）。
    kb_on = req.kb_on if req.kb_on is not None else True
    effective["kbOn"] = kb_on

    # ★ 知识库静默消失的防线（2026-10-18）：工具清单拉取失败时，`list_tools()` 返回 [] 与
    #   「用户确实没有工具」在旧实现里不可区分 ⇒ `has_kb_tool([])` 为假 ⇒ 预检索整段不跑、
    #   run 照样 SUCCESS —— 用户看到「AI 没查资料就答了」，且日志里只有一行 warning。
    #   现在 list_tools 记录失败原因，这里据此**显式告知模型**，让它如实说明本轮未检索到内部资料，
    #   而不是用参数记忆编制度条款。同时把 kbDegraded 带进 effective_params 便于追查。
    kb_degraded = bool(kb_on and tool_client.enabled and tool_client.list_error)
    if kb_degraded:
        effective["kbDegraded"] = True
        if messages:
            messages[0]["content"] = (messages[0].get("content") or "") + KB_DEGRADED_NOTE
        logger.error("run %s: 工具清单拉取失败（%s）⇒ 本轮知识库不可用，已在提示中显式降级",
                     req.run_id, tool_client.list_error)

    citations: list[dict] = []
    if not kb_on:
        tools = retrieval.strip_kb_tool(tools)
    elif tool_client.enabled and retrieval.has_kb_tool(tools):
        kb_block, kb_citations = await retrieval.pre_retrieve(
            tool_client, req.text, top_k, threshold, retrieval_mode, kb_scope)
        if kb_block and messages:
            messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + kb_block
        citations.extend(kb_citations)

    # 铁律 1（docs/51 §1.4 / §1.7）：有动作意图的轮次，确认入口在**界面** —— 用户点了才算数。
    # 提示词只是**软**约束（模型可以不遵守），而同一类缺陷已实测复现两次
    # （CREATE_WORKER 记为 D3、APPLY_LEAVE 本轮复现），故这里补一道**确定性**闸门：
    # 本轮干脆不把申请权限工具暴露给模型，模型即使「想」抢先落库也**无工具可调**。
    # 判别力（为什么不会误伤 V36）：显式申请诉求「请帮我提交 approval:leave 权限申请」**不**判为
    # 任何动作（见 intake 的窄口径规则）⇒ action=None ⇒ 本闸门不触发，工具照常暴露、照常可调。
    tools = filter_intent_write_tools(tools, worker_intake.detect_action(req.text))

    # V88 专家会话（有 expert、无 scope）不暴露 request_form：业务表单是数字员工的能力，
    # 专家 AI 该用文字澄清与给意见，弹表单会把咨询当成办理（实测法律专家弹「合同起草」表、正文为空）。
    # 这是确定性闸（不给工具），绑了数字员工（scope 非空）的办理类会话原样返回，零回归。
    tools = filter_expert_tools(tools, req.expert, req.scope)

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

    # —— 确定性开表（Java 判定，agent 只执行）——
    # 触发条件：模型这一轮**没有**任何工具调用、本轮也还没有过澄清/表单回执
    # （`clarifications` 为空 ⇒ 不是续跑后的第二轮），而后端下发了 `form_hint`
    # （该数字人只绑一张表 + 用户原话点名了这项任务）。
    # 为什么必须在**图里**开表：`request_form` 的语义是走到 `clarify` 节点 `interrupt()`，
    # 只有 `interrupt()` 才会把挂起态写进 checkpointer；若改由后端在流末补发一帧，
    # 图里没有断点，用户提交表单后 /resume 无从恢复（实测表现为续跑零帧、模型不再确认）。
    if (not calls and _hitl_enabled() and not (state.get("clarifications") or [])):
        hint = (state.get("req") or {}).get("form_hint") or {}
        hint_code = hint.get("form_code") if isinstance(hint, dict) else None
        if hint_code:
            hint_args: dict[str, Any] = {"form_code": hint_code}
            if hint.get("reason"):
                hint_args["reason"] = hint["reason"]
            # 两种表示不能混：状态里的 pending_calls 是**归一化**形状 {id,name,arguments(dict)}
            # （见 _parse_tool_calls / tools 节点），而回注上下文的消息必须是 OpenAI 的
            # tool_calls 形状（function.name / function.arguments 字符串）。
            calls = [{"id": "call_form_hint_1", "name": "request_form",
                      "arguments": hint_args}]
            messages.append({"role": "assistant", "content": message.get("content"),
                             "tool_calls": [{
                                 "id": "call_form_hint_1",
                                 "type": "function",
                                 "function": {
                                     "name": "request_form",
                                     "arguments": json.dumps(hint_args, ensure_ascii=False),
                                 },
                             }]})

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
    # 防御性过滤：ask_user / request_form 都是内置控制工具、不由业务网关执行（正常路由
    # 不会送到这里，但从 clarify 交回的「本轮其余调用」若混入也一律剔除，避免误打网关）。
    calls = [c for c in (state.get("pending_calls") or [])
             if not ask_user_tool.is_ask_user(c.get("name"))
             and not request_form_tool.is_request_form(c.get("name"))]
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
    """澄清轮：模型调用了内置控制工具（``ask_user`` 或 ``request_form``）⇒ 暂停等待用户，再带着答案继续。

    为什么必须是**独立节点**（不能塞进 tools 节点）
    -----------------------------------------------
    LangGraph ``interrupt()`` 的语义是：暂停时保存状态；**恢复时整个节点函数从头重跑**，
    并在当初 ``interrupt()`` 的位置返回用户的选择。若把中断塞进 tools 节点，恢复时同一轮里
    **已经执行过的其它工具会被再执行一遍**（有副作用的工具直接翻倍）—— 这正是
    `docs/50 §7` 的 **Q3 精确恢复**判据要防的事。
    所以这里只把内置控制调用交给本节点，且本节点**在做任何有副作用的动作之前就中断**，
    重跑成本恒为零。暂停态由 checkpointer 按 thread_id(=run_id) 落盘，恢复时取回。

    两条控制链（ask_user / request_form）共用 interrupt/resume/checkpoint 底座，不新建状态机：
    仅按工具类型选择归一化函数与 spec 形状。request_form 的 spec 带 ``kind="form"`` 标记，
    供 facade 的 ``_frame_type`` 区分发 ``need_form`` 还是 ``need_clarification``。
    ask_user 的 spec 维持历史形状（仅 ``question`` / ``suggested_options``），前端零改动。
    """
    calls = state.get("pending_calls") or []
    # 找出内置控制调用：ask_user 或 request_form（两种都走 interrupt 暂停）。二者互斥取首个。
    ctrl_call = next((c for c in calls
                      if ask_user_tool.is_ask_user(c.get("name"))
                      or request_form_tool.is_request_form(c.get("name"))), None)
    if ctrl_call is None:                     # 正常不会发生（路由保证），兜底直接放行
        return {"pending_calls": calls}

    name = ctrl_call.get("name")
    is_form = request_form_tool.is_request_form(name)
    if is_form:
        spec = request_form_tool.build_form_request(ctrl_call.get("arguments"))
    else:
        spec = ask_user_tool.build_clarification(ctrl_call.get("arguments"))
    if spec is None:
        # 归一化失败（request_form 缺 form_code 等）：不当作有效内置调用，剔除后放行、不暂停。
        # 避免把「无效控制调用」再喂回模型造成空转。
        remaining = [c for c in calls
                     if not ask_user_tool.is_ask_user(c.get("name"))
                     and not request_form_tool.is_request_form(c.get("name"))]
        return {"pending_calls": remaining}

    # —— 中断点之前：不做任何副作用（不调模型、不调工具、不发事件）。——
    # 暂停事件由 facade 在「观察到暂停」后统一发出，避免恢复重跑时重复发事件。
    answer = interrupt(spec)                 # 首次执行：暂停于此；resume 后：返回用户的答案/回执

    # —— 以下代码只在 resume 之后执行一次。——
    messages = list(state.get("messages") or [])   # assistant 消息已由 agent 节点并入
    messages.append({
        "role": "tool",
        "tool_call_id": ctrl_call.get("id") or "",
        "content": json.dumps({"ok": True, "data": {"answer": answer}}, ensure_ascii=False),
    })
    clarifications = list(state.get("clarifications") or [])
    if is_form:
        # 表单回执是对象（{form_code, submission_id, status, data, receipt}），同样可 JSON 序列化。
        clarifications.append({"form_code": spec.get("form_code"), "answer": answer})
    else:
        clarifications.append({"question": spec.get("question"), "answer": answer})

    # 本轮若还夹带了其它（非内置控制）调用，交回 tools 执行 —— 它们此前从未执行过，
    # 不会重复；反之直接回到 agent，让模型带着答案继续。两种控制调用都需从余量里剔除。
    remaining = [c for c in calls
                if not ask_user_tool.is_ask_user(c.get("name"))
                and not request_form_tool.is_request_form(c.get("name"))]
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
    """agent 之后：含 ask_user / request_form 且 HITL 已开 ⇒ 先澄清；否则有工具调用且未达上限 ⇒ 执行工具；否则收尾。

    两条内置控制链（ask_user / request_form）都走 ``clarify`` 节点。分支必须同时看开关：
    关闭时模型本不该拿到这些工具，但若它（或因缓存/伪造）仍返回了同名调用，绝不能进
    ``clarify`` —— 那里会 ``interrupt()``，而关闭态没有 checkpointer，会直接抛错。
    开关必须是唯一权威。
    """
    calls = state.get("pending_calls") or []
    if _hitl_enabled() and any(
        ask_user_tool.is_ask_user(c.get("name"))
        or request_form_tool.is_request_form(c.get("name"))
        for c in calls
    ):
        return "clarify"
    if calls and state.get("allow_tools"):
        return "tools"
    return "finalize"


def route_after_clarify(state: dict) -> str:
    """澄清之后：本轮若还夹带其它工具调用 → 去执行；否则带着答案回到 agent 继续跑。"""
    return "tools" if state.get("pending_calls") else "agent"
