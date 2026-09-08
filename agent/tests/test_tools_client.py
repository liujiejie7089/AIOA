"""业务工具网关客户端（tools_client）契约测试。

覆盖：
  - enabled：无 user_token 时工具不可用
  - list_tools：清单拉取 / 非 200 / 网络异常均收敛为 []
  - invoke：ok 提取、非 200、网关返回 ok=false、网络异常收敛 ok=False

注意：agent_runtime 与本模块引用同一个 httpx 模块单例；本文件内 patch 时
必须用 "app.tools_client.httpx.AsyncClient"，且不要与 agent_runtime 的
patch 叠加在同一个 with 块里。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools_client import ToolClient


def _resp(status: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    return resp


def _mock_http(post=None, get=None) -> MagicMock:
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    if post is not None:
        http.post = post
    if get is not None:
        http.get = get
    return http


def test_disabled_without_token():
    client = ToolClient.from_request(None)
    assert client.enabled is False
    assert asyncio.run(client.list_tools()) == []
    outcome = asyncio.run(client.invoke("list_my_approvals", {}))
    assert outcome.ok is False
    assert "缺少用户凭证" in (outcome.error or "")


def test_list_tools_ok():
    http = _mock_http(get=AsyncMock(return_value=_resp(200, {"code": 0, "data": [
        {"type": "function", "function": {"name": "list_my_approvals"}}]})))
    client = ToolClient("http://x", "tok")
    with patch("app.tools_client.httpx.AsyncClient", return_value=http):
        tools = asyncio.run(client.list_tools())
    assert [t["function"]["name"] for t in tools] == ["list_my_approvals"]


def test_list_tools_failure_returns_empty():
    # 非 200
    http = _mock_http(get=AsyncMock(return_value=_resp(500, {"message": "boom"})))
    client = ToolClient("http://x", "tok")
    with patch("app.tools_client.httpx.AsyncClient", return_value=http):
        assert asyncio.run(client.list_tools()) == []
    # 网络异常
    http2 = _mock_http(get=AsyncMock(side_effect=ConnectionError("refused")))
    with patch("app.tools_client.httpx.AsyncClient", return_value=http2):
        assert asyncio.run(client.list_tools()) == []


def test_invoke_ok():
    http = _mock_http(post=AsyncMock(return_value=_resp(
        200, {"code": 0, "data": {"ok": True, "data": [{"id": 1}]}})))
    client = ToolClient("http://x", "tok")
    with patch("app.tools_client.httpx.AsyncClient", return_value=http):
        outcome = asyncio.run(client.invoke("list_my_approvals", {}))
    assert outcome.ok is True
    assert outcome.data == [{"id": 1}]
    # 鉴权头透传用户 token
    _, kwargs = http.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_invoke_gateway_rejected():
    http = _mock_http(post=AsyncMock(return_value=_resp(
        200, {"code": 0, "data": {"ok": False, "error": "无权限"}})))
    client = ToolClient("http://x", "tok")
    with patch("app.tools_client.httpx.AsyncClient", return_value=http):
        outcome = asyncio.run(client.invoke("list_todo_approvals", {}))
    assert outcome.ok is False
    assert "无权限" in (outcome.error or "")


def test_invoke_http_error_and_exception():
    http = _mock_http(post=AsyncMock(return_value=_resp(401, {"message": "unauthorized"})))
    client = ToolClient("http://x", "tok")
    with patch("app.tools_client.httpx.AsyncClient", return_value=http):
        outcome = asyncio.run(client.invoke("list_my_approvals", {}))
    assert outcome.ok is False
    assert "HTTP 401" in (outcome.error or "")

    http2 = _mock_http(post=AsyncMock(side_effect=TimeoutError("timeout")))
    with patch("app.tools_client.httpx.AsyncClient", return_value=http2):
        outcome2 = asyncio.run(client.invoke("list_my_approvals", {}))
    assert outcome2.ok is False
    assert "timeout" in (outcome2.error or "")
