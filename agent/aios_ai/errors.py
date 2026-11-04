"""统一错误载荷（agent 侧，docs/73）。

与 Java `cn.aios.common.error.ErrorCode` **同一套码、同一套字段**：
`{code, category, message, suggestion, retryable, errorId}`。
前端只看这一份结构，因此「Java 抛的错」和「agent 抛的错」长得一样。

铁律
----
1. **原始信息只进日志**。上游返回的 JSON（含 request_id、密钥片段、模型名）、
   Python 异常类名与堆栈，一律不得出现在响应/事件帧里 —— 用户看不懂，还泄漏内部细节。
2. **每条错误都要有「下一步」**（suggestion）。写不出建议，说明这类错误还没想清楚。
3. **errorId 是给运维对账的**：优先用上游 `request_id`，没有就用本次 trace，
   用户报「错误编号 xxx」，日志里能直接 grep 到。
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# 码表（与 Java ErrorCode 对齐；agent 只用到其中一部分）
# ---------------------------------------------------------------------------
CATEGORY_VALIDATION = "VALIDATION"
CATEGORY_AUTHENTICATION = "AUTHENTICATION"
CATEGORY_PERMISSION = "PERMISSION"
CATEGORY_NOT_FOUND = "NOT_FOUND"
CATEGORY_CONFLICT = "CONFLICT"
CATEGORY_RATE_LIMIT = "RATE_LIMIT"
CATEGORY_UPSTREAM = "UPSTREAM"
CATEGORY_INTERNAL = "INTERNAL"

# code -> (category, 默认文案, 建议)
CATALOG: dict[str, tuple[str, str, str]] = {
    "BAD_REQUEST": (CATEGORY_VALIDATION, "请求内容不合法，本次操作没有执行",
                    "补齐必填项、检查格式后重试"),
    "GUARD_REJECTED": (CATEGORY_VALIDATION, "这次请求被安全护栏拦下了",
                       "把问题拆小一点、去掉疑似越权的指令后重试"),
    "PERMISSION_DENIED": (CATEGORY_PERMISSION, "当前账号没有这个操作的权限",
                          "换用有权限的账号，或让管理员为你开通"),
    "MODEL_UPSTREAM_ERROR": (CATEGORY_UPSTREAM, "模型服务本次没有返回结果",
                             "稍后重试；连续失败请让管理员在「模型配置」里做连通性校验"),
    "MODEL_NOT_FOUND": (CATEGORY_UPSTREAM, "配置的模型已下线或不存在",
                        "管理员在「模型配置」里把模型名换成供应商当前提供的名称（可用其 /models 列表确认）"),
    "MODEL_AUTH_FAILED": (CATEGORY_UPSTREAM, "模型密钥无效或没有调用权限",
                          "到「我的 → 模型账号」检查这个账号的 API Key；或改用平台默认模型"),
    "MODEL_RATE_LIMITED": (CATEGORY_UPSTREAM, "模型调用过于频繁",
                           "等几十秒再试；长期不足请让管理员提高额度"),
    "MODEL_TIMEOUT": (CATEGORY_UPSTREAM, "模型响应超时",
                      "稍后重试；把问题拆小一点（或减少附件）"),
    "MODEL_STREAM_ERROR": (CATEGORY_UPSTREAM, "生成过程中断，内容可能不完整",
                           "重试一次；仍失败请把错误编号发给管理员"),
    "CONNECTOR_ERROR": (CATEGORY_UPSTREAM, "连接的外部应用调用失败",
                        "到「连接器」确认状态为「已连接」，必要时重新授权"),
    "INTERNAL_ERROR": (CATEGORY_INTERNAL, "服务内部出错了，本次操作没有完成",
                       "稍后重试；仍失败请把「错误编号」发给管理员，他能凭它定位到这次请求"),
}

MAX_MESSAGE = 200

_STACK_LINE = re.compile(r"(?m)^\s*(?:File |at )\S.*$")
_FQCN = re.compile(r"\b(?:[A-Za-z_][\w$]*\.){2,}[A-Za-z_$][\w$]*\b")
_SQL = re.compile(r"(?is)\b(select|insert\s+into|update\s+\w+\s+set|delete\s+from|"
                  r"create\s+table|alter\s+table|drop\s+table)\b.{0,180}")
_PATH = re.compile(r"(?:(?:[A-Za-z]:\\|/)[\w.\-]+){2,}[\\/]?[\w.\-]*")
_SECRET = re.compile(r"(?i)\b(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+[A-Za-z0-9._\-]{8,}|"
                     r"(?:password|passwd|pwd|api[_-]?key|secret|token)\s*[=:]\s*[^\s,;\"'}]{3,})")
_REQUEST_ID = re.compile(r'"?request_id"?\s*[:=]\s*"?([A-Za-z0-9\-]{8,})"?')

MODEL_NOT_FOUND_HINTS = ("no longer available", "not found", "does not exist",
                         "model_not_found", "unknown model")


def mask_secrets(text: str | None) -> str | None:
    """日志用：保留结构，抹掉密钥形态的串。"""
    if not text:
        return text
    return _SECRET.sub(lambda m: m.group()[:4] + "***", text)


def sanitize(text: Any, fallback: str) -> str:
    """把异常/上游消息洗成可展示的一句话；洗空了就用兜底文案。"""
    if text is None:
        return fallback
    s = str(text)
    s = _STACK_LINE.sub(" ", s)
    s = mask_secrets(s) or ""
    s = _SQL.sub(" ", s)
    s = _FQCN.sub("", s)
    s = _PATH.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" :;,，。、\t\n'\"")
    if not s:
        return fallback
    return s[:MAX_MESSAGE] + ("…" if len(s) > MAX_MESSAGE else "")


def error_id_of(raw: str | None) -> str | None:
    """从上游 body 里抽 request_id（DeepSeek/MiniMax 都有），供用户报给运维。"""
    if not raw:
        return None
    m = _REQUEST_ID.search(raw)
    return m.group(1) if m else None


def error_payload(code: str, message: str | None = None, suggestion: str | None = None,
                  retryable: bool = False, error_id: str | None = None) -> dict:
    """构造统一错误载荷（只含可外发字段）。"""
    category, default_message, default_suggestion = CATALOG.get(
        code, (CATEGORY_INTERNAL, "服务内部出错了", "稍后重试；仍失败请联系管理员"))
    out: dict[str, Any] = {
        "code": code,
        "category": category,
        "message": sanitize(message, default_message) if message else default_message,
        "suggestion": suggestion or default_suggestion,
        "retryable": bool(retryable),
    }
    if error_id:
        out["errorId"] = error_id
    return out


def upstream_payload(status: int, raw: str | None, model: str | None = None) -> dict:
    """上游非 200 → 统一载荷。**raw 只用于判类型与抽 request_id，不外发。**"""
    text = (raw or "").lower()
    rid = error_id_of(raw)
    if status in (401, 403):
        return error_payload("MODEL_AUTH_FAILED", None, None, retryable=False, error_id=rid)
    if status == 429:
        return error_payload("MODEL_RATE_LIMITED", None, None, retryable=True, error_id=rid)
    if status in (408, 504):
        return error_payload("MODEL_TIMEOUT", None, None, retryable=True, error_id=rid)
    if status == 404 or any(h in text for h in MODEL_NOT_FOUND_HINTS):
        name = f"「{model}」" if model else ""
        return error_payload(
            "MODEL_NOT_FOUND",
            f"配置的模型{name}已下线或不存在",
            f"请管理员在「模型配置」里把模型名{name}换成供应商当前提供的名称"
            "（可用其 /models 列表确认），无需改代码即可生效",
            retryable=False, error_id=rid)
    if status >= 500:
        return error_payload("MODEL_UPSTREAM_ERROR", None, None, retryable=True, error_id=rid)
    return error_payload("MODEL_UPSTREAM_ERROR", None, None, retryable=False, error_id=rid)


def internal_payload(trace_id: str | None = None) -> dict:
    """兜底 5xx：对外零信息，只给错误编号。原始异常由调用方写日志。"""
    return error_payload("INTERNAL_ERROR", None,
                         f"稍后重试；仍失败请把错误编号 {trace_id or '（见服务日志）'} 发给管理员",
                         retryable=True, error_id=trace_id)
