# -*- coding: utf-8 -*-
"""哨兵：SSE 流结束时是否触发 Spring Security 的「已提交响应被判 403」三段 ERROR。

背景（2026-10-14 定案）
    `GET /api/v1/runs/{runId}/events` 返回 SseEmitter。流结束时容器会做一次
    **ASYNC 派发**，这次派发会再走一遍安全过滤链：
      - `JwtAuthenticationFilter` 继承 `OncePerRequestFilter`，默认
        `shouldNotFilterAsyncDispatch()=true` ⇒ 不参与 ASYNC 派发 ⇒ 该次没有 SecurityContext；
      - `AuthorizationFilter` 默认参与 ⇒ 判 `AccessDeniedException`；
      - 而 SSE 响应早已写出（committed）⇒ 403 写不进去，于是每次都刷三段 ERROR：
          1) AccessDeniedException: Access Denied
          2) Unable to handle the Spring Security Exception because the response is already committed.
          3) Cannot render error page for request [null] ...
    修法：`SecurityConfig` 的 `authorizeHttpRequests(...)` 加
    `.shouldFilterAllDispatcherTypes(false)`（鉴权只在 REQUEST 派发发生）。

判据来源（为什么要读服务端日志）
    这个缺陷**不改变 HTTP 响应**（SSE 仍然是 200 且事件完整），唯一可观测面就是
    服务端日志。所以判据必须回到日志本身，而不是「客户端收没收到」。
    另加一条正向断言：SSE 必须真的 200 且收到 `run.completed`/`run.failed`，
    防止「为了不报错把流也弄坏了」这种假绿。

用法（后端与日志路径按需覆盖）
    <python> scripts/_check_sse_async_denied.py
    <python> scripts/_check_sse_async_denied.py --log logs/boot.log --base http://127.0.0.1:8080

退出码：0 = 干净（无三段 ERROR）；1 = 缺陷在（DEFECT-PRESENT）。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

MARKERS = [
    "Unable to handle the Spring Security Exception because the response is already committed",
    "Cannot render error page for request [null]",
]
# AccessDeniedException 单看会误伤（真实的未授权访问也会打），所以只在「同一段新增日志里
# 同时出现 committed 文案」时才算命中；committed 文案是这条缺陷的指纹。

FAILS = []


def chk(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "   <<< %s" % detail))
    if not cond:
        FAILS.append(name)


def post(url, obj, token=None):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def read_sse(url, token, budget=90):
    """订阅 SSE，读到达终止事件或流关闭为止。返回 (http_code, 收到的文本)。"""
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "text/event-stream")
    buf = []
    code = 0
    try:
        with urllib.request.urlopen(req, timeout=budget) as r:
            code = r.status
            deadline = time.time() + budget
            while time.time() < deadline:
                line = r.readline()
                if not line:
                    break
                buf.append(line.decode("utf-8", "replace"))
                joined = "".join(buf)
                if "event:run.completed" in joined or "event:run.failed" in joined:
                    break
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        buf.append("EXC: %s" % e)
    return code, "".join(buf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--log", default=None)
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = args.log or os.path.join(repo, "logs", "boot.log")
    base = args.base.rstrip("/")

    if not os.path.isfile(log_path):
        print("[SKIP] 找不到后端日志 %s —— 无法判定，不用 PASS 伪装。" % log_path)
        print("[STATUS] SKIP")
        return 0

    with open(log_path, "rb") as f:
        f.seek(0, os.SEEK_END)
        start_offset = f.tell()

    # ---- 正向：真实跑一次 run 并订阅 SSE ----
    tok = post(base + "/api/v1/auth/login",
               {"username": args.user, "password": args.password})["data"]["accessToken"]
    conv = post(base + "/api/v1/conversations", {"title": "sse-async-sentinel"}, tok)["data"]
    run = post("%s/api/v1/conversations/%s/runs" % (base, conv["id"]), {"text": "你好", "context": {}}, tok)
    run_id = run["data"]["runId"]
    print("runId=%s" % run_id)

    code, body = read_sse("%s/api/v1/runs/%s/events" % (base, run_id), tok)
    print("SSE http=%s bytes=%d first=%r" % (code, len(body), body[:120]))

    chk("S1 SSE 返回 200（功能没被改坏）", code == 200, "http=%s" % code)
    chk("S2 收到终止事件（run.completed / run.failed）",
        ("event:run.completed" in body) or ("event:run.failed" in body),
        body[-200:])

    # ---- 缺陷判据：新增日志里的指纹 ----
    time.sleep(3)  # 给日志落盘留时间
    with open(log_path, "rb") as f:
        f.seek(start_offset)
        new_text = f.read().decode("utf-8", "replace")

    hits = {m: new_text.count(m) for m in MARKERS}
    print("新增日志 %d 字节；指纹命中：%s" % (len(new_text), hits))
    bad = sum(hits.values())
    chk("S3 SSE 结束后新增日志里没有「已提交响应被判 403」的指纹", bad == 0,
        "命中 %s" % json.dumps({k: v for k, v in hits.items() if v}, ensure_ascii=False))

    print("\n结果：失败 %d 项 %s" % (len(FAILS), FAILS if FAILS else ""))
    print("[STATUS] %s" % ("CLEAN" if not FAILS else "DEFECT-PRESENT"))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
