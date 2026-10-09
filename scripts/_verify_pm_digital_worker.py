# -*- coding: utf-8 -*-
"""项目管理「数字人分配 + 项目上下文控制」（V74 建表 / V76 补权限码）的**接口级判据**。

为什么必须有这条套件：
    这一批全是**新增可配置维度**（铁律 5：新维度必然造出旧状态机从未有过的组合），
    且有三条只能靠真请求 + 真库才能证明的语义：
      · 「上下文控制」的实质 = enabled=0 的来源**不参与**上下文组装 —— 判据必须看到它
        从「生效集」里消失、但配置仍在；
      · 「移除数字员工」的**级联边界** = 删掉该员工的专属来源，但**不碰**项目级来源
        （删多了 = 静默丢配置，删少了 = 永久无主行）；
      · 「分配」的幂等键 = (project, worker) —— 重复分配必须 409 而不是插两行。
    这些都无法从代码/编译看出，只能在真数据上数行数。

★ 同源判据（铁律 12）：期望值来自「本脚本自己 POST 了什么」；并用**直连库**复核软删状态
  （不读接口自报的副本），因为「接口说删了」与「库里真删了」是两件事。
★ 负向先行（铁律 7）：先证明非法输入被拒，再证明合法输入被接受。
★ 权限门隔离：用一个**能看到项目但没有管理权**的成员（fagai_chen / ROLE_MEMBER）验证
  pm:ai:manage / 项目角色这道门真的会拦人 —— 不是拿「跨机构看不见（404）」冒充权限拦截。
★ 自净（铁律 11）：临时项目结尾软删，使其退出业务可见面。
★ 用法：python scripts/_verify_pm_digital_worker.py
  前置：后端 :8080 已起（含本批代码）；V74/V76 已应用；MySQL 127.0.0.1:3306 可直连。
"""
import json
import sys
import time

import httpx
import pymysql

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"
# 低权限账号：ROLE_MEMBER（租户 2 / 机构 1），org_member.id=4（陈静怡）。
# 用途：加到项目里后「可见但不可写」，用于隔离验证权限门 —— 不用跨机构账号（那只会得到 404）。
LOW_USER = "fagai_chen"
LOW_MEMBER_ID = 4

DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aioa",
          charset="utf8mb4", autocommit=True)

C = httpx.Client(timeout=60, trust_env=False)
RES = []      # (cid, ok)
SKIPS = []    # (cid, why)


class Abort(Exception):
    """前置断言失败时提前退出（finally 仍执行自净）。"""


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
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return {"Authorization": f"Bearer {d['data']['accessToken']}"}


def call(method, path, h, **kw):
    return getattr(C, method)(f"{API}{path}", headers=h, **kw).json()


def raw(method, path, h, **kw):
    return C.request(method, f"{API}{path}", headers=h, **kw)


def endpoint_absent(method, path, h):
    """断言「该端点不存在」。未注册路由本项目统一回 HTTP 404 + {code:404}；405 也接受。"""
    resp = raw(method, path, h)
    sc = resp.status_code
    try:
        cj = resp.json()
    except Exception:
        cj = {}
    code = cj.get("code")
    msg = str(cj.get("message") or "")
    absent = sc == 405 or (sc == 404 and code == 404 and "接口不存在" in msg)
    return absent, sc, code, (msg or resp.text[:120])


def db_all(sql, args=None):
    conn = pymysql.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute(sql, args or ())
        return cur.fetchall()
    finally:
        conn.close()


def db_int(sql, args=None):
    rows = db_all(sql, args)
    return int(rows[0][0]) if rows else 0


def body(h, created, stamp):
    base = None
    # ---------------------------------------------------------------- 立项
    r = call("post", "/pm/projects", h, json={
        "projectNo": "PM-DW-" + stamp, "name": "数字人上下文自检 " + stamp,
        "projectType": "BUSINESS", "budgetAmount": 1000})
    pid = (r.get("data") or {}).get("id")
    if not chk("A0 业务项目创建成功（后续用例的载体）", r.get("code") == 0 and bool(pid), r):
        raise Abort()
    created.append(pid)
    base = f"/pm/projects/{pid}"

    # ---- 判据自检（铁律 12）：endpoint_absent 必须能识别「真实存在的端点」为存在，
    #      否则下方任何「缺席」类断言都是恒真。
    absent_self, sc0, code0, _ = endpoint_absent("get", f"{base}/workers", h)
    chk("A0b 判据自检：真实存在的端点不被误判为「缺席」", not absent_self, {"http": sc0, "code": code0})

    # ================================================================ 数字人分配
    wl = call("get", f"{base}/workers", h)
    data = wl.get("data") or {}
    cands = data.get("candidates") or []
    if not chk("A1 前置：本租户存在可分配数字员工（候选非空）", len(cands) >= 1, data):
        raise Abort()
    wid = cands[0]["workerId"]

    r = call("post", f"{base}/workers", h, json={"workerId": wid, "assignRole": "自检-项目助理"})
    item = r.get("data") or {}
    row_id = item.get("id")
    chk("A2 分配既有数字员工成功", r.get("code") == 0 and item.get("workerId") == wid, r)
    chk("A3 回显数字员工名称（来自 agent_worker，证明是复用而非新建）", bool(item.get("name")), item)

    r = call("post", f"{base}/workers", h, json={"workerId": wid})
    chk("A4 ★重复分配同一数字员工被拒（409，幂等键 project+worker）", r.get("code") == 409, r)

    r = call("post", f"{base}/workers", h, json={"workerId": 999999999})
    chk("A5 分配不存在的数字员工被拒（非 0）", r.get("code") not in (0, None), r)

    wl2 = call("get", f"{base}/workers", h).get("data") or {}
    chk("A6 已分配的数字员工不再出现在候选里",
        wid not in [c.get("workerId") for c in (wl2.get("candidates") or [])], wl2.get("candidates"))

    r = call("put", f"{base}/workers/{row_id}", h, json={"assignRole": "合同初审"})
    chk("A7 用途说明可更新", r.get("code") == 0 and (r.get("data") or {}).get("assignRole") == "合同初审", r)

    r = call("put", f"{base}/workers/{row_id}", h, json={"enabled": False})
    chk("A8 分配可停用（enabled=false）", r.get("code") == 0 and (r.get("data") or {}).get("enabled") is False, r)
    call("put", f"{base}/workers/{row_id}", h, json={"enabled": True})

    # ================================================================ 上下文来源
    rf = call("post", f"{base}/docs/folders", h, json={"name": "自检目录"})
    folder_id = (rf.get("data") or {}).get("id")
    if not chk("C0 前置：项目文件夹已创建（UPLOAD 来源的载体）", rf.get("code") == 0 and bool(folder_id), rf):
        raise Abort()

    # ---- UPLOAD（项目级）
    r = call("post", f"{base}/context-sources", h, json={"sourceType": "UPLOAD", "folderId": folder_id})
    up_id = (r.get("data") or {}).get("id")
    chk("C1 新增「后台上传(整目录)」来源成功", r.get("code") == 0 and bool(up_id), r)
    chk("C1b 显示名按来源自动生成（含目录名）", "自检目录" in ((r.get("data") or {}).get("name") or ""), r)

    r = call("post", f"{base}/context-sources", h, json={"sourceType": "UPLOAD"})
    chk("C2 上传来源缺 folderId/fileId 被拒（非 0）", r.get("code") not in (0, None), r)

    r = call("post", f"{base}/context-sources", h, json={"sourceType": "UPLOAD", "folderId": 999999999})
    chk("C2b 引用不存在的目录被拒（非 0）", r.get("code") not in (0, None), r)

    # ---- WEB_SEARCH（项目级）
    r = call("post", f"{base}/context-sources", h, json={
        "sourceType": "WEB_SEARCH", "config": {"keywords": ["智慧城市", "数据治理"]}})
    web_id = (r.get("data") or {}).get("id")
    chk("C3 新增「网上搜索」来源成功", r.get("code") == 0 and bool(web_id), r)
    try:
        cfg = json.loads((r.get("data") or {}).get("config") or "{}")
    except Exception:
        cfg = {}
    chk("C3b config 归一化：maxResults 默认 10", cfg.get("maxResults") == 10, cfg)
    chk("C3c 关键词完整保留（2 个）", cfg.get("keywords") == ["智慧城市", "数据治理"], cfg)

    r = call("post", f"{base}/context-sources", h, json={
        "sourceType": "WEB_SEARCH", "config": {"keywords": []}})
    chk("C4 网搜来源缺关键词被拒（非 0）", r.get("code") not in (0, None), r)

    r = call("post", f"{base}/context-sources", h, json={
        "sourceType": "WEB_SEARCH", "config": "{不是合法 json"})
    chk("C4b 非法 JSON config 被拒（非 0）", r.get("code") not in (0, None), r)

    # ---- POLICY
    r = call("post", f"{base}/context-sources", h, json={"sourceType": "POLICY"})
    chk("C5 政策来源缺 kbDocumentId 被拒（非 0）", r.get("code") not in (0, None), r)

    r = call("post", f"{base}/context-sources", h, json={"sourceType": "POLICY", "kbDocumentId": 999999999})
    chk("C5b 政策文档不存在被拒（非 0）", r.get("code") not in (0, None), r)

    r = call("post", f"{base}/context-sources", h, json={"sourceType": "WHATEVER", "folderId": folder_id})
    chk("C6 未知来源类型被拒（非 0）", r.get("code") not in (0, None), r)

    # ---- 绑定「未分配到本项目」的数字员工 → 拒绝
    r = call("post", f"{base}/context-sources", h, json={
        "sourceType": "UPLOAD", "folderId": folder_id, "workerId": 888888})
    chk("C7 上下文绑定未分配的数字员工被拒（非 0）", r.get("code") not in (0, None), r)

    # ---- 绑定「已分配」的数字员工 → 成功（专属来源）
    r = call("post", f"{base}/context-sources", h, json={
        "sourceType": "UPLOAD", "folderId": folder_id, "workerId": wid})
    wsrc_id = (r.get("data") or {}).get("id")
    chk("C8 新增「数字员工专属」来源成功", r.get("code") == 0 and bool(wsrc_id), r)
    chk("C8b 专属来源回显作用范围=该数字员工名",
        (r.get("data") or {}).get("workerId") == wid and bool((r.get("data") or {}).get("workerName")), r)

    # ================================================================ 生效视图（上下文控制语义）
    sc1 = call("get", f"{base}/ai-scope", h).get("data") or {}
    ids1 = [s.get("id") for s in (sc1.get("effective") or [])]
    chk("S1 不指定数字人时，生效集只含项目级来源（不含专属）",
        up_id in ids1 and web_id in ids1 and wsrc_id not in ids1, ids1)

    sc2 = call("get", f"{base}/ai-scope?workerId={wid}", h).get("data") or {}
    ids2 = [s.get("id") for s in (sc2.get("effective") or [])]
    chk("S2 指定数字人时，生效集 = 项目级 + 该员工专属",
        up_id in ids2 and web_id in ids2 and wsrc_id in ids2, ids2)
    chk("S2b 生效计数与「项目级 + 专属」一致（3）", sc2.get("effectiveCount") == 3, sc2.get("effectiveCount"))

    # ★ 核心语义：停用后不参与上下文组装
    call("put", f"{base}/context-sources/{web_id}", h, json={"enabled": False})
    sc3 = call("get", f"{base}/ai-scope?workerId={wid}", h).get("data") or {}
    ids3 = [s.get("id") for s in (sc3.get("effective") or [])]
    chk("S3 ★「关闭」后该来源不再进入生效集（上下文控制的实质）", web_id not in ids3, ids3)
    lst = call("get", f"{base}/context-sources", h).get("data") or {}
    kept = [s for s in (lst.get("items") or []) if s.get("id") == web_id]
    chk("S3b 关闭只影响生效、配置仍保留（列表里仍在且 enabled=false）",
        len(kept) == 1 and kept[0].get("enabled") is False, kept)
    call("put", f"{base}/context-sources/{web_id}", h, json={"enabled": True})

    # ================================================================ 权限门隔离（可见但不可写）
    rm = call("post", f"{base}/members", h, json={"memberId": LOW_MEMBER_ID, "roleCode": "MEMBER"})
    if rm.get("code") != 0:
        skip("P2 权限门隔离", "低权限账号加入项目失败：%s" % rm.get("message"))
    else:
        hl = token(LOW_USER)
        rd = call("get", base, hl)
        chk("P2a ★前提：低权限成员(ROLE_MEMBER)能看到本项目（可见性经由成员身份）",
            rd.get("code") == 0, {"code": rd.get("code"), "message": rd.get("message")})
        rw = call("post", f"{base}/workers", hl, json={"workerId": wid})
        chk("P2b ★可见但无管理权：低权限成员「分配数字人」被拒（403）", rw.get("code") == 403, rw)
        rw2 = call("post", f"{base}/context-sources", hl, json={"sourceType": "UPLOAD", "folderId": folder_id})
        chk("P2c ★可见但无管理权：低权限成员「新增上下文来源」被拒（403）", rw2.get("code") == 403, rw2)

    # ================================================================ 级联删除边界
    r = call("delete", f"{base}/workers/{row_id}", h)
    removed = (r.get("data") or {}).get("removedContextSources")
    chk("D1 移除数字员工成功", r.get("code") == 0, r)
    chk("D2 返回「连带删除的专属来源数」>=1", isinstance(removed, int) and removed >= 1, r)

    items = (call("get", f"{base}/context-sources", h).get("data") or {}).get("items") or []
    ids = [s.get("id") for s in items]
    chk("D3 ★该数字员工的专属来源已随之删除", wsrc_id not in ids, ids)
    chk("D4 ★项目级来源未被误删（负向守卫：级联不得扩大）", up_id in ids and web_id in ids, ids)

    # ---- 直连库复核（判据不与接口自报同源）
    alive_worker = db_int(
        "SELECT COUNT(*) FROM pm_project_worker WHERE id=%s AND deleted_at IS NULL", (row_id,))
    gone_src = db_int(
        "SELECT COUNT(*) FROM pm_context_source WHERE id=%s AND deleted_at IS NOT NULL", (wsrc_id,))
    alive_src = db_int(
        "SELECT COUNT(*) FROM pm_context_source WHERE id=%s AND deleted_at IS NULL", (up_id,))
    chk("D5 ★DB 复核：分配行已软删 / 专属来源已软删 / 项目级来源仍存活",
        alive_worker == 0 and gone_src == 1 and alive_src == 1,
        {"worker_alive": alive_worker, "src_gone": gone_src, "src_alive": alive_src})

    # ================================================================ 权限码播种（能力实际可用）
    cnt = db_int("SELECT COUNT(*) FROM sys_permission WHERE perm_code='pm:ai:manage' AND deleted_at IS NULL")
    chk("P1 ★权限码 pm:ai:manage 已在 sys_permission 播种（V76，能力实际可申请/可用）", cnt == 1, cnt)


def cleanup(h, created):
    ok = True
    for p in created:
        rr = call("delete", f"/pm/projects/{p}", h)
        if rr.get("code") != 0:
            ok = False
            print("    清理失败 id=%s: %s" % (p, rr.get("message")))
    chk("Z90 临时项目已全部软删（自净）", ok, created)


def main():
    stamp = time.strftime("%m%d-%H%M%S")
    h = token(USER)
    created = []
    try:
        body(h, created, stamp)
    except Abort:
        print("  前置失败，提前退出（仍执行自净）")
    finally:
        cleanup(h, created)

    ok = sum(1 for _, v in RES if v)
    print("\n[SUMMARY] %d/%d 通过%s" % (ok, len(RES),
                                       ("，%d 跳过" % len(SKIPS)) if SKIPS else ""))
    failed = [cid for cid, v in RES if not v]
    if failed:
        for cid in failed:
            print("  未通过：%s" % cid)
    for cid, why in SKIPS:
        print("  跳过：%s（%s）" % (cid, why))
    # 有失败 或 有跳过（前置不满足，未真正验证）→ 一律非 0，绝不把「没验到」当「通过」
    if failed or SKIPS:
        sys.exit(1)


if __name__ == "__main__":
    main()
