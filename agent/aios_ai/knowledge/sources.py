"""数据源目录：把「工具名」翻译成「人类可读的来源」。

为什么单独成模块：
    引用溯源（``knowledge/kb.py``）与跨源聚合编排（``aggregate/``）都要回答同一个问题 ——
    「这条数据是哪来的、叫什么名字」。若各自维护一份映射，加一个连接器就要改两处，
    迟早出现「同一份企微数据，引用里叫 wecom_cli、聚合里叫企业微信」的分裂。

设计口径：
    * **code → 中文名** 是唯一事实源（``SOURCE_LABELS``）；code 与 mcp-hub 的 serverCode、
      业务网关的工具族保持同名，不另造一套词。
    * 未登记的 code **不丢弃、不报错**：回退成 code 本身。理由同审批人策略族 ——
      新增连接器时忘了登记，应该是「显示成英文 code」而不是「整条引用消失」。
    * 只做**词表与提取**，不做 IO、不 import 工具层：引用转换要在运行时与回声运行时共用，
      任何对工具层的依赖都会造成循环 import。
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# 一、来源词表：code → 中文名
# ---------------------------------------------------------------------------
# 命名口径：MCP 连接器用 serverCode（与 mcp-hub/connectors/registry.py 一致），
# 内部数据域用语义名。新增连接器时**只在这里加一行**，引用与聚合自动生效。
SOURCE_LABELS: dict[str, str] = {
    # ---- 三方连接器（mcp-hub 注册的 serverCode）----
    "wecom_cli": "企业微信",
    "qq_mail": "QQ邮箱",
    "dingtalk": "钉钉",
    # ---- 内部数据域 ----
    "knowledge_base": "知识库",
    "approval": "审批",
    "leave": "请假",
    "org": "组织架构",
    "portal": "门户",
    "meeting": "会议",
    "schedule": "日程",
    "todo": "待办",
    "biz_data": "业务数据库",
    "quota": "额度",
    # ---- 外部 ----
    "web": "网络",
}

# 数据源大类：聚合编排按大类决定「这个源该问什么」，引用按大类决定排序优先级。
SOURCE_KINDS: dict[str, str] = {
    "wecom_cli": "im",
    "qq_mail": "mail",
    "dingtalk": "im",
    "knowledge_base": "kb",
    "web": "web",
    "approval": "oa",
    "leave": "oa",
    "org": "oa",
    "portal": "oa",
    "meeting": "oa",
    "schedule": "oa",
    "todo": "oa",
    "biz_data": "data",
    "quota": "meta",
}


def source_label(code: str | None) -> str:
    """code → 中文名；未登记时回退 code 本身（绝不返回空串）。"""
    if not code:
        return ""
    return SOURCE_LABELS.get(code, code)


def source_kind(code: str | None) -> str:
    """code → 大类（im/mail/kb/oa/data/web/meta）；未登记回退 ``other``。"""
    if not code:
        return "other"
    return SOURCE_KINDS.get(code, "other")


# ---------------------------------------------------------------------------
# 二、工具 → 来源
# ---------------------------------------------------------------------------
# 业务网关（/api/v1/tools）的工具没有前缀，必须显式登记；MCP 工具靠 mcp__ 前缀反解。
GATEWAY_TOOL_SOURCES: dict[str, str] = {
    "search_kb_documents": "knowledge_base",
    "web_search": "web",
    "list_my_approvals": "approval",
    "list_todo_approvals": "approval",
    "get_approval_result": "approval",
    "list_approval_handlers": "org",
    "submit_leave_request": "leave",
    "list_my_leaves": "leave",
    "get_my_quota": "quota",
    "sql_query": "biz_data",
}

# MCP 工具的中文动作名：用于「调用级引用」的标题，让用户看到「企业微信 · 最近会话」
# 而不是「企业微信 · recent_group_sessions」。未登记时回退原始 tool 名。
MCP_TOOL_LABELS: dict[tuple[str, str], str] = {
    ("wecom_cli", "whoami"): "当前身份",
    ("wecom_cli", "contact_search"): "通讯录",
    ("wecom_cli", "recent_group_sessions"): "最近会话",
    ("wecom_cli", "session_messages"): "会话消息",
    ("wecom_cli", "mail_search"): "邮件检索",
    ("wecom_cli", "mail_get"): "邮件详情",
    ("wecom_cli", "todo_list"): "待办清单",
    ("wecom_cli", "calendar_list"): "日历",
    ("wecom_cli", "meeting_list"): "会议列表",
    ("wecom_cli", "meeting_get"): "会议详情",
    ("wecom_cli", "doc_search"): "文档检索",
    ("wecom_cli", "doc_content"): "文档内容",
    ("wecom_cli", "sheet_info"): "表格信息",
    ("wecom_cli", "smartsheet_records"): "智能表格记录",
    ("wecom_cli", "smartpage_get"): "智能页面",
    ("wecom_cli", "disk_search"): "微盘检索",
    ("qq_mail", "list_folders"): "邮箱文件夹",
    ("qq_mail", "list_messages"): "邮件列表",
    ("qq_mail", "read_message"): "邮件详情",
    ("qq_mail", "search_messages"): "邮件检索",
}


def tool_source(name: str) -> str:
    """工具名 → 来源 code。

    三形态：
      * ``mcp__<server>__<tool>`` → server（与 client.py 的命名规则逐字对齐）
      * 网关工具 → ``GATEWAY_TOOL_SOURCES``
      * 其它内置（web_fetch / ask_user 等）→ 空串（不产生引用）
    """
    if not name:
        return ""
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        return parts[1] if len(parts) >= 2 else ""
    return GATEWAY_TOOL_SOURCES.get(name, "")


# 网关工具的中文动作名（与 GATEWAY_TOOL_SOURCES 同键集，分开是因为「归属哪个源」
# 与「叫什么动作」是两个问题：如 list_my_approvals 与 get_approval_result 同属 approval，
# 但一个查列表、一个查结果，引用里要能区分）。
GATEWAY_TOOL_LABELS: dict[str, str] = {
    "search_kb_documents": "知识库检索",
    "web_search": "联网检索",
    "list_my_approvals": "我的审批",
    "list_todo_approvals": "待审批",
    "get_approval_result": "审批结果",
    "list_approval_handlers": "可选处理人",
    "submit_leave_request": "请假申请",
    "list_my_leaves": "请假记录",
    "get_my_quota": "额度",
    "sql_query": "业务数据查询",
}


def tool_action_label(name: str) -> str:
    """工具名 → 中文动作名（调用级引用标题用）。"""
    if name.startswith("mcp__"):
        src = tool_source(name)
        parts = name.split("__", 2)
        tool = parts[2] if len(parts) >= 3 else name
        return MCP_TOOL_LABELS.get((src, tool), tool)
    return GATEWAY_TOOL_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# 三、条目级引用：从工具返回里挖「可展示的标题」
# ---------------------------------------------------------------------------
# 不同工具返回结构差异极大（联系人 / 邮件 / 文档 / 审批单），无法用一套 schema 描述。
# 口径：按**优先级顺序**探已知的标题类字段，命中即用；都不命中就退化为调用级引用。
_TITLE_KEYS: tuple[str, ...] = (
    "title", "subject", "docName", "doc_name", "fileName", "file_name",
    "name", "summary", "todo_title", "chat_title", "conversation_title",
    "display_name", "nickname", "content", "text", "snippet",
)
_ID_KEYS: tuple[str, ...] = ("id", "docId", "doc_id", "msgId", "msg_id", "userid",
                             "userId", "user_id", "key", "path", "url")

# 单次工具调用最多产出多少条引用：防止一次 ``list_messages`` 返回 200 封邮件把
# citations 撑成几百条（用户端只渲染前几条，落库却是整份 JSON）。
MAX_CITATIONS_PER_CALL = 6


def _first_str(item: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = item.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            return str(v).strip()
    return ""


def _truncate(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def normalize_payload(data):
    """把工具返回体归一成 Python 结构。

    ★ MCP 通道的真实形状是**字符串**：``client.py`` 把 content blocks 里的 text 用 ``\\n``
      拼成一个 str 返回（见 ``ToolClient.invoke``），而 hub 侧工具返回的是 JSON 文本。
      若不解析，所有 ``isinstance(data, list)`` 的条目抽取都会失效，
      MCP 数据源就永远只能退化成「调用级引用」——这正是「标注不出来源」的隐形原因。
    解析失败（纯文本结果，如 ``whoami`` 的人话输出）原样返回，由调用方按文本处理。
    """
    if not isinstance(data, str):
        return data
    s = data.strip()
    if not s or s[0] not in "[{":
        return data
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return data


def item_citations(name: str, data) -> list[dict]:
    """从工具返回体里抽取「条目级」引用 [{docId, title, source, label}]。

    只在能挖到标题时才返回条目；挖不到返回空列表，由调用方退化为调用级引用。
    """
    src = tool_source(name)
    data = normalize_payload(data)
    if not src or not isinstance(data, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        title = _first_str(item, _TITLE_KEYS)
        if not title:
            continue
        ident = _first_str(item, _ID_KEYS) or title
        if ident in seen:
            continue
        seen.add(ident)
        out.append({
            "docId": f"{src}:{ident}",
            "title": _truncate(title),
            "source": src,
            "label": source_label(src),
            "action": tool_action_label(name),
        })
        if len(out) >= MAX_CITATIONS_PER_CALL:
            break
    return out


def call_citation(name: str, count: int | None = None) -> dict:
    """调用级引用：一个工具调用算一条来源（条目挖不出标题时的兜底）。

    ``docId`` 用 ``<source>:<tool>``：同一次 run 里重复调用同一工具只算一条，
    与 ``nodes.py`` 里按 docId 去重的口径一致。
    """
    src = tool_source(name)
    action = tool_action_label(name)
    title = f"{source_label(src)} · {action}"
    if count:
        title += f"（{count} 条）"
    return {"docId": f"{src}:{name}", "title": title, "source": src,
            "label": source_label(src), "action": action}
