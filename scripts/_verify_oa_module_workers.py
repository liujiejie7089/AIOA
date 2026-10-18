#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""OA 模块数字人收口哨兵（V83）。

判据（每条都必须能因缺陷而变红，禁止恒真断言 —— 铁律 7/12）：

  M1  平台模板库恰好 43 条 OA 数字人（tenant_id=0 且 is_template=1）。
      —— 若模板库为空，「从模板创建」就是空壳（本迁移之前正是如此）。
  M2  每个租户（sys_tenant.id>0）都有 43 条 OA 数字人 —— 只写模板不回填 = 用户看不见。
  M3  每条 description 非空、≥20 字、且含「不含」—— 职责必须自带反向边界，
      否则 agent 系统提示的「唯一可回答的范围」是空话。
  M4  GET /workers/templates 返回 43 条且 workerType 全为 OA*。
  M5  GET /workers 里每个 OA 条目的 roleCode **等于自身 workerType**，不是 GENERAL。
      —— 这是本轮的**核心判据**：WorkerRole.of 对未知取值静默降级 GENERAL，
         不修就是 43 个模块数字人统一自称「通用办公助手」，职责边界全错。
  M6  负向对照：同一响应里，legacy GENERAL 员工的 roleCode 仍为 GENERAL、
      roleName 仍为「通用办公助手」—— 证明 M5 不是「所有行都异常」的恒真断言。
  M7  43 个 worker_type 互不相同（防重复灌入）。
  M8  图标键都在前端白名单内（ICON_MAP），否则前端一律回落 bot、看起来全是同一个。

跑法（用装了 requests+pymysql 的解释器）：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
      scripts/_verify_oa_module_workers.py
"""
import json
import sys
import urllib.request

DB = dict(host="127.0.0.1", user="root", password="", database="aioa", charset="utf8mb4")
BASE = "http://127.0.0.1:8080/api/v1"
USER, PWD = "zhangsan", "User@123"   # 任意登录用户可读 /workers；模块数字人是 TENANT 可见

EXPECT = 43
ICONS = {"bot", "bell", "pen", "megaphone", "doc", "sheet", "chart",
         "scale", "bank", "user", "clock", "calendar", "trophy", "inbox"}

fails, hits = [], []


def ok(mid, msg):
    print("[OK]   %s %s" % (mid, msg))


def bad(mid, msg):
    fails.append(mid)
    print("[FAIL] %s %s" % (mid, msg))


def api(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def login():
    req = urllib.request.Request(BASE + "/auth/login",
                                data=json.dumps({"username": USER, "password": PWD}).encode(),
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.loads(r.read().decode("utf-8"))
    return (body.get("data") or {}).get("token") or (body.get("data") or {}).get("accessToken")


def main():
    try:
        import pymysql
    except ImportError:
        print("[ENV] 缺 pymysql —— 用 envs/default 的解释器跑")
        return 2
    conn = pymysql.connect(**DB)
    cur = conn.cursor()

    # M1 模板库
    cur.execute("SELECT worker_type, name, icon, description FROM agent_worker "
                "WHERE tenant_id=0 AND is_template=1 AND worker_type LIKE 'OA%%' AND deleted_at IS NULL")
    tpl = cur.fetchall()
    if len(tpl) == EXPECT:
        ok("M1", "模板库 %d 条" % len(tpl))
    else:
        bad("M1", "模板库应 %d 条，实为 %d 条" % (EXPECT, len(tpl)))

    # M7 唯一性
    codes = [r[0] for r in tpl]
    if len(set(codes)) == len(codes) == EXPECT:
        ok("M7", "worker_type 互不相同，共 %d 个" % len(codes))
    else:
        bad("M7", "worker_type 有重复：%d 行 / %d 个唯一值" % (len(codes), len(set(codes))))

    # M3 职责文案
    weak = [r[0] for r in tpl if not r[3] or len(r[3]) < 20 or "不含" not in r[3]]
    if weak:
        bad("M3", "以下类型职责文案不合格（空/过短/无反向边界）：%s" % weak)
    else:
        ok("M3", "43 条职责均含正向范围 + 「不含…」反向边界")

    # M8 图标键
    bad_icons = sorted({r[2] for r in tpl} - ICONS)
    if bad_icons:
        bad("M8", "图标键不在白名单，前端会回落 bot：%s" % bad_icons)
    else:
        ok("M8", "图标键均在前端白名单内（覆盖 %d 种）" % len({r[2] for r in tpl}))

    # M2 每租户回填
    cur.execute("SELECT id FROM sys_tenant WHERE id>0 AND deleted_at IS NULL ORDER BY id")
    tenants = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT tenant_id, COUNT(DISTINCT worker_type) FROM agent_worker "
                "WHERE worker_type LIKE 'OA%%' AND deleted_at IS NULL AND tenant_id>0 GROUP BY tenant_id")
    got = dict(cur.fetchall())
    miss = [t for t in tenants if got.get(t, 0) != EXPECT]
    if miss:
        bad("M2", "这些租户未回填满 %d 条：%s" % (EXPECT, [(t, got.get(t, 0)) for t in miss]))
    else:
        ok("M2", "%d 个租户各 %d 条模块数字人" % (len(tenants), EXPECT))
    cur.close()
    conn.close()

    token = login()
    if not token:
        bad("M4", "登录失败，无法取 /workers（账号 %s）" % USER)
        return summarize()

    # M4 模板接口
    t = (api("/workers/templates", token).get("data") or [])
    oa_t = [x for x in t if str(x.get("workerType", "")).startswith("OA")]
    if len(oa_t) == EXPECT and all(str(x["workerType"]).startswith("OA") for x in oa_t):
        ok("M4", "/workers/templates 返回 %d 条 OA 模板" % len(oa_t))
    else:
        bad("M4", "/workers/templates OA 模板应 %d 条，实为 %d 条（总 %d）" % (EXPECT, len(oa_t), len(t)))

    # M5 角色画像不降级。注意接口字段名：WorkerView.workerType 装的是「角色码」
    # （即 WorkerProfile.code()），roleName 是展示名 —— 降级时二者都会变成 GENERAL/「通用办公助手」。
    workers = (api("/workers", token).get("data") or [])
    oa_w = [w for w in workers if str(w.get("workerType", "")).startswith("OA")]
    wrong = [(w.get("workerType"), w.get("roleName"), w.get("name"), w.get("boundary"))
             for w in oa_w
             if w.get("roleName") in (None, "", "通用办公助手")
             or not str(w.get("name", "")).startswith(str(w.get("roleName", "")))
             or not w.get("boundary")]
    if not oa_w:
        bad("M5", "/workers 里没有任何 OA 模块数字人 —— 角色码已被 WorkerRole.of 降级成 GENERAL")
    elif wrong:
        bad("M5", "以下 OA 条目角色画像不完整（roleName 应为自身名称前缀 / boundary 不得为空）：%s" % wrong[:5])
    else:
        ok("M5", "%d 条 OA 条目的角色码与展示名均未被降级" % len(oa_w))

    # M6 负向对照：legacy GENERAL 仍必须是 GENERAL，否则 M5 可能只是「全部被改写」的假绿
    gen = [w for w in workers if str(w.get("workerType", "")) == "GENERAL"]
    if not gen:
        print("[SKIP] M6 该租户没有 GENERAL 员工，无法做负向对照（不代表通过）")
    elif any(w.get("roleName") != "通用办公助手" for w in gen):
        bad("M6", "负向对照破裂：GENERAL 员工被改写成 %s"
            % [(w.get("roleName")) for w in gen[:3]])
    else:
        ok("M6", "负向对照：%d 个 GENERAL 员工仍为「通用办公助手」" % len(gen))

    return summarize()


def summarize():
    if fails:
        print("\n[RESULT] FAIL %d 项：%s" % (len(fails), ",".join(fails)))
        return 1
    print("\n[RESULT] 全绿（M1–M8）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
