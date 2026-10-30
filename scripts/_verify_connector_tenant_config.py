#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：租户级连接器应用凭据（管理端填写 → 运行时生效，2026-10-29 改为 hub 权威）

契约变化：凭据的**权威存储是 mcp-hub**（工具在 hub 里跑），MySQL 只留影子记录。
因此本哨兵同时需要 Java 后端与 mcp-hub 在线，且**每一项都在第二个来源复核**
（铁律 12：不能只信被测接口自己的回话）。

  T0  hub  /health                                        200 且报两个内置连接器
  T1  GET  /api/v1/admin/connector-configs/wechat_work    200；有 configKeys/values/source=hub；无明文
  T2  PUT  保存测试凭据                                    200；且**回查 hub** configured=true（第二源）
  T3  GET  /api/v1/connectors                             wechat_work.configReady=true（用户端解除待配置）
  T4  PUT  只提交掩码值/空串                               200 且 hub 侧 configured 仍为 true（旧值保留）
  T5  GET  掩码视图 + connect/start                       无 corpSecret 明文；start 出 authUrl（URL 不含密钥）
  T6  GET  未登录                                          401
  T7  DELETE 清除                                          hub configured=false + configReady 回 false（不残留）

用法：
    NO_PROXY='*' python scripts/_verify_connector_tenant_config.py [--base http://127.0.0.1:8080]
前置：Java 后端 :8080 在线；mcp-hub :8099 在线（AIOS_MCP_HUB=true 且设置 WECOM_CONNECTOR_KEY）。
退出码 = 失败项数。结束时**不残留**测试配置（T7 清除）。
"""
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

RESULTS = []
TEST_CORP = "ww_sentinel_corp"
TEST_AGENT = "1000001"
TEST_SECRET = "sentinel_secret_000111"

# 与 _verify_mcp_registry 同一口径：用盘符式路径（Git Bash 的 /d/... 在 Python 下不成立）
MYSQL = "D:/dev/mysql/mysql-8.4.10-winx64/bin/mysql.exe"


def connector_status(code: str) -> "str | None":
    """读 connector_def.status（第二源：库，不看接口回话）。"""
    try:
        out = subprocess.run([MYSQL, "-uroot", "-N", "-B", "aios", "-e",
                              "select status from connector_def where tenant_id=0 and code='%s' limit 1" % code],
                             capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    return (out.stdout or "").strip() or None


def set_connector_status(code: str, status: str) -> None:
    subprocess.run([MYSQL, "-uroot", "-N", "-B", "aios", "-e",
                    "update connector_def set status='%s' where tenant_id=0 and code='%s'" % (status, code)],
                   capture_output=True, text=True, timeout=20)


def call(base, path, method="GET", token=None, body=None, timeout=25, extra_headers=None):
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        return 0, {}, "URLError: %s" % e.reason


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def rec(name, ok, det=""):
    RESULTS.append((name, ok, det))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" —— " + det) if det else ""))


def login(base, username, password):
    st, _, raw = call(base, "/api/v1/auth/login", "POST",
                      body={"username": username, "password": password})
    d = jload(raw) or {}
    token = ((d.get("data") or {}).get("accessToken")) if st == 200 else None
    return token, st


def hub_status(hub, token, code="wechat_work"):
    """第二源：直接问 hub 拿掩码视图（POST 保存后用它复核，不信 Java 的回话）。"""
    st, _, raw = call(hub, "/api/v1/connectors/%s/credentials" % code, token=token)
    return st, (jload(raw) or {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--hub", default="http://127.0.0.1:8099")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()

    # 前置：2026-10-30 起 wechat_work 已下线（V103，企业微信统一改用扫码连接器 docs/64）。
    # 但本套件验的是「租户凭据中心 → hub vault → 用户端 configReady」这条机制，机制还在，
    # 只是被测对象不再出现在用户目录里。所以临时把 status 置回 ACTIVE 跑完再复原
    # （与本项目「快照→复位→跑→恢复」的既有纪律一致；不能因为主体下线就把机制测试删掉）。
    prev = connector_status("wechat_work")
    if prev not in (None, "ACTIVE"):
        set_connector_status("wechat_work", "ACTIVE")
        print("  [ 前置 ] wechat_work 当前为 %s（已下线），临时置 ACTIVE 验机制，跑完恢复" % prev)
    try:
        return _run(args)
    finally:
        if prev not in (None, "ACTIVE"):
            set_connector_status("wechat_work", prev)
            print("  [ 复原 ] wechat_work 恢复为 %s" % prev)


def _run(args):
    base, hub = args.base, args.hub

    print("== 连接器应用凭据验收（管理端 → 运行时） @ %s / hub %s ==" % (base, hub))

    # ---------- T0 hub 在线 ----------
    st, _, raw = call(hub, "/health", timeout=5)
    hb = jload(raw) or {}
    rec("T0 mcp-hub 在线且报出内置连接器",
        st == 200 and hb.get("ok") is True and "wechat_work" in (hb.get("servers") or {}),
        "HTTP=%s servers=%s" % (st, hb.get("servers")))

    token, st = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s）：%s" % (st, "后端未启动或无此账号"))
        return 1
    CFG = "/api/v1/admin/connector-configs/wechat_work"

    # ---------- T1 初始掩码视图 ----------
    st, _, raw = call(base, CFG, token=token)
    d = jload(raw) or {}
    v0 = d.get("data") or {}
    rec("T1 管理端掩码视图（configKeys/values/source=hub，无明文）",
        st == 200 and d.get("code") == 0
        and v0.get("source") == "hub"
        and isinstance(v0.get("configKeys"), list) and v0.get("configKeys")
        and isinstance(v0.get("values"), dict)
        and TEST_SECRET not in raw,
        "HTTP=%s source=%s keys=%s" % (st, v0.get("source"), v0.get("configKeys")))

    # ---------- T2 保存 → 回查 hub ----------
    st, _, raw = call(base, CFG, "PUT", token=token,
                      body={"values": {"corpId": TEST_CORP, "agentId": TEST_AGENT,
                                       "corpSecret": TEST_SECRET}, "enabled": True})
    d = jload(raw) or {}
    v = d.get("data") or {}
    java_ok = st == 200 and d.get("code") == 0 and v.get("configured") is True
    hst, hv = hub_status(hub, token)
    hub_ok = hst == 200 and hv.get("configured") is True
    rec("T2 保存后**运行时（hub）**已生效（第二源复核）",
        java_ok and hub_ok,
        "javaHTTP=%s hubHTTP=%s hubConfigured=%s" % (st, hst, hv.get("configured")))

    # ---------- T3 用户端就绪度翻转 ----------
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    ww = {i.get("code"): i for i in ((jload(raw) or {}).get("data") or [])}.get("wechat_work") or {}
    rec("T3 用户端 wechat_work.configReady=true（解除待管理员配置）",
        ww.get("configReady") is True, "configReady=%s hint=%r" % (ww.get("configReady"), ww.get("configHint")))

    # ---------- T4 掩码值回传 = 保留旧值 ----------
    st, _, raw = call(base, CFG, "PUT", token=token,
                      body={"values": {"corpId": "••••", "agentId": "", "corpSecret": "••••••"},
                            "enabled": True})
    d = jload(raw) or {}
    v = d.get("data") or {}
    hst, hv = hub_status(hub, token)
    rec("T4 只提交掩码值/空串 → 旧凭据保留（hub 侧仍已配置）",
        st == 200 and d.get("code") == 0 and v.get("configured") is True
        and hst == 200 and hv.get("configured") is True,
        "javaHTTP=%s hubConfigured=%s" % (st, hv.get("configured")))

    # ---------- T5 不泄露明文 + start 出 authUrl ----------
    st, _, raw = call(base, CFG, token=token)
    leak = TEST_SECRET in raw or TEST_CORP in raw
    rec("T5 掩码视图不含 corpId/corpSecret 明文", st == 200 and not leak, "明文出现=%s" % leak)
    st, _, raw = call(base, "/api/v1/connectors/wechat_work/connect/start", "POST",
                      token=token, body={"returnPath": "/"},
                      extra_headers={"Origin": base, "Host": base.split("//", 1)[1]})
    d = jload(raw) or {}
    auth_url = (d.get("data") or {}).get("authUrl") or ""
    rec("T5b start 生成 authUrl 且不含密钥",
        st == 200 and d.get("code") == 0 and "qrConnect" in auth_url and TEST_SECRET not in raw,
        "authUrl前缀=%r secret泄露=%s" % (auth_url[:60], TEST_SECRET in raw))

    # ---------- T6 未登录 401 ----------
    st, _, raw = call(base, CFG)
    rec("T6 未登录 401", st == 401, "HTTP=%s" % st)

    # ---------- T7 清除（不残留） ----------
    st, _, raw = call(base, CFG, "DELETE", token=token)
    ok7 = st == 200 and (jload(raw) or {}).get("code") == 0
    hst, hv = hub_status(hub, token)
    st2, _, raw2 = call(base, "/api/v1/connectors", token=token)
    ww = {i.get("code"): i for i in ((jload(raw2) or {}).get("data") or [])}.get("wechat_work") or {}
    rec("T7 清除后 hub 与用户端都回到待配置（不残留）",
        ok7 and hst == 200 and hv.get("configured") is False and ww.get("configReady") is False,
        "delete=%s hubConfigured=%s configReady=%s" % (ok7, hv.get("configured"), ww.get("configReady")))

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for n, _, det in fails:
        print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
