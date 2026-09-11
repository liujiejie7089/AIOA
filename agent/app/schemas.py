"""接口数据模型：与 docs/04-接口契约/internal-agent.yaml 严格一致。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PageContext(BaseModel):
    """页面上下文快照（子应用经 SDK 上报）。"""

    appCode: str | None = None
    page: str | None = None
    pageTitle: str | None = None
    entityType: str | None = None
    entityId: str | None = None
    filters: dict[str, Any] | None = None
    selection: list[str] | None = None


class UserContext(BaseModel):
    """用户上下文（必填 user_id / tenant_id / roles）。"""

    user_id: int
    tenant_id: int
    username: str | None = None
    roles: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class RunRequest(BaseModel):
    """POST /internal/v1/runs 请求体。"""

    run_id: str
    conversation_id: int
    text: str
    attachments: list[int] | None = None
    context: PageContext | None = None
    agent_code: str | None = None
    model_ref: str | None = None
    user_context: UserContext
    history: list[dict[str, Any]] | None = None
    # 发起方用户 accessToken（M2 工具回调）：调用业务工具网关时透传，工具权限 = 用户权限
    user_token: str | None = None
    # 职责范围（V21）：会话绑定数字员工时下发，用于限定回答边界（越界拒答）
    # 键：worker_id / name / role / role_name / duty / permission
    scope: dict[str, Any] | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class CompleteRequest(BaseModel):
    """POST /internal/v1/complete 请求体（非流式单轮补全，供数字员工定时任务等内部调用）。"""

    prompt: str
    system: str | None = None
    model_ref: str | None = None
    max_tokens: int | None = None


class CompleteResponse(BaseModel):
    content: str
    model: str
    usage: Usage = Field(default_factory=Usage)


class SseEvent(BaseModel):
    """SSE 事件：seq 单调递增，type 即 SSE event 名，data 为 JSON 对象。"""

    seq: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
