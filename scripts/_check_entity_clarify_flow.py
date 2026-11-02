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
    for kw in ("searchMode=list", "这一轮只澄清", "hasMore=true", "不许编人",
               "降级请用户直接给姓名或工号", "就此终止"):
        chk(kw in blob, f"E5 边界写死：{kw}")

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

    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 —— " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
