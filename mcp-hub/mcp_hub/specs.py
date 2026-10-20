# -*- coding: utf-8 -*-
"""
内置 MCP 服务器工具规格（唯一事实源）。

本文件与 Java 侧 V97 种子（server/aios-boot/.../V97__mcp_server_registry.sql）逐字对齐：
工具名、参数名、JSON Schema、read_only 必须与 Java 种子一致，否则「信任」写入的目录
会让模型调出 handler 不认识的工具（MailMcpHandler / WeComMcpHandler 的 supports() 返回 false）。

hub 自身不实现任何工具逻辑，只在 /internal/mcp/probe 的 builtin transport 下直接读这里，
并把 tool 调用原样转发给 Java 的 /api/v1/mcp/builtin/{code}/call。
"""

BUILTIN_SERVERS = {
    "qq_mail": {
        "name": "QQ邮箱",
        "tools": [
            {
                "name": "list_folders",
                "description": "列出邮箱的文件夹（收件箱、已发送等），用于确认 folder 参数取值",
                "input_schema": {"type": "object", "properties": {}},
                "read_only": True,
            },
            {
                "name": "list_messages",
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
                "name": "read_message",
                "description": "读取单封邮件的正文（只读；不会把邮件标记为已读）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "uid": {"type": "integer", "description": "邮件 UID，来自 list_messages / search_messages 的返回"},
                        "folder": {"type": "string", "description": "文件夹名，默认 INBOX"},
                    },
                    "required": ["uid"],
                },
                "read_only": True,
            },
            {
                "name": "search_messages",
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
                "name": "create_draft",
                "description": "创建邮件草稿（不发送）。用户确认后必须再调 send_draft 才真正发出",
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
                "name": "send_draft",
                "description": "发送已创建的草稿。同一 requestId 重复调用只会发出一封（幂等）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "draftId": {"type": "integer", "description": "create_draft 返回的 draftId"},
                        "requestId": {"type": "string", "description": "调用方生成的唯一串（如 run_id+时间戳），用于幂等"},
                    },
                    "required": ["draftId", "requestId"],
                },
                "read_only": False,
            },
        ],
    },
    "wechat_work": {
        "name": "企业微信",
        "tools": [
            {
                "name": "check_connection",
                "description": "检查企业微信应用凭据是否有效（不返回 token 本身）",
                "input_schema": {"type": "object", "properties": {}},
                "read_only": True,
            },
            {
                "name": "send_text_message",
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
        ],
    },
}


def tool_count(code: str) -> int:
    return len(BUILTIN_SERVERS.get(code, {}).get("tools", []))
