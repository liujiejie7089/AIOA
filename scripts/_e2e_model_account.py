# -*- coding: utf-8 -*-
"""真机 E2E：模型账号共享与计费归属（docs/71）。

## 验的是什么

「A 用 B 注册的账号」这条链路上，**归属有没有真的落到账本上**：
  · 被邀请人（李思远）自己的额度已用尽，却能跑完一轮对话 ⇒ 额度扣的是邀请者（刘敏）；
  · 账本那一行 bearer = 李思远、charge = 刘敏、company_charged = 0；
  · 统计按三个维度都能对上；公司账号标「公司收费」；
  · 越权 / 自邀 / 重复邀请 / 撤销后使用 / 跨租户，全部被拦。

## 为什么起一个本地 mock 供应商

否则「用别人的 Key 打真的 DeepSeek」会 401，一轮都跑不完。mock 只回固定 SSE，
词元数是写死的，便于反查账本。

## 跑法

    agent/.venv/Scripts/python.exe scripts/_e2e_model_account.py

前置：Java :8080 / agent :8000 在线；V105 已迁移（后端启动时自动执行）。
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

BASE = "http://127.0.0.1:8080"
MOCK_PORT = 8123
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"
MOCK_PROMPT = 1234
MOCK_COMPLETION = 567

OWNER = ("fagai_liu", "User@123")      # tenant 2 / user 7  邀请者（DEPPT_LEADER）
GRANTEE = ("fagai_li", "User@123")     # tenant 2 / user 8  被邀请人（个人额度已用尽）
ADMIN = ("admin", "Admin@123")         # 平台管理员（tenant 0）
MEMBER = ("zhangsan", "User@123")   # tenant 0 / user 2  普通成员
ADMIN_ID, MEMBER_ID = 1, 2
OUTSIDER = ("zhangsan", "User@123")    # tenant 0 / user 2  跨租户

OWNER_ID, GRANTEE_ID = 7, 8

fails: list[str] = []
oks = 0


def chk(name: str, ok: bool, detail: str = "") -> bool:
    global oks
    if ok:
        oks += 1
    else:
        fails.append(name)
    print(("[OK  ] " if ok else "[FAIL] ") + name + (f" — {detail}" if detail else ""), flush=True)
    return ok


def _report_body(body: dict) -> tuple[bool, str]:
    """按项目约定解析回执：HTTP 恒 200，业务失败在信封 code 里（铁律 #29/30）。

    返回 (是否成功, 摘要)。判「被拒」一律看 body.code != 0，不要看 HTTP 状态码。
    """
    code = body.get("code")
    return (code in (0, None)), f"code={code} msg={body.get('message')}"


def _rejected(body: dict) -> bool:
    return body.get("code") not in (0, None)


# --------------------------------------------------------------------------- mock 供应商

class _Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunks = [
                {"choices": [{"delta": {"role": "assistant", "content": "这是共享账号"}}]},
                {"choices": [{"delta": {"content": "跑出来的一轮回答。"}}]},
                {"choices": [{"delta": {}}],
                 "usage": {"prompt_tokens": MOCK_PROMPT, "completion_tokens": MOCK_COMPLETION,
                           "total_tokens": MOCK_PROMPT + MOCK_COMPLETION}},
            ]
            for ch in chunks:
                self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "mock 回答"}}],
            "usage": {"prompt_tokens": MOCK_PROMPT, "completion_tokens": MOCK_COMPLETION,
                      "total_tokens": MOCK_PROMPT + MOCK_COMPLETION},
        }).encode())


def start_mock() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), _Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --------------------------------------------------------------------------- 工具

def login(user: str, pwd: str) -> httpx.Client:
    c = httpx.Client(trust_env=False, timeout=60)
    r = c.post(f"{BASE}/api/v1/auth/login", json={"username": user, "password": pwd})
    tok = ((r.json() or {}).get("data") or {}).get("accessToken")
    if not tok:
        raise RuntimeError(f"登录失败 {user}: {r.text[:200]}")
    c.headers["Authorization"] = "Bearer " + tok
    return c


def jget(c: httpx.Client, path: str):
    r = c.get(BASE + path)
    try:
        return r.status_code, (r.json() or {})
    except ValueError:
        return r.status_code, {"raw": r.text[:200]}


def jpost(c: httpx.Client, path: str, body: dict | None = None):
    r = c.post(BASE + path, json=body or {})
    try:
        return r.status_code, (r.json() or {})
    except ValueError:
        return r.status_code, {"raw": r.text[:200]}


def jdel(c: httpx.Client, path: str):
    r = c.delete(BASE + path)
    try:
        return r.status_code, (r.json() or {})
    except ValueError:
        return r.status_code, {"raw": r.text[:200]}


def _frames(resp: httpx.Response) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    ev, buf = "", []
    for line in resp.text.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:"):
            buf.append(line[5:].strip())
        elif line == "":
            if ev:
                out.append((ev, "\n".join(buf)))
            ev, buf = "", []
    if ev:
        out.append((ev, "\n".join(buf)))
    return out


def stream(c: httpx.Client, method: str, path: str, body: dict | None = None):
    with c.stream(method, BASE + path, json=body, timeout=240) as r:
        r.read()
        return _frames(r)


def run_conversation(c: httpx.Client, text: str, credential_id: int | None = None) -> tuple[str, dict]:
    conv = c.post(f"{BASE}/api/v1/conversations", json={"title": "账号 E2E", "source": "aios-client"})
    cid = ((conv.json() or {}).get("data") or {}).get("id")
    body = {"text": text, "context": {}, "kb_on": False}
    if credential_id is not None:
        body["credential_id"] = credential_id
    run = c.post(f"{BASE}/api/v1/conversations/{cid}/runs", json=body)
    rd = (run.json() or {}).get("data") or {}
    rid = rd.get("runId") or rd.get("id")
    frames = stream(c, "GET", f"/api/v1/runs/{rid}/events")
    completed = next((json.loads(d) for t, d in frames if t == "message.completed"), None) or {}
    answer = completed.get("content") or "".join(
        json.loads(d).get("text", "") for t, d in frames if t == "message.delta")
    return rid, {"answer": answer, "types": [t for t, _ in frames], "completed": completed}


def db_one(sql: str, args: tuple = ()):
    import pymysql
    conn = pymysql.connect(host="127.0.0.1", user="root", password="", database="aios", charset="utf8mb4")
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchone()
    finally:
        conn.close()


# --------------------------------------------------------------------------- 用例

def case_owner(c: httpx.Client) -> int:
    """持有人：建账号 → 密钥不回传明文 → 邀请的全部校验。"""
    print("\n=== ① 持有人建账号与邀请校验 ===")
    st, body = jpost(c, "/api/v1/model-credentials", {
        "ownerType": "PERSONAL", "providerKey": "vllm", "name": "e2e-shared-key",
        "apiKey": "sk-e2e-plaintext-should-never-come-back",
        "baseUrl": MOCK_BASE, "modelName": "mock-model", "shareEnabled": True,
    })
    data = (body.get("data") or {})
    if not chk("创建个人账号", st == 200 and bool(data.get("id")), f"{st} {str(body)[:160]}"):
        return 0
    cid = int(data["id"])

    st, body = jget(c, "/api/v1/model-credentials")
    mine = ((body.get("data") or {}).get("mine") or [])
    row = next((r for r in mine if r.get("id") == cid), None)
    chk("列表能查到自己的账号", row is not None, str(st))
    if row:
        chk("回执只有掩码、不出现明文 Key",
            "sk-e2e-plaintext" not in json.dumps(row, ensure_ascii=False) and bool(row.get("keyHint")),
            str(row.get("keyHint")))
        chk("掩码形如 前3后4", row.get("keyHint") == "sk-****back", str(row.get("keyHint")))

    # 邀请自己
    st, body = jpost(c, f"/api/v1/model-credentials/{cid}/shares", {"granteeUsername": OWNER[0]})
    chk("不能邀请自己（code=400）", _rejected(body), f"{st} {str(body)[:140]}")
    # 不存在的同事
    st, body = jpost(c, f"/api/v1/model-credentials/{cid}/shares", {"granteeUsername": "no_such_user"})
    chk("不能邀请不存在的人（code=400）", _rejected(body), f"{st} {str(body)[:140]}")
    # 正常邀请
    st, body = jpost(c, f"/api/v1/model-credentials/{cid}/shares", {"granteeUsername": GRANTEE[0]})
    share = body.get("data") or {}
    chk("邀请同事成功", st == 200 and share.get("status") == "ACTIVE", f"{st} {str(body)[:160]}")
    chk("共享记录里邀请者 = 持有人（承担人）", share.get("ownerUserId") == OWNER_ID,
        str(share.get("ownerUserId")))
    # 重复邀请。判据看**信封 code**，不是 HTTP 状态码（本项目 200 + code=400 约定）
    st, body = jpost(c, f"/api/v1/model-credentials/{cid}/shares", {"granteeUsername": GRANTEE[0]})
    chk("重复邀请被拒（code=400）", _rejected(body), f"{st} {str(body)[:140]}")

    # 未开启共享的账号不能邀请
    st, body = jpost(c, "/api/v1/model-credentials", {
        "ownerType": "PERSONAL", "providerKey": "deepseek", "name": "e2e-no-share",
        "apiKey": "sk-x", "shareEnabled": False,
    })
    no_share_id = int(((body.get("data") or {}).get("id") or 0))
    if no_share_id:
        st, body = jpost(c, f"/api/v1/model-credentials/{no_share_id}/shares",
                         {"granteeUsername": GRANTEE[0]})
        chk("未开启共享的账号不能邀请（code=400）", _rejected(body), f"{st} {str(body)[:140]}")
        jdel(c, f"/api/v1/model-credentials/{no_share_id}")
    return cid


def case_grantee(cid: int) -> str:
    """被邀请人：额度已尽却能跑 ⇒ 扣的是邀请者；账本归属正确。"""
    print("\n=== ② 被邀请人使用与记账归属 ===")
    c = login(*GRANTEE)
    st, body = jget(c, "/api/v1/model-credentials")
    shared = ((body.get("data") or {}).get("shared") or [])
    chk("被邀请人能看到共享账号", any(r.get("id") == cid for r in shared), f"{st} {len(shared)} 个")

    # 他自己的额度必须是用尽的（这是本用例的判别点：扣错人就跑不动）
    q = db_one("SELECT quota_tokens, used_tokens FROM tenant_quota WHERE tenant_id=2 AND user_id=%s",
               (GRANTEE_ID,))
    chk("前置条件：被邀请人个人额度已用尽", q and q["used_tokens"] >= q["quota_tokens"],
        str(dict(q) if q else None))

    used_before = db_one("SELECT used_tokens FROM tenant_quota WHERE tenant_id=2 AND user_id=%s",
                         (OWNER_ID,))
    rid, out = run_conversation(c, "用共享账号回答一句", credential_id=cid)
    chk("用共享账号跑完一轮对话", bool(out["answer"].strip()), str(out["types"]))
    print("  回答:", (out["answer"] or "")[:80])

    row = db_one("SELECT * FROM token_ledger WHERE run_id=%s", (rid,))
    chk("账本有这一行", row is not None, str(rid))
    if row:
        chk("bearer = 实际使用者（被邀请人）", row["bearer_user_id"] == GRANTEE_ID, str(row["bearer_user_id"]))
        chk("charge = 邀请者（token 由邀请者承担）", row["charge_user_id"] == OWNER_ID, str(row["charge_user_id"]))
        chk("company_charged = 0（个人注册账号，公司不收费）", row["company_charged"] == 0, str(row["company_charged"]))
        chk("credential_id 指向本次用的账号", row["credential_id"] == cid, str(row["credential_id"]))
        chk("provider / model 也记了（按供应商出账用）",
            row["provider_key"] == "vllm" and row["model_name"] == "mock-model",
            f"{row['provider_key']}/{row['model_name']}")
        chk("词元数与 mock 返回一致", row["total_tokens"] == MOCK_PROMPT + MOCK_COMPLETION,
            str(row["total_tokens"]))

    used_after = db_one("SELECT used_tokens FROM tenant_quota WHERE tenant_id=2 AND user_id=%s",
                        (OWNER_ID,))
    chk("扣的是邀请者的额度行", used_after and used_before
        and used_after["used_tokens"] == used_before["used_tokens"] + MOCK_PROMPT + MOCK_COMPLETION,
        f"{used_before} → {used_after}")
    g = db_one("SELECT quota_tokens, used_tokens FROM tenant_quota WHERE tenant_id=2 AND user_id=%s",
               (GRANTEE_ID,))
    chk("被邀请人自己的额度一点没扣", g and g["used_tokens"] >= g["quota_tokens"], str(dict(g) if g else None))
    return rid


def case_stats(cid: int, rid: str) -> None:
    print("\n=== ③ 归属统计 ===")
    c = login(*OWNER)
    st, body = jget(c, f"/api/v1/billing/stats?dim=charge&period={_period()}")
    rows = ((body.get("data") or {}).get("rows") or [])
    # 同一 key 可能有多行：历史未标注（ownerType=UNKNOWN）+ 本用例（PERSONAL）。
    # 判据要挑「本用例那一行」——挑第一行会撞上历史数据，那是假失败。
    me = next((r for r in rows if str(r.get("key")) == str(OWNER_ID)
               and r.get("companyCharged") == 0), None)
    chk("按付费人能查到邀请者", me is not None and me.get("tokens", 0) > 0, str(rows[:3]))
    chk("该行标注「个人自付」（非公司收费）", me is not None, str(me))
    split = (body.get("data") or {}).get("split") or {}
    chk("汇总块把「个人自付」单独一档", split.get("personalCharged", 0) > 0, str(split))

    st, body = jget(c, f"/api/v1/billing/stats?dim=credential&period={_period()}")
    rows = ((body.get("data") or {}).get("rows") or [])
    mine = next((r for r in rows if str(r.get("key")) == str(cid)), None)
    chk("按账号能查到这把 Key", mine is not None and mine.get("tokens", 0) > 0, str(rows[:3]))
    chk("账号来源标注 PERSONAL", mine and mine.get("ownerType") == "PERSONAL", str(mine))

    st, body = jget(c, f"/api/v1/billing/stats?dim=bearer&period={_period()}")
    rows = ((body.get("data") or {}).get("rows") or [])
    g = next((r for r in rows if str(r.get("key")) == str(GRANTEE_ID)), None)
    chk("按使用者能追到被邀请人", g is not None and g.get("tokens", 0) > 0, str(rows[:3]))

    st, body = jget(c, "/api/v1/ledger?scope=charge&limit=5")
    rows = (body.get("data") or [])
    chk("作为付费人的账本能看到这笔", any(str(r.get("runId")) == rid for r in rows), str(rows[:2]))


def case_revoke(cid: int) -> None:
    print("\n=== ④ 撤销与越权 ===")
    owner = login(*OWNER)
    st, body = jget(owner, "/api/v1/model-credentials/invites")
    share = next((s for s in ((body.get("data") or [])) if s.get("credentialId") == cid
                  and s.get("granteeUserId") == GRANTEE_ID), None)
    if not chk("能查到共享记录", share is not None, str(st)):
        return
    st, body = jdel(owner, f"/api/v1/model-credentials/shares/{share['id']}")
    chk("撤销共享", st == 200, f"{st} {str(body)[:120]}")

    grantee = login(*GRANTEE)
    st, body = jget(grantee, "/api/v1/model-credentials")
    shared = ((body.get("data") or {}).get("shared") or [])
    chk("撤销后被邀请人看不到该账号", not any(r.get("id") == cid for r in shared), str(len(shared)))

    st, body = jget(grantee, f"/api/v1/model-credentials/{cid}/check")
    chk("撤销后按 id 直接用被拒", _rejected(body), f"{st} {str(body)[:140]}")

    # 邀请者自己仍可用
    st, body = jget(owner, f"/api/v1/model-credentials/{cid}/check")
    chk("持有人自己仍可用", st == 200 and (body.get("data") or {}).get("companyCharged") is False,
        f"{st} {str(body)[:140]}")


def case_company_and_cross_tenant() -> None:
    print("\n=== ⑤ 公司账号与跨租户 ===")
    admin = login(*ADMIN)
    st, body = jpost(admin, "/api/v1/model-credentials", {
        "ownerType": "COMPANY", "providerKey": "vllm", "name": "e2e-company-key",
        "apiKey": "sk-company", "baseUrl": MOCK_BASE, "modelName": "mock-model",
        "shareEnabled": True,
    })
    comp = body.get("data") or {}
    chk("租户管理员可建公司账号", st == 200 and bool(comp.get("id")), f"{st} {str(body)[:160]}")
    comp_id = int(comp.get("id") or 0)

    member = login(*MEMBER)
    st, body = jpost(member, "/api/v1/model-credentials", {
        "ownerType": "COMPANY", "providerKey": "vllm", "name": "x", "apiKey": "sk-x",
    })
    chk("普通成员不能建公司账号（403）", st == 403 and _rejected(body), f"{st} {str(body)[:140]}")

    if comp_id:
        st, body = jget(member, f"/api/v1/model-credentials/{comp_id}/check")
        d = body.get("data") or {}
        chk("公司账号：本租户成员可用", st == 200, f"{st} {str(body)[:140]}")
        chk("公司账号标注 company_charged = true", d.get("companyCharged") is True, str(d))
        chk("公司账号 charge_user_id = 0（公司池）", d.get("chargeUserId") == 0, str(d))

    outsider = login(*GRANTEE)   # 租户 2 的账号，看租户 0 的公司账号 ⇒ 真跨租户
    st, body = jget(outsider, f"/api/v1/model-credentials/{comp_id or 1}/check")
    chk("跨租户用公司账号被拒", _rejected(body), f"{st} {str(body)[:140]}")

    # 公司账号跑一轮：账本 company_charged = 1、charge = 0
    if comp_id:
        rid, out = run_conversation(member, "用公司账号回答一句", credential_id=comp_id)
        chk("公司账号能跑完一轮", bool(out["answer"].strip()), str(out["types"]))
        row = db_one("SELECT * FROM token_ledger WHERE run_id=%s", (rid,))
        if chk("账本有这一行", row is not None, rid) and row:
            chk("company_charged = 1（公司收费）", row["company_charged"] == 1, str(row["company_charged"]))
            chk("charge_user_id = 0（公司池）", row["charge_user_id"] == 0, str(row["charge_user_id"]))
            chk("bearer = 实际使用者", row["bearer_user_id"] == MEMBER_ID, str(row["bearer_user_id"]))
        pool = db_one("SELECT used_tokens FROM tenant_quota WHERE tenant_id=0 AND user_id=0")
        chk("扣的是公司池（user_id=0）", pool and pool["used_tokens"] >= MOCK_PROMPT + MOCK_COMPLETION,
            str(dict(pool) if pool else None))

    # 清理公司账号（留数据会污染后续统计）
    if comp_id:
        jdel(admin, f"/api/v1/model-credentials/{comp_id}")


def _period() -> str:
    import datetime
    return datetime.date.today().strftime("%Y-%m")


def _cleanup() -> None:
    """删掉本脚本建的账号（共享行按设计保留作审计痕迹）。"""
    import pymysql
    conn = pymysql.connect(host="127.0.0.1", user="root", password="", database="aios", charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE model_credential SET deleted_at=NOW(6) WHERE name LIKE 'e2e-%' AND deleted_at IS NULL")
            conn.commit()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留测试账号不清理")
    a = ap.parse_args()

    srv = start_mock()
    try:
        owner = login(*OWNER)
        cid = case_owner(owner)
        if cid:
            rid = case_grantee(cid)
            case_stats(cid, rid)
            case_revoke(cid)
        case_company_and_cross_tenant()
    finally:
        srv.shutdown()
        if not a.keep:
            _cleanup()

    if fails:
        print(f"\nFAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"\nALL PASS  {oks} 项")
    return 0


if __name__ == "__main__":
    sys.exit(main())
