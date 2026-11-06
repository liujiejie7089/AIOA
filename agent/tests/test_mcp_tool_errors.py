"""MCP 工具「失败必须报失败」的定点验收（2026-11-06）。

背景（用户报的 A1，最高优先）：连接器工具真正执行失败时，agent 曾把 ``ok=true`` 交给模型，
错误文本被当成成功内容吞掉。根因是 ``langchain-mcp-adapters`` 的两层语义：

  ① 默认 ``handle_tool_errors=True`` 时，``CallToolResult(isError=True)`` **不抛异常**，
     而是被包成 ``ToolMessage(status="error")`` 返回；
  ② 我们原来的结果归一分支只认 ``list[dict]``（content blocks），
     ``ToolMessage`` 直接落进最后那个 ``return ok=True``。

于是「MCP 说错了」⇒「agent 说成了」。本用例锁三件事：
  · 构造 ``MultiServerMCPClient`` 必须显式传 ``handle_tool_errors=False``（让失败抛出来）；
  · 万一适配器版本回退成返回 ``ToolMessage(status="error")``，也必须判失败（双保险）；
  · 成功路径一个字都不能变（``str`` / content blocks / 前缀启发式都要保持原语义）。

判据来源：被测对象是 ``ToolClient.invoke`` 本身，不是我们另写的一份「预期」——
每条都断言返回的 ``ToolOutcome.ok``，与 agent 据此拼给模型的 tool 消息一一对应。
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from aios_ai.config import settings
from aios_ai.tools.client import ToolClient


class _RaisingTool:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def ainvoke(self, _args):        # noqa: D401 —— 与 BaseTool 同签名
        raise self._exc


class _ReturningTool:
    def __init__(self, value) -> None:
        self._value = value

    async def ainvoke(self, _args):
        return self._value


def _client_with(tool_obj) -> ToolClient:
    c = ToolClient("http://x", "tok")
    c._mcp_tools["mcp__wecom_cli__whoami"] = (tool_obj, "whoami")
    return c


def _invoke(tool_obj):
    return asyncio.run(_client_with(tool_obj).invoke("mcp__wecom_cli__whoami", {}))


# --------------------------------------------------------------- 构造参数（根因）
def test_mcp_client_built_with_handle_tool_errors_false():
    """第一道闸：必须让失败抛出来，而不是被适配器折成 ToolMessage。"""
    captured: dict = {}

    class _FakeMCPClient:
        def __init__(self, connections, **kwargs):
            captured.update(kwargs)
            self._connections = connections

        async def get_tools(self):
            return []

    c = ToolClient("http://x", "tok", mcp_manifest=[{"code": "wecom_cli", "url": "http://h/mcp"}])
    with patch.object(settings, "mcp_hub_enabled", True), \
            patch("aios_ai.tools.client.MultiServerMCPClient", _FakeMCPClient):
        asyncio.run(c.list_mcp_tools())

    assert captured.get("handle_tool_errors") is False, (
        "构造 MultiServerMCPClient 必须显式 handle_tool_errors=False；"
        f"实际 kwargs={captured}"
    )


# --------------------------------------------------------------- 失败路径
def test_tool_exception_is_reported_as_failure():
    out = _invoke(_RaisingTool(ToolException("Error executing tool whoami: 凭证已失效")))
    assert out.ok is False
    assert "凭证已失效" in (out.error or "")


def test_tool_message_error_status_is_reported_as_failure():
    """适配器把错误折成 ToolMessage 时（旧/新版本都可能），同样必须判失败。"""
    out = _invoke(_ReturningTool(ToolMessage(
        content="Error executing tool whoami: 无权限", status="error", tool_call_id="call_1")))
    assert out.ok is False
    assert "无权限" in (out.error or "")


def test_error_prefix_block_is_reported_as_failure():
    """content blocks 形态里 isError 被适配器丢掉时，靠 FastMCP 固定前缀兜底。"""
    out = _invoke(_ReturningTool([{"type": "text", "text": "Error executing tool whoami: boom"}]))
    assert out.ok is False
    assert "boom" in (out.error or "")


def test_explicit_is_error_flag_is_reported_as_failure():
    out = _invoke(_ReturningTool([{"type": "text", "text": "anything", "isError": True}]))
    assert out.ok is False


# --------------------------------------------------------------- 成功路径（零回归）
def test_plain_string_stays_success():
    out = _invoke(_ReturningTool("企业微信：我是谁 → 张三"))
    assert out.ok is True and out.error is None
    assert out.data == "企业微信：我是谁 → 张三"


def test_text_blocks_stay_success():
    out = _invoke(_ReturningTool([{"type": "text", "text": "第一段"},
                                  {"type": "text", "text": "第二段"}]))
    assert out.ok is True
    assert out.data == "第一段\n第二段"


def test_unknown_tool_still_fails_loudly():
    """找不到映射是负向判据：必须显式报错，不能回落到 Java 网关。"""
    out = asyncio.run(ToolClient("http://x", "tok").invoke("mcp__nope__missing", {}))
    assert out.ok is False
    assert "不存在" in (out.error or "")
