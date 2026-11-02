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
#
# 2026-11-02（第二轮）：把「补充说明」并进同一张卡。
# 现场问题：用户选完「小亮」后，模型还要再问一句「请告诉我您要发送的内容」——
# 一次任务被拆成三次往返（选人 → 填内容 → 再说一次），而且中途上下文就断了。
# 现在选项可以声明 `needs_text`：**选中它就当场出现输入框**，选项与补充内容
# 在**同一个确认动作**里一起提交（`{value,label,text}` 一次 resume 回填）。
ASK_USER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": ASK_USER_TOOL_NAME,
        "description": (
            "当你缺少完成用户请求所必需的关键参数、或用户意图模糊到无法确定该做什么时，"
            "调用本工具向用户提出**一个**单选题，然后停下等待用户选择。"
            "仅在确实无法继续时使用；不要用它追问次要细节，更不要凭猜测编造默认值继续执行。"
            "一次只问一个问题。"
            "**如果选定某项之后还需要用户补一句内容才能继续**（例如选完收件人还要知道发什么），"
            "把该项标成 `needs_text: true` 并给出文案 —— 用户会在同一次交互里把内容一起填完，"
            "不要选完再追问一轮。"
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
                            "needs_text": {
                                "type": "boolean",
                                "description": (
                                    "选中本项后是否还需要用户补一段文字才能继续。"
                                    "为 true 时界面上会**动态出现**输入框，且必须填写才能确认。"
                                ),
                            },
                            "text_label": {
                                "type": "string",
                                "description": "needs_text 时输入框的标题，例如「要发送的内容」。",
                            },
                            "text_placeholder": {
                                "type": "string",
                                "description": "needs_text 时输入框的提示语，给一个具体例子最好。",
                            },
                        },
                        "required": ["value", "label"],
                    },
                },
                "text_input": {
                    "type": "object",
                    "description": (
                        "卡级补充输入：不针对某个选项、而是这一问本身就需要一段文字时用"
                        "（例如「请描述一下具体需求」）。与选项可同时存在，一次提交。"
                    ),
                    "properties": {
                        "label": {"type": "string", "description": "输入框标题。"},
                        "placeholder": {"type": "string", "description": "提示语/例子。"},
                        "required": {"type": "boolean", "description": "是否必须填写才能确认，默认 false。"},
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


def _as_options(raw: Any) -> list[dict[str, Any]]:
    """把模型给的 options 归一成 ``[{value, label, needs_text?, text_label?, text_placeholder?}]``。

    容错：选项可能是 ``{"value","label"}``，也可能只给了字符串；缺失/非法一律丢弃。
    少于 2 个有效选项时仍返回（图会以「仅有一个继续选项」的方式兜底），
    但绝不编造选项 —— 追问内容的真伪必须来自模型，不能由代码臆造。

    ``needs_text`` 一族字段**只在显式给出时**才带上：老前端/老断言看到的形状与改造前
    逐字节一致（多出来的键只在用到时才出现，不会把既有载荷撑大）。
    """
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            out.append({"value": item, "label": item})
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("value") or "").strip()
            value = str(item.get("value") or label).strip()
            if not (label or value):
                continue
            opt: dict[str, Any] = {"value": value or label, "label": label or value}
            if item.get("needs_text") is True:
                opt["needs_text"] = True
                tl = str(item.get("text_label") or "").strip()
                tp = str(item.get("text_placeholder") or "").strip()
                if tl:
                    opt["text_label"] = tl
                if tp:
                    opt["text_placeholder"] = tp
            out.append(opt)
        if len(out) >= MAX_OPTIONS:  # 与 H5 clarCardHtml 的 slice 上限必须一致
            break
    return out


def _as_text_input(raw: Any) -> dict[str, Any] | None:
    """卡级补充输入归一。没有就返回 None（保持旧载荷形状完全不变）。"""
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip() or "补充说明"
    placeholder = str(raw.get("placeholder") or "").strip()
    spec: dict[str, Any] = {"label": label, "required": raw.get("required") is True}
    if placeholder:
        spec["placeholder"] = placeholder
    return spec


def build_clarification(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """把 ``ask_user`` 的入参归一成 ``need_clarification`` 事件载荷。

    返回 ``{"question", "suggested_options", "text_input"?}``。
    ``text_input`` 只在模型真的给了时才出现 —— 老载荷形状不变。
    """
    args = arguments or {}
    question = str(args.get("question") or "").strip() or "请补充必要信息后继续。"
    spec: dict[str, Any] = {
        "question": question,
        "suggested_options": _as_options(args.get("options")),
    }
    ti = _as_text_input(args.get("text_input"))
    if ti:
        spec["text_input"] = ti
    return spec
