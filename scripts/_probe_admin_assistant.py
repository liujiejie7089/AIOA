# -*- coding: utf-8 -*-
"""复现：管理端 AI 助手（/conversations → /runs → /runs/{id}/events SSE）到底卡在哪一步。

逐段打点，把「创建会话 / 创建 run / SSE 首包 / 收尾」四个环节分别定位，
避免只看到「按钮点不动」这种笼统现象。
"""
import json
import sys
import time

import httpx

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"

C = httpx.Client(timeout=90, trust_env=False)


def step(label, ok, detail=""):
    print(f"[{'OK ' if ok else 'FAIL'}] {label}" + (f"  | {str(detail)[:500]}" if detail else ""))
    return ok


def main():
    r = C.post(f"{API}/auth/login", json={"username": USER, "password": PWD, "tenantName": TENANT})
    d = r.json()
    if not step("1. 登录", d.get("code") == 0, d.get("message")):
        return 1
    h = {"Authorization": "Bearer " + d["data"]["accessToken"]}

    # 2. 会话列表
    r = C.get(f"{API}/conversations", headers=h)
    d = r.json()
    step("2. GET /conversations", d.get("code") == 0, f"http={r.status_code} count={len(d.get('data') or [])}")

    # 3. 建会话
    r = C.post(f"{API}/conversations", headers=h, json={"title": "管理端助手自检"})
    d = r.json()
    if not step("3. POST /conversations", d.get("code") == 0, d):
        return 1
    conv_id = d["data"]["id"]
    print("      conversationId =", conv_id)

    # 4. 建 run
    t0 = time.time()
    r = C.post(f"{API}/conversations/{conv_id}/runs", headers=h,
               json={"text": "你好，请用一句话自我介绍", "context": None})
    dt = time.time() - t0
    d = r.json()
    ok = d.get("code") == 0
    step(f"4. POST /conversations/{conv_id}/runs（{dt:.1f}s）", ok, d)
    if not ok:
        return 1
    run_id = d["data"]["runId"]
    print("      runId =", run_id)

    # 5. 订阅 SSE
    print("5. GET /runs/%s/events ..." % run_id)
    got_delta, got_done, err = 0, False, ""
    try:
        with C.stream("GET", f"{API}/runs/{run_id}/events", headers=h,
                      timeout=httpx.Timeout(90, read=90)) as s:
            print("      http =", s.status_code, dict(s.headers).get("content-type"))
            ev, data_buf = "", ""
            for line in s.iter_lines():
                if line.startswith("event:"):
                    ev = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf += line[5:].strip()
                elif line == "":
                    if ev:
                        print(f"      <- event={ev} data={data_buf[:300]}")
                        if ev == "message.delta":
                            got_delta += 1
                        if ev in ("message.completed", "run.completed"):
                            got_done = True
                        if ev in ("run.failed", "error", "run.error"):
                            err = data_buf[:300]
                    ev, data_buf = "", ""
                if got_done or err:
                    break
    except Exception as e:  # noqa: BLE001
        step("5. SSE 订阅异常", False, f"{type(e).__name__}: {e}")
        return 1

    step("5a. SSE 收到增量包", got_delta > 0, f"delta 包数={got_delta}")
    step("5b. SSE 正常收尾", got_done, err or "")
    step("5c. 无错误事件", not err, err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
