"""回声模式端到端：流式读 /internal/v1/runs，校验事件序列与帧格式。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

RUN_ID = "run_20260906_000001"
USER_CONTEXT = {"user_id": 1, "tenant_id": 0, "username": "admin", "roles": ["ROLE_ADMIN"], "trace_id": "trace-8f3a2c"}


def post_run(payload: dict) -> list[dict]:
    """POST /internal/v1/runs，解析 SSE 帧为 [(seq, type, data)]。"""
    with client.stream("POST", "/internal/v1/runs", json=payload) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(resp.iter_text())
    return events


def parse_sse(chunks) -> list[dict]:
    """把 `id/event/data` 帧文本解析为事件列表。"""
    events: list[dict] = []
    seq = None
    etype = None
    data = None
    for chunk in chunks:
        for line in chunk.split("\n"):
            if line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                etype = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
            elif line == "" and etype is not None:
                events.append({"seq": seq, "type": etype, "data": data})
                seq, etype, data = None, None, None
    return events


def test_health():
    assert client.get("/health").json() == {"status": "UP"}


def test_echo_run_with_context():
    text = "我今天待处理的工单有哪些"
    payload = {
        "run_id": RUN_ID,
        "conversation_id": 10001,
        "text": text,
        # 显式指定 echo：单测不依赖 .env 的 MODEL_DEFAULT（本地可能配置为真实模型）
        "model_ref": "echo",
        "context": {"appCode": "ticket", "page": "ticket-list", "pageTitle": "工单列表", "filters": {"status": "OPEN"}},
        "user_context": USER_CONTEXT,
    }
    events = post_run(payload)

    types = [e["type"] for e in events]
    # 序列：run.started → message.delta×N → message.completed → run.completed
    assert types[0] == "run.started"
    assert types[-2] == "message.completed"
    assert types[-1] == "run.completed"
    deltas = [e for e in events if e["type"] == "message.delta"]
    assert len(deltas) >= 1
    assert set(types[1:-2]) == {"message.delta"}

    # seq 从 1 单调递增
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))

    # 首帧 delta 之前不插入其它事件，回显前缀合并在文本里
    assert deltas[0]["data"]["text"] == "["

    expected = f"[ticket/ticket-list] {text}"
    assert "".join(d["data"]["text"] for d in deltas) == expected

    started = events[0]["data"]
    # run.started 现携带真实模型名（前端据此显示「模型：xxx」）
    assert started == {"run_id": RUN_ID, "conversation_id": 10001,
                       "model": "echo", "gateway_key": "echo"}

    completed = events[-2]["data"]
    assert completed["content"] == expected
    assert completed["citations"] == []
    assert completed["tool_calls"] == []
    assert completed["usage"]["prompt_tokens"] == 0
    assert completed["usage"]["completion_tokens"] == len(expected)

    assert events[-1]["data"]["status"] == "SUCCEEDED"
    assert events[-1]["data"]["usage"] == completed["usage"]


def test_echo_run_without_context():
    text = "hi"
    payload = {"run_id": RUN_ID, "conversation_id": 10002, "text": text, "model_ref": "echo", "user_context": USER_CONTEXT}
    events = post_run(payload)
    deltas = [e["data"]["text"] for e in events if e["type"] == "message.delta"]
    assert "".join(deltas) == text
    assert events[-2]["data"]["content"] == text


def test_echo_run_kb_citations():
    """echo 工具链路回写 citations（FR-D5）：知识库检索结果出现在 message.completed。"""
    from unittest.mock import AsyncMock, patch

    from app.tools_client import ToolClient, ToolOutcome

    kb_rows = [{"id": 17, "docName": "差旅费管理办法（2026版）", "state": "ENABLED"}]
    payload = {
        "run_id": RUN_ID,
        "conversation_id": 10003,
        "text": "知识库 差旅费",
        "model_ref": "echo",
        "user_token": "tok",
        "user_context": USER_CONTEXT,
    }
    with patch.object(ToolClient, "list_tools",
                      AsyncMock(return_value=[{"type": "function", "function": {
                          "name": "search_kb_documents", "description": "x", "parameters": {}}}])):
        with patch.object(ToolClient, "invoke",
                          AsyncMock(return_value=ToolOutcome(name="search_kb_documents",
                                                             arguments={"keyword": "差旅费"},
                                                             ok=True, data=kb_rows))):
            events = post_run(payload)

    types = [e["type"] for e in events]
    assert "tool.call" in types and "tool.result" in types
    completed = next(e for e in events if e["type"] == "message.completed")["data"]
    assert completed["citations"] == [
        {"docId": 17, "title": "差旅费管理办法（2026版）", "source": "knowledge_base"}]
    assert completed["tool_calls"][0]["name"] == "search_kb_documents"
    assert "差旅费管理办法" in completed["content"]
