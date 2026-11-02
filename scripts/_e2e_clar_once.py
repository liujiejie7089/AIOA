# -*- coding: utf-8 -*-
"""真机 E2E：一句话 → 澄清卡（选人 + 填内容）→ **一次** resume → 继续执行。

验的是用户报的那条：以前「点完人，气泡就没下文了」。现在的判据是

    resume 之后**必须**继续推进（调工具执行 / 二次确认 / 给出结果），
    不能又回到「同一个问题再问一遍」。

跑法：
    agent/.venv/Scripts/python.exe scripts/_e2e_clar_once.py
    agent/.venv/Scripts/python.exe scripts/_e2e_clar_once.py --text "帮我给同事发条消息说下午三点开会"
    agent/.venv/Scripts/python.exe scripts/_e2e_clar_once.py --dry     # 只看第一段暂停帧，不回填

前置：Java :8080 / agent :8000 / hub :8099 在线，企微连接器已授权（zhangsan）。
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

BASE = "http://127.0.0.1:8080"
DEFAULT_TEXT = "帮我给同事发条消息说下午三点开会"

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
    """把 SSE 响应拆成 [(event, data)]。"""
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
    with client.stream(method, BASE + path, json=body, timeout=180) as r:
        r.read()
        return _frames(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--user", default="zhangsan")
    ap.add_argument("--pwd", default="User@123")
    ap.add_argument("--dry", action="store_true", help="只跑到第一段暂停帧")
    a = ap.parse_args()

    with httpx.Client(trust_env=False, timeout=30) as c:
        r = c.post(f"{BASE}/api/v1/auth/login",
                   json={"username": a.user, "password": a.pwd})
        tok = ((r.json() or {}).get("data") or {}).get("accessToken")
        if not tok:
            print("登录失败：", r.text[:300])
            return 1
        c.headers["Authorization"] = "Bearer " + tok

        conv = c.post(f"{BASE}/api/v1/conversations",
                      json={"title": "HITL 一次交齐 E2E", "source": "aios-client"})
        cid = ((conv.json() or {}).get("data") or {}).get("id")
        chk("建会话", bool(cid), str(cid))
        if not cid:
            return 1

        run = c.post(f"{BASE}/api/v1/conversations/{cid}/runs",
                     json={"text": a.text, "context": {}, "kb_on": False})
        _rd = (run.json() or {}).get("data") or {}
        rid = _rd.get("runId") or _rd.get("id")      # 建 run 返回 runId（不是 id）
        chk("建 run", bool(rid), str(rid))
        if not rid:
            return 1

        print(f"\n=== 第一段流（user={a.user}, run={rid}）===")
        f1 = stream(c, "GET", f"/api/v1/runs/{rid}/events")
        types = [t for t, _ in f1]
        print("  frames:", types)
        chk("第一段以 need_clarification 暂停", "need_clarification" in types, str(types))
        chk("暂停前没有正文（说明是代码短路，不是模型列名单）",
            "message.delta" not in types,
            "；".join(d for t, d in f1 if t == "message.delta")[:120])

        clar = next((json.loads(d) for t, d in f1 if t == "need_clarification"), None) or {}
        opts = clar.get("suggested_options") or []
        print(f"  question: {clar.get('question')}")
        for o in opts:
            print("   ·", o)
        chk("候选以按钮形式给出", len(opts) >= 1, f"{len(opts)} 个")
        chk("选项带 needs_text（同一次交互里要内容）",
            bool(opts) and all(o.get("needs_text") is True for o in opts),
            str([o.get("text_label") for o in opts][:2]))
        chk("value 是机器值、label 是人看的名字",
            bool(opts) and opts[0]["value"] != opts[0]["label"], str(opts[:1]))

        if a.dry or not opts:
            return _report()

        # ---- 一次回填：选中值 + 补充内容，同一个对象 ----
        answer = {"value": opts[0]["value"], "label": opts[0]["label"],
                  "text": "下午三点开会"}
        print(f"\n=== resume 一次回填 {json.dumps(answer, ensure_ascii=False)} ===")
        f2 = stream(c, "POST", f"/api/v1/runs/{rid}/resume", {"answer": answer})
        types2 = [t for t, _ in f2]
        print("  frames:", types2)
        text2 = "".join(json.loads(d).get("text", "") for t, d in f2 if t == "message.delta")
        if text2:
            print("  正文:", text2[:300].replace("\n", " / "))

        chk("resume 后没有立刻再弹同一张澄清卡（不再多轮往返）",
            "need_clarification" not in types2, str(types2))
        chk("resume 后有实质推进（正文 / 工具 / 二次确认 / 完成，至少有一样）",
            bool(text2) or any(t in types2 for t in
                               ("tool.call", "need_confirm", "need_form", "run.completed")),
            str(types2))
        if "need_confirm" in types2:
            cfm = json.loads(next(d for t, d in f2 if t == "need_confirm"))
            print("  二次确认:", cfm.get("title"), "/", cfm.get("description"))
            chk("停在二次确认（写操作前确认，属预期）", bool(cfm.get("title")), str(cfm)[:160])

        # 收尾：把确认卡取消掉，别在服务器上留一个待确认的写操作
        if "need_confirm" in types2:
            f3 = stream(c, "POST", f"/api/v1/runs/{rid}/resume", {"decision": False})
            print("  取消后 frames:", [t for t, _ in f3])

    return _report()


def _report() -> int:
    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
