# -*- coding: utf-8 -*-
"""全量实测 scfy MCP 工具目录：逐个真实调用 -> JSON -> HTML 报告 -> 截图。

为什么要有这条：69 个工具里多数是详情/统计接口，单测只能证明“工具在册”，
证明不了“公网点下去真有数据”。本脚本按 catalog.json 全量调用，先用列表接口
发现真实 id，再逐个请求；参数错配导致的空集不会被伪装成通过（EMPTY 单列）。

用法（agent venv 已装 playwright + Edge）：
    agent/.venv/Scripts/python.exe mcp-hub/_verify_scfy_all_tools.py
产物：
    docs/scfy-mcp-all-tools-test-2026-11-20.json
    docs/screenshots/scfy-all-interfaces-2026-11-20/report.html
    docs/screenshots/scfy-all-interfaces-2026-11-20/01-overview.png
    docs/screenshots/scfy-all-interfaces-2026-11-20/02-<group>.png ...
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AIOS_SCFY_BASE_URL", "https://szbhpt.tsichuan.com/scfy")
# 全量 69 接口连通性测试只验证「上游 /show/* 有没有数据」，不测租户闸门；
# 进程内没有 Java 回调端点与用户 token，故跳过按租户接入准入校验。
os.environ.setdefault("AIOS_SCFY_ACCESS_CHECK", "0")

from mcp_hub import builtin
from mcp_hub.scfy import catalog

ROOT = Path(__file__).resolve().parent.parent
JSON_OUT = ROOT / "docs" / "scfy-mcp-all-tools-test-2026-11-20.json"
SHOT_DIR = ROOT / "docs" / "screenshots" / "scfy-all-interfaces-2026-11-20"
HTML_OUT = SHOT_DIR / "report.html"

# 官网有行为风控；逐个请求之间留间隔，避免高频探测触发 403。
REQUEST_DELAY = 0.35

# 详情类工具必须先用列表接口拿到真实 id，否则上游会返回空对象且 code=0。
SPECIAL_ARGS: dict[str, dict[str, str]] = {
    "inheritor_detail": {"id": "INH_ID"},
    "inheritor_video": {"inheritorId": "INH_ID"},
    "project_detail": {"id": "PROJ_ID"},
    "project_video": {"projectBaseId": "PROJ_ID"},
    "shop_detail": {"id": "SHOP_ID"},
    "shop_inheritor": {"id": "SHOP_ID"},
    "shop_sales": {"id": "SHOP_ID"},
    "shop_project_type_pie": {"id": "SHOP_ID"},
    "shop_sales_num_pie": {"id": "SHOP_ID"},
    "eco_city_round": {"ecologicalAreaId": "ECO_ID"},
    "eco_road_data": {"ecologicalAreaId": "ECO_ID", "areaId": "CITY_CODE"},
    "eco_road_distribute": {"ecologicalAreaId": "ECO_ID", "areaId": "CITY_CODE"},
    "eco_all_image": {"ecologicalAreaId": "ECO_ID"},
    "travel_city_round": {"travelId": "TRAVEL_ID"},
    "travel_road_type_count": {"travelId": "TRAVEL_ID"},
    "travel_road_by_type": {"travelId": "TRAVEL_ID"},
    "travel_road_data": {"travelId": "TRAVEL_ID", "areaId": "CITY_CODE"},
    "travel_road_distribute": {"travelId": "TRAVEL_ID"},
    "travel_image": {"travelId": "TRAVEL_ID"},
    "travel_all_image": {"travelId": "TRAVEL_ID"},
    "travel_road_detail": {"dataId": "ROAD_DATA_ID"},
}


def unwrap(result) -> dict:
    content = result if isinstance(result, list) else getattr(result, "content", [])
    for c in content:
        text = getattr(c, "text", None)
        if text:
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text[:300]}
    return {}


async def call(server, name: str, args: dict | None = None) -> dict:
    result = await server.call_tool(name, args or {})
    return unwrap(result)


def dig(payload: dict, *path: str) -> str | None:
    node = payload.get("data") if isinstance(payload, dict) else None
    for key in path:
        if isinstance(node, list) and node:
            node = node[0]
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    if isinstance(node, list) and node:
        node = node[0]
    if isinstance(node, dict):
        for k in ("id", "project_base_id", "travel_id", "ecologicalarea_id",
                  "city_code", "area_id", "code"):
            if node.get(k):
                return str(node[k])
    return str(node) if node else None


async def discover(server) -> dict[str, str]:
    found: dict[str, str] = {}
    steps = [
        ("INH_ID", "inheritor_list_by_area", {"area": "成都市", "pageSize": 5}, ("dataList", "id")),
        ("PROJ_ID", "project_list_by_area", {"pageSize": 5}, ("dataList", "project_base_id")),
        ("SHOP_ID", "shop_table", {"cityName": "成都市"}, ("list", "id")),
        ("TRAVEL_ID", "travel_route_top_list", {"topNum": 10}, ("routesTopFewList", "travel_id")),
        ("ECO_ID", "eco_area_top_list", {"topNum": 10}, ("areasTopFewList", "ecologicalarea_id")),
        ("CITY_CODE", "travel_nmch_base", {}, ("nmchBaseDataList", "city_code")),
        ("COUNTY_CODE", "eco_tourist_county_list", {}, ("touristCounty", "id")),
    ]
    for key, tool, args, path in steps:
        try:
            payload = await call(server, tool, args)
            value = dig(payload, *path)
            if value:
                found[key] = value
            await asyncio.sleep(REQUEST_DELAY)
        except Exception as exc:  # 发现失败不能中断全量测试
            found[key + "_ERROR"] = str(exc)[:120]
    if found.get("TRAVEL_ID"):
        try:
            payload = await call(server, "travel_road_by_type",
                                 {"type": "1", "travelId": found["TRAVEL_ID"]})
            value = dig(payload, "dataList", "project_base_id")
            if value:
                found["ROAD_DATA_ID"] = value
            await asyncio.sleep(REQUEST_DELAY)
        except Exception as exc:
            found["ROAD_DATA_ID_ERROR"] = str(exc)[:120]
    return found


def build_args(tool: dict, ids: dict[str, str]) -> dict:
    props = tool["inputSchema"].get("properties") or {}
    special = SPECIAL_ARGS.get(tool["id"], {})
    out: dict = {}
    for name, spec in props.items():
        desc = str(spec.get("description") or "")
        example_match = re.search(r"示例：([^）]+)", desc)
        example = example_match.group(1).strip() if example_match else None
        if name in special:
            value = ids.get(special[name]) or example
        elif name == "area":
            value = "510525000000" if "12 位" in desc else "成都市"
        elif name == "cityName":
            value = "成都市"
        elif name == "cityCode":
            value = "510100000000"
        elif name == "areaId":
            value = "510100000000"
        elif name == "areaName":
            value = "锦江区"
        elif name == "name":
            value = "泸州市" if tool["id"] == "project_inheritor_count_by_area" else "四川省"
        elif name == "level":
            value = "country"
        elif name == "imageType":
            value = "1"
        elif name == "showUser":
            value = "false"
        elif name == "provinceName":
            value = "四川省"
        elif name == "year":
            value = "2023"
        elif name == "reportPeriod":
            value = "2024"
        elif name == "startDate":
            value = "2024-01-01"
        elif name == "endDate":
            value = "2024-12-31"
        elif name == "nearDays":
            value = "30"
        elif name in ("pageNum", "pageSize", "topNum", "limitNum"):
            value = example or "5"
        elif name == "type":
            value = "1"
        else:
            value = example or "1"
        if value is not None and str(value) != "":
            out[name] = value
    return out


def summarize(data) -> str:
    if isinstance(data, dict):
        parts = []
        for k, v in list(data.items())[:6]:
            if isinstance(v, list):
                parts.append(f"{k}:{len(v)}条")
            elif isinstance(v, dict):
                parts.append(f"{k}:{len(v)}键")
            else:
                parts.append(f"{k}={str(v)[:24]}")
        return "；".join(parts)
    if isinstance(data, list):
        return f"列表 {len(data)} 条"
    return str(data)[:120] if data else "空"


def data_size(data) -> int:
    if isinstance(data, (list, dict)):
        return len(data)
    return len(str(data)) if data else 0


async def main() -> int:
    server = builtin.SERVERS.get("scfy")
    if server is None:
        print("FATAL: hub 中未找到 scfy server（先启动 hub）")
        return 2
    ids = await discover(server)
    print("DISCOVERED", json.dumps(ids, ensure_ascii=False))

    rows = []
    started = time.monotonic()
    for tool in catalog.TOOLS:
        args = build_args(tool, ids)
        t0 = time.monotonic()
        try:
            payload = await call(server, tool["id"], args)
        except Exception as exc:
            payload = {"ok": False, "errors": "调用异常：" + str(exc)[:200]}
        elapsed = int((time.monotonic() - t0) * 1000)
        ok = payload.get("ok") is True
        data = payload.get("data")
        status = "PASS" if ok and data not in (None, "", [], {}) else ("EMPTY" if ok else "FAIL")
        rows.append({
            "id": tool["id"],
            "group": tool["group"],
            "path": tool["path"],
            "summary": tool["summary"],
            "args": args,
            "status": status,
            "httpStatus": payload.get("httpStatus"),
            "upstreamCode": payload.get("upstreamCode"),
            "errors": payload.get("errors"),
            "elapsedMs": elapsed,
            "size": data_size(data),
            "detail": summarize(data),
        })
        print(f"[{'OK ' if status == 'PASS' else status:4}] {tool['id']:<42} {elapsed:>6}ms {summarize(data)[:90]}")
        await asyncio.sleep(REQUEST_DELAY)

    total_ms = int((time.monotonic() - started) * 1000)
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseUrl": catalog.base_url(),
        "toolCount": len(rows),
        "elapsedMs": total_ms,
        "discovered": ids,
        "summary": {
            "PASS": sum(r["status"] == "PASS" for r in rows),
            "EMPTY": sum(r["status"] == "EMPTY" for r in rows),
            "FAIL": sum(r["status"] == "FAIL" for r in rows),
        },
        "rows": rows,
    }
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    write_html(report)
    print("SUMMARY", report["summary"], "elapsed", total_ms, "ms")
    await take_screenshots(report)
    return 0 if report["summary"]["FAIL"] == 0 else 1


def write_html(report: dict) -> None:
    groups: OrderedDict[str, list] = OrderedDict()
    for row in report["rows"]:
        groups.setdefault(row["group"], []).append(row)
    badge = {"PASS": "#0a7f43", "EMPTY": "#a86b00", "FAIL": "#c02626"}
    s = report["summary"]
    css_light = """
      body{margin:0;padding:28px 32px 48px;background:#f6f8fa;color:#1f2328;
           font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
      h1{font-size:24px;margin:0 0 6px} h2{font-size:18px;margin:30px 0 12px;
        padding-bottom:8px;border-bottom:1px solid #d0d7de}
      .meta{color:#57606a;margin-bottom:20px}
      .cards{display:flex;gap:12px;margin:18px 0 8px}
      .card{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:12px 18px;min-width:130px}
      .card b{display:block;font-size:26px;line-height:1.2}
      .card span{color:#57606a;font-size:12px}
      table{width:100%;border-collapse:collapse;background:#fff;font-size:12px}
      th,td{border:1px solid #d8dee4;padding:6px 8px;text-align:left;vertical-align:top}
      th{background:#eaeef2;color:#1f2328;white-space:nowrap}
      tr:nth-child(even) td{background:#fafbfc}
      .b{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-weight:600}
      .id{font-family:Consolas,monospace;white-space:nowrap}
      .args{color:#57606a;font-family:Consolas,monospace;word-break:break-all}
      .detail{max-width:520px;word-break:break-all}
      section{break-inside:avoid}
      footer{margin-top:30px;color:#57606a;font-size:12px}
    """
    html = [f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>非遗 MCP 全量接口测试</title><style>{css_light}</style></head><body>"]
    html.append("<h1>四川非遗 MCP · 全量工具真机测试</h1>")
    html.append(f"<div class='meta'>数据源 {report['baseUrl']} · 时间 {report['timestamp']} · 共 {report['toolCount']} 个工具 · 总耗时 {report['elapsedMs']/1000:.1f}s</div>")
    html.append("<div class='cards'>")
    for label, key in (("PASS 有数据", "PASS"), ("EMPTY 空结果", "EMPTY"), ("FAIL 调用失败", "FAIL")):
        html.append(f"<div class='card'><b style='color:{badge[key]}'>{s[key]}</b><span>{label}</span></div>")
    html.append("</div>")
    for idx, (group, rows) in enumerate(groups.items(), start=2):
        html.append(f"<section data-group='{group}'><h2>{group}（{len(rows)}）</h2>")
        html.append("<table><thead><tr><th>工具</th><th>状态</th><th>耗时</th><th>参数</th><th>返回摘要</th></tr></thead><tbody>")
        for r in rows:
            err = f"<br><span style='color:#c02626'>{r['errors']}</span>" if r["errors"] else ""
            args = " ".join(f"{k}={v}" for k, v in r["args"].items())
            html.append(
                "<tr>"
                f"<td class='id'>{r['id']}<br><span style='color:#57606a'>{r['path']}</span></td>"
                f"<td><span class='b' style='background:{badge[r['status']]}'>{r['status']}</span></td>"
                f"<td>{r['elapsedMs']}ms</td>"
                f"<td class='args'>{args}</td>"
                f"<td class='detail'>{r['detail']}{err}</td>"
                "</tr>")
        html.append("</tbody></table></section>")
    html.append("<footer>判定口径：PASS=上游 code=0 且 data 非空；EMPTY=code=0 但 data 为空（参数或上游无数据）；FAIL=HTTP/业务错误。所有请求均为 GET 只读。</footer>")
    html.append("</body></html>")
    HTML_OUT.write_text("\n".join(html), encoding="utf-8")
    print("HTML", HTML_OUT)


async def take_screenshots(report: dict) -> None:
    """必须用 async API：本脚本主流程在 asyncio loop 内，sync API 会直接报错。"""
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        print("SKIP screenshots: playwright unavailable", exc)
        return
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=edge, headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=1)
        await page.goto(HTML_OUT.as_uri(), wait_until="load")
        await page.locator(".cards").screenshot(path=str(SHOT_DIR / "01-overview.png"))
        for section in await page.locator("section").all():
            group = await section.get_attribute("data-group") or "group"
            safe = re.sub(r"[^A-Za-z0-9\u4e00-\u9fa5_-]+", "-", group)
            await section.screenshot(path=str(SHOT_DIR / f"02-{safe}.png"))
        await page.screenshot(path=str(SHOT_DIR / "00-full-page.png"), full_page=True)
        await browser.close()
    print("SCREENSHOTS", SHOT_DIR)


async def shots_only() -> int:
    """只重生成报告与截图，不重复打 69 个公网请求（便于修版式）。"""
    report = json.loads(JSON_OUT.read_text(encoding="utf-8"))
    write_html(report)
    await take_screenshots(report)
    return 0


if __name__ == "__main__":
    if "--shots-only" in sys.argv:
        raise SystemExit(asyncio.run(shots_only()))
    raise SystemExit(asyncio.run(main()))
