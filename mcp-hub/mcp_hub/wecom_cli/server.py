# -*- coding: utf-8 -*-
"""wecom_cli 原生 MCP 服务器：把 `wecom-cli` 的只读命令包成工具。

三条纪律（都在踩过的坑上立的）：

1. **身份只从 Authorization 来**，工具签名里没有任何 tenant/user 参数 ⇒
   模型无法「换一个人查」。这是「每人只管自己绑定的企微」的实现方式。
2. **未绑定就报人话错误**，且错误文案直接可给用户看（会原样进工具结果）——
   模型据此能正确引导「去连接器里点连接」，而不是瞎猜参数。
3. **参数两处事实源必须一致**：`catalog.py` 的 required 与 `_PARAMS` 的必填，
   启动时 `_assert_params_in_sync()` 不一致直接拒绝启动（`wecom/server.py` 有过一次教训）。
"""

from __future__ import annotations

import inspect
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import auth as cli_auth
from . import catalog, identity, profiles, runner

logger = logging.getLogger("mcp_hub.wecom_cli")

SERVER_CODE = catalog.SERVER_CODE
TOOLS = catalog.TOOLS


# ---------- 结果封装 ----------

def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text",
                                              text=json.dumps(data, ensure_ascii=False, default=str))])


def _err(msg: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=msg)])


# ---------- 小工具 ----------

def _since(days: int) -> tuple[str, str]:
    days = max(1, min(int(days or 7), 7))     # 官方硬限制：只能查最近 7 天
    end = datetime.now()
    begin = end - timedelta(days=days)
    fmt = "%Y-%m-%d %H:%M:%S"
    return begin.strftime(fmt), end.strftime(fmt)


def _first_list(data: Any, *keys: str) -> list:
    """CLI 各域的回包键名不统一（chats/users/mails/list…），按候选名取第一个列表。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
        for v in data.values():          # 兜底：任何位置的第一个列表
            if isinstance(v, list):
                return v
    return []


def _kw_list(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").replace("，", ",").split(",") if x.strip()]


async def _profile(ctx) -> tuple[identity.Identity, Any]:
    ident = await identity.resolve(ctx)
    d, shared = profiles.resolve(ident.tenant_id, ident.user_id)
    if shared:
        logger.warning("wecom_cli 使用共享授权目录（user=%s），仅限开发环境", ident.user_id)
    return ident, d


# ---------- 各工具实现 ----------

async def _exec_whoami(ctx: Context, **kw) -> CallToolResult:
    try:
        _, d = await _profile(ctx)
        names = await cli_auth.whoami(d)
        return _ok({"bound": True, "userName": names.get("userName"), "botName": names.get("botName")})
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))


async def _exec_contact_search(ctx: Context, keywords: str = "", **kw) -> CallToolResult:
    kws = _kw_list(keywords)
    if not kws:
        return _err("keywords 不能为空：请给出要搜索的姓名或拼音")
    try:
        _, d = await _profile(ctx)
        data = await runner.run(["contact", "users", "search", "--keywords", *kws], d, timeout=25)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = _first_list(data, "users", "user_list", "list")
    out = []
    for u in rows[:10]:
        if not isinstance(u, dict):
            continue
        deps = u.get("departments") or u.get("department") or []
        if isinstance(deps, str):
            deps = [deps]
        out.append({
            "name": u.get("name") or u.get("user_name"),
            "alias": u.get("alias"),
            "position": u.get("position") or u.get("title"),
            "departments": " / ".join(str(x) for x in deps if x),
            "email": u.get("email"),
        })
    return _ok({"count": len(out), "members": out,
                "scope": "我所在企业的通讯录（不代表对方授权过我任何东西）"})


async def _exec_recent_sessions(ctx: Context, days: int = 7, **kw) -> CallToolResult:
    b, e = _since(days)
    try:
        _, d = await _profile(ctx)
        data = await runner.run(["chat", "groups", "list", "--begin-time", b, "--end-time", e], d, timeout=25)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = _first_list(data, "chats", "groups", "list")
    out = []
    for c in rows[:20]:
        if not isinstance(c, dict):
            continue
        out.append({
            "chatName": c.get("chat_name") or "",
            "lastMessageTime": c.get("last_msg_time") or "",
            "messageCount": c.get("msg_count") or 0,
            # chat_id 是官方「框架加密输出」的句柄，用于下一步取消息；不要念给用户听
            "ref": c.get("chat_id") or "",
        })
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "sessions": out,
                "note": "ref 只能用于 session_messages，不要向用户展示"})


async def _exec_session_messages(ctx: Context, chat_id: str = "", days: int = 1, limit: int = 20,
                                 **kw) -> CallToolResult:
    if not (chat_id or "").strip():
        return _err("chat_id 不能为空：请先调用 recent_group_sessions 取得 ref")
    b, e = _since(days)
    try:
        _, d = await _profile(ctx)
        data = await runner.run(
            ["chat", "messages", "list", "--chat-id", chat_id.strip(),
             "--begin-time", b, "--end-time", e], d, timeout=25)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = _first_list(data, "messages", "msg_list", "list")
    out = []
    for m in rows[-max(1, min(int(limit or 20), 50)):]:
        if not isinstance(m, dict):
            continue
        out.append({
            "time": m.get("send_time") or m.get("msg_time") or m.get("create_time") or "",
            "from": m.get("sender_name") or m.get("from") or m.get("sender") or "",
            "type": m.get("msg_type") or m.get("type") or "text",
            "text": (m.get("text") or (m.get("content") or {}).get("text")
                     if isinstance(m.get("content"), dict) else m.get("text")) or "",
        })
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "messages": out})


async def _exec_mail_search(ctx: Context, keywords: str = "", days: int = 7, limit: int = 10,
                            onlyUnread: bool = False, **kw) -> CallToolResult:
    b, e = _since(days)
    args = ["mail", "search", "--begin-time", b, "--end-time", e,
            "--limit", str(max(1, min(int(limit or 10), 30)))]
    kws = _kw_list(keywords)
    if kws:
        args += ["--keywords", *kws]
    if onlyUnread:
        args += ["--only-unread", "true"]
    try:
        _, d = await _profile(ctx)
        data = await runner.run(args, d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = _first_list(data, "mails", "mail_list", "list")
    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        senders = m.get("sender") or m.get("from") or ""
        if isinstance(senders, dict):
            senders = senders.get("name") or senders.get("email") or ""
        out.append({
            "subject": m.get("subject") or "",
            "from": senders,
            "time": m.get("send_time") or m.get("date") or "",
            "isRead": m.get("is_read"),
            "hasAttachment": m.get("has_attachments") or m.get("has_attachment"),
            "ref": m.get("mail_id") or "",
        })
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "mails": out,
                "note": "ref 仅供后续读取正文，不要向用户展示"})


_EXEC = {
    "whoami": _exec_whoami,
    "contact_search": _exec_contact_search,
    "recent_group_sessions": _exec_recent_sessions,
    "session_messages": _exec_session_messages,
    "mail_search": _exec_mail_search,
}

# 第二处参数事实源：default=None ⇒ 必填。必须与 catalog 的 required 一致。
_PARAMS: dict[str, list[tuple[str, type, Any]]] = {
    "whoami": [],
    "contact_search": [("keywords", str, None)],
    "recent_group_sessions": [("days", int, 7)],
    "session_messages": [("chat_id", str, None), ("days", int, 1), ("limit", int, 20)],
    "mail_search": [("keywords", str, ""), ("days", int, 7), ("limit", int, 10),
                    ("onlyUnread", bool, False)],
}


def _assert_params_in_sync() -> None:
    problems = []
    for tool in TOOLS:
        name = tool["name"]
        declared = set((tool.get("input_schema") or {}).get("required") or [])
        actual = {p[0] for p in _PARAMS.get(name, []) if p[2] is None}
        if declared != actual:
            problems.append("%s：catalog required=%s / _PARAMS 必填=%s"
                            % (name, sorted(declared), sorted(actual)))
    if problems:
        raise RuntimeError("wecom_cli 工具参数声明与注册不一致：\n  " + "\n  ".join(problems))


def _make_tool_fn(tool_name: str, props: list[tuple[str, type, Any]]):
    fn_impl = _EXEC[tool_name]

    async def _fn(ctx: Context, **kwargs):
        return await fn_impl(ctx, **kwargs)

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for pname, ptype, default in props:
        if default is None:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=ptype))
        else:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY,
                                            default=default, annotation=ptype))
    _fn.__name__ = f"{SERVER_CODE}__{tool_name}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = f"{SERVER_CODE}.{tool_name}"
    return _fn


def build_server() -> FastMCP:
    _assert_params_in_sync()
    mcp = FastMCP(SERVER_CODE, streamable_http_path="/")
    for tool in TOOLS:
        name = tool["name"]
        mcp.add_tool(
            _make_tool_fn(name, _PARAMS.get(name, [])),
            name=name,
            description=tool["description"],
            annotations=ToolAnnotations(read_only_hint=tool["read_only"]),
        )
    return mcp


def tool_count() -> int:
    return len(TOOLS)
