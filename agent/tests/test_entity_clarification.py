# -*- coding: utf-8 -*-
"""模糊实体澄清：ask_user 轮「只澄清」的确定性闸 + 选项上限 10。

## 为什么要这套断言（2026-11-02 产品口径）

用户说「查我同事考勤」时，模型有两种坏习惯：
  ① 直接猜一个人（常常猜成用户自己）就把业务查询跑了；
  ② 只反问一句「是哪位同事？」，用户只能手打全名。

产品定的流程是：`contact_search` 枚举候选 → `ask_user` 把候选渲染成按钮 →
用户点了之后才用选中的 userid 执行原查询。其中**「本轮只澄清」必须是确定性闸**：
提示词挡不住模型在同一轮里先跑一遍查询，而那一跑会带着猜出来的 userid，
用户选完之后澄清卡下面就已经躺着一份「看起来很像对的」错误结果。

## 判据

  E1  ask_user 轮夹带的业务调用：pending_calls 清空、不执行
  E2  被丢弃的调用**必须补 tool 消息**（否则 assistant.tool_calls 悬空 ⇒ 下次请求 400）
  E3  被丢弃的调用要在 tool_calls_log 里留 SKIPPED 痕迹（审计不能「凭空少一次调用」）
  E4  request_confirm / request_form 链**不受影响**（余量照旧交回 tools，零回归）
  E5  ask_user 选项上限是 10（不是 6）：否则第 7~10 个候选被静默丢掉，用户选不到人
"""
from __future__ import annotations

import asyncio
import json

import pytest

from aios_ai.graph import nodes
from aios_ai.tools import ask_user as ask_user_tool


def _calls(*names: str) -> list[dict]:
    return [{"id": f"c{i}", "name": n, "arguments": {"q": "x"}} for i, n in enumerate(names)]


def _state(*names: str) -> dict:
    calls = _calls(*names)
    return {
        "req": {"run_id": "r_entity"},
        "messages": [{"role": "assistant", "content": "",
                      "tool_calls": [{"id": c["id"], "type": "function",
                                      "function": {"name": c["name"], "arguments": "{}"}}
                                     for c in calls]}],
        "pending_calls": calls,
    }


def _run(state: dict, answer="wobVcoRgAAwZdjMSCNmVIBRHqFTQwuAQ", monkeypatch=None) -> dict:
    monkeypatch.setattr(nodes, "interrupt", lambda spec: answer)
    return asyncio.run(nodes.clarify(state))


# ---------------------------------------------------------------- E1~E3 只澄清

def test_ask_user_drops_business_calls_in_same_turn(monkeypatch) -> None:
    """模型「一边问是哪位同事、一边先查了考勤」⇒ 那次查询必须被整轮丢弃。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    assert out["pending_calls"] == [], "ask_user 轮不允许再把业务调用交给 tools 执行"
    # 回填已归一成 {value,label,text}（2026-11-02 一次交互交齐）：标量时代只存过一个裸值，
    # 模型因此拿不到「用户还补了什么」，只能再问一句 ⇒ 多轮往返。断言按新契约收严。
    ans = out["clarifications"][0]["answer"]
    assert ans["value"].startswith("wob"), "用户的选择要落进 clarifications"
    assert set(ans) >= {"value", "text"}, "回填形状必须是归一后的对象"
    assert isinstance(ans["text"], str)


def test_dropped_call_gets_a_tool_message(monkeypatch) -> None:
    """丢弃必须补 tool 回包：assistant.tool_calls 有两个 id，就得有两条 tool 消息。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    ids = [m.get("tool_call_id") for m in tool_msgs]
    assert ids == ["c0", "c1"], f"控制调用 + 被丢弃调用各一条，实际 {ids}"
    skipped = [m for m in tool_msgs if "SKIPPED_PENDING_CLARIFICATION" in (m.get("content") or "")]
    assert len(skipped) == 1 and skipped[0]["tool_call_id"] == "c1"
    assert "未执行" in skipped[0]["content"], "要让模型看懂为什么没结果"


def test_dropped_call_is_audited(monkeypatch) -> None:
    """审计口径：被丢弃也要留痕，否则事后无法解释「这一轮为什么没查」。"""
    st = _state("ask_user", "mcp__wecom_cli__attendance_list")
    out = _run(st, monkeypatch=monkeypatch)
    log = out["tool_calls_log"]
    assert len(log) == 1 and log[0]["status"] == "SKIPPED"
    assert log[0]["name"] == "mcp__wecom_cli__attendance_list"


def test_ask_user_alone_keeps_behaviour(monkeypatch) -> None:
    """只有 ask_user 时行为不变：仍是一条 tool 消息 + 不产生 SKIPPED 日志。"""
    out = _run(_state("ask_user"), monkeypatch=monkeypatch)
    assert out["pending_calls"] == []
    assert len([m for m in out["messages"] if m.get("role") == "tool"]) == 1
    assert not out.get("tool_calls_log")


# ---------------------------------------------------------------- E4 其它链零回归

def test_confirm_chain_still_forwards_business_calls(monkeypatch) -> None:
    """确认链的余量照旧交回 tools —— 这条是回归哨兵，别把闸门做成全局的。"""
    out = _run(_state("request_confirm", "mcp__qq_mail__send_draft"), monkeypatch=monkeypatch)
    assert [c["name"] for c in out["pending_calls"]] == ["mcp__qq_mail__send_draft"]


def test_form_chain_still_forwards_business_calls(monkeypatch) -> None:
    st = _state("request_form", "mcp__qq_mail__send_draft")
    # request_form 需要 form_code，否则 build_form_request 归一化失败、整轮不暂停
    st["pending_calls"][0]["arguments"] = {"form_code": "leave", "reason": "测试"}
    out = _run(st, monkeypatch=monkeypatch)
    assert [c["name"] for c in out["pending_calls"]] == ["mcp__qq_mail__send_draft"]


# ---------------------------------------------------------------- E5 选项上限

def test_option_cap_is_ten_not_six() -> None:
    """候选澄清要能列到 10 个：6 的时代第 7 个联系人会被静默吃掉。"""
    assert ask_user_tool.MAX_OPTIONS == 10
    opts = [{"value": f"uid{i}", "label": f"张三({i})"} for i in range(14)]
    out = ask_user_tool._as_options(opts)
    assert len(out) == 10, f"应截到 10，实际 {len(out)}"
    assert out[-1]["value"] == "uid9"


def test_clarification_payload_shape_unchanged() -> None:
    """契约形状不动：前端只认 question + suggested_options。"""
    p = ask_user_tool.build_clarification(
        {"question": "是哪位同事？",
         "options": [{"value": "u1", "label": "张三（研发部/工程师）"},
                     {"value": "u2", "label": "张三（销售部/经理）"}]})
    assert p["question"] == "是哪位同事？"
    assert [o["value"] for o in p["suggested_options"]] == ["u1", "u2"]
    assert p["suggested_options"][0]["label"] == "张三（研发部/工程师）"


# ---------------------------------------------------------------- E6 提示词纪律

def _system_blob() -> str:
    from aios_ai.contracts import RunRequest, UserContext
    from aios_ai.prompt.builder import build_messages

    req = RunRequest(run_id="r_entity", conversation_id=1, text="查我同事考勤", user_token="t",
                     user_context=UserContext(user_id=2, tenant_id=1,
                                              username="zhangsan", roles=["ROLE_USER"]))
    return "\n".join(m.get("content") or "" for m in build_messages(req)
                     if m.get("role") == "system")


def test_prompt_has_entity_clarify_rule(monkeypatch) -> None:
    """HITL 开着才写这条规则（关掉时 ask_user 根本不在工具表里，写了就是骗模型）。"""
    from aios_ai.prompt import builder as prompt_builder

    monkeypatch.setattr(prompt_builder.settings, "agent_hitl", True, raising=False)
    blob = _system_blob()
    assert "模糊的人先澄清" in blob
    assert "searchMode=list" in blob, "不传 list 只回热度前 3，同名同事会被吃掉"
    assert "这一轮只澄清" in blob
    # 四个边界都要写死，否则模型只会「反问一句」而不是枚举候选
    for kw in ("hasMore=true", "不许编人", "就此终止"):
        assert kw in blob, f"缺边界：{kw}"


def test_prompt_forbids_text_only_followup(monkeypatch) -> None:
    """2026-11-02 用户实测：说「帮我给同事发条消息说下午三点开会」，数字人只回了一句
    「请提供一下同事的姓名、部门或职位」—— 用户什么按钮都没得到。

    这条退化必须被提示词挡死，并且要给出「没有姓名片段时」的替代路径：
    ask_user + options=[] ⇒ 界面渲染输入框（而不是让用户在正文里打字）。
    """
    from aios_ai.prompt import builder as prompt_builder

    monkeypatch.setattr(prompt_builder.settings, "agent_hitl", True, raising=False)
    blob = _system_blob()
    assert "严禁" in blob and "推回给用户" in blob, "要明确禁止「只反问一句」"
    assert "options 传空数组" in blob, "没片段时要走输入框卡片，不能硬搜也不能正文反问"
    assert "请输入姓名或工号" in blob, "输入框的提问文案要写死，模型才知道怎么问"
    assert "哪怕只有 1 个也出按钮确认" in blob, "有候选就必须列，别拿「留空」当省事"
    assert "降级请用户直接给姓名或工号" not in blob, "旧措辞（正文索要姓名）必须清掉"


def test_clarification_allows_empty_options() -> None:
    """ask_user 的 options 不再是必填：没有任何候选时留空，H5 会渲染输入框。"""
    schema = ask_user_tool.ASK_USER_TOOL["function"]["parameters"]
    assert schema["required"] == ["question"]
    desc = schema["properties"]["options"]["description"]
    assert "留空" in desc and "输入框" in desc
    # 空数组要能穿过归一化，不被当成「非法选项」丢掉
    p = ask_user_tool.build_clarification({"question": "要发给哪位同事？", "options": []})
    assert p["suggested_options"] == []
    assert p["question"] == "要发给哪位同事？"


def test_prompt_omits_rule_when_hitl_off(monkeypatch) -> None:
    from aios_ai.prompt import builder as prompt_builder

    monkeypatch.setattr(prompt_builder.settings, "agent_hitl", False, raising=False)
    assert "模糊的人先澄清" not in _system_blob()


# ---------------------------------------------------------------- E7 触发口径
#
# 用户实测的失败点不是「提示词没写」，而是**模型没去查**：它看到「没给姓名」就认定没法查。
# 所以改成代码级确定性路径（tools/entity_clarify）：prepare 先预取候选，agent 在「零工具调用
# 且确实在反问人名」时用候选合成 ask_user。下面这组断言盯的就是这条链的两个端点。

def test_needs_entity_clarify_requires_person_and_action() -> None:
    """只带「同事」不算：必须是「对着某位同事做事」，否则知识问答也会被弹卡。"""
    ec = _ec()
    assert ec.needs_entity_clarify("帮我给同事发条消息说下午三点开会") is True
    assert ec.needs_entity_clarify("给同事约个会议") is True
    assert ec.needs_entity_clarify("同事的报销流程是什么") is False, "知识问答不该弹选人卡"
    assert ec.needs_entity_clarify("公司差旅标准") is False
    assert ec.needs_entity_clarify("") is False


def test_looks_like_person_question_only_matches_askbacks() -> None:
    """只有「反问人名」的回复才值得再补一张卡；已给出答案的不打扰。"""
    ec = _ec()
    assert ec.looks_like_person_question(
        "为了确保消息发送给正确的同事，我需要知道您具体要发给哪位同事。您能提供一下姓名吗？")
    assert ec.looks_like_person_question("请问收件人是谁？")
    assert not ec.looks_like_person_question("已把下午三点的会议写进日程。")


def test_text_numbered_list_is_still_a_punt() -> None:
    """真机实测（DeepSeek）：模型查完候选后，用**正文编号列表**让用户选。

        「请选择您要发送消息的同事：1. 阿修bot.（成都易构） 2. 小亮…请选择后我将发送消息。」

    这句里一个「哪位/姓名」都没有 —— 按旧判据会被当成「已作答」，卡片不弹，
    用户面对的仍是一堆要自己打字的纯文本。它必须被判成「在让用户挑人」。
    """
    ec = _ec()
    assert ec.looks_like_person_question(
        "请选择您要发送消息的同事：\n\n1. 阿修bot.（成都易构）\n2. 小亮（成都易构）\n\n请选择后我将发送消息。")
    assert ec.looks_like_person_question("选一个吧：阿修bot. / 小亮")
    # 反向：真的做完了的句子不该再插卡
    assert not ec.looks_like_person_question("已发送给刘洋：下午三点开会。")


# ---------------------------------------------------------------- E8 连接器无关

def _ec():
    from aios_ai.tools import entity_clarify

    return entity_clarify


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_people_source_is_connector_agnostic() -> None:
    """人源按**工具短名**发现，不看连接器 code —— 企微与 QQ 邮箱走同一条路。"""
    ec = _ec()
    assert ec.find_people_source([_tool("mcp__wecom_cli__contact_search")]) == {
        "kind": "contact", "tool": "mcp__wecom_cli__contact_search"}
    assert ec.find_people_source([_tool("mcp__qq_mail__list_messages")]) == {
        "kind": "mail", "tool": "mcp__qq_mail__list_messages"}
    # 通讯录优先（与工具顺序无关）
    assert ec.find_people_source([_tool("mcp__qq_mail__list_messages"),
                                  _tool("mcp__wecom_cli__contact_search")])["kind"] == "contact"
    # 没有任何人源 ⇒ None（不许凭空造人）  ·  只有 search_messages 也不算：
    # 它的 query 必填，而这里恰恰是「不知道该搜什么」，拿它枚举只会返回参数校验错误。
    assert ec.find_people_source([_tool("mcp__qq_mail__search_messages")]) is None
    assert ec.find_people_source([_tool("kb_search")]) is None
    assert ec.find_people_source([]) is None


def test_contact_and_mail_share_one_pipeline() -> None:
    """两端产出的澄清卡形状完全一致：value 是机器值（userid / 邮箱），label 是人看的。"""
    ec = _ec()
    contact = ec.parse_members({"members": [
        {"name": "刘洋", "userid": "wob1", "departments": "研发部", "position": "工程师"}]}, "contact")
    assert ec.build_options(contact) == [{"value": "wob1", "label": "刘洋（研发部 / 工程师）"}]

    mail = ec.parse_members({"messages": [
        {"from": '"张三" <zhang@x.com>', "subject": "a"},
        {"from": "li@x.com", "subject": "b"}]}, "mail")
    assert [m["email"] for m in mail] == ["zhang@x.com", "li@x.com"]
    # 名字唯一 ⇒ 不带邮箱（带了只是把按钮变地址簿）；裸地址没有姓名可显示 ⇒ 用地址本身
    assert ec.build_options(mail) == [
        {"value": "zhang@x.com", "label": "张三"},
        {"value": "li@x.com", "label": "li@x.com"}]


def test_mail_senders_are_deduped_by_address() -> None:
    """同一个人发多封只出现一次，否则按钮列表会被同地址刷满。"""
    ec = _ec()
    rows = ec.parse_members({"messages": [
        {"from": "a@x.com"}, {"from": '"A" <a@x.com>'}, {"from": "b@x.com"}]}, "mail")
    assert [r["email"] for r in rows] == ["a@x.com", "b@x.com"]


def test_label_falls_back_to_distinguisher() -> None:
    """没有部门/职位时不能只显示姓名：两个「刘洋」并列等于没给候选。"""
    ec = _ec()
    assert ec.build_options([{"name": "刘洋", "userid": "u1", "from": "成都易构"}]) == [
        {"value": "u1", "label": "刘洋（来自成都易构）"}]
    # 缺 name 时直接用邮箱，不输出空 label
    assert ec.build_options([{"email": "z@x.com"}]) == [{"value": "z@x.com", "label": "z@x.com"}]


def test_shared_distinguisher_is_dropped() -> None:
    """只在**需要区分**时才带括号：同名才加，名字唯一就省。

    10 个不重名的人各带一串邮箱，等于把按钮变成地址簿，每行还被挤成两行；
    但「刘洋（研发部）/ 刘洋（销售部）」这种真区分必须留着，否则同名的人分不开。
    """
    ec = _ec()
    same = [{"name": "刘洋", "userid": "u1", "from": "成都易构"},
            {"name": "小亮", "userid": "u2", "from": "成都易构"}]
    assert [o["label"] for o in ec.build_options(same)] == ["刘洋", "小亮"]

    diff = [{"name": "刘洋", "userid": "u1", "departments": "研发部", "position": "工程师"},
            {"name": "刘洋", "userid": "u2", "departments": "销售部", "position": "经理"}]
    assert [o["label"] for o in ec.build_options(diff)] == [
        "刘洋（研发部 / 工程师）", "刘洋（销售部 / 经理）"]

    # 同名 + 不同邮箱：重名的那几个要带上邮箱才能分开
    dup_mail = [{"name": "张三", "email": "z1@x.com"}, {"name": "张三", "email": "z2@x.com"},
                {"name": "李四", "email": "l@x.com"}]
    assert [o["label"] for o in ec.build_options(dup_mail)] == [
        "张三（z1@x.com）", "张三（z2@x.com）", "李四"]

    # 只有一个候选时保留（此时区分项是信息，不是噪音）
    assert ec.build_options(same[:1])[0]["label"] == "刘洋（来自成都易构）"


def test_options_capped_at_ten_and_unique() -> None:
    ec = _ec()
    members = [{"name": f"人{i}", "userid": f"u{i}"} for i in range(14)]
    members.append({"name": "重复", "userid": "u0"})
    opts = ec.build_options(members)
    assert len(opts) == 10 and len({o["value"] for o in opts}) == 10


# ---------------------------------------------------------------- E9 预取必须不炸

def test_prefetch_swallows_errors() -> None:
    """未连/超时/无权限都不能把整条 run 打挂：返回空候选，主链路照跑。"""
    ec = _ec()

    class _Client:
        def __init__(self, exc=None, ok=True, data=""):
            self.exc, self.ok, self.data = exc, ok, data

        async def invoke(self, name, args):
            if self.exc:
                raise self.exc
            return type("O", (), {"ok": self.ok, "data": self.data, "error": "boom"})()

    tools = [_tool("mcp__qq_mail__list_messages")]
    assert asyncio.run(ec.prefetch(_Client(exc=RuntimeError("hub down")), tools)) == ([], "mail")
    assert asyncio.run(ec.prefetch(_Client(ok=False), tools)) == ([], "mail")
    assert asyncio.run(ec.prefetch(_Client(), [])) == ([], "")


def test_prefetch_parses_real_mail_payload() -> None:
    """端到端形状：hub 返回 JSON 字符串 ⇒ 聚合出收件人/发件人 ⇒ 能直接做成按钮。

    邮件这条链路要**两路合并**：已发送的收件人（我最近写过谁）+ 收件箱的发件人。
    只取收件箱的话，真实邮箱里往往全是 GitHub/系统通知，一个能用的联系人都没有。
    """
    ec = _ec()
    seen_calls = []

    class _Client:
        async def invoke(self, name, args):
            seen_calls.append((name, dict(args)))
            if name.endswith("list_folders"):
                return type("O", (), {"ok": True, "data": json.dumps([
                    {"name": "INBOX", "flags": ["\\HasNoChildren"]},
                    {"name": "Sent Messages", "flags": ["\\HasNoChildren"]},
                ])})()
            if args.get("folder") == "Sent Messages":
                return type("O", (), {"ok": True, "data": json.dumps({"messages": [
                    {"to": '"王五" <wang@x.com>, liu@x.com'},
                    {"to": '"王五" <wang@x.com>'}]})})()
            return type("O", (), {"ok": True, "data": json.dumps({"messages": [
                {"from": '"张三" <zhang@x.com>'}]})})()

    tools = [_tool("mcp__qq_mail__list_folders"), _tool("mcp__qq_mail__list_messages")]
    members, kind = asyncio.run(ec.prefetch(_Client(), tools))
    assert kind == "mail"
    # 已发送的收件人在前（更贴近「给同事发邮件」），收件箱发件人补在后面
    assert [m["email"] for m in members] == ["wang@x.com", "liu@x.com", "zhang@x.com"]
    assert members[0]["name"] == "王五"
    assert any(a.get("folder") == "Sent Messages" for _, a in seen_calls), "要真的去取已发送"


def test_sent_folder_is_discovered_not_hardcoded() -> None:
    """各家「已发送」名字不同 ⇒ 必须按名字判，不能写死 QQ 的 `Sent Messages`。"""
    ec = _ec()
    for folder, expect in [("[Gmail]/Sent Mail", True), ("Sent Items", True),
                           ("已发送", True), ("Drafts", False), ("INBOX", False)]:
        assert bool(ec.SENT_FOLDER_RE.search(folder)) is expect, folder


def test_prefetch_skips_sent_when_no_folder_tool() -> None:
    """没有 list_folders 的连接器：只用收件箱，不许把缺参数当异常抛出去。"""
    ec = _ec()

    class _Client:
        async def invoke(self, name, args):
            assert name.endswith("list_messages") and "folder" not in args
            return type("O", (), {"ok": True, "data": json.dumps(
                {"messages": [{"from": "a@x.com"}]})})()

    members, _ = asyncio.run(ec.prefetch(_Client(), [_tool("mcp__qq_mail__list_messages")]))
    assert [m["email"] for m in members] == ["a@x.com"]


# ---------------------------------------------------------------- E10 合成澄清卡

class _Prov:
    key, model, max_context, temperature = "p", "m", 8000, 0.3

    def api_key(self) -> str:
        return "k"


def _patch_model(monkeypatch, content: str) -> None:
    monkeypatch.setattr(nodes.gateway, "resolve", lambda ref: _Prov())
    monkeypatch.setattr(nodes.settings, "agent_stream", False, raising=False)
    monkeypatch.setattr(nodes.settings, "agent_hitl", True, raising=False)

    async def _post(http, provider, api_key, messages, use_tools, temperature):
        return ({"role": "assistant", "content": content},
                {"prompt_tokens": 1, "completion_tokens": 1})

    monkeypatch.setattr(nodes, "_post_non_stream", _post)


_MEMBERS = [{"name": "刘洋", "userid": "wob1", "departments": "成都易构"},
            {"name": "小亮", "userid": "wob2", "departments": "成都易构"}]


def _agent_state(*, members, clarifications=None, rounds=0, text=None) -> dict:
    from aios_ai.contracts import RunRequest, UserContext

    req = RunRequest(run_id="r_synth", conversation_id=1,
                     text=text or "帮我给同事发条消息说下午三点开会", user_token="t",
                     user_context=UserContext(user_id=2, tenant_id=1,
                                              username="zhangsan", roles=["ROLE_USER"]))
    return {
        "req": req.model_dump(),
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "tools": [_tool("mcp__wecom_cli__contact_search")],
        "agent_rounds": rounds,
        "temperature": 0.3,
        "content_parts": [],
        "entity_candidates": members,
        "entity_source": "contact" if members else "",
        "clarifications": clarifications or [],
    }


def test_agent_short_circuits_before_calling_model(monkeypatch) -> None:
    """**核心用例**：候选已就绪 + 用户没点名 ⇒ 根本不该让模型开口，直接弹卡。

    真机实测（DeepSeek）：模型拿到候选后不肯调 ask_user，把名单写进正文
    （`[阿修bot.](wobVcoRg…)`，userid 还成了链接），代码再补卡 ⇒ 用户同时看到
    一段带机器值的废话和一张按钮卡。所以第一轮直接截胡，连模型都不调。
    """
    called = []

    async def _boom(*a, **kw):
        called.append(1)
        raise AssertionError("短路路径下不该调用模型")

    monkeypatch.setattr(nodes, "_post_non_stream", _boom)
    monkeypatch.setattr(nodes.settings, "agent_stream", False, raising=False)
    monkeypatch.setattr(nodes.settings, "agent_hitl", True, raising=False)

    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS)))
    assert not called, "第一轮就该截胡，模型一次都不该被调"
    calls = out["pending_calls"]
    assert len(calls) == 1 and calls[0]["name"] == "ask_user"
    assert [o["value"] for o in calls[0]["arguments"]["options"]] == ["wob1", "wob2"]
    # 两人同属「成都易构」⇒ 区分项是共有的、等于没区分，省略（否则每行都挤成两行）
    assert calls[0]["arguments"]["options"][0]["label"] == "刘洋"
    assert out["content_parts"] == [], "短路轮不许产出正文（正文就是那段带 userid 的废话）"
    assert nodes.route_after_agent({**out, "allow_tools": True}) == "clarify"


def test_short_circuit_skipped_when_user_names_someone(monkeypatch) -> None:
    """「给同事刘洋发条消息」——用户其实已经点名，弹「要发给哪一位」是纯打扰。"""
    _patch_model(monkeypatch, "好的，这就发给刘洋。")
    out = asyncio.run(nodes.agent(
        _agent_state(members=_MEMBERS, text="给同事刘洋发条消息说下午三点开会")))
    assert out["pending_calls"] == []


def test_short_circuit_skipped_for_broadcast(monkeypatch) -> None:
    """群发语义不该收敛成「选一个人」。"""
    ec = _ec()
    assert ec.can_short_circuit(_MEMBERS, "给同事群发个通知") is False
    assert ec.can_short_circuit(_MEMBERS, "帮我把消息发给所有同事") is False
    assert ec.can_short_circuit(_MEMBERS, "帮我给同事发条消息说下午三点开会") is True


def test_agent_synthesizes_when_model_punted_after_tool_round(monkeypatch) -> None:
    """兜底路径：模型**自己先查了一轮**（rounds>0），下一轮又改成正文列名单 ⇒ 补卡。

    真机就是这个走向：先 contact_search（有 tool.call），再回一段编号列表不调 ask_user。
    """
    _patch_model(monkeypatch, "请选择您要发送消息的同事：\n\n1. 阿修bot.\n2. 小亮\n\n请选择后我将发送消息。")
    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS, rounds=1)))
    assert [c["name"] for c in out["pending_calls"]] == ["ask_user"]
    assert nodes.route_after_agent({**out, "allow_tools": True}) == "clarify"


def test_synth_call_is_echoed_in_openai_shape(monkeypatch) -> None:
    """回注上下文的 assistant 消息必须是 OpenAI 的 tool_calls 形状（arguments 是字符串），
    且 id 与下游 tool 消息一致 —— 否则续跑时上游直接 400。"""
    _patch_model(monkeypatch, "请问是哪位同事？")
    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS, rounds=1)))
    last = out["messages"][-1]
    assert last["role"] == "assistant"
    tc = last["tool_calls"][0]
    assert tc["id"] == out["pending_calls"][0]["id"]
    assert tc["function"]["name"] == "ask_user"
    assert json.loads(tc["function"]["arguments"])["options"][1]["value"] == "wob2"


def test_agent_keeps_answer_when_model_already_answered(monkeypatch) -> None:
    """模型已经给出答案（哪怕答错）也不插卡：再弹「要发给哪一位」只会更乱。"""
    _patch_model(monkeypatch, "下午三点的会议已记入日程，并通知了群里。")
    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS, rounds=1)))
    assert out["pending_calls"] == []
    assert nodes.route_after_agent({**out, "allow_tools": True}) == "finalize"


def test_agent_does_not_synth_without_candidates(monkeypatch) -> None:
    """没查到候选 ⇒ 不合成（宁可不弹，也不弹空卡），退回模型的文字追问。"""
    _patch_model(monkeypatch, "请问要发给哪位同事？")
    out = asyncio.run(nodes.agent(_agent_state(members=[])))
    assert out["pending_calls"] == []


def test_agent_does_not_synth_after_clarification(monkeypatch) -> None:
    """续跑后的第二轮（`clarifications` 非空）不再合成，否则会无限弹同一张卡。"""
    _patch_model(monkeypatch, "请问还要发给哪位同事？")
    out = asyncio.run(nodes.agent(
        _agent_state(members=_MEMBERS, rounds=1,
                     clarifications=[{"question": "q", "answer": "wob1"}])))
    assert out["pending_calls"] == []


def test_agent_does_not_synth_when_hitl_off(monkeypatch) -> None:
    """HITL 关闭时没有 clarify 节点可去（无 checkpointer，interrupt 会直接抛错）。"""
    _patch_model(monkeypatch, "请问要发给哪位同事？")
    monkeypatch.setattr(nodes.settings, "agent_hitl", False, raising=False)
    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS, rounds=1)))
    assert out["pending_calls"] == []


# ============================================================ E11 一次交互交齐
# 2026-11-02 现场：用户点「小亮」后卡片落款「已选择：小亮」，气泡再无下文。
# 根因不是前端不渲染，而是**回填只给了标量**：tool 消息里只有一个 userid，
# 模型不知道「要发什么」，只能再问一句 ⇒ 任务被拆成三轮，上下文断裂。
# 修法：选项可声明 needs_text（选中当场弹输入框、必填），回填 {value,label,text}
# 一次交齐；适配层 `_clarify_answer` 兼容标量/对象两种历史形状。

def test_content_hint_names_the_missing_piece() -> None:
    """按动作词判「还缺什么内容」，且不猜内容本身。"""
    ec = _ec()
    assert ec.content_hint("帮我给同事发条消息")[0] == "要发送的内容"
    assert ec.content_hint("给同事发封邮件")[0] == "邮件内容"
    assert ec.content_hint("帮我约同事开个会")[0] == "时间与主题"
    assert ec.content_hint("提醒一下同事交周报")[0] == "待办标题"
    # 没有动作词 ⇒ 不缺内容（只查人、只看通讯录就不该弹输入框）
    assert ec.content_hint("我同事叫什么名字") is None
    assert ec.content_hint("") is None
    assert ec.content_hint(None) is None


def test_build_clarify_call_marks_needs_text() -> None:
    """合成卡：缺内容时每个选项都带 needs_text + 文案（两形态同一份形状）。"""
    ec = _ec()
    call = ec.build_clarify_call(_MEMBERS, "帮我给同事发条消息说下午三点开会")
    assert call is not None
    opts = call["arguments"]["options"]
    assert all(o["needs_text"] is True for o in opts)
    assert opts[0]["text_label"] == "要发送的内容"
    assert opts[0]["text_placeholder"]
    # value/label 不受影响：机器值仍是 userid
    assert [o["value"] for o in opts] == ["wob1", "wob2"]


def test_build_clarify_call_plain_when_no_gap() -> None:
    """不缺内容 ⇒ **不出现** needs_text 键（老载荷形状逐字节不变）。"""
    ec = _ec()
    call = ec.build_clarify_call(_MEMBERS, "我同事叫什么名字")
    for o in call["arguments"]["options"]:
        assert "needs_text" not in o and "text_label" not in o


def test_build_block_tells_model_about_needs_text() -> None:
    """注入块里的 options JSON 必须是「可照抄且已标好」的那一份。

    模型自己调 ask_user 时不标 needs_text ⇒ 用户选完人仍会被追问内容，
    与代码合成路径走形。所以两条路共用 `with_content_hint`。
    """
    ec = _ec()
    block = ec.build_block(_MEMBERS, "contact", "帮我给同事发条消息")
    assert '"needs_text": true' in block
    assert "要发送的内容" in block
    assert "不要" in block and "追问" in block
    # 只有人、没有内容缺口时不出现这些叮嘱
    plain = ec.build_block(_MEMBERS, "contact", "我同事叫什么名字")
    assert "needs_text" not in plain


def test_build_clarification_keeps_needs_text_and_drops_absent_keys() -> None:
    """ask_user 归一：needs_text 一族**只在显式给出时**才带（老断言形状不变）。"""
    spec = ask_user_tool.build_clarification({
        "question": "发给哪位？",
        "options": [
            {"value": "u1", "label": "刘洋", "needs_text": True,
             "text_label": "要发送的内容", "text_placeholder": "例如：下午三点开会"},
            {"value": "u2", "label": "小亮"},
        ],
    })
    a, b = spec["suggested_options"]
    assert a["needs_text"] is True and a["text_label"] == "要发送的内容"
    assert "needs_text" not in b, "没声明的选项不该被补键（否则全卡都被要求填内容）"
    assert "text_input" not in spec, "没有卡级输入时不许凭空多出键"


def test_build_clarification_card_level_text_input() -> None:
    """卡级输入框：不针对某个选项，而是这一问本身就要一段文字。"""
    spec = ask_user_tool.build_clarification({
        "question": "描述一下你的需求",
        "options": [],
        "text_input": {"placeholder": "例如：报销 3 月差旅"},
    })
    assert spec["text_input"] == {"label": "补充说明", "required": False,
                                  "placeholder": "例如：报销 3 月差旅"}
    assert ask_user_tool.build_clarification(
        {"question": "q", "text_input": {"label": "内容", "required": True}}
    )["text_input"] == {"label": "内容", "required": True}


def test_clarify_answer_normalizes_all_shapes() -> None:
    """回填归一：标量 / {value,label,text} / None 三种历史形状都要认。"""
    assert nodes._clarify_answer("wob1") == {"value": "wob1", "text": ""}
    assert nodes._clarify_answer({"value": "wob1", "label": "刘洋", "text": "下午三点开会"}) \
        == {"value": "wob1", "label": "刘洋", "text": "下午三点开会"}
    # 只给了 text（卡级输入框场景）：value 退化成 text，别把答案丢了
    assert nodes._clarify_answer({"text": "报销 3 月差旅"})["value"] == "报销 3 月差旅"
    assert nodes._clarify_answer(None) == {"value": None, "text": ""}


def test_short_circuit_card_asks_for_content_in_one_shot(monkeypatch) -> None:
    """**核心用例**：一次交互交齐 —— 短路出的卡本身就带 needs_text。

    这条把用户诉求钉死在确定性路径上：不依赖模型「记得」标 needs_text。
    """
    async def _boom(*a, **kw):
        raise AssertionError("短路路径下不该调用模型")

    monkeypatch.setattr(nodes, "_post_non_stream", _boom)
    monkeypatch.setattr(nodes.settings, "agent_stream", False, raising=False)
    monkeypatch.setattr(nodes.settings, "agent_hitl", True, raising=False)

    out = asyncio.run(nodes.agent(_agent_state(members=_MEMBERS)))
    opts = out["pending_calls"][0]["arguments"]["options"]
    assert all(o.get("needs_text") is True for o in opts)
    assert opts[0].get("text_label") == "要发送的内容"


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))