#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V48 Gitee 联动 —— 冒烟测试（不依赖真实 Gitee）。

覆盖：
  1. 公开端点可达性与安全边界（webhook 无密钥 / 未知项目一律 accepted=false，且 HTTP 200）
  2. 授权绑定：未配置 OAuth 应用时给出**可执行**报错，而不是 401 或 500
  3. 项目 / 部门 / 任务统计等读接口的权限与可见性
  4. 跨租户访问一律 404（不泄露存在性）
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "http://127.0.0.1:8080/api/v1"
C = httpx.Client(timeout=60, trust_env=False)

T2 = "某某市某某区大数据管理局"
T9 = "某某智能科技有限公司"

U_T2TEN = ("dsj_admin", "User@123", T2)      # 租户 2 管理员
U_T9ORG = ("znkjyf_admin", "User@123", T9)   # 租户 9 机构管理员
U_PLAT = ("admin", "Admin@123", None)        # 平台管理员

PASS, FAIL = [], []


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  | " + str(detail)[:220]) if detail else ""))
    return bool(cond)


def login(acc):
    name, pwd, tenant = acc
    body = {"username": name, "password": pwd}
    if tenant:
        body["tenantName"] = tenant
    d = C.post(f"{BASE}/auth/login", json=body).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d}")
    return d["data"]["accessToken"]


def req(method, path, tok=None, **kw):
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    r = C.request(method, BASE + path, headers=headers, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:200]}


def main():
    print("== 1. 公开端点：Webhook 安全边界 ==")
    st, d = req("POST", "/gitee/webhook/999999", json={"ref": "refs/heads/master"})
    chk("webhook 未知项目返回 HTTP 200（避免 Gitee 无限重投）", st == 200, st)
    chk("webhook 未知项目 accepted=false", d.get("accepted") is False, d)
    chk("webhook 未知项目给出原因 PROJECT_NOT_FOUND",
        d.get("reason") == "PROJECT_NOT_FOUND", d.get("reason"))

    st, d = req("GET", "/gitee/bind/callback")
    chk("OAuth 回调缺 code/state 返回可读 HTML 而非 500",
        st == 200 and "<html" in str(d.get("_raw", "")).lower(), st)
    st, d = req("POST", "/gitee/bind/callback")
    chk("回调只接受 GET（POST → 405）", st == 405, st)

    print("\n== 2. 授权绑定：配置缺失时的报错质量 ==")
    tok_t2 = login(U_T2TEN)
    # arrange：本段断言的是**未绑定态**的渲染。dsj_admin 是共享演示账号，
    # e2e_v50_tenant_org.py（T3.2c）会把它绑定上且**不清理**，于是本段结果取决于套件执行顺序
    # ——曾因此在整轮矩阵后跑 SMOKE 时出现两条「失败」，而实际是无绑定态前置条件被别的套件改掉了。
    # 这里先自行解绑，把前置条件摆正；**断言保持原样**（不靠改断言转绿，也不依赖外部清理）。
    req("DELETE", "/gitee/bind", tok_t2)
    st, d = req("GET", "/gitee/bind", tok_t2)
    chk("查询绑定状态 200", st == 200 and d.get("code") == 0, d)
    chk("未绑定返回 bound=false", d.get("data", {}).get("bound") is False, d.get("data"))
    _keys = list((d.get("data") or {}).keys())
    _vals = [v for v in (d.get("data") or {}).values() if isinstance(v, str)]
    chk("绑定视图不泄露令牌（无 accessToken/refreshToken 键，且无密文值）",
        "accessToken" not in _keys and "refreshToken" not in _keys
        and not any(v.startswith("enc:") for v in _vals), _keys)
    # 注：旧断言把**所有含 "token" 的键名**一律判为违规，于是把 hasRefreshToken（布尔）也算进去了；
    # 但 hasRefreshToken 是既有的非密字段，且 scripts/e2e_v48_gitee.py 的 FR-1.12 明确要求它存在。
    # 该断言原先只有在账号恰好未绑定（视图仅 2 个键）时才通过，属**假阳性**。
    # 现改为按「是否泄露令牌/密文」判定，口径与 e2e_v48_gitee 的 FR-1.13 对齐，安全性不降。

    st, d = req("POST", "/gitee/bind/authorize", tok_t2)
    biz = d.get("code")
    if biz != 0:
        # 未配置 OAuth 应用（本机没设 AIOA_GITEE_CLIENT_ID）→ 必须给出**可执行**的报错
        chk("未配置 OAuth 应用时返回业务错误（非 500/401）", st == 200, (st, d))
        chk("错误信息直接指出缺哪个配置",
            "client-id" in str(d.get("message", "")) or "client_secret" in str(d.get("message", "")),
            d.get("message"))
    else:
        # 已配置（端到端回归的常规接线，见 scripts/gitee-e2e-env.sh）→ 守卫**按设计不触发**。
        #
        # 原断言把「未配置」当作前提，但它与所有 Gitee 套件都需要的
        # AIOA_GITEE_CLIENT_ID 互斥：带接线跑就必然假红，看着像回归、实为断言与运行前提冲突。
        # 这里改为「守卫不该触发时，就校验它产出的东西是否合格」——两条分支都在验同一个契约
        # （这个端点要么给可执行报错、要么给可用地址），既不丢覆盖也不产生假红。
        url = str((d.get("data") or {}).get("url") or "")
        chk("已配置 OAuth 应用时返回可用授权地址（守卫按设计不触发）",
            st == 200 and url.startswith("http") and "client_id=" in url
            and "redirect_uri=" in url and "response_type=code" in url and "state=" in url,
            url[:140])
        chk("授权地址的 client_id 与 state 均非空",
            "client_id=&" not in url and "state=&" not in url and "client_id=" in url,
            url[:140])

    st, d = req("POST", "/gitee/bind/authorize")
    chk("未登录调用绑定授权被拦截（401）", st in (401, 403), st)

    print("\n== 3. 读接口权限与数据形状 ==")
    for label, tok in (("租户管理员", tok_t2), ("机构管理员", login(U_T9ORG))):
        st, d = req("GET", "/gitee/config", tok)
        chk(f"[{label}] GET /gitee/config 200", st == 200 and d.get("code") == 0, d)
        data = d.get("data") or {}
        chk(f"[{label}] config 暴露 enabled/orgConfigured 布尔量",
            isinstance(data.get("enabled"), bool) and isinstance(data.get("orgConfigured"), bool), data)
        chk(f"[{label}] config 含角色选项（READ/WRITE/ADMIN）",
            {o.get("value") for o in (data.get("roleOptions") or [])} == {"READ", "WRITE", "ADMIN"},
            data.get("roleOptions"))

        st, d = req("GET", "/gitee/departments", tok)
        chk(f"[{label}] GET /gitee/departments 200 且返回数组",
            st == 200 and d.get("code") == 0 and isinstance(d.get("data"), list), (st, str(d)[:120]))

        st, d = req("GET", "/gitee/projects", tok)
        chk(f"[{label}] GET /gitee/projects 200 且含 items/total/canCreate",
            st == 200 and d.get("code") == 0
            and isinstance(d["data"].get("items"), list)
            and isinstance(d["data"].get("total"), int)
            and isinstance(d["data"].get("canCreate"), bool), (st, str(d)[:200]))
        chk(f"[{label}] 项目列表 total == len(items)（无分页，不做固定条数断言）",
            d.get("data", {}).get("total") == len(d.get("data", {}).get("items") or []),
            d.get("data", {}).get("total"))

    print("\n== 4. 越界访问一律 404 ==")
    tok9 = login(U_T9ORG)
    st, d = req("GET", "/gitee/projects/999999", tok9)
    chk("不存在的项目 → 404", st == 404, (st, d))

    # 租户 9 的机构管理员去读一个租户 2 才可能有的项目：先拿租户 2 的项目 id 列表
    st, d2 = req("GET", "/gitee/projects", tok_t2)
    ids2 = [x["id"] for x in (d2.get("data", {}).get("items") or [])]
    if ids2:
        st, d = req("GET", f"/gitee/projects/{ids2[0]}", tok9)
        chk("跨租户读项目 → 404（不泄露存在性）", st == 404, (st, d))
    else:
        chk("跨租户读项目 → 无数据可测（跳过，用不存在 id 等价验证）",
            req("GET", "/gitee/projects/999999", tok9)[0] == 404)

    print("\n== 5. 运维接口（仅租户管理员） ==")
    st, d = req("GET", "/gitee/tasks/stats", tok_t2)
    chk("租户管理员可读任务统计", st == 200 and d.get("code") == 0, (st, str(d)[:200]))
    chk("任务统计按状态给出计数（键与 gitee_task.status 同口径）",
        all(k in (d.get("data") or {}) for k in ("PENDING", "RUNNING", "DONE", "FAILED")),
        d.get("data"))

    st, d = req("GET", "/gitee/tasks/stats", tok9)
    chk("机构管理员读任务统计 → 403", st == 403, (st, d))

    st, d = req("POST", "/gitee/calibrate", tok_t2)
    chk("租户管理员可触发校准", st == 200 and d.get("code") == 0, (st, str(d)[:160]))
    chk("校准返回入队条数",
        isinstance((d.get("data") or {}).get("enqueued"), int), d.get("data"))

    st, d = req("POST", "/gitee/calibrate", tok9)
    chk("机构管理员触发校准 → 403", st == 403, (st, d))

    print("\n== 6. 平台管理员只读视角 ==")
    tokp = login(U_PLAT)
    st, d = req("POST", "/gitee/webhook/999999", json={})
    chk("平台管理员走公开 webhook 仍被拒（不因特权放行）",
        d.get("accepted") is False, d)

    print("\n" + "=" * 62)
    print(f"PASS={len(PASS)}  FAIL={len(FAIL)}")
    if FAIL:
        print("失败项：")
        for n, dt in FAIL:
            print("  -", n, "|", str(dt)[:200])
        return 1
    print("V48 Gitee 冒烟：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
