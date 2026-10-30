# -*- coding: utf-8 -*-
"""wecom_cli 工具目录（唯一事实源）。

与 `wecom/catalog.py` 同样的纪律：本文件的 `input_schema.required` 决定**模型看到什么**，
`server.py::_PARAMS` 决定**真正校验什么**，两边由启动自检强制一致。

本轮先只上**只读**工具（5 个）。理由：写入类命令（发消息/建待办/发邮件）在官方语义里
「只能写机器人创建或拥有的数据」，跨身份写只放开四类文档（见 docs/64 §二 F5）——
边界没实测清楚之前不开放写，避免出现「看着成功了其实改的是机器人的东西」。
"""

from __future__ import annotations

SERVER_CODE = "wecom_cli"
SERVER_NAME = "企业微信（扫码）"

TOOLS: list[dict] = [
    {
        "name": "whoami",
        "description": ("查「我」绑定的是哪个企业微信身份（姓名、以及代我执行的机器人名）。"
                        "用户问『我企微是谁』『绑定成功了吗』时用它。不需要任何参数。"
                        "注意：本工具**不返回**邮箱/手机号/工号，问这些字段时不要据此推测或拼造，"
                        "拿不到就如实说没有。"),
        "input_schema": {"type": "object", "properties": {}},
        "read_only": True,
    },
    {
        "name": "contact_search",
        "description": ("在企业微信通讯录里按姓名/拼音/英文名找同事，返回姓名、职务、部门路径、邮箱。"
                        "用于把『张三』这种名字换成后续接口要用的标识，或回答『XX 是哪个部门的』。"
                        "注意：这是**我所在企业的通讯录**，不等于对方授权过我任何东西。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string",
                             "description": "搜索关键词，多个用逗号分隔（如「张三,李四」）"},
            },
            "required": ["keywords"],
        },
        "read_only": True,
    },
    {
        "name": "recent_group_sessions",
        "description": ("列出我最近 N 天有消息的**群聊**会话（群名、最后消息时间、消息数）。"
                        "用户问『最近群里在聊什么』『我有哪些群有动静』时先用它拿列表，"
                        "再用 session_messages 看具体内容。官方限制只能查最近 7 天。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "回看天数，默认 7，最大 7"},
            },
            "required": [],
        },
        "read_only": True,
    },
    {
        "name": "session_messages",
        "description": ("读取某个会话最近 N 天的消息（谁说的、什么时间、内容）。"
                        "chat_id 必须来自 recent_group_sessions 的结果，或用户明确给出的会话标识；"
                        "**不要把 chat_id 原样念给用户听**，用群名/人名指代即可。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "会话标识，来自 recent_group_sessions"},
                "days": {"type": "integer", "description": "回看天数，默认 1，最大 7"},
                "limit": {"type": "integer", "description": "最多返回多少条，默认 20"},
            },
            "required": ["chat_id"],
        },
        "read_only": True,
    },
    {
        "name": "mail_search",
        "description": ("搜索我自己的企业微信邮箱（主题/发件人/正文匹配），返回主题、发件人、时间、是否已读。"
                        "用户问『有没有 XX 的邮件』『最近有什么未读』时用它。"
                        "只读：不支持发送、回复、删除、改标签（官方 CLI 也未开放这些写操作）。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "搜索关键词，多个用逗号分隔"},
                "days": {"type": "integer", "description": "回看天数，默认 7"},
                "limit": {"type": "integer", "description": "最多返回多少封，默认 10"},
                "onlyUnread": {"type": "boolean", "description": "只看未读，默认 false"},
            },
            "required": [],
        },
        "read_only": True,
    },
]
