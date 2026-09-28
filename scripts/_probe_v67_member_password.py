# -*- coding: utf-8 -*-
"""验证「员工开户口令可知性」全链路（docs/37 · V67 批次 C·补（口令可知性））。

背景：用户反馈「新增的员工无法登录用户端」。实测新账号**能**登录（统一演示口令 User@123），
真正的缺陷是**凭据不可知**：管理端新增员工表单没有口令输入、成功也不回显口令，
服务端只存 BCrypt 哈希、事后无法回读 ⇒ 操作员拿到"建好了但进不去"的账号，且没有补救出口。

本探针逐条钉死修好后的口径：

    P1  机构管理员可登录（前置）
    P2  新增员工时可指定初始口令，回执必须回吐同一个值
    P3  携带**指定**口令登录用户端成功，用户端核心接口全部可用
    P4  不填口令 ⇒ 回执回吐统一演示口令，且用它可登录
    P5  负向：错误口令必须失败（证明 P3/P4 不是"谁都能登"）
    P6  重置口令端点：重置后新口令可用、旧口令立即失效，回执回吐新口令
    P7  负向：账号**此前已存在**时不得回吐 initialPassword（那一刻口令并未被改动 ⇒ 回吐即假话）
    P8  批量导入：新建账号时必须回吐统一初始口令与新建个数，且该口令可登录
    P9  收尾：删自建员工 + 软删自建账号（不留残留污染「给员工绑定账号」的候选池）

用法：
    python scripts/_probe_v67_member_password.py
"""
import sys
import time

import httpx
import pymysql

BASE = "http://localhost:8080/api/v1"
C = httpx.Client(base_url=BASE, timeout=20, trust_env=False)
ok = 0
fail = []
created_usernames = []
created_member_ids = []


def chk(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print("  [PASS] %s %s" % (name, detail))
    else:
        fail.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def login(u, p):
    r = C.post("/auth/login", json={"username": u, "password": p})
    try:
        b = r.json()
    except Exception:
        b = {"raw": r.text[:200]}
    return r.status_code, b


def H(tok):
    return {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}


def token_of(b):
    d = b.get("data") or {}
    return d.get("accessToken") or d.get("token")


def soft_delete_accounts(usernames):
    """软删自建账号：行保留（排查证据不丢），但退出 `selectTenantAccounts` 的候选池。"""
    usernames = [u for u in usernames if u]
    if not usernames:
        return 0
    c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                        database="aioa", charset="utf8mb4")
    try:
        with c.cursor() as cur:
            ph = ",".join(["%s"] * len(usernames))
            n = cur.execute("UPDATE sys_user SET deleted_at = NOW(6) "
                            "WHERE deleted_at IS NULL AND username IN (%s)" % ph, tuple(usernames))
        c.commit()
        return n
    finally:
        c.close()


# 本探针（含历史版本与真机手测）用过的账号前缀 —— 收尾与开跑前都要清，保证可重复运行
PROBE_PREFIXES = ("zz_pw_", "zz_v67a_", "zz_v67b_", "zz_probe_", "zz_imp_dbg_", "zz_ui_")


def _purge(where_sql, params):
    """软删「按给定条件命中的账号」对应的成员行、账号绑定行、账号行。返回三元组行数。"""
    c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                        database="aioa", charset="utf8mb4")
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id FROM sys_user WHERE %s" % where_sql, params)
            uids = [r[0] for r in cur.fetchall()]
            n_mem = 0
            if uids:
                ph = ",".join(["%s"] * len(uids))
                cur.execute("SELECT id FROM org_member WHERE deleted_at IS NULL AND user_id IN (%s)" % ph,
                            tuple(uids))
                mids = [r[0] for r in cur.fetchall()]
                if mids:
                    mph = ",".join(["%s"] * len(mids))
                    n_mem = cur.execute("UPDATE org_member SET deleted_at = NOW(6) "
                                        "WHERE deleted_at IS NULL AND id IN (%s)" % mph, tuple(mids))
                    cur.execute("UPDATE org_member_account SET deleted_at = NOW(6) "
                                "WHERE deleted_at IS NULL AND member_id IN (%s)" % mph, tuple(mids))
                n_acc = cur.execute("UPDATE sys_user SET deleted_at = NOW(6) "
                                    "WHERE deleted_at IS NULL AND id IN (%s)" % ph, tuple(uids))
            else:
                n_acc = 0
        c.commit()
        return n_mem, n_acc, len(uids)
    finally:
        c.close()


def purge_by_prefixes(prefixes=PROBE_PREFIXES):
    """清掉本探针**历史残留**（按账号前缀）。"""
    tot = [0, 0, 0]
    for pfx in prefixes:
        a, b, c = _purge("username LIKE %s", (pfx + "%",))
        tot = [tot[0] + a, tot[1] + b, tot[2] + c]
    return tot


def purge_by_usernames(usernames):
    """清掉**本轮**自建账号对应的成员/绑定/账号行（精确匹配，收尾用）。

    只按 id 删成员是不够的：批量导入接口不回吐成员 id，靠接口 keyword 回查并不可靠
    （实测 keyword 不匹配账号名 ⇒ 导入出来的成员留在库里，下一轮 P8 会被它顶掉）。
    直连库按账号名反查最确定。
    """
    usernames = [u for u in usernames if u]
    if not usernames:
        return 0, 0, 0
    ph = ",".join(["%s"] * len(usernames))
    return _purge("username IN (%s)" % ph, tuple(usernames))


def main():
    st, b = login("fagai_admin", "User@123")
    tok = token_of(b)
    chk("P1 机构管理员可登录（前置）", b.get("code") == 0 and bool(tok), "http=%s" % st)
    if not tok:
        print("前置失败，终止：", b)
        return 1
    h = H(tok)

    n_mem, n_acc, _ = purge_by_prefixes()
    print("   （开跑前清理本探针历史残留：成员 %d 行 / 账号 %d 行）" % (n_mem, n_acc))

    sfx = str(int(time.time()))[-6:]
    u_new, u_def, u_rst, u_dup, u_imp = (
        "zz_pw_a_" + sfx, "zz_pw_b_" + sfx, "zz_pw_c_" + sfx,
        "zz_pw_d_" + sfx, "zz_pw_e_" + sfx)
    created_usernames.extend([u_new, u_def, u_rst, u_dup, u_imp])
    new_pw = "Qa9#pass_" + sfx

    def add_member(username, name, password=None, mobile=None):
        body = {"name": name, "username": username, "mobile": mobile or ("1350000" + sfx[-5:])}
        if password is not None:
            body["password"] = password
        r = C.post("/org/members", headers=h, json=body)
        return r.status_code, r.json()

    # ---- P2 指定口令开户 + 回执同源
    st, d = add_member(u_new, "口令探针A", new_pw)
    created_member_ids.append((d.get("data") or {}).get("id"))
    chk("P2 指定初始口令开户成功", d.get("code") == 0,
        "http=%s code=%s msg=%s" % (st, d.get("code"), d.get("message") or ""))
    chk("P2b 回执回吐的口令 == 指定口令", (d.get("data") or {}).get("initialPassword") == new_pw,
        "回执=%r 期望=%r" % ((d.get("data") or {}).get("initialPassword"), new_pw))

    # ---- P3 指定口令登录 + 用户端接口
    st, b = login(u_new, new_pw)
    t1 = token_of(b)
    chk("P3 指定口令可登录用户端", b.get("code") == 0 and bool(t1),
        "%s/%s -> http=%s code=%s" % (u_new, new_pw, st, b.get("code")))
    if t1:
        for path in ("/stats/me", "/experts", "/kb/documents", "/stats/org"):
            rr = C.get(path, headers=H(t1))
            jj = rr.json()
            chk("P3.%s %s 可用" % (path.strip("/").replace("/", "_"), path),
                rr.status_code == 200 and jj.get("code") == 0,
                "http=%s code=%s" % (rr.status_code, jj.get("code")))

    # ---- P4 留空 → 统一演示口令，且回执说明了它
    st, d = add_member(u_def, "口令探针B")
    created_member_ids.append((d.get("data") or {}).get("id"))
    pw_def = (d.get("data") or {}).get("initialPassword")
    chk("P4 未填口令时回吐统一演示口令 User@123", pw_def == "User@123", "回执=%r" % pw_def)
    st, b = login(u_def, pw_def or "User@123")
    chk("P4b 该口令可登录", b.get("code") == 0 and bool(token_of(b)), "code=%s" % b.get("code"))

    # ---- P5 负向
    st, b = login(u_new, "wrong-" + new_pw)
    chk("P5 负向：错误口令必须失败", b.get("code") != 0, "code=%s" % b.get("code"))

    # ---- P6 重置口令
    st, d = add_member(u_rst, "口令探针C")
    mid = (d.get("data") or {}).get("id")
    created_member_ids.append(mid)
    pw_old = (d.get("data") or {}).get("initialPassword")
    rst_pw = "New9#pw_" + sfx
    rr = C.post("/org/members/%s/password" % mid, headers=h, json={"password": rst_pw})
    jj = rr.json()
    chk("P6 重置口令成功且回吐新口令",
        jj.get("code") == 0 and (jj.get("data") or {}).get("initialPassword") == rst_pw,
        "http=%s code=%s 回执=%r" % (rr.status_code, jj.get("code"),
                                     (jj.get("data") or {}).get("initialPassword")))
    st, b = login(u_rst, rst_pw)
    chk("P6b 重置后新口令可登录", b.get("code") == 0 and bool(token_of(b)), "code=%s" % b.get("code"))
    st, b = login(u_rst, pw_old or "User@123")
    chk("P6c 重置后旧口令立即失效", b.get("code") != 0, "旧口令 code=%s" % b.get("code"))

    # ---- P7 负向：账号已存在时不得回吐 initialPassword
    st, d1 = add_member(u_dup, "口令探针D")
    mid_d = (d1.get("data") or {}).get("id")
    pw_first = (d1.get("data") or {}).get("initialPassword")
    C.delete("/org/members/%s" % mid_d, headers=h)   # 移除员工（账号仍在）
    st, d2 = add_member(u_dup, "口令探针D2")
    created_member_ids.append((d2.get("data") or {}).get("id"))
    chk("P7 负向：账号已存在时不得回吐 initialPassword",
        "initialPassword" not in (d2.get("data") or {}) if d2.get("code") == 0 else False,
        "code=%s 回执键=%s" % (d2.get("code"), sorted((d2.get("data") or {}).keys())))
    st, b = login(u_dup, pw_first or "User@123")
    chk("P7b 已存在账号的口令未被改动（原口令仍可登录）",
        b.get("code") == 0 and bool(token_of(b)), "code=%s" % b.get("code"))

    # ---- P8 批量导入
    # 行内姓名带 sfx：导入是按「姓名 + 工号」判重的，用固定姓名会让上一轮的残留成员
    # 把本轮的行顶掉（实测踩到：P8 报 success=0 且看不出原因）。
    rr = C.post("/org/members/import", headers=h,
                json={"rows": [{"name": "导入探针E-" + sfx, "username": u_imp}]})
    jj = rr.json()
    dd = jj.get("data") or {}
    chk("P8 导入回执带新建账号数与统一初始口令",
        jj.get("code") == 0 and (dd.get("newAccounts") or 0) >= 1
        and dd.get("initialPassword") == "User@123",
        "http=%s code=%s success=%s failed=%s newAccounts=%s initialPassword=%r"
        % (rr.status_code, jj.get("code"), dd.get("success"), dd.get("failed"),
           dd.get("newAccounts"), dd.get("initialPassword")))
    st, b = login(u_imp, dd.get("initialPassword") or "User@123")
    chk("P8b 导入新建的账号可用统一初始口令登录",
        b.get("code") == 0 and bool(token_of(b)), "code=%s" % b.get("code"))
    # 导入接口不回吐成员 id ⇒ 按账号回查，供收尾删除（否则残留成员会污染下一轮 P8）
    lj = C.get("/org/members", headers=h, params={"keyword": u_imp}).json()
    for row in ((lj.get("data") or {}).get("items") or []):
        created_member_ids.append(row.get("id"))

    # ---- P9 收尾回基线
    for mid in created_member_ids:
        if mid:
            C.delete("/org/members/%s" % mid, headers=h)
    m2, a2, _ = purge_by_usernames(created_usernames)
    n = soft_delete_accounts(created_usernames)
    left = 0
    left_mem = 0
    try:
        c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="",
                            database="aioa", charset="utf8mb4")
        with c.cursor() as cur:
            ph = ",".join(["%s"] * len(created_usernames))
            cur.execute("SELECT COUNT(*) FROM sys_user WHERE deleted_at IS NULL AND username IN (%s)"
                        % ph, tuple(created_usernames))
            left = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM org_member WHERE deleted_at IS NULL AND user_id IN "
                        "(SELECT id FROM sys_user WHERE username IN (%s))" % ph, tuple(created_usernames))
            left_mem = cur.fetchone()[0]
        c.close()
    except Exception as e:  # noqa: BLE001
        print("   (收尾校验跳过：%s)" % e)
    chk("P9 收尾：自建账号与成员均已退出（无残留）", left == 0 and left_mem == 0,
        "软删账号 %d 行 / 成员 %d 行；仍存活账号 %d 行、成员 %d 行" % (n + a2, m2, left, left_mem))

    print("\n合计通过 %d，失败 %d %s" % (ok, len(fail), fail or ""))
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
