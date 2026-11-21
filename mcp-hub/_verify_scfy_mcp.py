# -*- coding: utf-8 -*-
"""验证 scfy MCP 连接器：注册 -> 工具清单 -> 真实 tools/call -> 配置数据源数据。

默认打官网域名（与生产一致）；可用 AIOS_SCFY_BASE_URL 覆盖为本机 16060 排障。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AIOS_SCFY_BASE_URL", "https://szbhpt.tsichuan.com/scfy")
# 纯 hub 进程内验证：没有 Java 回调端点、也没有用户 token，跳过按租户接入准入校验。
# 端到端（含租户闸门）的验收另见 _verify_scfy_tenant_access.py / docs/92 A1~A12。
os.environ.setdefault("AIOS_SCFY_ACCESS_CHECK", "0")

from mcp_hub import builtin
from mcp_hub.connectors import registry
from mcp_hub.scfy import catalog

EXPECTED_TOOLS = catalog.tool_count()

FAILS = []
_LINES = []


def check(name, cond, detail=""):
    line = ("PASS" if cond else "FAIL") + " " + name + " " + str(detail)
    _LINES.append(line)
    print(line)
    if not cond:
        FAILS.append(name)


async def main():
    codes = registry.codes()
    check("scfy registered", "scfy" in codes, str(codes))
    mf = registry.get("scfy")
    check("tool count == catalog", mf.tool_count == EXPECTED_TOOLS,
          f"manifest={mf.tool_count} catalog={EXPECTED_TOOLS}")

    server = builtin.SERVERS.get("scfy")
    check("server built", server is not None)

    tools = await server.list_tools()
    check("list_tools == catalog", len(tools) == EXPECTED_TOOLS, str(len(tools)))
    by_name = {t.name: t for t in tools}
    check("new public tools present", {
        "project_inheritor_count_by_area", "heritage_activity_years",
        "image_category_stats", "opinion_top_keywords", "health_base_list",
    } <= set(by_name), sorted(by_name)[-5:])

    # 必填 schema 校验：count_by_area 的 area 必填
    t = by_name.get("project_count_by_area")
    check("required schema carried", t is not None and "area" in (t.inputSchema.get("required") or []),
          str(t.inputSchema.get("required")) if t else "no tool")

    # 真实调用 1：项目数量（无参）
    r = await server.call_tool("project_type_data", {"level": "country"})
    data = _unwrap(r)
    check("call project_type_data ok", isinstance(data, dict) and data.get("ok") is True, str(data)[:160])
    check("call returns real data", bool(data.get("data")), str(data.get("data"))[:120])

    # 真实调用 2：传承人门类（必填 level）
    r2 = await server.call_tool("inheritor_type_data", {"level": "country"})
    d2 = _unwrap(r2)
    check("call inheritor_type_data ok", isinstance(d2, dict) and d2.get("ok") is True, str(d2)[:160])

    # 真实调用 3：市州简称
    r3 = await server.call_tool("project_count_by_area", {"area": "甘孜州"})
    d3 = _unwrap(r3)
    check("call area short name ok", isinstance(d3, dict) and d3.get("ok") is True, str(d3)[:160])

    # 真实调用 4：本轮新增的公网接口（文化遗产日年份列表）
    r4 = await server.call_tool("heritage_activity_years", {"topNum": 5})
    d4 = _unwrap(r4)
    check("call new public tool ok", isinstance(d4, dict) and d4.get("ok") is True, str(d4)[:160])
    check("new public tool real data", bool(d4.get("data")), str(d4.get("data"))[:120])

    # 负向：上游业务错误不应伪装成功（传不存在的 level 让上游返回非 0 或空，这里只断言结构完整）
    check("all calls carry source", all(isinstance(x, dict) and x.get("source") == "scfy"
                                        for x in (data, d2, d3, d4)))

    result = "\nRESULT: " + ("ALL PASS" if not FAILS else ("FAIL " + ",".join(FAILS)))
    _LINES.append(result)
    print(result)
    import pathlib
    pathlib.Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_result.txt")).write_text(
        "\n".join(_LINES), encoding="utf-8")
    return 1 if FAILS else 0


def _unwrap(result):
    """call_tool 在不同 mcp 版本返回 CallToolResult 或 list[TextContent]，都取第一个 text 的 JSON。"""
    import json
    content = result if isinstance(result, list) else getattr(result, "content", [])
    for c in content:
        text = getattr(c, "text", None)
        if text:
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text[:200]}
    return {}


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
