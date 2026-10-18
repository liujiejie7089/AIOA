# -*- coding: utf-8 -*-
"""哨兵：第三道闸（确定性开表）不得在 HITL 续跑时重弹同一张表单
================================================================================

## 防的是什么缺陷

`RunService.maybeOpenSingleForm` 用 `lastUserText(run)` 判「用户原话点名了该数字人的唯一任务」。
判据本身正确，但 `proxyAgentRun` 被**首发**（`/internal/v1/runs`）与**续跑**
（`/internal/v1/runs/{runId}/resume`）共用，而续跑**不新建 run、不落新用户消息** ⇒
`lastUserText` 取到的仍是最初那句原话，判据必然再次为真 ⇒ 用户填完表单续跑时会**再弹一次**
同一张表，可无限循环。

修法：显式形参 `allowSingleFormFallback`，首发 true / 续跑 false（单一判定点）。

## 判据

  U1  首发出 `need_form`，且 `form_code` == 该数字人 capability 的 form_code
  U2  首发收口后 run 处于 `WAITING_INPUT`（判据：`/resume` 返回 200，而不是 400「不是等待澄清状态」）
  U3  续跑这条 SSE 流**不含任何 `need_form` 帧**（核心判据）
  U4  续跑流不是 `run.failed`
  U5  负向对照：同一数字人对「你好」这类问候**不出** `need_form`（证明判据不是无条件触发）

## 跑法

    agent/.venv/Scripts/python.exe scripts/_verify_form_resume_no_reopen.py
    ... --worker 1226 --utterance "帮我办理工会事项办理"

前置：后端 :8080 在跑（健康码 401 即 up）、agent :8000 在跑、MySQL 可读。
续跑用 `answer=null`（放弃澄清），避免真的写入业务单据污染演示数据。
退出码 = 失败项数；前置不满足时退出 2 并打印 SKIP 原因。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080/api/v1"
USER, PWD = "wjj_xu", "User@123"
SSE_TIMEOUT = 180


def log(msg: str) -> None:
    print(msg, flush=True)


def _req(path: str, method: str = "GET", body=None, token: str | None = None, timeout: int = 30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _unwrap(payload: dict) -> dict:
    if isinstance(payload, dict) and "code" in payload:
        if payload.get("code") != 0:
            raise RuntimeError(f"业务错误 {payload.get('code')}: {payload.get('message')}")
        return payload.get("data") or {}
    return payload


def _sse_stream(req: urllib.request.Request, stop_on_form: bool) -> tuple[list[tuple[str, str]], int]:
    """读一条 SSE 流。stop_on_form=True 时见 need_form 即收尾（首发用）；
    否则读到 completed/failed 收尾（续跑用，要看完整个流才能断言「没有 need_form」）。"""
    events: list[tuple[str, str]] = []
    cur_event, cur_data = "message", []
    try:
        with urllib.request.urlopen(req, timeout=SSE_TIMEOUT) as resp:
            status = resp.status
            while True:
                raw = resp.readline()
                if not raw:
                    break
                line = raw.decode("utf-8").rstrip("\r\n")
                if line == "":
                    if cur_data:
                        events.append((cur_event, "\n".join(cur_data)))
                        hit_form = stop_on_form and cur_event == "need_form"
                        # 只在**终态帧**收尾：message.completed 之后还有 run.completed，
                        # 而 markWaitingInput 发生在流结束时。停在 message.completed 会早断。
                        done = cur_event in ("run.completed", "run.failed")
                        if hit_form or done:
                            return events, status
                    cur_event, cur_data = "message", []
                    continue
                if line.startswith("event:"):
                    cur_event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    cur_data.append(line[len("data:"):].strip())
            return events, status
    except urllib.error.HTTPError as e:
        return events, e.code


def _form_code_of(events: list[tuple[str, str]]) -> str | None:
    for name, data in events:
        if name != "need_form":
            continue
        try:
            obj = json.loads(data)
        except Exception:
            continue
        for key in ("form_code", "formCode"):
            if obj.get(key):
                return obj[key]
    return None


def _cap_form_code(worker: int) -> str | None:
    import pymysql

    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                           database="aios", charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select form_code from worker_capability "
                "where worker_id=%s and deleted_at is null and enabled=1 "
                "and form_code is not null and form_code<>'' ", (worker,))
            rows = [r["form_code"] for r in cur.fetchall()]
    finally:
        conn.close()
    uniq = sorted(set(rows))
    return uniq[0] if len(uniq) == 1 else None


def _cleanup(conv_id, token: str) -> None:
    try:
        _req(f"/conversations/{conv_id}", "DELETE", None, token)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", type=int, default=1226)
    ap.add_argument("--utterance", default="帮我办理工会事项办理")
    ap.add_argument("--tenant", type=int, default=3)
    args = ap.parse_args()

    cap_code = _cap_form_code(args.worker)
    if not cap_code:
        log(f"[SKIP] worker {args.worker} 没有唯一 enabled 的 form_code，第三条闸不适用")
        return 2

    try:
        login = _unwrap(_req("/auth/login", "POST", {"username": USER, "password": PWD}))
    except Exception as e:
        log(f"[SKIP] 登录失败（后端未起？）：{e}")
        return 2
    token = login.get("accessToken") or login.get("token")
    if not token:
        log(f"[SKIP] 登录未返回 accessToken：{login}")
        return 2

    fails: list[str] = []
    conv_id = None
    try:
        conv = _unwrap(_req("/conversations", "POST",
                            {"title": f"续跑重弹哨兵-{args.worker}", "workerId": args.worker}, token))
        conv_id = conv.get("id") or conv.get("conversationId")
        run = _unwrap(_req(f"/conversations/{conv_id}/runs", "POST", {"text": args.utterance}, token))
        run_id = run.get("runId") or run.get("id")

        req = urllib.request.Request(f"{BASE}/runs/{run_id}/events")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Accept", "text/event-stream")
        # 必须读**到流结束**，不能见 need_form 就断：真实前端也会读完收尾帧，
        # 而后端是在流结束时才 completeRun → markWaitingInput。早断会让 run 卡在 RUNNING，
        # 后续 /resume 直接 400/500（本哨兵首版就踩了这个，误报成「未进 WAITING_INPUT」）。
        ev1, st1 = _sse_stream(req, stop_on_form=False)
        code1 = _form_code_of(ev1)
        log(f"[U1] 首发帧={[n for n, _ in ev1]} form_code={code1}")
        if not code1:
            fails.append("U1 首发出 need_form")
        elif code1 != cap_code:
            fails.append(f"U1 form_code 期望 {cap_code} 实得 {code1}")

        # U2/U3：续跑。answer=null（放弃澄清），不写业务数据。
        # markWaitingInput 在流结束的收口里落库，与客户端读到流尾有几毫秒竞态 ⇒ 非 200 时短重试。
        body = json.dumps({"answer": None}).encode("utf-8")
        ev2, st2 = [], 0
        for attempt in range(6):
            req2 = urllib.request.Request(f"{BASE}/runs/{run_id}/resume", data=body, method="POST")
            req2.add_header("Authorization", "Bearer " + token)
            req2.add_header("Content-Type", "application/json")
            req2.add_header("Accept", "text/event-stream")
            ev2, st2 = _sse_stream(req2, stop_on_form=False)
            if st2 == 200:
                break
            time.sleep(1)
        names2 = [n for n, _ in ev2]
        log(f"[U2] resume HTTP={st2}")
        log(f"[U3] 续跑帧={names2}")
        if st2 != 200:
            fails.append(f"U2 resume 返回 {st2}（期望 200，非 200 说明首发未进 WAITING_INPUT）")
        if "need_form" in names2:
            code2 = _form_code_of(ev2)
            fails.append(f"U3 续跑重弹表单 code={code2}（应关闭第三道闸）")
        if "run.failed" in names2:
            fails.append("U4 续跑以 run.failed 收尾")
    finally:
        if conv_id:
            _cleanup(conv_id, token)

    # U5 负向对照：问候不得触发确定性开表（冷启动新会话，避免沿用上文）
    conv2 = None
    try:
        conv2 = _unwrap(_req("/conversations", "POST",
                             {"title": f"续跑重弹哨兵-负向-{args.worker}", "workerId": args.worker}, token))
        cid2 = conv2.get("id") or conv2.get("conversationId")
        run2 = _unwrap(_req(f"/conversations/{cid2}/runs", "POST", {"text": "你好"}, token))
        rid2 = run2.get("runId") or run2.get("id")
        req3 = urllib.request.Request(f"{BASE}/runs/{rid2}/events")
        req3.add_header("Authorization", "Bearer " + token)
        req3.add_header("Accept", "text/event-stream")
        ev3, _ = _sse_stream(req3, stop_on_form=False)
        names3 = [n for n, _ in ev3]
        log(f"[U5] 问候帧={names3} form_code={_form_code_of(ev3)}")
        if "need_form" in names3:
            fails.append(f"U5 问候误触发开表 code={_form_code_of(ev3)}")
        _cleanup(cid2, token)
    except Exception as e:
        fails.append(f"U5 负向对照执行异常：{e}")

    log("")
    if fails:
        for f in fails:
            log(f"[FAIL] {f}")
        log(f"共 {len(fails)} 项失败")
        return len(fails)
    log("[OK] U1–U5 全通过：首发开表、续跑不重弹、问候不误触发")
    return 0


if __name__ == "__main__":
    sys.exit(main())
