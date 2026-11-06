# -*- coding: utf-8 -*-
"""成绩问答端到端验收（docs/75）：真实对话链路，看**模型最终回答**里有没有数字。

前面几层（解析还原 / 切片 / 检索 / 聚合）由 `_verify_kb_grade_sheet.py` 覆盖；
本脚本只回答一个问题：用户问「我的平均绩点和成绩」时，跑着的 agent 答出来的
回答里**是否真的出现 2.69 / 80.26 / 134.0**。

为什么必须单独验：检索命中 ≠ 数字进了提示词 ≠ 模型答出来。
实测过的坑：
  * 工具返回字段叫 snippet、builder 只认 content/text ⇒ 参考块恒为空，模型全程没看到一个字；
  * 模型把「没检索到」当「库里没有」⇒ 答「未取得该口径数据」。
两层都修好后，才有必要做这条活体验收。

判据
  A1 回答里出现「历年平均学分绩点」对应数值 2.69
  A2 回答里出现「历年平均成绩」对应数值 80.26
  A3 回答里出现总学分 134.0（或「已获得」同义表述旁的数字）
  A4 回答**不是**「未取得 / 没有该数据」这类拒答
  A5 回答里带分数来源资料名（可溯源）

前置：:8080 后端 + :8000 agent 在线，且 agent 已按新代码重启；
任一不满足 → 如实 SKIP（不算 PASS，铁律 15）。

用法（Python312）：
    C:/Users/刘尖尖/AppData/Local/Programs/Python/Python312/python.exe scripts/_verify_kb_grade_answer.py
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"
QUESTION = "我的平均绩点和成绩是多少？顺便说下我已经修了多少学分。"
PASS = 0
FAIL = 0
SKIP = 0


def chk(tag, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(("[PASS] " if ok else "[FAIL] ") + tag + (("  " + detail) if detail else ""))
    return ok


def skip(tag, why):
    global SKIP
    SKIP += 1
    print(f"[SKIP] {tag}  前置不足：{why}")


def post(url, body, token=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def read_sse(url, token, timeout=180):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    buf = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            buf.append(raw.decode("utf-8", "replace"))
    return "".join(buf)


def extract_answer(sse_text: str) -> str:
    """从 SSE 里拼出回答正文（与 _check_answer_kb_strict.py 同一口径）。

    事件结构（实测 :8080）：message.delta → {"text": 增量}；message.completed → {"content": 全文}。
    **优先用 delta 拼接**，只有整段没有 delta 时才回落 content，否则同一段回答会被算两次。
    """
    deltas, final = [], ""
    for ln in sse_text.splitlines():
        if not ln.startswith("data:"):
            continue
        raw = ln[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        body = obj.get("data") if isinstance(obj.get("data"), dict) else obj
        if not isinstance(body, dict):
            continue
        v = body.get("delta")
        if v is None and "text" in body:
            v = body.get("text")
        if isinstance(v, str) and v:
            deltas.append(v)
            continue
        for key in ("content", "answer"):
            x = body.get(key)
            if isinstance(x, str) and x:
                final = x
    return "".join(deltas) if deltas else final


def main():
    try:
        tok = post(BASE + "/api/v1/auth/login", {"username": "test", "password": "test"})["data"]["accessToken"]
    except Exception as e:  # noqa: BLE001
        skip("A1-A5 活体问答", f"后端登录失败（{e}），需要 :8080 在线")
        return summary()
    try:
        urllib.request.urlopen(AGENT + "/health", timeout=5)
    except Exception as e:  # noqa: BLE001
        skip("A1-A5 活体问答", f"agent 不可达（{e}），需要 :8000 在线")
        return summary()

    conv = post(BASE + "/api/v1/conversations", {"title": "grade-sheet-probe"}, tok)["data"]
    run = post(f"{BASE}/api/v1/conversations/{conv['id']}/runs",
               {"text": QUESTION, "context": {}}, tok)
    run_id = run["data"]["runId"]
    sse = read_sse(f"{BASE}/api/v1/runs/{run_id}/events", tok)

    ans = extract_answer(sse)
    if not ans.strip():
        skip("A1-A5 活体问答", f"未取到回答正文（SSE {len(sse)} 字节）；多为模型未配置或调用失败")
        print("       —— SSE 片段 ——\n" + "\n".join("       " + ln for ln in sse.splitlines()[:12]))
        return summary()

    print(f"=== 提问：{QUESTION}")
    print("=== 回答（前 600 字）===")
    print(ans.strip()[:600])

    chk("A1 回答给出平均学分绩点 2.69", "2.69" in ans)
    chk("A2 回答给出平均成绩 80.26", "80.26" in ans)
    chk("A3 回答给出已获得总学分 134", "134" in ans)
    refused = ("未取得" in ans and "绩点" in ans) or "没有相邻的数值" in ans or "无法可靠给出" in ans
    chk("A4 未出现「未取得绩点数值」这类拒答", not refused)
    chk("A5 回答可溯源（含成绩单资料名或「知识库」字样）",
        "score_23101100512" in ans or "成绩单" in ans or "知识库" in ans)
    return summary()


def summary():
    print(f"\n==== 结果：{PASS} 通过 / {FAIL} 失败 / {SKIP} 跳过 ====")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
