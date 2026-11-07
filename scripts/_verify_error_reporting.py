# -*- coding: utf-8 -*-
"""错误上报与回答排版：真机验收（2026-11-07，docs/87）。

## 现场（用户三张截图）

1. 用户端连着三条红色气泡「生成失败：生成过程中断，内容可能不完整　建议：
   重试一次；仍失败请把错误编号发给管理员」——**一个编号都没有**。
2. 管理端启用 MiniMax 失败，toast 把上游原始 JSON（含 request_id）整段抖出来；
   而 404 响应体里同时有 `insufficient_balance` 与 `no longer available`。
3. 「写一份周报」的正文里 `##` / `|` / `**` 全以裸符号挤成一段，旁边挂着
   「工作周报」表单卡 —— 暂停帧提前 return，收口的 formatAnswer() 没跑。

## 本脚本验什么

A 段（静态 + 纯函数，不消耗额度）：码表分类、编号自洽、不外发原文、resume 不再引用
未定义的 req、H5 三个新码 / 暂停帧排版 / 错误帧屏蔽原始 message。
B 段（真机）：agent 健康、resume 非空 SSE、管理端连通性校验、两条真实消息的 SSE
全链路 + 回库核（铁律 7/12：界面展示了 X 必须回库再取，不得同源）。

用法：
    agent/.venv/Scripts/python.exe scripts/_verify_error_reporting.py
    agent/.venv/Scripts/python.exe scripts/_verify_error_reporting.py --static-only
退出码：0 = 全过；1 = 有 FAIL；2 = 仅 SKIP（环境不可用）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = "http://127.0.0.1:8080/api/v1"
AGENT = "http://127.0.0.1:8000"
USER, PWD = "test", "test"
QUESTIONS = ["请假", "安康的汉水长歌怎么样？"]

BALANCE_BODY = ('{"error":{"message":"Insufficient Balance","type":"insufficient_balance",'
                '"code":402},"request_id":"req-abc12345"}')
NOT_FOUND_BODY = ('{"type":"error","error":{"type":"insufficient_balance",'
                  '"message":"The model \'MiniMax-M1\' is no longer available. (2013)",'
                  '"http_code":"404"},"request_id":"0217546xxxx"}')

PASS, FAIL, SKIP, RES = [], [], [], []


def chk(cid, ok, expect="", actual="", note=""):
    RES.append((cid, bool(ok)))
    (PASS if ok else FAIL).append(cid)
    print("  [%s] %s" % ("PASS" if ok else "FAIL", cid))
    if expect != "" or actual != "":
        print("        expect=%r" % (expect,))
        print("        actual=%r" % (str(actual)[:300],))
    if note:
        print("        note  : %s" % note)
    return bool(ok)


def skip(cid, why):
    SKIP.append(cid)
    print("  [SKIP] %s — %s" % (cid, why))
    return False


def src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def frames_of(raw: str):
    out, ev, buf = [], "", []
    for line in re.split(r"\r?\n", raw):
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].lstrip())
        elif line.startswith(":"):
            continue
        elif line == "":
            if ev:
                out.append((ev, "\n".join(buf)))
            ev, buf = "", []
    if ev:
        out.append((ev, "\n".join(buf)))
    return out


def frame_json(data):
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return json.loads(data.replace("\n", ""))


def case_static():
    print("\n=== A. 静态 / 纯函数判据（不消耗额度）===")
    from aios_ai import errors
    from app.main import _describe_upstream

    chk("A1 码表新增模型余额不足专用码",
        "MODEL_BALANCE_INSUFFICIENT" in errors.CATALOG)
    p402 = errors.upstream_payload(402, BALANCE_BODY, "deepseek-chat")
    chk("A2 402 Insufficient Balance → 余额不足（不再泛化成没返回结果）",
        p402["code"] == "MODEL_BALANCE_INSUFFICIENT" and "余额不足" in p402["message"],
        "MODEL_BALANCE_INSUFFICIENT", p402["code"])
    p404 = errors.upstream_payload(404, NOT_FOUND_BODY, "MiniMax-M1")
    chk("A3 404 同时带 insufficient_balance → 仍判模型下线（不误报充值）",
        p404["code"] == "MODEL_NOT_FOUND" and "充值" not in p404["suggestion"],
        "MODEL_NOT_FOUND", p404["code"])
    chk("A4 401 / 429 / 408 / 503 分类零回归",
        [errors.upstream_payload(s, "x")["code"] for s in (401, 429, 408, 503)]
        == ["MODEL_AUTH_FAILED", "MODEL_RATE_LIMITED", "MODEL_TIMEOUT", "MODEL_UPSTREAM_ERROR"])

    ids_ok = all(p.get("errorId") == "run_A" for p in (
        errors.stream_payload("run_A"), errors.internal_payload("run_A"),
        errors.exception_payload(NameError("x"), "run_A"),
        errors.exception_payload(TimeoutError(), "run_A"),
        errors.exception_payload(ConnectionError("ConnectError"), "run_A")))
    chk("A5 所有兜底载荷都带可报障编号", ids_ok)
    sp = errors.stream_payload("run_A")
    chk("A6 断流建议里的编号与 errorId 是同一个值",
        "run_A" in sp["suggestion"] and sp["errorId"] == "run_A")
    chk("A7 缺省文案不再空口承诺「错误编号」",
        all("错误编号" not in errors.error_payload(c)["suggestion"]
            for c in ("MODEL_STREAM_ERROR", "INTERNAL_ERROR"))
        and "errorId" not in errors.error_payload("MODEL_STREAM_ERROR"))
    chk("A8 异常按类型分类（超时 / 连接 / 代码 bug）",
        [errors.exception_payload(e, "r")["code"] for e in
         (TimeoutError(), ConnectionError("ConnectError"), NameError("req"))]
        == ["MODEL_TIMEOUT", "MODEL_UPSTREAM_ERROR", "INTERNAL_ERROR"])

    m404 = _describe_upstream(404, NOT_FOUND_BODY, "MiniMax-M1")
    chk("A9 管理端文案不外发 request_id / 原始 JSON，且点名失效模型",
        "request_id" not in m404 and "insufficient_balance" not in m404
        and "0217546xxxx" not in m404 and "MiniMax-M1" in m404,
        "人话 + 下一步", m404[:120])
    chk("A10 管理端 402 文案指向充值",
        "余额不足" in _describe_upstream(402, BALANCE_BODY, "deepseek-chat"))

    fac = src("agent/aios_ai/graph/facade.py")
    chk("A11 facade 不再用 getattr(exc,'trace_id')，且区分已吐正文与未分类异常",
        "getattr(exc, \"trace_id\", None)" not in fac
        and "errors.stream_payload(run_id)" in fac
        and "errors.exception_payload(exc, run_id)" in fac)
    main = src("agent/app/main.py")
    _rs = main.index("@app.post(\"/internal/v1/runs/{run_id}/resume\")")
    _re = main.find("@app.", _rs + 10)   # 精确切到下一个端点，别把别处的 req 算进来
    resume_seg = main[_rs:_re if _re > 0 else _rs + 3000]
    chk("A12 resume 端点不再引用未定义的 req.user_context",
        "req.user_context.trace_id" not in resume_seg
        and "request.headers.get(\"X-Trace-Id\") or run_id" in resume_seg)
    chk("A13 连通性校验不再把 resp.text 拼进 message",
        "_describe_upstream(resp.status_code, resp.text or \"\", provider.model)" in main
        and "f\"连接失败：{exc}\"" not in main)

    h5 = src("user-client/index.html")
    _fs = h5.index("var ERR_FALLBACK = {")
    fb = h5[_fs:h5.index("};", _fs)]   # 只认 ERR_FALLBACK 对象内的键，注释里提到不算
    chk("A14 H5 ERR_FALLBACK 补齐流中断 / 余额不足 / Java 兜底三个码",
        all(("%s:" % c) in fb for c in
            ("MODEL_STREAM_ERROR", "MODEL_BALANCE_INSUFFICIENT", "AGENT_STREAM_ERROR")))
    chk("A15 AGENT_STREAM_ERROR 帧不显示 Java 原始异常文本",
        "code === 'AGENT_STREAM_ERROR' ? '' : p.message" in h5)
    chk("A16 暂停帧到达时两形态都立刻排版（不再让正文停在裸 ## / |）",
        h5.count("renderAnsNow();") == 3 and h5.count("oaRenderAnsNow();") == 3
        and "function renderAnsNow()" in h5 and "function oaRenderAnsNow()" in h5)
    chk("A17 formatAnswer 仍在且支持标题与表格",
        "function formatAnswer(raw)" in h5 and "ans-table-wrap" in h5)


def case_live():
    print("\n=== B. 真机全链路 ===")
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(AGENT + "/health", timeout=10)
        if not chk("B1 agent :8000 健康", r.status_code == 200, 200, r.status_code):
            return skip("B 真机全链路", "agent 不可用")
    except Exception as e:
        return skip("B 真机全链路", "agent 不可达：%s" % e)

    from _svc_token import svc_headers
    sh = svc_headers()

    # B2：resume 端点不得再是空 200
    rp = s.post(AGENT + "/internal/v1/runs/run_verify_no_such/resume",
                json={"answer": "x"}, headers=sh, timeout=(10, 30))
    body = rp.content.decode("utf-8", "replace")
    chk("B2 resume 不再返回空 200，且 error 帧带编号",
        bool(body.strip()) and "event: error" in body and '"errorId"' in body,
        "error 帧 + errorId", body[:160].replace("\n", " / "))

    # B3：管理端同款连通性校验（三个通道都必须给出人话结果）
    oks = {}
    for key in ("minimax", "deepseek", "dashscope"):
        try:
            d = s.post(AGENT + "/internal/v1/models/check", json={"key": key},
                       headers=sh, timeout=40).json()
            oks[key] = (bool(d.get("ok")), str(d.get("message") or ""))
        except Exception as e:
            oks[key] = (False, str(e))
    chk("B3 管理端连通性校验三通道都返回结构化人话结果",
        all(ok for ok, _ in oks.values()) and all(m for _, m in oks.values()),
        "三通道 ok=true", {k: v[0] for k, v in oks.items()})

    # B4/B5/B6：与界面同源的建会话 → 发 run → SSE → 回库核
    lr = s.post(API + "/auth/login", json={"username": USER, "password": PWD}, timeout=20)
    if lr.status_code != 200 or lr.json().get("code") != 0:
        return skip("B4-B6", "登录失败：%s" % lr.text[:160])
    h = {"Authorization": "Bearer " + lr.json()["data"]["accessToken"]}

    for idx, q in enumerate(QUESTIONS, start=4):
        conv = s.post(API + "/conversations", headers=h,
                      json={"title": "错误上报验收", "source": "aios-client"}, timeout=20)
        cid = (conv.json().get("data") or {}).get("id")
        if not cid:
            skip("B%d %s" % (idx, q), "建会话失败")
            continue
        rr = s.post(API + "/conversations/%s/runs" % cid, headers=h,
                    json={"text": q, "context": {}, "kb_on": True}, timeout=30)
        d = rr.json()
        if d.get("code") == 403 and "额度" in str(d.get("message") or ""):
            skip("B%d %s" % (idx, q), "今日额度已用完（环境限制）")
            continue
        rid = (d.get("data") or {}).get("runId") or (d.get("data") or {}).get("id")
        if not rid:
            chk("B%d %s 发 run 成功" % (idx, q), False, "runId", rr.text[:200])
            continue
        with s.get(API + "/runs/%s/events" % rid, headers=h, stream=True,
                   timeout=(15, 240)) as resp:
            raw = resp.content.decode("utf-8", "replace")
        frames = frames_of(raw)
        types = [t for t, _ in frames]
        try:
            import pymysql
            conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                                  database="aios", charset="utf8mb4")
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM agent_run WHERE run_id=%s", (rid,))
                row = cur.fetchone()
                db_status = row[0] if row else ""
                cur.execute("SELECT content FROM chat_message WHERE run_id=%s "
                            "AND role='assistant' ORDER BY id DESC LIMIT 1", (rid,))
                row = cur.fetchone()
                db_content = (row[0] or "") if row else ""
            conn.close()
        except Exception as e:
            skip("B%d %s 回库核" % (idx, q), "数据库不可用：%s" % e)
            continue

        paused = any(t in types for t in ("need_form", "need_clarification", "need_confirm"))
        if paused:
            chk("B%d 「%s」暂停帧与库里状态一致" % (idx, q),
                db_status == "WAITING_INPUT", "WAITING_INPUT", db_status,
                "暂停帧：%s" % [t for t in types if t.startswith("need_")])
            continue
        completed = [data for t, data in frames if t == "message.completed"]
        if not completed:
            chk("B%d 「%s」拿到 message.completed" % (idx, q), False,
                "message.completed", types[-4:])
            continue
        content = frame_json(completed[-1]).get("content") or ""
        deltas = "".join(frame_json(dd).get("text", "")
                         for t, dd in frames if t == "message.delta")
        chk("B%d 「%s」成稿且三者同源（delta / 完成帧 / 落库）" % (idx, q),
            bool(content) and deltas == content == db_content
            and "\n" in content and db_status == "SUCCEEDED",
            "SUCCEEDED / 含真实换行 / 三者一致",
            "len(delta)=%d len(completed)=%d len(db)=%d status=%s"
            % (len(deltas), len(content), len(db_content), db_status))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static-only", action="store_true", help="只跑 A 段，不消耗额度")
    args = ap.parse_args()
    case_static()
    if not args.static_only:
        case_live()
    print("\n" + "=" * 60)
    print("汇总：%d 通过 / %d 失败 / %d 跳过（共 %d 项）"
          % (len(PASS), len(FAIL), len(SKIP), len(RES) + len(SKIP)))
    if FAIL:
        print("FAIL：", ", ".join(FAIL))
        return 1
    if SKIP and not PASS:
        return 2
    print("ALL PASS" if not SKIP else "PASS（含环境 SKIP）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
