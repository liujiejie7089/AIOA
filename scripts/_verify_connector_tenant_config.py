#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：管理端「连接器应用配置」面（2026-10-30 改主体）

**为什么改**：原来这套件以 `wechat_work`（自建应用 corpId/agentId/corpSecret）为主体，
验的是「管理端填写 → hub 权威存储 → 用户端 configReady 翻转」。2026-10-30 该连接器
连同 `provider=wecom` 分支一起被物理删除（docs/64 §9.7），主体没了。

现在**存活的连接器都不需要管理员配置**（qq_mail 用户自填授权码、wecom_cli 各自扫码），
于是这套件改成验「没有应用级凭据的形态必须表现正确」—— 这恰恰是删掉旧通道后
最容易被写坏的地方：把「无需配置」误显示成「待管理员配置」，或让管理端把一个
根本不会被使用的值悄悄写进去还报成功。

  T0  hub  /health                                        200
  T1  GET  /api/v1/admin/connector-configs                含 qq_mail / wecom_cli；configKeys 均为空；
                                                          source=hub（权威在运行时）；已下线的两个不出现
  T2  GET  /api/v1/admin/connector-configs/qq_mail        configKeys=[]、values={}、source=hub、hubAvailable=true
  T3  PUT  /api/v1/admin/connector-configs/qq_mail        业务码 400 + 文案含「应用级凭据」
                                                          ⇒ 无应用凭据的连接器**不许**被静默写入
  T4  GET  /api/v1/connectors                             qq_mail.configReady=true（用户端不显示「待配置」）
  T5  GET  /api/v1/admin/connector-configs/wechat_work     已下线 ⇒ 查无此连接器（不是「待配置」）
  T6  GET  /api/v1/admin/connector-configs（无 token）      401

**覆盖缺口（显式记录，别当成已验证）**：`provider!=none` 的「管理端保存 → 运行时生效」
端到端链路现在**没有活的被测主体**，本套件不再覆盖它。hub 侧的保存/掩码/保留旧值/清除
由 `_verify_connectors_registry.py`（S5–S8、S12、S13）用运行期登记的 provider=vault
连接器覆盖；Java→hub 的透传本身要等下一个「需要管理员配凭据」的连接器接进来才能真验。
届时必须把 T2/T3 扩回「保存 → 回查 hub configured=true → 用户端 configReady 翻转」。

用法：
    NO_PROXY='*' python scripts/_verify_connector_tenant_config.py [--base http://127.0.0.1:8080]
前置：Java 后端 :8080 在线；mcp-hub :8099 在线（AIOS_MCP_HUB=true）。
退出码 = 失败项数。全程只读 + 一次必被拒绝的 PUT，不留任何状态。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

RESULTS = []


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--hub", default="http://127.0.0.1:8099")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()

    base, hub = args.base, args.hub
    print("== 管理端连接器配置面验收 @ %s / hub %s ==" % (base, hub))

    # ---------- T0 hub 在线 ----------
    st, _, raw = call(hub, "/health", timeout=5)
    hb = jload(raw) or {}
    rec("T0 mcp-hub 在线并报出内置连接器",
        st == 200 and hb.get("ok") is True
        and {"qq_mail", "wecom_cli"} <= set(hb.get("servers") or {}),
        "HTTP=%s servers=%s" % (st, hb.get("servers")))

    token, st = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s）：%s" % (st, "后端未启动或无此账号"))
        return 1
    LIST = "/api/v1/admin/connector-configs"

    # ---------- T1 清单 ----------
    # 现状事实：存活的两个连接器都不需要应用级凭据 ⇒ 管理端「连接器配置」清单**应为空**。
    # 这不是「功能坏了」，但极易被写成「一台也没有 / 接口挂了」，所以同时用第二源交叉验证：
    # 用户端目录里这两个连接器必须在、且 configReady=true（说明它们只是"不需要配置"，不是"不存在"）。
    st, _, raw = call(base, LIST, token=token)
    d = jload(raw) or {}
    admin_items = d.get("data") or []
    st2, _, raw2 = call(base, "/api/v1/connectors", token=token)
    user_items = {i.get("code"): i for i in ((jload(raw2) or {}).get("data") or [])}
    user_ok = all((user_items.get(c) or {}).get("configReady") is True
                  for c in ("qq_mail", "wecom_cli"))
    rec("T1 管理端清单为空（无人需要配凭据）且用户端两个连接器都在且就绪",
        st == 200 and d.get("code") == 0 and admin_items == [] and user_ok,
        "HTTP=%s 管理端=%s 用户端就绪=%s" % (st, admin_items, user_ok))

    # ---------- T2 单项视图 ----------
    st, _, raw = call(base, LIST + "/qq_mail", token=token)
    d = jload(raw) or {}
    msg = d.get("message") or ""
    rec("T2 无应用级配置项的连接器：视图明确拒绝而不是回一个空表单",
        st == 200 and d.get("code") not in (None, 0)
        and "没有应用级配置项" in msg,
        "HTTP=%s code=%s message=%r" % (st, d.get("code"), msg[:120]))

    # ---------- T3 无应用凭据的连接器不许被写入 ----------
    st, _, raw = call(base, LIST + "/qq_mail", "PUT", token=token,
                      body={"values": {"email": "x@qq.com", "authCode": "should_not_be_stored"},
                            "enabled": True})
    d = jload(raw) or {}
    msg = d.get("message") or ""
    rec("T3 无应用级配置项的连接器 PUT 被拒（不静默成功、不落库）",
        st == 200 and d.get("code") not in (None, 0) and "没有应用级配置项" in msg,
        "HTTP=%s code=%s message=%r" % (st, d.get("code"), msg[:120]))

    # 第二源：再取一次视图，仍必须是「拒绝」（证明刚才那次没被半途写进去）
    st, _, raw = call(base, LIST + "/qq_mail", token=token)
    rec("T3b 拒绝之后仍未产生任何配置（明文绝不出现在响应里）",
        (jload(raw) or {}).get("code") not in (None, 0) and "should_not_be_stored" not in raw,
        "code=%s 明文出现=%s" % ((jload(raw) or {}).get("code"), "should_not_be_stored" in raw))

    # ---------- T4 用户端就绪度 ----------
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    qq = {i.get("code"): i for i in ((jload(raw) or {}).get("data") or [])}.get("qq_mail") or {}
    rec("T4 用户端 qq_mail.configReady=true（不显示「待管理员配置」）",
        qq.get("configReady") is True,
        "configReady=%s hint=%r" % (qq.get("configReady"), qq.get("configHint")))

    # ---------- T5 已下线连接器查无此项 ----------
    st, _, raw = call(base, LIST + "/wechat_work", token=token)
    d = jload(raw) or {}
    rec("T5 已下线连接器在管理端查无此项（不是「待配置」）",
        st == 404 and d.get("code") == 404 and "不存在" in (d.get("message") or ""),
        "HTTP=%s code=%s message=%r" % (st, d.get("code"), (d.get("message") or "")[:100]))

    # ---------- T6 未登录 ----------
    st, _, raw = call(base, LIST)
    rec("T6 未登录 401", st == 401, "HTTP=%s" % st)

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for n, _, det in fails:
        print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
