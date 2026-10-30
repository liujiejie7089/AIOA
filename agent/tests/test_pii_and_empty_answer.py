# -*- coding: utf-8 -*-
"""个人信息红线 + 空回答兜底（2026-10-30 现场两个缺陷的回归）。

现场：用户问「我邮箱是多少」，模型调了 `mcp__wecom_cli__whoami`（只返回
`{"bound":true,"userName":"刘洋","botName":"..."}`，**没有任何邮箱字段**），
然后拿姓名拼出 `liuyang@yourcompany.com（假设公司域名为 yourcompany.com）`；
下一句「qq」则收到空回答，界面显示「（本次未返回内容）」。

两件事都不是措辞问题，各有一条硬判据：
  P1 提示词必须带【个人信息红线】，且明确禁止「姓名+猜域名」与「假设/以…为例」占位；
  P2 模型返回空内容时，收尾节点必须给出**可行动**的兜底文案并补发 delta，
     不允许落一条空消息（空消息在界面上就是死胡同）。
"""
from __future__ import annotations

import asyncio

from aios_ai.contracts import RunRequest, UserContext
from aios_ai.graph import nodes
from aios_ai.prompt.builder import build_messages


def _system_blob() -> str:
    req = RunRequest(run_id="r_pii", conversation_id=1, text="我邮箱是多少",
                     user_token="t",
                     user_context=UserContext(user_id=2, tenant_id=1,
                                              username="zhangsan",
                                              roles=["ROLE_USER"]))
    msgs = build_messages(req)
    return "\n".join(m.get("content") or "" for m in msgs if m.get("role") == "system")


def test_prompt_has_pii_redline() -> None:
    blob = _system_blob()
    assert "【个人信息红线】" in blob, "提示词缺少个人信息红线"
    # 三个必须点名的禁令（少一条模型就会找漏洞）
    assert "姓名 + 猜测域名" in blob or "姓名+猜测域名" in blob.replace(" ", ""), \
        "未禁止「姓名 + 猜域名」拼造邮箱"
    assert "假设域名为" in blob, "未禁止「假设域名为…」占位式回答"
    assert "个人资料" in blob, "未给出没有数据时的真实入口"


def test_prompt_pii_rule_mentions_absence() -> None:
    blob = _system_blob()
    assert "没有你的邮箱登记信息" in blob, "未给出「没有就说没有」的标准说法"
    # 规则要落在「数据」上而不是某个工具名上：硬编码工具名会让规则随工具重命名失效
    assert "原值" in blob, "未要求只用工具返回的原值"
    assert "whoami" not in blob, "个人信息规则不应绑定具体工具名（应约束数据来源）"


def _run_finalize(**state) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    orig = nodes._emit
    nodes._emit = lambda t, d: events.append((t, d))
    try:
        asyncio.run(nodes.finalize(state))
    finally:
        nodes._emit = orig
    return events


def test_finalize_empty_answer_gets_actionable_fallback() -> None:
    events = _run_finalize(content_parts=[], tool_calls_log=[], usage={})
    deltas = "".join(d.get("text") or "" for t, d in events if t == "message.delta")
    done = [d for t, d in events if t == "message.completed"]
    assert done, "缺少 message.completed"
    content = done[0]["content"]
    assert content, "空内容仍然落库 —— 界面会显示死胡同文案"
    assert deltas == content, "兜底文案没有补发 delta（前端靠 delta 渲染）"
    assert ("再问一次" in content) or ("更具体" in content), "兜底文案不可行动"


def test_finalize_keeps_real_content() -> None:
    events = _run_finalize(content_parts=["你好，"], tool_calls_log=[], usage={})
    done = [d for t, d in events if t == "message.completed"]
    assert done[0]["content"] == "你好，", "真实内容不该被兜底覆盖"
