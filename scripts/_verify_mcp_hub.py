# -*- coding: utf-8 -*-
"""
验收脚本（必须真跑）：用真实 MCP 客户端连 /mcp/<code>，断言工具能被发现且 required 正确。

用法：
  D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_mcp_hub.py
前置：mcp-hub 已在 :8099 启动。
"""

import os as _os
# 本机存在 http_proxy，httpx 默认 trust_env=True 会把 127.0.0.1 也代理出去（实测表现为 502），
# 哨兵统一在进程内关掉代理，保证可复跑（不依赖外部 shell 环境）。
_os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
_os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

import asyncio
import sys

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.utils.function_calling import convert_to_openai_tool

EXPECT = {
    "qq_mail": {
        "count": 6,
        "required": {
            "list_folders": [],
            "list_messages": [],
            "read_message": ["uid"],
            "search_messages": ["query"],
            "create_draft": ["to", "subject", "body"],
            "send_draft": ["draftId", "requestId"],
        },
    },
    "wechat_work": {
        "count": 2,
        "required": {
            "check_connection": [],
            "send_text_message": ["touser", "content"],
        },
    },
}


def _core_name(name: str) -> str:
    """langchain 可能给工具名加服务器前缀（如 'qq_mail__list_folders'），这里剥掉取末尾工具名。"""
    return name.split("__")[-1].split("___")[-1]


async def main():
    client = MultiServerMCPClient(
        {
            "qq_mail": {
                "transport": "streamable_http",
                "url": "http://127.0.0.1:8099/mcp/qq_mail",
                "headers": {"Authorization": "Bearer test-token"},
            },
            "wechat_work": {
                "transport": "streamable_http",
                "url": "http://127.0.0.1:8099/mcp/wechat_work",
                "headers": {"Authorization": "Bearer test-token"},
            },
        }
    )
    tools = await client.get_tools()
    by_server = {"qq_mail": {}, "wechat_work": {}}
    for t in tools:
        core = _core_name(t.name)
        # 哪个服务器？用期望表反查；若重名属于某服务器则归属
        for srv, exp in EXPECT.items():
            if core in exp["required"]:
                by_server[srv][core] = t
                break
        else:
            print(f"[warn] 工具 {t.name!r} 无法归类（core={core!r}）")

    ok = True
    for srv, exp in EXPECT.items():
        got = by_server[srv]
        got_count = len(got)
        got_names = set(got.keys())
        exp_names = set(exp["required"].keys())
        print(f"\n=== {srv} ===")
        print(f"  工具数: 实际 {got_count} / 期望 {exp['count']} "
              f"{'OK' if got_count == exp['count'] else 'FAIL'}")
        if got_count != exp["count"]:
            ok = False
        print(f"  名字集合: 实际 {sorted(got_names)} / 期望 {sorted(exp_names)} "
              f"{'OK' if got_names == exp_names else 'FAIL'}")
        if got_names != exp_names:
            ok = False
        for tool_name, exp_req in exp["required"].items():
            t = got.get(tool_name)
            if t is None:
                print(f"  [FAIL] 缺少工具 {tool_name}")
                ok = False
                continue
            oa = convert_to_openai_tool(t)
            params = oa["function"]["parameters"]
            req = params.get("required") or []
            status = "OK" if set(req) == set(exp_req) else "FAIL"
            if status == "FAIL":
                ok = False
            print(f"  {tool_name}: required={req} 期望={exp_req} {status}")

    print("\n" + ("全部断言通过 ✅" if ok else "存在失败断言 ❌"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
