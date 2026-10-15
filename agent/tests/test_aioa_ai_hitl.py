"""HITL 澄清链（``ask_user`` → ``need_clarification`` → ``resume``）测试。

对应 `docs/50 §7` 的试点判据里的三条可离线验证项：
  - **Q1 中断可达**：模型调 ``ask_user`` ⇒ 产出 ``need_clarification``（含 question +
    suggested_options），且该轮**不发** ``run.completed``（是暂停，不是结束）；
  - **Q3 精确恢复**：resume 后**不重跑**已完成的工具调用（用调用计数断言，防副作用重复）；
  - **Q4 契约不破**：关闭 HITL 时事件序列与既有实现一致（由既有套件 108 项覆盖）。

不连真实模型：provider 解析与上游 HTTP 全部打桩。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aioa_ai.contracts import RunRequest, UserContext
from aioa_ai.llm import Provider
from aioa_ai.tools.client import ToolClient, ToolOutcome

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOA_TEST_FAKE_KEY")


def _req(text: str = "帮我处理一下") -> RunRequest:
    return RunRequest(run_id="run_hitl_0001", conversation_id=1, text=text,
                      model_ref="fake", user_token="tok",
                      user_context=UserContext(user_id=1, tenant_id=1))


def _stub(stream_stub, *extra):
    return [
        patch("aioa_ai.entry.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aioa_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


async def _enable_hitl():
    """打开开关 + 建内存 checkpointer + 重编译图（顺序不能反：先 setup 再 reset）。"""
    from aioa_ai.config import settings
    from aioa_ai.graph import builder, checkpoint

    settings.agent_hitl = True
    settings.checkpoint_url = ""            # 内存
    await checkpoint.setup()
    builder.reset()


async def _disable_hitl():
    from aioa_ai.config import settings
    from aioa_ai.graph import builder, checkpoint

    settings.agent_hitl = False
    await checkpoint.aclose()
    builder.reset()


def test_hitl_ask_user_pauses_then_resumes(monkeypatch):
    """Q1 + Q3：ask_user 暂停发 need_clarification；resume 后继续，且已完成的工具不重跑。"""
    monkeypatch.setenv("AIOA_TEST_FAKE_KEY", "k")
    calls = {"n": 0}
    tool_hits = {"n": 0}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第 1 轮：先调业务工具（这一步的结果必须被「冻结」到 resume 之后也不重跑）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "get_my_quota", "arguments": "{}"}}]},
                {"prompt_tokens": 5, "completion_tokens": 1})
        elif calls["n"] == 2:
            # 第 2 轮：意图模糊 ⇒ 调 ask_user 追问（本轮应暂停）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "a1", "type": "function",
                 "function": {"name": "ask_user", "arguments":
                              '{"question":"你要处理哪一类？","options":['
                              '{"value":"contract","label":"合同"},'
                              '{"value":"expense","label":"报销"}]}'}}]},
                {"prompt_tokens": 5, "completion_tokens": 2})
        else:
            # 第 3 轮（resume 之后）：据澄清答案作答
            for piece in ("已", "收到", "：合同"):
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "已收到：合同"},
                   {"prompt_tokens": 6, "completion_tokens": 3})

    async def counting_invoke(self, name, arguments=None):
        if name == "get_my_quota":
            tool_hits["n"] += 1
        return ToolOutcome(name=name, arguments=arguments or {}, ok=True, data={"left": 10})

    async def scenario():
        from aioa_ai import entry

        ctx = _stub(
            fake_stream,
            patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
                {"type": "function", "function": {"name": "get_my_quota",
                                                  "description": "q", "parameters": {}}}])),
            patch.object(ToolClient, "invoke", counting_invoke),
        )
        await _enable_hitl()
        for c in ctx:
            c.start()
        try:
            first = [(e.seq, e.type, e.data) async for e in entry.run(_req())]
            second = [(e.seq, e.type, e.data)
                      async for e in entry.resume("run_hitl_0001", "contract")]
        finally:
            for c in ctx:
                c.stop()
            await _disable_hitl()
        return first, second

    first, second = asyncio.run(scenario())

    # —— Q1：暂停 + need_clarification ——
    t1 = [t for _, t, _ in first]
    assert "need_clarification" in t1, f"应产出 need_clarification，实际={t1}"
    assert "run.completed" not in t1, "暂停不是结束：本轮不应发 run.completed"
    nc = next(d for _, t, d in first if t == "need_clarification")
    assert nc["question"] == "你要处理哪一类？"
    assert [o["value"] for o in nc["suggested_options"]] == ["contract", "expense"]
    assert [o["label"] for o in nc["suggested_options"]] == ["合同", "报销"]

    # —— Q3：resume 后不重跑已完成的工具 ——
    assert tool_hits["n"] == 1, f"resume 不得重跑已完成的工具，实际调用 {tool_hits['n']} 次"
    t2 = [t for _, t, _ in second]
    assert "run.completed" in t2, f"resume 应跑完，实际={t2}"
    assert "need_clarification" not in t2, "已回填，不应再次暂停"
    completed = next(d for _, t, d in second if t == "message.completed")
    assert completed["content"] == "已收到：合同"

    # seq 在每一段内各自单调（Java 侧按段拼接）
    assert [s for s, _, _ in first] == list(range(1, len(first) + 1))
    assert [s for s, _, _ in second] == list(range(1, len(second) + 1))
