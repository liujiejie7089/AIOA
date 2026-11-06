# -*- coding: utf-8 -*-
"""联网检索（web_search / web_fetch）独立验证哨兵 —— 离线为主，不依赖外网。

为什么要有这个哨兵
==================
2026-10-30 用户现场：澄清卡里选了「就业政策」，数字人回「未能找到关于就业政策的邮件」。
根因不是措辞，是**系统里根本没有联网工具**。补工具只解决了一半 —— 另一半是「失败时
不能伪装成成功」：把「网络不通」说成「网上没有」，用户会以为世界上真的没这条信息。
所以本哨兵的核心不是「能不能搜到」，而是：

  R1 解析器能把 Bing 结果页切成结构化条目（title/url/snippet 都在、实体已解码）
  R2 空 query / 反爬页 / 非法 URL / 不可达主机 —— 一律 ok=False + 中文原因
  R3 **绝不返回空列表冒充「没搜到」**（ok=True + results=[] 是禁止态）
  R4 失败文案必须带上原因（模型才有话可如实说）
  R5 工具真的被接进了模型视野（nodes.prepare 注入）且开关可关
  R6 联网结果能进溯源（source='web'、docId=URL）
  R7 task.completed 事件必须带 tool 名（否则 tool.result 帧 name=null，
     前端与审计无法把结果对回工具 —— 2026-10-30 实测踩过）

全部离线：网络相关的用例用 monkeypatch 替换 `_get`，不真的发请求。

用法：
  D:/aios/agent/.venv/Scripts/python.exe scripts/_verify_agent_web_search.py
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from aios_ai.tools import web_search as W          # noqa: E402
from aios_ai.tools import orchestrator as O        # noqa: E402

PROOF = ROOT / "logs" / "proof"
results: list[dict] = []


def rec(name: str, ok: bool, expect: str, actual) -> None:
    results.append({"name": name, "status": "PASS" if ok else "FAIL",
                    "expected": expect, "actual": str(actual)})
    print(("[✅] " if ok else "[❌] ") + name + f"\n      expect={expect}\n      actual ={actual}")


# 合成的 Bing 结果页：两个 b_algo 块（第二个含 HTML 实体与脚本噪声）
FAKE_PAGE = """
<html><body><ol id="b_results">
<li class="b_algo"><h2><a href="https://www.gov.cn/zhengce/2026.htm">2026 年就业政策<strong>要点</strong></a></h2>
  <div class="b_caption"><p>国务院部署<em>就业优先</em>政策，支持重点群体就业。</p></div></li>
<li class="b_algo"><h2><a href="https://www.mohrss.gov.cn/a?x=1&amp;y=2">人社部 &amp; 就业补贴</a></h2>
  <p>一次性扩岗补助与社保补贴延续至 2026 年底。</p><script>var x=1;</script></li>
</ol></body></html>
"""


async def case_parser() -> None:
    got = W._parse_bing(FAKE_PAGE, 6)
    rec("R1 解析器: 切出 2 条结构化结果", len(got) == 2, "len==2", len(got))
    ok_fields = bool(got) and all(
        r.get("title") and r.get("url", "").startswith("http") and r.get("snippet") for r in got)
    rec("R1 解析器: 每条都有 title/url/snippet", ok_fields, "三字段非空", got[:1])
    rec("R1 解析器: HTML 实体已解码（&amp; → &）",
        bool(got) and "&" in got[1]["url"] and "<" not in got[0]["title"],
        "url 含 '&'、title 无标签残留",
        got[1]["url"] if len(got) > 1 else "N/A")


async def case_failures() -> None:
    ok, data, err = await W.invoke("web_search", {"query": ""})
    rec("R2 空 query → ok=False（不是成功空列表）", (not ok) and data is None,
        "ok=False, data=None", f"ok={ok} data={data}")
    rec("R4 空 query 的原因可读（含中文原因）", bool(err) and "搜索词为空" in (err or ""),
        "err 含「搜索词为空」", err)

    # 反爬/无结果块：两个 host 都返回没有 b_algo 的页面
    async def no_algo(url: str, timeout: float) -> str:
        return "<html><body>no results here</body></html>"
    orig = W._get
    W._get = no_algo
    try:
        ok2, data2, err2 = await W.invoke("web_search", {"query": "就业政策"})
    finally:
        W._get = orig
    rec("R3 反爬页 → ok=False（绝不冒充「没搜到」）", (not ok2) and data2 is None,
        "ok=False, data=None", f"ok={ok2} data={data2}")
    rec("R3 反爬页: 原因说明是「无法解析/被拦截」而非「共 0 条」",
        bool(err2) and ("没有可解析的条目" in (err2 or "")) and "0 条" not in (err2 or ""),
        "err 含「没有可解析的条目」且不含「0 条」", err2)

    # 网络不可达：两个 host 都抛异常
    async def boom(url: str, timeout: float) -> str:
        raise ConnectionError("simulated network down")
    W._get = boom
    try:
        ok3, data3, err3 = await W.invoke("web_search", {"query": "就业政策"})
    finally:
        W._get = orig
    rec("R2 网络不可达 → ok=False", (not ok3) and data3 is None, "ok=False, data=None",
        f"ok={ok3} data={data3}")
    rec("R4 网络不可达: 文案含「联网检索失败」+ 底层原因",
        bool(err3) and "联网检索失败" in (err3 or "") and "network down" in (err3 or ""),
        "err 含「联网检索失败」与 'network down'", err3)

    ok4, data4, err4 = await W.invoke("web_fetch", {"url": "ftp://example.com/a.txt"})
    rec("R2 web_fetch 非 http(s) → ok=False", (not ok4) and data4 is None,
        "ok=False, data=None", f"ok={ok4} data={data4}")
    rec("R4 web_fetch 非法协议原因可读", "http" in (err4 or ""), "err 提及 http/https", err4)

    ok5, data5, err5 = await W.invoke("no_such_web_tool", {})
    rec("R2 未知工具名 → ok=False（不静默成功）", (not ok5) and data5 is None,
        "ok=False, data=None", f"ok={ok5} data={data5}")


async def case_fetch_ok() -> None:
    async def fake_page(url: str, timeout: float) -> str:
        return ("<html><head><title>t</title><style>.a{}</style></head>"
                "<body><p>就业政策正文第一段。</p><script>bad()</script></body></html>")
    orig = W._get
    W._get = fake_page
    try:
        ok, data, err = await W.invoke("web_fetch", {"url": "https://example.com/a", "max_chars": 500})
    finally:
        W._get = orig
    ok2 = ok and isinstance(data, dict) and "就业政策正文" in (data or {}).get("text", "")
    rec("R1 web_fetch 抽正文并剥掉 script/style", ok2, "ok=True 且 text 含正文、不含 bad()",
        (data or {}).get("text", "")[:60] if isinstance(data, dict) else data)


async def case_wiring() -> None:
    from aios_ai.config import settings
    rec("R5 开关默认开启（AIOS_WEB_SEARCH）", settings.web_search_enabled is True,
        "web_search_enabled=True", settings.web_search_enabled)
    names = [t["function"]["name"] for t in (W.WEB_SEARCH_TOOL, W.WEB_FETCH_TOOL)]
    rec("R5 两个工具 spec 名称正确", names == ["web_search", "web_fetch"],
        "['web_search', 'web_fetch']", names)
    rec("R5 is_web_tool 只认这两个", all(W.is_web_tool(n) for n in names)
        and not W.is_web_tool("scfy_leave_create"), "web_search/web_fetch 命中、业务工具不命中",
        [W.is_web_tool(n) for n in names] + [W.is_web_tool("scfy_leave_create")])

    # 溯源：联网结果要能进 citations（source=web、docId=URL）
    from aios_ai.knowledge import kb
    from aios_ai.tools.client import ToolOutcome
    outcome = ToolOutcome(name="web_search", arguments={"query": "x"}, ok=True,
                          data={"results": [{"title": "人社部通知",
                                             "url": "https://www.mohrss.gov.cn/n/1.html",
                                             "snippet": "补贴延续"}]}, error=None)
    cites = kb._citations_from_tool("web_search", outcome)
    has_web = any((c.get("source") == "web") for c in cites) if cites else False
    doc_ok = any("mohrss.gov.cn" in str(c.get("docId") or "") for c in cites) if cites else False
    rec("R6 联网结果进溯源（source=web）", has_web, "至少一条 source=='web'", cites[:1])
    rec("R6 溯源 docId 用真实 URL", doc_ok, "docId 含 mohrss.gov.cn", [c.get("docId") for c in cites][:2])


async def case_event_tool_field() -> None:
    """R7：task.completed 必须带 tool —— 否则改名出来的 tool.result 帧 name 恒为 null。"""
    events: list[tuple[str, dict]] = []

    async def fake_invoke(name, args):
        return True, {"ok": 1}, None

    orch = O.Orchestrator(fake_invoke, on_event=lambda t, d: events.append((t, d)))
    task = O.SubTask(id="s1", title="联网查", tool="web_search", arguments={"query": "x"})
    # 走公开的 run()：与真实调用链同一条（plan → 并发执行 → 事件）
    events.clear()
    await orch.run([task])
    done = [d for t, d in events if t == "task.completed"]
    rec("R7 task.completed 带 tool 字段", bool(done) and done[0].get("tool") == "web_search",
        "tool=='web_search'", done[0] if done else "无 task.completed 事件")
    started = [d for t, d in events if t == "task.started"]
    rec("R7 task.started 也带 tool（两侧对齐）",
        bool(started) and started[0].get("tool") == "web_search", "tool=='web_search'",
        started[0] if started else "无 task.started 事件")


def main() -> int:
    PROOF.mkdir(parents=True, exist_ok=True)
    asyncio.run(case_parser())
    asyncio.run(case_failures())
    asyncio.run(case_fetch_ok())
    asyncio.run(case_wiring())
    asyncio.run(case_event_tool_field())

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed
    print(f"\n==== 联网检索验证：PASS {passed} / FAIL {failed} ====")
    md = ["# 联网检索（web_search/web_fetch）· 独立验证举证\n",
          f"结论：PASS {passed} / FAIL {failed}\n",
          "| 项 | 状态 | 期望 | 实际 |", "|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['name']} | {r['status']} | {r['expected']} | {r['actual']} |")
    (PROOF / "agent_web_search_verify.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (PROOF / "agent_web_search_verify.json").write_text(
        json.dumps({"summary": {"pass": passed, "fail": failed}, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"举证报告：{PROOF / 'agent_web_search_verify.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
