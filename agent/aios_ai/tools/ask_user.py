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

# 动态字段（`fields`）的硬上限：控件超过 6 个就该拆成两问，而不是做成一张问卷。
# 超出部分**丢弃并告警**（不静默：日志里能看到「模型想给 9 个字段」）。
MAX_FIELDS = 6

# 支持的输入类型。**枚举是封闭的** —— 未知类型降级成 text，而不是让前端去猜。
#   select   菜单/候选按钮（有限互斥集合；searchable=true 时变成可检索候选框）
#   multi    多选（参与人、标签这类可多值的）
#   text     单行文本（姓名、标题）
#   textarea 多行文本（消息内容、说明）
#   date     日期        datetime 日期时间
#   number   数字（数量、金额、时长）
FIELD_TYPES = ("select", "multi", "text", "textarea", "date", "datetime", "number")

# 依赖条件支持的操作符（**只会这几个**，多一个都不认）：
#   eq/neq 等于/不等于某个值    in 属于某个集合
#   empty 该字段为空            truthy 该字段有值
COND_OPS = ("eq", "neq", "in", "empty", "truthy")

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
            "调用本工具向用户提出**一个**单选问题或一张**简短表单**，然后停下等待用户输入。"
            "仅在确实无法继续时使用；不要用它追问次要细节，更不要凭猜测编造默认值继续执行。"
            "**这一步缺几样东西，就在一次调用里问几样**（用 `fields`），不要拆成多轮往返。"
            "\n\n控件怎么选（按用户这句话的语义判断，不要随手都用文本框）："
            "\n· 从**有限、互斥**的几项里挑一个（动作类型、优先级、时间范围）⇒ `select`；"
            "\n· 候选很多或需要检索（人名、部门、单据号）⇒ `select` + `searchable: true`（可输入过滤的候选框）；"
            "\n· 可以选多个（参与人、标签）⇒ `multi`；"
            "\n· 一句话/一段话（消息内容、事由、说明）⇒ `text` / `textarea`；"
            "\n· 时间 ⇒ `date` / `datetime`（不要让人手打「明天下午三点」这种自由文本）；"
            "\n· 数量/金额/时长 ⇒ `number`。"
            "\n\n**后面的字段依赖前面的选择时**，给该字段写 `visible_when`："
            "例如先问「想做什么」(action)，再让「消息内容」只在 action=message 时出现、"
            "「会议时间」只在 action=meeting 时出现 —— 用户在同一次交互里把该填的都填完。"
            "\n· 只有单一互斥选择、且选完不需要补充别的内容时，也可以用更简单的 `options`；"
            "选定某项之后还要补一句内容，用 `options` + 该项 `needs_text: true`。"
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
                        "**注意**：需要多个字段、或字段之间有依赖时请改用 `fields`。"
                    ),
                    "properties": {
                        "label": {"type": "string", "description": "输入框标题。"},
                        "placeholder": {"type": "string", "description": "提示语/例子。"},
                        "required": {"type": "boolean", "description": "是否必须填写才能确认，默认 false。"},
                    },
                },
                "fields": {
                    "type": "array",
                    "description": (
                        "**一条消息里缺几样就问几样**：把这一步需要的全部输入列成字段，"
                        "用户填完一次提交。最多 6 个。与 `options` 二选一（要字段就别给 options）。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string",
                                   "description": "字段标识（英文/数字，回填时按它取值），如 action。"},
                            "label": {"type": "string", "description": "字段标题，例如「会议时间」。"},
                            "type": {"type": "string", "enum": list(FIELD_TYPES),
                                     "description": "控件类型，缺省 text。"},
                            "required": {"type": "boolean",
                                         "description": "是否必填（该字段可见时才校验）。"},
                            "options": {
                                "type": "array",
                                "description": "select/multi 的候选。选项很多时配 searchable=true。",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "string"},
                                        "label": {"type": "string"},
                                    },
                                    "required": ["value", "label"],
                                },
                            },
                            "searchable": {"type": "boolean",
                                           "description": "select 是否渲染成可输入过滤的候选框"
                                                          "（候选多、或需要按关键词找时用）。"},
                            "placeholder": {"type": "string", "description": "输入提示/例子。"},
                            "hint": {"type": "string", "description": "标题下的小字说明（可选）。"},
                            "default": {"type": "string", "description": "默认值（可选）。"},
                            "max_len": {"type": "integer",
                                        "description": "文本最大长度；超出时前端就地提示、不予提交。"},
                            "min": {"type": "number", "description": "number 的最小值。"},
                            "max": {"type": "number", "description": "number 的最大值。"},
                            "visible_when": {
                                "type": "object",
                                "description": (
                                    "依赖条件：满足时才显示本字段（不满足则隐藏、清空、不校验、不提交）。"
                                    "例如 {\"field\":\"action\",\"op\":\"eq\",\"value\":\"meeting\"}。"
                                ),
                                "properties": {
                                    "field": {"type": "string", "description": "依赖的字段 id。"},
                                    "op": {"type": "string", "enum": list(COND_OPS),
                                           "description": "eq/neq/in/empty/truthy，缺省 eq。"},
                                    "value": {"description": "比较值；op=in 时给数组。"},
                                },
                                "required": ["field"],
                            },
                        },
                        "required": ["id", "label"],
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


def _as_condition(raw: Any) -> dict[str, Any] | None:
    """依赖条件归一 ``{field, op, value}``；不合法返回 None（该字段就变成"总是显示"）。

    **宁可不显示依赖，也不要显示错的依赖**：条件写坏了最坏结果是「多问一个字段」，
    而按错误条件隐藏字段会导致「必填项看不到、提交又通不过」的死结。
    """
    if not isinstance(raw, dict):
        return None
    field = str(raw.get("field") or "").strip()
    if not field:
        return None
    op = str(raw.get("op") or "eq").strip()
    if op not in COND_OPS:
        op = "eq"
    cond: dict[str, Any] = {"field": field, "op": op}
    if op in ("eq", "neq"):
        if "value" not in raw:
            return None
        cond["value"] = raw["value"]
    elif op == "in":
        vals = raw.get("value")
        if not isinstance(vals, list) or not vals:
            return None
        cond["value"] = vals
    return cond


def _as_field(raw: Any, idx: int) -> dict[str, Any] | None:
    """单个字段归一。缺 id/label 的丢弃（没法回填、用户也看不懂）。"""
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    fid = str(raw.get("id") or "").strip()
    if not label or not fid:
        return None
    ftype = str(raw.get("type") or "text").strip()
    if ftype not in FIELD_TYPES:
        # 未知类型降级成 text：宁可让人手打，也不要前端拿着未知 type 渲染成空白块
        ftype = "text"
    opts = _as_options(raw.get("options")) if ftype in ("select", "multi") else []
    if ftype in ("select", "multi") and not opts:
        # 没有候选的「菜单」是死控件 ⇒ 降级成文本框，让用户至少能填
        ftype = "text"
    spec: dict[str, Any] = {"id": fid, "label": label, "type": ftype,
                            "required": raw.get("required") is True}
    if opts:
        spec["options"] = opts
    if raw.get("searchable") is True and ftype == "select":
        spec["searchable"] = True
    ph = str(raw.get("placeholder") or "").strip()
    if ph:
        spec["placeholder"] = ph
    hint = str(raw.get("hint") or "").strip()
    if hint:
        spec["hint"] = hint
    if raw.get("default") not in (None, ""):
        spec["default"] = str(raw["default"])
    if isinstance(raw.get("max_len"), int) and raw["max_len"] > 0:
        spec["max_len"] = raw["max_len"]
    if ftype == "number":
        for k in ("min", "max"):
            v = raw.get(k)
            if isinstance(v, (int, float)):
                spec[k] = v
    cond = _as_condition(raw.get("visible_when"))
    if cond:
        spec["visible_when"] = cond
    return spec


def _prune_conditions(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """剪掉「指向不存在的字段」与「成环」的依赖条件（**只剪条件，不剪字段**）。

    前端是按依赖图求值可见性的，一个环会让求值在「谁都不显示」和「都显示」之间来回跳，
    表现是控件闪烁、确认按钮灰度乱变。剪掉环上那条边之后，该字段退化成"总是显示"，
    用户多填一项，但流程一定走得通 —— 这是刻意选的降级方向。
    """
    ids = {f["id"] for f in fields}
    out: list[dict[str, Any]] = []
    for f in fields:
        cond = f.get("visible_when")
        if cond and (cond["field"] not in ids or cond["field"] == f["id"]):
            f = {k: v for k, v in f.items() if k != "visible_when"}
        out.append(f)

    # 环检测：沿 visible_when.field 走，回到自己就是环 ⇒ 去掉该字段的条件
    for f in out:
        seen = {f["id"]}
        cur = f.get("visible_when")
        while cur:
            nxt = cur["field"]
            if nxt in seen:
                f.pop("visible_when", None)
                break
            seen.add(nxt)
            cur = next((g.get("visible_when") for g in out if g["id"] == nxt), None)
    return out


def _as_fields(raw: Any) -> list[dict[str, Any]]:
    """把模型给的 ``fields`` 归一成前端可直接渲染的字段表。

    三道收敛，都是「宁可少问、不要问错」：
      1. 未知 type ⇒ text；select/multi 没有候选 ⇒ 也降级 text（死控件不如让用户打字）；
      2. 依赖指向不存在的字段 / 成环 ⇒ 剪掉条件（字段保留）；
      3. 超过 ``MAX_FIELDS`` ⇒ 截断（日志由调用方打，这里只保证结构合法）。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        f = _as_field(item, i)
        if not f or f["id"] in seen:
            continue
        seen.add(f["id"])
        out.append(f)
        if len(out) >= MAX_FIELDS:
            break
    return _prune_conditions(out)


def build_clarification(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """把 ``ask_user`` 的入参归一成 ``need_clarification`` 事件载荷。

    返回 ``{"question", "suggested_options", "text_input"?, "fields"?}``。
    ``text_input`` / ``fields`` 只在模型真的给了时才出现 —— 老载荷形状不变。

    三种卡型的优先级（前端同此顺序）：``fields`` > ``options + text_input`` > 自由输入。
    """
    args = arguments or {}
    question = str(args.get("question") or "").strip() or "请补充必要信息后继续。"
    spec: dict[str, Any] = {
        "question": question,
        "suggested_options": _as_options(args.get("options")),
    }
    fields = _as_fields(args.get("fields"))
    if fields:
        # 有字段卡 ⇒ 旧的 options/text_input 一律丢弃：一张卡上不能并存两套控件、
        # 两套必填规则（用户不知道该看哪套，回填形状也会变成两种）。
        spec["fields"] = fields
        spec["suggested_options"] = []
        return spec
    ti = _as_text_input(args.get("text_input"))
    if ti:
        spec["text_input"] = ti
    return spec
