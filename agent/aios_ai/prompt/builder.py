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

from aios_ai.config import settings
from aios_ai.contracts import RunRequest
from aios_ai.intent import intake as worker_intake
from aios_ai.prompt.answer import rules as answer_rules

logger = logging.getLogger("aios.ai.prompt")

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


def _forms_tool_enabled() -> bool:
    """表单请求能力（``request_form`` 内置工具）是否可用。

    唯一配置源是 ``config.agent_hitl``（与 ``graph/nodes.py#_hitl_enabled`` 同口径，
    用 ``getattr`` 兜底，兼容把 settings 换成精简 shim 的哨兵）。

    为什么提示词要看这个开关：工具表在 HITL 关闭时**不注入** ``request_form``，
    若提示词仍写「必须调用 request_form」，模型会幻觉调用一个不存在的工具，
    最后落到工具执行层报错 —— 提示词与工具表必须同源判定。
    """
    return bool(getattr(settings, "agent_hitl", False))


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
    # 专家人设（V88 链路补齐）：会话选了专家 AI 时下发。专家会话不绑数字员工，故与上面的
    # scope（数字员工职责边界）互斥——worker 优先。system_prompt 取 expert.system_prompt，
    # 若其为空而 expert_settings.systemPrompt 非空则兜底；二者皆空则回落通用助手。
    expert = req.expert or {}
    expert_name = expert.get("name")
    expert_prompt = (expert.get("system_prompt") or "").strip()
    if not expert_prompt and req.expert_settings:
        es_prompt = (req.expert_settings or {}).get("systemPrompt")
        if es_prompt:
            expert_prompt = str(es_prompt).strip()
    if scope:
        role_name = scope.get("role_name") or scope.get("role") or "通用办公助手"
        sys_parts: list[str] = [
            f"你是 AIOS 智能办公平台的数字员工「{scope.get('name') or '数字员工'}」（角色类型：{role_name}）。",
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
    elif expert_prompt and expert_name:
        # 专家人设：用领域身份替换通用助手身份（管理员配置的领域方法论，可信配置按指令处理）。
        sys_parts = [
            f"你是 AIOS 智能办公平台上的「{expert_name}」专家 AI。",
            expert_prompt,
            "【专家纪律】",
            "1. 只在本专业范围内回答；超出专业范围时一句话说明并建议换对应专家，不要硬答。",
            "2. 结论先行：先给判断/结果，再给依据与步骤。",
            "3. 不编造法条、文号、数字、案例；查不到就说查不到，并说明需要什么资料。",
            "4. 信息不足时先问 1-3 个关键问题，不要凭猜测输出成稿。",
        ]
    else:
        sys_parts = [
            "你是 AIOS 智能办公基座（AI Office Agent）的对话助手，服务于企业办公场景。",
            "请根据用户所在的业务页面与上下文，给出准确、简洁、可执行的回答。",
            "需要查询用户的审批、知识库、额度等业务数据时，优先调用提供的工具，不要编造。",
        ]
        # 专家有名字但无 system_prompt（旧前端只传了名称）：保持通用助手三行不变，
        # 仅追加一句引导，让模型围绕该领域回答（不改通用三行本身）。
        if expert_name:
            sys_parts.append(
                f"本次会话用户选择了「{expert_name}」专家，请围绕该领域回答。")
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
    # 会话内跨数字人转交（handoff）：后端已在「同一会话」内把会话改绑到当前数字人，
    # 并复用同一条已落库的用户消息继续跑（用户没有重述）。告知模型此前由哪个数字人接待，
    # 让它直接按职责回答，不要要求用户重复问题，也不要提及内部转交流程。
    if req.handoff:
        from_name = req.handoff.get("from_worker_name") or "其他数字员工"
        sys_parts.append(
            f"本次会话此前由数字员工「{from_name}」接待，用户的问题已转交给您（你）处理；"
            "请直接按您的职责回答，不要要求用户重复问题，也不要提及内部转交流程。")
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
        # 话术必须与事实同源（铁律 1）：创建入口此前只存在于经典形态「专家与员工」页，
        # 而默认形态（OA）没有该入口；改为描述「界面会直接打开创建窗口」这一真实行为。
        sys_parts.append(
            "本轮用户诉求已被识别为「创建数字员工」。创建是界面能力：界面会为用户直接打开"
            "「创建数字员工」窗口，由用户补齐名称与职责后创建（所需权限 worker:create 对全体登录用户"
            "默认开放）。你只需一句话确认（例如「正在为你打开创建数字员工窗口，请补上名称与职责。」），"
            "不要描述与当前界面不符的菜单路径，不要说需要申请 worker:manage，不要调用权限申请工具，"
            "不要回复无法操作。")
    elif action == "APPLY_LEAVE":
        # 话术必须与 H5 真实行为同源（铁律 1，见 docs/51 §1.4）：
        # 未持有 approval:leave ⇒ 界面弹「办理请假需要『请假审批』权限」卡片，由用户点「帮我申请」才提交、点「取消」不提交任何申请；
        # 已持有 ⇒ 界面直接进入请假数字人并给出《请假申请》表单。
        # 模型拿不到 held，故措辞须同时覆盖两种走向；核心是「动作只在用户点击时发生于界面，绝不在此代用户落库」。
        sys_parts.append(
            "本轮用户诉求已被识别为「请假」。这是界面要处理的动作，由界面按当前用户的权限状态给出对应入口，"
            "你只需一句话说明接下来用户要在界面上做什么，不要代替界面执行任何操作："
            "若用户当前没有「请假审批」权限，界面会弹出权限申请卡片，由用户自己点「帮我申请」或「取消」；"
            "若用户已持有该权限，界面会直接进入请假数字人并给出《请假申请》表单。"
            "因此你不得调用权限申请类工具（如 apply_permission），也不得说出「已为你提交」「已帮你申请」"
            "这类与界面不符、仿佛申请已落库的话。")
    # 全局硬规则：无论有无动作都生效，杜绝能力否认话术（例如「我无法直接处理文件上传」），
    # 改让用户要求执行某动作时说明具体入口或界面提供的入口。
    sys_parts.append(
        "禁止输出「我无法直接操作系统或平台」「我无法直接处理文件上传」"
        "「我无法直接打开上传窗口」这类能力否认话术；用户要求你执行某个动作时，"
        "说明具体入口或由界面提供的入口，不要给泛泛的通用教程。")
    # 全局硬规则：涉及**真实写操作**的工具（尤其申请权限类，如 apply_permission）只在用户**明确要求你办理**时才调用；
    # 用户只是表达意愿（「我要请假」「我要新建一个数字员工」）时不要抢先替他提交——这类操作界面会提供确认入口由用户自己决定。
    # 注意：用户**显式**要求「帮我提交/申请权限」「直接调用工具帮我提交」时仍应正常调用（V36 既有特性，不可拔除）。
    sys_parts.append(
        "涉及真实写操作的工具（尤其申请权限类工具，如 apply_permission）只在用户明确指示你办理时才调用；"
        "当用户只是表达意愿（如「我要请假」「我要新建一个数字员工」）而未明确要求你提交时，"
        "不要抢先替用户发起写操作——相关确认入口会由界面给出，由用户自己决定是否提交。"
        "但若用户明确说「请帮我提交/申请权限」「直接调用工具帮我提交」，则应照常执行。")
    # 当前租户可用表单清单（Java 从 form_template 查得并随 run 下发，顶层字段 available_forms）。
    # 仅清单非空时注入；表单名/编码来自 DB，按不可信数据经 _neutralize_injection 中和（内部会调
    # _strip_control_chars 剥换行/控制字符），保证每行单行、不会被换行截断或伪造提示结构。
    # 清单为空（None / 空列表）时不追加任何内容，保证与改动前逐字一致；
    # 不放进 scope 分支内部——无数字员工的一般会话也可能需要表单，故置于两处分支汇合之后。
    # 与 Java 侧一致，最多拼接 200 行，超出在末行后标注已截断。
    if req.available_forms:
        shown = req.available_forms[:200]
        rows: list[str] = []
        for f in shown:
            code = _neutralize_injection(f.get("code"))
            name = _neutralize_injection(f.get("name"))
            line = f"- {code}｜{name}"
            module_code = f.get("module_code")
            if module_code:  # 缺失就省略该段，不要输出「模块=None」
                line += f"｜模块={_neutralize_injection(module_code)}"
            rows.append(line)
        block = (
            "【可用表单清单】\n"
            + "\n".join(rows)
            + "\n【以上为可用表单清单】\n"
            "调用 request_form 时 form_code 必须逐字取自上面清单；清单未列出的表单一律不要调用工具"
            "（不要编造、不要改写编码），改为用一句话说明当前可办理的表单入口并建议用户从对应业务入口办理。"
        )
        # 强制使用规则：只在表单请求能力真的开启（HITL）时追加。
        # 关闭时 request_form **不在**模型工具表里（见 graph/nodes.py 的注入条件），
        # 此时若仍要求「必须调用 request_form」，等于让模型幻觉调用一个不存在的工具 ——
        # 所以这里与工具表同源判定，绝不无条件加。
        if _forms_tool_enabled():
            block += (
                "\n【可用表单清单 · 强制使用规则】\n"
                "1. 用户诉求属于清单中某张表单的业务范围时，**必须调用 request_form** 请用户填写该表单，"
                "由界面把表单卡发给用户；用户用词与表单名不完全一致时，按**业务归属**选择最接近的一张"
                "（例：「办公用品报销」「差旅报销」「招待费报销」都归「费用报销」）。\n"
                "2. 在用户填写并提交表单之前，**禁止**输出操作步骤、菜单路径、"
                "「进入某系统」「联系部门管理员/财务」这类通用教程，也不要要求用户自己去找入口；"
                "最多用一句话说明正在为他打开哪张表单。\n"
                "3. 只有清单里确实没有覆盖该业务的表单时，才用文字说明并建议业务入口。\n"
                "4. **禁止把工具调用写成文字**：不要输出 {\"form_code\": ...} 这类 JSON 代码块、"
                "不要写「请确认是否需要我打开表单」再等用户点头、也不要在正文里逐条罗列"
                "「用印类型/用印文件/用印数量」这类本该由表单收集的字段。"
                "**直接调用 request_form** —— 表单卡片由界面渲染给用户填写；"
                "用文字替代调用等于让用户无法提交（2026-10-18 实测：多个数字人正是这样漏调的）。\n"
                "5. **表单与项目无关**：不要说「请先进入一个项目」「在项目内选择某模块」再填表。"
                "当前没有项目上下文时同样直接调用 request_form。\n"
                "6. **参数不全也要开表单**：只要能判断出属于哪张表单的业务范围，哪怕用户没给"
                "「用印类型/金额/时间/公文种类」等具体值，也**直接调用 request_form** —— 这些字段"
                "本来就该由表单收集。只有在**根本判断不出属于哪类业务**时，才用一句话追问。"
                "尤其不要把表单里的枚举字段（如公文种类、印章类型）拿到正文里让用户先选。\n"
            )
        if len(req.available_forms) > 200:
            block += f"\n（清单过长已截断，共 {len(req.available_forms)} 张）"
        sys_parts.append(block)
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
