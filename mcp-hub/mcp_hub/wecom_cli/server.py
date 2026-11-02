# -*- coding: utf-8 -*-
"""wecom_cli 原生 MCP 服务器：把 `wecom-cli` 的命令包成工具（17 只读 + 6 写，见 catalog）。

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

from ..transport import security_settings
from . import auth as cli_auth
from . import argv, catalog, identity, profiles, runner

logger = logging.getLogger("mcp_hub.wecom_cli")

SERVER_CODE = catalog.SERVER_CODE
TOOLS = catalog.TOOLS


# ---------- 结果封装 ----------

# CLI 每个回包都夹带这两段：给「客户端自己看的」安全提示与身份说明。
# 它们对模型没有信息价值（还占上下文），且官方明确写着「禁止透露给用户」⇒ 一律剔除。
_NOISE_KEYS = frozenset({"security_notice", "extra_identity_context"})


def _strip_noise(obj: Any, depth: int = 0) -> Any:
    if depth > 6:
        return obj
    if isinstance(obj, dict):
        return {k: _strip_noise(v, depth + 1) for k, v in obj.items() if k not in _NOISE_KEYS}
    if isinstance(obj, list):
        return [_strip_noise(v, depth + 1) for v in obj[:200]]
    return obj


def _ok(data: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text",
                                              text=json.dumps(_strip_noise(data),
                                                              ensure_ascii=False, default=str))])


def _err(msg: str) -> CallToolResult:
    return CallToolResult(isError=True, content=[TextContent(type="text", text=msg)])


# 日志里要打码的入参：`chat_id` 是官方框架加密出来的句柄，不该原样落日志。
_SENSITIVE_ARG = frozenset({"chat_id"})


def _mask(kwargs: dict) -> str:
    """把工具入参压成一行可安全落日志的字符串（长值截断、敏感值打码）。"""
    out: dict[str, Any] = {}
    for k, v in (kwargs or {}).items():
        if k in _SENSITIVE_ARG and isinstance(v, str):
            out[k] = (v[:6] + "…") if len(v) > 8 else "***"
        elif isinstance(v, str) and len(v) > 60:
            out[k] = v[:60] + "…"
        else:
            out[k] = v
    return json.dumps(out, ensure_ascii=False, default=str)


# ---------- 小工具 ----------

# 官方对 begin_time 卡的是「**恰好 168 小时**滚动窗口」，多一秒都拒（850016）。
# 而这里算完 begin 到 CLI 真正发出请求还有秒级延迟（asyncio 起子进程 + 网络往返），
# 加上 strftime 把毫秒截掉，days=7 时 begin 必然比服务端的下界老 1~3 秒 ⇒ **每次都失败**。
#
# 2026-11-02 实测二分（now=17:55:23，同一个合法 chat_id）：
#   begin=2026-10-26 15:55 → 850016；begin=2026-10-26 17:55（= Python 精确算出的 now-7d）→ 850016
#   begin=2026-10-26 18:10 → 正常返回 7 条；10-27 00:00 / 09:00 → 正常
# 边界就在 168 小时整，余量是秒级，所以固定让出 1 小时把这 3 秒的死区彻底盖掉。
_BEGIN_MARGIN = timedelta(hours=1)


def _since(days: int) -> tuple[str, str]:
    days = max(1, min(int(days or 7), 7))     # 官方硬限制：只能查最近 7 天
    end = datetime.now()
    begin = end - timedelta(days=days) + _BEGIN_MARGIN
    fmt = "%Y-%m-%d %H:%M:%S"
    return begin.strftime(fmt), end.strftime(fmt)


_TS = "%Y-%m-%d %H:%M:%S"


def _range_forward(begin: str, end: str) -> tuple[str, str]:
    """日程/会议的时间窗：默认「现在 → 现在 + 30 天」（与 CLI 自身默认一致）。

    ⚠️ 不能复用 `_since()` —— 那里把天数夹到 7 是**聊天/邮件**的官方限制，
    用在这里会把「未来 30 天的会议」静默变成「过去 7 天」，用户问「我明天有什么会」
    会得到空列表，还以为自己没会。
    """
    b = (begin or "").strip() or datetime.now().strftime(_TS)
    e = (end or "").strip()
    if not e:
        e = (datetime.strptime(b, _TS) + timedelta(days=30)).strftime(_TS)
    return b, e


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


def _clip(v: Any, n: int = 400) -> str:
    """长文本截断（正文/摘要用）。CLI 返回的正文动辄上万字，全塞给模型只会挤掉上下文。"""
    s = "" if v is None else str(v)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


async def _call(args: list[str], d, timeout: float = 25) -> Any:
    """跑一条 CLI 命令，并把「业务错误」也当失败抛出来。

    ⚠️ 关键：企微 CLI 的业务错误是 **exit code 0 + `{"error": {...}}`**，不是非零退出。
    2026-11-02 实测 `chat messages list --chat-id 成都易构` ⇒ stdout 是
    `{"error":{"code":40073,"message":"非法的 'chat_id'..."}}`，退出码 0。
    原先各 executor 直接 `_first_list(data)` 取列表 ⇒ 拿到空数组 ⇒ 工具「成功返回 0 条」，
    模型于是对用户说「这个群没有消息」，而不是「chat_id 不合法」。必须在这里拦住。
    """
    data = await runner.run(args, d, timeout=timeout)
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            code = err.get("code")
            msg = _clip(err.get("message") or err, 200)
            raise runner.CliError(f"企业微信返回错误（{code}）：{msg}")
    return data


def _rows(data: Any, *keys: str) -> list[dict]:
    """取列表并只保留 dict 元素（各域回包键名不统一，交给 `_first_list` 兜底）。"""
    return [x for x in _first_list(data, *keys) if isinstance(x, dict)]


def _pick(d: dict, *names: str, default: Any = "") -> Any:
    """按候选键名取第一个非空值（同一个字段在不同域里叫法不一样）。"""
    for n in names:
        v = d.get(n)
        if v not in (None, "", [], {}):
            return v
    return default


def _deadline_text(v: Any) -> str:
    """待办 deadline 是 `{"type","value"}` 对象；直接 str() 会把 dict repr 丢给模型。"""
    if isinstance(v, dict):
        return _clip(v.get("value") or v.get("datetime") or v.get("date") or "", 40)
    return _clip(v, 40)


def _names(v: Any) -> str:
    """把 `[{"userid","user_name"}]` 归一成「刘洋、张三」。

    2026-11-02 实测：待办/日程的参与人是对象数组，`_clip` 出来的
    `"{'userid': ...}"` 既难读又会把 userid 混进正文，模型复述时容易张冠李戴。
    """
    if isinstance(v, str):
        return _clip(v, 200)
    if not isinstance(v, list):
        return ""
    out = []
    for x in v[:10]:
        if isinstance(x, dict):
            n = x.get("user_name") or x.get("name") or x.get("userid") or ""
            st = x.get("user_status") or ""
            out.append(f"{n}({st})" if st and st != "accept" else str(n))
        else:
            out.append(str(x))
    return _clip("、".join(x for x in out if x), 200)


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


#  通讯录候选上限：与澄清卡能渲染的按钮数（agent ask_user 上限 10）对齐。
#  超过就别再往回塞 —— 模型看到 10 条以外的人做不出选择，用户也只能盲选。
_CONTACT_MAX = 10


async def _exec_contact_search(ctx: Context, keywords: str = "", searchMode: str = "",
                               **kw) -> CallToolResult:
    kws = _kw_list(keywords)
    if not kws:
        return _err("keywords 不能为空：请给出要搜索的姓名、姓名片段或拼音")
    mode = (searchMode or "").strip().lower()
    if mode not in ("", "list"):
        return _err("searchMode 只支持 list（全量枚举候选）或留空（默认热度优先，只回前 3）")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.contact_search(keywords, mode), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = [u for u in _first_list(data, "users", "user_list", "list") if isinstance(u, dict)]
    # total 用上游的 users_count（缺省退回列表长度）。注意：默认模式上游自己就截到
    # 热度 top3，所以 total 只能当「这次返回了几人」，不能当「公司里有几个人叫这个」——
    # 要枚举候选必须传 searchMode=list（2026-11-02 实测两种模式返回数不同）。
    total = data.get("users_count") if isinstance(data, dict) else None
    if not isinstance(total, int) or total < len(rows):
        total = len(rows)
    out = []
    for u in rows[:_CONTACT_MAX]:
        deps = u.get("departments") or u.get("department") or []
        if isinstance(deps, str):
            deps = [deps]
        out.append({
            "name": u.get("name") or u.get("user_name"),
            # userid 必须回给模型：发邮件 / 拉日程参与人 / 建待办跟进人都要用它，
            # 而通讯录里的 email 字段实测恒为 null（2026-11-02）。
            "userid": u.get("userid") or u.get("user_id") or u.get("id"),
            "alias": u.get("alias"),
            "position": u.get("position") or u.get("title"),
            "departments": " / ".join(str(x) for x in deps if x),
            "email": u.get("email"),
        })
    payload: dict[str, Any] = {
        "count": len(out), "total": total, "hasMore": total > len(out), "members": out,
        "scope": "我所在企业的通讯录（不代表对方授权过我任何东西）",
    }
    if payload["hasMore"]:
        payload["hint"] = (f"命中 {total} 人，这里只回了前 {len(out)} 个："
                           "**不要**拿这份列表弹按钮，先让用户补充部门/工号或更完整的姓名")
    elif not out:
        payload["hint"] = ("通讯录里没搜到：告诉用户没找到，并建议按部门/工号或更完整的姓名再搜；"
                           "不要自己编一个人出来")
    elif len(out) > 1:
        payload["hint"] = "候选不止一个：用 ask_user 让用户选，value 填 userid、label 填「姓名（部门/职位）」"
    return _ok(payload)


async def _exec_recent_sessions(ctx: Context, days: int = 7, **kw) -> CallToolResult:
    b, e = _since(days)
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.recent_sessions(b, e), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as e:
        return _err(str(e))
    rows = _first_list(data, "chats", "groups", "list")
    out = []
    for c in rows[:20]:
        if not isinstance(c, dict):
            continue
        # chat_id 是官方「框架加密输出」的句柄，用于下一步取消息；不要念给用户听。
        # ⚠️ 字段名必须是 chat_id（与 session_messages 的入参同名）——
        # 早期这里叫 ref，模型拿到 ref 却要填 chat_id ⇒ 「chat_id 无效」
        # （2026-10-31 用户实测）。ref 保留为兼容别名，老客户端仍能读到。
        chat_id = c.get("chat_id") or ""
        out.append({
            "chatName": c.get("chat_name") or "",
            "lastMessageTime": c.get("last_msg_time") or "",
            "messageCount": c.get("msg_count") or 0,
            "chat_id": chat_id,
            # 兼容别名：老代码按 ref 读
            "ref": chat_id,
        })
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "sessions": out,
                "note": "chat_id 用于 session_messages 的入参，不要向用户展示该值本身"})


async def _resolve_session(raw: str, d) -> tuple[str, list[str]]:
    """把「chat_id 句柄**或**群名」统一成可用 chat_id。

    为什么允许传群名：`chat_id` 是框架加密出来的句柄，**只在当次工具结果里存在**。
    模型要跨轮用它，就必须把句柄留在上下文里；而旧版历史回灌只带正文、不带工具结果，
    于是下一轮模型手里只有群名，硬当 chat_id 传 ⇒ 企微回 `40073 非法的 'chat_id'`
    ⇒ 模型对用户说「我无法获取具体消息」（2026-10-31 会话 1436 实测）。

    修法有两层：
      ① 历史里回灌工具摘要（Java `RunService.formatToolDigest` + agent `_tool_digest`）；
      ② 本函数兜底：名字也能用 —— 用户在对话里说的本来就是群名。

    返回 `(chat_id, 候选名列表)`；`chat_id` 为空表示没匹配到（或重名需要用户选）。
    """
    b, e = _since(7)
    data = await _call(argv.recent_sessions(b, e), d)
    sess = [(str(_pick(c, "chat_name", "name")), str(_pick(c, "chat_id") or ""))
            for c in _rows(data, "chats", "groups", "list")]
    for _, cid in sess:                                  # ① 本身就是合法句柄
        if cid and cid == raw:
            return cid, []
    exact = [cid for name, cid in sess if name and name == raw]
    if len(exact) == 1:
        return exact[0], []
    part = [(name, cid) for name, cid in sess if name and (raw in name or name in raw)]
    if len(part) == 1:
        return part[0][1], []
    return "", [name for name, _ in part]


async def _exec_session_messages(ctx: Context, chat_id: str = "", days: int = 7, limit: int = 20,
                                 **kw) -> CallToolResult:
    raw = (chat_id or "").strip()
    if not raw:
        return _err("chat_id 不能为空：请先调用 recent_group_sessions 取得 chat_id，或直接传群名")
    used_days = max(1, min(int(days or 7), 7))
    b, e = _since(used_days)
    try:
        _, d = await _profile(ctx)
        target = raw
        try:
            data = await _call(argv.session_messages(target, b, e), d)
        except runner.CliError as first:
            # 句柄不合法（40073）或用户直接给了群名 ⇒ 按名字在最近 7 天会话里找一次
            resolved, cands = await _resolve_session(raw, d)
            if not resolved:
                if cands:
                    return _err("匹配到多个会话：" + "、".join(cands)
                                + "。请让用户确认是哪一个，再用完整群名重试。")
                return _err(f"没找到会话「{raw}」（官方只能查最近 7 天）。"
                            f"可先调用 recent_group_sessions 看有哪些群。原始错误：{first}")
            target = resolved
            data = await _call(argv.session_messages(target, b, e), d)
        rows = _rows(data, "messages", "msg_list", "list")
        # ★ 空窗口自动放宽到 7 天。
        #   模型经常**不传 days**（旧默认是 1 天），于是查了个空窗口，再对用户说
        #   「过去 7 天内没有新的消息」—— 2026-11-02 用户实测就是这个：
        #   群最后一条在 10-31 12:45，1 天窗口必然空，而它嘴上说的是「7 天」。
        #   不跟模型的参数较劲：直接放宽再查一次，并在回包里如实标注实际用了几天。
        if not rows and used_days < 7:
            used_days = 7
            b, e = _since(used_days)
            data = await _call(argv.session_messages(target, b, e), d)
            rows = _rows(data, "messages", "msg_list", "list")
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    out = []
    for m in rows[-max(1, min(int(limit or 20), 50)):]:
        # 实测字段：{"userid","user_name","send_time","msg_type","text":{"content":…}}
        body = m.get("text")
        if isinstance(body, dict):
            body = body.get("content") or body.get("text") or ""
        if not body:
            body = m.get("content")
            if isinstance(body, dict):
                body = body.get("text") or body.get("content") or ""
        out.append({
            "time": _pick(m, "send_time", "msg_time", "create_time"),
            "from": _pick(m, "user_name", "sender_name", "from", "sender"),
            "type": _pick(m, "msg_type", "type", default="text"),
            "text": _clip(body, 400),
        })
    return _ok({"range": {"begin": b, "end": e}, "days": used_days,
                "count": len(out), "messages": out})


async def _exec_mail_search(ctx: Context, keywords: str = "", days: int = 7, limit: int = 10,
                            onlyUnread: bool = False, **kw) -> CallToolResult:
    b, e = _since(days)
    # ★ 参数向量一律走 argv.py（纯函数、有哨兵核对）：
    #   2026-10-31 生产事故是这里内联拼成 `["--only-unread", "true"]`，
    #   而该 flag 是**布尔开关不带值** ⇒ CLI 回 `error: unexpected argument 'true' found`
    #   ⇒ 模型对用户说「参数错误」。只有问「未读」才会触发，所以极其像「模型不会用工具」。
    args = argv.mail_search(b, e, keywords=keywords, limit=limit, only_unread=onlyUnread)
    try:
        _, d = await _profile(ctx)
        data = await _call(args, d, timeout=30)
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


# ---------- 第二梯队：发消息 / 邮件正文 / 待办 / 日程 / 会议 ----------

async def _exec_message_send(ctx: Context, chat_id: str = "", text: str = "", **kw) -> CallToolResult:
    raw = (chat_id or "").strip()
    if not raw:
        return _err("chat_id 不能为空：可传群名、群 chat_id 或单聊对象的 userid/姓名")
    if not (text or "").strip():
        return _err("text 不能为空：请给出要发送的文本内容")
    try:
        _, d = await _profile(ctx)
        target = raw
        try:
            data = await _call(argv.message_send(target, text), d, timeout=30)
        except runner.CliError:
            resolved, cands = await _resolve_session(raw, d)
            if not resolved:
                if cands:
                    return _err("匹配到多个会话：" + "、".join(cands)
                                + "。请让用户确认发给哪一个。")
                return _err(f"没找到会话「{raw}」，无法发送。可先用 recent_group_sessions 确认群名。")
            target = resolved
            data = await _call(argv.message_send(target, text), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"sent": True, "to": target[:6] + "…" if len(target) > 12 else target,
                "chars": len(text), "result": data,
                "note": "消息的发送方是机器人身份，不是用户本人"})


async def _exec_mail_get(ctx: Context, mailIds: str = "", **kw) -> CallToolResult:
    ids = _kw_list(mailIds)
    if not ids:
        return _err("mailIds 不能为空：请先调用 mail_search，把它返回的 ref 传进来")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.mail_get(ids), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "mails", "mail_list", "list")
    out = [{
        "subject": _pick(m, "subject"),
        "from": _pick(m, "sender", "from") if not isinstance(_pick(m, "sender", "from"), dict)
                else _pick(_pick(m, "sender", "from"), "name", "email"),
        "to": _clip(m.get("to") or m.get("receivers"), 200),
        "time": _pick(m, "send_time", "date"),
        "text": _clip(_pick(m, "text", "content", "body", "snippet"), 1500),
    } for m in rows]
    return _ok({"count": len(out), "mails": out})


async def _exec_mail_send(ctx: Context, to: str = "", subject: str = "", content: str = "",
                          **kw) -> CallToolResult:
    tos = _kw_list(to)
    if not tos:
        return _err("to 不能为空：请给出收件人邮箱，或通讯录里的 userid（contact_search 可获得）")
    if not (subject or "").strip():
        return _err("subject 不能为空：邮件主题是必填项")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.mail_send(tos, subject, content or ""), d, timeout=60)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"sent": True, "to": tos, "subject": subject, "result": data,
                "note": "发件人是机器人绑定的邮箱身份"})


async def _exec_todo_list(ctx: Context, limit: int = 10, status: str = "", keywords: str = "",
                          **kw) -> CallToolResult:
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.todo_list(limit=limit, status=status, keywords=keywords), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "items", "todo_list", "list")
    out = [{
        "id": _pick(t, "todo_id", "id"),
        "title": _pick(t, "title", "subject"),
        "description": _clip(_pick(t, "description"), 300),
        "status": _pick(t, "status", "state"),
        "deadline": _deadline_text(_pick(t, "deadline")),
        "followers": _names(_pick(t, "follower_ids", "followers")),
    } for t in rows]
    return _ok({"count": len(out), "todos": out,
                "scope_note": "机器人视角：只含机器人创建/参与的待办，看不到用户在企微 App 自建的待办"})


async def _exec_todo_get(ctx: Context, items: str = "", **kw) -> CallToolResult:
    ids = _kw_list(items)
    if not ids:
        return _err("items 不能为空：请传入待办 id（来自 todo_list 或 todo_create）")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.todo_get(ids), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "items", "todo_list", "list")
    out = [{
        "id": _pick(t, "todo_id", "id"),
        "title": _pick(t, "title", "subject"),
        "description": _clip(_pick(t, "description"), 600),
        "status": _pick(t, "status", "state"),
        "deadline": _deadline_text(_pick(t, "deadline")),
        "followers": _names(_pick(t, "follower_ids", "followers")),
    } for t in rows]
    return _ok({"count": len(out), "todos": out})


async def _exec_todo_create(ctx: Context, title: str = "", description: str = "",
                            followerIds: str = "", deadline: str = "", **kw) -> CallToolResult:
    if not (title or "").strip():
        return _err("title 不能为空：请给出待办标题")
    item = argv.todo_item(title, description, _kw_list(followerIds), deadline)
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.todo_create(item), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"created": True, "input": item, "result": data,
                "note": "以机器人身份创建；用户在企微 App 的「我的待办」里可能看不到"})


async def _exec_calendar_list(ctx: Context, beginTime: str = "", endTime: str = "",
                              **kw) -> CallToolResult:
    try:
        b, e = _range_forward(beginTime, endTime)
    except ValueError:
        return _err("时间格式必须是 YYYY-MM-DD HH:mm:ss（例如 2026-11-03 09:00:00）")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.calendar_list(b, e), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "schedules", "schedule_list", "list")
    out = [{
        "id": _pick(s, "schedule_id", "id"),
        "subject": _pick(s, "subject", "title"),
        "begin": _pick(s, "begin_time", "start_time"),
        "end": _pick(s, "end_time"),
        "location": _clip(_pick(s, "location"), 100),
        "attendees": _names(_pick(s, "attendees")),
        "description": _clip(_pick(s, "description"), 200),
    } for s in rows]
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "schedules": out})


async def _exec_calendar_create(ctx: Context, subject: str = "", beginTime: str = "",
                                endTime: str = "", attendees: str = "", location: str = "",
                                description: str = "", **kw) -> CallToolResult:
    if not (subject or "").strip() or not (beginTime or "").strip() or not (endTime or "").strip():
        return _err("subject / beginTime / endTime 都是必填项")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.calendar_create(
            subject.strip(), beginTime.strip(), endTime.strip(),
            attendees=_kw_list(attendees), location=(location or "").strip(),
            description=(description or "").strip()), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"created": True, "subject": subject, "begin": beginTime, "end": endTime,
                "result": data, "note": "以机器人身份创建；请把时间/参与人复述给用户核对"})


async def _exec_meeting_list(ctx: Context, beginTime: str = "", endTime: str = "",
                             limit: int = 20, **kw) -> CallToolResult:
    try:
        b, e = _range_forward(beginTime, endTime)
    except ValueError:
        return _err("时间格式必须是 YYYY-MM-DD HH:mm:ss（例如 2026-11-03 09:00:00）")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.meeting_list(b, e, limit=limit), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "meetings", "meeting_list", "list")
    out = [{
        "id": _pick(m, "meeting_id", "meetingid", "id"),
        "subject": _pick(m, "subject", "title"),
        "begin": _pick(m, "begin_time", "start_time"),
        "end": _pick(m, "end_time"),
        "location": _clip(_pick(m, "location"), 100),
        "attendeeCount": _pick(m, "attendee_count", "attendees_count"),
    } for m in rows]
    return _ok({"range": {"begin": b, "end": e}, "count": len(out), "meetings": out})


async def _exec_meeting_get(ctx: Context, meetingIds: str = "", **kw) -> CallToolResult:
    ids = _kw_list(meetingIds)
    if not ids:
        return _err("meetingIds 不能为空：请先调用 meeting_list 拿会议 id")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.meeting_get(ids), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "meetings", "meeting_list", "list")
    out = [{
        "id": _pick(m, "meeting_id", "meetingid", "id"),
        "subject": _pick(m, "subject", "title"),
        "begin": _pick(m, "begin_time", "start_time"),
        "end": _pick(m, "end_time"),
        "location": _clip(_pick(m, "location"), 100),
        "attendees": _names(_pick(m, "attendees")),
        "minutesUrl": _pick(m, "minutes_url", "smart_minutes_url"),
        "recordUrl": _pick(m, "record_url", "recording_url"),
    } for m in rows]
    return _ok({"count": len(out), "meetings": out})


async def _exec_meeting_create(ctx: Context, subject: str = "", beginTime: str = "",
                               endTime: str = "", attendees: str = "", location: str = "",
                               description: str = "", **kw) -> CallToolResult:
    if not (subject or "").strip() or not (beginTime or "").strip() or not (endTime or "").strip():
        return _err("subject / beginTime / endTime 都是必填项")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.meeting_create(
            subject.strip(), beginTime.strip(), endTime.strip(),
            attendees=_kw_list(attendees), location=(location or "").strip(),
            description=(description or "").strip()), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"created": True, "subject": subject, "begin": beginTime, "end": endTime,
                "result": data, "note": "以机器人身份预约；请把时间/参会人复述给用户核对"})


# ---------- 第三梯队：文档 / 表格 / 智能表格 / 智能文档 / 微盘 ----------

async def _exec_doc_search(ctx: Context, keywords: str = "", limit: int = 10,
                           docTypes: str = "", **kw) -> CallToolResult:
    if not _kw_list(keywords):
        return _err("keywords 不能为空：请给出要搜索的文档关键词")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.doc_search(keywords, limit=limit, doc_types=docTypes), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "docs", "doc_list", "list")
    out = [{
        "title": _pick(x, "doc_name", "title", "name"),
        "docType": _pick(x, "doc_type", "type"),
        "docId": _pick(x, "docid", "doc_id"),
        "url": _pick(x, "url", "doc_url"),
        "fragment": _clip(_pick(x, "fragment", "highlight", "summary"), 200),
    } for x in rows]
    return _ok({"count": len(out), "docs": out,
                "note": "读内容请把 docId/url 交给 sheet_info / smartsheet_info / smartpage_get"})


async def _exec_doc_create(ctx: Context, docName: str = "", docType: str = "doc",
                           content: str = "", **kw) -> CallToolResult:
    if not (docName or "").strip():
        return _err("docName 不能为空：请给出文档名称")
    dtype = (docType or "doc").strip().lower()
    if dtype not in ("doc", "sheet", "smartsheet", "smartpage", "ppt"):
        return _err("docType 只支持 doc / sheet / smartsheet / smartpage / ppt")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.doc_create(docName.strip(), dtype, content or ""), d, timeout=45)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"created": True, "docName": docName, "docType": dtype, "result": data})


async def _exec_doc_content(ctx: Context, docId: str = "", contentType: str = "",
                            **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.doc_content(docId.strip(), (contentType or "").strip()), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    # 正文可能上万字：截断但保留足够上下文（模型还要据此回答问题）
    text = _pick(data, "content", "text", "data") if isinstance(data, dict) else data
    return _ok({"docId": docId, "content": _clip(text, 4000), "raw": None if text else data})


async def _exec_doc_append(ctx: Context, docId: str = "", content: str = "", **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    if not (content or "").strip():
        return _err("content 不能为空：请给出要追加的文本")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.doc_append(docId.strip(), content), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"appended": True, "docId": docId, "chars": len(content), "result": data})


async def _exec_sheet_info(ctx: Context, docId: str = "", **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.sheet_info(docId.strip()), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"docId": docId, "info": data})


async def _exec_smartsheet_info(ctx: Context, docId: str = "", **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.smartsheet_info(docId.strip()), d)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"docId": docId, "info": data})


async def _exec_smartsheet_records(ctx: Context, docId: str = "", sheetId: str = "",
                                   limit: int = 20, **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.smartsheet_records(docId.strip(), sheetId.strip(), limit=limit),
                           d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "records", "record_list", "list")
    return _ok({"docId": docId, "count": len(rows), "records": rows[:100]})


async def _exec_smartpage_get(ctx: Context, docId: str = "", pageId: str = "",
                              **kw) -> CallToolResult:
    if not (docId or "").strip():
        return _err("docId 不能为空：请给出文档 ID 或链接")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.smartpage_get(docId.strip(), (pageId or "").strip()), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    return _ok({"docId": docId, "content": data})


async def _exec_disk_search(ctx: Context, keywords: str = "", limit: int = 10,
                            **kw) -> CallToolResult:
    if not _kw_list(keywords):
        return _err("keywords 不能为空：请给出要搜索的文件名关键词")
    try:
        _, d = await _profile(ctx)
        data = await _call(argv.disk_search(keywords, limit=limit), d, timeout=30)
    except (profiles.NotBound, runner.CliError, identity.IdentityError) as exc:
        return _err(str(exc))
    rows = _rows(data, "files", "file_list", "list")
    out = [{
        "name": _pick(f, "file_name", "name"),
        "type": _pick(f, "file_type", "type"),
        "size": _pick(f, "file_size", "size"),
        "path": _clip(_pick(f, "path", "file_path"), 200),
        "id": _pick(f, "file_id", "id"),
    } for f in rows]
    return _ok({"count": len(out), "files": out})


_EXEC = {
    # 一梯队（只读）
    "whoami": _exec_whoami,
    "contact_search": _exec_contact_search,
    "recent_group_sessions": _exec_recent_sessions,
    "session_messages": _exec_session_messages,
    "mail_search": _exec_mail_search,
    # 二梯队（写）
    "message_send": _exec_message_send,
    "mail_get": _exec_mail_get,
    "mail_send": _exec_mail_send,
    "todo_list": _exec_todo_list,
    "todo_get": _exec_todo_get,
    "todo_create": _exec_todo_create,
    "calendar_list": _exec_calendar_list,
    "calendar_create": _exec_calendar_create,
    "meeting_list": _exec_meeting_list,
    "meeting_get": _exec_meeting_get,
    "meeting_create": _exec_meeting_create,
    # 三梯队（文档 / 表格 / 微盘）
    "doc_search": _exec_doc_search,
    "doc_create": _exec_doc_create,
    "doc_content": _exec_doc_content,
    "doc_append": _exec_doc_append,
    "sheet_info": _exec_sheet_info,
    "smartsheet_info": _exec_smartsheet_info,
    "smartsheet_records": _exec_smartsheet_records,
    "smartpage_get": _exec_smartpage_get,
    "disk_search": _exec_disk_search,
}

# 第二处参数事实源：default=None ⇒ 必填。必须与 catalog 的 required 一致。
_PARAMS: dict[str, list[tuple[str, type, Any]]] = {
    "whoami": [],
    "contact_search": [("keywords", str, None), ("searchMode", str, "")],
    "recent_group_sessions": [("days", int, 7)],
    "session_messages": [("chat_id", str, None), ("days", int, 7), ("limit", int, 20)],
    "mail_search": [("keywords", str, ""), ("days", int, 7), ("limit", int, 10),
                    ("onlyUnread", bool, False)],
    "message_send": [("chat_id", str, None), ("text", str, None)],
    "mail_get": [("mailIds", str, None)],
    "mail_send": [("to", str, None), ("subject", str, None), ("content", str, None)],
    "todo_list": [("limit", int, 10), ("status", str, ""), ("keywords", str, "")],
    "todo_get": [("items", str, None)],
    "todo_create": [("title", str, None), ("description", str, ""),
                    ("followerIds", str, ""), ("deadline", str, "")],
    "calendar_list": [("beginTime", str, ""), ("endTime", str, "")],
    "calendar_create": [("subject", str, None), ("beginTime", str, None), ("endTime", str, None),
                        ("attendees", str, ""), ("location", str, ""), ("description", str, "")],
    "meeting_list": [("beginTime", str, ""), ("endTime", str, ""), ("limit", int, 20)],
    "meeting_get": [("meetingIds", str, None)],
    "meeting_create": [("subject", str, None), ("beginTime", str, None), ("endTime", str, None),
                       ("attendees", str, ""), ("location", str, ""), ("description", str, "")],
    "doc_search": [("keywords", str, None), ("limit", int, 10), ("docTypes", str, "")],
    "doc_create": [("docName", str, None), ("docType", str, "doc"), ("content", str, "")],
    "doc_content": [("docId", str, None), ("contentType", str, "")],
    "doc_append": [("docId", str, None), ("content", str, None)],
    "sheet_info": [("docId", str, None)],
    "smartsheet_info": [("docId", str, None)],
    "smartsheet_records": [("docId", str, None), ("sheetId", str, ""), ("limit", int, 20)],
    "smartpage_get": [("docId", str, None), ("pageId", str, "")],
    "disk_search": [("keywords", str, None), ("limit", int, 10)],
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
        # ★ 工具失败必须**进日志**：模型只会对用户说一句「参数错误」，
        #   而真实原因是 CLI 的原话（例如 `error: unexpected argument 'true' found`）。
        #   2026-10-31 那次事故就是没有这行 —— 只能靠猜，猜错了方向就跑到「模型不会用工具」上。
        res = await fn_impl(ctx, **kwargs)
        if getattr(res, "isError", False):
            text = ""
            try:
                text = res.content[0].text if res.content else ""
            except Exception:                                   # noqa: BLE001
                pass
            logger.warning("wecom_cli.%s 失败 args=%s err=%s",
                           tool_name, _mask(kwargs), (text or "")[:300])
        else:
            logger.debug("wecom_cli.%s ok args=%s", tool_name, _mask(kwargs))
        return res

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
    # 与 builtin.py 同一理由：不显式传，FastMCP 会装「只信 localhost」的 Host 白名单，
    # 生产里 Host: mcp-hub:8099 会被 421 挡掉（见 mcp_hub/transport.py）。
    mcp = FastMCP(SERVER_CODE, streamable_http_path="/", transport_security=security_settings())
    for tool in TOOLS:
        name = tool["name"]
        mcp.add_tool(
            _make_tool_fn(name, _PARAMS.get(name, [])),
            name=name,
            description=tool["description"],
            annotations=ToolAnnotations(read_only_hint=tool["read_only"]),
        )
    return mcp
