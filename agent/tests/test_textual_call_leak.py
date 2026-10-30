# -*- coding: utf-8 -*-
"""「工具调用写成正文」不得泄漏到用户界面的回归（2026-10-30 现场）。

现象：模型把调用写成正文
    <function_call>```typescript\nmcp__wecom_cli__whoami({})\n```</function_call>
救援逻辑（`_rescue_textual_calls`）把它还原成真调用并执行了 —— 但**原文仍然逐片推给了用户**，
于是回答开头出现 ```` ```typescript mcp__wecom_cli__whoami({}) ``` ````。
上一轮同形（`functions.mcp__wecom_cli__recent_group_sessions({"days": 7})`）也是这个原因。

判据：
  L1 `_strip_call_text` 能删掉标签式 / 围栏式 / 裸行的调用文本；
  L2 正常代码块（```python …）**不能**被误删；
  L3 流式暂扣只对「像调用开头」的文本生效 —— 普通中文开头必须立刻下发，
     否则 message.delta 与上游分片的一对一契约会被悄悄改掉。
"""
from __future__ import annotations

from aios_ai.graph.nodes import _looks_like_call_start, _strip_call_text


def test_strip_tag_wrapped_fence() -> None:
    raw = ('<function_call>```typescript\nmcp__wecom_cli__whoami({})\n```</function_call>'
           '我这边没有你的邮箱登记信息。')
    assert _strip_call_text(raw) == "我这边没有你的邮箱登记信息。"


def test_strip_fence_without_tag() -> None:
    raw = '```typescript\nfunctions.mcp__wecom_cli__recent_group_sessions({"days": 7})\n```'
    assert _strip_call_text(raw) == ""


def test_strip_bare_call_line() -> None:
    raw = "正在为你查询。\nmcp__wecom_cli__whoami({})\n稍等。"
    out = _strip_call_text(raw)
    assert "mcp__wecom_cli__whoami" not in out
    assert "正在为你查询。" in out and "稍等。" in out


def test_strip_unclosed_tag() -> None:
    """模型只写开标签、忘了闭合（实测形态）——成对正则匹配不到，必须单独扫掉。"""
    raw = "<function_call>我这边没有您的邮箱登记信息。"
    assert _strip_call_text(raw) == "我这边没有您的邮箱登记信息。"
    raw2 = "```typescript\nmcp__x__y({})\n```</function_call>收尾一句。"
    assert _strip_call_text(raw2) == "收尾一句。"


def test_keep_normal_code_block() -> None:
    raw = "示例：\n```python\nprint(1)\n```\n就这样。"
    out = _strip_call_text(raw)
    assert "print(1)" in out, "正常代码块被误删 —— 会把用户要的示例吃掉"
    assert "就这样。" in out


def test_keep_plain_text() -> None:
    raw = "2026 年就业政策要点如下：\n1. 稳岗返还\n2. 扩岗补助"
    assert _strip_call_text(raw) == raw


def test_call_start_detection() -> None:
    assert _looks_like_call_start("<function_call>")
    assert _looks_like_call_start("```typescript")
    assert _looks_like_call_start("functions.foo(")
    assert _looks_like_call_start("mcp__wecom_cli__whoami({})")
    # 普通叙述不能被当成调用开头（否则所有回答都会被攒成一大段再吐）
    assert not _looks_like_call_start("你好，我来帮你查")
    assert not _looks_like_call_start("根据最新政策")
    assert not _looks_like_call_start("2026 年的数据")
