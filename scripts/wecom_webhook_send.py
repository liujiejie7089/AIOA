#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""企微群机器人（Webhook）发消息——**唯一零门槛的真机通道**。

为什么单独做这个：自建应用的业务接口（发消息/通讯录/身份）要求「企业可信 IP」，
而企微界面的硬规则是「配置可信 IP 前，必须先设置可信域名或接收消息服务器 URL」，
这两者都要求域名能通过企微校验（页面原文：备案主体与当前企业主体相同或有关联）。
没有备案域名 ⇒ 自建应用这条路走不通。

而群机器人只认 webhook 里的 key：不要求可信 IP、不要求域名、不要求企业认证。
官方文档（path/91770）只列了两条限制：仅群消息、20 条/分钟。

用法：
    export WECOM_WEBHOOK_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    python scripts/wecom_webhook_send.py --text "AIOS 连通性测试"
    python scripts/wecom_webhook_send.py --markdown "**加粗**\n> 引用" --at-mobile 13800001111

退出码：0 = 发送成功；2 = 失败（打印企微 errcode/errmsg）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.request

# 企微接口一律强制 IPv4 + 绕过系统代理（本机 http_proxy 出口可能是 IPv6，会被判成「IP 不可信」）
_orig_gai = socket.getaddrinfo


def _ipv4_only(host, port=None, family=0, type=0, proto=0, flags=0, *a):
    if isinstance(host, str) and host.endswith("qyapi.weixin.qq.com"):
        family = socket.AF_INET
    return _orig_gai(host, port, family, type, proto, flags, *a)


socket.getaddrinfo = _ipv4_only
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key="


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("WECOM_WEBHOOK_KEY", "").strip(),
                    help="群机器人 webhook 里的 key（也可用环境变量 WECOM_WEBHOOK_KEY）")
    ap.add_argument("--text", help="发文本消息")
    ap.add_argument("--markdown", help="发 markdown 消息")
    ap.add_argument("--at-mobile", default="", help="要 @ 的手机号，多个用逗号分隔；@all 用 @all")
    args = ap.parse_args()

    if not args.key:
        print("缺少 webhook key：用 --key 或环境变量 WECOM_WEBHOOK_KEY")
        print("获取方式：企微群 → 右上角 … → 群机器人 → 添加机器人 → 复制 Webhook 地址（末尾 key= 之后的部分）")
        return 2
    if not (args.text or args.markdown):
        print("至少给一个 --text 或 --markdown")
        return 2

    if args.markdown:
        payload = {"msgtype": "markdown", "markdown": {"content": args.markdown}}
    else:
        payload = {"msgtype": "text", "text": {"content": args.text}}
        if args.at_mobile:
            payload["text"]["mentioned_mobile_list"] = [
                s.strip() for s in args.at_mobile.split(",") if s.strip()
            ]

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK + args.key, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with _OPENER.open(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        print("[FAIL] 网络异常：", type(e).__name__, e)
        return 2

    if d.get("errcode") == 0:
        print("[ OK ] 已发送：", d.get("errmsg"))
        return 0
    print("[FAIL] errcode=%s errmsg=%s" % (d.get("errcode"), d.get("errmsg")))
    if d.get("errcode") == 93000:
        # 关键口径：93000 说明请求已到达企微（errmsg 里带 from ip），是 key 不被认，
        # 与网络/代理/可信 IP 都无关。别往 IP 白名单方向排查。
        print("       企微不认这个 key。按概率排查：")
        print("       1) 建的是「智能机器人」（带对话能力，无 webhook）→ 只能在群里建「消息推送/群机器人」")
        print("       2) 复制的是创建页的示例地址（key 是占位符）→ 去机器人详情页复制完整 Webhook 地址")
        print("       3) key 大小写被改过/字符被替换（UUID 大小写敏感）")
        print("       4) 机器人已删除或创建未完成")
        print("       正确形态：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<36位UUID>")
    elif d.get("errcode") == 45009:
        print("       超过 20 条/分钟，等一分钟再发")
    elif d.get("errcode") == 45033:
        print("       机器人已被移出群或停用")
    return 2


if __name__ == "__main__":
    sys.exit(main())
