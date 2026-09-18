#!/usr/bin/env python
"""Webhook 接收侧校验的行为验证（Gitee 明文 / Gitea HMAC 的机制边界）。

**为什么单独写这个脚本**：Webhook 端点是平台上唯一不需要登录态就能写数据的入口。
本次改造把「校验」从控制器里的内联字符串比对，改为由当前托管方
（`RepoProviderClient.verifyWebhook`）承担，并把报文接收类型从 `String` 改成 `byte[]`。
这两处都在安全关键路径上，必须拿真实运行的服务验一遍 —— 单测只能证明纯函数对。

验证内容：
1. 错误密钥 → 拒绝（accepted=false, BAD_TOKEN）
2. 不带密钥 → 拒绝
3. 项目不存在 → 拒绝（不泄露内部状态）
4. 正确密钥 + Push Hook → 接受，且落库事件类型为 PUSH
5. 正确密钥 + Merge Request Hook → 接受，且类型为 MERGE_REQUEST
6. **Gitea 风格投递（X-Gitea-Event + 无 X-Gitee-Token）在 provider=gitee 时必须被拒** ——
   这条刻意断言「拒绝」，用来固定「两家的校验机制不可互换」这一事实；
   若它变成接受，说明校验被削弱了。

退出码非 0 表示有断言失败。
"""

from __future__ import annotations

import json
import sys
import time

import httpx
import pymysql

BASE = "http://127.0.0.1:8080"
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa", charset="utf8mb4")

# trust_env=False：本机存在代理环境变量，交给 httpx 读环境会拿到代理的错误页
client = httpx.Client(trust_env=False, timeout=20.0)

results: list[tuple[bool, str, str]] = []


def chk(ok: bool, name: str, detail: object = "") -> None:
    results.append((bool(ok), name, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  | {detail}" if detail != "" else ""))


def project_secret(pid: int) -> str:
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT webhook_secret FROM gitee_project WHERE id=%s", (pid,))
            row = cur.fetchone()
            return (row[0] if row and row[0] else "") if row else ""
    finally:
        conn.close()


def latest_event(pid: int) -> dict | None:
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id, event_type, gitee_event, event_key FROM gitee_event "
                "WHERE project_id=%s ORDER BY id DESC LIMIT 1",
                (pid,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def post(pid: int, headers: dict[str, str], payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    r = client.post(f"{BASE}/api/v1/gitee/webhook/{pid}", content=body, headers=headers)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}


def main() -> int:
    pid = 5
    secret = project_secret(pid)
    if not secret:
        print(f"项目 {pid} 没有 webhook_secret，无法验证（换一个项目）")
        return 2
    print(f"使用项目 id={pid}，密钥长度 {len(secret)}\n")

    # ---- 1/2/3 拒绝路径 ----
    st, body = post(pid, {"X-Gitee-Event": "Push Hook", "X-Gitee-Token": "wrong-" + secret}, {})
    chk(st == 200 and body.get("accepted") is False and body.get("reason") == "BAD_TOKEN",
        "错误密钥被拒（HTTP 200 + BAD_TOKEN）", body)

    st, body = post(pid, {"X-Gitee-Event": "Push Hook"}, {})
    chk(st == 200 and body.get("accepted") is False and body.get("reason") == "BAD_TOKEN",
        "缺少密钥头被拒（不放行匿名写入）", body)

    st, body = post(999999, {"X-Gitee-Event": "Push Hook", "X-Gitee-Token": secret}, {})
    chk(st == 200 and body.get("accepted") is False and body.get("reason") == "PROJECT_NOT_FOUND",
        "项目不存在被拒（且不区分「不存在/已删除」，不泄露内部状态）", body)

    # ---- 4 Push ----
    stamp = int(time.time() * 1000)
    push_payload = {
        "ref": "refs/heads/master",
        "commits": [{"id": f"sha{stamp}", "message": "验证改造后的校验链路",
                     "timestamp": "2026-09-18T10:30:00+08:00",
                     "author": {"name": "verify", "email": "v@example.com"}}],
        "repository": {"id": 12345},
        "sender": {"id": 987654, "login": "verify_bot"},
    }
    st, body = post(pid, {"X-Gitee-Event": "Push Hook", "X-Gitee-Token": secret,
                          "X-Gitee-Request-Id": f"req-{stamp}"}, push_payload)
    chk(st == 200 and body.get("accepted") is True and body.get("duplicated") is False,
        "正确密钥 + Push Hook 被接受", body)
    ev = latest_event(pid)
    chk(ev is not None and ev["event_type"] == "PUSH",
        "落库事件类型为 PUSH（校验通过后分类链路仍正常）", ev)

    # ---- 5 Merge Request ----
    mr_payload = {
        "action": "open",
        "number": stamp % 100000,
        "pull_request": {"id": 7000000 + stamp % 100000, "number": stamp % 100000,
                         "title": "验证事件分类", "state": "open",
                         "updated_at": "2026-09-18T10:31:00+08:00",
                         "head": {"ref": "feature/verify"}, "base": {"ref": "master"}},
        "repository": {"id": 12345},
        "sender": {"id": 987654, "login": "verify_bot"},
    }
    st, body = post(pid, {"X-Gitee-Event": "Merge Request Hook", "X-Gitee-Token": secret}, mr_payload)
    chk(st == 200 and body.get("accepted") is True, "正确密钥 + Merge Request Hook 被接受", body)
    ev = latest_event(pid)
    chk(ev is not None and ev["event_type"] == "MERGE_REQUEST",
        "落库事件类型为 MERGE_REQUEST", ev)

    # ---- 6 机制边界：Gitea 风格投递在 provider=gitee 下必须被拒 ----
    st, body = post(pid, {"X-Gitea-Event": "push"}, push_payload)
    chk(st == 200 and body.get("accepted") is False and body.get("reason") == "BAD_TOKEN",
        "Gitea 风格投递（无 X-Gitee-Token）被拒 —— 两家的校验机制不可互换", body)

    # Gitea 的 HMAC 签名头，对我们（provider=gitee）没有任何意义，同样必须被拒
    st, body = post(pid, {"X-Gitea-Event": "push", "X-Gitea-Signature": "deadbeef" * 8}, push_payload)
    chk(st == 200 and body.get("accepted") is False and body.get("reason") == "BAD_TOKEN",
        "伪造的 X-Gitea-Signature 被拒（错误机制下的签名不构成凭证）", body)

    failed = [n for ok, n, _ in results if not ok]
    print(f"\n合计 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    if failed:
        for n in failed:
            print("  FAIL:", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
