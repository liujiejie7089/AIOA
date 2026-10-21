"""``request_form`` —— 模型主动请用户填一张业务表单的**内置控制工具**（HITL 表单）。

与 ``ask_user`` 同源：都不由业务工具网关执行。模型调用它 ⇒ 图在 ``clarify`` 节点
``interrupt()`` 暂停，把 ``need_form`` 帧发给前端；用户在表单里提交后，由 **Java 侧**
把表单回执经 ``resume`` 塞回图里继续。

与 ``ask_user`` 的区别（两条 HITL 链共用 interrupt/resume/checkpoint 底座，不新建状态机）：
  - ``ask_user`` 取**标量**答案（选项 value / 自由文本）→ ``need_clarification`` 帧；
  - ``request_form`` 取**整张表单回执对象** → ``need_form`` 帧；

单一事实源约束（关键）：表单定义（字段、校验、选项）在 **Java / DB**，agent 侧**没有**
这个数据源，因此本模块**只产出** ``{form_code, reason, prefill}`` 这一层——
**绝不**在 agent 里查表单定义、**绝不**生成 ``fields[]``（由 Java 侧补全，保持单一事实源）。

本模块只负责两件事：给模型的工具 schema（入参 ``form_code`` + ``reason`` + ``prefill``），
以及把模型给出的 ``arguments`` 归一成 ``need_form`` 事件载荷。**不**在这里做中断 ——
中断是图的语义，放在 ``aios_ai/graph/nodes.py`` 的 ``clarify`` 节点里（单一判定点）。
"""
from __future__ import annotations

from typing import Any

# 工具名（模型可见；也是 Java 侧识别「这是表单请求、不是业务工具」的依据）
REQUEST_FORM_TOOL_NAME = "request_form"

# 给模型的 function-calling schema。描述里强调「一次只请求一张表单」与
# 「form_code 必须来自可用表单清单（拿不到就不调）」，把表单定义的来源明确推给 Java/DB。
REQUEST_FORM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REQUEST_FORM_TOOL_NAME,
        "description": (
            "当需要用户填写一张业务表单（例如请假单、报销单）才能继续处理时，调用本工具"
            "向用户请求一张表单。一次只请求一张表单。form_code 必须来自当前可用表单清单"
            "（不确定有哪些表单时不要调用本工具）。调用后你会暂停等待用户提交表单，"
            "表单回执会作为答案回填给你继续。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "form_code": {
                    "type": "string",
                    # ⚠️ 这里**不要**写具体 code 当例子。2026-10-18 实测：原文写「如 leave_request」，
                    # 模型在只下发 meeting_book 的情况下仍产出 form_code=leave_request，
                    # 结果会议助手弹出了请假表单。示例比清单更容易被照抄 —— 只描述来源，不给样例。
                    "description": "表单编码，必须逐字复制【可用表单清单】里的 code，禁止自拟或套用其它表单。",
                },
                "reason": {
                    "type": "string",
                    "description": "为什么需要这张表单（展示给用户，说明用途）。",
                },
                "prefill": {
                    "type": "object",
                    "description": (
                        "调用本工具前，必须先把用户原话中已明确给出的信息提取为「字段名: 值」"
                        "填入本对象（键必须是该表单的真实字段名，值用用户原话或等价表述）。"
                        "可提取的信息包括但不限于：时间、事项、主题、标题、正文、金额、人员、地点等。"
                        "只有用户原话确实不包含任何可用字段值时，才传空对象 {}。"
                        "禁止在已识别出内容的情况下传空 prefill；由 Java 侧决定最终是否采纳。"
                        "例：用户说「发布一则通知，明天中午开会」，应把事项映射到标题/正文、"
                        "把时间映射到有效期等对应字段后再调用本工具。"
                    ),
                },
            },
            "required": ["form_code"],
        },
    },
}


def is_request_form(name: str | None, args: Any = None) -> bool:
    """该工具名是否为本内置表单工具。（``args`` 透传以对齐 ask_user 的判定签名，此处仅看名字。）"""
    return (name or "") == REQUEST_FORM_TOOL_NAME


def build_form_request(arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    """把 ``request_form`` 的入参归一成 ``need_form`` 事件载荷（agent 侧只产出这一层）。

    返回 ``{"kind": "form", "form_code": str, "reason": str, "prefill": dict}``；
    归一化规则：
      - ``form_code`` 必填且非空，否则返回 ``None``（图会把这个工具调用当「无效内置调用」剔除，不暂停）；
      - ``reason`` 字符串，缺省为空串；
      - ``prefill`` 必须是 dict，否则丢弃为 ``{}``（绝不擅自制造字段）。

    不查表单定义、不生成 ``fields[]``：表单定义在 Java / DB，agent 无此数据源，
    字段补充由 Java 侧完成（单一事实源）。
    """
    args = arguments or {}
    form_code = str(args.get("form_code") or "").strip()
    if not form_code:
        return None
    prefill = args.get("prefill")
    if not isinstance(prefill, dict):
        prefill = {}
    reason = str(args.get("reason") or "").strip()
    return {"kind": "form", "form_code": form_code, "reason": reason, "prefill": prefill}
