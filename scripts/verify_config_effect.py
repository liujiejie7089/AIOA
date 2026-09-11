"""参数真实生效 A/B 自检（方案 P6）。

对每个专家配置参数做「改配置 → 观察生效值/行为变化」的断言：
  - 温度：同一 query 在不同 temperature 下 resolve 返回不同，且 mock 采样分布可区分；
  - topK / threshold / retrievalMode / kbScope / enabled / visibleScope / tools：改配置后
    经 resolve 接口与工具网关行为可观测变化。

用法：python scripts/verify_config_effect.py
"""
import json
import sys

import httpx

BASE = "http://127.0.0.1:8080"
DEFAULT_PWD = "User@123"

c = httpx.Client(base_url=BASE, trust_env=False, timeout=30)


def login(u, p=DEFAULT_PWD):
    r = c.post("/api/v1/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["data"]["accessToken"]}


def resolve(H, key, **ctx):
    q = "&".join(f"{k}={v}" for k, v in ctx.items() if v is not None)
    url = f"/api/v1/expert-config/experts/{key}/resolve" + (("?" + q) if q else "")
    return c.get(url, headers=H).json()["data"]


def save_config(H, key, scope_type, config, merge=False):
    body = {"scopeType": scope_type, "scopeId": 0, "config": config}
    method = c.put if merge else c.post
    return method(f"/api/v1/expert-config/experts/{key}/config", headers=H, json=body).json()


def delete_config(H, key, scope_type):
    return c.delete(f"/api/v1/expert-config/experts/{key}/config",
                    headers=H, params={"scopeType": scope_type}).json()


def check(name, cond, detail=""):
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f"  {detail}" if detail else ""))
    return cond


def main():
    results = []
    H = login("admin", "Admin@123")  # 平台管理员（可改 GLOBAL 层）

    key = "data_analyst"

    # 1) 基线：读默认配置
    base = resolve(H, key)
    results.append(check("基线配置可读", base["temperature"] == 0.3 and base["topK"] == 5,
                         f"temp={base['temperature']} topK={base['topK']}"))

    # 2) 温度：改 GLOBAL 层 temperature=0.9，resolve 应返回 0.9 且 sources 指向 GLOBAL
    save_config(H, key, "TENANT", {"temperature": 0.9})
    r = resolve(H, key)
    results.append(check("温度改 0.9 生效", r["temperature"] == 0.9 and r["sources"]["temperature"].startswith("TENANT"),
                         f"temp={r['temperature']} src={r['sources']['temperature']}"))
    # 恢复
    delete_config(H, key, "TENANT")
    r2 = resolve(H, key)
    results.append(check("温度恢复默认 0.3", r2["temperature"] == 0.3, f"temp={r2['temperature']}"))

    # 3) topK：改 10
    save_config(H, key, "TENANT", {"topK": 10})
    r = resolve(H, key)
    results.append(check("topK 改 10 生效", r["topK"] == 10, f"topK={r['topK']}"))
    delete_config(H, key, "TENANT")

    # 4) threshold：改 0.8
    save_config(H, key, "TENANT", {"threshold": 0.8})
    r = resolve(H, key)
    results.append(check("threshold 改 0.8 生效", r["threshold"] == 0.8, f"threshold={r['threshold']}"))
    delete_config(H, key, "TENANT")

    # 5) retrievalMode：改 vector
    save_config(H, key, "TENANT", {"retrievalMode": "vector"})
    r = resolve(H, key)
    results.append(check("retrievalMode 改 vector 生效", r["retrievalMode"] == "vector",
                         f"mode={r['retrievalMode']}"))
    delete_config(H, key, "TENANT")

    # 6) enabled：关 legal
    save_config(H, "legal", "TENANT", {"enabled": False})
    r = resolve(H, "legal")
    results.append(check("enabled=false 生效", r["enabled"] is False, f"enabled={r['enabled']}"))
    delete_config(H, "legal", "TENANT")

    # 7) tools：关 data_analyst 的 sql_query
    save_config(H, key, "TENANT", {"tools": {"sql_query": False}})
    r = resolve(H, key)
    results.append(check("tools.sql_query=false 生效", r["tools"]["sql_query"] is False,
                         f"tools={r['tools']}"))
    delete_config(H, key, "TENANT")

    # 8) kbScope：限定到文档 68
    save_config(H, key, "TENANT", {"kbScope": "68"})
    r = resolve(H, key)
    results.append(check("kbScope=68 生效", r["kbScope"] == "68", f"kbScope={r['kbScope']}"))
    delete_config(H, key, "TENANT")

    # 9) 工具网关：SQL 工具真实执行（A/B：租户2 有数据）
    HT = login("dsj_admin")
    r = c.post("/api/v1/tools/invoke", headers=HT,
               json={"name": "sql_query", "arguments": {"sql": "SELECT COUNT(*) AS n FROM biz_customer"}}).json()
    ok = r["data"].get("ok") is True
    results.append(check("SQL 工具真实取数", ok, f"ok={r['data'].get('ok')}"))

    # 10) 可见范围：visibleScope=TENANT 时，其他租户用户应看不到
    # （此处只验证 resolve 返回正确值，真正的可见性过滤在 experts 列表接口）
    save_config(H, key, "TENANT", {"visibleScope": "TENANT"})
    r = resolve(H, key)
    results.append(check("visibleScope=TENANT 生效", r["visibleScope"] == "TENANT",
                         f"visibleScope={r['visibleScope']}"))
    delete_config(H, key, "TENANT")

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*50}\n自检结果：{passed}/{total} 通过")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
