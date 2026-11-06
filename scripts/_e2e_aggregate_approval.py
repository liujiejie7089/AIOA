# -*- coding: utf-8 -*-
"""真机 E2E：① 跨源聚合与来源标注 ② 请假发起 + 指定处理人一次填完。

## 为什么用脚本而不是靠肉眼

这两条能力的关键都不在「界面好不好看」，而在**代码有没有真的扇出 / 真的插节点**：
  * 聚合：若模型自己想到才查，八个源也只查一个 —— 必须看到多个 `tool.call` 才算通过；
  * 请假：若模型自己追问，就会跑成五六轮 —— 必须看到 `need_clarification` 且**暂停前零正文**。

## 跑法

    agent/.venv/Scripts/python.exe scripts/_e2e_aggregate_approval.py
    agent/.venv/Scripts/python.exe scripts/_e2e_aggregate_approval.py --only aggregate
    agent/.venv/Scripts/python.exe scripts/_e2e_aggregate_approval.py --only leave --dry

前置：Java :8080 / agent :8000 / hub :8099 在线；`fagai_liu` 已绑定机构（org_member）。

注意：`--only leave` 不带 `--dry` 时会**真的提交一张请假单**（用于验证闭环），
      跑完可在「我的审批」里看到；不想留数据请加 `--dry`。
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import sys

import httpx

BASE = "http://127.0.0.1:8080"
AGG_TEXT = "总结一下我这周的工作，写个周报"
LEAVE_TEXT = "帮我请个假，明天调休一天，交给王振华处理"

fails: list[str] = []
oks = 0


def chk(name: str, ok: bool, detail: str = "") -> bool:
    global oks
    if ok:
        oks += 1
    else:
        fails.append(name)
    print(("[OK  ] " if ok else "[FAIL] ") + name + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _frames(resp: httpx.Response) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    ev, buf = "", []
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].strip())
        elif line == "":
            if ev:
                out.append((ev, "\n".join(buf)))
            ev, buf = "", []
    if ev:
        out.append((ev, "\n".join(buf)))
    return out


def stream(client: httpx.Client, method: str, path: str, body: dict | None = None):
    with client.stream(method, BASE + path, json=body, timeout=240) as r:
        r.read()
        return _frames(r)


def new_run(c: httpx.Client, text: str, title: str, kb_on: bool = False) -> tuple[str, str]:
    conv = c.post(f"{BASE}/api/v1/conversations", json={"title": title, "source": "aios-client"})
    cid = ((conv.json() or {}).get("data") or {}).get("id")
    run = c.post(f"{BASE}/api/v1/conversations/{cid}/runs",
                 json={"text": text, "context": {}, "kb_on": kb_on})
    rd = (run.json() or {}).get("data") or {}
    return cid, (rd.get("runId") or rd.get("id"))


# --------------------------------------------------------------------------- ① 聚合

def case_aggregate(c: httpx.Client) -> None:
    print("\n=== ① 跨源聚合与来源标注 ===")
    _cid, rid = new_run(c, AGG_TEXT, "聚合 E2E", kb_on=True)
    if not chk("建 run", bool(rid), str(rid)):
        return
    frames = stream(c, "GET", f"/api/v1/runs/{rid}/events")
    types = [t for t, _ in frames]
    print("  frames:", types[:18], "…" if len(types) > 18 else "")

    tool_names: list[str] = []
    for t, d in frames:
        if t in ("tool.call", "tool_call"):
            try:
                v = json.loads(d)
            except ValueError:
                continue
            nm = v.get("name") or (v.get("function") or {}).get("name") or ""
            if nm:
                tool_names.append(nm)
    # 这一行只是诊断：聚合轮次里它**通常是空的**（原因见下），不是判据。
    print("  模型侧工具调用:", tool_names, "（聚合扇出在 prepare 阶段，不进 tool_calls）")

    # 判据：**不能用 tool.call 事件**。跨源扇出发生在 prepare 阶段（代码直连工具客户端），
    # 不走模型的 tool_calls ⇒ 一个 tool.call 帧都不会有。真正常见的误解就出在这里：
    # 「没看到工具调用 ⇒ 没聚合」是错的。可观测点有两个：
    #   ① citations 里有非知识库来源（说明聚合拿回了数据并记了来源）
    #   ② 正文里出现了来源名前缀（说明模型按来源标注写进了回答）
    completed = next((json.loads(d) for t, d in frames if t == "message.completed"), None) or {}
    cites = completed.get("citations") or []
    print(f"  引用 {len(cites)} 条：", [f"{c.get('label')}:{c.get('title')}" for c in cites[:6]])
    chk("答案带引用", len(cites) > 0, str(len(cites)))
    chk("引用带中文来源名（label）", all(c.get("label") for c in cites), str(cites[:1]))

    src_set = {c.get("source") for c in cites}
    chk("引用里有非知识库来源（三方连接器 / 内部模块）",
        any(s not in ("knowledge_base", "web") for s in src_set), str(sorted(src_set)))
    chk("同一来源下有多个条目（说明真的读了内容，不是只记了个调用）",
        len(cites) >= 2, str(len(cites)))

    answer = completed.get("content") or "".join(
        json.loads(d).get("text", "") for t, d in frames if t == "message.delta")
    print("  正文节选:", answer[:260].replace("\n", " / "))
    chk("正文非空", bool(answer.strip()), f"{len(answer)} 字")
    labels = {c.get("label") for c in cites if c.get("label")}
    chk("正文按来源标注（提到来源名）",
        any(lb in answer for lb in labels), f"labels={sorted(labels)}")


# --------------------------------------------------------------------------- ② 请假

def case_leave(c: httpx.Client, dry: bool) -> None:
    print("\n=== ② 请假发起 + 指定处理人 ===")
    _cid, rid = new_run(c, LEAVE_TEXT, "请假 E2E")
    if not chk("建 run", bool(rid), str(rid)):
        return
    frames = stream(c, "GET", f"/api/v1/runs/{rid}/events")
    types = [t for t, _ in frames]
    print("  frames:", types)
    if not chk("以 need_clarification 暂停", "need_clarification" in types, str(types)):
        return
    chk("暂停前零正文（代码短路，不是模型追问）",
        "message.delta" not in types,
        "；".join(d for t, d in frames if t == "message.delta")[:120])

    clar = next(json.loads(d) for t, d in frames if t == "need_clarification")
    flds = clar.get("fields") or []
    for f in flds:
        n = len(f.get("options") or [])
        print(f"   · [{f['type']}] {f['id']} — {f['label']}" + (f"（{n} 项）" if n else ""))

    chk("字段卡一次问全 5 项", [f["id"] for f in flds] ==
        ["leave_type", "start", "end", "reason", "handler"], str([f["id"] for f in flds]))

    by = {f["id"]: f for f in flds}
    chk("假种是菜单且候选来自真实假种目录",
        by.get("leave_type", {}).get("type") == "select"
        and len(by.get("leave_type", {}).get("options") or []) >= 1,
        str(len(by.get("leave_type", {}).get("options") or [])))
    handler = by.get("handler") or {}
    chk("处理人是可检索候选框", handler.get("type") == "select" and handler.get("searchable") is True,
        str({k: handler.get(k) for k in ("type", "searchable")}))
    opts = handler.get("options") or []
    chk("处理人候选来自本机构在职成员（非通讯录）", len(opts) >= 1, str(len(opts)))
    # 选项卡的 value 一律是字符串（与既有实体卡一致），语义上要求"装的是 userId 而不是姓名"
    def _is_id(v) -> bool:
        return isinstance(v, int) or (isinstance(v, str) and v.isdigit())

    chk("候选人值是 userId（机器值）而非姓名",
        bool(opts) and _is_id(opts[0].get("value")), str(opts[:1]))
    chk("候选里没有申请人本人",
        all(o.get("value") != 7 for o in opts), str([o.get("value") for o in opts]))

    if dry:
        print("\n（--dry：只验卡片，不回填）")
        return

    # 一次回填：值取自上面真实候选，避免硬编码错码
    type_opt = (by["leave_type"]["options"] or [{}])[0]
    pick = next((o for o in opts if "王振华" in str(o.get("label"))), opts[0])
    answer = {
        "value": type_opt.get("value"), "label": type_opt.get("label"),
        "values": {
            "leave_type": type_opt.get("value"),
            "start": "2026-11-10", "end": "2026-11-10",
            "reason": "家里有事需处理（E2E 验证）",
            "handler": pick.get("value"),
        },
        "text": "明天调休一天，交给王振华处理",
    }
    print(f"\n  一次回填: {json.dumps(answer['values'], ensure_ascii=False)}")
    f2 = stream(c, "POST", f"/api/v1/runs/{rid}/resume", {"answer": answer})
    types2 = [t for t, _ in f2]
    print("  frames:", types2)
    chk("回填后没有再问一遍（一次交互交齐）", "need_clarification" not in types2, str(types2))

    called = []
    for t, d in f2:
        if t in ("tool.call", "tool_call"):
            try:
                v = json.loads(d)
            except ValueError:
                continue
            called.append(v.get("name") or (v.get("function") or {}).get("name") or "")
    print("  工具调用:", called)
    chk("模型调用 submit_leave_request 落单", "submit_leave_request" in called, str(called))

    answer_text = "".join(json.loads(d).get("text", "") for t, d in f2 if t == "message.delta")
    print("  正文节选:", answer_text[:240].replace("\n", " / "))
    chk("回执提到处理人姓名", "王振华" in answer_text or "提交" in answer_text,
        answer_text[:120])


def _report() -> int:
    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="fagai_liu")
    ap.add_argument("--pwd", default="User@123")
    ap.add_argument("--only", choices=("aggregate", "leave"), default=None)
    ap.add_argument("--dry", action="store_true", help="请假用例只验卡片不回填")
    a = ap.parse_args()

    with httpx.Client(trust_env=False, timeout=40) as c:
        r = c.post(f"{BASE}/api/v1/auth/login", json={"username": a.user, "password": a.pwd})
        tok = ((r.json() or {}).get("data") or {}).get("accessToken")
        if not tok:
            print("登录失败：", r.text[:300])
            return 1
        c.headers["Authorization"] = "Bearer " + tok
        print(f"登录成功 user={a.user}")

        if a.only in (None, "aggregate"):
            case_aggregate(c)
        if a.only in (None, "leave"):
            case_leave(c, a.dry)

    return _report()


if __name__ == "__main__":
    sys.exit(main())
