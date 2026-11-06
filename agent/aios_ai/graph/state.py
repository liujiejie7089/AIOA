"""LangGraph 图状态定义。

设计约定：
  - 状态里**只放可序列化的数据**（dict / list / 原始类型），不放 httpx 客户端等运行时对象。
    当前缺省**不挂** checkpointer（见 builder.py），但状态仍按「可序列化」约束设计：
    一旦接上持久化 checkpointer（HITL 暂停/续跑），整份状态可以直接落盘 ——
    未注册的类实例会被 msgpack serde 直接拒绝（曾实测踩到 ToolClient 这一条）。
  - 运行期对象（WallClock、ToolClient）**在需要它的节点内按需重建**（见 nodes._clock /
    nodes.tools），状态里只留重建所需的原始字段（如 started_at、req.user_token）；
  - HTTP 客户端在需要它的节点内即用即建（一次 run 只多建几次，相对模型调用开销可忽略）。
  - ``req`` 存 **dict**（``RunRequest.model_dump()``）而非 pydantic 实例：挂上 HITL 的
    checkpointer 后整份状态要落盘，未注册的类实例会被 serde 告警并「未来版本直接拦截」；
    节点内用 ``RunRequest.model_validate(state["req"])`` 还原（见 nodes._req）。
"""
from __future__ import annotations

from typing import Any, TypedDict


class RunState(TypedDict, total=False):
    """一次 run 在图内流转的状态。"""

    # ---- 入参 ----
    req: dict                    # RunRequest.model_dump()（可序列化；节点内还原为模型对象）

    # ---- prepare 产出 ----
    messages: list[dict]         # 发给模型的消息列表（system + history + user）
    tools: list[dict]            # 候选工具（OpenAI function 格式）
    provider_key: str
    provider_model: str
    temperature: float
    search_params: tuple         # (top_k, threshold, retrieval_mode, kb_scope)
    effective: dict              # 回传前端的生效参数
    fatal: dict | None           # 致命错误（如 provider 未配置）：置位后直接结束，不调模型
    citations: list[dict]        # 引用溯源条目
    entity_candidates: list[dict]  # 「模糊的人」预取到的候选人（连接器无关，见 tools/entity_clarify）
    entity_source: str           # 候选来源：contact（通讯录）/ mail（最近邮件发件人）/ ""（没查）
    # 请假发起：prepare 阶段从 `available_forms` 挑好表单码后合成的 request_form 调用。
    # 存**成品调用**而不是候选本身，是因为它不是"要不要问"的判断，而是"已经确定要开哪张表"；
    # 让 agent 节点直接抛出去，避免两处各拼一次参数导致形状漂移。
    # ★ 只带 {form_code, reason, prefill}：字段由 Java 从 form_template 补全（单一事实源）。
    leave_form: dict | None      # None = 本轮不是请假发起（既有链路零影响）

    # ---- 循环态 ----
    agent_rounds: int            # 已调模型的次数
    allow_tools: bool            # 本次 agent 调用是否挂工具（达到上限后为 False）
    pending_calls: list[dict]    # 本轮模型给出的 tool_calls
    content_parts: list[str]     # 正文分片（累计）
    tool_calls_log: list[dict]   # 工具调用日志（回传前端）
    usage: dict                  # token 用量（多轮累加）
    clarifications: list[dict]   # 本轮 run 内发生过的 HITL 回填，供审计与回传。
                                  # 两种形状都允许（同走 interrupt/resume 底座，不新建状态机）：
                                  #   - ask_user 澄清：{"question": str, "answer": 标量}
                                  #   - request_form 表单：{"form_code": str, "answer": 回执对象}

    # ---- 内部通道（不在对外契约里；LangGraph 要求节点写回的每个键都在 schema 中声明）----
    started_at: float            # 墙钟起点（time.monotonic()）。存 float 而非 WallClock 实例，
                                 # 是为了让整份状态可被 checkpointer 序列化（持久化 checkpoint 的前提）
    _assistant_message: dict     # 本轮 assistant 原始消息（供 tools 节点回注上下文）
