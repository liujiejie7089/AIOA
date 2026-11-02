"""``ask_user`` —— 模型主动向用户提问的**内置控制工具**（HITL 澄清）。

与业务工具的根本区别：它**不由业务工具网关执行**。模型一旦调用它，图在 ``clarify``
节点调用 LangGraph 的 ``interrupt()`` 暂停运行，把「问题 + 互斥选项」作为
``need_clarification`` 事件发给前端；用户选择后经 ``resume`` 把答案塞回图里继续跑。

契约对齐（docs/04-接口契约/internal-agent.yaml 第 133 行）::

    need_clarification: { question, suggested_options }

本模块只负责两件事：给模型的工具 schema（入参 ``question`` + ``options[]``），以及把
模型给出的 ``arguments`` 归一成契约要的形状。**不**在这里做中断 —— 中断是图的语义，
放在 ``aios_ai/graph/nodes.py`` 的 ``clarify`` 节点里（单一判定点）。
"""
from __future__ import annotations

from typing import Any

# 工具名（模型可见；也是 Java 侧识别「这是澄清、不是业务工具」的依据）
ASK_USER_TOOL_NAME = "ask_user"

# 选项上限：2026-11-02 由 6 提到 10。
# 起因是「同事」类模糊实体的澄清需要把通讯录命中的候选列成按钮（产品口径：候选 ≤10 条，
# 超过就不弹按钮、先让用户补条件）。原来 6 的上限**静默截断**——第 7~10 个候选会被丢掉，
# 而模型以为已经列全了，用户就等于选不到人。H5 侧同步 slice(0,10)，两处必须一致。
MAX_OPTIONS = 10

# 给模型的 function-calling schema。描述里强调「只在一个问题、确实无法继续时才用」，
# 避免模型拿它当万能追问、把简单请求也拆成多轮。
ASK_USER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ASK_USER_TOOL_NAME,
        "description": (
            "当你缺少完成用户请求所必需的关键参数、或用户意图模糊到无法确定该做什么时，"
            "调用本工具向用户提出**一个**单选题，然后停下等待用户选择。"
            "仅在确实无法继续时使用；不要用它追问次要细节，更不要凭猜测编造默认值继续执行。"
            "一次只问一个问题。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题，一句话说清。"},
                "options": {
                    "type": "array",
                    "description": (
                        "2~10 个互斥选项，供用户单选。**确实一个候选都没有时留空**"
                        "（界面上会渲染成一个输入框让用户自己填），"
                        "但只要有候选就必须列出来 —— 不要为了省事留空让用户手打。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "string", "description": "选项取值（回传给系统的机器值）。"},
                            "label": {"type": "string", "description": "选项展示文案（给人看）。"},
                        },
                        "required": ["value", "label"],
                    },
                },
            },
            # options 不再 required（2026-11-02）：「我同事」这种完全没给姓名片段的问法
            # 在通讯录里**没有任何关键词可搜**（search 的 keywords 必填），此时既不能猜、
            # 也不该用正文反问一句了事。留空 ⇒ H5 的 clarCardHtml 走 else 分支渲染
            # `.clar-free` 输入框，用户填完仍走 resume 回填，比正文反问多一个可交互控件。
            "required": ["question"],
        },
    },
}


def is_ask_user(name: str | None) -> bool:
    """该工具名是否为本内置澄清工具。"""
    return (name or "") == ASK_USER_TOOL_NAME


def _as_options(raw: Any) -> list[dict[str, str]]:
    """把模型给的 options 归一成 ``[{value, label}]``。

    容错：选项可能是 ``{"value","label"}``，也可能只给了字符串；缺失/非法一律丢弃。
    少于 2 个有效选项时仍返回（图会以「仅有一个继续选项」的方式兜底），
    但绝不编造选项 —— 追问内容的真伪必须来自模型，不能由代码臆造。
    """
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if isinstance(item, str):
            out.append({"value": item, "label": item})
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("value") or "").strip()
            value = str(item.get("value") or label).strip()
            if label or value:
                out.append({"value": value or label, "label": label or value})
        if len(out) >= MAX_OPTIONS:  # 与 H5 clarCardHtml 的 slice 上限必须一致
            break
    return out


def build_clarification(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """把 ``ask_user`` 的入参归一成 ``need_clarification`` 事件载荷。

    返回 ``{"question": str, "suggested_options": [{"value","label"}]}``。
    """
    args = arguments or {}
    question = str(args.get("question") or "").strip() or "请补充必要信息后继续。"
    return {"question": question, "suggested_options": _as_options(args.get("options"))}
