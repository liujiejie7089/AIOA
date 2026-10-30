# -*- coding: utf-8 -*-
"""双模式连接器的原生 MCP 服务器（/mcp/wechat_work）。

与 builtin.py 的代理服务器本质不同：这一台**自己实现工具逻辑**
（OAuth 授权 / 邮箱绑定 / 模式闸门 / LangGraph 分发），凭据只进加密存储。

工具分三类：
- lifecycle（connect / disconnect / connection_status）：直连实现，含 elicitation 授权交互；
- A 组（check_connection / get_my_profile / send_text_message / contact_search）；
- B 组（mail_* 六件套）。
后两类经 LangGraph 工作流分发（graph.run_tool），闸门拒绝与后端失败都转成
isError 的 CallToolResult —— 失败不静默。

授权交互（对齐 MCP URL elicitation，敏感交互不走 LLM 上下文）：
- A 模式：session.elicit_url 下发企微授权页 URL（snsapi_privateinfo / qrConnect 按 UA 分流）；
  客户端不支持 URL elicitation 时降级为把 authorizeUrl 放进工具结果，供 H5 渲染按钮。
- B 模式：ctx.elicit 表单（邮箱地址 + 客户端专用密码），服务端探活后才落库。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from . import graph, identity, mail, oauth, store, sync, wecom_api
from .catalog import SERVER_CODE, TOOLS, MAIL_SERVER_DEFAULTS
from .models import (
    MODE_A,
    MODE_B,
    STATUS_CONNECTED,
    Connection,
    Identity,
)

logger = logging.getLogger("mcp_hub.wecom")

# connect 等待授权回调完成的最长秒数（超时返回 pending，由 H5 轮询 connection_status）
CONNECT_WAIT_SECONDS = float(os.environ.get("WECOM_CONNECT_WAIT_SECONDS", "30"))


# ---------- 工具结果辅助 ----------


def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False, default=str))])


def _err(message: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=message)])


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ---------- 连接态辅助 ----------


def _status_view(conn: Connection | None) -> dict:
    if conn is None or conn.status != STATUS_CONNECTED:
        return {"code": SERVER_CODE, "connected": False, "mode": None,
                "hint": "尚未连接企业微信。A=企微 App 内 OAuth 授权（消息/通讯录）；B=企业邮箱客户端专用密码（邮件收发）"}
    view = conn.public_view()
    view["connected"] = True
    return view


async def _wait_connected(ident: Identity, mode: str, timeout: float) -> Connection | None:
    """等待授权回调把连接态写成功（回调接口与 connect 工具之间的接力）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        conn = await store.get_connection(ident.tenant_id, ident.user_id)
        if conn is not None and conn.status == STATUS_CONNECTED and mode in _modes_of(conn):
            return conn
        await asyncio.sleep(0.4)
    return None


def _modes_of(conn: Connection) -> list[str]:
    return store.split_modes(conn.mode)


# ---------- A 模式：OAuth 授权回调后的落库（回调接口与 connect 共用） ----------


async def complete_oauth(tenant_id: str, user_id: str, code: str) -> Connection:
    """用授权 code 换身份并落库（A 模式）。callback REST 与 mock 直连都走这里。

    <b>拿到 userid 只是「连上了」，不代表「拿到敏感字段」</b>（docs/63 §3.3）：
    只有 scope=snsapi_privateinfo **且成员在应用可见范围内**时，企微才回 user_ticket；
    没有 ticket 就拿不到 biz_mail。这条分支过去是静默的（连接成功、字段全 null），
    现在显式记进凭据：`sensitive_authorized=false` + `sensitive_note`，让上层与界面对用户说实话。
    """
    cfg = await store.get_tenant_config(tenant_id)
    if cfg is None:
        raise ValueError("租户未配置企业微信应用凭据（corpId / corpSecret / agentId）")
    api = wecom_api.get_backend()
    token = await oauth.get_access_token(cfg.corp_id, cfg.corp_secret, api.get_access_token)
    exchanged = await api.exchange_code(token, code)
    userid = exchanged.get("userid")
    if not userid:
        # 非企业成员：企微只回 openid；把它作为原因说出来，别让用户对着空错误发呆
        if exchanged.get("openid"):
            raise ValueError("授权人不是本企业成员（企微只返回 openid），请用企业微信内部账号授权")
        raise ValueError("授权回调未换取到 userid")

    detail: dict[str, Any] = {"userid": userid, "name": None, "biz_mail": None,
                              "position": None, "sensitive_authorized": False,
                              "sensitive_note": None}
    ticket = exchanged.get("user_ticket")
    if ticket:
        d = await api.get_user_detail(token, ticket)
        detail.update({
            "biz_mail": d.get("biz_mail"),
            "mobile": d.get("mobile"),
            "sensitive_authorized": True,
        })
    else:
        detail["sensitive_note"] = (
            "未获得 user_ticket：敏感字段（企业邮箱/手机）需要 scope=snsapi_privateinfo "
            "且该成员在应用可见范围内；本次仅拿到 userid"
        )
        logger.warning("A 模式未拿到 user_ticket（tenant=%s user=%s）：仅落 userid", tenant_id, userid)

    # 姓名/职务/部门不在 getuserdetail 里，走通讯录 user/get；失败不阻断（只是显示名缺失）
    if not detail["name"]:
        try:
            member = await api.get_member(token, userid)
            detail["name"] = member.get("name")
            detail["position"] = member.get("position")
            detail["department"] = member.get("department")
        except Exception as e:  # noqa: BLE001 —— 读不到通讯录不该让授权失败
            logger.info("读取成员 %s 详情未成功（不阻断连接）：%s", userid, type(e).__name__)

    conn = await store.ensure_connection(tenant_id, user_id)
    conn.a_credential = {
        "userid": userid,
        "name": detail.get("name"),
        "biz_mail": detail.get("biz_mail"),
        "position": detail.get("position"),
        "department": detail.get("department"),
        "sensitive_authorized": detail.get("sensitive_authorized"),
        "sensitive_note": detail.get("sensitive_note"),
        "bound_at": _now_iso(),
    }
    conn.mode = store.merge_mode(conn.mode, MODE_A)
    conn.status = STATUS_CONNECTED
    conn.account_label = detail.get("name") or detail.get("biz_mail") or userid
    await store.save_connection(conn)

    # 连接态回写 Java（唯一真相源）。失败不回滚：企微那边已经授权成功，
    # 回滚只会让用户白点一次；但必须把结果带出去，绝不静默（docs/63 §9.2）。
    # 三态：True=已同步 / False=真失败（告警）/ None=按设计跳过（sync 自己已记 info）。
    conn.synced = await sync.report_connected(
        tenant_id, user_id, SERVER_CODE, conn.account_label, conn.a_credential or {})
    if conn.synced is False:
        logger.warning("连接态未同步到 Java（tenant=%s user=%s）：manifest 闸门会看不到本次连接",
                       tenant_id, user_id)
    return conn


# ---------- lifecycle 工具实现 ----------


async def _tool_connect(ctx: Context, mode: str = "A") -> CallToolResult:
    ident = await identity.resolve(ctx)
    mode = (mode or "A").upper()
    if mode not in (MODE_A, MODE_B):
        return _err(f"不支持的授权方式：{mode}（仅 A / B）")

    existing = await store.get_connection(ident.tenant_id, ident.user_id)
    if existing is not None and existing.status == STATUS_CONNECTED and mode in _modes_of(existing):
        return _ok({**_status_view(existing), "note": f"{mode} 模式已连接（幂等）"})

    if mode == MODE_A:
        return await _connect_a(ctx, ident)
    return await _connect_b(ctx, ident)


async def _connect_a(ctx: Context, ident: Identity) -> CallToolResult:
    cfg = await store.get_tenant_config(ident.tenant_id)
    if cfg is None:
        return _err("管理员尚未配置企业微信应用凭据（corpId / corpSecret / agentId），请联系租户管理员")
    try:
        redirect_uri = oauth.redirect_uri_of(cfg)
    except ValueError as e:
        return _err(str(e))

    ua = oauth.user_agent_of(ctx)
    state = await oauth.issue_state(
        ident.tenant_id, ident.user_id, MODE_A,
        {"redirect_uri": redirect_uri, "ua": ua, "issued_at": _now_iso()},
    )
    if oauth.is_wecom_builtin(ua):
        url = oauth.build_authorize_url(cfg.corp_id, cfg.agent_id, redirect_uri, state)
        kind = "oauth_authorize"
        hint = "企微内置浏览器网页授权（snsapi_privateinfo）：可同时获得 userid 与企业邮箱地址"
    else:
        url = oauth.build_qr_connect_url(cfg.corp_id, cfg.agent_id, redirect_uri, state)
        kind = "qr_connect"
        hint = "当前不在企微 App 内，已降级为 PC 扫码授权（仅获取 userid，拿不到企业邮箱地址）；" \
               "如需完整身份请在企微 App 内打开本页面"

    elicited = False
    try:
        session = ctx.request_context.session
        result = await session.elicit_url(
            message=f"请在打开的页面完成企业微信授权。{hint}",
            url=url,
            elicitation_id=state,
            related_request_id=ctx.request_id,
        )
        elicited = result.action == "accept"
        if result.action == "decline":
            return _err("你已取消企业微信授权")
    except Exception as e:  # noqa: BLE001 —— 客户端不支持 URL elicitation 时降级
        logger.info("elicit_url 不可用（%s），降级为返回授权链接", type(e).__name__)

    if not elicited:
        return _ok({
            "connected": False,
            "pending": True,
            "kind": kind,
            "authorizeUrl": url,
            "state": state,
            "expiresInSeconds": 600,
            "note": "客户端未走 URL elicitation，请引导用户打开 authorizeUrl 完成授权，"
                    "完成后轮询 connection_status",
        })

    conn = await _wait_connected(ident, MODE_A, CONNECT_WAIT_SECONDS)
    if conn is None:
        return _ok({
            "connected": False,
            "pending": True,
            "kind": kind,
            "authorizeUrl": url,
            "state": state,
            "note": "授权已发起，等待企微回调。完成后可再调 connection_status 查看",
        })
    # _wait_connected 是从库里重新读出来的对象，拿不到 complete_oauth 在内存里打的 synced 标记，
    # 这里幂等再同步一次（Java 侧是 upsert），好把「manifest 闸门是否已认可」如实带回给调用方。
    if conn.synced is None:
        conn.synced = await sync.report_connected(
            ident.tenant_id, ident.user_id, SERVER_CODE, conn.account_label, conn.a_credential or {})
    note = "A 模式授权完成"
    if conn.synced is False:
        note += "；但连接态未同步到平台（manifest 闸门暂时看不到本次连接），请联系管理员检查服务间令牌配置"
    elif conn.synced is None:
        note += "；本地是 mock 身份，已跳过平台状态同步"
    return _ok({**_status_view(conn), "note": note})


class _MailBindForm(BaseModel):
    email: str = Field(description="企业邮箱地址，如 zhangsan@company.com")
    client_password: str = Field(description="客户端专用密码（邮箱设置中生成，非登录密码）")


async def _connect_b(ctx: Context, ident: Identity) -> CallToolResult:
    try:
        result = await ctx.elicit(
            "请填写企业邮箱与客户端专用密码。专用密码在邮箱设置（客户端/IMAP 选项）中生成，"
            "可随时吊销；我们只保存加密后的副本。",
            _MailBindForm,
        )
    except Exception as e:  # noqa: BLE001 —— 客户端不支持表单 elicitation
        return _err(f"当前客户端不支持授权表单elicitation（{type(e).__name__}），请升级 H5 客户端")
    if result.action != "accept" or result.data is None:
        return _err("你已取消企业邮箱绑定")

    form: _MailBindForm = result.data
    backend = mail.get_backend()
    try:
        probe = await backend.probe(form.email, form.client_password)
    except mail.MailError as e:
        return _err(f"邮箱验证失败：{e.reason}（code={e.code}）")
    except Exception as e:  # noqa: BLE001
        return _err(f"邮箱验证失败：{type(e).__name__}: {e}")

    conn = await store.ensure_connection(ident.tenant_id, ident.user_id)
    conn.b_credential = {
        "email": form.email,
        "client_password": form.client_password,
        "imap_host": MAIL_SERVER_DEFAULTS["imap_host"],
        "imap_port": MAIL_SERVER_DEFAULTS["imap_port"],
        "smtp_host": MAIL_SERVER_DEFAULTS["smtp_host"],
        "smtp_port": MAIL_SERVER_DEFAULTS["smtp_port"],
        "bound_at": _now_iso(),
        "probe": probe,
    }
    conn.mode = store.merge_mode(conn.mode, MODE_B)
    conn.status = STATUS_CONNECTED
    if not conn.account_label:
        conn.account_label = form.email
    await store.save_connection(conn)
    return _ok({**_status_view(conn), "note": "B 模式绑定完成，邮件工具已可用"})


async def _tool_disconnect(ctx: Context, mode: str | None = None) -> CallToolResult:
    ident = await identity.resolve(ctx)
    conn = await store.get_connection(ident.tenant_id, ident.user_id)
    if conn is None or conn.status != STATUS_CONNECTED:
        return _ok({"connected": False, "note": "本就未连接"})

    if mode:
        mode = mode.upper()
        remaining = store.drop_mode(conn.mode, mode)
        if remaining is None:
            await store.delete_connection(ident.tenant_id, ident.user_id)
            synced = await sync.report_disconnected(ident.tenant_id, ident.user_id, SERVER_CODE)
            return _ok({"connected": False, "stateSynced": synced,
                        "note": f"{mode} 已断开，连接已全部解除"})
        conn.mode = remaining
        if mode == MODE_A:
            conn.a_credential = None
        else:
            conn.b_credential = None
        await store.save_connection(conn)
        # 只剩 B（邮箱）时，A 的授权身份已经没了：平台侧也必须回到 NEED_AUTH，
        # 否则 manifest 会继续把「企微身份类工具」给模型，调用时才发现拿不到 userid。
        synced = await sync.report_disconnected(ident.tenant_id, ident.user_id, SERVER_CODE) \
            if MODE_A not in store.split_modes(remaining) else None
        return _ok({**_status_view(conn), "stateSynced": synced,
                    "note": f"{mode} 已断开，剩余模式 {remaining}"})

    await store.delete_connection(ident.tenant_id, ident.user_id)
    synced = await sync.report_disconnected(ident.tenant_id, ident.user_id, SERVER_CODE)
    return _ok({"connected": False, "stateSynced": synced, "note": "已断开全部模式，凭据已清除"})


async def _tool_status(ctx: Context) -> CallToolResult:
    ident = await identity.resolve(ctx)
    conn = await store.get_connection(ident.tenant_id, ident.user_id)
    return _ok(_status_view(conn))


# ---------- 模式工具执行器（经 LangGraph 分发） ----------


def _payload():
    return graph.current_payload()


async def _exec_check_connection(args: dict) -> dict:
    p = _payload()
    cfg = await store.get_tenant_config(p["identity"].tenant_id)
    if cfg is None:
        raise ValueError("租户未配置企业微信应用凭据")
    api = wecom_api.get_backend()
    token = await oauth.get_access_token(cfg.corp_id, cfg.corp_secret, api.get_access_token)
    from .crypto import mask

    return {"ok": True, "corpId": mask(cfg.corp_id), "agentId": cfg.agent_id,
            "tokenCached": bool(token), "mode": p["connection"].mode}


async def _exec_get_profile(args: dict) -> dict:
    p = _payload()
    a = (p["connection"].a_credential or {})
    if not a.get("userid"):
        raise ValueError("A 模式凭据缺失，请重新授权")
    return {"userid": a.get("userid"), "name": a.get("name"),
            "bizMail": a.get("biz_mail"), "boundAt": a.get("bound_at")}


async def _exec_send_text(args: dict) -> dict:
    p = _payload()
    touser = (args.get("touser") or "").strip()
    content = args.get("content")
    if not touser:
        raise ValueError("touser 不能为空")
    if not content:
        raise ValueError("content 不能为空")
    cfg = await store.get_tenant_config(p["identity"].tenant_id)
    if cfg is None:
        raise ValueError("租户未配置企业微信应用凭据")
    api = wecom_api.get_backend()
    token = await oauth.get_access_token(cfg.corp_id, cfg.corp_secret, api.get_access_token)
    return await api.send_text(token, cfg.agent_id, touser, content)


async def _exec_contact_search(args: dict) -> dict:
    p = _payload()
    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    limit = int(args.get("limit") or 10)
    cfg = await store.get_tenant_config(p["identity"].tenant_id)
    if cfg is None:
        raise ValueError("租户未配置企业微信应用凭据")
    api = wecom_api.get_backend()
    token = await oauth.get_access_token(cfg.corp_id, cfg.corp_secret, api.get_access_token)
    members = await api.search_contact(token, query, limit)
    return {"query": query, "count": len(members), "members": members}


def _mail_credential(p: dict) -> tuple[str, str]:
    b = (p["connection"].b_credential or {})
    email, pwd = b.get("email"), b.get("client_password")
    if not email or not pwd:
        raise ValueError("B 模式凭据缺失，请重新绑定企业邮箱")
    return email, pwd


async def _exec_mail_list_folders(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    folders = await mail.get_backend().list_folders(email, pwd)
    return {"folders": folders}


async def _exec_mail_list_messages(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    rows = await mail.get_backend().list_messages(
        email, pwd, args.get("folder") or "INBOX",
        int(args.get("limit") or 10), bool(args.get("unreadOnly")))
    return {"folder": args.get("folder") or "INBOX", "count": len(rows), "messages": rows}


async def _exec_mail_read_message(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    uid = args.get("uid")
    if uid is None:
        raise ValueError("uid 不能为空")
    return await mail.get_backend().read_message(email, pwd, int(uid), args.get("folder") or "INBOX")


async def _exec_mail_search_messages(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    query = (args.get("query") or "").strip()
    if not query:
        raise ValueError("query 不能为空")
    rows = await mail.get_backend().search_messages(
        email, pwd, query, args.get("folder") or "INBOX", int(args.get("limit") or 10))
    return {"query": query, "folder": args.get("folder") or "INBOX", "count": len(rows), "messages": rows}


async def _exec_mail_create_draft(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    for field in ("to", "subject", "body"):
        if not (args.get(field) or "").strip():
            raise ValueError(f"{field} 不能为空")
    return await mail.get_backend().create_draft(
        email, pwd, args["to"].strip(), args["subject"], args["body"], args.get("cc"))


async def _exec_mail_send_draft(args: dict) -> dict:
    p = _payload()
    email, pwd = _mail_credential(p)
    if args.get("draftId") is None:
        raise ValueError("draftId 不能为空")
    if not (args.get("requestId") or "").strip():
        raise ValueError("requestId 不能为空（幂等键）")
    return await mail.get_backend().send_draft(email, pwd, int(args["draftId"]), args["requestId"])


_EXECUTORS = {
    "check_connection": _exec_check_connection,
    "get_my_profile": _exec_get_profile,
    "send_text_message": _exec_send_text,
    "contact_search": _exec_contact_search,
    "mail_list_folders": _exec_mail_list_folders,
    "mail_list_messages": _exec_mail_list_messages,
    "mail_read_message": _exec_mail_read_message,
    "mail_search_messages": _exec_mail_search_messages,
    "mail_create_draft": _exec_mail_create_draft,
    "mail_send_draft": _exec_mail_send_draft,
}


def register_executors() -> None:
    for name, fn in _EXECUTORS.items():
        graph.register_executor(name, fn)


# ---------- 通用分发（模式工具 → LangGraph → CallToolResult） ----------


async def _dispatch(ctx: Context, tool_name: str, arguments: dict) -> CallToolResult:
    ident = await identity.resolve(ctx)
    conn = await store.get_connection(ident.tenant_id, ident.user_id)
    mode = conn.mode if (conn is not None and conn.status == STATUS_CONNECTED) else None
    outcome = await graph.run_tool(mode, tool_name, arguments,
                                   ident.tenant_id, ident.user_id,
                                   payload={"identity": ident, "connection": conn})
    if not outcome["ok"]:
        return _err(outcome["error"])
    return _ok(outcome["result"])


# ---------- 注册 ----------

_PARAMS: dict[str, list[tuple[str, type, Any]]] = {
    "connect": [("mode", str, "A")],
    "disconnect": [("mode", str, "")],
    "connection_status": [],
    "check_connection": [],
    "get_my_profile": [],
    "send_text_message": [("touser", str, None), ("content", str, None)],
    "contact_search": [("query", str, None), ("limit", int, 10)],
    "mail_list_folders": [],
    "mail_list_messages": [("folder", str, "INBOX"), ("limit", int, 10), ("unreadOnly", bool, False)],
    "mail_read_message": [("uid", int, None), ("folder", str, "INBOX")],
    "mail_search_messages": [("query", str, None), ("folder", str, "INBOX"), ("limit", int, 10)],
    "mail_create_draft": [("to", str, None), ("subject", str, None), ("body", str, None), ("cc", str, "")],
    "mail_send_draft": [("draftId", int, None), ("requestId", str, None)],
}

_IMPL = {
    "connect": _tool_connect,
    "disconnect": _tool_disconnect,
    "connection_status": _tool_status,
}


def _make_tool_fn(tool_name: str, props: list[tuple[str, type, Any]]):
    impl = _IMPL.get(tool_name)

    async def _fn(ctx: Context, **kwargs):
        if impl is not None:
            return await impl(ctx, **kwargs)
        return await _dispatch(ctx, tool_name, kwargs)

    params = [inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    for pname, ptype, default in props:
        if default is None:
            params.append(inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, annotation=ptype))
        else:
            params.append(
                inspect.Parameter(pname, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=ptype)
            )
    _fn.__name__ = f"{SERVER_CODE}__{tool_name}"
    _fn.__signature__ = inspect.Signature(params)
    _fn.__doc__ = f"{SERVER_CODE}.{tool_name}"
    return _fn


def build_server() -> FastMCP:
    """构建原生 wechat_work 服务器（streamable_http_path='/'，与代理服务器一致）。"""
    register_executors()
    mcp = FastMCP(SERVER_CODE, streamable_http_path="/")
    for tool in TOOLS:
        name = tool["name"]
        fn = _make_tool_fn(name, _PARAMS.get(name, []))
        mcp.add_tool(
            fn,
            name=name,
            description=tool["description"],
            annotations=ToolAnnotations(read_only_hint=tool["read_only"]),
        )
    return mcp


def server_info() -> dict:
    return {t["name"]: t["read_only"] for t in TOOLS}
