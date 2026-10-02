# -*- coding: utf-8 -*-
"""只读探针：采集【项目管理】【项目与仓库】两模块的**当前实测基线**。

为什么需要它：
    手工用例的「前置条件 / 预期结果」必须与**当天真实系统**同源（铁律 1）。
    本探针只读不写，把两模块的当前状态（枚举字典、列表内容、Gitee 初始化态、
    运维统计、权限可见性）一次性打出来，供用例编写者对齐。

用法：python scripts/_probe_pm_gitee_state.py
"""
import json
import sys

import httpx

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"

C = httpx.Client(timeout=30, trust_env=False)


def login(name, pwd=PWD):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                          "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"]


def get(path, h):
    try:
        r = C.get(f"{API}{path}", headers=h)
        return r.status_code, r.json()
    except Exception as e:  # noqa: BLE001
        return -1, {"error": str(e)}


def show(title, path, h, keys=None):
    code, d = get(path, h)
    print(f"\n=== {title}  [{path}]  http={code}")
    if keys:
        data = d.get("data")
        if isinstance(data, dict):
            print("  " + json.dumps({k: data.get(k) for k in keys},
                                    ensure_ascii=False, default=str))
        else:
            print("  " + json.dumps(d, ensure_ascii=False, default=str)[:1500])
    else:
        print("  " + json.dumps(d, ensure_ascii=False, default=str)[:2500])
    return d


def main():
    h = {"Authorization": "Bearer " + login(USER)}
    print(f"# 探针基线  tenant={TENANT}  user={USER}")

    show("PM 配置字典（类型/状态/优先级）", "/pm/config", h)
    show("PM 项目列表", "/pm/projects?page=1&size=50", h)

    show("Gitee 初始化状态", "/gitee/init", h)
    show("Gitee 租户配置", "/gitee/tenant-config", h)
    show("Gitee 运维任务统计", "/gitee/tasks/stats", h)
    show("Gitee 项目仓库列表", "/gitee/projects", h)
    show("Gitee 可选部门", "/gitee/departments", h)
    show("Gitee 个人绑定状态", "/gitee/bind", h)
    show("Gitee 前端配置视图", "/gitee/config", h)

    print("\n# 探针完成（只读，未产生任何写入）")


if __name__ == "__main__":
    sys.exit(main())
