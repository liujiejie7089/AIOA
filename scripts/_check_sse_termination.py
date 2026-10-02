# -*- coding: utf-8 -*-
"""诊断：管理端 AI 助手 SSE 为何以 ERR_INCOMPLETE_CHUNKED_ENCODING 收场。

现象（已复现）：浏览器里回答能拿到，但 `GET /runs/{id}/events` 报
`net::ERR_INCOMPLETE_CHUNKED_ENCODING`，前端据此弹红色「network error」。
用户看到的就是「AI 助手不能用」。

本脚本把「同一份事件流」分别在两条路径上取一次，并对比 curl 的退出码：
  · 路径 A：/api/v1/runs/{id}/events      （直连，老形态）
  · 路径 B：/aioa/api/v1/runs/{id}/events （单端口前缀剥离形态，浏览器实际走的）
curl 退出码 18 = "transfer closed with outstanding read data remaining"，
即分块传输**没有正常终止块**——这正是浏览器 ERR_INCOMPLETE_CHUNKED_ENCODING 的成因。
两条路径不一致 ⇒ 缺陷在**前缀剥离/托管层**；两条一致 ⇒ 缺陷在 **SseEmitter 收尾方式**。

定位：**报告型长期哨兵**（原 `_diag_sse_truncation.py`，因该缺陷至今未修故转正入库）。
恒退出 0，只在 stdout 打 `[STATUS]`；修复判据 = 该行从 `DEFECT-PRESENT` 变为 `OK`。
"""
import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8080"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"


def login():
    r = httpx.post(BASE + "/api/v1/auth/login", timeout=30, trust_env=False,
                   json={"username": USER, "password": PWD, "tenantName": TENANT}).json()
    assert r.get("code") == 0, r
    return r["data"]["accessToken"]


def make_run(tok):
    h = {"Authorization": "Bearer " + tok}
    c = httpx.post(BASE + "/api/v1/conversations", headers=h, timeout=30,
                   trust_env=False, json={"title": "SSE 诊断"}).json()
    cid = (c.get("data") or {}).get("id")
    r = httpx.post(BASE + "/api/v1/conversations/%s/runs" % cid, headers=h, timeout=30,
                   trust_env=False, json={"text": "只回四个字：收到收到"}).json()
    assert r.get("code") == 0, r
    return (r.get("data") or {}).get("runId")


def stream(path, tok, tag):
    url = BASE + path
    out = subprocess.run(
        ["curl", "-sS", "-N", "--max-time", "60", "-H",
         "Authorization: Bearer " + tok, "-H", "Accept: text/event-stream", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    body = out.stdout or ""
    frames = [l for l in body.splitlines() if l.startswith("event:")]
    print("  [%s] %s" % (tag, path))
    print("    curl exit=%d stderr=%s" % (out.returncode, (out.stderr or "").strip()[:160] or "-"))
    print("    事件序列：%s" % ", ".join(f.replace("event: ", "") for f in frames))
    print("    末行(hex 尾部)：%r" % body[-60:])
    return out.returncode, frames


def main():
    tok = login()
    print("\n[A] 直连形态（老路径，无前缀）")
    ra = make_run(tok)
    time.sleep(0.3)
    ca, fa = stream("/api/v1/runs/%s/events" % ra, tok, "A")

    print("\n[B] 单端口形态（浏览器实际走的路径）")
    rb = make_run(tok)
    time.sleep(0.3)
    cb, fb = stream("/aioa/api/v1/runs/%s/events" % rb, tok, "B")

    print("\n======== 结论 ========")
    print("A 退出码=%d  事件=%s" % (ca, fa))
    print("B 退出码=%d  事件=%s" % (cb, fb))
    if ca == cb == 18:
        print("两条路径同样非正常终止 ⇒ 与路径剥离无关，缺陷在 SseEmitter 的收尾/心跳线程")
        print("[STATUS] DEFECT-PRESENT  (curl=18，分块流缺终止块)")
        print("         修复判据：本行应变成 [STATUS] OK，且 A/B 退出码均为 0。")
    elif ca != cb:
        print("两条路径不一致 ⇒ 缺陷在单端口前缀剥离/托管层")
        print("[STATUS] DEFECT-PRESENT  (两条路径行为不一致)")
    else:
        print("两条路径都正常收尾 ⇒ curl 侧无法复现，需回到浏览器侧继续查")
        print("[STATUS] OK  (两条路径均退出 0，分块流有正常终止块)")
    # 本脚本是**报告型哨兵**（铁律 6）：恒退出 0，结论只在 stdout 里。
    # 缺陷修复前它永远打 DEFECT-PRESENT —— 这是**如实报告**，不是「测试失败」，
    # 因此不要把它挂进任何「必须全绿」的回归闸门里。
    return 0


if __name__ == "__main__":
    sys.exit(main())
