# -*- coding: utf-8 -*-
"""需求一「用户端项目上下文与跨项目隔离」的服务端活体哨兵（docs/44 §1）。

**它验的不是「接口回 200」，而是「隔离真的成立」**——回 200 与数据落到正确的项目毫无关系
（铁律 12 的教训：判据必须回到事实源头）。因此：

  · 每条「落库」断言都回 **MySQL `chat_conversation`** 复核，不读接口自己的回显；
  · 每条「隔离」断言都做 **集合判定**（相等 / 不相交），不是「包含」；
  · 数字人准入用 **同 id、只改 enabled** 的负向对照，证明判据不是恒真。

三层隔离（docs/44 §1.3-④）在本脚本的覆盖：
  ① 候选集过滤        —— 属前端（H5），本脚本用 H5 产物静态检查 G 组兜底；
  ② 会话绑定硬校验     —— B 组（403 负向对照）；
  ③ 上下文下发 buildScope —— D 组（数据出口在，真实下发需 agent 在线，如实记 SKIP）。

用法：
    python scripts/_verify_project_isolation.py                 # 活体（默认 8080）
    python scripts/_verify_project_isolation.py --base http://127.0.0.1:8081/api/v1
    python scripts/_verify_project_isolation.py --selftest      # 纯函数自检（判据是否非恒真）

A/B 负向对照（证明本脚本会红，不是恒绿）：
    同一脚本指向**旧 jar**（:8080，未含 V79/B 组逻辑）时，B1/B2/C1 三条必须 FAIL；
    指向新 jar（:8081）时全绿。两条命令的结果已在会话记录中留存。

退出码：0=全过；1=有失败或有 SKIP（「没验到」绝不当作「通过」）。
"""
import argparse
import os
import sys
import time

import httpx
import pymysql

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
H5_PRODUCT = os.path.join(REPO, "user-client", "index.html")
H5_SOURCE = os.path.join(REPO, "user-client", "_oa_app.js")
MIGRATION = os.path.join(REPO, "server", "aioa-boot", "src", "main", "resources",
                         "db", "migration", "V79__chat_conversation_project.sql")
CONV_SRC = os.path.join(REPO, "server", "aioa-chat", "src", "main", "java", "cn", "aioa",
                        "chat", "service", "ConversationService.java")

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)

C = httpx.Client(timeout=60, trust_env=False)
RES = []
SKIPS = []


class Abort(Exception):
    """前置失败提前退出（finally 仍自净）。"""


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def skip(cid, why):
    SKIPS.append((cid, why))
    print("  SKIP %s  | %s" % (cid, why))


def token(name, pwd=PWD):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}（环境漂移？铁律 15）")
    return {"Authorization": f"Bearer {d['data']['accessToken']}"}


def call(method, path, h, **kw):
    return getattr(C, method)(f"{API}{path}", headers=h, **kw).json()


def db_all(sql, args=None):
    conn = pymysql.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute(sql, args or ())
        return cur.fetchall()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 纯函数判据（--selftest 直接测它们，证明「非恒真」）
# ----------------------------------------------------------------------

def set_equal(a, b):
    return set(a) == set(b)


def set_disjoint(a, b):
    return not (set(a) & set(b))


def rows_all_project(rows, expected_pid):
    """rows: [(id, project_id)] → 每行的 project_id 都必须等于 expected_pid。"""
    return all(pid == expected_pid for _, pid in rows)


def selftest():
    print("== 判据纯函数自检（必须能区分真/假，否则断言无意义）==")
    ok = True
    cases = [
        ("set_equal 相等", set_equal([1, 2], [2, 1]), True),
        ("set_equal 不等", set_equal([1, 2], [1]), False),
        ("set_disjoint 相交→False", set_disjoint([1, 2], [2, 3]), False),
        ("set_disjoint 不相交→True", set_disjoint([1], [2]), True),
        ("rows_all_project 越界→False", rows_all_project([(9, 1), (8, 2)], 1), False),
        ("rows_all_project 全等→True", rows_all_project([(9, 1), (8, 1)], 1), True),
    ]
    for name, got, want in cases:
        good = (got == want)
        ok = ok and good
        print("  %s %s" % ("PASS" if good else "FAIL", name))
    print("[SELFTEST] %s" % ("OK" if ok else "BROKEN"))
    sys.exit(0 if ok else 1)


# ----------------------------------------------------------------------
# 静态检查（加列零回归的「静态」证据 + H5 产物兜底）
# ----------------------------------------------------------------------

def check_static():
    print("== E 组：静态证据 ==")
    # E1 V79 存在且是可空加列
    sql = open(MIGRATION, encoding="utf-8").read() if os.path.exists(MIGRATION) else ""
    chk("E1 V79 迁移存在且为 chat_conversation 加可空 project_id",
        "ALTER TABLE `chat_conversation`" in sql and "`project_id`" in sql and "NULL" in sql,
        MIGRATION)

    # E2 无位置式 INSERT / SELECT *（MyBatis-Plus 字段映射，列序无关）
    bad = []
    for root, _, files in os.walk(os.path.join(REPO, "server")):
        if os.sep + "target" + os.sep in root + os.sep:
            continue
        for f in files:
            if not f.endswith((".java", ".xml")):
                continue
            p = os.path.join(root, f)
            try:
                txt = open(p, encoding="utf-8").read()
            except Exception:
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                low = line.lower()
                if "insert into chat_conversation" in low or ("select *" in low and "chat_conversation" in low):
                    bad.append("%s:%d" % (p, i))
    chk("E2 无位置式 INSERT / SELECT * 触及 chat_conversation", not bad, bad)

    # E3 会话创建的硬校验只在一处（ConversationService.bindWorker 调 isWorkerUsable）
    src = open(CONV_SRC, encoding="utf-8").read() if os.path.exists(CONV_SRC) else ""
    chk("E3 会话绑定项目校验走端口（isWorkerUsable）", "pmAiScopePort.isWorkerUsable" in src, "")

    # G 组 H5 产物兜底：改了源没重建产物，这里会红
    html = open(H5_PRODUCT, encoding="utf-8", errors="ignore").read() if os.path.exists(H5_PRODUCT) else ""
    for cid, needle, why in [
        ("G1", "enterProject", "H5 产物含 enterProject（可点击进入项目）"),
        ("G2", "projectConvId", "H5 产物含按项目分账会话 projectConvId"),
        ("G3", "currentProjectId", "H5 产物含唯一「当前项目」读取入口"),
    ]:
        chk("%s %s" % (cid, why), needle in html, "")

    # G4 ★ 回归指纹：H5 早期版本在项目分支里**无条件复用**已存在的项目会话：
    #     if(existing){ S.convId = existing; return existing; }
    # 后果：进入项目时建的是「无员工会话」，之后 oaPickWorker 换了数字人、S.convId 被清空，
    # 再次发送时这段代码把那条无员工会话又取回来 ⇒ 界面上选了数字人、会话却没绑 workerId
    # ⇒ 职责范围/项目上下文不生效，且后端 403 准入被整条绕过。正确写法必须以 worker 为条件复用。
    appjs = open(H5_SOURCE, encoding="utf-8").read() if os.path.exists(H5_SOURCE) else ""
    chk("G4 ★项目会话复用以 worker 为条件（防「选了数字人却没绑上」回归）",
        "S.projectConvWorker[pid]" in appjs
        and "if(existing){ S.convId = existing; return existing; }" not in appjs, "")


# ----------------------------------------------------------------------
# 活体检查
# ----------------------------------------------------------------------

def project_body(h, created, stamp, tag):
    r = call("post", "/pm/projects", h, json={
        "projectNo": "PM-ISO-" + tag + "-" + stamp, "name": "隔离自检" + tag + " " + stamp,
        "projectType": "BUSINESS", "budgetAmount": 1000})
    pid = (r.get("data") or {}).get("id")
    if not chk("前置 P%s 项目创建成功" % tag, r.get("code") == 0 and bool(pid), r):
        raise Abort()
    created["projects"].append(pid)
    return pid


def live(base):
    global API
    API = base
    stamp = time.strftime("%m%d-%H%M%S")
    h = token(USER)
    created = {"projects": [], "convs": []}

    # V79 是否已应用（缺列则整套无意义，如实 SKIP 而非假过）
    has_col = db_all("SELECT COUNT(*) FROM information_schema.columns "
                     "WHERE table_schema=DATABASE() AND table_name='chat_conversation' "
                     "AND column_name='project_id'")[0][0]
    if not has_col:
        skip("ALL", "chat_conversation.project_id 不存在 —— V79 未应用（指向新构建的 jar 再跑）")
        return created

    try:
        p1 = project_body(h, created, stamp, "1")
        p2 = project_body(h, created, stamp, "2")

        # 给 P1 分配一个既有数字员工 W1（P2 不分配 → 天然构成跨项目负向对照）
        wl = call("get", f"/pm/projects/{p1}/workers", h).get("data") or {}
        cands = wl.get("candidates") or []
        if not chk("前置 P1 存在可分配数字员工", len(cands) >= 1, wl):
            raise Abort()
        w1 = cands[0]["workerId"]
        ra = call("post", f"/pm/projects/{p1}/workers", h,
                  json={"workerId": w1, "assignRole": "自检-项目助理"})
        row1 = (ra.get("data") or {}).get("id")
        if not chk("前置 数字员工 W1 已分配到 P1", ra.get("code") == 0 and bool(row1), ra):
            raise Abort()

        print("== A 组：会话项目落库（写接口 + DB 事实源）==")
        r = call("post", "/conversations", h, json={"title": "iso-P1", "projectId": p1})
        c1 = (r.get("data") or {}).get("id")
        created["convs"].append(c1)
        chk("A1 建会话(projectId=P1)成功且回显 projectId=P1",
            r.get("code") == 0 and (r.get("data") or {}).get("projectId") == p1, r)
        got = db_all("SELECT project_id FROM chat_conversation WHERE id=%s", (c1,))
        chk("A2 ★DB 事实源：该会话 project_id = P1", bool(got) and got[0][0] == p1, got)

        r = call("post", "/conversations", h, json={"title": "iso-P1-w", "projectId": p1, "workerId": w1})
        c2 = (r.get("data") or {}).get("id")
        created["convs"].append(c2)
        chk("A3 建会话(P1+已分配 W1)成功", r.get("code") == 0 and bool(c2), r)
        got = db_all("SELECT project_id, worker_id FROM chat_conversation WHERE id=%s", (c2,))
        chk("A3b ★DB 事实源：project_id=P1 且 worker_id=W1",
            bool(got) and got[0][0] == p1 and got[0][1] == w1, got)

        r = call("post", "/conversations", h, json={"title": "iso-none"})
        c0 = (r.get("data") or {}).get("id")
        created["convs"].append(c0)
        got = db_all("SELECT project_id FROM chat_conversation WHERE id=%s", (c0,))
        chk("A4 不带 projectId 的会话 → project_id IS NULL（旧行为不回退）",
            bool(got) and got[0][0] is None, got)

        print("== B 组：数字人项目硬校验（403 负向对照）==")
        # B1 把 P1 的员工拿去 P2 建会话 → 必须 403
        r = call("post", "/conversations", h, json={"projectId": p2, "workerId": w1})
        cbad = (r.get("data") or {}).get("id")
        if cbad:
            created["convs"].append(cbad)
        chk("B1 ★跨项目使用未分配员工 → 403", r.get("code") == 403, r)

        # B2 同 id、只在 P1 内停用 → 再建会话必须 403（证明判据对 enabled 敏感、非恒真）
        call("put", f"/pm/projects/{p1}/workers/{row1}", h, json={"enabled": False})
        r = call("post", "/conversations", h, json={"projectId": p1, "workerId": w1})
        cbad = (r.get("data") or {}).get("id")
        if cbad:
            created["convs"].append(cbad)
        chk("B2 ★员工在项目内被停用 → 403（同 id，仅 enabled 不同）", r.get("code") == 403, r)
        # 恢复启用 + 复验可用（证明 B2 不是因为别的原因恒 403）
        call("put", f"/pm/projects/{p1}/workers/{row1}", h, json={"enabled": True})
        r = call("post", "/conversations", h, json={"projectId": p1, "workerId": w1})
        cok = (r.get("data") or {}).get("id")
        if cok:
            created["convs"].append(cok)
        chk("B2b 重新启用后可再建会话（证明 B2 是 enabled 引起、非恒 403）",
            r.get("code") == 0, r)

        # B3 不存在的员工 id → 非 0
        r = call("post", "/conversations", h, json={"projectId": p1, "workerId": 999999999})
        chk("B3 不存在的数字员工 → 非 0", r.get("code") not in (0, None), r)

        print("== C 组：列表按项目隔离（集合相等 / 不相交）==")
        db_p1 = [row[0] for row in db_all(
            "SELECT id FROM chat_conversation WHERE project_id=%s AND deleted_at IS NULL", (p1,))]
        api_p1 = [row["id"] for row in (call("get", f"/conversations?size=100&projectId={p1}", h)
                                        .get("data") or {}).get("list", [])]
        chk("C1 ★API(projectId=P1) 与 DB(P1) 集合相等（同源）", set_equal(api_p1, db_p1),
            {"api": sorted(api_p1), "db": sorted(db_p1)})

        api_p2 = [row["id"] for row in (call("get", f"/conversations?size=100&projectId={p2}", h)
                                        .get("data") or {}).get("list", [])]
        chk("C2 ★P1 与 P2 会话集合不相交（隔离）", set_disjoint(db_p1, api_p2),
            {"p1": sorted(db_p1), "p2": sorted(api_p2)})

        api_none = [row["id"] for row in (call("get", "/conversations?size=100&projectId=0", h)
                                          .get("data") or {}).get("list", [])]
        chk("C3 ★「无项目」视图不含任何项目会话", set_disjoint(api_none, db_p1 + api_p2),
            {"none": sorted(api_none)})
        chk("C3b 无项目视图含刚才的无项目会话", c0 in api_none, {"none": sorted(api_none)})

        print("== D 组：项目上下文下发 ==")
        sc = call("get", f"/pm/projects/{p1}/ai-scope?workerId={w1}", h)
        d = sc.get("data") or {}
        chk("D1 项目生效上下文出口存在（effectiveCount 字段齐）",
            sc.get("code") == 0 and "effectiveCount" in d and "effective" in d, sc)
        skip("D2 buildScope 真实下发（run 需 agent 服务在线）",
             "本环境未验：RunService.buildScope 已接 PmAiScopePort，但需跑一次真实 run 才能观察 scope 载荷"
             "（agent :8000 在线时可另起 e2e 覆盖）")

    except Abort:
        print("  前置失败，提前退出（仍执行自净）")
    finally:
        for cid in created["convs"]:
            if cid:
                call("delete", f"/conversations/{cid}", h)
        for p in created["projects"]:
            call("delete", f"/pm/projects/{p}", h)
        print("  自净：会话 %d、项目 %d 已清理" % (len(created["convs"]), len(created["projects"])))
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=API)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skip-static", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        selftest()

    if not a.skip_static:
        check_static()
    live(a.base)

    ok = sum(1 for _, v in RES if v)
    print("\n[SUMMARY] %d/%d 通过%s" % (ok, len(RES), ("，%d 跳过" % len(SKIPS)) if SKIPS else ""))
    failed = [cid for cid, v in RES if not v]
    for cid in failed:
        print("  未通过：%s" % cid)
    for cid, why in SKIPS:
        print("  跳过：%s（%s）" % (cid, why))
    if failed or SKIPS:
        sys.exit(1)


if __name__ == "__main__":
    main()
