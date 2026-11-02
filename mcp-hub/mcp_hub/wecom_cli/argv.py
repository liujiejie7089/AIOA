# -*- coding: utf-8 -*-
"""企微 CLI 的参数向量构造 —— **纯函数、零依赖**，可离线单测。

## 为什么单独抽出来

原先这些参数是在 `server.py` 里内联拼的，而「拼错一个 flag」的后果**不是本地异常**：
CLI 会返回一句 `error: unexpected argument 'true' found`，被 `_err()` 包成工具错误
交给模型 —— 模型于是对用户说「调用企业微信邮箱搜索工具时出现了参数错误」，然后放弃。
用户看到的是「这个助手不会用企微」，真实原因只是一个 flag 少写/多写。

2026-10-31 生产实测就是这么炸的：

    mail search ... --only-unread true        # ← 错
    error: unexpected argument 'true' found   # CLI 原话

`--only-unread` 在官方 CLI 里是**布尔开关（不带值）**，和 `--has-attachments`
`--only-subject` / `--has-star` 一样；帮助文本里那句「true-仅未读 false-都返回」
是文档的通用措辞，容易让人误以为要传值。

抽成纯函数后，`scripts/_check_wecom_cli_argv.py` 可以拿**真 CLI 的 `--help` 当事实源**，
逐个核对「flag 拼没拼错 / 该带值的带没带 / 布尔开关有没有多塞值」。
改这里的任何一行，那个哨兵都会先叫。

## 纪律

- 本模块**不许 import mcp / fastmcp / 任何网络库** —— 哨兵要在没有 hub 依赖时也能跑。
- 每个函数返回「`bin_path()` 之后的完整 argv」，即 `["mail", "search", ...]`。
- 时间格式由调用方给（`YYYY-MM-DD HH:MM:SS`），本模块不碰时钟，保证可测。
"""
from __future__ import annotations

import json

# 官方 CLI 里「布尔开关」型 flag：**只写 flag 本身，后面绝不跟值**。
# 新增命令时如果用到新的布尔 flag，先登记在这里，再写进 argv 构造函数。
BOOLEAN_FLAGS: frozenset[str] = frozenset({
    "--only-unread",
    "--has-attachments",
    "--has-star",
    "--only-reminder",
    "--only-subject",
})


def kw_list(raw: str) -> list[str]:
    """把「张三,李四」拆成列表；中文逗号也认。"""
    return [x.strip() for x in (raw or "").replace("，", ",").split(",") if x.strip()]


def mail_search(begin: str, end: str, keywords: str = "", limit: int = 10,
                only_unread: bool = False) -> list[str]:
    """`wecom-cli mail search`。布尔开关 `--only-unread` **不带值**。"""
    args = ["mail", "search",
            "--begin-time", begin, "--end-time", end,
            "--limit", str(max(1, min(int(limit or 10), 30)))]
    kws = kw_list(keywords)
    if kws:
        args += ["--keywords", *kws]
    if only_unread:
        args.append("--only-unread")      # ★ 开关，别跟 "true"
    return args


def session_messages(chat_id: str, begin: str, end: str) -> list[str]:
    """`wecom-cli chat messages list`。三个参数都是必填且带值。"""
    return ["chat", "messages", "list",
            "--chat-id", chat_id,
            "--begin-time", begin, "--end-time", end]


def recent_sessions(begin: str, end: str) -> list[str]:
    """`wecom-cli chat groups list`。"""
    return ["chat", "groups", "list", "--begin-time", begin, "--end-time", end]


def contact_search(keywords: str) -> list[str]:
    """`wecom-cli contact users search`。`--keywords` 是**变参**，可跟多个词。"""
    return ["contact", "users", "search", "--keywords", *kw_list(keywords)]


# ---------------------------------------------------------------------------
# 二、三梯队：待办 / 日程 / 会议 / 文档 / 表格 / 微盘 / 发消息
#
# 这些命令的入参形态比一梯队复杂（有 JSON 数组、有变参、有布尔开关），
# 一律在这里构造并登记，**不在 server.py 里内联拼** —— 理由见模块头：
# 拼错 flag 的后果是模型对用户说「参数错误」，而不是本地异常。
# 每条都过 `scripts/_check_wecom_cli_argv.py` 的 help 比对。
# ---------------------------------------------------------------------------

def _json_array(values: list[str]) -> str:
    """JSON 数组入参（`--items` / `--attendees` / `--meeting-ids` 都要求这种形态）。

    注意：runner 用 `create_subprocess_exec` 传 argv，**不经过 shell**，
    所以字符串里的引号不会被 shell 吃掉，也不需要额外转义。
    """
    return json.dumps([str(v) for v in values if str(v).strip()], ensure_ascii=False)


def _json_obj(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _attendees(values) -> str:
    """`--attendees` 要的是 `[{"userid": ...}]`，不是 `["userid"]`。

    2026-11-02 实测：只传字符串数组时 `--dry-run` 能过（它只校验 JSON 解析），
    真调用才报 640027。所以这里统一补成对象；已经给了 dict 的原样透传，
    这样调用方要传更多字段（如 name）也不用改这里。
    """
    out = []
    for v in values or []:
        if isinstance(v, dict):
            if v:
                out.append(v)
            continue
        s = str(v).strip()
        if s:
            out.append({"userid": s})
    return json.dumps(out, ensure_ascii=False)


def todo_list(limit: int = 10, status: str = "", keywords: str = "") -> list[str]:
    """`wecom-cli todo list` —— 机器人视角（**只包含机器人创建的待办**）。"""
    args = ["todo", "list", "--limit", str(max(1, min(int(limit or 10), 20)))]
    kws = kw_list(keywords)
    if kws:
        args += ["--keywords", *kws]
    st = kw_list(status)
    if st:
        args += ["--status-filter", *st]
    return args


def todo_get(ids: list[str]) -> list[str]:
    """`wecom-cli todo get`。待办 id 最多 20 个。"""
    return ["todo", "get", "--items", _json_array(ids[:20])]


def todo_create(item: dict) -> list[str]:
    """`wecom-cli todo create`。一次只建一条 —— 批量创建会让用户难以确认建了什么。"""
    return ["todo", "create", "--items", _json_obj([item])]


def todo_item(title: str, description: str = "", follower_ids=None,
              deadline: str = "") -> dict:
    """构造一条待办的 `--items` 元素。

    ⚠️ `deadline` 的 schema 是 `{type, value}`，**不是** `{type, date}`。
    2026-11-02 实测写成 `{"type":"date","date":"2026-11-05"}` 会被服务端判
    「存在未知字段 'items.deadline.date'」。注意 `--dry-run` **不校验字段名**
    （它只把请求体打出来），所以这条只能靠 `_check_wecom_cli_argv.py` 的 R6c
    拿 CLI 自己的 `--schema` 比对兜住。
    """
    item: dict = {"title": str(title).strip()}
    desc = (description or "").strip()
    if desc:
        item["description"] = desc
    fids = [str(x).strip() for x in (follower_ids or []) if str(x).strip()]
    if fids:
        item["follower_ids"] = fids
    dl = (deadline or "").strip()
    if dl:
        # 带时分秒的按 datetime，纯日期按 date
        item["deadline"] = {"type": "datetime" if len(dl) > 10 else "date", "value": dl}
    return item


def calendar_list(begin: str, end: str) -> list[str]:
    """`wecom-cli calendar schedules list`。"""
    return ["calendar", "schedules", "list", "--begin-time", begin, "--end-time", end]


def calendar_create(subject: str, begin: str, end: str, attendees: list[str] | None = None,
                    location: str = "", description: str = "") -> list[str]:
    """`wecom-cli calendar schedules create`（写）。subject/begin/end 三项必填。"""
    args = ["calendar", "schedules", "create",
            "--subject", subject, "--begin-time", begin, "--end-time", end]
    if attendees:
        args += ["--attendees", _attendees(attendees)]
    if location:
        args += ["--location", location]
    if description:
        args += ["--description", description]
    return args


def meeting_list(begin: str, end: str, limit: int = 20) -> list[str]:
    """`wecom-cli meeting list`。上限 100。"""
    return ["meeting", "list", "--begin-time", begin, "--end-time", end,
            "--limit", str(max(1, min(int(limit or 20), 100)))]


def meeting_get(ids: list[str]) -> list[str]:
    """`wecom-cli meeting get`。meeting_ids 最多 10 个。"""
    return ["meeting", "get", "--meeting-ids", _json_array(ids[:10])]


def meeting_create(subject: str, begin: str, end: str, attendees: list[str] | None = None,
                   location: str = "", description: str = "") -> list[str]:
    """`wecom-cli meeting create`（写）。subject/begin/end 三项必填。"""
    args = ["meeting", "create",
            "--subject", subject, "--begin-time", begin, "--end-time", end]
    if attendees:
        args += ["--attendees", _attendees(attendees)]
    if location:
        args += ["--location", location]
    if description:
        args += ["--description", description]
    return args


def message_send(chat_id: str, text: str) -> list[str]:
    """`wecom-cli message send`（写）。`--msg-type` 目前只支持 text，`--text` 是对象。"""
    return ["message", "send",
            "--chat-id", chat_id,
            "--msg-type", "text",
            "--text", _json_obj({"content": text})]


def mail_get(mail_ids: list[str]) -> list[str]:
    """`wecom-cli mail get`。`--mail-ids` 是**变参**，不是 JSON 数组。"""
    return ["mail", "get", "--mail-ids", *[str(x) for x in mail_ids[:10] if str(x).strip()]]


def mail_send(to: list[str], subject: str, content: str) -> list[str]:
    """`wecom-cli mail send`（写）。`--to` 是对象：`{emails:[...], userids:[...]}`。

    含 `@` 的按邮箱地址走 `emails`，其余按企微 userid 走 `userids` ——
    因为 `contact users search` 只返回 userid，不返回邮箱（2026-11-02 实测
    通讯录里的 `email` 字段一律为 null），只支持 emails 等于发不出信。
    """
    tos = [str(x).strip() for x in to if str(x).strip()]
    payload: dict[str, list[str]] = {}
    emails = [x for x in tos if "@" in x]
    uids = [x for x in tos if "@" not in x]
    if emails:
        payload["emails"] = emails
    if uids:
        payload["userids"] = uids
    return ["mail", "send",
            "--to", _json_obj(payload),
            "--subject", subject,
            "--content", content]


def doc_search(keywords: str, limit: int = 10, doc_types: str = "") -> list[str]:
    """`wecom-cli doc search`。`--keywords` 变参必填；`--doc-types` 也是变参。"""
    args = ["doc", "search", "--keywords", *kw_list(keywords),
            "--limit", str(max(1, min(int(limit or 10), 100)))]
    types = kw_list(doc_types)
    if types:
        args += ["--doc-types", *types]
    return args


def doc_create(doc_name: str, doc_type: str = "doc", content: str = "") -> list[str]:
    """`wecom-cli doc create`（写）。doc_type ∈ doc/sheet/smartsheet/smartpage/ppt。"""
    args = ["doc", "create", "--doc-name", doc_name, "--doc-type", doc_type]
    if content and doc_type in ("doc", "smartpage"):
        args += ["--content", content, "--content-type",
                 "markdown" if doc_type == "smartpage" else "text"]
    return args


def doc_content(docid: str, content_type: str = "") -> list[str]:
    """`wecom-cli doc contents get` —— 读 Word 文档正文（默认 markdown）。"""
    args = ["doc", "contents", "get", "--docid", docid]
    if content_type:
        args += ["--content-type", content_type]
    return args


def doc_append(docid: str, content: str) -> list[str]:
    """`wecom-cli doc contents append`（写）—— 在 Word 文档末尾追加纯文本。"""
    return ["doc", "contents", "append", "--docid", docid, "--content", content]


def sheet_info(docid: str) -> list[str]:
    """`wecom-cli sheet get`。docid 支持文档 ID 或链接。"""
    return ["sheet", "get", "--docid", docid]


def smartsheet_info(docid: str) -> list[str]:
    """`wecom-cli smartsheet get`。"""
    return ["smartsheet", "get", "--docid", docid]


def smartsheet_records(docid: str, sheet_id: str = "", limit: int = 20) -> list[str]:
    """`wecom-cli smartsheet records list`。sheet_id 不传则由服务端选默认子表。"""
    args = ["smartsheet", "records", "list", "--docid", docid,
            "--limit", str(max(1, min(int(limit or 20), 100)))]
    if sheet_id:
        args += ["--sheet-id", sheet_id]
    return args


def smartpage_get(docid: str, page_id: str = "") -> list[str]:
    """`wecom-cli smartpage pages get` —— 读智能主页正文。"""
    args = ["smartpage", "pages", "get", "--docid", docid]
    if page_id:
        args += ["--page-id", page_id]
    return args


def disk_search(keywords: str, limit: int = 10) -> list[str]:
    """`wecom-cli disk files search`。`--keywords` 是变参（OR 关系）。"""
    return ["disk", "files", "search", "--keywords", *kw_list(keywords),
            "--limit", str(max(1, min(int(limit or 10), 100)))]


def flag_violations(argv: list[str], takes_value: dict[str, bool]) -> list[str]:
    """按 `{flag: 是否带值}` 校验一条 argv，返回人类可读的问题列表。

    三件事都查：
      1. flag 不认识（拼错 / 版本里没有）；
      2. 该带值的没带（后面直接跟了下一个 flag 或到头了）；
      3. 布尔开关后面多塞了一个值（就是本次事故）。
    """
    problems: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        if tok not in takes_value:
            problems.append(f"未知 flag {tok}")
            i += 1
            continue
        if takes_value[tok]:
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is None or nxt.startswith("--"):
                problems.append(f"{tok} 需要值，但后面是 {nxt!r}")
                i += 1
                continue
            i += 2
        else:
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is not None and not nxt.startswith("--"):
                problems.append(f"{tok} 是布尔开关，不该带值（发现 {nxt!r}）")
            i += 1
    return problems
