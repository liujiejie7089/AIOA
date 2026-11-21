# -*- coding: utf-8 -*-
"""非遗按租户接入：端到端真机验收（docs/92 §6 A1/A2/A3/A4/A5/A6/A7/A10/A11）。

与 _verify_scfy_access_gate.py 的分工：那边是 hub 进程内 stub（证明闸门逻辑），
这边是**真机**：真 Java（Flyway V115 + 迁移后的库）、真 hub :8099、真登录 JWT、
真 MCP Streamable HTTP 协议、真非遗公网接口。两条链路都过才算改造完成。

判据纪律（铁律 7/12）：
  - 「不可见」= 回 /api/v1/mcp/manifest 取，**不看界面**；
  - 「不可调」= 真发 tools/call 到 /mcp/scfy，断言 accessDenied；
  - A10 判别力：把租户接入配置停用后，原本「可用」的同一用例必须转 FAIL；
  - 末尾 finally 恢复现场（启用 + 清空范围 + 恢复 tenant2），绝不把测试状态留给现网。

用法：
    python scripts/_verify_scfy_tenant_access.py
产物：scripts/_verify_scfy_tenant_access_result.txt
前置：8080 / 8099 已启动，AIOS_SCFY_ACCESS_CHECK=1（默认）。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
HUB = "http://127.0.0.1:8099"
MYSQL = r"D:\dev\mysql\mysql-8.4.10-winx64\bin\mysql.exe"
RESULT = Path(__file__).resolve().parent / "_verify_scfy_tenant_access_result.txt"

_LINES: list[str] = []
_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    line = ("PASS" if cond else "FAIL") + " " + name + " " + str(detail)[:260]
    _LINES.append(line)
    print(line)
    if not cond:
        _FAILS.append(name)


def sql(statement: str) -> str:
    p = subprocess.run([MYSQL, "-uroot", "aios", "-e", statement],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout or ""


def _count_sql(statement: str) -> int:
    """执行一条只回单列计数的 SQL，取第一数据行的整数；解析失败返回 -1（判据会红）。"""
    out = sql(statement)
    for line in out.splitlines()[1:]:
        s = line.strip()
        if s.isdigit():
            return int(s)
    return -1


_client = httpx.Client(trust_env=False, timeout=30.0)


def login(username: str, password: str, tenant_name: str) -> "str | None":
    r = _client.post(BASE + "/api/v1/auth/login",
                      json={"username": username, "password": password,
                            "tenantName": tenant_name})
    if r.status_code != 200:
        return None
    body = r.json()
    return (body.get("data") or {}).get("accessToken")


def api(method: str, path: str, token: str, body: "dict | None" = None):
    r = _client.request(method, BASE + path,
                        headers={"Authorization": "Bearer " + token}, json=body)
    try:
        parsed = r.json()
    except Exception:
        parsed = {}
    return r.status_code, parsed


def manifest_codes(token: str) -> list[str]:
    st, body = api("GET", "/api/v1/mcp/manifest", token)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    return [str(x.get("code")) for x in data if isinstance(x, dict)]


def hub_call(token: str, tool: str = "project_count_by_area",
             args: "dict | None" = None) -> dict:
    """真机 MCP Streamable HTTP：initialize → initialized → tools/call，带调用者 JWT。"""
    async def _run() -> dict:
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "Authorization": "Bearer " + token}
        async with httpx.AsyncClient(trust_env=False, timeout=40.0) as c:
            r = await c.post(HUB + "/mcp/scfy", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "tenant-access-verify", "version": "1.0"}}})
            session = r.headers.get("mcp-session-id")
            h2 = dict(headers)
            if session:
                h2["Mcp-Session-Id"] = session
            await c.post(HUB + "/mcp/scfy", headers=h2, json={
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            rr = await c.post(HUB + "/mcp/scfy", headers=h2, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool, "arguments": args or {"area": "甘孜州"}}})
            raw = rr.text
            parsed = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        parsed = json.loads(line[5:].strip())
                        break
                    except Exception:
                        continue
            if parsed is None:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return {"_transport_error": raw[:200]}
            content = (parsed.get("result") or {}).get("content") or []
            if not content:
                return {"_no_content": parsed}
            try:
                return json.loads(content[0].get("text", "{}"))
            except Exception:
                return {"_bad_content": str(content[0])[:200]}
    return asyncio.run(_run())


def access_view(token: str, code: str = "scfy") -> dict:
    st, body = api("GET", "/api/v1/connector-access/" + code, token)
    d = body.get("data") if isinstance(body, dict) else None
    return d if isinstance(d, dict) else {}


def main() -> int:
    admin = login("admin", "Admin@123", "默认租户")
    check("B1 平台管理员登录", bool(admin), "tenant=0")
    if not admin:
        return finish()

    # 本机实测（scripts/.tmp_probe_login.py）：dsj_admin 的口令是 Admin@123，
    # 其它同租户账号才是 User@123 —— 与 docs/14 的口径有偏差，以真机为准，别照抄文档。
    dsj = login("dsj_admin", "Admin@123", "某某市某某区大数据管理局")
    check("B2 第二租户管理员登录", bool(dsj), "tenant=2")

    # ---- 数据驱动清单 / 用户端字段（证明 jar 里有 list 端点与 accessMode）----
    st, body = api("GET", "/api/v1/connector-access", admin)
    lst = body.get("data") if isinstance(body, dict) else None
    check("B3 接入清单端点可用且含 scfy",
          st == 200 and isinstance(lst, list) and any(x.get("code") == "scfy" for x in lst),
          str(lst)[:200])
    st, body = api("GET", "/api/v1/connectors", admin)
    conns = body.get("data") if isinstance(body, dict) else None
    scfy_conn = next((x for x in conns if isinstance(x, dict) and x.get("code") == "scfy"), {}) \
        if isinstance(conns, list) else {}
    check("B4 /connectors 下发 accessMode=TENANT",
          scfy_conn.get("accessMode") == "TENANT", scfy_conn.get("accessMode"))
    check("B5 基线 configReady=true（存量平移已启用）",
          scfy_conn.get("configReady") is True, scfy_conn.get("configReady"))

    try:
        # ---- A3 基线：已接入租户可见 + 可调真数据 ----
        codes = manifest_codes(admin)
        check("A3-1 基线 manifest 含 scfy", "scfy" in codes, codes)
        r = hub_call(admin)
        check("A3-2 hub 直调返回真实数据",
              r.get("ok") is True and bool(r.get("data")), str(r)[:220])

        # ---- A11 既有连接器工具数不回退（docs/92 A11：hub /health 对照）----
        # manifest 只列「trusted=1 且可用」的服务器；qq_mail / wecom_cli 需用户 CONNECTED，
        # admin 从未连接 ⇒ 本来就不在 manifest 里，那是既有基线，不是本次改造的回退。
        # 因此按 docs/92 的口径回 hub /health 取三台 server 的注册工具数对照。
        hr = _client.get(HUB + "/health").json()
        servers = hr.get("servers") or {}
        check("A11 既有连接器工具数不变（wecom_cli=25 / qq_mail=6 / scfy=69）",
              servers.get("wecom_cli") == 25 and servers.get("qq_mail") == 6
              and servers.get("scfy") == 69, servers)

        # ---- A10 判别力 + A1：停用后原可用例必须转 FAIL ----
        st, body = api("POST", "/api/v1/admin/connector-access/scfy/disable", admin)
        v = access_view(admin)
        check("A10-0 停用后状态=DISABLED", v.get("status") == "DISABLED", v.get("status"))
        codes_off = manifest_codes(admin)
        check("A10-1 停用后 manifest 不含 scfy（判别力）", "scfy" not in codes_off, codes_off)
        r_off = hub_call(admin)   # 同一 token，不重新登录
        check("A1-1 停用后 hub 直调被拒",
              r_off.get("ok") is False and r_off.get("accessDenied") is True, str(r_off)[:220])
        check("A1-2 拒绝文案可执行（指租户接入）",
              "租户" in str(r_off.get("errors")) or "接入" in str(r_off.get("errors")),
              r_off.get("errors"))

        # ---- A2：启用后立即生效，无需重新登录 ----
        api("POST", "/api/v1/admin/connector-access/scfy/enable", admin)
        codes_on = manifest_codes(admin)
        check("A2-1 启用后 manifest 立即含 scfy", "scfy" in codes_on, codes_on)
        r_on = hub_call(admin)
        check("A2-2 启用后 hub 直调立即恢复",
              r_on.get("ok") is True and bool(r_on.get("data")), str(r_on)[:220])

        # ---- A5 机构范围：配置不存在的机构白名单 → 主闸门拦下 ----
        api("PUT", "/api/v1/admin/connector-access/scfy/config", admin,
            {"scopeInstitutions": [999999], "config": {}})
        codes_scope = manifest_codes(admin)
        check("A5-1 机构白名单外用户不可见 scfy", "scfy" not in codes_scope, codes_scope)
        r_scope = hub_call(admin)
        check("A5-2 机构白名单外用户直调被拒",
              r_scope.get("ok") is False and r_scope.get("accessDenied") is True,
              str(r_scope)[:220])
        api("PUT", "/api/v1/admin/connector-access/scfy/config", admin,
            {"scopeInstitutions": [], "config": {}})
        check("A5-3 清空白名单后恢复可见", "scfy" in manifest_codes(admin))

        # ---- A6 用户范围：allowedUserIds 白名单外 → 拦下 ----
        api("PUT", "/api/v1/admin/connector-access/scfy/config", admin,
            {"scopeInstitutions": [], "config": {"allowedUserIds": [999999]}})
        check("A6-1 用户白名单外不可见 scfy", "scfy" not in manifest_codes(admin))
        api("PUT", "/api/v1/admin/connector-access/scfy/config", admin,
            {"scopeInstitutions": [], "config": {}})
        check("A6-2 清空用户白名单后恢复可见", "scfy" in manifest_codes(admin))

        # ---- A7 审计归属：精确回库计数，不用「字符串里有没有」这种恒真条件 ----
        n0 = _count_sql("SELECT COUNT(*) FROM mcp_tool_audit "
                         "WHERE server_code='scfy' AND tenant_id=0")
        check("A7 scfy 调用审计按 tenant=0 归属落库", n0 >= 1, "rows=%d" % n0)

        # ---- A4 跨租户隔离：物理删 tenant2 的接入行，模拟「新租户未接入」----
        if dsj:
            sql("DELETE FROM connector_tenant_access WHERE tenant_id=2 AND connector_code='scfy';")
            codes_b = manifest_codes(dsj)
            check("A4-1 未接入租户 B 的 manifest 不含 scfy", "scfy" not in codes_b, codes_b)
            r_b = hub_call(dsj)
            check("A4-2 未接入租户 B 直调 hub 被拒",
                  r_b.get("ok") is False and r_b.get("accessDenied") is True, str(r_b)[:220])
            n2 = _count_sql("SELECT COUNT(*) FROM mcp_tool_audit "
                             "WHERE server_code='scfy' AND tenant_id=2")
            check("A7b 租户 B 被拒的调用也按 tenant=2 留痕", n2 >= 1, "rows=%d" % n2)
            check("A4-3 同一时刻租户 A 仍可见（隔离成立）",
                  "scfy" in manifest_codes(admin))
            st, body = api("POST", "/api/v1/admin/connector-access/scfy/enable", dsj)
            check("A4-4 租户 B 自行启用后立即可见",
                  "scfy" in manifest_codes(dsj), (st, str(body)[:160]))

        # ---- 回滚开关口径自检：check 端点需登录（不带 token 必须 401/403）----
        r_anon = _client.get(BASE + "/api/v1/mcp/access/scfy/check",
                             params={"tool": "project_count_by_area"})
        check("S1 check 端点拒绝匿名调用", r_anon.status_code in (401, 403),
              r_anon.status_code)
    finally:
        # 恢复现场：启用 + 清空范围；tenant2 若被删则补回已启用行
        try:
            api("PUT", "/api/v1/admin/connector-access/scfy/config", admin,
                {"scopeInstitutions": [], "config": {}})
            api("POST", "/api/v1/admin/connector-access/scfy/enable", admin)
            sql("INSERT INTO connector_tenant_access "
                "(tenant_id, connector_code, enabled, enabled_by, enabled_at, created_by) "
                "SELECT 2, 'scfy', 1, 0, NOW(6), 0 FROM DUAL "
                "WHERE NOT EXISTS (SELECT 1 FROM connector_tenant_access "
                "WHERE tenant_id=2 AND connector_code='scfy');")
            check("R1 现场恢复：tenant0 已启用", "scfy" in manifest_codes(admin))
            if dsj:
                check("R2 现场恢复：tenant2 已启用", "scfy" in manifest_codes(dsj))
        except Exception as e:  # noqa: BLE001
            check("R1 现场恢复", False, repr(e))

    return finish()


def finish() -> int:
    RESULT.write_text("\n".join(_LINES) + "\nRESULT: " +
                      ("ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS)) + "\n",
                      encoding="utf-8")
    print("RESULT:", "ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
