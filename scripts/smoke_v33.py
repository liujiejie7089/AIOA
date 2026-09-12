# -*- coding: utf-8 -*-
"""V33 冒烟：登录 → 读配置 → 生成 AI 解读 → 数字员工自建/自改。

用脚本而非 curl：避免口令出现在命令行里，也便于复用做多角色回归。
"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8080/api/v1"
AGENT = "http://127.0.0.1:8000"

# trust_env=False —— 否则走系统代理，会拿到非预期 HTML / ConnectError
CLIENT = httpx.Client(timeout=60, trust_env=False)


def login(u, p):
    r = CLIENT.post(f"{BASE}/auth/login", json={"username": u, "password": p})
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise SystemExit(f"登录失败 {u}: {body.get('message')}")
    return body["data"]["accessToken"]


def call(method, path, token, **kw):
    r = CLIENT.request(method, BASE + path, headers={"Authorization": f"Bearer {token}"}, **kw)
    try:
        body = r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}
    return r.status_code, body


def ok(status, body):
    return status == 200 and isinstance(body, dict) and body.get("code") == 0


def show(tag, status, body, depth=260):
    flag = "PASS" if ok(status, body) else "FAIL"
    txt = json.dumps(body, ensure_ascii=False)[:depth]
    print(f"[{flag}] {tag}  http={status} {txt}")


def main():
    print("=== 1. 平台管理员 ===")
    t_admin = login("admin", "Admin@123")
    show("GET /configs?keys=billing.package.scenes", *call("GET", "/configs?keys=billing.package.scenes", t_admin))
    # 白名单外的键必须 403：这里 code!=0 才是正确结果，单独断言以免被误读成失败
    st, body = call("GET", "/configs?keys=quota.warn.threshold", t_admin)
    print(f"[{'PASS' if st == 403 else 'FAIL'}] GET /configs 越权键(期望 403)  http={st}")

    print("\n=== 2. 普通用户 zhangsan ===")
    t_user = login("zhangsan", "User@123")
    show("GET /configs scenes", *call("GET", "/configs?keys=billing.package.scenes", t_user))
    show("GET /workers", *call("GET", "/workers", t_user))

    # 自建数字员工：普通成员应可创建，且落库为 SELF
    created_id = None
    st, body = call("POST", "/workers", t_user, json={
        "name": f"V33冒烟助理-{__import__('time').strftime('%H%M%S')}",
        "icon": "bot",
        "description": "冒烟：验证普通成员自建",
        "runMode": "ON_DEMAND",
        "taskPrompt": "整理今日待办",
        "visibleScope": "TENANT",  # 故意越权：后端必须强制降级为 SELF
    })
    show("POST /workers（普通成员自建，故意传 TENANT）", st, body, depth=420)
    if ok(st, body):
        w = body["data"]
        created_id = w.get("id")
        scope = w.get("visibleScope")
        print(f"      → visibleScope={scope} mine={w.get('mine')} editable={w.get('editable')}")
        print(f"      → {'PASS' if scope == 'SELF' else 'FAIL'} 越权 scope 已被强制降级")

    if created_id:
        st, body = call("PUT", f"/workers/{created_id}", t_user, json={"description": "冒烟：本人改配置"})
        show("PUT /workers/{id}（本人修改）", st, body, depth=300)

    print("\n=== 3. AI 解读 ===")
    st, body = call("POST", "/kpi/board/insight?period=month", t_admin)
    show("POST /kpi/board/insight", st, body, depth=500)
    if ok(st, body):
        d = body["data"]
        print(f"      → source={d.get('source')} model={d.get('model')} tokens={d.get('promptTokens')}")
        print(f"      → 解读前 120 字：{(d.get('insight') or '')[:120]}")

    print("\n=== 4. Agent 存活 ===")
    try:
        r = CLIENT.get(f"{AGENT}/health", timeout=10)
        print(f"[{'PASS' if r.status_code == 200 else 'FAIL'}] agent /health http={r.status_code}")
    except Exception as e:
        print(f"[FAIL] agent /health {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
