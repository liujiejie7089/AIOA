# -*- coding: utf-8 -*-
"""模糊实体澄清流程的**静态一致性**哨兵（不需要后端、不需要网络、不需要真实凭据）。

## 为什么要有这个哨兵

「查我同事考勤」这条流程横跨四处代码，任何一处单独改都会静默走形：

  ① `mcp-hub/.../wecom_cli/server.py`  —— 候选上限（多回几个模型也不会用，少回就选不到人）
  ② `agent/aios_ai/tools/ask_user.py`   —— 选项上限（曾经是 6，第 7~10 个候选被静默丢弃）
  ③ `user-client/index.html`            —— 澄清卡渲染上限（同样是 6，且与 ② 各写一份）
  ④ `agent/aios_ai/graph/nodes.py`      —— ask_user 轮是否真的不执行本轮业务调用

2026-11-02 就是这样：三个上限各写一份、两个是 6、一个是 10，谁也不知道另一个在哪。
**判据必须落在「三处相等」上**，而不是各自等于一个字面量 —— 否则将来只改一处照样绿。

## 判据

  E1  三处候选/选项上限相等且为 10（hub `_CONTACT_MAX` / agent `MAX_OPTIONS` / H5 `CLAR_MAX_OPTS`）
  E2  H5 渲染真的用 `CLAR_MAX_OPTS`，且卡片里不再有裸 `slice(0, 6)`
  E3  `.clar-opts` 有 max-height（10 个选项靠内滚动，不把气泡顶出一屏）
  E4  catalog 声明了 `searchMode` 且 `_PARAMS` 与之同步（两处参数事实源）
  E5  提示词块存在，且四个边界（>10 / 无结果 / 接口失败 / 只澄清）都写死
  E6  行为断言：ask_user 轮的业务调用被丢弃 + 补 tool 消息；confirm 轮照旧放行
  E7  负向自检：把上限改回 6（内存里改，不碰磁盘）⇒ E1 必须转红
  E8  连接器无关：人源按工具短名发现（企微通讯录 / QQ 邮箱 list_messages 走同一条链）
  E9  图里真的接上了两处确定性路径（prepare 预取 + agent 合成），且负向不弹空卡

跑法：
  agent/.venv/Scripts/python.exe scripts/_check_entity_clarify_flow.py
退出码非零 = 有断言失败。
"""
import asyncio
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "mcp-hub"))
sys.path.insert(0, os.path.join(REPO, "agent"))

INDEX = os.path.join(REPO, "user-client", "index.html")

fails = []
oks = 0


def chk(cond, name, detail="") -> None:
    global oks
    if cond:
        oks += 1
        print(f"[OK  ] {name}" + (f" — {detail}" if detail else ""))
    else:
        fails.append(name)
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def head(title: str) -> None:
    print(f"\n=== {title} ===")


def _read(path: str) -> str:
    return io.open(path, encoding="utf-8").read()


def main() -> int:
    # ------------------------------------------------------------------ E1
    head("E1 三处候选/选项上限必须相等")
    from mcp_hub.wecom_cli import catalog, server as hub_server   # noqa: E402

    from aios_ai.tools import ask_user as ask_user_tool          # noqa: E402

    html = _read(INDEX)
    m = re.search(r"var\s+CLAR_MAX_OPTS\s*=\s*(\d+)", html)
    h5_cap = int(m.group(1)) if m else -1
    hub_cap = int(getattr(hub_server, "_CONTACT_MAX", -1))
    agent_cap = int(getattr(ask_user_tool, "MAX_OPTIONS", -1))
    chk(hub_cap == agent_cap == h5_cap == 10,
        "E1 hub / agent / H5 三处上限相等且为 10",
        f"hub={hub_cap} agent={agent_cap} h5={h5_cap}")

    # ------------------------------------------------------------------ E2
    head("E2 H5 用变量渲染，不再写死 6")
    chk("slice(0, CLAR_MAX_OPTS)" in html, "E2 澄清卡按 CLAR_MAX_OPTS 渲染")
    # 反向：卡片函数体里不得再出现裸 6（历史上就是它把第 7 个候选吃掉的）
    body = html[html.find("function clarCardHtml"):html.find("var clarPendingResolve")]
    chk(not re.search(r"slice\(\s*0\s*,\s*6\s*\)", body),
        "E2 澄清卡里没有裸 slice(0, 6)", "命中即代表有人把上限又写死了")

    # ------------------------------------------------------------------ E3
    head("E3 选项容器可滚动（10 个选项不撑爆气泡）")
    chk(re.search(r"\.clar-opts\{[^}]*max-height\s*:", html) is not None,
        "E3 .clar-opts 设了 max-height")
    # 溢出时打 .many：否则「半截行 + 确认按钮」贴在一起，看着像按钮压住了列表
    chk("card.classList.add('many')" in html, "E3 溢出时打 .many 标记")
    chk(".clar-card.many .clar-ok" in html, "E3 .many 时给确认按钮留间距")
    chk("mask-image" in html, "E3 .many 时底部渐隐（暗示还有内容）")

    # ------------------------------------------------------------------ E4
    head("E4 contact_search 的 searchMode 两处参数源同步")
    tool = next((t for t in catalog.TOOLS if t["name"] == "contact_search"), {})
    props = ((tool.get("input_schema") or {}).get("properties") or {})
    chk("searchMode" in props, "E4 catalog 声明 searchMode",
        f"现有字段={sorted(props)}")
    declared = set((tool.get("input_schema") or {}).get("required") or [])
    actual = {p[0] for p in hub_server._PARAMS.get("contact_search", []) if p[2] is None}
    chk(declared == actual, "E4 catalog.required 与 _PARAMS 必填一致",
        f"required={sorted(declared)} / 必填={sorted(actual)}")
    chk(any(p[0] == "searchMode" for p in hub_server._PARAMS.get("contact_search", [])),
        "E4 _PARAMS 里有 searchMode")
    chk(getattr(hub_server, "_exec_contact_search", None) is not None
        and "hasMore" in io.open(os.path.join(REPO, "mcp-hub", "mcp_hub", "wecom_cli",
                                              "server.py"), encoding="utf-8").read(),
        "E4 回包带 hasMore（>10 时模型才知道别弹按钮）")

    # ------------------------------------------------------------------ E5
    head("E5 提示词纪律（HITL 开着才写）")
    from aios_ai.contracts import RunRequest, UserContext   # noqa: E402
    from aios_ai.prompt import builder as prompt_builder    # noqa: E402

    def system_blob() -> str:
        req = RunRequest(run_id="r_entity", conversation_id=1, text="查我同事考勤",
                         user_token="t",
                         user_context=UserContext(user_id=2, tenant_id=1,
                                                  username="zhangsan", roles=["ROLE_USER"]))
        return "\n".join(m.get("content") or "" for m in prompt_builder.build_messages(req)
                         if m.get("role") == "system")

    _orig = getattr(prompt_builder.settings, "agent_hitl", False)
    try:
        prompt_builder.settings.agent_hitl = True
        blob = system_blob()
    finally:
        prompt_builder.settings.agent_hitl = _orig
    chk("模糊的人先澄清" in blob, "E5 有【模糊的人先澄清】段")
    for kw in ("searchMode=list", "这一轮只澄清", "hasMore=true", "不许编人", "就此终止",
               # 2026-11-02 用户实测「帮我给同事发条消息」被正文反问一句 —— 这三个词就是那条退化
               "严禁", "options 传空数组", "请输入姓名或工号"):
        chk(kw in blob, f"E5 边界写死：{kw}")
    # 反向：提示词里不能再出现「让用户自己打字补充」式的旧措辞（那正是被投诉的行为）
    chk("降级请用户直接给姓名或工号" not in blob,
        "E5 旧措辞已清除（不许再用正文索要姓名）")

    # ------------------------------------------------------------------ E6
    head("E6 行为断言：ask_user 轮不执行本轮业务调用")
    from aios_ai.graph import nodes as graph_nodes          # noqa: E402

    def state(*names):
        calls = [{"id": f"c{i}", "name": n, "arguments": {"x": 1}} for i, n in enumerate(names)]
        return {"req": {"run_id": "r_entity"},
                "messages": [{"role": "assistant", "content": "",
                              "tool_calls": [{"id": c["id"], "type": "function",
                                              "function": {"name": c["name"], "arguments": "{}"}}
                                             for c in calls]}],
                "pending_calls": calls}

    _orig_interrupt = graph_nodes.interrupt
    graph_nodes.interrupt = lambda spec: "wobVcoRgAAwZdjMSCNmVIBRHqFTQwuAQ"
    try:
        out = asyncio.run(graph_nodes.clarify(
            state("ask_user", "mcp__wecom_cli__attendance_list")))
        out_confirm = asyncio.run(graph_nodes.clarify(
            state("request_confirm", "mcp__qq_mail__send_draft")))
    finally:
        graph_nodes.interrupt = _orig_interrupt

    chk(out["pending_calls"] == [], "E6 ask_user 轮 pending_calls 清空")
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    chk([m.get("tool_call_id") for m in tool_msgs] == ["c0", "c1"],
        "E6 被丢弃的调用补了 tool 消息（否则下次请求 400）",
        f"tool 消息={[m.get('tool_call_id') for m in tool_msgs]}")
    chk(any("SKIPPED_PENDING_CLARIFICATION" in (m.get("content") or "") for m in tool_msgs),
        "E6 补的消息里说明了「未执行」")
    chk((out.get("tool_calls_log") or [{}])[0].get("status") == "SKIPPED",
        "E6 丢弃也进审计（tool_calls_log）")
    chk([c["name"] for c in out_confirm["pending_calls"]] == ["mcp__qq_mail__send_draft"],
        "E6 确认链零回归：余量照旧交回 tools")

    # ------------------------------------------------------------------ E7
    head("E7 负向自检：上限改回 6 必须转红")
    real = ask_user_tool.MAX_OPTIONS
    ask_user_tool.MAX_OPTIONS = 6
    try:
        now = int(getattr(ask_user_tool, "MAX_OPTIONS", -1))
        chk(not (hub_cap == now == h5_cap == 10), "E7 判据非恒真（改回 6 会红）",
            f"hub={hub_cap} agent={now} h5={h5_cap}")
    finally:
        ask_user_tool.MAX_OPTIONS = real

    # ------------------------------------------------------------------ E8
    head("E8 连接器无关：人源按工具短名发现")
    from aios_ai.tools import entity_clarify as ec                 # noqa: E402

    def _t(n):
        return {"type": "function", "function": {"name": n}}

    wecom_src = ec.find_people_source([_t("mcp__wecom_cli__contact_search")])
    mail_src = ec.find_people_source([_t("mcp__qq_mail__list_messages")])
    chk(wecom_src == {"kind": "contact", "tool": "mcp__wecom_cli__contact_search"},
        "E8 企微：contact_search 识别为通讯录人源", str(wecom_src))
    chk(mail_src == {"kind": "mail", "tool": "mcp__qq_mail__list_messages"},
        "E8 QQ 邮箱：list_messages 识别为邮件人源（不写死连接器 code）", str(mail_src))
    chk(ec.find_people_source([_t("mcp__qq_mail__search_messages")]) is None,
        "E8 负向：只有 search_messages 不算人源（query 必填，这里恰恰不知道搜什么）")
    chk(ec.find_people_source([_t("kb_search")]) is None,
        "E8 负向：没有连接器工具 ⇒ 不造人")

    # 两条链路最终产出**同一种**澄清卡形状：value 是机器值、label 是人看的
    mail_rows = ec.parse_members({"messages": [{"from": '"张三" <zhang@x.com>'},
                                               {"from": "li@x.com"}]}, "mail")
    mail_opts = ec.build_options(mail_rows)
    chk([o["value"] for o in mail_opts] == ["zhang@x.com", "li@x.com"],
        "E8 邮件候选的 value 是邮箱（可直接喂 send_draft 的 to）", str(mail_opts))
    contact_rows = ec.parse_members({"members": [
        {"name": "刘洋", "userid": "wob1", "departments": "研发部", "position": "工程师"}]},
        "contact")
    chk(ec.build_options(contact_rows) == [
        {"value": "wob1", "label": "刘洋（研发部 / 工程师）"}],
        "E8 通讯录候选的 value 是 userid、label 带部门/职位")

    # ------------------------------------------------------------------ E9
    head("E9 图里的两处确定性接线")
    nodes_src = _read(os.path.join(REPO, "agent", "aios_ai", "graph", "nodes.py"))
    state_src = _read(os.path.join(REPO, "agent", "aios_ai", "graph", "state.py"))
    chk("entity_clarify_tool.prefetch(" in nodes_src,
        "E9 prepare 里真的调了 prefetch（不是只有提示词）")
    chk("entity_clarify_tool.build_call(" in nodes_src,
        "E9 agent 里真的会合成 ask_user（两条合成路径统一走 build_call）")
    chk(nodes_src.count("entity_clarify_tool.build_call(") == 2,
        "E9 短路与兜底两处都走同一个入口（判断不分叉）",
        f"{nodes_src.count('entity_clarify_tool.build_call(')} 处")
    chk("entity_clarify_tool.looks_like_person_question(" in nodes_src,
        "E9 合成前先确认模型是在反问人名（已作答就不打扰）")
    chk("entity_candidates" in state_src and "entity_source" in state_src,
        "E9 RunState 声明了预取结果（LangGraph 要求节点写回的键都在 schema 里）")

    # 负向：候选为空时必须返回 None —— 证明判据不是恒真，不会弹空卡
    chk(ec.build_clarify_call([]) is None, "E9 负向：0 个候选 ⇒ 不合成调用")
    synth = ec.build_clarify_call(contact_rows)
    chk(synth and synth["name"] == "ask_user"
        and synth["arguments"]["options"][0]["value"] == "wob1",
        "E9 有候选 ⇒ 合成的是 ask_user，value 用通讯录 userid")

    # ------------------------------------------------------------------ E10
    head("E10 真机反馈：短路调模型 + 不泄露机器值")
    # 2026-11-02 真机（DeepSeek）实测两条退化，都必须被代码挡住：
    #   ① 模型拿到候选后不肯调 ask_user，把名单写进正文，还把 userid 渲染成
    #      `[阿修bot.](wobVcoRg…)` 链接 ⇒ 用户看到一段带机器值的废话 + 一张卡；
    #   ② 「给同事刘洋发消息」其实已经点名，却还要弹「要发给哪一位」。
    members = [{"name": "刘洋", "userid": "u1", "departments": "研发部"},
               {"name": "小亮", "userid": "u2", "departments": "研发部"}]
    chk("entity_clarify_tool.can_short_circuit(" in nodes_src,
        "E10 agent 第一轮会短路（不给模型写正文的机会）")
    chk("names_in_text(" in nodes_src,
        "E10 兜底合成也会避开「用户已点名」的情况")
    chk(ec.can_short_circuit(members, "帮我给同事发条消息说下午三点开会") is True,
        "E10 正常诉求 ⇒ 短路弹卡")
    chk(ec.can_short_circuit(members, "给同事刘洋发条消息") is False,
        "E10 用户已点名刘洋 ⇒ 不短路（再问就是打扰）")
    chk(ec.can_short_circuit(members, "给同事群发个通知") is False,
        "E10 群发语义 ⇒ 不收敛成选一个人")
    chk(ec.can_short_circuit([], "帮我给同事发条消息") is False,
        "E10 没候选 ⇒ 不短路（不许弹空卡）")
    block = ec.build_block(members, "contact")
    chk('"value": "u1"' in block and "逐字照抄" in block,
        "E10 注入块直接给可照抄的 options JSON（只给姓名时模型会退回正文列名单）")
    chk("不要把名单写进正文" in block, "E10 注入块明令不许把名单写进正文")

    # ------------------------------------------------------------------ E11
    head("E11 一次交互交齐：选完不终止 + 动态文本框 + 单次提交")
    # 2026-11-02 现场：点「小亮」后卡片落款「已选择：小亮」，气泡再无下文。
    # 根因是回填只给标量 —— 模型拿不到「要发什么」，只能再问一轮，任务被拆成三轮。
    html_now = _read(INDEX)
    chk("function clarAnswerPayload(" in html_now,
        "E11 H5 有统一回填载荷 clarAnswerPayload（两形态共用一份形状）")
    # 只数「调用处」，别把 `function clarAnswerPayload(pick)` 的定义本身也算进去
    n_use = len(re.findall(r"resumeStream\(\s*(?:state\.)?runId\s*,\s*clarAnswerPayload\(pick\)",
                           html_now))
    chk(n_use == 2,
        "E11 经典 send 与 OA oaSend 都改走对象载荷", f"实际 {n_use} 处（应为 2）")
    chk("resumeStream(runId, pick.value, h)" not in html_now and
        "resumeStream(state.runId, pick.value, h)" not in html_now,
        "E11 不再有「只回标量」的旧调用（标量是上下文断裂的根因）")
    chk("text:(pick.text || '')" in html_now,
        "E11 载荷里始终带 text（空也要带，形状统一，agent 侧不用猜）")
    chk("clar-text-wrap" in html_now and "clar-text" in html_now,
        "E11 H5 渲染补充输入框容器")
    chk("needs_text === true" in html_now,
        "E11 只有声明了 needs_text 的选项才要求填内容（不是整卡强制）")
    chk("function syncText(" in html_now and "function syncOk(" in html_now,
        "E11 选中/取消选中会同步输入框显隐与提交按钮可用性")
    chk("textBox.value = ''" in html_now,
        "E11 切到不需要内容的选项时清空输入框（避免把上一项内容带过去）")
    chk("(e.ctrlKey || e.metaKey)" in html_now,
        "E11 输入框里 Ctrl/Cmd+Enter 提交（普通 Enter 留给换行）")
    # 只数**调用**（行首缩进 + 分号），别把 `function liftTextBelowCard(bubble){` 算进去
    n_lift = len(re.findall(r"^\s*liftTextBelowCard\(bubble\);", html_now, re.M))
    chk("function liftTextBelowCard(" in html_now and n_lift == 2,
        "E11 落定后把正文容器挪到卡片之下（两形态各一处）", f"{n_lift} 处调用")

    nodes_now = _read(os.path.join(REPO, "agent", "aios_ai", "graph", "nodes.py"))
    chk("def _clarify_answer(" in nodes_now,
        "E11 agent 侧把回填归一成 {value,label,text}")
    chk('if chain == "clarify":\n        payload' in nodes_now,
        "E11 归一化只作用于 clarify 链（套到 confirm 上会把 decision 吃掉）")
    chk('"next": hint' in nodes_now,
        "E11 tool 消息带下一步指令（「直接执行，别再确认一次」），减少重复追问")

    members2 = [{"name": "刘洋", "userid": "u1"}, {"name": "小亮", "userid": "u2"}]
    call2 = ec.build_clarify_call(members2, "帮我给同事发条消息说下午三点开会")
    opts2 = call2["arguments"]["options"]
    chk(all(o.get("needs_text") is True for o in opts2),
        "E11 「发消息」缺内容 ⇒ 选项带 needs_text（界面会弹输入框）")
    chk(opts2[0].get("text_label") == "要发送的内容",
        "E11 输入框标题点明缺什么", opts2[0].get("text_label", ""))
    call3 = ec.build_clarify_call(members2, "我同事叫什么名字")
    chk(all("needs_text" not in o for o in call3["arguments"]["options"]),
        "E11 不缺内容 ⇒ 不出现 needs_text（老载荷形状不变）")
    chk(ec.content_hint("帮我约同事开个会")[0] == "时间与主题",
        "E11 会议类动作要「时间与主题」")
    chk(ec.content_hint("帮我给同事发条消息说下午三点开会")[0] == "要发送的内容",
        "E11 一句话里同时有「消息」「开会」⇒ 按先出现的动作判（消息）")

    # ------------------------------------------------------------------ E12
    head("E12 动态字段卡：菜单 / 候选框 / 文本框 / 依赖 / 校验 / 一次提交")
    # 用户口径：「根据语义动态生成菜单、候选框和文本框，并依据输入驱动后续流程」。
    # 判据钉在三处：① 模型侧能声明 fields（schema 有枚举）；② 服务端会收敛坏 schema；
    # ③ H5 有字段引擎（渲染/依赖/校验/提交），并且旧的单选卡不受影响。
    chk("fields" in ask_user_tool.ASK_USER_TOOL["function"]["parameters"]["properties"],
        "E12 ask_user 暴露 fields（模型才能按语义给控件）")
    props = ask_user_tool.ASK_USER_TOOL["function"]["parameters"]["properties"]["fields"]["items"]
    chk(set(props["properties"]["type"]["enum"]) == set(ask_user_tool.FIELD_TYPES),
        "E12 控件类型是封闭枚举（select/multi/text/textarea/date/datetime/number）",
        str(ask_user_tool.FIELD_TYPES))
    chk("visible_when" in props["properties"],
        "E12 依赖条件有独立声明（visible_when），不是靠提示词约定")

    spec_f = ask_user_tool.build_clarification({
        "question": "q",
        "options": [{"value": "a", "label": "A"}],
        "fields": [{"id": "x", "label": "X", "type": "weird"},
                   {"id": "y", "label": "Y", "type": "select"},
                   {"id": "z", "label": "Z", "type": "text",
                    "visible_when": {"field": "nope", "value": 1}}],
    })
    chk(spec_f["suggested_options"] == [] and "text_input" not in spec_f,
        "E12 有 fields ⇒ 旧选项/卡级输入一律丢弃（一张卡不能两套规则）")
    chk([f["type"] for f in spec_f["fields"]] == ["text", "text", "text"],
        "E12 未知类型、无候选的菜单都降级成 text（不留死控件）",
        str([f["type"] for f in spec_f["fields"]]))
    chk("visible_when" not in spec_f["fields"][2],
        "E12 依赖指向不存在的字段 ⇒ 剪掉条件（字段保留）")

    chk("function clarFieldsHtml(" in html_now and "function mountClarFields(" in html_now,
        "E12 H5 有字段渲染与字段引擎两个入口")
    for cls in ("clar-search", "clar-cand", "clar-inp", "clar-err", "clar-fields"):
        chk(cls in html_now, f"E12 控件类名 {cls} 存在")
    chk("data-fid=" in html_now, "E12 每个字段带 data-fid（依赖与校验按 id 定位）")
    chk("function condOk(" in html_now and "condOk(f.visible_when" in html_now,
        "E12 依赖求值真的被调用（不是只渲染不计算）")
    chk("function clearField(" in html_now, "E12 字段隐藏时清空（不把上一支的内容带过去）")
    chk("function errOf(" in html_now, "E12 每个字段有独立校验")
    chk("visible().every(" in html_now, "E12 提交前对所有**可见**字段做整体校验")
    chk("out.values = pick.values" in html_now,
        "E12 回填载荷带 values（一次交齐全字段）")
    chk('data-clar-ok="1">确认' in html_now,
        "E12 字段卡的确认键不置灰（点后校验并点亮问题字段，而不是让用户猜）")

    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 —— " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
