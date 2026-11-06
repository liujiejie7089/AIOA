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
import re
import time

import httpx
from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from aios_ai import capabilities
from aios_ai import aggregate as aggregate_tool
from aios_ai.config import settings
from aios_ai.contracts import RunRequest
from aios_ai.guard import WallClock, check_text_len
from aios_ai.intent import intake as worker_intake
from aios_ai.intent import leave_apply as leave_apply_tool
from aios_ai.knowledge import retrieval
from aios_ai.knowledge.kb import _citations_from_tool
from aios_ai.llm import gateway
from aios_ai.llm.upstream import UpstreamError, _post_non_stream, _post_stream
from aios_ai.prompt.builder import build_messages
from aios_ai.tools import ask_user as ask_user_tool
from aios_ai.tools import entity_clarify as entity_clarify_tool
from aios_ai.tools import request_confirm as request_confirm_tool
from aios_ai.tools import request_form as request_form_tool
from aios_ai.tools import web_search as web_search_tool
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


# --------------------------------------------------------------------------- 内置控制工具（HITL 三条链）
#
# ask_user / request_form / request_confirm 三条链共用 interrupt/resume/checkpoint 底座。
# 它们的共同点是**不由业务工具网关执行**、命中即暂停 —— 于是「判断某个调用是不是控制调用」
# 这个命题会在 prepare（注入）/ tools（防御性过滤）/ clarify（识别）/ 路由（分支）四处重复出现。
# 先前每加一条链就要改四个地方各加一个 `or`（2026-10-31 加 request_confirm 时已经是第三次），
# 漏一处就会出现「新工具被当成业务工具打进网关」这类静默错。故收敛成下面三个单点判定函数。

def _is_control_call(name: str | None) -> bool:
    """该工具名是否为内置控制工具（三条 HITL 链之一）。"""
    return (ask_user_tool.is_ask_user(name)
            or request_form_tool.is_request_form(name)
            or request_confirm_tool.is_request_confirm(name))


def _control_chain(name: str | None) -> str:
    """控制链代号：``"form"`` / ``"confirm"`` / ``"clarify"``；非控制调用返回 ``""``。"""
    if request_form_tool.is_request_form(name):
        return "form"
    if request_confirm_tool.is_request_confirm(name):
        return "confirm"
    if ask_user_tool.is_ask_user(name):
        return "clarify"
    return ""


def _drop_control_calls(calls: list[dict] | None) -> list[dict]:
    """剔除内置控制调用后的余量。

    两处语义相同、但**原因不同**，别写成两个函数导致将来只改一处：
      - tools 节点：防御性过滤（路由本不该送到这里，但状态里混进来也不能误打网关）；
      - clarify 节点：本轮控制调用已被本节点消费，余下的普通调用交回 tools 执行。
    """
    return [c for c in (calls or []) if not _is_control_call(c.get("name"))]


def _connector_of_tool_name(name: str | None) -> str:
    """从 MCP 工具名解析连接器 code。

    工具名形如 ``mcp__<serverCode>__<toolName>``；非 MCP 工具返回空串。
    """
    parts = str(name or "").split("__")
    return parts[1] if len(parts) >= 3 and parts[0] == "mcp" else ""


def _blocked_connector_calls(calls: list[dict] | None,
                              disabled: list[str] | None) -> list[dict]:
    """挑出「本次对话已屏蔽连接器」的工具调用（**纯函数**，便于单测）。

    对话级连接器开关（2026-10-31，用户口径「关闭只是本次对话不调用对应应用」）
    的第二道闸：prepare 已把这些连接器的工具从清单里摘掉，
    但模型可能凭记忆硬编出工具名 ⇒ 执行前再拦一次。

    ⚠️ 返回的是「被拦下的调用」而不是「保留的调用」：调用方要把它们从执行队列里
    排除，但**仍要回注一条 ok=False 的 tool 结果**（丢弃会让 tool_call_id 找不到
    对应的 tool 消息，上游会判为协议错误）。
    """
    blocked_codes = {str(c).strip() for c in (disabled or []) if str(c).strip()}
    if not blocked_codes:
        return []
    return [c for c in (calls or [])
            if _connector_of_tool_name(c.get("name")) in blocked_codes]


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


def strip_form_for_aggregate(tools: list[dict]) -> list[dict]:
    """跨源汇总轮次不向模型暴露 request_form。

    实测（2026-11-03）：用户说「总结一下我这周的工作，写个周报」，`intake` 判成公文起草意图，
    模型于是调 request_form 弹了一张「工作报告」表单 —— 用户要的是**已经发生的事的汇总**，
    不是要填一张空表。表现是：跑了 5 个源的数据一条没用上，界面只出现一张表。

    与 filter_expert_tools 同口径：不确定的行为就用**不给工具**来保证，
    而不是在提示词里写「不要弹表单」（那是软约束，实测挡不住）。
    仅当本轮**确实完成了聚合**时才剥离（由调用方判断），普通办理类会话零影响。
    """
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


# 单条工具结果的摘要长度上限。历史回灌时每条都带，太长会把 prompt 撑爆
# （10 条历史 × 每个结果几十 KB 是真实发生过的），240~600 字符足够装下
# `chat_id` / `mail_id` / 文件名这类「下一轮还要用」的标识。
_TOOL_DIGEST_CHARS = 600


def _tool_digest(data) -> str:
    """把工具返回压成一句**能续用标识**的短摘要，随 tool_calls 一起回传并落库。

    为什么需要：`tool_calls_log` 原先只有 `{name, arguments, ok}`，**结果是丢的**。
    而 `RunService.loadHistory` 回灌历史时只带 role+content ⇒ 模型上一轮明明查到过
    `chat_id`，这一轮却拿不到，只能把**群名**当 chat_id 硬传 ⇒ 企微回
    `40073 非法的 'chat_id'`，模型随即对用户说「我无法获取具体消息」。
    （2026-10-31 会话 1436 第 3→5 轮实测；docs/64 §9.10）

    只保留标识类信息，不做语义加工：摘要原样截断，避免把工具结果「改写」出事实错误。
    """
    if data is None:
        return ""
    try:
        text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return ""
    text = " ".join(str(text).split())
    return text[:_TOOL_DIGEST_CHARS]


# 代码块里的「调用表达式」：```typescript\nfunctions.mcp__x__y({"k": 1})\n```
# 语言标记可有可无，`functions.` 前缀可能有也可能没（MiniMax 两种都写过）。
_FENCE_BLOCK_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_CALL_EXPR_RE = re.compile(r"^\s*(?:functions\.)?([A-Za-z_][\w.]*)\s*\((.*)\)\s*;?\s*$", re.S)
# 「正在查询」类承诺句：只用于 finalize 的可观测性告警（零工具调用却这么说话 = 界面会停住）
_PROMISE_RE = re.compile(r"请稍等|稍候|正在(为你|为您)?(查询|检索|查看|整理|读取)|马上为你")

# 「把工具调用写成正文」的**特征串**：一旦在正文里出现，这一轮的正文就不再外发给用户。
# 2026-10-30 实测两种形态：
#   <function_call>```typescript\nmcp__wecom_cli__whoami({})\n```</function_call>
#   ```typescript\nfunctions.mcp__wecom_cli__recent_group_sessions({"days": 7})\n```
# 救援逻辑（_rescue_textual_calls）只负责「让调用真的执行」，**不会**把这段原文收回去 ——
# 于是用户既收到了原始调用文本、又真的查了一遍。判据放这里，两者才闭环。
# 只认「调用形态」而不认裸 ``` ：正常回答里的代码块必须照常显示。
_CALL_TEXT_SIG_RE = re.compile(
    r"<function_call|<tool_call|\bfunctions\.[A-Za-z_]\w*\s*\(|\bmcp__\w+\s*\(|\b[A-Za-z_]\w*__\w[\w.]*\s*\(",
    re.I)
_TAG_CALL_RE = re.compile(r"<function_call>.*?</function_call>", re.S | re.I)
# 流式期间先攒够这么多字符再决定发不发（够看出是不是调用文本，又不至于让用户等太久）
_STREAM_HOLD = 40
# 正文开头**可能是**调用表达式的前缀：只有这种开头才暂扣，普通中文/英文照常逐片下发。
# 不这么做的话所有回答都会被攒成一大段再吐（实测会把「你好」「世界」两片合成一片，
# 破坏 message.delta 与上游分片的一对一契约，前端打字机效果也跟着变）。
_CALL_START_RE = re.compile(r"^(?:`|<|functions\.|mcp__|[A-Za-z_][\w]*__?)")


def _looks_like_call_start(text: str) -> bool:
    t = (text or "").lstrip()
    if not t:
        return True                      # 只有空白，再等等
    return bool(_CALL_START_RE.match(t))


def _strip_call_text(text: str) -> str:
    """把正文里的工具调用文本删干净（保留调用之外的叙述）。"""
    if not text:
        return text
    out = _TAG_CALL_RE.sub("", text)
    # 模型有时只写开标签、忘了闭合（实测 <function_call> 后面直接跟正文），
    # 成对正则匹配不到，得单独把游离标签扫掉，否则用户会看到「<function_call>我这边没有…」。
    out = re.sub(r"</?(?:function_call|tool_calls?|invoke)\s*>", "", out, flags=re.I)

    def _drop(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        expr = _CALL_EXPR_RE.match(inner)
        if not expr:
            return m.group(0)
        # 只删「工具形状」的调用：带 `functions.` 前缀，或 MCP 的双下划线命名。
        # 否则 `print(1)` 这种普通代码也会命中 _CALL_EXPR_RE 被整块删掉 ——
        # 用户要的示例代码就这么没了（本文件的回归测试专门守着这条）。
        name = (expr.group(1) or "").strip()
        is_tool_call = inner.startswith("functions.") or "__" in name
        return "" if is_tool_call else m.group(0)

    out = _FENCE_BLOCK_RE.sub(_drop, out)
    # 裸写一行的调用表达式（没有代码块包裹）：整行删掉，别留在答案里
    out = re.sub(r"(?m)^[ \t]*(?:functions\.)?[A-Za-z_][\w]*(?:__|\.)[\w.]*\s*\(.*\)[ \t]*;?[ \t]*$",
                 "", out)
    return out.strip()


def _rescue_textual_calls(content: str, allowed_names: set[str], limit: int = 4) -> list[dict]:
    """把模型**写成正文**的工具调用还原成真正的 tool_calls。

    现场（2026-10-30，用户截图「一起停留在查询界面」）：MiniMax-Text-01 偶尔不把调用放进
    `tool_calls` 字段，而是当正文写出来：

        ```typescript
        functions.mcp__wecom_cli__recent_group_sessions({"days": 7})
        ```

    于是 `_parse_tool_calls` 返回空 ⇒ 这一轮被当成「最终回答」⇒ 模型那句
    「请稍等，我正在为您查询这些信息。」变成答案直接收尾，工具**一次都没执行**，
    界面就永远停在「正在查询」。同一形态在 2026-10-21 的 QQ 邮箱链路上也出现过
    （`chat_message.id=2513` 的 `functions.mcp__qq_mail__send_draft(...)` 同样没被执行）。

    安全边界（**错救比不救更糟**，所以收得很紧）：
      ① 只认**代码块**里、整块**只有一个调用表达式**的情形；正文里顺口提到的 `foo()` 不动；
      ② 名字必须**精确命中**本轮真的下发给模型的工具名，否则丢弃（防模型"发明"工具）；
      ③ 参数必须是合法 JSON **对象**，解析不了就丢弃 —— 不猜、不补默认值。
    """
    out: list[dict] = []
    for block in _FENCE_BLOCK_RE.findall(content or ""):
        m = _CALL_EXPR_RE.match(block.strip())
        if not m:
            continue
        name = (m.group(1) or "").strip()
        if name not in allowed_names:
            continue
        raw_args = (m.group(2) or "").strip()
        if raw_args:
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                continue
            if not isinstance(args, dict):
                continue
        else:
            args = {}
        out.append({"id": "call_rescue_%d" % (len(out) + 1),
                    "name": name, "arguments": args})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- prepare

async def prepare(state: dict) -> dict:
    """准备阶段：护栏 → provider → 专家配置 → messages → 工具 → 知识库预检索。"""
    req = _req(state)
    check_text_len(req.text)
    started_at = time.monotonic()

    provider = gateway.resolve(req.model_ref, credential=req.model_credential)
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
    # 阈值：显式配置优先（含显式 0——运营在管理端配了就尊重），未配置时用保守默认
    # （docs/60 P0-3a）。旧实现 `or 0.0` 把「没配」和「配了 0」混为一谈，问候语都能
    # 拖出 0 分命中。
    _raw_threshold = es.get("threshold")
    threshold = (float(_raw_threshold)
                 if _raw_threshold is not None and str(_raw_threshold).strip() != ""
                 else retrieval.DEFAULT_KB_THRESHOLD)
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

    # —— 对话级「本次不调用某连接器」开关（2026-10-31）——
    # 语义：**只屏蔽本次对话的工具**，不改任何持久状态（授权 / trusted / manifest 可见性都不动）
    # ⇒ 用户把开关关掉再打开，不需要重新扫码（与旧的「关闭=disconnect」最本质的区别）。
    # 过滤按工具的 source（= 连接器 code）匹配；MCP 工具名形如 mcp__<serverCode>__<tool>，
    # source 与 serverCode 同源，两者都判一次，避免 manifest 未带 source 时漏筛。
    disabled_connectors = {
        str(c).strip() for c in (req.disabled_connectors or []) if str(c).strip()
    }
    if disabled_connectors and mcp_tools:
        def _connector_of(t: dict) -> str:
            src = str(t.get("source") or "").strip()
            if src:
                return src
            return _connector_of_tool_name(((t.get("function") or {}).get("name")))

        kept = [t for t in mcp_tools if _connector_of(t) not in disabled_connectors]
        if len(kept) != len(mcp_tools):
            logger.info("run %s: 本次对话屏蔽连接器 %s ⇒ MCP 工具 %d → %d",
                        req.run_id, sorted(disabled_connectors),
                        len(mcp_tools), len(kept))
        mcp_tools = kept
    # 观测：让 Run 日志能解释「为什么模型没看到某个连接器的工具」
    if disabled_connectors:
        effective["disabledConnectors"] = sorted(disabled_connectors)

    mcp_degraded = bool(settings.mcp_hub_enabled and tool_client.enabled and tool_client.mcp_error)
    if mcp_degraded:
        effective["mcpDegraded"] = True
        if messages:
            messages[0]["content"] = (messages[0].get("content") or "") + MCP_DEGRADED_NOTE
        logger.error("run %s: MCP 连接器清单不可用（%s）⇒ 本轮连接器工具不可用，已在提示中显式降级",
                     req.run_id, tool_client.mcp_error)

    # —— 内置 / 外部能力一律经**能力注册表**（aios_ai.capabilities）装配 ——
    # 改造前这里有三段手工前置拼接（MCP / 联网 / HITL 三工具），每加一类能力就要再添一段，
    # 且没有任何一处能回答「现在注册了哪些能力、各自健不健康」。现在收敛成一处：
    # 注入顺序 = 注册表注册顺序 = HITL 三工具 → 联网两工具 → MCP → 技能，
    # 之后才是业务网关工具（``tools``），与旧实现**逐项同序**（零回归由哨兵与单测盯着）。
    head, cap_states = await capabilities.get_registry().load(
        {"mcp_tools": mcp_tools, "run_id": req.run_id})
    tools = list(head) + list(tools)
    # 观测（docs/60 P2-12 口径：Run 日志要能解释「模型为什么没看到某类工具」）
    effective["capabilities"] = [s.as_dict() for s in cap_states]
    degraded = [s.as_dict() for s in cap_states if s.state.value in ("ERROR", "UNRESOLVED")]
    if degraded:
        logger.info("run %s: capabilities degraded=%s", req.run_id,
                    [(d["code"], d["state"]) for d in degraded])

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
    # 知识库是否参与本轮、命中几条：跨源聚合要把**内部知识库**也计入「来源覆盖面」，
    # 否则周报的来源清单里只有聊天记录与邮件，用户会以为 AI 没看公司文档。
    kb_state: dict | None = None
    if not kb_on:
        tools = retrieval.strip_kb_tool(tools)
    elif retrieval.is_chitchat(req.text):
        # 闲聊分流（docs/60 P0-3b）：问候/感谢/告别类短句没有检索价值，跳过预检索——
        # 旧行为下「你好」也会拖出「来源：策划书.docx」，观感差且污染上下文。
        logger.info("run %s: kb pre-retrieval skipped (chit-chat, %d chars)",
                    req.run_id, len(req.text or ""))
    elif tool_client.enabled and retrieval.has_kb_tool(tools):
        kb_block, kb_citations = await retrieval.pre_retrieve(
            tool_client, req.text, top_k, threshold, retrieval_mode, kb_scope)
        if kb_block and messages:
            messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + kb_block
        citations.extend(kb_citations)
        kb_state = {"ok": bool(kb_citations), "count": len(kb_citations)}

    # —— 跨源数据聚合（2026-11-03）——
    # 「总结本周工作」不是语义检索能解决的事：它要的是**多个结构化源都查过**。
    # 交给模型自觉的后果是「只查了企微就开始写」，用户拿到半份周报却看不出来。
    # 这里由代码扇出（企微会话/待办/日历 + 邮箱 + 审批），并把「哪些源没查成」也写进提示，
    # 逼模型如实交代缺口。非汇总诉求时 collect 直接返回空串，下列分支全部不执行。
    if settings.aggregate_enabled and tool_client.enabled:
        agg_block, agg_citations, agg_sources = await aggregate_tool.collect(
            tool_client, tools, req.text, kb=kb_state)
        if agg_block and messages:
            messages[0]["content"] = (messages[0].get("content") or "") + agg_block
        if agg_citations:
            seen_doc = {c.get("docId") for c in citations}
            citations.extend(c for c in agg_citations if c.get("docId") not in seen_doc)
        if agg_sources:
            effective["aggregate"] = agg_sources
            # 真聚合到了数据 ⇒ 本轮是「汇总并回答」，不是「填表」：
            # 收起 request_form，逼模型用素材组织答案（实测它会去弹「工作报告」空表）。
            tools = strip_form_for_aggregate(tools)
            logger.info("run %s: 跨源聚合 %d 个源（成功 %d），已收起表单工具",
                        req.run_id, len(agg_sources),
                        sum(1 for s in agg_sources if s.get("ok")))

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

    # —— 「模糊的人」确定性预取（2026-11-02，**连接器无关**）——
    # 提示词早已写了「先查候选人再 ask_user」，但工具存在 ≠ 模型会用：用户实测「帮我给同事
    # 发条消息」时，模型看到没给姓名就直接认定「没法查」，只回一句「请提供姓名/部门/职位」。
    # 这里改成代码先查一次人源（`entity_clarify.find_people_source` 按**工具短名**发现，
    # 通讯录类优先、没有就退到邮件发件人聚合 —— 所以企微和 QQ 邮箱走的是同一条路）：
    #   · 查到候选 ⇒ 往系统提示里写「已为你查好」，并把候选存进 state；
    #   · agent 节点若这一轮**零工具调用**，再用这批候选合成 ask_user（下面那段确定性闸）。
    # 预取失败/超时/无权限一律吞掉（prefetch 内部已兜），不能因为查候选把整条 run 打挂。
    entity_candidates: list[dict] = []
    entity_source = ""
    if _hitl_enabled() and entity_clarify_tool.needs_entity_clarify(req.text):
        entity_candidates, entity_source = await entity_clarify_tool.prefetch(tool_client, tools)
        entity_block = entity_clarify_tool.build_block(
            entity_candidates, entity_source or "contact", req.text)
        if entity_block and messages:
            messages[0]["content"] = (messages[0].get("content") or "") + entity_block
        if entity_candidates:
            effective["entityCandidates"] = len(entity_candidates)
            effective["entitySource"] = entity_source
        logger.info("run %s: 模糊实体预取 %d 个候选（source=%s）",
                    req.run_id, len(entity_candidates), entity_source or "-")

    # —— 请假发起：直接请后端定义的业务表单（2026-11-06 改）——
    # 原先在这里合成一张 ask_user 字段卡（假种/起止/事由/处理人）。实测两个问题：
    #   ① 字段与 form_template 漂移（漏 days / proof）；② 未命中本闸时模型自造卡，
    #      把「负责人」造成自由文本框 —— 用户要的是选人，不是敲名字。
    # 现在只挑表单码、产出 request_form：字段由 Java 从 DB 补全（单一事实源），
    # 负责人留到提交时由 H5 的选择器问（见 H5 askHandlers）。
    # 未命中时 leave_form 为 None，此段对既有链路零影响。
    leave_form = None
    if _hitl_enabled() and leave_apply_tool.needs_leave_form(req.text):
        leave_form = leave_apply_tool.build_request(req.available_forms, req.text)
        if leave_form:
            _blk = leave_apply_tool.build_block(req.available_forms,
                                                leave_form["arguments"]["form_code"])
            if _blk and messages:
                messages[0]["content"] = (messages[0].get("content") or "") + _blk
            effective["leaveFormCode"] = leave_form["arguments"]["form_code"]
            logger.info("run %s: 请假发起 ⇒ 开后端表单 %s（字段由 Java 补全）",
                        req.run_id, leave_form["arguments"]["form_code"])
        else:
            logger.info("run %s: 请假发起但可用表单清单里没有请假表单 ⇒ 交回模型", req.run_id)

    # 观测（docs/60 P2-12）：附件注入量与检索参数进同一条 run 日志，线上排查
    # 「模型为什么看不见附件」不再靠猜。
    _att_count = len(req.attachment_docs or [])
    _att_chars = sum(len(d.text or "") for d in (req.attachment_docs or []))
    logger.info("run %s: history=%d turns, tools=%d, kbOn=%s, temperature=%s, topK=%s, "
                "mode=%s, threshold=%s, atts=%d docs/%d chars",
                req.run_id, len(req.history or []), len(tools), kb_on, temperature, top_k,
                retrieval_mode, threshold, _att_count, _att_chars)

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
        "entity_candidates": entity_candidates,
        "entity_source": entity_source,
        "leave_form": leave_form,
    }


# --------------------------------------------------------------------------- agent

async def agent(state: dict) -> dict:
    """决策轮：调模型（可流式），逐字产出 message.delta，解析 tool_calls。"""
    req = _req(state)
    clock = _clock(state)
    rounds = int(state.get("agent_rounds") or 0)
    allow_tools = rounds < MAX_TOOL_ROUNDS
    provider = gateway.resolve(req.model_ref, credential=req.model_credential)
    api_key = provider.api_key()
    temperature = float(state.get("temperature") or 0.3)
    messages = list(state.get("messages") or [])
    use_tools = (state.get("tools") or None) if allow_tools else None

    # 流式开关：全局设置打开，且**该模型配置允许流式**（管理端/用户端可关，兼容不支持 SSE 的网关）
    stream = bool(settings.agent_stream) and bool(getattr(provider, "stream_enabled", True))
    content_parts = list(state.get("content_parts") or [])
    usage = dict(state.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0})

    # —— 确定性短路①：请假发起（2026-11-03，2026-11-06 改为开后端表单）——
    # 已在 prepare 阶段挑好表单码（`request_form{form_code}`），这里直接作为本轮
    # tool_call 抛出 ⇒ clarify 节点 interrupt ⇒ Java 补全字段 ⇒ 前端渲染。
    # 抢在模型前面的理由与下面「模糊实体」一致：真机实测模型会自己拼一张残缺的卡
    # （负责人成文本框、days 字段丢失），而字段定义本来就在 DB 里。
    if (rounds == 0 and _hitl_enabled() and not (state.get("clarifications") or [])
            and state.get("leave_form")):
        early = state.get("leave_form")
        args = early["arguments"]
        logger.info("run %s: 请假发起 ⇒ 跳过模型，直接开后端表单 %s",
                    req.run_id, args.get("form_code"))
        return {
            "agent_rounds": rounds,
            "allow_tools": allow_tools,
            "pending_calls": [early],
            "content_parts": content_parts,
            "usage": usage,
            "messages": messages + [{
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": early["id"], "type": "function",
                    "function": {"name": early["name"],
                                 "arguments": json.dumps(early["arguments"], ensure_ascii=False)},
                }],
            }],
            "_assistant_message": {"role": "assistant", "content": None},
        }

    # —— 确定性短路：这一轮本来就不该让模型开口（2026-11-02，模糊实体澄清）——
    # 前置条件：prepare 已经查到候选（`entity_candidates`）、HITL 开着、还没澄清过、
    # 用户**没有点名**其中任何人、也不是群发语义。
    # 为什么要抢在调模型之前：真机实测模型拿到候选后不肯调 ask_user，而是把名单写进正文
    # （`[阿修bot.](wobVcoRg…)`，userid 成了链接），代码再补一张卡 ⇒ 用户同时看到一段
    # 带机器值的废话和一张按钮卡。这种写法提示词挡不住，只能不给它写的机会。
    # 代价：这一轮不消耗 `agent_rounds`、不产生任何正文 delta —— 界面直接出按钮，更快更干净。
    # 只抢**第一轮**（`rounds == 0`）：一旦模型已经动过工具（比如它自己先查了通讯录），
    # 后续的「它又改成正文列名单」由下面那段兜底合成来接，而不是在这里截胡。
    if (rounds == 0 and _hitl_enabled() and not (state.get("clarifications") or [])
            and entity_clarify_tool.can_short_circuit(state.get("entity_candidates"),
                                                      req.text)):
        early = entity_clarify_tool.build_call(state.get("entity_candidates"), req.text)
        if early:
            _args = early["arguments"]
            _what = (f"{len(_args['fields'])} 个字段" if _args.get("fields")
                     else f"{len(_args.get('options') or [])} 个候选")
            logger.info("run %s: 候选已就绪且用户未点名 ⇒ 跳过模型，直接弹澄清卡（%s）",
                        req.run_id, _what)
            return {
                "agent_rounds": rounds,
                "allow_tools": allow_tools,
                "pending_calls": [early],
                "content_parts": content_parts,
                "usage": usage,
                "messages": messages + [{
                    "role": "assistant", "content": None,
                    "tool_calls": [{
                        "id": early["id"], "type": "function",
                        "function": {"name": early["name"],
                                     "arguments": json.dumps(early["arguments"], ensure_ascii=False)},
                    }],
                }],
                "_assistant_message": {"role": "assistant", "content": None},
            }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
        message: dict = {}
        u: dict = {}
        round_text = ""
        if stream:
            round_parts: list[str] = []
            buf = ""            # 已收但尚未决定可见性的正文
            emitted = 0         # buf 里已经发出去的长度
            suppress = False    # 命中「调用文本」特征后，本轮正文不再外发
            async for item in _post_stream(http, provider, api_key, messages, use_tools, temperature):
                if item[0] == "delta":
                    clock.check()
                    t = item[1]
                    round_parts.append(t)
                    if suppress:
                        continue
                    buf += t
                    if _CALL_TEXT_SIG_RE.search(buf):
                        # 模型把工具调用写成了正文：这段文字不该出现在回答里。
                        # 已经发出去的前缀（promise 句之类）收不回来，但后续一律压住。
                        suppress = True
                        logger.warning("正文里出现工具调用文本，本轮正文停止外发（等救援）")
                        continue
                    # 开头可能是调用表达式时先扣住，攒够 _STREAM_HOLD 再判；否则照常下发
                    if emitted == 0 and len(buf) < _STREAM_HOLD and _looks_like_call_start(buf):
                        continue
                    _emit("message.delta", {"text": buf[emitted:]})
                    emitted = len(buf)
                else:  # ("done", message, usage)
                    message, u = item[1], item[2]
            round_text = "".join(round_parts)
        else:
            message, u = await _post_non_stream(http, provider, api_key, messages, use_tools, temperature)

    usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
    usage["completion_tokens"] += int(u.get("completion_tokens") or 0)

    calls = _parse_tool_calls(message)
    assistant_calls = message.get("tool_calls")

    # 兜底：模型把工具调用写成正文时必须**在判定「这是不是最终回答」之前**救回来，
    # 否则这一轮会带着「请稍等，我正在为您查询」直接收尾（工具一次都没执行）。
    if not calls and use_tools:
        allowed = {n for n in (_tool_name(t) for t in use_tools) if n}
        rescued = _rescue_textual_calls(str(message.get("content") or ""), allowed)
        if rescued:
            logger.warning("模型把工具调用写成了正文，已还原为真实调用：%s",
                           [c["name"] for c in rescued])
            calls = rescued
            assistant_calls = [{
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"],
                             "arguments": json.dumps(c["arguments"], ensure_ascii=False)},
            } for c in rescued]

    if stream:
        # 流式分支的正文统一在这里收口：清理掉调用文本，再把「还没发出去的部分」补发。
        # 这样界面看到的、落库的、以及后续上下文里的正文三者同源。
        cleaned = _strip_call_text(round_text) if calls else round_text
        if calls and cleaned != round_text:
            round_text = cleaned
        if len(round_text) > emitted:
            _emit("message.delta", {"text": round_text[emitted:]})
        content_parts.append(round_text)
    elif not calls:
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
        # 用 assistant_calls 而不是 message["tool_calls"]：救回来的调用只在 assistant_calls 里，
        # 且它们的 id 必须与下游 tool 消息的 tool_call_id 一致，否则上游直接 400。
        messages.append({"role": "assistant", "content": message.get("content"),
                         "tool_calls": assistant_calls})

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

    # —— 确定性澄清卡（2026-11-02，**连接器无关**）——
    # 与上面 form_hint 同一套思路：模型这一轮**一个工具都没调**（典型表现就是把「请提供姓名」
    # 当成了答案直接收尾），而 prepare 已经查到真实候选 ⇒ 代码替它把按钮弹出来。
    # 条件比 form_hint 更严，三层缺一不可：
    #   ① 真查到候选（查不到就退回模型的文字追问 —— 宁可不弹，也不弹空卡）；
    #   ② 本轮零工具调用、且还没澄清过（`clarifications` 为空 ⇒ 不是续跑后的第二轮）；
    #   ③ 模型这句回复**确实是在反问人名**、或者干脆是空的 ——
    #      若它已经给出了答案（哪怕答错），再插一张「要发给哪一位」的卡只会更乱。
    # 合成后走 clarify 节点 interrupt()，前端渲染真按钮。
    _model_text = str(message.get("content") or "").strip()
    if (not calls and _hitl_enabled() and not (state.get("clarifications") or [])
            and (state.get("entity_candidates") or [])
            and not entity_clarify_tool.names_in_text(state.get("entity_candidates"), req.text)
            and (not _model_text
                 or entity_clarify_tool.looks_like_person_question(_model_text))):
        synth = entity_clarify_tool.build_call(state.get("entity_candidates"), req.text)
        if synth:
            calls = [synth]
            messages.append({"role": "assistant", "content": message.get("content"),
                             "tool_calls": [{
                                 "id": synth["id"],
                                 "type": "function",
                                 "function": {
                                     "name": synth["name"],
                                     "arguments": json.dumps(synth["arguments"], ensure_ascii=False),
                                 },
                             }]})
            logger.info("run %s: 模型零工具调用 ⇒ 用预取的 %d 个候选合成 ask_user（%s）",
                        req.run_id, len(state.get("entity_candidates") or []),
                        "字段卡" if synth["arguments"].get("fields") else "单选卡")

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
    # 防御性过滤：ask_user / request_form / request_confirm 都是内置控制工具、不由业务网关执行
    # （正常路由不会送到这里，但从 clarify 交回的「本轮其余调用」若混入也一律剔除，避免误打网关）。
    calls = _drop_control_calls(state.get("pending_calls"))
    # 防御性过滤（对话级连接器开关）：本次对话被屏蔽的连接器，其工具**即使被模型硬编出来**
    # 也不许执行 —— prepare 已从工具清单里摘掉，这里是第二道闸（模型可能凭记忆编工具名）。
    # ⚠️ 这里**不能直接丢弃**调用：每个 tool_call_id 都必须有对应的 tool 消息，
    # 丢掉会让下一轮请求被上游判为「tool 消息缺失」。正确做法是执行队列里排除、
    # 但仍回注一条 ok=False 的结果 —— 模型据此如实说「该应用在本次对话中未启用」。
    blocked_calls = _blocked_connector_calls(calls, _req(state).disabled_connectors)
    if blocked_calls:
        blocked_ids = {c.get("id") for c in blocked_calls}
        calls = [c for c in calls if c.get("id") not in blocked_ids]
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
        tool_calls_log.append({"name": outcome.name, "arguments": outcome.arguments, "ok": outcome.ok,
                               "digest": _tool_digest(outcome.data)})
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

    # 被对话级开关拦下的连接器调用：回注一条 ok=False 的结果。
    # 必须回注而不是丢弃 —— 每个 tool_call_id 都要有对应的 tool 消息，
    # 丢掉会让下一轮请求被上游判为协议错误（"tool message missing"）。
    for call in blocked_calls:
        tool_calls_log.append({"name": call.get("name"), "arguments": call.get("arguments") or {},
                                "ok": False, "digest": ""})
        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps({
                "ok": False, "data": None,
                "error": "该连接器在本次对话中已被关闭，未执行该调用（连接器本身未被解绑，"
                         "重新开启后即可使用）"}, ensure_ascii=False),
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

def _clarify_answer(answer: Any) -> dict[str, Any]:
    """把回填的答案归一成 ``{value, label, text, values?}``（**标量也要能进**）。

    四种历史形状都要认，否则老客户端/老脚本会静默丢答案：
      · 标量（最老路径，用户选了一个值）      ⇒ ``{"value": 标量, "text": ""}``
      · ``{value,label,text}``（2026-11-02）  ⇒ 原样保留（`text` 是同一张卡里填的补充内容）
      · ``{value,label,text,values}``（字段卡）⇒ 额外带上 ``values``（多字段一次交齐）
      · 其它对象（例如只给了 ``{text: …}``）  ⇒ 尽量凑出 value/text，凑不出就当空答案

    为什么必须归一：这条 tool 消息是**模型唯一的输入**。2026-11-02 现场，用户选完人之后
    模型拿不到「选的是谁 / 要发什么」，只能再问一遍 —— 一次任务被拆成三轮往返。
    """
    if answer is None:
        return {"value": None, "text": ""}
    if isinstance(answer, dict):
        value = answer.get("value")
        text = answer.get("text")
        label = answer.get("label")
        values = answer.get("values")
        out: dict[str, Any] = {
            "value": value if value is not None else text,
            "label": label if label is not None else value,
            "text": str(text).strip() if text is not None else "",
        }
        if isinstance(values, dict) and values:
            # 字段卡：把每个字段原样交给模型（键就是 schema 里的 id），
            # 它才能一次拿到「动作=会议 / 时间=… / 参与人=…」这样的完整一组答案。
            out["values"] = {str(k): v for k, v in values.items()}
            if out["value"] is None:
                first = next((v for v in out["values"].values() if v not in (None, "", [])), None)
                out["value"] = first
        return out
    return {"value": answer, "text": ""}

async def clarify(state: dict) -> dict:
    """澄清轮：模型调用了内置控制工具 ⇒ 暂停等待用户决策，再带着答案继续。

    为什么必须是**独立节点**（不能塞进 tools 节点）
    -----------------------------------------------
    LangGraph ``interrupt()`` 的语义是：暂停时保存状态；**恢复时整个节点函数从头重跑**，
    并在当初 ``interrupt()`` 的位置返回用户的选择。若把中断塞进 tools 节点，恢复时同一轮里
    **已经执行过的其它工具会被再执行一遍**（有副作用的工具直接翻倍）—— 这正是
    `docs/50 §7` 的 **Q3 精确恢复**判据要防的事。
    所以这里只把内置控制调用交给本节点，且本节点**在做任何有副作用的动作之前就中断**，
    重跑成本恒为零。暂停态由 checkpointer 按 thread_id(=run_id) 落盘，恢复时取回。

    三条控制链（ask_user / request_form / request_confirm）共用 interrupt/resume/checkpoint
    底座，不新建状态机：仅按工具类型选择归一化函数与 spec 形状。request_form 的 spec 带
    ``kind="form"``、request_confirm 带 ``kind="confirm"``，供 facade 的 ``_frame_type``
    区分发哪一帧；ask_user 的 spec 维持历史形状（仅 ``question`` / ``suggested_options``），
    前端零改动。
    """
    calls = state.get("pending_calls") or []
    # 找出内置控制调用（三条链都是「命中即暂停」）。互斥取首个。
    ctrl_call = next((c for c in calls if _is_control_call(c.get("name"))), None)
    if ctrl_call is None:                     # 正常不会发生（路由保证），兜底直接放行
        return {"pending_calls": calls}

    name = ctrl_call.get("name")
    chain = _control_chain(name)
    args = ctrl_call.get("arguments")
    if chain == "form":
        spec = request_form_tool.build_form_request(args)
    elif chain == "confirm":
        spec = request_confirm_tool.build_confirm_request(args)
    else:
        spec = ask_user_tool.build_clarification(args)
    if spec is None:
        # 归一化失败（request_form 缺 form_code、request_confirm 标题与描述全空等）：
        # 不当作有效内置调用，剔除后放行、不暂停。避免把「无效控制调用」再喂回模型造成空转。
        return {"pending_calls": _drop_control_calls(calls)}

    # —— 中断点之前：不做任何副作用（不调模型、不调工具、不发事件）。——
    # 暂停事件由 facade 在「观察到暂停」后统一发出，避免恢复重跑时重复发事件。
    answer = interrupt(spec)                 # 首次执行：暂停于此；resume 后：返回用户的答案/回执/决策

    # —— 以下代码只在 resume 之后执行一次。——
    # answer 的回填形状与调用契约逐字对齐（tools.py#build_* 产出什么形状，这里就回填什么形状）：
    #   clarify → 标量或 {value,label,text}；form → 回执对象；confirm → {"decision": true|false}
    #
    # ⚠️ 归一化**只对 clarify 链**做。三条链共用 interrupted 的位置，但形状各不相同：
    # 早先无差别套 `_clarify_answer`，把 confirm 的 `{"decision": true}` 压成了
    # `{"value": null}` —— 决策被吃掉，模型看不见「用户点了确认」，写工具永不执行
    # （test_request_confirm 两条用例当场红）。这层必须按链别分工。
    if chain == "clarify":
        payload: Any = _clarify_answer(answer)
        hint = "信息已齐备，请**直接执行**用户最初的请求，不要再向用户重复确认同一件事。"
    elif chain == "confirm":
        payload = answer
        hint = "用户已做出决策（decision 为 true 表示确认执行）。请据此继续，不要重复发起同一个确认。"
    else:
        payload = answer
        hint = "表单已提交。请据此继续，不要重复发起同一张表单。"
    messages = list(state.get("messages") or [])   # assistant 消息已由 agent 节点并入
    messages.append({
        "role": "tool",
        "tool_call_id": ctrl_call.get("id") or "",
        "content": json.dumps({"ok": True, "data": {"answer": payload}, "next": hint},
                              ensure_ascii=False),
    })
    clarifications = list(state.get("clarifications") or [])
    if chain == "form":
        # 表单回执是对象（{form_code, submission_id, status, data, receipt}），同样可 JSON 序列化。
        clarifications.append({"form_code": spec.get("form_code"), "answer": answer})
    elif chain == "confirm":
        # 确认是二值决策：answer 形如 {"decision": true} / {"decision": false}（取消也可为 null，
        # 一律按「未确认」处理）。记下 title 便于事后追溯用户到底确认了什么。
        clarifications.append({"confirm": spec.get("title"), "answer": answer})
    else:
        clarifications.append({"question": spec.get("question"), "answer": payload})

    # —— 澄清轮「只澄清」的确定性闸（2026-11-02，模糊实体澄清口径）——
    # 模型有时会在同一轮里**既**问「是哪位同事」、**又**先把业务查询用猜的人跑掉。
    # 用户选完之后，那份错误结果已经躺在上下文里，答案就会「错得看起来很像对的」。
    # 提示词只是软约束，这里按链别区分：
    #   · ask_user（澄清）：本轮其余业务调用**整轮丢弃**，等用户选定后再重新调用；
    #   · request_form / request_confirm：保持原行为（这些轮的余下调用是有意的，例如
    #     表单提交后紧跟一条通知），不做改动以免回归。
    # ⚠️ 丢弃必须**补 tool 消息**：assistant 消息里的 tool_calls 若无对应 tool 回包，
    # 下一次请求会被严格实现直接判 400（"tool_call_id not found"）。
    leftovers = _drop_control_calls(calls)
    if chain == "clarify" and leftovers:
        tool_calls_log = list(state.get("tool_calls_log") or [])
        for c in leftovers:
            messages.append({
                "role": "tool",
                "tool_call_id": c.get("id") or "",
                "content": json.dumps({
                    "ok": False, "error": "SKIPPED_PENDING_CLARIFICATION",
                    "message": "本轮只向用户澄清，该调用未执行；请等用户选定后用确认后的标识重新调用",
                }, ensure_ascii=False),
            })
            tool_calls_log.append({
                "name": c.get("name"), "arguments": c.get("arguments"),
                "status": "SKIPPED", "reason": "本轮只澄清（ask_user 未答复）",
            })
        logger.info("run %s clarify: 本轮只澄清，丢弃 %d 个业务调用（%s）",
                    (state.get("req") or {}).get("run_id"),
                    len(leftovers), [c.get("name") for c in leftovers])
        return {"messages": messages, "pending_calls": [],
                "clarifications": clarifications,
                "tool_calls_log": tool_calls_log}

    # 其它控制链（表单/确认）：本轮若还夹带了其它（非内置控制）调用，交回 tools 执行 ——
    # 它们此前从未执行过，不会重复；反之直接回到 agent，让模型带着答案继续。
    return {"messages": messages, "pending_calls": leftovers,
            "clarifications": clarifications}


# --------------------------------------------------------------------------- finalize

async def finalize(state: dict) -> dict:
    """收尾：产出 message.completed + run.completed。"""
    content = "".join(state.get("content_parts") or [])
    tool_calls_log = list(state.get("tool_calls_log") or [])
    usage = dict(state.get("usage") or {})

    # 可观测性：一次工具都没调、却给出「正在查询」的承诺 —— 用户那边表现就是界面停住。
    # 兜底已在 agent 节点（_rescue_textual_calls），这里只负责在漏网时留下可查的日志，
    # 不去改写答案（改写会把模型真说的话换掉，比留个可疑句子更难排查）。
    if not tool_calls_log and _PROMISE_RE.search(content or ""):
        logger.warning("本轮零工具调用但回答像是「正在查询」的承诺（%r…）："
                       "用户会看到停在查询中，检查模型是否把工具调用写成了正文", content[:40])

    if not content and tool_calls_log:
        # 工具轮数用尽仍未产出正文：汇总已获取的数据直接作答（与原行为一致）
        content = "已完成的工具查询结果：\n" + "\n".join(
            f"· {c['name']}：{'成功' if c['ok'] else '失败'}" for c in tool_calls_log)
        for ch in content:
            _emit("message.delta", {"text": ch})
    elif not content:
        # 既没正文也没工具调用 —— 模型这一轮返回了空内容（MiniMax 偶发）。
        # 此前会直接落一条空消息，前端只能显示「（本次未返回内容）」：用户既不知道发生了什么，
        # 也不知道下一步能做什么（2026-10-30 用户现场截图）。这里补一句**可行动**的说明，
        # 同时留下 warn 便于统计频率 —— 但不能把它包装成「已回答」，那才是伪装成功。
        logger.warning("模型本轮返回空内容（无 delta、无 tool_calls）：run 收口用兜底文案")
        content = ("我这轮没有生成内容（模型返回为空）。可以再问一次，"
                   "或把问题说得更具体一些（例如对象、时间范围、想要的结果形式）。")
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
    """agent 之后：含内置控制调用且 HITL 已开 ⇒ 先暂停取值；否则有工具调用且未达上限 ⇒ 执行工具；否则收尾。

    三条内置控制链（ask_user / request_form / request_confirm）都走 ``clarify`` 节点。
    分支必须同时看开关：关闭时模型本不该拿到这些工具，但若它（或因缓存/伪造）仍返回了同名调用，
    绝不能进 ``clarify`` —— 那里会 ``interrupt()``，而关闭态没有 checkpointer，会直接抛错。
    开关必须是唯一权威。
    """
    calls = state.get("pending_calls") or []
    if _hitl_enabled() and any(_is_control_call(c.get("name")) for c in calls):
        return "clarify"
    if calls and state.get("allow_tools"):
        return "tools"
    return "finalize"


def route_after_clarify(state: dict) -> str:
    """澄清之后：本轮若还夹带其它工具调用 → 去执行；否则带着答案回到 agent 继续跑。"""
    return "tools" if state.get("pending_calls") else "agent"
