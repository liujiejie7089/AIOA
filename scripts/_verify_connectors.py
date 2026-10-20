#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：连接器中心（docs/58 §4 / §7）接口层验收（2026-10-20）

只做只读调用与「必被拒绝」的负向调用，**不留下任何 CONNECTED 状态**（唯一会碰网络的是
C7 的真实 IMAP 登录失败用例，它天然不写库）。

  C1  GET  /api/v1/connectors                   200 + 恰好 2 个（qq_mail / wechat_work）
  C2  连接器就绪度                              qq_mail=true；wechat_work=false（平台未配 corpId）
  C3  字段白名单                                列表项只含约定字段，**不含** credential/authRef/secret/authCode
  C4  GET  /api/v1/connectors/qq_mail            mode=CREDENTIAL + fields=[email,authCode]，authCode 为 password
  C5  POST /qq_mail/connect/start               mode=CREDENTIAL，无 authUrl（凭据式不走跳转）
  C6  POST /qq_mail/connect/credential 非法邮箱  业务码 400 + 文案「合法的邮箱地址」，且状态仍 NEED_AUTH
  C7  POST /qq_mail/connect/credential 空授权码  业务码 400 + 文案「授权码不能为空」
  C8  POST /qq_mail/connect/credential 假授权码  **真实连 imap.qq.com** 登录失败 → 业务码 400 + 文案「QQ邮箱登录失败」，
                                                且**仍为 NEED_AUTH**（证明「先校验成功再落库」，没有假 CONNECTED）
  C9  POST /wechat_work/connect/start           业务码 400 + 缺配置提示，且响应里**没有 authUrl**（不返回假授权链接）
  C10 GET  /wechat_work/callback?state=forged   302 且 Location 指向本站失败页；连接状态仍 NEED_AUTH（伪造 state 绝不写库）
  C11 POST /qq_mail/verify（未连接时）            业务码 400 + 「未处于已连接状态」
  C12 POST /qq_mail/disconnect                  幂等：业务码 0 + status=NEED_AUTH
  C13 GET  /api/v1/connectors（无 token）         HTTP 401（用户维度隔离，未登录不可读）
  C14 GET  /api/v1/plugins                      200 + 每项键**恰好**为 code/name/description/domain/riskLevel/requiresApproval
                                                （绝不泄露 endpoint / auth_ref / input_schema）

用法：
    python scripts/_verify_connectors.py [--base http://127.0.0.1:8080]
前置：后端在线且 V96 已执行（首次启动自动建表 + 种子）。缺前置时脚本会明说而非静默 SKIP。
退出码 = 失败项数。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

RESULTS = []
ALLOWED_CONNECTOR_KEYS = {
    "code", "name", "group", "icon", "summary", "authMode", "configReady",
    "status", "accountLabel", "connectedAt", "lastCheckedAt", "lastError",
    "isPlatformManaged", "configHint",
}
ALLOWED_PLUGIN_KEYS = {"code", "name", "description", "domain", "riskLevel", "requiresApproval"}
# ⚠️ 只扫「键名」，不扫整串 JSON：`authMode` 的合法取值就是 "CREDENTIAL"，整串扫描会自造假阳性
#    （2026-10-20 实测踩过）。凭据值是否泄漏另用「密文前缀 enc:」与「提交过的明文授权码」两条查。
FORBIDDEN_KEY_SUBSTR = ("credential", "authref", "auth_ref", "secret", "authcode", "password")


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " —— " + detail)


def call(base, path, method="GET", token=None, body=None, timeout=25):
    """返回 (http_status, headers, raw_text)。4xx/5xx 不抛异常；302 单独处理。"""
    url = base.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def login(base, username, password):
    st, _, raw = call(base, "/api/v1/auth/login", "POST",
                      body={"username": username, "password": password})
    d = jload(raw) or {}
    return (d.get("data") or {}).get("accessToken"), st, d


def biz_fail(name, st, d, expect_frag):
    """断言「业务失败」：HTTP 200（401/403/404 除外）+ body.code != 0 + 文案含片段。"""
    if d is None:
        rec(name, False, "响应不是 JSON（HTTP %s）" % st)
        return
    code = d.get("code")
    msg = d.get("message") or ""
    ok = (st == 200 and code not in (None, 0) and expect_frag in msg)
    rec(name, ok, "HTTP=%s code=%s message=%r（期望含 %r）" % (st, code, msg[:120], expect_frag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOA_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== 连接器中心接口验收 @ %s ==" % base)
    token, st, d = login(base, args.user, args.password)
    if not token:
        print("  [FATAL] 登录失败（HTTP %s，%s）—— 后端未就绪或账号密码变更，无法继续"
              % (st, (d or {}).get("message")))
        return 1
    print("  登录成功：%s" % args.user)

    # ---------- C1 / C2 / C3 列表 + 就绪度 + 白名单 ----------
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    d = jload(raw) or {}
    items = d.get("data") or []
    codes = sorted(i.get("code") for i in items)
    rec("C1 连接器目录 = 2 个", st == 200 and d.get("code") == 0 and codes == ["qq_mail", "wechat_work"],
        "HTTP=%s code=%s codes=%s" % (st, d.get("code"), codes))

    by_code = {i.get("code"): i for i in items}
    qq_ready = (by_code.get("qq_mail") or {}).get("configReady")
    ww_ready = (by_code.get("wechat_work") or {}).get("configReady")
    ww_hint = (by_code.get("wechat_work") or {}).get("configHint")
    rec("C2 就绪度 qq_mail=true / wechat_work=false",
        qq_ready is True and ww_ready is False,
        "qq_mail.configReady=%s wechat_work.configReady=%s hint=%r" % (qq_ready, ww_ready, ww_hint))

    extra = set()
    leaked = []
    for it in items:
        extra |= (set(it.keys()) - ALLOWED_CONNECTOR_KEYS)
        leaked += [k for k in it.keys() if any(s in k.lower() for s in FORBIDDEN_KEY_SUBSTR)]
    cipher_leak = "enc:" in raw
    rec("C3 列表字段白名单（不泄露凭据字段/密文）",
        not extra and not leaked and not cipher_leak,
        "多余键=%s 敏感键名=%s 密文前缀=%s" % (sorted(extra) or "无", sorted(set(leaked)) or "无",
                                              "出现" if cipher_leak else "无"))

    # ---------- C4 详情 ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail", token=token)
    d = jload(raw) or {}
    det = d.get("data") or {}
    fields = det.get("fields") or []
    fmap = {f.get("key"): f for f in fields}
    ok4 = (st == 200 and det.get("mode") == "CREDENTIAL"
           and set(fmap) == {"email", "authCode"}
           and (fmap.get("authCode") or {}).get("type") == "password"
           and (fmap.get("email") or {}).get("required") is True)
    rec("C4 qq_mail 详情 = 凭据式两字段", ok4,
        "mode=%s fields=%s authCodeType=%s" % (det.get("mode"), sorted(fmap),
                                               (fmap.get("authCode") or {}).get("type")))

    # ---------- C5 start（凭据式不跳转） ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/connect/start", "POST",
                      token=token, body={"returnPath": "/"})
    d = jload(raw) or {}
    stt = d.get("data") or {}
    rec("C5 qq_mail start = CREDENTIAL 无 authUrl",
        st == 200 and d.get("code") == 0 and stt.get("mode") == "CREDENTIAL" and not stt.get("authUrl"),
        "mode=%s authUrl=%s" % (stt.get("mode"), stt.get("authUrl")))

    # ---------- C6 非法邮箱 ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/connect/credential", "POST",
                      token=token, body={"values": {"email": "not-an-email", "authCode": "x"}})
    biz_fail("C6 非法邮箱被拒（400）", st, jload(raw), "合法的邮箱地址")

    # ---------- C7 空授权码 ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/connect/credential", "POST",
                      token=token, body={"values": {"email": "someone@qq.com", "authCode": "  "}})
    biz_fail("C7 空授权码被拒（400）", st, jload(raw), "授权码不能为空")

    # ---------- C8 假授权码：真实 IMAP 校验失败 ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/connect/credential", "POST",
                      token=token, body={"values": {"email": "sentinel_probe@qq.com",
                                                    "authCode": "fakeauthcode0000000"}})
    d = jload(raw) or {}
    ok8 = st == 200 and d.get("code") not in (None, 0) and "登录失败" in (d.get("message") or "")
    rec("C8 假授权码真实 IMAP 校验失败（400）", ok8,
        "HTTP=%s code=%s message=%r" % (st, d.get("code"), (d.get("message") or "")[:140]))

    # 失败后必须仍为 NEED_AUTH（先校验成功再落库）
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    qq = {i.get("code"): i for i in ((jload(raw) or {}).get("data") or [])}.get("qq_mail") or {}
    rec("C8b 校验失败后未落库（仍 NEED_AUTH）", qq.get("status") == "NEED_AUTH" and not qq.get("accountLabel"),
        "status=%s accountLabel=%s" % (qq.get("status"), qq.get("accountLabel")))
    rec("C8c 响应不含提交的授权码明文", "fakeauthcode0000000" not in raw and "enc:" not in raw,
        "明文出现=%s 密文前缀=%s" % ("fakeauthcode0000000" in raw, "enc:" in raw))

    # ---------- C9 企业微信未配置：拒绝且不给假链接 ----------
    st, _, raw = call(base, "/api/v1/connectors/wechat_work/connect/start", "POST",
                      token=token, body={"returnPath": "/"})
    d = jload(raw) or {}
    ok9 = (st == 200 and d.get("code") not in (None, 0)
           and "corpId" in (d.get("message") or "") and "authUrl" not in raw)
    rec("C9 企业微信未配 → 400 且无 authUrl", ok9,
        "code=%s message=%r authUrl出现=%s" % (d.get("code"), (d.get("message") or "")[:120],
                                               "authUrl" in raw))

    # ---------- C10 伪造 state 回调 ----------
    st, hdrs, raw = call(base, "/api/v1/connectors/wechat_work/callback?code=fakecode&state=forged_by_sentinel")
    loc = (hdrs or {}).get("Location") or ""
    ok10 = st == 302 and "result=fail" in loc and loc.startswith("/")
    rec("C10 伪造 state 回调 → 302 失败页（不写库）", ok10,
        "HTTP=%s Location=%r" % (st, loc))
    st, _, raw = call(base, "/api/v1/connectors", token=token)
    ww = {i.get("code"): i for i in ((jload(raw) or {}).get("data") or [])}.get("wechat_work") or {}
    rec("C10b 伪造 state 后 wechat_work 仍 NEED_AUTH", ww.get("status") == "NEED_AUTH",
        "status=%s accountLabel=%s" % (ww.get("status"), ww.get("accountLabel")))

    # ---------- C11 未连接时 verify ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/verify", "POST", token=token, body={})
    biz_fail("C11 未连接时 verify 被拒（400）", st, jload(raw), "未处于已连接状态")

    # ---------- C12 disconnect 幂等 ----------
    st, _, raw = call(base, "/api/v1/connectors/qq_mail/disconnect", "POST", token=token, body={})
    d = jload(raw) or {}
    rec("C12 disconnect 幂等 → NEED_AUTH",
        st == 200 and d.get("code") == 0 and (d.get("data") or {}).get("status") == "NEED_AUTH",
        "code=%s data=%s" % (d.get("code"), d.get("data")))

    # ---------- C13 未登录 401 ----------
    st, _, raw = call(base, "/api/v1/connectors")
    rec("C13 未登录访问 401", st == 401, "HTTP=%s body=%r" % (st, raw[:100]))

    # ---------- C14 插件清单字段白名单 ----------
    st, _, raw = call(base, "/api/v1/plugins", token=token)
    d = jload(raw) or {}
    plist = d.get("data") or []
    bad = set()
    for p in plist:
        bad |= (set(p.keys()) - ALLOWED_PLUGIN_KEYS)
    low = raw.lower()
    leaks = [k for k in ("endpoint", "auth_ref", "input_schema", "authref") if k in low]
    rec("C14 /v1/plugins 字段白名单", st == 200 and d.get("code") == 0 and not bad and not leaks,
        "HTTP=%s 条数=%s 多余键=%s 泄露关键字=%s" % (st, len(plist), sorted(bad) or "无",
                                                    leaks or "无"))

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    if fails:
        print("失败项：")
        for n, _, det in fails:
            print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
