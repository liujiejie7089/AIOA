"""2026-11-07 debug：错误载荷的「编号」「分类」「不外发原文」三条契约。

现场（用户三张截图）：
  1. 用户端连着三条「生成过程中断，内容可能不完整　建议：…请把错误编号发给管理员」，
     却一个编号都没有 —— `facade` 用 `getattr(exc, "trace_id", None)`，普通异常恒为 None，
     `error_payload` 的 `if error_id` 又把字段整个丢掉。
  2. 默认 DeepSeek 402 Insufficient Balance 被泛化成「模型服务本次没有返回结果」，
     管理员不知道要去充值。
  3. 管理端启用 MiniMax 时把上游原始 JSON（含 request_id）整段抖到 toast 上；
     而那个 404 响应体同时带 `insufficient_balance` 与 `no longer available`，
     如果不先判「模型下线」，就会被误报成余额问题。

另有一条同源缺陷：`/internal/v1/runs/{id}/resume` 的 event_stream 里误写
`req.user_context`（本端点参数名是 body），NameError 在 try 之前抛出 ⇒ 空 200。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aios_ai import errors
from app.main import _describe_upstream, app
from tests._svc import svc_headers

client = TestClient(app)
AUTH = svc_headers()

BALANCE_BODY = (
    '{"error":{"message":"Insufficient Balance","type":"insufficient_balance",'
    '"code":402},"request_id":"req-abc12345"}'
)
# 管理端截图的原始响应体：insufficient_balance 与 no longer available 同时出现
NOT_FOUND_BODY = (
    '{"type":"error","error":{"type":"insufficient_balance",'
    '"message":"The model \'MiniMax-M1\' is no longer available. (2013)",'
    '"http_code":"404"},"request_id":"0217546xxxx"}'
)


def test_402_is_balance_not_generic_upstream_error():
    p = errors.upstream_payload(402, BALANCE_BODY, "deepseek-chat")
    assert p["code"] == "MODEL_BALANCE_INSUFFICIENT"
    assert "余额不足" in p["message"]
    assert "充值" in p["suggestion"] or "切换" in p["suggestion"]
    assert p["errorId"] == "req-abc12345"
    assert p["retryable"] is False, "充值前重试没有意义"


def test_model_offline_wins_over_insufficient_balance_in_same_body():
    """404 且 body 同时带两种措辞：必须判「模型已下线」，不能让管理员白去充值。"""
    p = errors.upstream_payload(404, NOT_FOUND_BODY, "MiniMax-M1")
    assert p["code"] == "MODEL_NOT_FOUND"
    assert "MiniMax-M1" in p["message"]
    assert "充值" not in p["suggestion"]
    assert p["errorId"] == "0217546xxxx"


def test_other_upstream_statuses_unchanged():
    assert errors.upstream_payload(401, "x")["code"] == "MODEL_AUTH_FAILED"
    assert errors.upstream_payload(429, "x")["code"] == "MODEL_RATE_LIMITED"
    assert errors.upstream_payload(408, "x")["code"] == "MODEL_TIMEOUT"
    assert errors.upstream_payload(503, "x")["code"] == "MODEL_UPSTREAM_ERROR"


def test_every_fallback_payload_carries_the_id_it_promises():
    """文案里出现「错误编号」的载荷，必须真有同值的 errorId。"""
    for p in (
        errors.stream_payload("run_A"),
        errors.internal_payload("run_A"),
        errors.exception_payload(NameError("req is not defined"), "run_A"),
        errors.exception_payload(TimeoutError(), "run_A"),
        errors.exception_payload(ConnectionError("ConnectError"), "run_A"),
    ):
        assert p.get("errorId") == "run_A", p
    assert "run_A" in errors.stream_payload("run_A")["suggestion"]


def test_default_catalog_suggestion_never_promises_a_missing_id():
    """缺省调用也不许出现「请把错误编号发给管理员」却没有编号的文案。"""
    for code in ("MODEL_STREAM_ERROR", "INTERNAL_ERROR"):
        p = errors.error_payload(code)
        assert "错误编号" not in p["suggestion"], p
        assert "errorId" not in p, p


def test_exception_payload_classifies_by_type_not_one_size_fits_all():
    assert errors.exception_payload(TimeoutError(), "r")["code"] == "MODEL_TIMEOUT"
    assert errors.exception_payload(ConnectionError("ConnectError"), "r")["code"] == "MODEL_UPSTREAM_ERROR"
    assert errors.exception_payload(NameError("req"), "r")["code"] == "INTERNAL_ERROR"


def test_describe_upstream_never_leaks_raw_json_to_admin():
    msg = _describe_upstream(404, NOT_FOUND_BODY, "MiniMax-M1")
    assert "request_id" not in msg
    assert "insufficient_balance" not in msg
    assert "0217546xxxx" not in msg
    assert "MiniMax-M1" in msg, "要点名是哪个模型下线，管理员才知道改哪一行"
    assert "供应商" in msg, "必须给可执行的下一步"


def test_describe_upstream_402_points_to_recharge():
    assert "余额不足" in _describe_upstream(402, BALANCE_BODY, "deepseek-chat")


def test_resume_endpoint_never_returns_empty_200():
    """旧版 NameError 在 try 之前抛出 ⇒ HTTP 200 + 空 body，Java 收不到任何帧。"""
    resp = client.post("/internal/v1/runs/run_no_such_probe/resume",
                       json={"answer": "x"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.text.strip(), "resume 不得再返回空 body"
    assert "event: " in resp.text, "至少要有一帧 SSE"
