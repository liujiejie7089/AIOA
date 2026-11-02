"""「模糊的人」澄清：代码级预取候选 + 合成澄清卡（**连接器无关**）。

## 为什么需要这个模块

2026-11-02 用户实测：

    用户：帮我给同事发条消息说下午三点开会
    数字人：为了确保消息发送给正确的同事，我需要知道您具体想联系哪位同事。
            您能提供一下同事的姓名、部门或职位吗？

期望是「先查 → 把候选做成按钮让用户点」，实际只回了一句反问。
提示词已经写了「先查再 ask_user」，但**工具存在 ≠ 模型会用**：模型看到「没给姓名」
就直接认定「没法查」，于是把找人的活推回给用户。

所以这里走确定性路径（与 `form_hint` 同一套思路：代码判定，agent 只执行）：

  1. ``prepare``：识别到「同事」这类模糊指代时，**代码先查一次人源工具**，结果塞进 state；
  2. ``agent``：如果模型这一轮**一个工具都没调**（典型就是正文反问），
     代码用预取到的候选合成一次 ``ask_user`` 控制调用 ⇒ 走 clarify 节点 ``interrupt()``
     ⇒ 前端渲染真按钮。

## 为什么不是写死企业微信

用户的说法是「这个功能应该对所有连接器都适用」。所以人源按**工具清单**发现，不看连接器 code：

  · ``kind=contact``：工具短名命中 ``contact_search`` / ``search_contacts`` / ``user_search`` …
    —— 真通讯录，value 用 userid（企微就是这里）；
  · ``kind=mail``：命中 ``list_messages`` / ``search_messages``
    —— 邮件类没有通讯录，就用**最近邮件的发件人**聚合出可联系人，value 用邮箱地址（QQ 邮箱是这里）。

两者都没有 ⇒ 返回空、不合成卡片，退回模型的文字追问（宁可不弹，也不能凭空造人）。

## 边界

- 只在 HITL 开启、且工具清单里**确实有**上述人源工具时启用；
- 预取失败（未连/超时/无权限）一律吞掉、只记日志：不能因为查候选把整条 run 打挂；
- 候选为空时不合成调用（否则会弹一张空卡）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("aios.ai.entity_clarify")

# 人源工具的**短名**（连接器无关：工具全名是 mcp__<server>__<short>）
CONTACT_SHORT_NAMES = frozenset({
    "contact_search", "contacts_search", "search_contacts",
    "user_search", "search_users", "find_user", "lookup_user",
})
MAIL_LIST_SHORT_NAMES = frozenset({"list_messages", "list_mails", "list_emails"})
MAIL_SEARCH_SHORT_NAMES = frozenset({"search_messages", "search_mails"})
# 文件夹枚举（用来找「已发送」；没有这个工具的连接器就跳过那一路）
LIST_FOLDERS_SHORT_NAMES = frozenset({"list_folders", "list_mail_folders", "folders"})
# 「已发送」的取名各家不同：QQ=`Sent Messages`、Gmail=`[Gmail]/Sent Mail`、
# Outlook=`Sent Items`、中文邮箱=「已发送」。只按名字判，不写死任何一家的常量。
SENT_FOLDER_RE = re.compile(r"(^|[/\s])(sent(\s|-)?(mail|messages|items)?)([/\s]|$)|已发送|已寄出",
                            re.I)

# 模糊指代：出现这些词、又没给唯一标识时，大概率需要枚举候选。
# 刻意写得**窄**：只匹配「同事」这一类人称指代，不匹配「大家/所有人」（那是群发语义，
# 不该走单人澄清），避免把普通提问也拖进澄清轮。
ENTITY_HINT_RE = re.compile(r"(同事|同事的|那位同事|某位同事|那个人|某人)")

# 动作/渠道线索：单单出现「同事」不够 —— 「公司同事的报销流程是什么」也带「同事」，
# 但那是知识问答，弹一张「要发给哪一位同事」的卡就是纯打扰（实测这类问句很常见）。
# 所以必须同时出现**对着人做事**的动词或渠道词，才认为这是「要找一个人」。
ACTION_RE = re.compile(
    r"(发给|发条|发个|发一封|发给同事|发送|转发给|转告|告诉|通知|邀请|抄送|"
    r"安排|约一下|约个|拉个|拉进|建个|建一个|催一下|催催|跟进|回复|回个|"
    r"消息|私信|邮件|日程|会议|待办|提醒)"
)

# 模型「把找人的活推回给用户」的语言特征。只在**候选已查到**且**本轮零工具调用**时
# 用来确认「它确实是在反问/让用户挑人」，而不是已经给出答案（后者不该再插一张卡）。
#
# 2026-11-02 真机实测（DeepSeek）暴露了最容易漏的一类：模型把候选查出来之后，
# 用**正文编号列表**让用户选 ——
#     「请选择您要发送消息的同事：\n\n1. 阿修bot.（成都易构）\n2. 小亮…\n\n请选择后我将发送消息。」
# 它一个「哪位/姓名」都没说，于是被判成「已作答」，卡片没弹出来 —— 用户面对的仍是一堆纯文字。
# 所以「请选择 / 选一个 / 哪一位」这类**把选择权交回用户**的措辞必须算数。
PERSON_ASK_RE = re.compile(
    r"(哪位|哪一位|哪一个|哪个人|发给谁|告诉谁|通知谁|收件人|发件人|姓名|工号|"
    r"具体是谁|是谁|请选择|请选|选一个|选择一个|选哪位)"
)

# 合成调用时用的固定 id：与 form_hint 同样写死，便于日志与判据对齐
SYNTH_CALL_ID = "call_entity_clarify_1"

MAX_OPTIONS = 10

# `"张三" <zhang@x.com>` / `zhang@x.com` 两种 From 头形态
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _tool_name(tool: dict) -> str:
    return ((tool.get("function") or {}).get("name") or tool.get("name") or "")


def _short(name: str) -> str:
    return name.split("__")[-1] if name else ""


def needs_entity_clarify(text: str | None) -> bool:
    """该用户消息是否属于「要对着某位同事做事、但没给唯一标识」。

    两个条件**都要**满足（少一个就会误伤）：
      · 人称指代（`同事` 等）—— 说明对象没被唯一确定；
      · 动作/渠道词（`发给` / `消息` / `邮件` / `日程` …）—— 说明真的要做动作。
    「公司同事的报销流程是什么」只满足前者 ⇒ 不预取、不弹卡，走正常知识问答。
    """
    t = text or ""
    return bool(ENTITY_HINT_RE.search(t)) and bool(ACTION_RE.search(t))


def looks_like_person_question(text: str | None) -> bool:
    """模型的这句回复是不是在「反问人名」（而不是已经给出了答案）。"""
    return bool(PERSON_ASK_RE.search(text or ""))


# 群发语义：这类诉求**不该**收敛成「选一个人」。「给同事群发个通知」是发给一群人，
# 弹一张「要发给哪一位同事」的卡就是答错题。
BROADCAST_RE = re.compile(
    r"(群发|所有人|所有同事|全员|全体|大家|群里|群聊|各部门|全部同事|"
    r"每个同事|每位同事|都发|一并通知)")


def names_in_text(members: list[dict] | None, text: str | None) -> bool:
    """用户这句话里是否已经点名了某个候选（说明本体已被唯一确定，不该再澄清）。

    「给同事刘洋发条消息」里出现了候选「刘洋」⇒ 用户其实已经指定了人，
    只是顺带说了「同事」这个词。这时弹「要发给哪一位」是纯打扰。
    """
    t = text or ""
    for m in members or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if len(name) >= 2 and name in t:
            return True
    return False


def can_short_circuit(members: list[dict] | None, text: str | None) -> bool:
    """能不能**跳过模型这一轮**、直接弹澄清卡。

    2026-11-02 真机实测：模型拿到候选后不肯调 ask_user，而是把名单写进正文
    （`[阿修bot.](wobVcoRg…)`，userid 还成了链接），代码再补一张卡 ⇒ 用户同时看到
    一段带机器值的废话和一张按钮卡。提示词挡不住这种写法，只能在源头上不让它写：
    候选已就绪、用户没点名、也不是群发 ⇒ 这一轮本来就不该由模型开口。
    """
    if not build_options(members):
        return False
    if BROADCAST_RE.search(text or ""):
        return False
    return not names_in_text(members, text)



def find_people_source(tools: list[dict] | None) -> dict[str, str] | None:
    """从工具清单里发现人源。返回 ``{"kind","tool"}``；没有则 None。

    分两趟扫，保证**优先级与工具顺序无关**（否则连接器只要把 search 排在 list 前面就会挑错）：
      1. 通讯录类（``CONTACT_SHORT_NAMES``）—— 最强，能枚举「全公司可联系人」；
      2. 邮件**列表**类（``MAIL_LIST_SHORT_NAMES``）—— 退而求其次，枚举「最近邮件的发件人」。
    邮件**搜索**类（``MAIL_SEARCH_SHORT_NAMES``）不参与枚举：它的 ``query`` 是必填，
    而这里恰恰是「不知道该搜什么」的场景，拿它枚举只会返回参数校验错误。
    """
    mail: dict[str, str] | None = None
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        name = _tool_name(t)
        if not name.startswith("mcp__"):
            continue
        short = _short(name)
        if short in CONTACT_SHORT_NAMES:
            return {"kind": "contact", "tool": name}
        if mail is None and short in MAIL_LIST_SHORT_NAMES:
            mail = {"kind": "mail", "tool": name}
    return mail


def has_contact_tool(tools: list[dict] | None) -> bool:
    """工具清单里是否有人源（保留旧名，供既有调用点使用）。"""
    return find_people_source(tools) is not None


def _parts(member: dict) -> tuple[str, str]:
    """拆出 (显示名, 区分项)。区分项优先部门/职位，其次邮箱，最后群名/出处。

    拿不到部门/职位时必须退化成**别的能区分的信息** —— 这一步不能省：
    通讯录走「最近群里说过话的人」这条路时只有群名，邮件只有邮箱地址，
    若只显示姓名，两个「刘洋」并列会让用户没法选（等于没给候选）。
    """
    name = str(member.get("name") or "").strip()
    dept = str(member.get("departments") or member.get("department") or "").strip()
    pos = str(member.get("position") or member.get("title") or "").strip()
    sub = " / ".join(x for x in (dept, pos) if x)
    if not sub:
        sub = (str(member.get("email") or "").strip()
               or (f"来自{str(member.get('from')).strip()}" if member.get("from") else ""))
    if not name:
        return sub, ""          # 只有邮箱/出处时，直接拿它当显示名
    return name, sub


def _label(member: dict, drop_sub: bool = False) -> str:
    """按钮文案：`姓名（部门 / 职位）`；缺哪段就省哪段，不输出「（）」。"""
    name, sub = _parts(member)
    return f"{name}（{sub}）" if (name and sub and not drop_sub) else name


def build_options(members: list[dict] | None, limit: int = MAX_OPTIONS) -> list[dict[str, str]]:
    """候选 → 澄清卡选项（value 是机器值：userid 或邮箱；label 是人看的）。

    **只在需要区分时才带括号**：
      · 名字唯一 ⇒ 只显示姓名（10 个不重名的人各带一串邮箱，等于把按钮变成地址簿，
        每行还被挤成两行）；
      · 有重名 ⇒ 重名的那几个都带上区分项（部门/职位/邮箱/出处）；
      · 只有一个候选 ⇒ 保留区分项（这时它是信息，不是噪音）。
    """
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for m in members or []:
        if not isinstance(m, dict):
            continue
        value = str(m.get("userid") or m.get("email") or "").strip()
        name, sub = _parts(m)
        if not name or not value or value in seen:
            continue
        seen.add(value)
        rows.append((name, sub, value))
        if len(rows) >= limit:
            break

    counts: dict[str, int] = {}
    for n, _, _ in rows:
        counts[n] = counts.get(n, 0) + 1
    single = len(rows) == 1
    return [{"value": v,
             "label": f"{n}（{s}）" if (s and (single or counts[n] > 1)) else n}
            for n, s, v in rows]


def build_question() -> str:
    return "要发给哪一位同事？"


# 「选完人之后还差一段内容」——按动作词判，缺什么就在同一张卡上要什么。
# 这是把「选人 → 再问一句内容」的两轮压成一轮的关键：文本框跟着选项一起出现，
# 用户在**同一个确认动作**里把人和内容交齐（见 ask_user 的 needs_text）。
_CONTENT_HINTS: tuple[tuple[re.Pattern, tuple[str, str]], ...] = (
    (re.compile(r"(邮件|mail)", re.I), ("邮件内容", "例如：附件已更新，请查收")),
    (re.compile(r"(日程|会议|开会|约个|约一下|约.{0,6}(?:会|时间|见面)|安排|碰头|排期)"),
     ("时间与主题", "例如：明天下午三点，项目评审")),
    (re.compile(r"(待办|提醒|催一下|催催|跟进)"), ("待办标题", "例如：周五前提交周报")),
    (re.compile(r"(消息|私信|转告|告诉|通知|回复|回个)"), ("要发送的内容", "例如：下午三点开会")),
)


def content_hint(text: str | None) -> tuple[str, str] | None:
    """这句话对应的动作还需要用户补什么内容；不需要补就返回 None。

    只认「动作类型」，不猜内容本身 —— 猜内容就是替用户编消息，比多问一句更糟。

    **按最先出现的动作词判定**（不是按表里顺序）：一句话常同时提到两件事，
    例如「发条消息说下午三点开会」—— 消息在前、开会只是内容的一部分，
    要的是「要发送的内容」；固定顺序会让它被后半句误判成「约会议」。
    """
    t = text or ""
    best: tuple[int, tuple[str, str]] | None = None
    for pat, hint in _CONTENT_HINTS:
        m = pat.search(t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), hint)
    return best[1] if best else None


def with_content_hint(options: list[dict], text: str | None) -> list[dict]:
    """给选项挂上「选中后还要补一段内容」的声明（有内容缺口时）。

    `build_clarify_call`（代码合成）与 `build_block`（模型照抄）都走这里，
    保证两条路径给出的 options 是**同一份形状** —— 否则模型自己调 ask_user 时
    不会标 needs_text，用户选完人又被追问一轮内容（正是本次要修的多轮往返）。
    """
    hint = content_hint(text)
    if not hint:
        return options
    label, placeholder = hint
    return [dict(o, needs_text=True, text_label=label, text_placeholder=placeholder)
            for o in options]


def build_clarify_call(members: list[dict] | None,
                       text: str | None = None) -> dict[str, Any] | None:
    """合成一条 ``ask_user`` 调用（状态里的**归一化**形状：arguments 是 dict）。

    候选为空或全都缺可用标识（userid/邮箱）时返回 None —— 宁可不弹卡，也不弹空卡。

    ``text`` 是用户原话：如果这次动作还缺一段内容（发消息要内容、约会议要时间…），
    就把每个选项标成 ``needs_text``，输入框**跟着选项动态出现**、且必须填写才能确认 ——
    用户在这一次交互里把「选谁 + 说什么」一起交掉，不会选完再被问一轮。
    """
    options = build_options(members)
    if not options:
        return None
    options = with_content_hint(options, text)
    return {"id": SYNTH_CALL_ID, "name": "ask_user",
            "arguments": {"question": build_question(), "options": options}}


def build_block(members: list[dict] | None, source: str = "contact",
                text: str | None = None) -> str:
    """把预取到的候选写进系统提示，让模型知道「已经查过了、照抄就能调」。

    这里**必须把 `value` 一起给出**（不是只给姓名）。2026-11-02 真机实测：只给姓名时，
    模型不知道 options 里该传什么值，于是退回「正文编号列表让用户选」——
    正文里还把 userid 渲染成 `[阿修bot.](wobVcoRg…)` 这种链接，既重复又泄露机器值。
    给成可直接照抄的 JSON 之后，它调 ask_user 就没有任何犹豫的理由。

    ``text`` 是用户原话：这次动作若还缺一段内容（发消息要内容、约会议要时间…），
    照抄的 JSON 里就已经带好 ``needs_text``，并额外叮嘱「不要再追问内容」——
    用户会在同一次交互里把「选谁 + 说什么」一起交掉。
    """
    options = with_content_hint(build_options(members), text)
    if not options:
        return ""
    lines = "\n".join(f"- {o['label']}" for o in options)
    payload = json.dumps(options, ensure_ascii=False)
    gaps = content_hint(text)
    origin = ("「最近 7 天群里说过话的人」，不等于全公司通讯录"
              if source == "contact"
              else "「最近的邮件收发件人」，不等于全公司通讯录")
    extra = ""
    if gaps:
        extra = (
            "\n注意：这次动作还缺一段内容（" + gaps[0] + "）。上面 JSON 里每项都带了 "
            "`needs_text: true` —— **照抄**，界面上会跟着选项弹出输入框，"
            "用户填完一次提交。**不要**在用户选完后再追问「要发送什么内容」。"
        )
    return (
        "\n\n【已为你查好候选】用户说的是「同事」这类没有唯一标识的指向，"
        f"系统已经查过一次，得到以下候选（真实数据，来自{origin}）：\n"
        f"{lines}\n"
        "处理方式（照做，别再自己猜）：调 **ask_user**，`question` 用"
        "「要发给哪一位同事？」，`options` **逐字照抄**下面这段 JSON：\n"
        f"{payload}\n"
        "铁律：**不要把名单写进正文、也不要把这些 value（userid/邮箱）显示给用户** —— "
        "用户只需要点按钮；等用户选完（回填里已含他补的内容），直接用选中的 value 执行原任务。"
        f"{extra}"
    )


def _split_addr(raw: str) -> tuple[str, str]:
    """`"张三" <zhang@x.com>` → ("张三", "zhang@x.com")；裸地址则 name 留空。

    name 留空（而不是取 @ 前面那段）是刻意的：`li@x.com` 的「li」既不是真名、
    也没法用来区分人，硬凑出来只会得到「li（li@x.com）」这种半截文案。
    留空后 `_label` 会退化成只显示地址，反而干净、也足够区分。
    """
    text = str(raw or "").strip()
    m = _EMAIL_RE.search(text)
    if not m:
        return "", ""
    email = m.group(0)
    name = re.sub(r"<[^>]*>", "", text).strip().strip('"').strip()
    if name == email or "@" in name:
        name = ""
    return name, email


def _parse_json(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except Exception:  # noqa: BLE001 —— 解析失败就当没候选，不要让 run 挂
            return None
    return data


def _rows_of(payload: Any, kind: str) -> list:
    if isinstance(payload, dict):
        keys = ("messages", "mails", "items", "list", "data") if kind == "mail" \
            else ("members", "users", "items", "list", "data")
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        return []
    return payload if isinstance(payload, list) else []


def parse_members(data: Any, kind: str = "contact") -> list[dict]:
    """解析人源返回：通讯录是 ``members``，邮件是「消息列表里的 from」。

    ⚠️ 两类的**列表键不同**：通讯录回 ``members``/``users``，邮件回 ``messages``/``mails``
    （`qq_mail.list_messages` 就是 ``{"messages": [...]}``）。只认 ``members`` 的话
    邮件这条链路会永远解析出 0 个候选 —— 表现为「QQ 邮箱也弹不出按钮」。
    """
    rows = _rows_of(_parse_json(data), kind)
    if kind == "mail":
        out: list[dict] = []
        seen: set[str] = set()
        for r in rows:
            if not isinstance(r, dict):
                continue
            name, email = _split_addr(r.get("from") or r.get("sender") or "")
            if email and email not in seen:
                seen.add(email)
                out.append({"name": name, "email": email})
        return out
    return [m for m in rows if isinstance(m, dict)]


def parse_recipients(data: Any) -> list[dict]:
    """从「已发送」邮件里解析收件人（`to` 可含多个、逗号分隔）。

    为什么要看已发送：收件箱里通常是**别人发给我**的（GitHub 通知、系统邮件），
    聚合出来的「可联系人」全是 noreply；“给同事发邮件”真正该给的候选是
    **我最近写过的人**，那只能从已发送里取。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for r in _rows_of(_parse_json(data), "mail"):
        if not isinstance(r, dict):
            continue
        raw = str(r.get("to") or "")
        for part in re.split(r",(?![^<]*>)", raw):
            name, email = _split_addr(part)
            if email and email not in seen:
                seen.add(email)
                out.append({"name": name, "email": email})
    return out


async def _invoke(tool_client, tool: str, args: dict) -> tuple[bool, Any]:
    """调一次人源工具；任何异常都收敛成 (False, None)。"""
    try:
        outcome = await tool_client.invoke(tool, args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("entity prefetch failed (ignored): %s", exc)
        return False, None
    if not getattr(outcome, "ok", False):
        logger.info("entity prefetch not ok (%s): %s", tool,
                    str(getattr(outcome, "error", ""))[:200])
        return False, None
    return True, getattr(outcome, "data", None)


def _find_tool(tools: list[dict] | None, shorts: frozenset[str]) -> str:
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        name = _tool_name(t)
        if name.startswith("mcp__") and _short(name) in shorts:
            return name
    return ""


async def _sent_folder(tool_client, tools: list[dict] | None) -> str:
    """找「已发送」文件夹名。

    **不写死 `Sent Messages`**（那是 QQ 的取名）：Gmail 叫 `[Gmail]/Sent Mail`、
    Outlook 叫 `Sent Items`、企业邮箱可能是「已发送」。所以先问 `list_folders`，
    再按名字判 —— 判不出来就返回空、跳过这一路（少几个候选，不会出错）。
    """
    folder_tool = _find_tool(tools, LIST_FOLDERS_SHORT_NAMES)
    if not folder_tool:
        return ""
    ok, data = await _invoke(tool_client, folder_tool, {})
    if not ok:
        return ""
    payload = _parse_json(data)
    rows = payload if isinstance(payload, list) else _rows_of(payload, "mail")
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "")
        flags = " ".join(str(f) for f in (r.get("flags") or []))
        if "\\NoSelect" in flags:
            continue
        if name and SENT_FOLDER_RE.search(name):
            return name
    return ""


async def prefetch(tool_client, tools: list[dict] | None,
                   limit: int = MAX_OPTIONS) -> tuple[list[dict], str]:
    """查一次人源，返回 ``(候选, kind)``。任何异常都不上抛。

    通讯录：一次调用就够（`contact_search` 空关键词 ⇒ hub 用最近群里说过话的人兜底）。
    邮件：要两路合起来才像样 ——
      · **已发送的收件人**（我最近写过谁，这是「给同事发邮件」最该给的候选）；
      · **收件箱的发件人**（谁最近写过我，补上往来人）。
    只取收件箱的话，真实邮箱里往往全是 GitHub/系统通知，聚合出来一个能用的联系人都没有。
    """
    src = find_people_source(tools)
    if not src:
        return [], ""
    kind, tool = src["kind"], src["tool"]

    if kind == "contact":
        ok, data = await _invoke(tool_client, tool, {})
        rows = parse_members(data, "contact") if ok else []
        logger.info("entity prefetch via %s got %d candidates", tool, len(rows))
        return rows[:limit], kind

    members: list[dict] = []
    folder = await _sent_folder(tool_client, tools)
    if folder:
        ok, data = await _invoke(tool_client, tool, {"limit": 20, "folder": folder})
        if ok:
            members.extend(parse_recipients(data))
    ok, data = await _invoke(tool_client, tool, {"limit": 30})
    if ok:
        members.extend(parse_members(data, "mail"))

    deduped: list[dict] = []
    seen: set[str] = set()
    for m in members:
        key = str(m.get("email") or "").strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(m)
    logger.info("entity prefetch via %s (sent=%r) got %d candidates",
                tool, folder, len(deduped))
    return deduped[:limit], kind
