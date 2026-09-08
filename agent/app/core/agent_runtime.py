"""M2 真实 Agent 运行时（即设计中的「DeepSeek Harness 引擎 / Sidecar」）。

职责（对应架构第 3 层 · 智能体运行层）：
  - Agent Runtime：维护多轮对话上下文与页面上下文（记忆/状态机雏形）
  - DeepSeek Harness：经 model_gateway 解析 openai_compatible provider（DeepSeek / 通义 /
    本地 vLLM / Ollama），以 SSE 流式拉取推理结果，与主业务栈（Java）解耦
  - 上报 token 用量（usage），作为「平台底座层 · 运营计费」的计量源头

事件序列与 echo 完全一致（契约不变）：
    run.started{run_id,conversation_id}
    → message.delta{text} × N
    → message.completed{content,citations,tool_calls,usage}
    → run.completed{status:"SUCCEEDED",usage}
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.core.guards import GuardError, WallClock, check_text_len
from app.model_gateway import gateway
from app.schemas import RunRequest, SseEvent

# OpenAI 兼容 /chat/completions 的 SSE 行前缀
_DATA_PREFIX = "data: "


def _build_messages(req: RunRequest) -> list[dict]:
    """构造带系统提示（页面/用户上下文）与多轮历史的消息列表。

    页面上下文让模型具备「所在业务页面 / 选中实体」的态势感知，对应设计中的
    「上下文维护 / 记忆管理」。
    """
    sys_parts: list[str] = [
        "你是 AIOA 智能办公基座（AI Office Agent）的对话助手，服务于企业办公场景。",
        "请根据用户所在的业务页面与上下文，给出准确、简洁、可执行的回答。",
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


async def run(req: RunRequest, seq_start: int = 1) -> AsyncIterator[SseEvent]:
    """真实 LLM 推理事件流。"""
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
        data={"run_id": req.run_id, "conversation_id": req.conversation_id},
    )
    seq += 1

    messages = _build_messages(req)
    body = {
        "model": provider.model,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    endpoint = provider.base_url.rstrip("/") + "/chat/completions"

    content_parts: list[str] = []
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            async with client.stream("POST", endpoint, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    yield SseEvent(
                        seq=seq,
                        type="error",
                        data={
                            "code": "MODEL_UPSTREAM_ERROR",
                            "message": f"status={resp.status_code} {err.decode('utf-8', 'replace')[:200]}",
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

                async for line in resp.aiter_lines():
                    if not line or not line.startswith(_DATA_PREFIX):
                        continue
                    payload = line[len(_DATA_PREFIX):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    # 用量统计（通常出现在最后一个 chunk，作为计费计量源头）
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        usage["prompt_tokens"] = u.get("prompt_tokens", 0)
                        usage["completion_tokens"] = u.get("completion_tokens", 0)

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        content_parts.append(text)
                        clock.check()  # 墙钟护栏：超时则抛 GuardError，由 main 统一收口
                        yield SseEvent(seq=seq, type="message.delta", data={"text": text})
                        seq += 1
    except GuardError:
        raise  # 交由 main.py 的 event_stream 统一转成 error + run.failed
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
        data={"content": final_content, "citations": [], "tool_calls": [], "usage": usage},
    )
    seq += 1
    yield SseEvent(seq=seq, type="run.completed", data={"status": "SUCCEEDED", "usage": usage})
