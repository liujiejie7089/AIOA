#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：企业微信 OAuth 网页授权「静默登录」（V100，2026-10-28）

  W1  GET  /api/v1/auth/wecom/start            302 + Location 指向 open.weixin.qq.com，
                                               scope=snsapi_privateinfo + agentid + state（state 已落库）
  W2  GET  /api/v1/auth/wecom/callback?state=伪造  302 回 H5 首页失败态，绝不换身份/写绑定
  W3  GET  /api/v1/auth/wecom/callback?code=fake&state=真实  一次性 state 即废；
                                               gettoken/getuserinfo 失败（假 code）⇒ 302 fail，不写绑定
  W4  GET  /api/v1/auth/wecom/status?state=伪造    400（无此 pending 身份）
  W5  POST /api/v1/auth/wecom/bind（无 token）    401（绑定必须登录态）
  W6  state 一次性：W3 用过的 state 再回调        302 fail（state 已使用）

用法：
    NO_PROXY='*' python scripts/_verify_wecom_login.py [--base http://127.0.0.1:8080]
前置：后端在线且 V100 已执行；连接器配置已配（未配时 W1 断言文案「未配置」也成立）。
退出码 = 失败项数。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request

RESULTS = []


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """验收必须看到 302 本身（Location 断言）：不让 urllib 自动跟随到企业微信服务器。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def call(base, path, method="GET", token=None, body=None, timeout=25, extra_headers=None):
    req = urllib.request.Request(base.rstrip("/") + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with _OPENER.open(req, data=data, timeout=timeout) as resp:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args()
    base = args.base
    hdrs = {"Origin": base, "Host": base.split("//", 1)[1]}

    print("== 企业微信 OAuth 静默登录验收 @ %s ==" % base)

    # ---------- W1 start：授权 URL 构造 ----------
    st, hd, raw = call(base, "/api/v1/auth/wecom/start?returnPath=/aios/h5/", extra_headers=hdrs)
    loc = (hd or {}).get("Location") or ""
    d = jload(raw) or {}
    msg = d.get("message") or ""
    if st == 302:
        ok = ("open.weixin.qq.com/connect/oauth2/authorize" in loc
              and "scope=snsapi_privateinfo" in loc and "agentid=" in loc
              and "response_type=code" in loc and "state=" in loc
              and "#wechat_redirect" in loc)
        rec("W1 start → 302 授权页（snsapi_privateinfo + agentid + 一次性 state）", ok,
            "Location=%r" % loc[:90])
        m = re.search(r"[?&]state=([0-9a-f]+)", loc)
        state = m.group(1) if m else None
    else:
        # 未配置凭据（如被配置管理哨兵清除）时 start 明确 400 拒绝，同样算通过（不返回假授权链接）
        ok = st == 200 and d.get("code") not in (None, 0) and "corpId" in msg and "open.weixin" not in raw
        rec("W1 未配置凭据 → 明确拒绝且无授权链接", ok, "HTTP=%s message=%r" % (st, msg[:80]))
        state = None

    # ---------- W2 伪造 state 回调 ----------
    st, hd, raw = call(base, "/api/v1/auth/wecom/callback?code=fakecode&state=forged_by_sentinel")
    loc = (hd or {}).get("Location") or ""
    ok = st == 302 and "wecom_login=fail" in loc and "wecom_token=" not in loc
    rec("W2 伪造 state 回调 → 302 失败态（无令牌、不换身份）", ok,
        "HTTP=%s Location=%r" % (st, loc[:80]))

    # ---------- W3 真实 state + 假 code：state 一次性即废，绝不写绑定 ----------
    if state:
        st, hd, raw = call(base, "/api/v1/auth/wecom/callback?code=fakecode&state=" + state)
        loc = (hd or {}).get("Location") or ""
        ok = st == 302 and "wecom_token=" not in loc
        rec("W3 假 code 回调 → 302 失败态（不签发令牌）", ok,
            "HTTP=%s Location=%r" % (st, loc[:80]))
        # ---------- W6 state 一次性 ----------
        st, hd, raw = call(base, "/api/v1/auth/wecom/callback?code=fakecode&state=" + state)
        loc = (hd or {}).get("Location") or ""
        ok6 = st == 302 and "state" in loc and "wecom_token=" not in loc
        rec("W6 state 一次性（重复回调被拒）", ok6, "HTTP=%s Location=%r" % (st, loc[:80]))
    else:
        # 无凭据时 W1 已断言「明确拒绝」，W3/W6 的前置（真实 state）不成立，记 SKIP 不计失败
        print("  [SKIP] W3 假 code 回调 / W6 state 一次性：W1 未拿到 state（凭据未配置）")

    # ---------- W4 伪造 state 查 pending ----------
    st, _, raw = call(base, "/api/v1/auth/wecom/status?state=forged_by_sentinel")
    rec("W4 伪造 state 查 pending 身份 → 400", st == 200 and (jload(raw) or {}).get("code") not in (None, 0),
        "HTTP=%s body=%r" % (st, raw[:80]))

    # ---------- W5 bind 无 token ----------
    st, _, raw = call(base, "/api/v1/auth/wecom/bind", "POST", body={"state": "whatever"})
    rec("W5 bind 无登录态 → 401", st == 401, "HTTP=%s" % st)

    fails = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
    for n, _, det in fails:
        print("  - %s：%s" % (n, det))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
