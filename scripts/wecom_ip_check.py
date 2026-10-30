#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""企业微信「可信 IP」自检（真机联调第一步）。

为什么需要它：`gettoken` **不校验**可信 IP，业务接口（agent/get、user/list、message/send）
**校验**。所以最常见的误判是「gettoken 成功 ⇒ 以为配好了」，结果一调工具就 60020。
本脚本两步都打，并把结论直接说出来。

用法（凭据走环境变量，避免留在命令行历史里）：
    export WECOM_CORP_ID=wwxxxxxxxxxxxxxxxx
    export WECOM_AGENT_ID=1000002
    export WECOM_CORP_SECRET=xxxx
    python scripts/wecom_ip_check.py

退出码：0 = IP 已加白且应用可用；1 = 60020（IP 未加白/已漂移）；2 = 其它错误（凭据等）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

# 强制 IPv4：企微可信 IP 只认 IPv4，双栈机器上默认可能走 IPv6（会报 60020 且看不出原因）
import socket

_orig_gai = socket.getaddrinfo


def _ipv4_only(host, port=None, family=0, type=0, proto=0, flags=0, *a):
    if isinstance(host, str) and host.endswith("qyapi.weixin.qq.com"):
        family = socket.AF_INET
    return _orig_gai(host, port, family, type, proto, flags, *a)


socket.getaddrinfo = _ipv4_only

# 本机存在系统代理；对企微直连必须绕过，否则出口 IP 变成代理的（多半是 IPv6）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str, timeout: int = 12) -> dict:
    with _OPENER.open(urllib.request.Request(url), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def my_ipv4() -> str:
    try:
        with _OPENER.open("https://ipv4.icanhazip.com", timeout=8) as r:
            return r.read().decode().strip()
    except Exception:
        return "(探测失败)"


def main() -> int:
    corp = os.environ.get("WECOM_CORP_ID", "").strip()
    agent = os.environ.get("WECOM_AGENT_ID", "").strip()
    secret = os.environ.get("WECOM_CORP_SECRET", "").strip()
    if not (corp and agent and secret):
        print("缺少环境变量：WECOM_CORP_ID / WECOM_AGENT_ID / WECOM_CORP_SECRET")
        return 2

    ip = my_ipv4()
    print("本机出口 IPv4 :", ip)
    print("（若下面报 60020，就把这个 IPv4 加进 企微管理端 → 应用 → 企业可信 IP）\n")

    q = urllib.parse.urlencode({"corpid": corp, "corpsecret": secret})
    try:
        tk = get(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{q}")
    except Exception as e:  # noqa: BLE001
        print("[FAIL] gettoken 网络异常：", type(e).__name__)
        return 2
    if tk.get("errcode") != 0:
        print("[FAIL] gettoken errcode=%s errmsg=%s" % (tk.get("errcode"), tk.get("errmsg")))
        print("       ⇒ corpId 或 secret 不对（与可信 IP 无关）")
        return 2
    print("[ OK ] gettoken 通过（说明 corpId + secret 正确；注意这一步不校验可信 IP）")

    token = tk.get("access_token", "")
    q2 = urllib.parse.urlencode({"access_token": token, "agentid": agent})
    try:
        ag = get(f"https://qyapi.weixin.qq.com/cgi-bin/agent/get?{q2}")
    except Exception as e:  # noqa: BLE001
        print("[FAIL] agent/get 网络异常：", type(e).__name__)
        return 2

    code = ag.get("errcode")
    if code == 0:
        members = len(((ag.get("allow_userinfos") or {}).get("user")) or [])
        print("[ OK ] agent/get 通过：应用名=%r agentid=%s 可见成员数=%s"
              % (ag.get("name"), ag.get("agentid"), members))
        if members == 0:
            print("       ⚠ 可见成员为 0：发消息会 81013/90236，请先在应用里设置可见范围")
        print("\n结论：可信 IP 已生效，该应用可用于发消息 / 通讯录。")
        return 0

    if code == 60020:
        print("[FAIL] agent/get errcode=60020 —— 当前出口 IP 不在该应用的可信 IP 白名单")
        print("       errmsg :", ag.get("errmsg"))
        print("       要做   : 企微管理端 → 应用管理 → 自建应用(agentid=%s) → 企业可信 IP" % agent)
        print("                → 添加 %s（只支持 IPv4，不支持网段/通配；建议顺手删掉已失效的旧 IP）" % ip)
        return 1

    print("[FAIL] agent/get errcode=%s errmsg=%s" % (code, ag.get("errmsg")))
    print("       常见：40013 corpId 错 / 40056 agentId 不属于该企业 / 301002 无权限")
    return 2


if __name__ == "__main__":
    sys.exit(main())
