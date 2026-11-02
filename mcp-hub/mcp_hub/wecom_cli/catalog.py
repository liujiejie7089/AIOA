# -*- coding: utf-8 -*-
"""wecom_cli 工具目录（唯一事实源）。

与 `wecom/catalog.py` 同样的纪律：本文件的 `input_schema.required` 决定**模型看到什么**，
`server.py::_PARAMS` 决定**真正校验什么**，两边由启动自检强制一致。

## 能力边界（必读，别照着授权页想当然）

企微授权页列的是「**机器人身份**被授予的能力上限」，但官方对**跨身份写**有硬限制：

    仅在在线文档（doc）、在线表格（sheet）、智能表格（smartsheet）、智能文档（smartpage）
    四类文档上允许跨身份操作；其他品类只能写入或修改**机器人自己创建或拥有**的数据。

实际后果（2026-11-02 实测）：
  · `todo list` 返回 0 条 —— 用户在企微 App 里的待办，机器人看不到（它不是创建人）；
  · `message send` 发出去的消息，发送方是**机器人**，不是用户本人；
  · `calendar create` / `meeting create` 建的是机器人名下的日程/会议。

所以写工具的 description 里必须把这条讲给模型听，并要求它动手前**跟用户确认**，
否则用户会以为「AI 替我建了待办」，实际建在机器人名下、自己的待办列表里看不到。

## read_only 标记

`read_only=True` 会映射成 MCP 的 `read_only_hint`，前端据此决定要不要弹写操作提示。
写工具一律 `False`，不要因为「看起来只是查一下」把写当读。
"""

from __future__ import annotations

SERVER_CODE = "wecom_cli"
SERVER_NAME = "企业微信（扫码）"

# 写工具统一要带的一句话：身份边界 + 必须确认
_WRITE_NOTE = ("⚠️ 写操作：官方限制「只能写入机器人自己创建/拥有的数据」（四类在线文档除外）。"
               "执行前必须先向用户确认要做的事，并在结果里说明「这是以机器人身份做的」，"
               "不要让用户以为改动在自己名下。")

TOOLS: list[dict] = [
    # ---------------------------------------------------------------- 身份 / 通讯录
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
        "description": ("在企业微信通讯录里按姓名/拼音/英文名找同事，返回姓名、userid、职务、部门路径、邮箱。"
                        "用于把『张三』这种名字换成后续接口要用的标识，或回答『XX 是哪个部门的』。\n"
                        "**要枚举候选（重名 / 用户只说『我同事』）时必须传 searchMode=list** —— "
                        "默认模式上游只回热度前 3，会把同名同事吃掉。"
                        "返回的 total/hasMore 表示命中有多少人；hasMore=true 时不要弹按钮，先让用户补条件。"
                        "注意：这是**我所在企业的通讯录**，不等于对方授权过我任何东西。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string",
                             "description": "搜索关键词，多个用逗号分隔（如「张三,李四」）。"
                                            "只支持姓名/拼音片段，按部门名搜不到（实测）。"},
                "searchMode": {"type": "string",
                               "description": "list=全量枚举候选（澄清重名时用）；留空=默认热度优先，只回前 3"},
            },
            "required": ["keywords"],
        },
        "read_only": True,
    },

    # ---------------------------------------------------------------- 会话 / 消息
    {
        "name": "recent_group_sessions",
        "description": ("列出我最近 N 天有消息的**群聊**会话（群名、最后消息时间、消息数）。"
                        "用户问『最近群里在聊什么』『我有哪些群有动静』时先用它拿列表，"
                        "再用 session_messages 看具体内容。官方限制只能查最近 7 天。\n"
                        "返回的每条会话都带一个 **chat_id** 字段 —— 要看某群的具体消息时，"
                        "把它原样作为 session_messages 的 chat_id 入参传进去。"),
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
                        "chat_id **可以传两种值**：① recent_group_sessions 返回的 chat_id；"
                        "② 直接传群名（如「成都易构」）—— 传群名时本工具会自己去匹配，"
                        "匹配不到或重名会返回候选列表让你选。**默认查 7 天**，不要假设只有今天的消息。"
                        "**不要把 chat_id 原样念给用户听**，用群名/人名指代即可。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string",
                            "description": "会话标识：recent_group_sessions 返回的 chat_id，或群名"},
                "days": {"type": "integer", "description": "回看天数，默认 7（官方上限 7）。"
                             "用户说『过去 N 天』就传 N；返回为空时本工具会自动放宽到 7 天再查一次"},
                "limit": {"type": "integer", "description": "最多返回多少条，默认 20"},
            },
            "required": ["chat_id"],
        },
        "read_only": True,
    },
    {
        "name": "message_send",
        "description": ("向指定单聊/群聊发送一条**文本**消息。chat_id 也可传群名或成员姓名。"
                        + _WRITE_NOTE + "另注：消息的发送方是**机器人**，不是用户本人。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string",
                            "description": "群会话 chat_id、群名，或单聊对象的 userid/姓名"},
                "text": {"type": "string", "description": "要发送的文本内容"},
            },
            "required": ["chat_id", "text"],
        },
        "read_only": False,
    },

    # ---------------------------------------------------------------- 邮件
    {
        "name": "mail_search",
        "description": ("搜索我自己的企业微信邮箱（主题/发件人/正文匹配），返回主题、发件人、时间、是否已读。"
                        "用户问『有没有 XX 的邮件』『最近有什么未读』时用它。"
                        "返回的 ref 是邮件句柄，读正文要把它传给 mail_get。"),
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
    {
        "name": "mail_get",
        "description": ("按 mail_search 返回的 ref 读取邮件正文（收件人、正文摘要）。"
                        "用户说『把第 2 封念一下』『这封邮件具体说了什么』时用它。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailIds": {"type": "string",
                            "description": "一个或多个 mail_search 返回的 ref，逗号分隔（最多 10 个）"},
            },
            "required": ["mailIds"],
        },
        "read_only": True,
    },
    {
        "name": "mail_send",
        "description": ("发送一封邮件。收件人用邮箱地址。" + _WRITE_NOTE
                        + "另注：发件人是机器人绑定的邮箱身份，发前必须把收件人、主题、正文读给用户确认。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "收件人邮箱地址，多个用逗号分隔"},
                "subject": {"type": "string", "description": "邮件主题"},
                "content": {"type": "string", "description": "正文（markdown）"},
            },
            "required": ["to", "subject", "content"],
        },
        "read_only": False,
    },

    # ---------------------------------------------------------------- 待办
    {
        "name": "todo_list",
        "description": ("列出**机器人视角**的待办（机器人创建的、或把用户列为参与人的）。"
                        "⚠️ 用户在企微 App 里自己建的待办**看不到** —— 返回 0 条时不要断言"
                        "『你没有待办』，要说明『机器人只能看到它自己创建的待办』。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "最多返回多少条，默认 10，最大 20"},
                "status": {"type": "string",
                           "description": "状态过滤，如 proceed / done，留空默认 proceed"},
                "keywords": {"type": "string", "description": "标题/描述关键词，多个用逗号分隔"},
            },
            "required": [],
        },
        "read_only": True,
    },
    {
        "name": "todo_get",
        "description": ("按待办 id 读取详情（标题、描述、参与人、截止时间）。"
                        "id 来自 todo_list 或 todo_create 的返回。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {"type": "string", "description": "待办 id，多个用逗号分隔（最多 20 个）"},
            },
            "required": ["items"],
        },
        "read_only": True,
    },
    {
        "name": "todo_create",
        "description": ("新建一条待办（机器人视角创建）。" + _WRITE_NOTE
                        + "建完把返回的待办 id 记下来，后续跟进要用。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "待办标题"},
                "description": {"type": "string", "description": "待办描述，可留空"},
                "followerIds": {"type": "string",
                                "description": "参与人 userid，多个用逗号分隔，可留空"},
                "deadline": {"type": "string", "description": "截止时间 YYYY-MM-DD HH:mm:ss，可留空"},
            },
            "required": ["title"],
        },
        "read_only": False,
    },

    # ---------------------------------------------------------------- 日程
    {
        "name": "calendar_list",
        "description": ("查询指定时间范围内的日程（标题、起止时间、参与人、地点、备注）。"
                        "用户问『我今天/本周有什么日程』时用它。都不传时间则从当前时间起 30 天。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "beginTime": {"type": "string", "description": "开始时间 YYYY-MM-DD HH:mm:ss，可留空"},
                "endTime": {"type": "string", "description": "结束时间 YYYY-MM-DD HH:mm:ss，可留空"},
            },
            "required": [],
        },
        "read_only": True,
    },
    {
        "name": "calendar_create",
        "description": ("新建一个日程。" + _WRITE_NOTE
                        + "时间必须是绝对时间（YYYY-MM-DD HH:mm:ss），先跟用户确认再建。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "日程标题"},
                "beginTime": {"type": "string", "description": "开始时间 YYYY-MM-DD HH:mm:ss"},
                "endTime": {"type": "string", "description": "结束时间 YYYY-MM-DD HH:mm:ss"},
                "attendees": {"type": "string", "description": "参与人 userid，多个用逗号分隔，可留空"},
                "location": {"type": "string", "description": "地点，可留空"},
                "description": {"type": "string", "description": "备注，可留空"},
            },
            "required": ["subject", "beginTime", "endTime"],
        },
        "read_only": False,
    },

    # ---------------------------------------------------------------- 会议
    {
        "name": "meeting_list",
        "description": ("列出指定时间范围内开始的会议（标题、起止、参会人数、地点）。"
                        "用户问『最近有什么会』时用它。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "beginTime": {"type": "string", "description": "开始时间 YYYY-MM-DD HH:mm:ss，可留空"},
                "endTime": {"type": "string", "description": "结束时间 YYYY-MM-DD HH:mm:ss，可留空"},
                "limit": {"type": "integer", "description": "每页数量，默认 20，最大 100"},
            },
            "required": [],
        },
        "read_only": True,
    },
    {
        "name": "meeting_get",
        "description": ("按会议 id 读取详情（参与人、会议室、智能纪要地址、录制文件地址）。"
                        "id 来自 meeting_list。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "meetingIds": {"type": "string", "description": "会议 id，多个用逗号分隔（最多 10 个）"},
            },
            "required": ["meetingIds"],
        },
        "read_only": True,
    },
    {
        "name": "meeting_create",
        "description": ("预约一个会议。" + _WRITE_NOTE
                        + "时间必须绝对，且先跟用户确认参会人。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "会议标题"},
                "beginTime": {"type": "string", "description": "开始时间 YYYY-MM-DD HH:mm:ss"},
                "endTime": {"type": "string", "description": "结束时间 YYYY-MM-DD HH:mm:ss"},
                "attendees": {"type": "string", "description": "参会人 userid，多个用逗号分隔，可留空"},
                "location": {"type": "string", "description": "地点，可留空"},
                "description": {"type": "string", "description": "备注，可留空"},
            },
            "required": ["subject", "beginTime", "endTime"],
        },
        "read_only": False,
    },

    # ---------------------------------------------------------------- 文档
    {
        "name": "doc_search",
        "description": ("按关键词搜索在线文档/表格（返回标题、类型、链接、摘要）。"
                        "用户问『有没有 XX 那份文档』时用它；拿到链接后可交给 sheet_info / "
                        "smartsheet_info / smartpage_get 读内容。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "搜索关键词，多个用逗号分隔"},
                "limit": {"type": "integer", "description": "最多返回多少篇，默认 10"},
                "docTypes": {"type": "string",
                             "description": "限定类型，可留空；如 doc,sheet,smartsheet,smartpage,ppt"},
            },
            "required": ["keywords"],
        },
        "read_only": True,
    },
    {
        "name": "doc_create",
        "description": ("新建一篇在线文档/表格/智能表格/智能文档。"
                        "这是四类**允许跨身份**的品类之一，但仍要先跟用户确认名称与类型。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "docName": {"type": "string",
                            "description": "文档名称（不能含 / \\ : * ? \" < > |）"},
                "docType": {"type": "string",
                            "description": "类型：doc / sheet / smartsheet / smartpage / ppt，默认 doc"},
                "content": {"type": "string",
                            "description": "初始内容（doc 为纯文本、smartpage 为 markdown），可留空"},
            },
            "required": ["docName"],
        },
        "read_only": False,
    },
    {
        "name": "doc_content",
        "description": ("读 Word 在线文档的正文（默认 markdown）。docId 可传 doc_create 返回的 docid 或文档链接。"
                        "用户说『这份文档写了什么』时用它。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
                "contentType": {"type": "string",
                                "description": "返回格式：markdown（默认）/ text / ooxml，可留空"},
            },
            "required": ["docId"],
        },
        "read_only": True,
    },
    {
        "name": "doc_append",
        "description": ("在已有 Word 在线文档**末尾追加**文本（不覆盖原内容）。"
                        "这是四类允许跨身份的品类之一，但仍要先跟用户确认追加内容。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
                "content": {"type": "string", "description": "要追加的纯文本"},
            },
            "required": ["docId", "content"],
        },
        "read_only": False,
    },
    {
        "name": "sheet_info",
        "description": ("读在线表格的基本信息与工作表列表（sheet_id、标题、行列数）。"
                        "docId 可传文档 ID 或文档链接。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
            },
            "required": ["docId"],
        },
        "read_only": True,
    },
    {
        "name": "smartsheet_info",
        "description": "读智能表格的基本信息与子表列表（子表 ID、名称、行列数、前五列）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
            },
            "required": ["docId"],
        },
        "read_only": True,
    },
    {
        "name": "smartsheet_records",
        "description": "读智能表格某个子表的记录（行）。sheetId 可留空由服务端选默认子表。",
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
                "sheetId": {"type": "string", "description": "子表 ID，可留空"},
                "limit": {"type": "integer", "description": "返回条数，默认 20，最大 100"},
            },
            "required": ["docId"],
        },
        "read_only": True,
    },
    {
        "name": "smartpage_get",
        "description": "读智能文档（smartpage）页面正文。docId 必填，pageId 可留空取默认页。",
        "input_schema": {
            "type": "object",
            "properties": {
                "docId": {"type": "string", "description": "文档 ID 或文档链接"},
                "pageId": {"type": "string", "description": "页面 ID，可留空"},
            },
            "required": ["docId"],
        },
        "read_only": True,
    },

    # ---------------------------------------------------------------- 微盘
    {
        "name": "disk_search",
        "description": ("在微盘里按关键词搜文件/文件夹（名称匹配，OR 关系）。"
                        "用户问『微盘里有没有 XX 的文件』时用它。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "关键词，多个用逗号分隔"},
                "limit": {"type": "integer", "description": "最多返回多少条，默认 10"},
            },
            "required": ["keywords"],
        },
        "read_only": True,
    },
]
