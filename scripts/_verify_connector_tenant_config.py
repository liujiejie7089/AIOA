#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：租户级连接器配置管理（管理端动态解除「待管理员配置」，2026-10-27）

  T1  GET  /api/v1/admin/connector-configs/wechat_work   200 + 掩码视图（无明文密钥）
  T2  PUT  保存测试凭据                                   200 + configured=true + configReady=true
  T3  GET  /api/v1/connectors                            wechat_work.configReady=true（不再是「待管理员配置」）
  T4  PUT  只提交掩码值                                   200 且旧凭据保留（掩码绝不当新值写库）
  T5  GET  掩码视图 + start                              响应不含 corpSecret/corpId 明文；start 生成 authUrl（不含密钥）
  T6  GET  未登录                                        401
  T7  DELETE 清除                                          configReady 回 false（恢复「待管理员配置」）

用法：
    NO_PROXY='*' python scripts/_verify_connector_tenant_config.py [--base http://127.0.0.1:8080]
前置：后端在线（含 ConnectorTenantConfigController）。退出码 = 失败项数。
结束时**不残留**测试配置（T7 清除）。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

RESULTS = []
TEST_CORP = "ww_sentinel_corp"
TEST_AGENT = "1000001"
TEST_SECRET = "sentinel_secret_000111"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()
    base = args.base

    print("== 租户级连接器配置管理验收 @ %s ==" % base)
    token, st = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s）" % st)
        return 1
    CFG = "/api/v1/admin/connector-configs/wechat_work"

    # ---------- T1 初始掩码视图 ----------
    st, _, raw = call(base, CFG, token=token)
    d = jload(raw) or {}
    v0 = d.get("data") or {}
    rec("T1 掩码视图可读（200 + 约定字段）",
        st == 200 and d.get("code") == 0
        and set(v0) >= {"corpId", "agentId", "corpSecretSet", "enabled", "configured", "configReady"},
        "HTTP=%s keys=%s" % (st, sorted(v0)))

    # ---------- T2 保存测试凭据 ----------
    st, _, raw = call(base, CFG, "PUT", token=token,
                      body={"values": {"corpId": TEST_CORP, "agentId": TEST_AGENT,
                                       "corpSecret": TEST_SECRET}, "enabled": True})
    d = jload(raw) or {}
    v = d.get("data") or {}
    rec("T2 保存测试凭据 → configured/configReady=true",
        st == 200 and d.get("code") == 0 and v.get("configured") is True and v.get("configReady") is True,
        "HTTP=%s configured=%s configReady=%s" % (st, v.get("configured"), v.get("configReady")))

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
    rec("T4 只提交掩码值 → 旧凭据保留（仍 configReady）",
        st == 200 and d.get("code") == 0 and v.get("configured") is True and v.get("configReady") is True,
        "HTTP=%s configReady=%s" % (st, v.get("configReady")))

    # ---------- T5 不泄露明文 + start 出 authUrl ----------
    st, _, raw = call(base, CFG, token=token)
    leak = TEST_SECRET in raw or TEST_CORP in raw
    rec("T5 掩码视图不含 corpId/corpSecret 明文", st == 200 and not leak,
        "明文出现=%s" % leak)
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
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    ww = {i.get("code"): i for i in ((jload(raw) or {}).get("data") or [])}.get("wechat_work") or {}
    rec("T7 清除后回到待管理员配置（不残留测试配置）",
        ok7 and ww.get("configReady") is False,
        "delete=%s configReady=%s" % (ok7, ww.get("configReady")))

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for n, _, det in fails:
        print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
