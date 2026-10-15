"""提示词构造：把一次请求（职责范围 / 页面 / 项目 / 动作提示 / 参考文档 / 历史）拼成 messages。

原寄居在 `app/core/agent_runtime.py` 的 `_build_messages` 及其 4 个私有辅助函数。
独立成模块的理由：这是**提示词工程**，与「用什么框架跑循环」无关；
换编排框架时这一层应当原样保留（既有哨兵 `test_attachment_docs.py` 与
`_check_kb_toggle.py` 正是针对本模块产出的定界符做判定）。

安全约定（勿回退）：
  - 用户可控数据一律经 `_neutralize_injection` 中和（命中 token-override 黑名单即剥离并记 warn），
    并剥掉控制字符与换行，防止伪造/截断提示结构；
  - 库/文档正文用「硬括号 + 固定前缀」包裹（`_wrap_field`），让模型区分「这是数据」而非指令；
  - 实现**不得在提示词里引用注入块的定界符原文**（【参考文档】/【知识库参考】）——
    这两个定界符是「块是否真被注入」的判据，写进提示词会让判据恒真、失效。
"""
from __future__ import annotations

import logging
import re

from aioa_ai.contracts import RunRequest
from aioa_ai.intent import intake as worker_intake
from aioa_ai.prompt.answer import rules as answer_rules

logger = logging.getLogger("aioa.ai.prompt")

# 指令覆盖（prompt injection）黑名单：命中即视为尝试越权注入系统提示。
# 仅中和（剥离）并记 warn，不拒绝请求（保持产品行为）。
_OVERRIDE_PATTERNS = (
    "ignore previous instructions", "ignore the above", "ignore all previous",
    "disregard previous", "disregard the above", "forget your instructions",
    "forget previous", "new instructions", "system:", "system prompt",
    "忽略以上指令", "忽略上述指令", "忽略之前的指令", "无视以上指令", "忘记你的指令",
    "忽略前面的指令", "覆盖指令", "新的指令", "系统提示：", "假装你是", "你现在是",
)
_INJECTION_MASK = "[已屏蔽的指令覆盖尝试]"

# 对话内参考文档正文合计上限（字符）：超出后按顺序截断，避免单次请求上下文被长文档撑爆。
_MAX_ATTACHMENT_CHARS = 40000


def _strip_control_chars(value: str) -> str:
    """剥掉控制字符与换行（保留可读文本）：防止通过换行/制表符伪造或截断提示结构。"""
    if not value:
        return ""
    # 仅保留 0x20 及以上的可见/空白字符（CJK、标点、空格等），剔除 0x00-0x1F、0x7F。
    return "".join(ch for ch in value if ord(ch) >= 0x20 and ord(ch) != 0x7F)


def _wrap_field(prefix: str, value: str | int | None) -> str:
    """把用户可控数据包裹成「硬括号 + 固定前缀」，让模型明确区分『这是数据』而非指令。

    例：[user.name=张三] / [ctx.appCode=ticket]。同时剥掉控制字符与换行。
    非字符串值（如 user_id 整数）先转 str；值为空时返回空串（调用方已做真值判断）。
    """
    if value is None:
        return ""
    cleaned = _strip_control_chars(str(value))
    if not cleaned:
        return ""
    return f"[{prefix}={cleaned}]"


def _neutralize_injection(text: str | None) -> str:
    """对用户输入 / 历史正文做指令覆盖中和：命中 token-override 黑名单时剔除并记 warn，
    同时剥掉控制字符。不拒绝请求（保持产品行为），仅做降噪与越权防护。
    """
    if text is None:
        return ""
    cleaned = _strip_control_chars(str(text))
    hit = False
    for pat in _OVERRIDE_PATTERNS:
        if re.search(re.escape(pat), cleaned, flags=re.IGNORECASE):
            hit = True
            cleaned = re.sub(re.escape(pat), _INJECTION_MASK, cleaned, flags=re.IGNORECASE)
    if hit:
        logger.warning("检测到疑似指令覆盖注入并已中和：%r", text[:120])
    return cleaned


def _build_attachment_block(docs: list) -> str:
    """把对话内上传的参考文档拼成一段「独立」的上下文块。

    每块用「【参考文档】《名字》」开头、「【以上为参考文档】」结尾，作为不可信输入
    **同样经过** ``_neutralize_injection``（文档内容可能夹带指令覆盖尝试，与 history/text
    同等待遇，不得原样裸拼）。放在 system 提示的末尾、作为独立段落，而非混入 ``scope``
    的职责提示：职责提示是「身份 / 边界」，参考文档是「本次待参考的资料」，语义不同，
    混在职责段里会污染职责边界；独立成段 + 硬边界包裹，方便模型区分「这是用户上传的资料」
    与「这是系统给你的指令」。

    - ``truncated`` 为真（单篇已被后端节选）：块尾注明「（文档较长，以上为节选）」。
    - 所有文档正文合计超 ``_MAX_ATTACHMENT_CHARS``：按序截断剩余，并在被截断块尾注明
      「（参考文档总长度超出上限，以上为截断内容）」。
    """
    blocks: list[str] = []
    total = 0
    for doc in docs:
        name = doc.name or "未命名文档"
        text = _neutralize_injection(doc.text or "")
        note = ""
        if doc.truncated:
            note += "\n（文档较长，以上为节选）"
        # 总长保护：本篇会让累计正文超上限时，截断本篇、并清空后续预算
        if total + len(text) > _MAX_ATTACHMENT_CHARS:
            remaining = _MAX_ATTACHMENT_CHARS - total
            text = text[:remaining] if remaining > 0 else ""
            note += "\n（参考文档总长度超出上限，以上为截断内容）"
            total = _MAX_ATTACHMENT_CHARS  # 后续文档均无剩余预算
        else:
            total += len(text)
        piece = f"【参考文档】《{name}》\n{text}\n【以上为参考文档】"
        if note:
            piece += note
        blocks.append(piece)
    return "\n\n".join(blocks)


def build_kb_reference_block(rows: list) -> str:
    """把预检索命中的知识库片段拼成一段「独立」的参考上下文块。

    风格照搬 ``_build_attachment_block``：用硬边界包裹为不可信输入，同样经过
    ``_neutralize_injection``（库文档可能夹带指令覆盖尝试），作为独立段落追加到
    system 提示末尾，让模型区分「这是用户相关知识库资料」与「系统指令」。

    库文档字段不固定（可能含 ``content`` / ``text`` / ``docName`` 等），这里做兼容取值。
    """
    blocks: list[str] = []
    for doc in rows:
        if not isinstance(doc, dict):
            continue
        name = doc.get("docName") or doc.get("title") or "未命名文档"
        text = _neutralize_injection(doc.get("content") or doc.get("text") or "")
        if not text:
            continue
        blocks.append(f"【知识库参考】《{name}》\n{text}\n【以上为知识库参考】")
    return "\n\n".join(blocks)


def build_messages(req: RunRequest, max_context: int = 0) -> list[dict]:
    """构造带系统提示（职责范围 / 页面 / 用户上下文）与多轮历史的消息列表。

    页面上下文让模型具备「所在业务页面 / 选中实体」的态势感知，对应设计中的
    「上下文维护 / 记忆管理」。

    max_context > 0 时按字符预算裁剪多轮历史（丢最旧的）：模型配置里的「最大上下文长度」
    必须真的作用于请求，否则就只是个展示字段。0（默认）= 不限制，保持既有行为。

    职责范围（req.scope）由后端在会话绑定数字员工时下发：一旦存在，**整体替换**
    通用助手身份提示，并追加「只答职责范围内、越界一律拒答」的硬规则——
    这是「职责限定」的触发点（会话绑定）与判定点（系统提示 + 拒答规则）在 Agent 侧的落点。
    """
    scope = req.scope or {}
    if scope:
        role_name = scope.get("role_name") or scope.get("role") or "通用办公助手"
        sys_parts: list[str] = [
            f"你是 AIOA 智能办公平台的数字员工「{scope.get('name') or '数字员工'}」（角色类型：{role_name}）。",
            f"你的职责边界（唯一可回答的范围）：{scope.get('duty') or '通用办公'}。",
            "【职责范围限定 · 必须严格遵守】",
            "1. 只回答与上述职责边界直接相关的问题；",
            "2. 与职责无关的问题（闲聊、其他岗位职责、与本职责无关的通用知识），"
            "一律礼貌拒答，用一句话说明你的职责范围，并建议用户改问对应的数字员工或业务入口；",
            "3. 不得编造或推测超出职责边界的信息；需要业务数据时调用已提供的工具，工具查不到就如实说明；",
            "4. 不得声称自己拥有职责范围之外的权限（如审批、放款、盖章等），也不得越权承诺办理结果。",
        ]
        if scope.get("role") == "LEAVE_APPROVER":
            sys_parts.append(
                "请假审批场景：你负责受理请假申请、校验请假类型与证明材料，"
                "并依据企业请假制度给出送审与答复意见；与请假无关的审批事项一律不予处理。")
    else:
        sys_parts = [
            "你是 AIOA 智能办公基座（AI Office Agent）的对话助手，服务于企业办公场景。",
            "请根据用户所在的业务页面与上下文，给出准确、简洁、可执行的回答。",
            "需要查询用户的审批、知识库、额度等业务数据时，优先调用提供的工具，不要编造。",
        ]
    # 回答风格：只划「不能答什么」不够，还要管「答多长、答什么」。
    # 规则唯一出处见 prompt/answer.rules。
    sys_parts.extend(answer_rules(scope))
    uc = req.user_context
    if uc.username or uc.roles:
        role_desc = "、".join(uc.roles) if uc.roles else "普通用户"
        sys_parts.append(
            f"当前用户：{_wrap_field('user.name', uc.username or uc.user_id)}"
            f"（角色：{_wrap_field('user.role', role_desc)}）。")
    ctx = req.context
    if ctx is not None:
        bits: list[str] = []
        if ctx.appCode:
            bits.append(f"所在应用={_wrap_field('ctx.appCode', ctx.appCode)}")
        if ctx.page:
            bits.append(f"页面={_wrap_field('ctx.page', ctx.page)}")
        if ctx.pageTitle:
            bits.append(f"页面标题={_wrap_field('ctx.pageTitle', ctx.pageTitle)}")
        if ctx.entityType:
            bits.append(f"实体类型={_wrap_field('ctx.entityType', ctx.entityType)}")
        if ctx.entityId:
            bits.append(f"实体ID={_wrap_field('ctx.entityId', ctx.entityId)}")
        if bits:
            sys_parts.append("页面上下文：" + "，".join(bits) + "。")
    # 当前项目上下文（后端在有项目会话时下发，键名照抄后端契约 {id,name,type,status}）。
    # 目的：让模型明确「用户在本项目会话中提问默认针对该项目」，不再反问上传到哪个系统/平台。
    # 项目名/类型为库里数据，用 _wrap_field 包裹防注入；缺失时不追加任何内容，保持与改动前逐字一致。
    if req.project and req.project.get("id") is not None:
        pid = req.project.get("id")
        pname = _wrap_field("project.name", req.project.get("name"))
        ptype = _wrap_field("project.type", req.project.get("type"))
        sys_parts.append(
            f"当前项目：《{pname}》（id={pid}，类型={ptype}）。"
            "用户在本项目会话中提问时默认针对该项目；不要反问用户在哪个系统或平台。")
    # 动作提示：把「本轮回应的正确姿态」显式告诉模型，修两类已核实缺陷——
    # ① H5 已自行打开上传/上报窗口，模型却答「我无法直接处理文件上传」（来源矛盾）；
    # ② 用户要「新建数字人」，模型却说要申请 worker:manage（真实是 worker:create 默认开放）。
    # 只在有对应动作时追加，无动作时保持与改动前逐字一致。
    action = worker_intake.detect_action(req.text)
    if action == "UPLOAD_FILE":
        if req.project and req.project.get("id") is not None:
            sys_parts.append(
                "本轮用户诉求已被识别为「上传文件」。用户端会为当前项目直接打开上传窗口 —— "
                "你只需一句话确认（例如「正在为你打开上传窗口，请选择文件。」），不要重复描述窗口细节，"
                "更不要回复「我无法直接操作」「请使用系统/平台提供的上传功能」「请确认你要上传到哪个平台」这类话。")
        else:
            sys_parts.append(
                "本轮用户诉求已被识别为「上传文件」。用户端会提示用户先进入一个项目再上传 —— "
                "你只需一句话说明，不要给通用上传教程。")
    elif action == "REPORT_EXPENSE":
        if req.project and req.project.get("id") is not None:
            sys_parts.append(
                "本轮用户诉求已被识别为「上报花费」。用户端会为当前项目直接打开花费上报窗口 —— "
                "你只需一句话确认（例如「正在为你打开花费上报窗口，请填写金额。」），不要重复描述窗口细节，"
                "更不要回复「我无法直接操作」「请使用系统/平台提供的相关功能」这类话。")
        else:
            sys_parts.append(
                "本轮用户诉求已被识别为「上报花费」。用户端会提示用户先进入一个项目再上报 —— "
                "你只需一句话说明，不要给通用上报教程。")
    elif action == "CREATE_WORKER":
        sys_parts.append(
            "本轮用户诉求已被识别为「创建数字员工」。创建是界面能力：用户端「专家与员工」页有"
            "「＋ 创建数字员工」入口（管理端亦可），所需权限 worker:create 对全体登录用户默认开放。"
            "不要说需要申请 worker:manage，不要调用权限申请工具，不要回复无法操作；用一句话把入口告诉用户即可。")
    # 全局硬规则：无论有无动作都生效，杜绝能力否认话术（例如「我无法直接处理文件上传」），
    # 改让用户要求执行某动作时说明具体入口或界面提供的入口。
    sys_parts.append(
        "禁止输出「我无法直接操作系统或平台」「我无法直接处理文件上传」"
        "「我无法直接打开上传窗口」这类能力否认话术；用户要求你执行某个动作时，"
        "说明具体入口或由界面提供的入口，不要给泛泛的通用教程。")
    # 对话内上传的参考文档：作为独立上下文块追加到 system 提示末尾（详见 _build_attachment_block）。
    # 无附件时不追加任何内容，保证与改动前逐字一致。
    if req.attachment_docs:
        sys_parts.append(_build_attachment_block(req.attachment_docs))
    system = "\n".join(sys_parts)

    system_message = {"role": "system", "content": system}
    history: list[dict] = []
    for turn in req.history or []:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant", "system") and content:
            history.append({"role": role, "content": str(_neutralize_injection(content))})

    if max_context and max_context > 0:
        # token -> 字符的粗换算（中英混合经验值 1 token ≈ 2 字符），只用来做上限保护；
        # 系统提示与当前提问永远保留，超出预算的从最旧的一轮开始丢。
        budget = max(int(max_context) * 2, 1000)
        used = len(system) + len(req.text or "")
        kept: list[dict] = []
        for turn in reversed(history):
            if used + len(turn["content"]) > budget:
                break
            kept.append(turn)
            used += len(turn["content"])
        kept.reverse()
        if len(kept) < len(history):
            logger.info("history trimmed by max_context=%d: %d -> %d turns",
                        max_context, len(history), len(kept))
        history = kept

    messages: list[dict] = [system_message]
    messages.extend(history)
    messages.append({"role": "user", "content": _neutralize_injection(req.text)})
    return messages
