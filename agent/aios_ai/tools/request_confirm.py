"""``request_confirm`` —— 模型请用户对「即将发生的动作」做二选一决策的**内置控制工具**（HITL 确认）。

与 ``ask_user`` / ``request_form`` 同源：都不由业务工具网关执行。模型调用它 ⇒ 图在
``clarify`` 节点 ``interrupt()`` 暂停，把 ``need_confirm`` 帧发给前端；用户点「确认 / 取消」
后经 ``resume`` 把 ``answer={"decision": true|false}`` 塞回图里继续。

三条链的分工（共用 interrupt/resume/checkpoint 底座，不新建状态机）：
  - ``ask_user``        取**标量**答案（选项 value / 自由文本）→ ``need_clarification`` 帧；
  - ``request_form``    取**表单回执对象**               → ``need_form`` 帧；
  - ``request_confirm`` 取**二值决策**（确认 / 取消）      → ``need_confirm`` 帧。

为什么要单独一条链（而不是让 ask_user 带两个选项）
------------------------------------------------
ask_user 的选项是**单选题**，用户要「先选中一个再点确认」两步；而确认是**二值**的，
界面上必须同时给出两个按钮、点一下即生效、点了就禁用（不能有机会重复提交）。
把确认做成 ask_user 的选项会让 UI 语义错位（还要多选一次），也让「危险操作」的高亮样式无处安放。

本模块只负责两件事：给模型的工具 schema，以及把模型给出的 ``arguments`` 归一成契约形状。
**不**在这里做中断 —— 中断是图的语义，放在 ``aios_ai/graph/nodes.py`` 的 ``clarify`` 节点里（单一判定点）。
"""
from __future__ import annotations

from typing import Any

# 工具名（模型可见；也是 Java 侧识别「这是确认请求、不是业务工具」的依据）
REQUEST_CONFIRM_TOOL_NAME = "request_confirm"

# 按钮文案上限： UI 上是短按钮，超长会撑破气泡布局；超长一律退回默认文案（绝不截断成半个词）。
_LABEL_MAX = 10
_DEFAULT_CONFIRM_LABEL = "确认"
_DEFAULT_CANCEL_LABEL = "取消"
_DEFAULT_TITLE = "请确认是否继续"

# 给模型的 function-calling schema。
# 描述里点名三类必须确认的场景（发送 / 删除 / 提交），并强调「调用前不许先做」——
# 这是本工具存在的全部意义：把不可逆动作的最终决定权交回用户。
REQUEST_CONFIRM_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REQUEST_CONFIRM_TOOL_NAME,
        "description": (
            "当你要执行一个**不可逆或有外部影响**的动作、且用户尚未明确说「执行/发送/删除」时，"
            "调用本工具向用户要一次确认，界面会渲染「确认 / 取消」两个按钮，用户点一下即可决定，"
            "不需要在输入框里打字。\n"
            "必须使用本工具的场景：① 对外发送邮件/消息/通知（如「确认发送」）；"
            "② 删除或覆盖已有数据；③ 提交审批单、表单、订单等会产生流程记录的动作。\n"
            "调用时机：**先确认、再调用真正的写工具** —— 调用本工具时不要先执行那个动作，"
            "等用户点了「确认」你才执行它；用户点了「取消」就什么都不做，只回复一句「已取消」。\n"
            "若用户原话已经明确说了「确认」「发送吧」「删掉吧」，说明已经确认过，**不要再调用本工具**，"
            "直接执行即可。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "一句话说明要做什么（展示在按钮上方，如「向张三发送这封邮件」）。",
                },
                "description": {
                    "type": "string",
                    "description": "可选。补充说明关键对象与影响范围（收件人、条数、不可逆后果等），一到两句。",
                },
                "confirm_label": {"type": "string", "description": "可选。确认按钮文案，最长 10 字，如「确认发送」。缺省为「确认」。"},
                "cancel_label": {"type": "string", "description": "可选。取消按钮文案，最长 10 字。缺省为「取消」。"},
                "danger": {
                    "type": "boolean",
                    "description": "可选。true 表示这是删除/覆盖等高风险动作，界面会把确认按钮标红。缺省 false。",
                },
            },
            "required": ["title"],
        },
    },
}


def is_request_confirm(name: str | None, args: Any = None) -> bool:
    """该工具名是否为本内置确认工具。（``args`` 透传以对齐 request_form 的判定签名，此处仅看名字。）"""
    return (name or "") == REQUEST_CONFIRM_TOOL_NAME


def _label(raw: Any, default: str) -> str:
    """归一按钮文案：去空白、限长；空值或超长一律退回默认（不截断，截断会产出「确认发」这种残句）。"""
    text = str(raw or "").strip()
    if not text or len(text) > _LABEL_MAX:
        return default
    return text


def build_confirm_request(arguments: dict[str, Any] | None) -> dict[str, Any] | None:
    """把 ``request_confirm`` 的入参归一成 ``need_confirm`` 事件载荷。

    返回 ``{"kind": "confirm", "title", "description", "confirm_label", "cancel_label", "danger"}``；
    归一化规则：
      - ``title`` 与 ``description`` **都**为空时返回 ``None``（图会把这个调用当「无效内置调用」
        剔除后放行、不暂停）——避免出现「一个没有文案的空确认卡」，那比不弹还糟；
      - ``title`` 缺失但 ``description`` 有值 ⇒ 用默认标题兜底（描述已经说明白了，弹比不弹好）；
      - ``description`` 缺失 ⇒ 空串（前端据此决定是否渲染描述行）；
      - ``confirm_label`` / ``cancel_label`` 缺省或超长 ⇒ 回默认文案；
      - ``danger`` 只认布尔真值（``"true"`` 这类字符串不算）。

    不做任何副作用、不猜用户意图：确认卡上写什么必须来自模型，代码只负责形状与安全限长。
    """
    args = arguments or {}
    title = str(args.get("title") or "").strip()
    description = str(args.get("description") or "").strip()
    if not title and not description:
        return None
    return {
        "kind": "confirm",
        "title": title or _DEFAULT_TITLE,
        "description": description,
        "confirm_label": _label(args.get("confirm_label"), _DEFAULT_CONFIRM_LABEL),
        "cancel_label": _label(args.get("cancel_label"), _DEFAULT_CANCEL_LABEL),
        "danger": args.get("danger") is True,
    }
