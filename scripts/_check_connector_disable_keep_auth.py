#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
收口哨兵：连接器「关闭/开启」不得要求重新认证（2026-10-31 用户口径）

用户口径原话：
    「对话框"+"号关闭连接器后再开启还需要重新认证，你把这一步去掉，
      连接器开启是不需要重新连接。」

改前的事实（根因）：连接器卡上唯一的停用动作是「断开」，它走
`POST /v1/connectors/{code}/disconnect` —— 置 NEED_AUTH 并**清空 credential_json**。
于是再点「连接」必然要重新填授权码 / 重新扫码。用户把那个按钮当"关闭"用，就撞上了重新认证。

本轮改法：新增 DISABLED 状态（`disable` / `enable` 两个端点），
关闭**只翻状态位、一个字节的凭据都不碰**；开启直接回 CONNECTED。
`disconnect` 保留为「解除绑定」（破坏性，清凭据），但收进二次确认，日常用「关闭」。

判据（每条都要有第二源，不能只信被测接口自己说的话 —— 铁律 12）：
  A1 登录 zhangsan（tenant 0 / user 2）成功
  A2 前置：wecom_cli 已是 CONNECTED 且库里 credential_json 非空（否则本哨兵无从验证，明确 SKIP 而非假绿）
  B1 POST /wecom_cli/disable  ⇒ code=0 + status=DISABLED
  B2 **回库**：status=DISABLED 且 credential_json 与关闭前**逐字节相同**（这条是本次改造的核心）
  B3 GET /v1/connectors ⇒ wecom_cli.status=DISABLED（H5 的数据源）
  B4 GET /v1/mcp/servers ⇒ 该内置 MCP 的 connected=false（关闭后确实不注入工具）
  C1 POST /wecom_cli/enable   ⇒ code=0 + status=CONNECTED
  C2 **回库**：status=CONNECTED 且 credential_json 仍与最初**逐字节相同**
     —— 凭据没被重写过 ⇒ 不可能发生过「重新认证」（重新认证必然重写 credential_json）
  C3 GET /v1/connectors ⇒ CONNECTED
  C4 GET /v1/mcp/servers ⇒ connected=true（工具恢复注入）
  D1 负向：对 NEED_AUTH 的连接器（admin 的 qq_mail）调 disable ⇒ 仍 NEED_AUTH（不把"没连过"伪装成"已关闭"）
  D2 幂等：对已 CONNECTED 的连接器再 enable ⇒ 仍 CONNECTED 且凭据不变

用法：
    python scripts/_check_connector_disable_keep_auth.py [--base http://127.0.0.1:8080]
前置：后端在线；zhangsan 的 wecom_cli 处于 CONNECTED（本机库里 id=4 就是）。
    脚本用 try/finally 保证**无论失败在哪一步都恢复成 CONNECTED**，不留残局。
退出码 = 失败项数（SKIP 不算失败，但会打印出来）。
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

MYSQL = "D:/dev/mysql/mysql-8.4.10-winx64/bin/mysql.exe"
CODE = "wecom_cli"        # QR 类连接器：凭据在本机目录，库里是 68 字节密文
OWNER_USERNAME = "zhangsan"
OWNER_PASSWORD = "User@123"

RESULTS = []


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " —— " + detail)


def sql(statement):
    """读标量（第二源）。库不可用返回 None，由调用方判失败，绝不静默通过。"""
    try:
        out = subprocess.run([MYSQL, "-uroot", "-N", "-B", "aios", "-e", statement],
                             capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    return (out.stdout or "").strip() or None


def db_status(user_id=2, code=CODE):
    return sql("SELECT status FROM connector_connection "
               "WHERE user_id=%d AND connector_code='%s' AND deleted_at IS NULL" % (user_id, code))


def db_cred(user_id=2, code=CODE):
    """凭据密文。**逐字节比对**用（不是长度：长度相同但内容不同也必须判失败）。"""
    return sql("SELECT COALESCE(credential_json,'<NULL>') FROM connector_connection "
               "WHERE user_id=%d AND connector_code='%s' AND deleted_at IS NULL" % (user_id, code))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(base, path, method="GET", token=None, body=None, timeout=25):
    url = base.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, "EXC:" + str(e)


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def login(base, username, password):
    st, raw = call(base, "/api/v1/auth/login", "POST",
                   body={"username": username, "password": password})
    d = jload(raw) or {}
    return (d.get("data") or {}).get("accessToken"), st, d


def connector_status(base, token, code):
    st, raw = call(base, "/api/v1/connectors", token=token)
    d = jload(raw) or {}
    for c in ((d.get("data") or []) if isinstance(d.get("data"), list) else []):
        if c.get("code") == code:
            return c.get("status"), st
    return None, st


def mcp_connected(base, token, code):
    """内置 MCP 的 connected 字段（闸门的对外投影：false ⇒ 该连接器工具不注入 AI）。"""
    st, raw = call(base, "/api/v1/mcp/servers", token=token)
    d = jload(raw) or {}
    for s in ((d.get("data") or []) if isinstance(d.get("data"), list) else []):
        if s.get("connectorCode") == code:
            return s.get("connected"), st
    return None, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args()
    base = args.base

    print("=" * 60)
    print("连接器「关闭→开启」保持授权（无需重新认证）  2026-10-31")
    print("=" * 60)

    # ---- A. 前置 ----
    token, st, d = login(base, OWNER_USERNAME, OWNER_PASSWORD)
    rec("A1 登录 %s 成功" % OWNER_USERNAME,
        bool(token),
        "HTTP=%s code=%s token_len=%s" % (st, d.get("code"), len(token or "")))
    if not token:
        print("\n登录失败，后续无从验证。")
        return len([r for r in RESULTS if not r[1]])

    status0 = db_status()
    cred0 = db_cred()
    ok_pre = (status0 == "CONNECTED" and cred0 not in (None, "<NULL>"))
    rec("A2 前置：%s 已连接且库里有凭据" % CODE, ok_pre,
        "db.status=%s credential_json_len=%s" % (status0, len(cred0 or "")))
    if not ok_pre:
        print("\n[SKIP] 前置不成立：需要一条 CONNECTED 且 credential_json 非空的 %s 记录。" % CODE)
        print("       本机可用 zhangsan/User@123（tenant 0 / user 2）先扫码连接后再跑。")
        return len([r for r in RESULTS if not r[1]])

    try:
        # ---- B. 关闭 ----
        st, raw = call(base, "/api/v1/connectors/%s/disable" % CODE, "POST", token=token)
        d = jload(raw) or {}
        rec("B1 关闭（disable）⇒ DISABLED",
            st == 200 and d.get("code") == 0 and (d.get("data") or {}).get("status") == "DISABLED",
            "HTTP=%s code=%s data=%s" % (st, d.get("code"), json.dumps(d.get("data"), ensure_ascii=False)))

        db_st = db_status()
        db_cred_now = db_cred()
        rec("B2 回库：状态已关闭，但**凭据逐字节未变**",
            db_st == "DISABLED" and db_cred_now == cred0,
            "db.status=%s 凭据相同=%s（关闭前 %d 字节 / 关闭后 %d 字节）"
            % (db_st, db_cred_now == cred0, len(cred0 or ""), len(db_cred_now or "")))

        ui_st, st2 = connector_status(base, token, CODE)
        rec("B3 列表接口（H5 数据源）显示 DISABLED", ui_st == "DISABLED",
            "GET /v1/connectors ⇒ HTTP=%s status=%s" % (st2, ui_st))

        conn_off, st3 = mcp_connected(base, token, CODE)
        rec("B4 关闭态下该连接器的 MCP 对 AI 不生效（connected=false）", conn_off is False,
            "GET /v1/mcp/servers ⇒ HTTP=%s connected=%s" % (st3, conn_off))

        # ---- C. 开启 ----
        st, raw = call(base, "/api/v1/connectors/%s/enable" % CODE, "POST", token=token)
        d = jload(raw) or {}
        rec("C1 开启（enable）⇒ CONNECTED（单次 POST，无认证步骤）",
            st == 200 and d.get("code") == 0 and (d.get("data") or {}).get("status") == "CONNECTED",
            "HTTP=%s code=%s data=%s" % (st, d.get("code"), json.dumps(d.get("data"), ensure_ascii=False)))

        db_st2 = db_status()
        db_cred2 = db_cred()
        rec("C2 回库：已恢复连接，凭据仍与最初**逐字节相同**（证明没有重新认证）",
            db_st2 == "CONNECTED" and db_cred2 == cred0,
            "db.status=%s 凭据相同=%s" % (db_st2, db_cred2 == cred0))

        ui_st2, st4 = connector_status(base, token, CODE)
        rec("C3 列表接口恢复 CONNECTED", ui_st2 == "CONNECTED",
            "GET /v1/connectors ⇒ HTTP=%s status=%s" % (st4, ui_st2))

        conn_on, st5 = mcp_connected(base, token, CODE)
        rec("C4 开启后该连接器的 MCP 恢复生效（connected=true）", conn_on is True,
            "GET /v1/mcp/servers ⇒ HTTP=%s connected=%s" % (st5, conn_on))

        # ---- D. 负向与幂等 ----
        # 用 admin 的 qq_mail（NEED_AUTH）：关闭一个"没连过"的连接器，不能变成"已关闭"
        atk, _, ad = login(base, "admin", "Admin@123")
        if atk:
            st, raw = call(base, "/api/v1/connectors/qq_mail/disable", "POST", token=atk)
            d = jload(raw) or {}
            got = (d.get("data") or {}).get("status")
            adm_db = sql("SELECT status FROM connector_connection "
                         "WHERE user_id=1 AND connector_code='qq_mail' AND deleted_at IS NULL")
            rec("D1 负向：对未连接的连接器关闭 ⇒ 仍是 NEED_AUTH（不伪装成已关闭）",
                d.get("code") == 0 and got == "NEED_AUTH",
                "接口 status=%s / 库 status=%s" % (got, adm_db))
        else:
            rec("D1 负向：对未连接的连接器关闭 ⇒ 仍是 NEED_AUTH", False, "admin 登录失败，无法验证")

        st, raw = call(base, "/api/v1/connectors/%s/enable" % CODE, "POST", token=token)
        d = jload(raw) or {}
        got = (d.get("data") or {}).get("status")
        rec("D2 幂等：对已连接的连接器再开启 ⇒ 仍 CONNECTED，凭据不变",
            d.get("code") == 0 and got == "CONNECTED" and db_cred() == cred0,
            "status=%s 凭据相同=%s" % (got, db_cred() == cred0))
    finally:
        # 无论失败在哪一步，都把它恢复成 CONNECTED（绝不给用户留一个关闭态）
        call(base, "/api/v1/connectors/%s/enable" % CODE, "POST", token=token)
        print("\n  [清理] 已确保 %s 恢复为 CONNECTED（当前库状态：%s）" % (CODE, db_status()))

    bad = [r for r in RESULTS if not r[1]]
    print("\n" + "=" * 60)
    print("合计 %d 项，通过 %d 项，失败 %d 项" % (len(RESULTS), len(RESULTS) - len(bad), len(bad)))
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())
