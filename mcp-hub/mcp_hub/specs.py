# -*- coding: utf-8 -*-
"""
**代理型**内置连接器的工具规格（唯一事实源）。

本文件与 Java 侧 V97 种子（server/aios-boot/.../V97__mcp_server_registry.sql）逐字对齐：
工具名、参数名、JSON Schema、read_only 必须与 Java 种子一致，否则「信任」写入的目录
会让模型调出 handler 不认识的工具（MailMcpHandler 的 supports() 返回 false）。

hub 自身不实现代理型连接器的工具逻辑，只在 /internal/mcp/probe 的 builtin transport 下直接读这里，
并把 tool 调用原样转发给 Java 的 /api/v1/mcp/builtin/{code}/call。

原生型连接器（工具逻辑在本进程）不在此登记，见 wecom_cli/catalog.py。
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
                "defaults": {"folder": "INBOX", "limit": 10, "unreadOnly": False},
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
                "defaults": {"folder": "INBOX"},
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
                "defaults": {"folder": "INBOX", "limit": 10},
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
                "defaults": {"cc": None},
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
    # 说明：企业微信（wechat_work 自建应用 + OAuth、wecom_group 群机器人）两个连接器
    # 已于 2026-10-30 下线并物理删除（docs/64 §9.7）。企业微信现在只有 wecom_cli（扫码），
    # 其工具目录的事实源是 wecom_cli/catalog.py。请勿把旧的两份代理声明加回来。
}


def tool_count(code: str) -> int:
    return len(BUILTIN_SERVERS.get(code, {}).get("tools", []))
