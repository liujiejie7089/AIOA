# -*- coding: utf-8 -*-
"""走标准 MCP Streamable HTTP 协议验证 /mcp/scfy：initialize -> initialized -> tools/list -> tools/call。

按租户接入后（docs/92 阶段 4），hub 的 tools/call 会回调 Java 校验调用者身份：
  - 纯协议验证：hub 以 AIOS_SCFY_ACCESS_CHECK=0 启动（无租户闸门），本脚本直接跑；
  - 端到端验证：设 AIOS_TEST_TOKEN=<登录 JWT>，脚本把 token 放进每个 /mcp/scfy 请求，
    tools/call 必须真有数据（已接入租户）。未带 token 而 hub 又开启校验时，tools/call
    会如实 FAIL 并给出「缺少调用身份」—— 这是正确的安全行为，不放宽断言。
"""
import asyncio
import json
import os
import pathlib

import httpx

from mcp_hub.scfy import catalog

URL = "http://127.0.0.1:8099/mcp/scfy"
EXPECTED_TOOLS = catalog.tool_count()
_LINES = []
_FAILS = []


def check(name, cond, detail=""):
    line = ("PASS" if cond else "FAIL") + " " + name + " " + str(detail)[:200]
    _LINES.append(line)
    print(line)
    if not cond:
        _FAILS.append(name)


def _parse_sse(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return json.loads(text)


async def _rpc(client: httpx.AsyncClient, msg_id: int, method: str,
               params: dict | None, session: str | None):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    # 端到端验收：把调用者 JWT 透传给 hub，由它回调 Java 做按租户准入判定。
    # 未设置时保持纯协议验证（需 hub 侧关闭准入校验）。
    token = os.environ.get("AIOS_TEST_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    resp = await client.post(URL, json=body, headers=headers)
    return resp.status_code, _parse_sse(resp.text), resp


async def main():
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        status, init, r = await _rpc(client, 1, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "verify", "version": "1.0"},
        }, None)
        check("initialize http 200", status == 200, status)
        check("initialize has result", "result" in init, list(init.keys()))
        session = r.headers.get("mcp-session-id")
        check("session id issued", bool(session), session)

        # notifications/initialized 是通知（无 id）
        await _rpc(client, 0, "notifications/initialized", {}, session)

        status, tl, _ = await _rpc(client, 2, "tools/list", {}, session)
        tools = tl.get("result", {}).get("tools", [])
        check("tools/list http 200", status == 200, status)
        check("tools/list == catalog", len(tools) == EXPECTED_TOOLS,
              f"protocol={len(tools)} catalog={EXPECTED_TOOLS}")
        names = {t["name"] for t in tools}
        check("scfy tools present", {
            "project_type_data", "project_count_by_area",
            "project_inheritor_count_by_area", "heritage_activity_years",
            "image_category_stats", "opinion_top_keywords", "health_base_list",
        } <= names, sorted(names)[-7:])
        pc = next((t for t in tools if t["name"] == "project_count_by_area"), {})
        req = pc.get("inputSchema", {}).get("required", [])
        check("required schema via protocol", "area" in req, req)
        ann = pc.get("annotations", {})
        check("tools read-only hint", (ann.get("readOnlyHint") or ann.get("read_only_hint")) is True, ann)

        status, cr, _ = await _rpc(client, 3, "tools/call", {
            "name": "project_count_by_area", "arguments": {"area": "甘孜州"}
        }, session)
        check("tools/call http 200", status == 200, status)
        content = cr.get("result", {}).get("content", [])
        text = content[0].get("text", "{}") if content else "{}"
        payload = json.loads(text)
        check("tools/call ok=true", payload.get("ok") is True, payload)
        check("tools/call real data", bool(payload.get("data")), str(payload.get("data"))[:150])
        check("tools/call not error", cr.get("result", {}).get("isError") is not True)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_protocol_result.txt")
    pathlib.Path(out).write_text("\n".join(_LINES) + "\nRESULT: " +
                                 ("ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS)),
                                 encoding="utf-8")
    print("RESULT:", "ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
