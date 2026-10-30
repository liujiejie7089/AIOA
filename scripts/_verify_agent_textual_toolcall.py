#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""哨兵：模型把工具调用**写成正文**时，必须还原成真实调用（不许停在「正在查询」）。

要防的是什么
------------
2026-10-30 用户现场：问「帮我整理一下我的企业微信…」，数字人回了

    1. **群聊会话**：
       ```typescript
       functions.mcp__wecom_cli__recent_group_sessions({"days": 7})
       ```
    请稍等，我正在为您查询这些信息。

然后就停住了。原因不是前端、也不是 SSE：MiniMax-Text-01 把工具调用写进了**正文**，
`_parse_tool_calls` 于是拿到空列表 ⇒ 这一轮被当成「最终回答」⇒ 用那句「请稍等」收尾，
工具一次都没执行。同一形态在 2026-10-21 的 QQ 邮箱链路上也出现过（`chat_message.id=2513`）。

判据
----
- **U 段（离线，纯函数）**：拿库里的**真实坏样本原文**喂 `_rescue_textual_calls`，必须解析出
  对应的工具名与参数；同时把四种「不该救」的情形钉死（正文顺口提及 / 工具名不存在 /
  参数不是 JSON / 参数不是对象）。错救比不救更糟 —— 会凭空执行一个模型没打算调的写操作。
- **E 段（在线，不变量）**：真发一轮提问，断言最终回答里**每一个** `functions.<name>(`
  都出现在 `message.completed.tool_calls` 里。即「写在正文里的调用必须是真执行过的」，
  不允许出现「写了但没执行」。这条与模型当天是否听话无关，是可重复的确定性断言。

用法：python scripts/_verify_agent_textual_toolcall.py
退出码 = 失败项数。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

BASE = os.environ.get("AIOS_BASE", "http://127.0.0.1:8080")
USER, PASSWORD = "zhangsan", "User@123"
RESULTS: list[tuple[str, bool, str]] = []

# 库里 chat_message.id=2578 的**原文**（用户看到的那一条），一字未改。
REAL_SAMPLE = """您已成功绑定企业微信，您的姓名是 **刘洋**，并且有一个名为 **刘洋的机器人** 的数字员工为您服务。

接下来，我将为您整理最近的企业微信内容：

1. **群聊会话**：
   ```typescript
   functions.mcp__wecom_cli__recent_group_sessions({"days": 7})
   ```

2. **邮件内容**：
   ```typescript
   functions.mcp__wecom_cli__mail_search({"days": 7, "limit": 10})
   ```

请稍等，我正在为您查询这些信息。"""

ALLOWED = {"mcp__wecom_cli__recent_group_sessions", "mcp__wecom_cli__mail_search"}


def rec(name, ok, det=""):
    RESULTS.append((name, ok, det))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, (" —— " + det) if det else ""))


# ---------------------------------------------------------------- U 段：离线纯函数

def unit_checks(rescue):
    got = rescue(REAL_SAMPLE, ALLOWED)
    names = [c["name"] for c in got]
    rec("U1 库里真实坏样本 → 解析出 2 个真实调用（群会话 + 邮件）",
        names == ["mcp__wecom_cli__recent_group_sessions", "mcp__wecom_cli__mail_search"],
        "解析到 %s" % names)
    rec("U2 参数被还原成对象（days=7 / days=7,limit=10）",
        got and got[0]["arguments"] == {"days": 7}
        and len(got) > 1 and got[1]["arguments"] == {"days": 7, "limit": 10},
        json.dumps([c["arguments"] for c in got], ensure_ascii=False))
    rec("U3 还原出的 id 非空且互不相同（否则下游 tool_call_id 对不上会 400）",
        len({c["id"] for c in got}) == len(got) and all(c["id"] for c in got),
        str([c["id"] for c in got]))

    # —— 四种「不该救」——
    prose = "你可以调用 functions.mcp__wecom_cli__mail_search({\"days\": 7}) 来查邮件。"
    rec("U4 [负向] 正文里顺口提到的调用（不在代码块里）不救",
        rescue(prose, ALLOWED) == [], str(rescue(prose, ALLOWED)))

    unknown = "```typescript\nfunctions.mcp__nope__do_something({\"a\": 1})\n```"
    rec("U5 [负向] 工具名不在本轮工具表里 ⇒ 不救（防模型发明工具）",
        rescue(unknown, ALLOWED) == [], "allowed=%s" % sorted(ALLOWED))

    bad_json = "```typescript\nfunctions.mcp__wecom_cli__mail_search({days: 7})\n```"
    rec("U6 [负向] 参数不是合法 JSON ⇒ 不救（不猜、不补默认值）",
        rescue(bad_json, ALLOWED) == [], str(rescue(bad_json, ALLOWED)))

    not_obj = "```typescript\nfunctions.mcp__wecom_cli__mail_search([1,2])\n```"
    rec("U7 [负向] 参数是数组而非对象 ⇒ 不救",
        rescue(not_obj, ALLOWED) == [], str(rescue(not_obj, ALLOWED)))

    empty = "```typescript\nfunctions.mcp__wecom_cli__whoami()\n```"
    got_e = rescue(empty, {"mcp__wecom_cli__whoami"})
    rec("U8 无参调用还原为 arguments={}",
        len(got_e) == 1 and got_e[0]["arguments"] == {}, str(got_e))

    plain = "最近7天内，你的企业微信中有以下群聊有消息：成都易构…"
    rec("U9 [负向] 普通正文（无代码块）原样不救 ⇒ 零回归",
        rescue(plain, ALLOWED) == [], "len=%d" % len(plain))


# ---------------------------------------------------------------- E 段：在线不变量

def api(path, token=None, body=None, method="GET", timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def e2e_check():
    tok = api("/api/v1/auth/login", body={"username": USER, "password": PASSWORD}, method="POST")
    token = tok["data"]["accessToken"]
    conv = api("/api/v1/conversations", token=token, method="POST",
               body={"title": "textual-toolcall-probe", "appCode": "chat", "workerId": None})
    cid = conv["data"]["id"] if isinstance(conv.get("data"), dict) else conv["data"]
    run = api("/api/v1/conversations/%s/runs" % cid, token=token, method="POST",
              body={"text": "帮我整理一下我的企业微信，汇报一下里面最近的内容",
                    "context": {}, "model_ref": None})
    rid = run["data"]["runId"]

    h = {"Accept": "text/event-stream", "Authorization": "Bearer " + token}
    req = urllib.request.Request(BASE + "/api/v1/runs/%s/events" % rid, headers=h)
    content, completed, calls, events = "", None, [], []
    with urllib.request.urlopen(req, timeout=180) as resp:
        buf = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                txt = frame.decode("utf-8", "replace")
                ev, data = None, ""
                for line in txt.split("\n"):
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        data += line[5:].strip()
                if not ev:
                    continue
                events.append(ev)
                try:
                    payload = json.loads(data) if data else {}
                except json.JSONDecodeError:
                    payload = {}
                if ev == "message.delta":
                    content += str(payload.get("text") or "")
                elif ev == "message.completed":
                    completed = payload
                    calls = payload.get("tool_calls") or []
    called = {(c.get("name") or "").replace("mcp__", "mcp__") for c in calls}
    written = []
    for name in ALLOWED | {"mcp__wecom_cli__whoami", "mcp__wecom_cli__session_messages"}:
        if ("functions." + name + "(") in content:
            written.append(name)

    rec("E1 一轮真实提问能正常收尾（出现 message.completed + run.completed）",
        completed is not None and "run.completed" in events,
        "events=%s" % (sorted(set(events)),))
    missing = [n for n in written if n not in called]
    rec("E2 [不变量] 正文里写出的调用必须都真执行过（写了没执行 = 会停在查询中）",
        not missing,
        "写在正文=%s 已执行=%s 缺=%s" % (written, [c.get("name") for c in calls], missing))
    rec("E3 回答不是「请稍等」的纯承诺（有工具结果或直接作答）",
        bool(calls) or ("请稍等" not in content and "正在为您查询" not in content),
        "tool_calls=%s content=%r" % ([c.get("name") for c in calls], content[-80:]))
    return cid, rid, content, calls


def main() -> int:
    from aios_ai.graph.nodes import _rescue_textual_calls

    print("== 模型把工具调用写成正文：兜底还原验收 @ %s ==" % BASE)
    print("-- U 段：离线纯函数（用库里真实坏样本）--")
    unit_checks(_rescue_textual_calls)
    print("-- E 段：在线不变量 --")
    try:
        e2e_check()
    except Exception as e:  # noqa: BLE001
        rec("E0 在线提问跑通", False, "%s: %s" % (type(e).__name__, e))

    failed = [r for r in RESULTS if not r[1]]
    print("\n== 汇总：%d 项，通过 %d，失败 %d ==" %
          (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n, _, det in failed:
        print("  - %s：%s" % (n, det))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
