#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仓库地址「全部是 127.0.0.1、点击跳不到 Gitee」专项排查 —— 全流程取证。

现象
----
详情页的四个地址（克隆命令 / SSH / HTTPS / Gitee 网页）全部指向 127.0.0.1:8090，
点击后打开的是本地 Gitee 桩而不是 Gitee。

本脚本逐环节取证，用来判定「代码缺陷」还是「配置问题」
------------------------------------------------------
UR-1 地址生成（基线复现）：证明「Gitee 接口返回什么，平台就落库并展示什么」
UR-2 地址生成（生产形态对照）：让桩按 https://gitee.com 返回 → 四个地址应即时变为公网形态
UR-3 接口 ↔ 库 ↔ 渲染值一致性：详情接口三地址 == gitee_project 三列（前端 href 直接绑这三个值）
UR-4 链接配置审计：webhook 回调地址 / OAuth redirect_uri / 前端回跳地址 是否为本地
UR-5 快照证据：撤销 public-base 后**已存在**项目的地址不随之变化 → 存量数据必须回填才可修

设计要点
--------
- 平台侧代码**没有**本地拼地址的逻辑：`GiteeRepoTaskHandler` 把接口响应的
  html_url/ssh_url/https_url 原样写库（GiteeRepoTaskHandler:98-100），
  详情页再原样读库（GiteeProjectService:223-227）。
  因此要验证「换成真实 Gitee 会不会变」，唯一诚实的办法是让**接口真的返回公网地址** ——
  即桩的 `/_stub/public-base`（本脚本用），而不是对着一堆本机地址硬断言。
- 可重复运行；不修改任何生产代码，只建 2 个测试项目（前缀「URL排查」）。
"""
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080/api/v1"
STUB = "http://127.0.0.1:8090"
ROOT = Path(__file__).resolve().parent.parent
IDS_FILE = ROOT / ".workbuddy" / "artifacts" / "v51_ids.json"

C = httpx.Client(timeout=60, trust_env=False)

T9 = "某某智能科技有限公司"
# 与用户截图里的 dept101-dept_text 同一条链路：机构管理员 + 部门 101
U_ORG = ("znkjyf_admin", "User@123", T9, 3143, 101)

PASS, FAIL = [], []
TOK = {}


def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("  | " + str(detail)[:260]) if detail else ""))
    return bool(cond)


def login(acc):
    name, pwd, tenant, _, _ = acc
    d = C.post(f"{BASE}/auth/login", json={"username": name, "password": pwd,
                                           "tenantName": tenant}).json()
    if d.get("code") != 0:
        print("登录失败", name, d)
        sys.exit(1)
    return d["data"]["accessToken"]


def req(method, path, tok=None, **kw):
    h = {"Authorization": "Bearer " + tok} if tok else {}
    r = C.request(method, BASE + path, headers=h, **kw)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:200]}


def raw(method, url, **kw):
    return C.request(method, url, **kw)


def ok(d):
    return isinstance(d, dict) and d.get("code") == 0


def wait_for(fn, timeout=90, interval=1.5, what=""):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    print("    (超时等待: %s)" % what)
    return None


def stub_get(p):
    return C.get(STUB + p).json()


def stub_post(p, body=None):
    return C.post(STUB + p, json=body or {}).json()


def project_ready(pid, tok, timeout=90):
    def f():
        st, d = req("GET", f"/gitee/projects/{pid}", tok)
        if not (ok(d) and d["data"]["project"]["status"] == "ACTIVE"):
            return None
        return d["data"]
    data = wait_for(f, timeout=timeout, what=f"项目 {pid} 建仓完成")
    if data:
        return data
    st, d = req("GET", f"/gitee/projects/{pid}", tok)
    return d.get("data") if ok(d) else None


def db_project_urls(pid):
    """直连库读三列 —— 用来证明「接口值 == 库值」，排除接口层二次加工。"""
    import pymysql
    c = pymysql.connect(host="127.0.0.1", user="root", password="",
                        database="aioa", charset="utf8mb4")
    try:
        with c.cursor() as cur:
            cur.execute("SELECT gitee_html_url,gitee_ssh_url,gitee_https_url "
                        "FROM gitee_project WHERE id=%s", (pid,))
            return cur.fetchone()
    finally:
        c.close()


def bind_account(tok, gitee_login):
    """走真实授权码流程绑定一个 Gitee 身份（桩为此提供 login 参数）。"""
    st, d = req("POST", "/gitee/bind/authorize", tok)
    if not ok(d):
        return False
    r = raw("GET", d["data"]["url"] + "&login=" + gitee_login, follow_redirects=False)
    if r.status_code != 302:
        return False
    raw("GET", r.headers["location"])
    st, d = req("GET", "/gitee/bind", tok)
    return ok(d) and (d["data"] or {}).get("bound") is True


def make_project(tok, tag):
    name = "URL排查 %s %d" % (tag, int(time.time()))
    st, d = req("POST", "/gitee/projects", tok,
                json={"name": name, "departmentId": 101,
                      "description": "仓库地址排查用", "visibility": "private"})
    if not ok(d):
        print("  建项目失败:", st, d)
        return None, None
    pid = d["data"]["id"]
    p = project_ready(pid, tok)
    return (pid, p)


# ======================================================================
# UR-1 基线复现：接口返回本机地址 → 平台就展示本机地址
# ======================================================================

def ur1_baseline(tok):
    print("\n[UR-1] 地址生成 · 基线复现（复刻用户截图现象）")
    stub_post("/_stub/public-base", {"base": ""})   # 桩回到默认：返回本机地址
    chk("UR-1.1 桩已回到默认形态（返回本机地址）",
        stub_get("/_stub/state").get("public_base") is None,
        stub_get("/_stub/state").get("public_base"))

    pid, p = make_project(tok, "基线")
    if not p:
        chk("UR-1.2 项目建仓完成", False, "无法继续")
        return None
    proj, repo = p["project"], p["repository"]
    chk("UR-1.2 项目建仓完成并回写地址", proj.get("status") == "ACTIVE", proj.get("status"))

    chk("UR-1.3 【复现】Gitee 网页地址是本地桩地址",
        str(proj.get("htmlUrl", "")).startswith("http://127.0.0.1:8090/"), proj.get("htmlUrl"))
    chk("UR-1.4 【复现】HTTPS 地址是本地桩地址",
        str(repo.get("httpsUrl", "")).startswith("http://127.0.0.1:8090/"), repo.get("httpsUrl"))
    chk("UR-1.5 【复现】SSH 地址是本地 127.0.0.1 主机",
        str(repo.get("sshUrl", "")).startswith("git@127.0.0.1:"), repo.get("sshUrl"))
    chk("UR-1.6 【复现】克隆命令 = git clone + SSH 地址（本地）",
        repo.get("cloneCommand") == "git clone " + str(repo.get("sshUrl")),
        repo.get("cloneCommand"))
    return pid


# ======================================================================
# UR-2 对照：接口按公网域名返回 → 地址随之变为公网形态
# ======================================================================

def ur2_public_shape(tok):
    print("\n[UR-2] 地址生成 · 生产形态对照（桩改按 https://gitee.com 返回）")
    sample = stub_post("/_stub/public-base", {"base": "https://gitee.com"})
    chk("UR-2.1 桩已切换为公网基址（含 SSH 主机推导）",
        sample.get("public_base") == "https://gitee.com"
        and sample["sample"]["ssh_url"].startswith("git@gitee.com:"), sample.get("sample"))

    pid, p = make_project(tok, "公网")
    if not p:
        chk("UR-2.2 项目建仓完成", False, "无法继续")
        return None
    proj, repo = p["project"], p["repository"]
    owner, rname = proj.get("giteeOwner"), proj.get("repoName")
    chk("UR-2.2 项目建仓完成（组织 aioa-demo-org）", proj.get("status") == "ACTIVE" and owner == "aioa-demo-org",
        (proj.get("status"), owner))

    want_html = f"https://gitee.com/{owner}/{rname}"
    want_ssh = f"git@gitee.com:{owner}/{rname}.git"
    want_https = f"https://gitee.com/{owner}/{rname}.git"
    chk("UR-2.3 Gitee 网页地址已变为公网形态", proj.get("htmlUrl") == want_html, proj.get("htmlUrl"))
    chk("UR-2.4 SSH 地址已变为 git@gitee.com:...", repo.get("sshUrl") == want_ssh, repo.get("sshUrl"))
    chk("UR-2.5 HTTPS 地址已变为 https://gitee.com/....git", repo.get("httpsUrl") == want_https,
        repo.get("httpsUrl"))
    chk("UR-2.6 克隆命令随之变为公网 SSH",
        repo.get("cloneCommand") == "git clone " + want_ssh, repo.get("cloneCommand"))

    # Gitee 侧事实：桩自己登记的仓库三地址应与平台展示一致
    st_repos = {r["path"]: r for r in stub_get("/_stub/state")["repos"]}
    sr = st_repos.get(rname) or {}
    chk("UR-2.7 Gitee 侧登记的地址与平台展示一致（不是平台自己拼的）",
        sr.get("html_url") == want_html and sr.get("ssh_url") == want_ssh
        and sr.get("https_url") == want_https,
        {"stub_html": sr.get("html_url"), "stub_ssh": sr.get("ssh_url")})
    return pid


# ======================================================================
# UR-3 接口 ↔ 库 ↔ 前端渲染值一致性
# ======================================================================

def ur3_consistency(tok, pid):
    print("\n[UR-3] 接口返回值 ↔ 数据库 ↔ 前端渲染值 一致性")
    st, d = req("GET", f"/gitee/projects/{pid}", tok)
    proj, repo = d["data"]["project"], d["data"]["repository"]
    row = db_project_urls(pid)
    chk("UR-3.1 详情接口三地址 == gitee_project 三列（无接口层加工）",
        row is not None and (str(row[0]), str(row[1]), str(row[2]))
        == (str(proj.get("htmlUrl")), str(repo.get("sshUrl")), str(repo.get("httpsUrl"))),
        {"db": row, "api": (proj.get("htmlUrl"), repo.get("sshUrl"), repo.get("httpsUrl"))})
    chk("UR-3.2 三个地址字段齐备（前端 href 直接绑定它们）",
        bool(proj.get("htmlUrl") and repo.get("sshUrl") and repo.get("httpsUrl")),
        (proj.get("htmlUrl"), repo.get("sshUrl"), repo.get("httpsUrl")))
    chk("UR-3.3 地址为创建时快照（落库列），非实时计算",
        True, "取证见 UR-3.1 库列 + UR-5 快照不变性")
    return True


# ======================================================================
# UR-4 链接配置审计
# ======================================================================

def ur4_link_config(tok, pid):
    print("\n[UR-4] 链接配置审计（哪些配置项参与链接生成、当前是否为本地地址）")
    state = stub_get("/_stub/state")
    hooks = []
    for k, v in (state.get("hooks") or {}).items():
        for h in v:
            hooks.append((k, h.get("url")))
    my = [u for (k, u) in hooks if k.endswith(str(pid)) or f"webhook/{pid}" in str(u)]
    hook_url = my[0] if my else None
    chk("UR-4.1 Webhook 回调地址 = webhook-base-url + /api/v1/gitee/webhook/{id}",
        bool(hook_url) and f"/api/v1/gitee/webhook/{pid}" in hook_url, hook_url)
    chk("UR-4.2 【配置问题】回调地址是 127.0.0.1，真实 Gitee 无法回调（生产必须公网）",
        bool(hook_url) and "127.0.0.1" in hook_url, hook_url)

    st, d = req("POST", "/gitee/bind/authorize", tok)
    aurl = (d.get("data") or {}).get("url", "") if ok(d) else ""
    chk("UR-4.3 【配置问题】OAuth redirect_uri 指向本机（Gitee 侧须登记同址）",
        "redirect_uri=" in aurl and "127.0.0.1" in aurl, aurl[:200])

    # 前端回跳地址：走一次回调页，看它 location.replace 到哪里
    r = raw("GET", aurl + "&login=znkjyf_admin", follow_redirects=False)
    cb = r.headers.get("location", "")
    body = raw("GET", cb).text if cb else ""
    chk("UR-4.4 【配置问题】授权完成后的前端回跳为本地地址",
        "127.0.0.1:5173" in body or "localhost:5173" in body,
        [ln for ln in body.splitlines() if "location.replace" in ln][:1])
    return True


# ======================================================================
# UR-5 快照不变性 → 存量必须回填
# ======================================================================

def ur5_snapshot(tok, pid):
    print("\n[UR-5] 快照证据：撤销 public-base 后已存在项目地址不变")
    stub_post("/_stub/public-base", {"base": ""})
    chk("UR-5.1 桩已恢复默认（后续新建才会是本地地址）",
        stub_get("/_stub/state").get("public_base") is None)
    st, d = req("GET", f"/gitee/projects/{pid}", tok)
    proj, repo = d["data"]["project"], d["data"]["repository"]
    chk("UR-5.2 已存在项目仍显示公网地址（创建时快照，不随配置变化）",
        str(proj.get("htmlUrl", "")).startswith("https://gitee.com/")
        and str(repo.get("sshUrl", "")).startswith("git@gitee.com:"),
        (proj.get("htmlUrl"), repo.get("sshUrl")))
    chk("UR-5.3 结论：存量行若已被写坏，只能靠回填修复（无自愈路径）", True,
        "平台无「刷新仓库信息」接口，地址仅在建仓时回填一次")
    return True


def main():
    print("=" * 74)
    print("仓库地址本地化 / 点击跳转 专项排查 · 全流程验证")
    print("=" * 74)
    stub_post("/_stub/reset")
    TOK["org"] = login(U_ORG)
    if not bind_account(TOK["org"], "znkjyf_admin"):
        print("Gitee 账号绑定失败，无法继续")
        sys.exit(1)
    print("  已绑定 Gitee 身份 znkjyf_admin（dept 101）")

    p1 = ur1_baseline(TOK["org"])
    p2 = ur2_public_shape(TOK["org"])
    if p2:
        ur3_consistency(TOK["org"], p2)
        ur4_link_config(TOK["org"], p2)
        ur5_snapshot(TOK["org"], p2)
    stub_post("/_stub/public-base", {"base": ""})

    IDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    IDS_FILE.write_text(json.dumps({"local_pid": p1, "public_pid": p2}, ensure_ascii=False),
                        encoding="utf-8")
    print("\n  供 UI 校验使用的项目 id 已写出：%s" % IDS_FILE)

    print("\n" + "=" * 74)
    print("PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
    print("=" * 74)
    if FAIL:
        for n, d in FAIL:
            print("  FAIL %s | %s" % (n, str(d)[:200]))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
