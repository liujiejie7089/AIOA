"""内部端点的错误码契约：入参错误必须是 4xx，不能掉进兜底 500。

背景（2026-10-17 实测）：`POST /internal/v1/worker-intent` 收到空 `text` 时抛 `GuardError`，
当时只有 `Exception` 兜底处理器 ⇒ 返回 **500**。调用方 Java `WorkerIntakeService` 收到 5xx
只能当作「agent 故障」降级为本地推断，真实原因（入参空）被埋进 ASGI traceback，
排查时误判为「意图接口本身坏了」。

本文件钉死两条判据：
  1. 空入参 → 400 且 `code=BAD_REQUEST`（可归因到调用方）；
  2. 正常入参 → 200 且带 `role`/`formCode`（证明 4xx 修复没有顺手把正常链路改坏）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests._svc import svc_headers

client = TestClient(app)
# 所有内部端点都要服务间令牌（2026-10-18 起）；本文件验的是「入参错误码」，
# 故统一在模块级备一张票，不重复打扰每个用例。
AUTH = svc_headers()


def test_worker_intent_empty_text_is_400_not_500():
    """空 text 属于调用方错误：必须是 400 + BAD_REQUEST，不能是 500。"""
    resp = client.post("/internal/v1/worker-intent", json={"text": "   "}, headers=AUTH)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["code"] == "BAD_REQUEST"
    assert body["message"], "错误信息不能为空 —— 调用方要据此归因"


def test_worker_intent_missing_text_is_400_not_500():
    """连 text 键都不给，同样按调用方错误处理（而不是 KeyError→500）。"""
    resp = client.post("/internal/v1/worker-intent", json={}, headers=AUTH)
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "BAD_REQUEST"


@pytest.mark.parametrize("text,expect_role", [
    ("帮我创建一个请假审批数字人", "LEAVE_APPROVER"),
    ("我想做一个知识库问答助手", "KB_ASSISTANT"),
    ("帮我写个公文起草数字人", "DOC_DRAFTER"),
])
def test_worker_intent_happy_path_still_200(text: str, expect_role: str):
    """负向对照：4xx 修复不得影响正常分类（role/formCode 仍按 Python 唯一真相返回）。"""
    resp = client.post("/internal/v1/worker-intent", json={"text": text}, headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == expect_role, body
    assert body.get("formCode"), "角色必须带 formCode（字段标签由 Java 侧按表单库补全）"
