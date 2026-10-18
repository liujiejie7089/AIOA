"""上游模型调用层：OpenAI 兼容 /chat/completions 的流式与非流式两种打法。

原寄居在 `app/core/agent_runtime.py`。独立出来的理由：
  - 这是**协议适配**（HTTP + SSE 分片重组），与「智能体怎么决策」无关；
  - 换编排框架（如 LangGraph）时，这一层不该跟着重写；
  - `app/main.py` 的 `/internal/v1/complete`（非流式单轮补全）也复用它，
     若留在运行时里会造成「非流式端点依赖智能体运行时」的倒挂依赖。

调用方只关心：拿到 assistant message（含 tool_calls）与 usage。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

# OpenAI 兼容 /chat/completions 的 SSE 行前缀与结束标记
_DATA_PREFIX = "data: "
_DONE_MARK = "[DONE]"


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
