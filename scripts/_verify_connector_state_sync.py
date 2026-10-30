#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""连接态同源验收：hub 授权结果 → Java `connector_connection` → manifest 闸门（docs/63 §9.2）。

要防的是什么
------------
用户连接态本来存在两个互不同步的地方：
  - Java `connector_connection`：`/api/v1/mcp/manifest` 的闸门读它；
  - hub `wecom_connection`：MCP 工具执行读它。
于是「用 MCP 的 connect 工具连上」这条路，Java 侧仍停在 NEED_AUTH ⇒ 下一轮对话
manifest 判未连接 ⇒ **工具从模型手里消失**（连上了反而不能用）。
本哨兵就是钉住「hub 写回 Java 之后，manifest 必须认可」。

判据全部取第二源：不看 hub 自己怎么说，看 Java 的库/接口与 manifest 的真实返回。

  S1  POST /internal/v1/connectors/{code}/connection（无服务令牌）→ 401
  S2  同一路径用**错误密钥**签的服务令牌 → 401（证明不是「有票就放行」）
  S3  用 svc=hub 的正确令牌 → 200
  S4  第二源：GET /api/v1/connectors 显示该连接器 CONNECTED，且响应里没有凭据明文
  S5  **GET /api/v1/mcp/manifest 含 wechat_work**（核心判据：闸门真的认了）
  S6  POST .../connection/disconnect → manifest 不再含 wechat_work
  S7  hub 侧同步客户端（wecom/sync.py）打桩验证：路径 / Bearer / 字段转换都对
      （布尔要转小写字符串，否则 Java 的 Map<String,String> 会把 False 存成 "False"）

用法：
    D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_connector_state_sync.py [--base ...]
前置：Java :8080 在线（V96 已建表）。hub 无需在线（S7 用本地桩）。
退出码 = 失败项数。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

HUB_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp-hub")
if HUB_SRC not in sys.path:
    sys.path.insert(0, HUB_SRC)

DEV_SECRET = "aios-dev-service-jwt-secret-please-change"   # 与 DevSecretPlaceholders.SERVICE_JWT 一致
CODE = "wechat_work"
RESULTS: list[tuple[str, bool, str]] = []


def rec(name, ok, det=""):
    RESULTS.append((name, ok, det))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" —— " + det) if det else ""))


def call(base, path, method="GET", token=None, body=None, timeout=20):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, "TRANSPORT_ERROR: %s: %s" % (type(e).__name__, e)


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


def svc_token(svc="hub", secret=DEV_SECRET):
    """用 hub 自己的签发实现（不是照抄一份），这样验的就是生产用的那份代码。"""
    from mcp_hub import service_jwt
    old = os.environ.get(service_jwt.ENV_SECRET)
    os.environ[service_jwt.ENV_SECRET] = secret
    try:
        return service_jwt.issue(svc)
    finally:
        if old is None:
            os.environ.pop(service_jwt.ENV_SECRET, None)
        else:
            os.environ[service_jwt.ENV_SECRET] = old


# ---------- S7 用的桩：模拟 Java 接收端 ----------

class _Stub(BaseHTTPRequestHandler):
    captured: dict = {}

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace")
        _Stub.captured = {"path": self.path,
                          "auth": self.headers.get("Authorization") or "",
                          "body": jload(raw)}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"code":0,"message":"ok"}')

    def log_message(self, *args):  # 静音
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOS_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    ap.add_argument("--tenant", type=int, default=0)
    ap.add_argument("--uid", type=int, default=1)
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== 连接态同源验收 @ %s ==" % base)
    st, raw = call(base, "/api/v1/auth/login", "POST",
                   body={"username": args.user, "password": args.password})
    user_token = ((jload(raw).get("data") or {}).get("accessToken")) if st == 200 else None
    if not user_token:
        print("  [FATAL] 登录失败 HTTP=%s %s" % (st, raw[:120]))
        return 1

    path = "/internal/v1/connectors/%s/connection" % CODE
    body = {"tenantId": args.tenant, "userId": args.uid, "status": "CONNECTED",
            "accountLabel": "同源验收", "credential": {"userid": "verify-user",
                                                      "sensitive_authorized": "false"}}
    try:
        # S1 无票
        st, raw = call(base, path, "POST", body=body)
        rec("S1 无服务令牌 → 401", st == 401, "HTTP=%s" % st)

        # S2 错误密钥签的票
        st, raw = call(base, path, "POST", token=svc_token(secret="wrong-secret-" + "x" * 24), body=body)
        rec("S2 错误密钥的令牌 → 401", st == 401, "HTTP=%s" % st)

        # S3 正确票
        st, raw = call(base, path, "POST", token=svc_token(), body=body)
        d = jload(raw)
        rec("S3 svc=hub 正确令牌 → 写入成功",
            st == 200 and d.get("code") == 0 and (d.get("data") or {}).get("status") == "CONNECTED",
            "HTTP=%s data=%s" % (st, d.get("data")))

        # S4 第二源：用户视角的目录状态 + 无明文
        # ★ 连接态必须只信库（connector_connection）：list() 曾用 configReady 门把 CONNECTED
        #   强降级成 NEED_AUTH，于是 manifest 已放行、界面却说「未连接」，自相矛盾。
        #   应用配置就绪度是另一根轴（configReady/configHint），未就绪时 hint 不能为空，
        #   否则 H5 只能显示「管理员尚未完成配置」这句写死的兜底（_oa_app.js connCardHtml）。
        st, raw = call(base, "/api/v1/connectors", token=user_token)
        items = (jload(raw).get("data") or [])
        me = next((i for i in items if i.get("code") == CODE), {}) or {}
        leaked = "verify-user" in raw and "credentialJson" in raw
        hint_ok = (me.get("configReady") is True) or bool(me.get("configHint"))
        rec("S4 用户端目录显示 CONNECTED 且无凭据明文",
            st == 200 and me.get("status") == "CONNECTED" and not leaked and hint_ok,
            "HTTP=%s status=%s configReady=%s hint=%r leaked=%s"
            % (st, me.get("status"), me.get("configReady"), me.get("configHint"), leaked))

        # S5 核心：manifest 闸门认了
        st, raw = call(base, "/api/v1/mcp/manifest", token=user_token)
        codes = [i.get("code") for i in (jload(raw).get("data") or [])]
        rec("S5 manifest 含 wechat_work（闸门认可）", st == 200 and CODE in codes,
            "HTTP=%s codes=%s" % (st, codes))

        # S6 断开后必须消失
        st, raw = call(base, "/internal/v1/connectors/%s/connection/disconnect" % CODE, "POST",
                       token=svc_token(), body={"tenantId": args.tenant, "userId": args.uid})
        st2, raw2 = call(base, "/api/v1/mcp/manifest", token=user_token)
        codes2 = [i.get("code") for i in (jload(raw2).get("data") or [])]
        rec("S6 断开后 manifest 不含 wechat_work", st == 200 and CODE not in codes2,
            "HTTP=%s codes=%s" % (st, codes2))
    finally:
        # 兜底复原：无论上面哪步炸了，都不要把 admin 留在「已连接」
        call(base, "/internal/v1/connectors/%s/connection/disconnect" % CODE, "POST",
             token=svc_token(), body={"tenantId": args.tenant, "userId": args.uid})

    # ---------- S7 hub 侧同步客户端（打桩） ----------
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old_base = os.environ.get("AIOS_SERVER_BASE_URL")
    old_secret = os.environ.get("AIOS_SERVICE_JWT_SECRET")
    os.environ["AIOS_SERVER_BASE_URL"] = "http://127.0.0.1:%d" % port
    os.environ["AIOS_SERVICE_JWT_SECRET"] = DEV_SECRET
    try:
        from mcp_hub.wecom import sync
        okc = asyncio.run(sync.report_connected(
            "0", "1", CODE, "张三", {"userid": "zhangsan", "name": "张三",
                                     "biz_mail": "z@corp.com", "sensitive_authorized": False}))
        cap = dict(_Stub.captured)
        okd = asyncio.run(sync.report_disconnected("0", "1", CODE))
        capd = dict(_Stub.captured)
    finally:
        srv.shutdown()
        for k, v in (("AIOS_SERVER_BASE_URL", old_base), ("AIOS_SERVICE_JWT_SECRET", old_secret)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    cb = cap.get("body") or {}
    auth_ok = cap.get("auth", "").startswith("Bearer ") and cap.get("auth", "").count(".") == 2
    cred = (cb.get("credential") or {})
    rec("S7 hub 同步客户端：路径/Bearer/布尔转小写都对",
        okc and okd
        and cap.get("path") == "/internal/v1/connectors/%s/connection" % CODE
        and capd.get("path") == "/internal/v1/connectors/%s/connection/disconnect" % CODE
        and auth_ok
        and cb.get("tenantId") == 0 and cb.get("userId") == 1
        and cb.get("accountLabel") == "张三"
        and cred.get("sensitive_authorized") == "false"
        and cred.get("biz_mail") == "z@corp.com",
        "path=%s auth=%s body=%s" % (cap.get("path"), "Bearer" if auth_ok else cap.get("auth"),
                                     json.dumps(cb, ensure_ascii=False)[:200]))

    failed = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n, _, det in failed:
        print("  - %s：%s" % (n, det))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
