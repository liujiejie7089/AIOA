# -*- coding: utf-8 -*-
"""双模式连接器目录（唯一事实源）。

对齐 Octop 的 catalog.json 思想，但把两种 auth_kind 挂在同一个连接器下：
用户在 H5 眼里只有一个「企业微信」，连接态分 A / B / A+B 三种，工具白名单按模式收窄。

纪律（与 specs.py 同）：
- 工具名一经发布不得改名；新增工具只能追加。
- V97/V99 已有的 check_connection / send_text_message / get_my_profile
  三个工具的 name / input_schema / required 必须保持原样（Java 种子与 hub 历史消费者都在用）。
"""

from __future__ import annotations

from .models import MODE_A, MODE_AB, MODE_B

SERVER_CODE = "wechat_work"
SERVER_NAME = "企业微信"

TOOLS: list[dict] = [
    # ---------- 连接生命周期（两模式共用，未连接也可调） ----------
    {
        "name": "connect",
        "group": "lifecycle",
        "modes": [],
        "description": (
            "连接企业微信连接器。A=企微 App 内 OAuth 网页授权（scope=snsapi_privateinfo，用户零填写）；"
            "B=企业邮箱客户端专用密码绑定（IMAP/SMTP）。已绑一种模式后再绑另一种会自动合并为 A+B 双模式"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["A", "B"],
                    "description": "授权方式：A=企微 OAuth 网页授权；B=企业邮箱客户端专用密码。默认 A",
                },
            },
            "required": [],
        },
        "read_only": False,
    },
    {
        "name": "disconnect",
        "group": "lifecycle",
        "modes": [],
        "description": "断开企业微信连接。mode=A 只清 OAuth 身份，mode=B 只清邮箱绑定；不传 mode 则全部断开",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["A", "B"],
                    "description": "要断开的模式；不传则断开全部",
                },
            },
            "required": [],
        },
        "read_only": False,
    },
    {
        "name": "connection_status",
        "group": "lifecycle",
        "modes": [],
        "description": "查询当前用户的企业微信连接状态（未连接 / A / B / A+B、账号脱敏显示、各模式绑定时间）",
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    # ---------- A 组：企微 OAuth 模式（身份 + 消息 + 通讯录） ----------
    {
        "name": "check_connection",
        "group": "A",
        "modes": [MODE_A],
        "description": "检查企业微信应用凭据是否有效（不返回 token 本身）",
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    {
        "name": "get_my_profile",
        "group": "A",
        "modes": [MODE_A],
        "description": "获取当前用户的企业微信身份（userid / 姓名 / 企业邮箱地址），来自 snsapi_privateinfo 授权后的 getuserdetail",
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    {
        "name": "send_text_message",
        "group": "A",
        "modes": [MODE_A],
        "description": "以企业微信自建应用身份向指定成员发送文本消息",
        "input_schema": {
            "type": "object",
            "properties": {
                "touser": {"type": "string", "description": "成员 UserID，多个用 | 分隔"},
                "content": {"type": "string", "description": "消息正文"},
            },
            "required": ["touser", "content"],
        },
        "read_only": False,
    },
    {
        "name": "contact_search",
        "group": "A",
        "modes": [MODE_A],
        "description": "按姓名/用户名关键词搜索企业通讯录成员（应用级只读，不需要对应用户授权）",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词（匹配姓名/用户名/邮箱前缀）"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最大 30"},
            },
            "required": ["query"],
        },
        "read_only": True,
    },
    # ---------- B 组：企业邮箱模式（IMAP/SMTP 读发） ----------
    {
        "name": "mail_list_folders",
        "group": "B",
        "modes": [MODE_B],
        "description": "列出邮箱的文件夹（收件箱、已发送等），用于确认 folder 参数取值",
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    {
        "name": "mail_list_messages",
        "group": "B",
        "modes": [MODE_B],
        "description": "列出指定文件夹最近的邮件摘要（发件人/主题/时间/是否未读）",
        "input_schema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最大 30"},
                "unreadOnly": {"type": "boolean", "description": "只返回未读邮件，默认 false"},
            },
            "required": [],
        },
        "read_only": True,
    },
    {
        "name": "mail_read_message",
        "group": "B",
        "modes": [MODE_B],
        "description": "读取单封邮件的正文（只读；不会把邮件标记为已读）",
        "input_schema": {
            "type": "object",
            "properties": {
                "uid": {"type": "integer", "description": "邮件 UID，来自 mail_list_messages / mail_search_messages 的返回"},
                "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
            },
            "required": ["uid"],
        },
        "read_only": True,
    },
    {
        "name": "mail_search_messages",
        "group": "B",
        "modes": [MODE_B],
        "description": "按关键词搜索邮件（IMAP TEXT 搜索，匹配主题与正文）",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                "limit": {"type": "integer", "description": "返回条数，默认 10，最大 30"},
            },
            "required": ["query"],
        },
        "read_only": True,
    },
    {
        "name": "mail_create_draft",
        "group": "B",
        "modes": [MODE_B],
        "description": "创建邮件草稿（不发送）。用户确认后必须再调 mail_send_draft 才真正发出",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "收件人邮箱，多个用逗号分隔"},
                "subject": {"type": "string", "description": "主题"},
                "body": {"type": "string", "description": "正文纯文本"},
                "cc": {"type": "string", "description": "抄送，可空"},
            },
            "required": ["to", "subject", "body"],
        },
        "read_only": False,
    },
    {
        "name": "mail_send_draft",
        "group": "B",
        "modes": [MODE_B],
        "description": "发送已创建的草稿。同一 requestId 重复调用只会发出一封（幂等）",
        "input_schema": {
            "type": "object",
            "properties": {
                "draftId": {"type": "integer", "description": "mail_create_draft 返回的 draftId"},
                "requestId": {"type": "string", "description": "调用方生成的唯一串（如 run_id+时间戳），用于幂等"},
            },
            "required": ["draftId", "requestId"],
        },
        "read_only": False,
    },
]

TOOLS_BY_NAME: dict[str, dict] = {t["name"]: t for t in TOOLS}
TOOL_NAMES: list[str] = [t["name"] for t in TOOLS]

# B 模式绑定表单的声明式字段（对齐 Octop credential_fields）：H5 按此渲染表单，
# 服务端按此校验；密码字段永不明文回显。
CREDENTIAL_FIELDS = {
    "imap_app_password": [
        {"name": "email", "label": "企业邮箱地址", "type": "email", "required": True,
         "placeholder": "zhangsan@company.com", "sensitive": False},
        {"name": "client_password", "label": "客户端专用密码", "type": "password", "required": True,
         "placeholder": "邮箱设置中生成的客户端专用密码", "sensitive": True},
    ],
}

# 可选：绑定 B 模式时用户可覆盖的服务器地址（默认腾讯企业邮）
MAIL_SERVER_DEFAULTS = {
    "imap_host": "imap.exmail.qq.com",
    "imap_port": 993,
    "smtp_host": "smtp.exmail.qq.com",
    "smtp_port": 465,
}


def tool_count() -> int:
    return len(TOOLS)
