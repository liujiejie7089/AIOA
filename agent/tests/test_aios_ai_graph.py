"""LangGraph 图运行时（``aios_ai.graph``）冒烟测试。

不连真实模型：把 provider 解析与上游 HTTP 全部打桩，验证重建后的图产出的事件序列
与重建前契约一致：

    run.started → [tool.call → tool.result] → message.delta×N
                → message.completed → run.completed

（seq 从 1 单调递增；这是 Java / H5 唯一依赖的对外契约，必须逐项验到。）
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from aios_ai.contracts import RunRequest, UserContext
from aios_ai.llm import Provider
from aios_ai.tools.client import ToolClient, ToolOutcome

FAKE = Provider(key="fake", driver="openai_compatible", base_url="http://fake.invalid",
                model="fake-1", api_key_env="AIOS_TEST_FAKE_KEY")


def _req(text: str = "你好", **kw) -> RunRequest:
    return RunRequest(run_id="run_test_0001", conversation_id=1, text=text,
                      model_ref="fake",
                      user_context=UserContext(user_id=1, tenant_id=1), **kw)


async def _collect(req: RunRequest) -> list[tuple[int, str, dict]]:
    from aios_ai import entry

    out: list[tuple[int, str, dict]] = []
    async for event in entry.run(req):
        out.append((event.seq, event.type, event.data))
    return out


def _stub(resolve_patches, stream_stub, *extra):
    """把「分派解析 + 图内解析 + 上游调用」一起打桩，返回 contexts 列表。"""
    return [
        patch("aios_ai.entry.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes.gateway.resolve", return_value=FAKE),
        patch("aios_ai.graph.nodes._post_stream", stream_stub),
    ] + list(extra)


def test_graph_streams_message(monkeypatch):
    """纯推理（无工具）：run.started → message.delta×2 → message.completed → run.completed。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        for piece in ("你", "好"):
            yield ("delta", piece)
        yield ("done", {"role": "assistant", "content": "你好"},
               {"prompt_tokens": 3, "completion_tokens": 2})

    ctx = _stub(None, fake_stream)
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req()))
    finally:
        for c in ctx:
            c.stop()

    types = [t for _, t, _ in events]
    assert types[0] == "run.started"
    assert types[-2:] == ["message.completed", "run.completed"]
    assert set(types[1:-2]) == {"message.delta"}
    assert [s for s, _, _ in events] == list(range(1, len(events) + 1))

    deltas = "".join(d["text"] for _, t, d in events if t == "message.delta")
    assert deltas == "你好"

    completed = next(d for _, t, d in events if t == "message.completed")
    assert completed["content"] == "你好"
    assert completed["citations"] == []
    assert completed["tool_calls"] == []
    assert completed["usage"] == {"prompt_tokens": 3, "completion_tokens": 2}
    assert events[0][2]["model"] == "fake-1" and events[0][2]["gateway_key"] == "fake"


def test_graph_tool_round(monkeypatch):
    """带一轮工具调用：message.delta 之前先出 tool.call / tool.result，且结果回注上下文。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")

    calls = {"n": 0}
    seen_messages: list[list[dict]] = []

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen_messages.append(list(messages))
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一轮：模型决定调工具（不带正文）
            yield ("done", {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "get_my_quota", "arguments": "{}"}}]},
                {"prompt_tokens": 5, "completion_tokens": 1})
        else:
            # 第二轮：依据回注的工具结果作答
            for piece in ("剩余", "10"):
                yield ("delta", piece)
            yield ("done", {"role": "assistant", "content": "剩余10"},
                   {"prompt_tokens": 8, "completion_tokens": 2})

    ctx = _stub(
        None, fake_stream,
        patch.object(ToolClient, "list_tools", AsyncMock(return_value=[
            {"type": "function", "function": {"name": "get_my_quota",
                                              "description": "q", "parameters": {}}}])),
        patch.object(ToolClient, "invoke", AsyncMock(return_value=ToolOutcome(
            name="get_my_quota", arguments={}, ok=True,
            data={"quota": 100, "used": 90, "left": 10}))),
    )
    for c in ctx:
        c.start()
    try:
        events = asyncio.run(_collect(_req(text="我还有多少额度", user_token="tok")))
    finally:
        for c in ctx:
            c.stop()

    types = [t for _, t, _ in events]
    assert types[0] == "run.started"
    assert types.count("tool.call") == 1 and types.count("tool.result") == 1
    # 工具事件必须早于正文分片
    assert types.index("tool.call") < types.index("message.delta")
    assert types[-2:] == ["message.completed", "run.completed"]
    assert [s for s, _, _ in events] == list(range(1, len(events) + 1))

    completed = next(d for _, t, d in events if t == "message.completed")
    assert completed["content"] == "剩余10"
    assert completed["tool_calls"] == [{"name": "get_my_quota", "arguments": {}, "ok": True}]
    assert completed["usage"] == {"prompt_tokens": 13, "completion_tokens": 3}

    # 第二轮模型调用必须能看到回注的工具结果（role=tool）
    assert calls["n"] == 2
    second = seen_messages[1]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in second)


# ---- 「请假」动作意图 ⇒ 本轮不向模型暴露写工具（确定性闸门，docs/51 §1.4 / 铁律 1）----
#
# 为什么必须有这道闸门：提示词只是**软**约束，模型可以不遵守；同一类缺陷（动作被抢先落库）
# 已实测复现两次（CREATE_WORKER、APPLY_LEAVE）。判据回到**事实源头** —— 直接观察模型实际收到的
# tools 列表，而不是读提示词文本；删掉 nodes.prepare 里的 filter_intent_write_tools 调用，下面第一个用例立刻变红。

APPLY_DEF = {"type": "function", "function": {"name": "apply_permission",
                                              "description": "p", "parameters": {}}}
QUOTA_DEF = {"type": "function", "function": {"name": "get_my_quota",
                                              "description": "q", "parameters": {}}}


def _names(tools: list[dict]) -> list[str]:
    return [(t.get("function", {}).get("name") or t.get("name")) for t in tools]


def _seen_tools_for(text: str) -> list[dict]:
    """跑一遍图，返回模型实际收到的 tools（打桩 list_tools，不连模型/网络）。"""
    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        yield ("delta", "ok")
        yield ("done", {"role": "assistant", "content": "ok"}, {})

    seen: list[list[dict]] = []

    async def spy_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen.append(list(tools or []))
        async for item in fake_stream(http, provider, api_key, messages, tools, temperature):
            yield item

    ctx = _stub(None, spy_stream,
                patch.object(ToolClient, "list_tools",
                             AsyncMock(return_value=[APPLY_DEF, QUOTA_DEF])))
    for c in ctx:
        c.start()
    try:
        asyncio.run(_collect(_req(text=text, user_token="tok")))
    finally:
        for c in ctx:
            c.stop()
    return seen[0]


def test_leave_intent_hides_permission_write_tool(monkeypatch):
    """「我要请假两天」判为 APPLY_LEAVE ⇒ apply_permission 不出现在本轮工具表里。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    names = _names(_seen_tools_for("我要请假两天"))
    assert "apply_permission" not in names, names
    assert "get_my_quota" in names, names  # 非写工具不得被误伤


def test_create_worker_intent_hides_permission_write_tool(monkeypatch):
    """同类缺陷的第二例（D3）：「创建一个数字人」判为 CREATE_WORKER ⇒ 同样不得暴露写工具。

    这条钉的是**泛化**：闸门不是只为请假开的特例，而是「凡是界面拥有确认入口的动作」。
    """
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    names = _names(_seen_tools_for("帮我创建一个数字人"))
    assert "apply_permission" not in names, names


def test_upload_intent_hides_permission_write_tool(monkeypatch):
    """第三个 UI 拥有型动作（UPLOAD_FILE）同样收敛，证明规则是普适的而非枚举巧合。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    names = _names(_seen_tools_for("我要上传文件"))
    assert "apply_permission" not in names, names


def test_explicit_permission_apply_keeps_write_tool(monkeypatch):
    """负向对照（V36 不被拔掉）：显式「申请权限」诉求**不判任何动作** ⇒ 工具照常暴露。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    names = _names(_seen_tools_for("请直接调用工具帮我提交 approval:leave 权限申请"))
    assert "apply_permission" in names, names


def test_no_intent_keeps_write_tool(monkeypatch):
    """负向对照：普通对话（action=None）⇒ 工具表原样返回，零回归。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    names = _names(_seen_tools_for("你好"))
    assert "apply_permission" in names and "get_my_quota" in names, names


def test_filter_intent_write_tools_pure():
    """纯函数面：有动作意图才剔除；两种 schema 形态都要认；无动作原样返回。"""
    from aios_ai.graph.nodes import filter_intent_write_tools as f

    src = [APPLY_DEF, QUOTA_DEF]
    for act in ("APPLY_LEAVE", "CREATE_WORKER", "UPLOAD_FILE", "REPORT_EXPENSE"):
        assert _names(f(src, act)) == ["get_my_quota"], act
    # 无动作 ⇒ 原样返回（同一对象，零回归）
    assert f(src, None) is src
    # 扁平 schema（无 function 包装）同样要能剔除
    assert _names(f([{"name": "apply_permission"}, QUOTA_DEF], "APPLY_LEAVE")) == ["get_my_quota"]


def _kb_case(monkeypatch, list_impl, kb_on=None):
    """跑一次带 user_token 的对话，返回 (system 文本, 事件类型列表)。"""
    monkeypatch.setenv("AIOS_TEST_FAKE_KEY", "k")
    seen = {}

    async def fake_stream(http, provider, api_key, messages, tools, temperature=0.3):
        seen["sys"] = messages[0].get("content") or ""
        yield ("done", {"role": "assistant", "content": "好"},
               {"prompt_tokens": 3, "completion_tokens": 1})

    ctx = _stub(None, fake_stream, patch.object(ToolClient, "list_tools", list_impl))
    for c in ctx:
        c.start()
    try:
        kw = {"user_token": "tok"}
        if kb_on is not None:
            kw["kb_on"] = kb_on
        events = asyncio.run(_collect(_req("报销制度是什么", **kw)))
    finally:
        for c in ctx:
            c.stop()
    return seen.get("sys", ""), [t for _, t, _ in events]


def test_kb_degraded_note_when_tool_list_fails(monkeypatch):
    """工具清单拉取失败 ⇒ 必须在 system 里显式声明知识库不可用。

    回归的静默缺陷：``list_tools()`` 吞掉异常返回 []，与「用户确实没有工具」不可区分
    ⇒ ``has_kb_tool([])`` 为假 ⇒ 预检索不跑、run 照样 SUCCESS，日志只有一行 warning。
    """
    async def failing(self):
        self.list_error = "status=503"
        return []

    sys_text, types = _kb_case(monkeypatch, failing)
    assert "本轮知识库不可用" in sys_text, f"应显式降级，实际 system={sys_text[:200]}"
    assert "message.completed" in types, f"降级不应把整轮打死，实际={types}"


def test_no_kb_degraded_note_when_gateway_returns_empty(monkeypatch):
    """负向对照：网关正常但该用户真的没有工具（200+空数组）⇒ **不得**报降级。"""
    async def empty(self):
        self.list_error = None
        return []

    sys_text, _ = _kb_case(monkeypatch, empty)
    assert "本轮知识库不可用" not in sys_text, "「确实没有工具」不是故障，不该声明降级"


def test_no_kb_degraded_note_when_kb_off(monkeypatch):
    """用户主动关掉知识库（kb_on=False）⇒ 即使网关失败也不该声明降级（本轮本来就不查）。"""
    async def failing(self):
        self.list_error = "status=503"
        return []

    sys_text, _ = _kb_case(monkeypatch, failing, kb_on=False)
    assert "本轮知识库不可用" not in sys_text
