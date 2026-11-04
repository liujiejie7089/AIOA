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


def _max_attempts(provider=None) -> int:
    """总尝试次数（含首次）。优先级：模型配置 > 环境变量 AIOS_MODEL_RETRY_ATTEMPTS > 3。"""
    if provider is not None:
        try:
            n = int(getattr(provider, "retry_attempts", 0) or 0)
            if n > 0:
                return max(1, min(n, 5))
        except (TypeError, ValueError):
            pass
    try:
        n = int(os.environ.get("AIOS_MODEL_RETRY_ATTEMPTS", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 5))


def _request_timeout(provider) -> float:
    """单次上游请求超时（秒）：模型配置优先，缺省 120。"""
    try:
        t = float(getattr(provider, "timeout_seconds", 0) or 0)
    except (TypeError, ValueError):
        t = 0
    return t if t > 0 else 120.0


def _sampling_params(provider, temperature: float, max_tokens: int | None = None) -> dict:
    """组装采样参数：**只在配了值时才下发**。

    为什么「0 不下发」而不是「下发 0」：多数 OpenAI 兼容网关把 top_p=0 当非法参数
    直接 400，把 max_tokens=0 当「不要输出」。所以 0/NULL 一律视为「沿用供应商默认」，
    这也是两端表单里 0 的含义（docs/72 §2）。
    """
    body: dict = {"temperature": float(temperature)}
    top_p = getattr(provider, "top_p", None)
    if top_p not in (None, ""):
        try:
            v = float(top_p)
            if 0 < v <= 1:
                body["top_p"] = v
        except (TypeError, ValueError):
            pass
    tokens = max_tokens if max_tokens not in (None, 0) else int(getattr(provider, "max_tokens", 0) or 0)
    if tokens and int(tokens) > 0:
        body["max_tokens"] = int(tokens)
    pp = float(getattr(provider, "presence_penalty", 0) or 0)
    if pp:
        body["presence_penalty"] = pp
    fp = float(getattr(provider, "frequency_penalty", 0) or 0)
    if fp:
        body["frequency_penalty"] = fp
    return body


def _backoff_seconds(attempt_index: int) -> float:
    """指数退避：0.8s / 1.6s（不引入随机抖动，便于测试断言）。"""
    return 0.8 * (2 ** attempt_index)


class UpstreamError(RuntimeError):
    """上游模型非 200：转 MODEL_* 系列（其余异常仍归 MODEL_STREAM_ERROR）。

    2026-11-04 起不再自带「用户文案」，改为交给 `aios_ai.errors.upstream_payload()`
    统一映射 —— 文案与错误码只在一处维护，避免「Java 说 A、agent 说 B」。
    """

    def __init__(self, status: int, text: str, model: str | None = None):
        super().__init__(f"status={status} {text[:200]}")
        self.status = status
        self.text = text
        self.model = model

    @property
    def retryable(self) -> bool:
        return self.status in _RETRYABLE_STATUS

    @property
    def payload(self) -> dict:
        """统一错误载荷（可外发）：只含 code/category/message/suggestion/retryable/errorId。"""
        from aios_ai import errors as err

        return err.upstream_payload(self.status, self.text, self.model)

    @property
    def error_code(self) -> str:
        return str(self.payload["code"])

    @property
    def user_message(self) -> str:
        """给人看的一句话（向后兼容旧调用点）。原始 JSON 只进日志。"""
        return str(self.payload["message"])


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
    attempts = _max_attempts(provider)
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
                  "stream_options": {"include_usage": True}}
    body.update(_sampling_params(provider, temperature))
    if tools:
        body["tools"] = tools
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
               "Accept": "text/event-stream"}

    content_parts: list[str] = []
    acc: dict[int, dict] = {}
    usage: dict = {}
    async with client_http.stream("POST", url, json=body, headers=headers,
                                  timeout=_request_timeout(provider)) as resp:
        if resp.status_code != 200:
            try:
                raw = await resp.aread()
                text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
            except Exception:  # 读不出 body 也要带上状态码，便于定位
                text = ""
            raise UpstreamError(resp.status_code, text, getattr(provider, "model", None))
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
                                    f"{base.get('status_msg') or ''}",
                                    getattr(provider, "model", None))
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
    attempts = _max_attempts(provider)
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
    body: dict = {"model": provider.model, "messages": messages, "stream": False}
    # 采样参数统一由 _sampling_params 组装（配了才下发）；显式 max_tokens 优先于模型配置
    body.update(_sampling_params(provider, temperature, max_tokens))
    if tools:
        body["tools"] = tools
    resp = await client_http.post(
        provider.base_url.rstrip("/") + "/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=_request_timeout(provider),
    )
    if resp.status_code != 200:
        raise UpstreamError(resp.status_code, resp.text or "", getattr(provider, "model", None))
    try:
        data = resp.json()
    except Exception as exc:  # 200 但 body 不是 JSON（网关插页/被劫持）：按上游故障上报
        raise UpstreamError(502, f"非 JSON 响应：{exc}｜{resp.text[:120]}",
                                getattr(provider, "model", None)) from exc
    # ⚠️ MiniMax 的 OpenAI 兼容接口即使 HTTP 200，也可能在 base_resp.status_code 里报错
    # （实测 `1000 = unknown error`）。只看 HTTP 码会把这种失败当成成功，
    # 结果是一轮「成功」的空回答 —— 用户看到「本次未返回内容」却查不到原因。
    base = data.get("base_resp") or {}
    code = base.get("status_code")
    if code not in (None, 0):
        raise UpstreamError(int(base.get("status_code") or 500),
                            f"base_resp={code} {base.get('status_msg') or ''}",
                            getattr(provider, "model", None))
    message = (data.get("choices") or [{}])[0].get("message") or {}
    usage = data.get("usage") or {}
    return message, usage
