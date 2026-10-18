# -*- coding: utf-8 -*-
"""探针：确认本环境后端(:8080)+agent(:8000)+LLM 是否对对话 runs 有真实响应。"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
USER, PWD = "fagai_liu", "User@123"


def post(url, obj, token=None, timeout=30):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def read_sse(url, token, budget=120):
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    buf, code = [], 0
    try:
        with urllib.request.urlopen(req, timeout=budget) as r:
            code = r.status
            import time as _t
            deadline = _t.time() + budget
            while _t.time() < deadline:
                line = r.readline()
                if not line:
                    break
                buf.append(line.decode("utf-8", "replace"))
                j = "".join(buf)
                if "event:run.completed" in j or "event:run.failed" in j:
                    break
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:  # noqa: BLE001
        buf.append("EXC: %s" % e)
    return code, "".join(buf)


def main():
    try:
        st, b = post(BASE + "/auth/login", {"username": USER, "password": PWD})
    except Exception as e:
        print("LOGIN_FAIL", e)
        return 1
    if b.get("code") != 0:
        print("LOGIN_CODE", b.get("message"))
        return 1
    tok = b["data"]["accessToken"]
    print("LOGIN_OK")

    st, b = post(BASE + "/conversations", {"title": "probe"}, tok)
    if b.get("code") != 0:
        print("CONV_FAIL", b.get("message"))
        return 1
    cid = b["data"]["id"]
    print("CONV_OK", cid)

    st, b = post("%s/conversations/%s/runs" % (BASE, cid), {"text": "你好", "context": {}}, tok)
    if b.get("code") != 0:
        print("RUN_FAIL", b.get("message"))
        return 1
    rid = b["data"]["runId"]
    print("RUN_QUEUED", rid)

    code, sse = read_sse("%s/runs/%s/events" % (BASE, rid), tok)
    print("SSE_HTTP", code, "bytes", len(sse))
    # 打印前若干事件类型
    evs = []
    for ln in sse.splitlines():
        if ln.startswith("event:"):
            evs.append(ln[6:].strip())
    print("EVENTS", evs[:20])
    # 抽取回答
    deltas = []
    for ln in sse.splitlines():
        if not ln.startswith("data:"):
            continue
        raw = ln[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        body = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        if not isinstance(body, dict):
            continue
        v = body.get("delta")
        if v is None and "text" in body:
            v = body.get("text")
        if isinstance(v, str) and v:
            deltas.append(v)
    ans = "".join(deltas)
    print("ANSWER_LEN", len(ans))
    print("ANSWER_HEAD", ans[:200].replace("\n", " ⏎ "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
