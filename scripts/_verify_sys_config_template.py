# -*- coding: utf-8 -*-
"""系统参数「本地齐全、生产只剩几项」漂移修复的验收（docs/44 §4）。

缺陷（已定位）：生产 `GET /api/v1/admin/configs` 的 `total` 只有 3，本地演示租户是 14+。
根因是三层叠加：
  ① V18 的 14 条只播 `tenant_id=1`，平台模板 `tenant_id=0` 一条都没播；
  ② V33/V34 各往 `tenant_id=0` 插 1 条 ⇒ 模板成了「非空但只有 3 条」的畸形态
     （V62 的注释**明确警告过**这个坑，V33/V34 没遵守）；
  ③ 旧 `loadTenantConfigs` 的 `if (!rows.isEmpty()) return rows;` 使「已有几行但缺基座」的
     租户永不补齐；而 `if (templates.isEmpty())` 又让代码兜底永不触发。
  ⇒ 任何 tenant_id≠1 的租户只能看到 3 条、且永远停在 3 条。

修法（数据 + 逻辑，缺一不可）：
  · 数据面：迁移 `V78__sys_config_template_backfill.sql`（补全模板 + 幂等回填已有租户）；
  · 逻辑面：`AdminConfigController.loadTenantConfigs` 改为「config_key 键级并集自愈」，
    并新增 `healTemplate()` 防「模板残缺」继续传播。

判据（对应 docs/44 §4.5 D1–D4；D5 见「诚实 SKIP」）：
  D2 静态：各迁移里出现过的 sys_config 键 ⊆ V78 补全后的模板键
  D1 DB  ：模板键 ⊇ 全库键并集；**每个有参数行的租户都拥有全部模板键**（核心）
  D1 API ：租户管理员读 /admin/configs 的 total/键集 == 模板键集（逐键，不是只比个数）
  D4     ：把 V78 的 SQL 连跑两次 ⇒ 结果一致；**任何已存在的值都不被覆盖**（只补缺失键）
  D3     ：负向对照 —— 删掉某租户一条参数 ⇒ 再读**自动补回**（自愈生效）；
           删掉平台模板一条内建键 ⇒ 再读**不报错**且模板被补回

诚实 SKIP：D5「新租户入驻后 sys_config/leave_type/approval_flow_def/org_duty 同时齐备」
  需要跑真实入驻流程 + 统一播种器（docs/44 §4.3-③，尚未开工），本脚本**不伪装 PASS**。

用法：
    python scripts/_verify_sys_config_template.py [--base http://127.0.0.1:8080/api/v1]
退出码：0 全过；1 有失败。
"""
import argparse
import glob
import os
import re
import sys

import httpx
import pymysql
from pymysql.constants import CLIENT

API = "http://127.0.0.1:8080/api/v1"
TENANT = "某某市某某区大数据管理局"
USER, PWD = "dsj_admin", "User@123"
HERE = os.path.dirname(os.path.abspath(__file__))
MIG_DIR = os.path.join(HERE, "..", "server", "aioa-boot", "src", "main", "resources", "db", "migration")
V78 = os.path.join(MIG_DIR, "V78__sys_config_template_backfill.sql")
DB = dict(host="127.0.0.1", port=3306, user="root", password="",
          database="aioa", charset="utf8mb4")

C = httpx.Client(timeout=60, trust_env=False)
RES = []


def chk(cid, cond, detail=""):
    RES.append((cid, bool(cond)))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", cid,
                        ("  | " + str(detail)[:400]) if detail else ""))
    return bool(cond)


def skip(cid, why):
    print("  SKIP %s  %s" % (cid, why))


# 参数键的特征：含点的小写标识（chat.* / quota.* / kb.* / security.* / billing.* / approval.*）。
# 其它单引号字面量（'INT' 'BOOL' 'CONVERSATION' 'auto' 'general' …）都不含点 ⇒ 可安全区分。
KEY_RE = re.compile(r"'([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)'")


def migrations_keys():
    """各迁移里出现过的 sys_config 候选键（静态判据的输入）。"""
    out = set()
    for f in sorted(glob.glob(os.path.join(MIG_DIR, "*.sql"))):
        txt = open(f, encoding="utf-8").read()
        if "sys_config" not in txt:
            continue
        # 只看 INSERT/UPDATE sys_config 语句块，避免把别表的键误纳
        for m in re.finditer(r"(INSERT|UPDATE)\s+INTO?\s+`?sys_config`?(.*?);", txt, re.S | re.I):
            out |= set(KEY_RE.findall(m.group(2)))
    return out


def db_rows(cur):
    cur.execute("SELECT tenant_id, config_key, config_value, default_value "
                "FROM sys_config WHERE deleted_at IS NULL")
    return {(t, k): (v, d) for t, k, v, d in cur.fetchall()}


def main():
    h = {"Authorization": "Bearer " + _login(USER)}
    db = pymysql.connect(**DB)
    cur = db.cursor()

    try:
        # ---------------- D2 静态 ----------------
        mk = migrations_keys()
        before = db_rows(cur)
        tpl = {k for (t, k) in before if t == 0}
        chk("D2 静态：迁移里出现过的 sys_config 键都已被模板覆盖",
            mk <= tpl, sorted(mk - tpl))
        chk("D2b 静态：V78 迁移存在且含「补模板 + 幂等回填」两步",
            os.path.isfile(V78)
            and "ON DUPLICATE KEY UPDATE" in open(V78, encoding="utf-8").read()
            and "CROSS JOIN" in open(V78, encoding="utf-8").read(), V78)

        # ---------------- D1 DB ----------------
        allk = {k for (t, k) in before}
        chk("D1a DB：模板键 ⊇ 全库键并集（无「某租户有、模板没有」的孤儿键）",
            allk <= tpl, sorted(allk - tpl))

        tenants = sorted({t for (t, k) in before if t != 0})
        incomplete = {}
        for t in tenants:
            have = {k for (tt, k) in before if tt == t}
            miss = tpl - have
            if miss:
                incomplete[t] = sorted(miss)
        chk("D1b ★DB：每个有参数行的租户都拥有**全部模板键**（本次缺陷的核心）",
            not incomplete, incomplete)

        # ---------------- D4 幂等 + 不覆盖 ----------------
        sql = open(V78, encoding="utf-8").read()
        errs = []
        for i in (1, 2):
            try:
                cs = db.cursor()
                cs.execute(sql)          # 多语句：V78 只有 INSERT，无结果集
                while cs.nextset():
                    pass
                cs.close()
            except Exception as e:       # noqa: BLE001
                errs.append("第%d次执行失败: %s" % (i, e))
        chk("D4a V78 的 SQL 可重复执行（幂等，连跑两次无异常）", not errs, errs)
        after1 = db_rows(cur)
        overwritten = {k: (before[k], after1[k]) for k in before if k in after1 and after1[k] != before[k]}
        chk("D4b ★不覆盖：任何**已存在**的值在重跑后都未被改写（只补缺失键）",
            not overwritten, overwritten)
        cs = db.cursor()
        cs.execute(sql)
        while cs.nextset():
            pass
        cs.close()
        after2 = db_rows(cur)
        chk("D4c 连跑两次结果一致（幂等）", after1 == after2,
            "行数 %d vs %d" % (len(after1), len(after2)))

        # 每个租户现在都完整
        after = after2
        tpl2 = {k for (t, k) in after if t == 0}
        bad = {t: sorted(tpl2 - {k for (tt, k) in after if tt == t})
               for t in sorted({t for (t, k) in after if t != 0})}
        bad = {t: v for t, v in bad.items() if v}
        chk("D4d 重跑后所有租户仍完整（幂等不产生回退）", not bad, bad)

        # ---------------- D1 API ----------------
        r = C.get(f"{API}/admin/configs", headers=h).json()
        data = r.get("data") or {}
        got = {it.get("configKey") for it in (data.get("items") or [])}
        chk("D1c ★API：租户管理员读到的 total == 模板键数（逐键比对，不只看个数）",
            r.get("code") == 0 and data.get("total") == len(tpl2) and got == tpl2,
            "code=%s total=%s 模板=%d 差=%s" % (r.get("code"), data.get("total"), len(tpl2),
                                            sorted(tpl2 ^ got)))
        groups = data.get("groups") or {}
        chk("D1d API：AUDIT 分组已登记（approval.tenant.content 不再「库里有、界面看不见」）",
            "AUDIT" in groups, groups)

        # ---------------- D3 负向对照：自愈 ----------------
        # 选一条「值 == 出厂默认」的租户键来删，保证自愈补回后与原值相等（不丢用户数据）
        victim = None
        for (t, k), (v, d) in after.items():
            if t == 2 and v == d and k in tpl2:
                victim = (t, k)
                break
        if not victim:
            skip("D3a", "租户 2 找不到「值==默认」的键，跳过（不伪装 PASS）")
        else:
            t, k = victim
            cur.execute("DELETE FROM sys_config WHERE tenant_id=%s AND config_key=%s", (t, k))
            db.commit()
            miss_now = k not in {kk for (tt, kk) in db_rows(cur) if tt == t}
            r2 = C.get(f"{API}/admin/configs", headers=h).json()
            back = k in {it.get("configKey") for it in ((r2.get("data") or {}).get("items") or [])}
            chk("D3a ★负向对照：删掉租户 2 的一条参数 → 再读**自动补回**（自愈生效）",
                miss_now and back, "删后缺失=%s 读后补回=%s key=%s" % (miss_now, back, k))

        # 模板侧：删一条「内建且值==默认」的模板键 → 再读不得报错，且模板被补回
        tv = None
        for (t, k), (v, d) in after.items():
            if t == 0 and v == d and k in tpl2:
                tv = k
                break
        if not tv:
            skip("D3b", "模板里找不到「值==默认」的键，跳过（不伪装 PASS）")
        else:
            cur.execute("DELETE FROM sys_config WHERE tenant_id=0 AND config_key=%s", (tv,))
            db.commit()
            r3 = C.get(f"{API}/admin/configs", headers=h).json()
            healed = tv in {kk for (tt, kk) in db_rows(cur) if tt == 0}
            chk("D3b ★负向对照：删掉模板一条内建键 → 读取不报错且模板自愈补回",
                r3.get("code") == 0 and healed, "code=%s 模板已补回=%s key=%s" % (r3.get("code"), healed, tv))

        # 收尾：自愈后仍完整
        fin = db_rows(cur)
        tplf = {k for (t, k) in fin if t == 0}
        bad2 = {t: sorted(tplf - {k for (tt, k) in fin if tt == t})
                for t in sorted({t for (t, k) in fin if t != 0})}
        chk("D3c 收尾：全部租户仍完整（自愈把删掉的行补回来了）",
            not {t: v for t, v in bad2.items() if v}, {t: v for t, v in bad2.items() if v})

        # ---------------- D5：诚实 SKIP ----------------
        skip("D5", "「新租户入驻四表齐备」需跑真实入驻流程 + 统一播种器（docs/44 §4.3-③ 未开工）")
    finally:
        cur.close()
        db.close()

    n = len(RES)
    bad = [c for c, ok in RES if not ok]
    print("\n" + "=" * 70)
    print("=== 系统参数漂移验收 %d/%d 通过 ===" % (n - len(bad), n))
    if bad:
        print("失败项：" + ", ".join(bad))
    return 1 if bad else 0


def _login(name):
    d = C.post(f"{API}/auth/login", json={"username": name, "password": PWD,
                                         "tenantName": TENANT}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=API, help="接口前缀，默认 http://127.0.0.1:8080/api/v1")
    a = ap.parse_args()
    API = a.base
    # 多语句执行（V78 内含两条 INSERT，中间有注释）
    DB["client_flag"] = CLIENT.MULTI_STATEMENTS
    sys.exit(main())
