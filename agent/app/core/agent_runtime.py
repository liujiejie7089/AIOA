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
from collections.abc import AsyncIterator

import httpx

from app.core.guards import GuardError, WallClock, check_text_len
from app.model_gateway import gateway
from app.schemas import RunRequest, SseEvent
from app.tools_client import MAX_TOOL_ROUNDS, ToolClient

logger = logging.getLogger("aioa.agent.runtime")

# OpenAI 兼容 /chat/completions 的 SSE 行前缀
_DATA_PREFIX = "data: "

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


def _build_messages(req: RunRequest) -> list[dict]:
    """构造带系统提示（职责范围 / 页面 / 用户上下文）与多轮历史的消息列表。

    页面上下文让模型具备「所在业务页面 / 选中实体」的态势感知，对应设计中的
    「上下文维护 / 记忆管理」。

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
    uc = req.user_context
    if uc.username or uc.roles:
        role_desc = "、".join(uc.roles) if uc.roles else "普通用户"
        sys_parts.append(f"当前用户：{uc.username or uc.user_id}（角色：{role_desc}）。")
    ctx = req.context
    if ctx is not None:
        bits: list[str] = []
        if ctx.appCode:
            bits.append(f"所在应用={ctx.appCode}")
        if ctx.page:
            bits.append(f"页面={ctx.page}")
        if ctx.pageTitle:
            bits.append(f"页面标题={ctx.pageTitle}")
        if ctx.entityType:
            bits.append(f"实体类型={ctx.entityType}")
        if ctx.entityId:
            bits.append(f"实体ID={ctx.entityId}")
        if bits:
            sys_parts.append("页面上下文：" + "，".join(bits) + "。")
    system = "\n".join(sys_parts)

    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in req.history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant", "system") and content:
            messages.append({"role": role, "content": str(content)})
    messages.append({"role": "user", "content": req.text})
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


async def _post_non_stream(client_http: httpx.AsyncClient, provider, api_key: str,
                           messages: list[dict], tools: list[dict] | None) -> tuple[dict, dict]:
    """非流式推理一轮，返回 (assistant_message, usage)。非 200 抛 UpstreamError。"""
    body: dict = {"model": provider.model, "messages": messages, "stream": False, "temperature": 0.3}
    if tools:
        body["tools"] = tools
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

    messages = _build_messages(req)
    tool_client = ToolClient.from_request(req.user_token)
    tools = await tool_client.list_tools()
    logger.info("run %s: history=%d turns, tools=%d",
                req.run_id, len(req.history or []), len(tools))

    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    tool_calls_log: list[dict] = []
    citations: list[dict] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http:
            # 感知—规划—执行—反思 循环（工具段）：非流式决策，命中工具则执行后回注
            for _round in range(MAX_TOOL_ROUNDS + 1):
                message, u = await _post_non_stream(http, provider, api_key, messages,
                                                    tools if _round < MAX_TOOL_ROUNDS else None)
                usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
                usage["completion_tokens"] += int(u.get("completion_tokens") or 0)

                calls = _parse_tool_calls(message)
                if not calls:
                    # 无工具调用：该 message 即最终回答（本地切片为 delta，保持事件契约）
                    content = str(message.get("content") or "")
                    for ch in content:
                        clock.check()
                        yield SseEvent(seq=seq, type="message.delta", data={"text": ch})
                        seq += 1
                    content_parts.append(content)
                    break

                messages.append({"role": "assistant", "content": message.get("content"),
                                 "tool_calls": message.get("tool_calls")})
                for call in calls:
                    clock.check()
                    yield SseEvent(seq=seq, type="tool.call",
                                   data={"name": call["name"], "arguments": call["arguments"]})
                    seq += 1
                    outcome = await tool_client.invoke(call["name"], call["arguments"])
                    tool_calls_log.append({"name": call["name"], "arguments": call["arguments"],
                                           "ok": outcome.ok})
                    citations.extend(c for c in _citations_from_tool(call["name"], outcome)
                                     if c["docId"] not in {x["docId"] for x in citations})
                    yield SseEvent(seq=seq, type="tool.result",
                                   data={"name": call["name"], "ok": outcome.ok,
                                         "summary": outcome.summary()})
                    seq += 1
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
        data={"content": final_content, "citations": citations, "tool_calls": tool_calls_log, "usage": usage},
    )
    seq += 1
    yield SseEvent(seq=seq, type="run.completed", data={"status": "SUCCEEDED", "usage": usage})
