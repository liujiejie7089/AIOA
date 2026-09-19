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
    # 专家生效配置（方案 P4 / B5）：由后端 ExpertConfigService.resolve 下发，
    # 键：enabled/visibleScope/kbScope/model/temperature/topK/threshold/retrievalMode/tools/sort/chunkSize/chunkOverlap
    # agent 据此真实驱动推理与检索，并把最终值回传 message.completed.effective_params。
    expert_settings: dict[str, Any] | None = None


class SubTaskSpec(BaseModel):
    """多任务协同中的一个子任务（POST /internal/v1/tasks）。

    ``dependsOn`` 里的 id 全部成功后本任务才开始；入参里的 ``"$taskId"`` /
    ``"$taskId.field"`` 会被替换成前序任务的产出 —— 依赖关系的表达放在计划里，
    不靠模型再推理一轮。
    """

    id: str
    title: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependsOn: list[str] = Field(default_factory=list)


class TaskPlanRequest(BaseModel):
    """POST /internal/v1/tasks 请求体：一份显式的多任务执行计划。"""

    run_id: str
    conversation_id: int = 0
    text: str | None = None
    user_context: UserContext
    user_token: str | None = None
    tasks: list[SubTaskSpec] = Field(default_factory=list)
    max_concurrency: int | None = None


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
