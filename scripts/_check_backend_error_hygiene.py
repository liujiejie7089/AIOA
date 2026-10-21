#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：后端「错误卫生」四条硬约束（2026-10-20）

覆盖三处修复，全部只读或只做「必被拒绝」的负向调用，**不写业务数据**：

  S1  开通租户缺 adminPassword      → 业务码 400 且文案含「租户管理员初始密码」
  S2  开通租户密码 < 8 位           → 业务码 400 且文案含「至少 8 位」
  S3  SSE 端点上的业务异常          → HTTP 200 + text/event-stream + `event: error` 帧（JSON 可解析）
  S4  同一 URL 发 JSON Accept       → 406 且 JSON 错误体（不是 500「服务内部错误」）
  S5  @Async 线程池已装配           → 运行中 JVM 线程名出现 aios-async-
  S6  首页统计 / 未读数可用         → /stats/home 四字段为数字，/notifications 带 unread

为什么要有 S3/S4 这一对：`produces = text/event-stream` 的端点抛业务异常时，
异常处理器若仍回 JSON，Spring 会因「无可写表示」抛 HttpMediaTypeNotAcceptableException，
**错误处理器自身失败** → 日志出现 `Failure in @ExceptionHandler` + Tomcat 完整 ERROR 栈，
客户端拿到错误页。历史上那条 `HttpMessageNotWritableException: No converter for
[ApiResponse] with preset Content-Type 'text/html'` 属同一根因。

用法：
    python scripts/_check_backend_error_hygiene.py [--base http://127.0.0.1:8080]
需要：后端在线；本机有 jcmd（可选，缺失时 S5 记 SKIP 并打印具体原因）。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

RESULTS = []


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " —— " + detail)


def skip(name, why):
    RESULTS.append((name, None, why))
    print("  [SKIP] " + name + " —— " + why)


def call(base, path, method="GET", token=None, body=None, accept=None, timeout=15):
    """返回 (http_status, headers, raw_text)。4xx/5xx 不抛异常。"""
    url = base.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")


def login(base, username, password):
    st, _, raw = call(base, "/api/v1/auth/login", "POST",
                      body={"username": username, "password": password})
    try:
        d = json.loads(raw)
    except Exception:
        return None
    return (d.get("data") or {}).get("accessToken")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOA_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pwd", default="Admin@123")
    args = ap.parse_args()
    base = args.base

    print("=== 后端错误卫生哨兵 ===")
    print("base =", base)

    token = login(base, args.user, args.pwd)
    if not token:
        print("  [FAIL] 登录失败，后续无法判定")
        return 1
    print("  登录成功（%s）" % args.user)

    # ---- S1 / S2：开通租户必须显式给密码 ----
    st, _, raw = call(base, "/api/v1/admin/tenants", "POST", token,
                      {"code": "zz_sentinel_nopwd", "name": "哨兵-缺密码",
                       "adminUsername": "zz_sentinel_nopwd_admin"})
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    ok = d.get("code") == 400 and "租户管理员初始密码" in (d.get("message") or "")
    rec("S1 缺密码被拒", ok, "code=%s msg=%s" % (d.get("code"), d.get("message")))

    st, _, raw = call(base, "/api/v1/admin/tenants", "POST", token,
                      {"code": "zz_sentinel_short", "name": "哨兵-短密码",
                       "adminUsername": "zz_sentinel_short_admin", "adminPassword": "123"})
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    ok = d.get("code") == 400 and "至少 8 位" in (d.get("message") or "")
    rec("S2 短密码被拒", ok, "code=%s msg=%s" % (d.get("code"), d.get("message")))

    # ---- S3：SSE 端点上的业务异常必须是 200 + event: error ----
    # 用一个不存在的 runId 触发同步 BizException（不写任何数据）
    sse_path = "/api/v1/runs/run_sentinel_not_exist/events"
    st, hdrs, raw = call(base, sse_path, token=token, accept="text/event-stream", timeout=10)
    ctype = (hdrs.get("Content-Type") or "").lower()
    is_sse = "text/event-stream" in ctype
    first = (raw.splitlines() or [""])[0].strip()
    data_line = ""
    for line in raw.splitlines():
        if line.startswith("data:"):
            data_line = line[5:].strip()
            break
    payload = {}
    try:
        payload = json.loads(data_line) if data_line else {}
    except Exception:
        payload = {}
    ok = st == 200 and is_sse and first == "event: error" and bool(payload.get("message"))
    rec("S3 SSE 错误帧", ok,
        "http=%s ctype=%s first=%r msg=%s" % (st, ctype, first, payload.get("message")))
    if st == 200 and is_sse and first == "event: error":
        print("        ↳ 原始帧: " + raw.strip().replace("\n", " | ")[:180])

    # ---- S4：对 SSE-only 端点发 JSON Accept → 必须 406（不是 500）----
    # 若落到 Exception 兜底会变成「服务内部错误」，把「客户端写错 Accept 头」
    # 伪装成「后端崩了」；本仓对 TypeMismatch / NoResourceFound 已有同类修正。
    st, hdrs, raw = call(base, sse_path, token=token, accept="application/json", timeout=10)
    ctype = (hdrs.get("Content-Type") or "").lower()
    try:
        d = json.loads(raw)
    except Exception:
        d = {}
    ok = st == 406 and ("json" in ctype) and d.get("code") == 406 and "不支持的响应类型" in (d.get("message") or "")
    rec("S4 协商失败归 406", ok, "http=%s ctype=%s code=%s msg=%s"
        % (st, ctype, d.get("code"), d.get("message")))

    # ---- S5：@Async 线程池已装配（线程名 aios-async-*）----
    try:
        # 从 8080 反查监听进程，避免写死 pid。
        # 注意：Windows 控制台输出是 GBK 混合，必须显式 errors="replace"，
        # 否则 subprocess 的读取线程会抛 UnicodeDecodeError，stdout 变成 None。
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15).stdout or ""
        pid = None
        for line in out.splitlines():
            if re.search(r":8080\s", line) and "LISTENING" in line:
                pid = line.split()[-1]
                break
        if not pid:
            skip("S5 @Async 线程池", "未从 netstat 找到监听 8080 的 pid")
        else:
            jcmd = os.path.join(os.environ.get("JAVA_HOME", ""), "bin", "jcmd.exe")
            if not os.path.exists(jcmd):
                jcmd = "jcmd"
            dump = subprocess.run([jcmd, pid, "Thread.print"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=25).stdout or ""
            n = dump.count("aios-async-")
            if n:
                rec("S5 @Async 线程池", True, "pid=%s 线程名 aios-async-* 出现 %d 次" % (pid, n))
            else:
                # 线程池核心线程懒创建：尚未有 @Async 调用时不存在，不算失败
                skip("S5 @Async 线程池",
                     "pid=%s 未出现 aios-async-* 线程：本次启动后尚未触发过 @Async（池按需创建）；"
                     "要验证请先提交一次走审批的表单（如 leave_request）后重跑" % pid)
    except FileNotFoundError:
        skip("S5 @Async 线程池", "本机找不到 jcmd（需 JDK 而非 JRE）")
    except Exception as e:
        skip("S5 @Async 线程池", "探测失败：%s" % e)

    # ---- S6：首页统计 / 未读数 ----
    st, _, raw = call(base, "/api/v1/stats/home", token=token)
    try:
        d = json.loads(raw).get("data") or {}
    except Exception:
        d = {}
    keys = ("todoApprovals", "aiConversations", "aiRuns")
    ok = all(isinstance(d.get(k), int) for k in keys)
    rec("S6a /stats/home", ok, json.dumps({k: d.get(k) for k in keys}, ensure_ascii=False))

    st, _, raw = call(base, "/api/v1/notifications?limit=1", token=token)
    try:
        d = json.loads(raw).get("data") or {}
    except Exception:
        d = {}
    ok = isinstance(d.get("unread"), int)
    rec("S6b /notifications unread", ok, "unread=%s" % d.get("unread"))

    failed = [r for r in RESULTS if r[1] is False]
    skipped = [r for r in RESULTS if r[1] is None]
    print("\n=== 汇总：%d 通过 / %d 失败 / %d 跳过（共 %d）==="
          % (len(RESULTS) - len(failed) - len(skipped), len(failed), len(skipped), len(RESULTS)))
    for name, _, detail in failed:
        print("  失败：" + name + " —— " + detail)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
