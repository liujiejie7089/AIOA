# -*- coding: utf-8 -*-
"""项目管理 批次 4（经费流水 + 合同收付款，V73/V75）的**接口级判据**。

为什么必须有这条套件：
    批次 4 有两条**跨对象、跨事务**的硬约束，光看代码/编译过不了关：
      · K4「不能修改」= 账目 append-only —— 判据不是「读注释」，而是
        「PUT/DELETE 端点不存在（405）」+「同一条原行重复红冲被拒（409）」；
      · BR-09 单一事实源 —— 确认收付款时必须在**同一事务**内生成**恰好一条**经费流水。
        少一条 = 钱没入账；多一条 = 同笔业务记两遍。两者都只能在真请求上数行数才能证明。

★ 同源判据（铁律 12）：所有金额/行数一律回到**接口**取一次再比对，
  不读任何界面副本；期望值来自「本脚本自己 POST 了什么」这个真正的事实源头。
★ 负向先行（铁律 7）：先证明端点真的会拒绝，再证明它会接受 —— 否则「通过」可能是路径写错。
★ 自净（铁律 11）：临时项目结尾软删，使其退出业务可见面。
★ 用法：python scripts/_verify_pm_finance_contract.py
  前置：后端 :8080 已起；V73/V75 已应用。
"""
import sys
import time

import httpx

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"

C = httpx.Client(timeout=60, trust_env=False)
RES = []


class Abort(Exception):
    """前置断言失败时提前退出（finally 仍执行自净）。"""


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                         ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def login(name, pwd=PWD):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": pwd,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"]


def call(method, path, h, **kw):
    return getattr(C, method)(f"{API}{path}", headers=h, **kw).json()


def raw(method, path, h, **kw):
    return C.request(method, f"{API}{path}", headers=h, **kw)


def endpoint_absent(method, path, h):
    """断言「该写端点不存在」（K4 append-only 的核心判据）。

    本项目对未注册路由统一回 **HTTP 404 + {code:404,"接口不存在：…"}**（全局异常处理器），
    405 也接受。**不接受**任何 200+code=0 —— 那才是真出了个可写的后门。
    返回 (是否缺席, HTTP 状态, body code, 摘要)。
    """
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


def num(v):
    return float(v or 0)


def body(h, created, stamp):
    # ---------------------------------------------------------------- 立项
    r = call("post", "/pm/projects", h, json={
        "projectNo": "PM-FC-" + stamp, "name": "财务合同自检 " + stamp,
        "projectType": "BUSINESS", "budgetAmount": 1000})
    pid = (r.get("data") or {}).get("id")
    if not chk("F1 业务项目创建成功（后续用例的载体）", r.get("code") == 0 and bool(pid), r):
        raise Abort()
    created.append(pid)
    base = f"/pm/projects/{pid}"

    # ---- 判据自检（铁律 12）：F4/F14 用的「端点缺席」判据必须能变红，
    #      对一个**真实存在**的端点调用它必须判「存在」，否则 F4/F14 是恒真断言。
    absent_self, sc0, code0, _ = endpoint_absent("get", f"{base}/expenses", h)
    chk("F0 判据自检：真实存在的端点不被误判为「缺席」", not absent_self, {"http": sc0, "code": code0})

    # ================================================================ 经费：追加
    r = call("post", f"{base}/expenses", h, json={
        "direction": "OUT", "category": "LABOR", "amount": 100, "remark": "自检-人工费"})
    e_out = (r.get("data") or {}).get("id")
    chk("F2a 追加支出流水成功", r.get("code") == 0 and bool(e_out), r)

    r = call("post", f"{base}/expenses", h, json={
        "direction": "IN", "category": "OTHER", "amount": 500, "remark": "自检-其他收入"})
    e_in = (r.get("data") or {}).get("id")
    chk("F2b 追加收入流水成功", r.get("code") == 0 and bool(e_in), r)

    # 非法方向必须被拒（负向先行）
    r = call("post", f"{base}/expenses", h, json={
        "direction": "SIDEWAYS", "category": "OTHER", "amount": 1})
    chk("F2c 非法方向被拒", r.get("code") not in (0, None), r)

    # ---- 汇总同源核对：期望值来自「我 POST 了什么」，不是接口自报
    lst = call("get", f"{base}/expenses", h).get("data") or {}
    s = lst.get("summary") or {}
    chk("F3a 累计支出 = 我录入的支出合计（100）", abs(num(s.get("totalOutcome")) - 100) < 0.001, s)
    chk("F3b 累计收入 = 我录入的收入合计（500）", abs(num(s.get("totalIncome")) - 500) < 0.001, s)
    chk("F3c 结余 = 预算(1000) - 支出(100) = 900", abs(num(s.get("balance")) - 900) < 0.001, s)
    chk("F3d 未超支（overrun=false）", s.get("overrun") is False, s)

    # ---- 超支只警示不阻断（BR-16）：追加一笔大额支出
    call("post", f"{base}/expenses", h, json={
        "direction": "OUT", "category": "PURCHASE", "amount": 1500, "remark": "自检-大额采购"})
    r = call("post", f"{base}/expenses", h, json={
        "direction": "OUT", "category": "OTHER", "amount": 1, "remark": "自检-超支后仍可录"})
    chk("F3e 超支后仍能继续录入（BR-16 不阻断）", r.get("code") == 0, r)
    s = (call("get", f"{base}/expenses", h).get("data") or {}).get("summary") or {}
    chk("F3f 汇总 overrun=true（支出 1601 > 预算 1000）", s.get("overrun") is True, s)

    # ================================================================ 经费：不能修改（K4）
    for m in ("put", "delete"):
        absent, sc, code, msg = endpoint_absent(m, f"{base}/expenses/{e_out}", h)
        chk(f"F4 {m.upper()} 流水端点不存在（实测 HTTP {sc} / code {code}）", absent, msg)

    # ---- 红冲：原行不改，新增「同方向负金额」红字行，且汇总按原额回退
    sum_before = (call("get", f"{base}/expenses", h).get("data") or {}).get("summary") or {}
    r = call("post", f"{base}/expenses/{e_out}/reverse", h, json={"reason": "自检-录入有误"})
    rev = r.get("data") or {}
    chk("F5a 红冲支出流水成功", r.get("code") == 0, r)
    chk("F5b 红冲行 reversalOf 指向被冲销原行", rev.get("reversalOf") == e_out, rev)
    chk("F5c ★红字冲销：红冲行方向与原行**相同**（OUT），不是翻转",
        rev.get("direction") == "OUT", rev)
    chk("F5d ★红字冲销：红冲行金额为**负数**（-100）",
        abs(num(rev.get("amount")) + 100) < 0.001, rev)
    sum_after = (call("get", f"{base}/expenses", h).get("data") or {}).get("summary") or {}
    chk("F5f ★红冲后累计支出按原额回退 100（1601 → 1501）",
        abs(num(sum_before.get("totalOutcome")) - num(sum_after.get("totalOutcome")) - 100) < 0.001,
        {"before": sum_before.get("totalOutcome"), "after": sum_after.get("totalOutcome")})
    chk("F5g ★红冲不污染收入桶（累计收入保持不变）",
        abs(num(sum_before.get("totalIncome")) - num(sum_after.get("totalIncome"))) < 0.001,
        {"before": sum_before.get("totalIncome"), "after": sum_after.get("totalIncome")})

    items = (call("get", f"{base}/expenses", h).get("data") or {}).get("items") or []
    orig = [x for x in items if x.get("id") == e_out]
    chk("F5e 原行仍在且未被标记（原行永不改）",
        len(orig) == 1 and orig[0].get("reversalOf") is None, orig)

    # ---- 重复红冲 / 红冲红冲行：两条负向约束
    r = call("post", f"{base}/expenses/{e_out}/reverse", h, json={"reason": "再冲一次"})
    chk("F6a 同一原行重复红冲被拒（409）", r.get("code") == 409, r)

    r = call("post", f"{base}/expenses/{rev.get('id')}/reverse", h, json={"reason": "冲红冲行"})
    chk("F6b 红冲一条红冲行被拒（400）", r.get("code") not in (0, None), r)

    # ================================================================ 合同
    cno = "HT-FC-" + stamp
    r = call("post", f"{base}/contracts", h, json={
        "contractNo": cno, "name": "自检采购合同", "direction": "OUT",
        "partyName": "某某供应商", "amount": 8000})
    cid = (r.get("data") or {}).get("id")
    chk("F7a 新建采购合同成功", r.get("code") == 0 and bool(cid), r)
    chk("F7b 新建合同初始状态为 DRAFT", (r.get("data") or {}).get("status") == "DRAFT", r)

    # 编号重复必须 409（软删行从唯一键消失 ⇒ 先查活行的约定）
    r = call("post", f"{base}/contracts", h, json={
        "contractNo": cno, "name": "重复编号", "direction": "OUT", "amount": 1})
    chk("F7c 重复合同编号被拒（409）", r.get("code") == 409, r)

    # 收款合同
    r = call("post", f"{base}/contracts", h, json={
        "contractNo": cno + "-IN", "name": "自检收款合同", "direction": "IN", "amount": 3000})
    cid_in = (r.get("data") or {}).get("id")
    chk("F7d 新建收款合同成功", r.get("code") == 0 and bool(cid_in), r)

    # 方向过滤（同源：只应回 OUT 一条本次造的单向合同）
    outs = call("get", f"{base}/contracts?direction=OUT", h).get("data") or {}
    chk("F7e 合同方向过滤生效（OUT 结果里不含收款合同）",
        all(x.get("direction") == "OUT" for x in (outs.get("items") or [])),
        [x.get("direction") for x in (outs.get("items") or [])])

    # 状态流转 + 已结不可再改
    r = call("post", f"{base}/contracts/{cid}/status", h, json={"status": "EXECUTING"})
    chk("F8a 合同状态流转 DRAFT→EXECUTING 成功", r.get("code") == 0, r)

    # ================================================================ BR-09 单一事实源
    r = call("post", f"{base}/contracts/{cid}/payments", h, json={"planAmount": 2000})
    pays = (r.get("data") or {}).get("items") or []
    pay = pays[-1] if pays else {}
    pay_id = pay.get("id")
    chk("F9a 新增收付款期次成功且状态 PLANNED",
        r.get("code") == 0 and bool(pay_id) and pay.get("status") == "PLANNED", r)

    before = len((call("get", f"{base}/expenses", h).get("data") or {}).get("items") or [])

    r = call("post", f"{base}/contracts/{cid}/payments/{pay_id}/confirm", h,
             json={"actualAmount": 2000})
    chk("F9b 确认收付款成功", r.get("code") == 0, r)
    confirmed = {}
    for x in ((r.get("data") or {}).get("items") or []):
        if x.get("id") == pay_id:
            confirmed = x
    chk("F9c 期次状态置 CONFIRMED 且实付已写入",
        confirmed.get("status") == "CONFIRMED" and abs(num(confirmed.get("actualAmount")) - 2000) < 0.001,
        confirmed)

    items = (call("get", f"{base}/expenses", h).get("data") or {}).get("items") or []
    linked = [x for x in items if x.get("contractPaymentId") == pay_id and not x.get("isReversal")]
    chk("F10a ★BR-09：确认后恰好多出 1 条经费流水（不是 0、不是 2）",
        len(items) == before + 1, {"before": before, "after": len(items)})
    chk("F10b ★BR-09：该流水溯源到本次收付款期次（contractPaymentId 精确命中）",
        len(linked) == 1, linked)
    chk("F10c 自动流水金额 = 实付 2000、方向 OUT（采购付款支出）",
        bool(linked) and abs(num(linked[0].get("amount")) - 2000) < 0.001
        and linked[0].get("direction") == "OUT", linked[:1])

    # 重复确认必须被拒（只能确认 PLANNED）
    r = call("post", f"{base}/contracts/{cid}/payments/{pay_id}/confirm", h, json={})
    chk("F11 重复确认同一起期次被拒（409）", r.get("code") == 409, r)

    # ---- 红冲收付款：置 REVERSED + 追加反向流水
    exp_id = linked[0].get("id") if linked else None
    r = call("post", f"{base}/contracts/{cid}/payments/{pay_id}/reverse", h, json={"reason": "自检-退回"})
    chk("F12a 红冲已确认收付款成功", r.get("code") == 0, r)
    reved = {}
    for x in ((r.get("data") or {}).get("items") or []):
        if x.get("id") == pay_id:
            reved = x
    chk("F12b 期次状态置 REVERSED", reved.get("status") == "REVERSED", reved)

    items = (call("get", f"{base}/expenses", h).get("data") or {}).get("items") or []
    rev_rows = [x for x in items if x.get("reversalOf") == exp_id]
    chk("F12c 红冲收付款追加了反向流水（reversalOf 指向原自动流水）",
        len(rev_rows) == 1, {"exp_id": exp_id, "rev_rows": rev_rows})
    chk("F12d ★合同红冲流水同为「同方向负金额」（OUT / -2000）",
        bool(rev_rows) and rev_rows[0].get("direction") == "OUT"
        and abs(num(rev_rows[0].get("amount")) + 2000) < 0.001, rev_rows[:1])

    # 非确认态不可红冲
    r = call("post", f"{base}/contracts/{cid}/payments/{pay_id}/reverse", h, json={})
    chk("F13 红冲一条已红冲的收付款被拒（409）", r.get("code") == 409, r)

    # 已确认收付款不可删（无 delete 端点）
    absent, sc, code, msg = endpoint_absent("delete", f"{base}/contracts/{cid}/payments/{pay_id}", h)
    chk(f"F14 收付款没有删除端点（实测 HTTP {sc} / code {code}）", absent, msg)


def cleanup(h, created):
    ok = True
    for p in created:
        rr = call("delete", f"/pm/projects/{p}", h)
        if rr.get("code") != 0:
            ok = False
            print("    清理失败 id=%s: %s" % (p, rr.get("message")))
    chk("F90 临时项目已全部软删（自净）", ok, created)


def main():
    stamp = time.strftime("%m%d-%H%M%S")
    h = {"Authorization": f"Bearer {login(USER)}"}
    created = []
    try:
        body(h, created, stamp)
    except Abort:
        print("  前置失败，提前退出（仍执行自净）")
    finally:
        cleanup(h, created)

    ok = sum(1 for _, v in RES if v)
    print("\n[SUMMARY] %d/%d 通过" % (ok, len(RES)))
    if ok != len(RES):
        for cid, v in RES:
            if not v:
                print("  未通过：%s" % cid)
        sys.exit(1)


if __name__ == "__main__":
    main()
