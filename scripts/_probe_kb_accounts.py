# -*- coding: utf-8 -*-
"""知识库共享可见性批量探针（纯 HTTP，无浏览器）。

对一批账号逐个登录，打印：
  - 登录返回的 tenantId / roles
  - GET /api/v1/kb/documents         （用户端「我的知识库」口径 = listVisible）
  - GET /api/v1/kb/documents?scope=tenant （管理端「租户全部资料」，仅 ROLE_ADMIN）
  - GET /api/v1/org/kb               （机构知识库挂载清单，FR-I1）

用法：python scripts/_probe_kb_accounts.py [username ...]
"""
import sys

import httpx

API = "http://127.0.0.1:8080/api/v1"
PWD = "User@123"
DEFAULT_USERS = ["dsj_admin", "fagai_admin", "fagai_li", "shenpi_admin",
                 "chengtou_admin", "wjj_admin"]


def show(username):
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": username, "password": PWD}).json()
    if d.get("code") != 0:
        print(f"\n### {username}: 登录失败 {d}")
        return
    me = d["data"].get("user") or {}
    tok = d["data"]["accessToken"]
    h = {"Authorization": "Bearer " + tok}
    print(f"\n### {username}  tenant={me.get('tenantId')} uid={me.get('id')} "
          f"roles={me.get('roles')}")

    for label, url in [
        ("我的知识库  /kb/documents", f"{API}/kb/documents"),
        ("租户总览    /kb/documents?scope=tenant", f"{API}/kb/documents?scope=tenant"),
        ("机构知识库  /org/kb", f"{API}/org/kb"),
    ]:
        r = c.get(url, headers=h)
        try:
            body = r.json()
        except Exception:
            print(f"  {label}: HTTP {r.status_code} 非法 JSON")
            continue
        if body.get("code") != 0:
            print(f"  {label}: HTTP {r.status_code} code={body.get('code')} "
                  f"msg={body.get('message')}")
            continue
        data = body.get("data")
        if isinstance(data, list):
            print(f"  {label}: {len(data)} 条")
            for x in data:
                print(f"      id={x.get('id')} {x.get('name')!r} "
                      f"scope={x.get('scope')} owner={x.get('ownerUserId')} "
                      f"state={x.get('state')}")
        else:
            items = (data or {}).get("items") or []
            print(f"  {label}: total={data.get('total')} indexed={data.get('indexedCount')}"
                  if isinstance(data, dict) else f"  {label}: {data}")
            for x in items:
                print(f"      {x}")
    c.close()


if __name__ == "__main__":
    users = sys.argv[1:] or DEFAULT_USERS
    for u in users:
        show(u)
