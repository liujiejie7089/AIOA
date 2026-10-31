"""上游模型调用层：OpenAI 兼容 /chat/completions 的流式与非流式两种打法。

原寄居在 `app/core/agent_runtime.py`。独立出来的理由：
  - 这是**协议适配**（HTTP + SSE 分片重组），与「智能体怎么决策」无关；
  - 换编排框架（如 LangGraph）时，这一层不该跟着重写；
  - `app/main.py` 的 `/internal/v1/complete`（非流式单轮补全）也复用它，
     若留在运行时里会造成「非流式端点依赖智能体运行时」的倒挂依赖。

调用方只关心：拿到 assistant message（含 tool_calls）与 usage。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger("aios.ai.llm")

# OpenAI 兼容 /chat/completions 的 SSE 行前缀与结束标记
_DATA_PREFIX = "data: "
_DONE_MARK = "[DONE]"

# 值得重试的上游状态码。MiniMax 的 5xx 多为瞬时故障（实测 2026-10-31：
# `HTTP 500 {"type":"server_error","message":"unknown error, 999 (1000)"}`，
# 同一份请求体隔几秒重发就 200）。原先一遇 500 就直接把裸 JSON 甩给用户，
# 用户看到的是「生成失败：{...request_id...}」，实际什么都没做错。
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def _max_attempts() -> int:
    """总尝试次数（含首次）。默认 3 = 首次 + 2 次重试；AIOS_MODEL_RETRY_ATTEMPTS 可调。"""
    try:
        n = int(os.environ.get("AIOS_MODEL_RETRY_ATTEMPTS", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 5))


def _backoff_seconds(attempt_index: int) -> float:
    """指数退避：0.8s / 1.6s（不引入随机抖动，便于测试断言）。"""
    return 0.8 * (2 ** attempt_index)


class UpstreamError(RuntimeError):
    """上游模型非 200：转 MODEL_UPSTREAM_ERROR（其余异常仍归 MODEL_STREAM_ERROR）。"""

    def __init__(self, status: int, text: str):
        super().__init__(f"status={status} {text[:200]}")
        self.status = status
        self.text = text

    @property
    def retryable(self) -> bool:
        return self.status in _RETRYABLE_STATUS

    @property
    def user_message(self) -> str:
        """给人看的一句话。原始 JSON 留在日志里，不要甩到界面上。

        原先 facade 直接 `str(exc)[:200]`，用户看到的是
        `生成失败：status=500 {"code":"MODEL_UPSTREAM_ERROR",...request_id...}` ——
        既看不懂也不知道该怎么办（2026-10-31 用户现场截图）。
        """
        if self.status in (401, 403):
            return "模型密钥无效或无权限（HTTP %d），请联系管理员检查模型配置。" % self.status
        if self.status == 429:
            return "模型调用过于频繁（HTTP 429），请稍后重试。"
        if self.status in (408, 504):
            return "模型服务响应超时（HTTP %d），请稍后重试或把问题拆小一点。" % self.status
        if self.status >= 500:
            return "模型服务暂时不可用（HTTP %d），已自动重试仍失败，请稍后重试。" % self.status
        return "上游模型拒绝了本次请求（HTTP %d）。" % self.status


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
    """流式推理一轮，**带瞬时可重试**：先产出 ("delta", text) ×N，最后 ("done", message, usage)。

    为什么用流式替代「非流式取回后本地切片」：本地切片只是把等待时间挪到了第一个
    delta 之前，用户在长回答上仍要干等整段生成完；流式让首字延迟等于上游首个分片
    的到达时间。事件契约（message.delta ×N）保持不变，前端零改动。

    重试边界（关键）
    ----------------
    只在「一个 delta 都还没吐出去」时重试。一旦已经把正文推给用户，再发一遍
    就是同一段回答出现两次 —— 那比重试失败更糟。5xx/429 是在读第一个分片之前
    抛的（`resp.status_code != 200` 的检查在循环之前），所以天然安全；
    但**中途断流**（已经 yield 过 delta 再抛 UpstreamError/网络错）必须原样抛出。
    """
    attempts = _max_attempts()
    for attempt in range(attempts):
        emitted = False
        try:
            async for item in _post_stream_once(client_http, provider, api_key,
                                                messages, tools, temperature):
                if item[0] == "delta":
                    emitted = True
                yield item
            return
        except UpstreamError as exc:
            if emitted or not exc.retryable or attempt == attempts - 1:
                raise
            logger.warning("上游模型 HTTP %s（第 %d/%d 次尝试）⇒ %.1fs 后重试：%s",
                           exc.status, attempt + 1, attempts,
                           _backoff_seconds(attempt), exc)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # 连接层失败同理：只在没吐过正文时重试。
            if emitted or attempt == attempts - 1:
                raise
            logger.warning("上游模型连接失败（第 %d/%d 次尝试）⇒ %.1fs 后重试：%s",
                           attempt + 1, attempts, _backoff_seconds(attempt), exc)
        await asyncio.sleep(_backoff_seconds(attempt))


async def _post_stream_once(client_http: httpx.AsyncClient, provider, api_key: str,
                            messages: list[dict], tools: list[dict] | None,
                            temperature: float) -> AsyncIterator[tuple]:
    """单次流式请求（不含重试）。"""
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
            # 与 _post_non_stream_once 同口径：MiniMax 流式也会在分片里带 base_resp 错误
            # （HTTP 200 + base_resp.status_code=1000）。不判它就会「成功」收口成空回答。
            base = chunk.get("base_resp") or {}
            if base.get("status_code") not in (None, 0):
                raise UpstreamError(int(base.get("status_code") or 500),
                                    f"base_resp={base.get('status_code')} "
                                    f"{base.get('status_msg') or ''}")
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
    """非流式推理一轮，返回 (assistant_message, usage)。非 200 抛 UpstreamError。

    与流式同口径做瞬时重试（非流式天然幂等，重试没有重复输出的风险）。
    """
    attempts = _max_attempts()
    for attempt in range(attempts):
        try:
            return await _post_non_stream_once(client_http, provider, api_key,
                                               messages, tools, temperature, max_tokens)
        except UpstreamError as exc:
            if not exc.retryable or attempt == attempts - 1:
                raise
            logger.warning("上游模型 HTTP %s（第 %d/%d 次尝试）⇒ %.1fs 后重试：%s",
                           exc.status, attempt + 1, attempts,
                           _backoff_seconds(attempt), exc)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt == attempts - 1:
                raise
            logger.warning("上游模型连接失败（第 %d/%d 次尝试）⇒ %.1fs 后重试：%s",
                           attempt + 1, attempts, _backoff_seconds(attempt), exc)
        await asyncio.sleep(_backoff_seconds(attempt))
    raise UpstreamError(503, "retry exhausted")  # 理论不可达：循环内必 return 或 raise


async def _post_non_stream_once(client_http: httpx.AsyncClient, provider, api_key: str,
                                messages: list[dict], tools: list[dict] | None,
                                temperature: float, max_tokens: int | None) -> tuple[dict, dict]:
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
    try:
        data = resp.json()
    except Exception as exc:  # 200 但 body 不是 JSON（网关插页/被劫持）：按上游故障上报
        raise UpstreamError(502, f"非 JSON 响应：{exc}｜{resp.text[:120]}") from exc
    # ⚠️ MiniMax 的 OpenAI 兼容接口即使 HTTP 200，也可能在 base_resp.status_code 里报错
    # （实测 `1000 = unknown error`）。只看 HTTP 码会把这种失败当成成功，
    # 结果是一轮「成功」的空回答 —— 用户看到「本次未返回内容」却查不到原因。
    base = data.get("base_resp") or {}
    code = base.get("status_code")
    if code not in (None, 0):
        raise UpstreamError(int(base.get("status_code") or 500),
                            f"base_resp={code} {base.get('status_msg') or ''}")
    message = (data.get("choices") or [{}])[0].get("message") or {}
    usage = data.get("usage") or {}
    return message, usage
