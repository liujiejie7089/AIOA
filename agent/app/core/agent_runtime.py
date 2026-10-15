"""M2 真实 Agent 运行时（即设计中的「DeepSeek Harness 引擎 / Sidecar」）。

职责（对应架构第 3 层 · 智能体运行层）：
  - Agent Runtime：维护多轮对话上下文与页面上下文（记忆/状态机雏形）
  - 工具调用循环（function-calling）：决策轮（非流式，带 tools）→ 命中工具则经
    业务工具网关（用户 token 透传）执行 → 结果回注模型 → 直至产出正文
    对应技术方案「感知—规划—执行—反思」循环的工具执行段，最多 MAX_TOOL_ROUNDS 轮
  - 上报 token 用量（usage，多轮累加），作为「平台底座层 · 运营计费」的计量源头

事件序列（与 echo 完全一致，另加可选 tool 事件，契约向后兼容）：
    run.started{run_id,conversation_id,model,gateway_key}
    → [tool.call{name,arguments} → tool.result{name,ok,summary}]×N
    → message.delta{text} × N
    → message.completed{content,citations,tool_calls,usage}
    → run.completed{status:"SUCCEEDED",usage}
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

import httpx

from app.config import settings
from app.core import answer_shape
from app.core import worker_intake
from app.core.guards import GuardError, WallClock, check_text_len
from app.core.orchestrator import SubTask, stream_run
from app.model_gateway import gateway
from app.schemas import RunRequest, SseEvent
from app.tools_client import MAX_TOOL_ROUNDS, ToolClient, ToolOutcome

logger = logging.getLogger("aioa.agent.runtime")

# OpenAI 兼容 /chat/completions 的 SSE 行前缀与结束标记
_DATA_PREFIX = "data: "
_DONE_MARK = "[DONE]"

# 知识库检索工具名：其结果回写 message.completed.citations（FR-D5 引用溯源）
KB_TOOL = "search_kb_documents"


def _citations_from_tool(name: str, outcome) -> list[dict]:
    """知识库检索结果 → 引用溯源条目 [{docId, title, source}]（同文档去重）。"""
    if name != KB_TOOL or not outcome.ok or not isinstance(outcome.data, list):
        return []
    out: list[dict] = []
    seen: set = set()
    for doc in outcome.data:
        if isinstance(doc, dict) and doc.get("id") is not None and doc["id"] not in seen:
            seen.add(doc["id"])
            out.append({"docId": doc["id"], "title": str(doc.get("docName") or ""),
                        "source": "knowledge_base"})
    return out


# 指令覆盖（prompt injection）黑名单：命中即视为尝试越权注入系统提示。
# 仅中和（剥离）并记 warn，不拒绝请求（保持产品行为）。
_OVERRIDE_PATTERNS = (
    "ignore previous instructions", "ignore the above", "ignore all previous",
    "disregard previous", "disregard the above", "forget your instructions",
    "forget previous", "new instructions", "system:", "system prompt",
    "忽略以上指令", "忽略上述指令", "忽略之前的指令", "无视以上指令", "忘记你的指令",
    "忽略前面的指令", "覆盖指令", "新的指令", "系统提示：", "假装你是", "你现在是",
)
_INJECTION_MASK = "[已屏蔽的指令覆盖尝试]"


def _strip_control_chars(value: str) -> str:
    """剥掉控制字符与换行（保留可读文本）：防止通过换行/制表符伪造或截断提示结构。"""
    if not value:
        return ""
    # 仅保留 0x20 及以上的可见/空白字符（CJK、标点、空格等），剔除 0x00-0x1F、0x7F。
    return "".join(ch for ch in value if ord(ch) >= 0x20 and ord(ch) != 0x7F)


def _wrap_field(prefix: str, value: str | int | None) -> str:
    """把用户可控数据包裹成「硬括号 + 固定前缀」，让模型明确区分『这是数据』而非指令。

    例：[user.name=张三] / [ctx.appCode=ticket]。同时剥掉控制字符与换行。
    非字符串值（如 user_id 整数）先转 str；值为空时返回空串（调用方已做真值判断）。
    """
    if value is None:
        return ""
    cleaned = _strip_control_chars(str(value))
    if not cleaned:
        return ""
    return f"[{prefix}={cleaned}]"


def _neutralize_injection(text: str | None) -> str:
    """对用户输入 / 历史正文做指令覆盖中和：命中 token-override 黑名单时剔除并记 warn，
    同时剥掉控制字符。不拒绝请求（保持产品行为），仅做降噪与越权防护。
    """
    if text is None:
        return ""
    cleaned = _strip_control_chars(str(text))
    hit = False
    for pat in _OVERRIDE_PATTERNS:
        if re.search(re.escape(pat), cleaned, flags=re.IGNORECASE):
            hit = True
            cleaned = re.sub(re.escape(pat), _INJECTION_MASK, cleaned, flags=re.IGNORECASE)
    if hit:
        logger.warning("检测到疑似指令覆盖注入并已中和：%r", text[:120])
    return cleaned


# 对话内参考文档正文合计上限（字符）：超出后按顺序截断，避免单次请求上下文被长文档撑爆。
_MAX_ATTACHMENT_CHARS = 40000


def _build_attachment_block(docs: list) -> str:
    """把对话内上传的参考文档拼成一段「独立」的上下文块。

    每块用「【参考文档】《名字》」开头、「【以上为参考文档】」结尾，作为不可信输入
    **同样经过** ``_neutralize_injection``（文档内容可能夹带指令覆盖尝试，与 history/text
    同等待遇，不得原样裸拼）。放在 system 提示的末尾、作为独立段落，而非混入 ``scope``
    的职责提示：职责提示是「身份 / 边界」，参考文档是「本次待参考的资料」，语义不同，
    混在职责段里会污染职责边界；独立成段 + 硬边界包裹，方便模型区分「这是用户上传的资料」
    与「这是系统给你的指令」。

    - ``truncated`` 为真（单篇已被后端节选）：块尾注明「（文档较长，以上为节选）」。
    - 所有文档正文合计超 ``_MAX_ATTACHMENT_CHARS``：按序截断剩余，并在被截断块尾注明
      「（参考文档总长度超出上限，以上为截断内容）」。
    """
    blocks: list[str] = []
    total = 0
    for doc in docs:
        name = doc.name or "未命名文档"
        text = _neutralize_injection(doc.text or "")
        note = ""
        if doc.truncated:
            note += "\n（文档较长，以上为节选）"
        # 总长保护：本篇会让累计正文超上限时，截断本篇、并清空后续预算
        if total + len(text) > _MAX_ATTACHMENT_CHARS:
            remaining = _MAX_ATTACHMENT_CHARS - total
            text = text[:remaining] if remaining > 0 else ""
            note += "\n（参考文档总长度超出上限，以上为截断内容）"
            total = _MAX_ATTACHMENT_CHARS  # 后续文档均无剩余预算
        else:
            total += len(text)
        piece = f"【参考文档】《{name}》\n{text}\n【以上为参考文档】"
        if note:
            piece += note
        blocks.append(piece)
    return "\n\n".join(blocks)


def _build_kb_reference_block(rows: list) -> str:
    """把预检索命中的知识库片段拼成一段「独立」的参考上下文块。

    风格照搬 ``_build_attachment_block``：用硬边界包裹为不可信输入，同样经过
    ``_neutralize_injection``（库文档可能夹带指令覆盖尝试），作为独立段落追加到
    system 提示末尾，让模型区分「这是用户相关知识库资料」与「系统指令」。

    库文档字段不固定（可能含 ``content`` / ``text`` / ``docName`` 等），这里做兼容取值。
    """
    blocks: list[str] = []
    for doc in rows:
        if not isinstance(doc, dict):
            continue
        name = doc.get("docName") or doc.get("title") or "未命名文档"
        text = _neutralize_injection(doc.get("content") or doc.get("text") or "")
        if not text:
            continue
        blocks.append(f"【知识库参考】《{name}》\n{text}\n【以上为知识库参考】")
    return "\n\n".join(blocks)


def _build_messages(req: RunRequest, max_context: int = 0) -> list[dict]:
    """构造带系统提示（职责范围 / 页面 / 用户上下文）与多轮历史的消息列表。

    页面上下文让模型具备「所在业务页面 / 选中实体」的态势感知，对应设计中的
    「上下文维护 / 记忆管理」。

    max_context > 0 时按字符预算裁剪多轮历史（丢最旧的）：模型配置里的「最大上下文长度」
    必须真的作用于请求，否则就只是个展示字段。0（默认）= 不限制，保持既有行为。

    职责范围（req.scope）由后端在会话绑定数字员工时下发：一旦存在，**整体替换**
    通用助手身份提示，并追加「只答职责范围内、越界一律拒答」的硬规则——
    这是「职责限定」的触发点（会话绑定）与判定点（系统提示 + 拒答规则）在 Agent 侧的落点。
    """
    scope = req.scope or {}
    if scope:
        role_name = scope.get("role_name") or scope.get("role") or "通用办公助手"
        sys_parts: list[str] = [
            f"你是 AIOA 智能办公平台的数字员工「{scope.get('name') or '数字员工'}」（角色类型：{role_name}）。",
            f"你的职责边界（唯一可回答的范围）：{scope.get('duty') or '通用办公'}。",
            "【职责范围限定 · 必须严格遵守】",
            "1. 只回答与上述职责边界直接相关的问题；",
            "2. 与职责无关的问题（闲聊、其他岗位职责、与本职责无关的通用知识），"
            "一律礼貌拒答，用一句话说明你的职责范围，并建议用户改问对应的数字员工或业务入口；",
            "3. 不得编造或推测超出职责边界的信息；需要业务数据时调用已提供的工具，工具查不到就如实说明；",
            "4. 不得声称自己拥有职责范围之外的权限（如审批、放款、盖章等），也不得越权承诺办理结果。",
        ]
        if scope.get("role") == "LEAVE_APPROVER":
            sys_parts.append(
                "请假审批场景：你负责受理请假申请、校验请假类型与证明材料，"
                "并依据企业请假制度给出送审与答复意见；与请假无关的审批事项一律不予处理。")
    else:
        sys_parts = [
            "你是 AIOA 智能办公基座（AI Office Agent）的对话助手，服务于企业办公场景。",
            "请根据用户所在的业务页面与上下文，给出准确、简洁、可执行的回答。",
            "需要查询用户的审批、知识库、额度等业务数据时，优先调用提供的工具，不要编造。",
        ]
    # 回答风格：只划「不能答什么」不够，还要管「答多长、答什么」。
    # 2026-10-12 起**不再**要求每次回答都按六段输出 —— 那会让「这个文件里有什么」这类
    # 简单提问也被撑成六段（用户反馈：回答太多，只答与提问相关的）。现改为「默认只答所问」，
    # 且仅在「用户提问**涉及权限**」时才补「下一步 / 找谁放行」——答不了、超出职责、查不到
    # 数据等其余情况一律不出现此类办理指引（用户进一步要求：口径只限权限话题）。
    # 规则唯一出处见 answer_shape.rules。
    sys_parts.extend(answer_shape.rules(scope))
    uc = req.user_context
    if uc.username or uc.roles:
        role_desc = "、".join(uc.roles) if uc.roles else "普通用户"
        sys_parts.append(
            f"当前用户：{_wrap_field('user.name', uc.username or uc.user_id)}"
            f"（角色：{_wrap_field('user.role', role_desc)}）。")
    ctx = req.context
    if ctx is not None:
        bits: list[str] = []
        if ctx.appCode:
            bits.append(f"所在应用={_wrap_field('ctx.appCode', ctx.appCode)}")
        if ctx.page:
            bits.append(f"页面={_wrap_field('ctx.page', ctx.page)}")
        if ctx.pageTitle:
            bits.append(f"页面标题={_wrap_field('ctx.pageTitle', ctx.pageTitle)}")
        if ctx.entityType:
            bits.append(f"实体类型={_wrap_field('ctx.entityType', ctx.entityType)}")
        if ctx.entityId:
            bits.append(f"实体ID={_wrap_field('ctx.entityId', ctx.entityId)}")
        if bits:
            sys_parts.append("页面上下文：" + "，".join(bits) + "。")
    # 当前项目上下文（后端在有项目会话时下发，键名照抄后端契约 {id,name,type,status}）。
    # 目的：让模型明确「用户在本项目会话中提问默认针对该项目」，不再反问上传到哪个系统/平台。
    # 项目名/类型为库里数据，用 _wrap_field 包裹防注入；缺失时不追加任何内容，保持与改动前逐字一致。
    if req.project and req.project.get("id") is not None:
        pid = req.project.get("id")
        pname = _wrap_field("project.name", req.project.get("name"))
        ptype = _wrap_field("project.type", req.project.get("type"))
        sys_parts.append(
            f"当前项目：《{pname}》（id={pid}，类型={ptype}）。"
            "用户在本项目会话中提问时默认针对该项目；不要反问用户在哪个系统或平台。")
    # 动作提示：把「本轮回应的正确姿态」显式告诉模型，修两类已核实缺陷——
    # ① H5 已自行打开上传/上报窗口，模型却答「我无法直接处理文件上传」（来源矛盾）；
    # ② 用户要「新建数字人」，模型却说要申请 worker:manage（真实是 worker:create 默认开放）。
    # 只在有对应动作时追加，无动作时保持与改动前逐字一致。
    action = worker_intake.detect_action(req.text)
    if action == "UPLOAD_FILE":
        if req.project and req.project.get("id") is not None:
            sys_parts.append(
                "本轮用户诉求已被识别为「上传文件」。用户端会为当前项目直接打开上传窗口 —— "
                "你只需一句话确认（例如「正在为你打开上传窗口，请选择文件。」），不要重复描述窗口细节，"
                "更不要回复「我无法直接操作」「请使用系统/平台提供的上传功能」「请确认你要上传到哪个平台」这类话。")
        else:
            sys_parts.append(
                "本轮用户诉求已被识别为「上传文件」。用户端会提示用户先进入一个项目再上传 —— "
                "你只需一句话说明，不要给通用上传教程。")
    elif action == "REPORT_EXPENSE":
        if req.project and req.project.get("id") is not None:
            sys_parts.append(
                "本轮用户诉求已被识别为「上报花费」。用户端会为当前项目直接打开花费上报窗口 —— "
                "你只需一句话确认（例如「正在为你打开花费上报窗口，请填写金额。」），不要重复描述窗口细节，"
                "更不要回复「我无法直接操作」「请使用系统/平台提供的相关功能」这类话。")
        else:
            sys_parts.append(
                "本轮用户诉求已被识别为「上报花费」。用户端会提示用户先进入一个项目再上报 —— "
                "你只需一句话说明，不要给通用上报教程。")
    elif action == "CREATE_WORKER":
        sys_parts.append(
            "本轮用户诉求已被识别为「创建数字员工」。创建是界面能力：用户端「专家与员工」页有"
            "「＋ 创建数字员工」入口（管理端亦可），所需权限 worker:create 对全体登录用户默认开放。"
            "不要说需要申请 worker:manage，不要调用权限申请工具，不要回复无法操作；用一句话把入口告诉用户即可。")
    # 全局硬规则：无论有无动作都生效，杜绝能力否认话术（例如「我无法直接处理文件上传」），
    # 改让用户要求执行某动作时说明具体入口或界面提供的入口。
    sys_parts.append(
        "禁止输出「我无法直接操作系统或平台」「我无法直接处理文件上传」"
        "「我无法直接打开上传窗口」这类能力否认话术；用户要求你执行某个动作时，"
        "说明具体入口或由界面提供的入口，不要给泛泛的通用教程。")
    # 对话内上传的参考文档：作为独立上下文块追加到 system 提示末尾（详见 _build_attachment_block）。
    # 无附件时不追加任何内容，保证与改动前逐字一致。
    if req.attachment_docs:
        sys_parts.append(_build_attachment_block(req.attachment_docs))
    system = "\n".join(sys_parts)

    system_message = {"role": "system", "content": system}
    history: list[dict] = []
    for turn in req.history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant", "system") and content:
            history.append({"role": role, "content": str(_neutralize_injection(content))})

    if max_context and max_context > 0:
        # token -> 字符的粗换算（中英混合经验值 1 token ≈ 2 字符），只用来做上限保护；
        # 系统提示与当前提问永远保留，超出预算的从最旧的一轮开始丢。
        budget = max(int(max_context) * 2, 1000)
        used = len(system) + len(req.text or "")
        kept: list[dict] = []
        for turn in reversed(history):
            if used + len(turn["content"]) > budget:
                break
            kept.append(turn)
            used += len(turn["content"])
        kept.reverse()
        if len(kept) < len(history):
            logger.info("history trimmed by max_context=%d: %d -> %d turns",
                        max_context, len(history), len(kept))
        history = kept

    messages: list[dict] = [system_message]
    messages.extend(history)
    messages.append({"role": "user", "content": _neutralize_injection(req.text)})
    return messages


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


class UpstreamError(RuntimeError):
    """上游模型非 200：转 MODEL_UPSTREAM_ERROR（其余异常仍归 MODEL_STREAM_ERROR）。"""

    def __init__(self, status: int, text: str):
        super().__init__(f"status={status} {text[:200]}")
        self.status = status


def _accumulate_tool_call(acc: dict[int, dict], delta_call: dict) -> None:
    """流式 tool_calls 是分片到达的（name 一段、arguments 多段），按 index 累加拼接。"""
    idx = int(delta_call.get("index") or 0)
    slot = acc.setdefault(idx, {"id": "", "type": "function",
                                "function": {"name": "", "arguments": ""}})
    if delta_call.get("id"):
        slot["id"] = delta_call["id"]
    fn = delta_call.get("function") or {}
    if fn.get("name"):
        slot["function"]["name"] += fn["name"]
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]


async def _post_stream(client_http: httpx.AsyncClient, provider, api_key: str,
                       messages: list[dict], tools: list[dict] | None,
                       temperature: float = 0.3) -> AsyncIterator[tuple]:
    """流式推理一轮：先产出 ("delta", text) ×N，最后产出 ("done", message, usage)。

    为什么用流式替代「非流式取回后本地切片」：本地切片只是把等待时间挪到了第一个
    delta 之前，用户在长回答上仍要干等整段生成完；流式让首字延迟等于上游首个分片
    的到达时间。事件契约（message.delta ×N）保持不变，前端零改动。
    """
    body: dict = {"model": provider.model, "messages": messages, "stream": True,
                  "temperature": temperature, "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "Accept": "text/event-stream"}

    content_parts: list[str] = []
    acc: dict[int, dict] = {}
    usage: dict = {}
    async with client_http.stream("POST", url, json=body, headers=headers) as resp:
        if resp.status_code != 200:
            try:
                raw = await resp.aread()
                text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            except Exception:  # 读不出 body 也要带上状态码，便于定位
                text = ""
            raise UpstreamError(resp.status_code, text)
        async for line in resp.aiter_lines():
            if not line or not line.startswith(_DATA_PREFIX):
                continue
            payload = line[len(_DATA_PREFIX):].strip()
            if payload == _DONE_MARK:
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(chunk.get("usage"), dict) and chunk["usage"]:
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    yield ("delta", piece)
                for call in delta.get("tool_calls") or []:
                    _accumulate_tool_call(acc, call)

    message: dict = {"role": "assistant", "content": "".join(content_parts) or None}
    if acc:
        message["tool_calls"] = [acc[i] for i in sorted(acc)]
    yield ("done", message, usage)


async def _post_non_stream(client_http: httpx.AsyncClient, provider, api_key: str,
                           messages: list[dict], tools: list[dict] | None,
                           temperature: float = 0.3, max_tokens: int | None = None) -> tuple[dict, dict]:
    """非流式推理一轮，返回 (assistant_message, usage)。非 200 抛 UpstreamError。"""
    body: dict = {"model": provider.model, "messages": messages, "stream": False, "temperature": temperature}
    if tools:
        body["tools"] = tools
    if max_tokens:
        body["max_tokens"] = max_tokens
    resp = await client_http.post(
        provider.base_url.rstrip("/") + "/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        raise UpstreamError(resp.status_code, resp.text or "")
    data = resp.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    usage = data.get("usage") or {}
    return message, usage


async def run(req: RunRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """真实 LLM 推理事件流（含工具调用循环）。"""
    seq = seq_start
    check_text_len(req.text)
    clock = WallClock()

    provider = gateway.resolve(req.model_ref)
    api_key = provider.api_key()
    if not api_key:
        yield SseEvent(
            seq=seq,
            type="error",
            data={
                "code": "MODEL_PROVIDER_NOT_CONFIGURED",
                "message": f"provider '{provider.key}' 未配置 api_key（请设置环境变量 {provider.api_key_env}）",
                "retryable": False,
            },
        )
        seq += 1
        yield SseEvent(
            seq=seq,
            type="run.failed",
            data={"reason": "provider not configured", "error_code": "MODEL_PROVIDER_NOT_CONFIGURED"},
        )
        return

    yield SseEvent(
        seq=seq,
        type="run.started",
        data={"run_id": req.run_id, "conversation_id": req.conversation_id,
              "model": provider.model, "gateway_key": provider.key},
    )
    seq += 1

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

    messages = _build_messages(req, getattr(provider, "max_context", 0) or 0)
    tool_client = ToolClient.from_request(req.user_token)
    tools = await tool_client.list_tools()

    # 对话级知识库开关（KB）：由 Java 后端从 CreateRunRequest 透传，缺省视为 True。
    # False = 本次 run 完全不使用知识库（剔除检索工具，模型无法发起检索）；
    # True（或缺省）= 知识库可用且优先（进入工具循环前先做预检索并注入参考上下文）。
    kb_on = req.kb_on if req.kb_on is not None else True
    effective["kbOn"] = kb_on

    # citations 须在预检索之前初始化（预检索命中时会并入引用）
    citations: list[dict] = []

    if not kb_on:
        # 关闭知识库：从候选工具中剔除检索工具，模型即使想检索也无工具可调用。
        tools = [t for t in tools
                 if (t.get("function", {}).get("name") or t.get("name")) != KB_TOOL]
    else:
        # 知识库可用且优先：进入工具循环前先预检索，命中则把片段作为参考上下文注入，
        # 并把引用并入 citations。检索失败只记日志、绝不中断 run。
        if tool_client.enabled and any(
            (t.get("function", {}).get("name") or t.get("name")) == KB_TOOL for t in tools
        ):
            try:
                kb_args = _inject_search_params(
                    KB_TOOL, {"keyword": req.text}, top_k, threshold, retrieval_mode, kb_scope
                )
                kb_outcome = await tool_client.invoke(KB_TOOL, kb_args)
                if kb_outcome.ok and isinstance(kb_outcome.data, list) and kb_outcome.data:
                    kb_block = _build_kb_reference_block(kb_outcome.data)
                    if kb_block and messages:
                        messages[0]["content"] = (messages[0].get("content") or "") + "\n\n" + kb_block
                    seen_ids = {c["docId"] for c in citations}
                    for c in _citations_from_tool(KB_TOOL, kb_outcome):
                        if c["docId"] not in seen_ids:
                            citations.append(c)
                            seen_ids.add(c["docId"])
                    logger.info("run %s: kb pre-retrieval hit %d docs", req.run_id, len(kb_outcome.data))
                else:
                    logger.info("run %s: kb pre-retrieval returned no data", req.run_id)
            except Exception as exc:  # 检索失败不冒泡成 error，保证 run 能跑完
                logger.warning("run %s: kb pre-retrieval failed (ignored): %s", req.run_id, exc)

    logger.info("run %s: history=%d turns, tools=%d, kbOn=%s, temperature=%s, topK=%s, mode=%s",
                req.run_id, len(req.history or []), len(tools), kb_on, temperature, top_k, retrieval_mode)

    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    tool_calls_log: list[dict] = []
    content_parts: list[str] = []

    # 运行期开关（见 config.Settings）：流式直出 / 一轮内多工具并发
    stream = bool(settings.agent_stream)
    parallel = bool(settings.agent_parallel_tools)
    max_concurrency = max(1, int(settings.agent_max_concurrency or 1))
    search_params = (top_k, threshold, retrieval_mode, kb_scope)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
            # 感知—规划—执行—反思 循环（工具段）：决策命中工具则执行后回注
            for _round in range(MAX_TOOL_ROUNDS + 1):
                use_tools = tools if _round < MAX_TOOL_ROUNDS else None
                message: dict = {}
                u: dict = {}
                if stream:
                    async for item in _post_stream(http, provider, api_key, messages, use_tools,
                                                   temperature):
                        if item[0] == "delta":
                            clock.check()
                            content_parts.append(item[1])
                            yield SseEvent(seq=seq, type="message.delta", data={"text": item[1]})
                            seq += 1
                        else:  # ("done", message, usage)
                            message, u = item[1], item[2]
                else:
                    message, u = await _post_non_stream(http, provider, api_key, messages,
                                                        use_tools, temperature)
                usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
                usage["completion_tokens"] += int(u.get("completion_tokens") or 0)

                calls = _parse_tool_calls(message)
                if not calls:
                    if not stream:
                        # 非流式：该 message 即最终回答，本地切片为 delta（保持事件契约）
                        content = str(message.get("content") or "")
                        for ch in content:
                            clock.check()
                            yield SseEvent(seq=seq, type="message.delta", data={"text": ch})
                            seq += 1
                        content_parts.append(content)
                    break

                messages.append({"role": "assistant", "content": message.get("content"),
                                 "tool_calls": message.get("tool_calls")})
                # 本轮的工具调用走编排器：彼此独立时并发执行（省等待），
                # 单调用时等价于串行（一层一个任务），行为不变。
                outcomes: list[ToolOutcome] = []
                async for item in _run_tool_calls(calls, tool_client, search_params,
                                                  parallel, max_concurrency):
                    if item[0] == "event":
                        clock.check()
                        yield SseEvent(seq=seq, type=item[1], data=item[2])
                        seq += 1
                    else:  # ("done", outcomes)
                        outcomes = item[1]
                for call, outcome in zip(calls, outcomes):
                    tool_calls_log.append({"name": outcome.name, "arguments": outcome.arguments,
                                           "ok": outcome.ok})
                    citations.extend(c for c in _citations_from_tool(outcome.name, outcome)
                                     if c["docId"] not in {x["docId"] for x in citations})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps({"ok": outcome.ok,
                                               "data": None if outcome.data is None else outcome.data,
                                               "error": outcome.error}, ensure_ascii=False),
                    })
            else:
                # 工具轮数用尽仍未产出正文：汇总已获取的数据直接作答，不再调模型
                content = "已完成的工具查询结果：\n" + "\n".join(
                    f"· {c['name']}：{'成功' if c['ok'] else '失败'}" for c in tool_calls_log)
                for ch in content:
                    yield SseEvent(seq=seq, type="message.delta", data={"text": ch})
                    seq += 1
                content_parts.append(content)
    except GuardError:
        raise  # 交由 main.py 的 event_stream 统一转成 error + run.failed
    except UpstreamError as exc:  # 上游非 200：可重试的上游错误
        yield SseEvent(
            seq=seq,
            type="error",
            data={
                "code": "MODEL_UPSTREAM_ERROR",
                "message": str(exc)[:200],
                "retryable": True,
            },
        )
        seq += 1
        yield SseEvent(
            seq=seq,
            type="run.failed",
            data={"reason": "upstream error", "error_code": "MODEL_UPSTREAM_ERROR"},
        )
        return
    except Exception as exc:  # 网络/解析等：流内异常按 error + run.failed 上报，不中断服务
        yield SseEvent(
            seq=seq,
            type="error",
            data={"code": "MODEL_STREAM_ERROR", "message": str(exc)[:200], "retryable": True},
        )
        seq += 1
        yield SseEvent(
            seq=seq,
            type="run.failed",
            data={"reason": str(exc)[:200], "error_code": "MODEL_STREAM_ERROR"},
        )
        return

    final_content = "".join(content_parts)
    yield SseEvent(
        seq=seq,
        type="message.completed",
        data={"content": final_content, "citations": citations, "tool_calls": tool_calls_log,
              "usage": usage, "effective_params": effective},
    )
    seq += 1
    yield SseEvent(seq=seq, type="run.completed", data={"status": "SUCCEEDED", "usage": usage})


async def _run_tool_calls(calls: list[dict], tool_client: ToolClient, search_params: tuple,
                          parallel: bool, max_concurrency: int) -> AsyncIterator[tuple]:
    """执行一轮内的全部工具调用：产出 ("event", type, data)×N，末项 ("done", outcomes)。

    改造前是 `for call in calls: await invoke(...)` 的串行循环 —— 模型一次吐出 3 个
    互不相关的查询就要付 3 倍等待。这里改走编排器：同层并发，且并发度有上限
    （不把业务网关打满）。parallel=False 时 max_concurrency=1，等价于原串行语义。
    """
    top_k, threshold, retrieval_mode, kb_scope = search_params
    subtasks = [
        # 检索类工具透传专家配置参数（真实生效），其他工具原样透传
        SubTask(id=call["id"] or f"call_{i}", tool=call["name"],
                arguments=_inject_search_params(call["name"], dict(call["arguments"]),
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


def _inject_search_params(name: str, arguments: dict, top_k: int, threshold: float,
                          mode: str, kb_scope: str) -> dict:
    """检索类工具注入专家配置参数（topK/threshold/mode/kbScope 真实生效）。"""
    if name != "search_kb_documents":
        return arguments
    arguments.setdefault("topK", top_k)
    arguments.setdefault("threshold", threshold)
    arguments.setdefault("mode", mode)
    arguments.setdefault("kbScope", kb_scope)
    return arguments
