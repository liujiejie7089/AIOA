# -*- coding: utf-8 -*-
"""仓库地址「点击跳转」浏览器取证（无头 Edge）。

为什么必须真跑浏览器
--------------------
「点击后跳不到 Gitee」这条投诉，只有**真的点一下**才能定性：
前端把三地址绑在 `el-link :href` + `target="_blank"` 上，所以点击会新开标签页。
于是本脚本直接**点击**并捕获新标签页的 URL：

  - 本地地址项目 → 新标签页打开 `http://127.0.0.1:8090/...`（= Gitee 桩，不是 Gitee）→ 复现投诉
  - 公网地址项目 → 新标签页打开 `https://gitee.com/...` → 证明「配置对了，跳转就对了」

同时断言三处 href / 克隆命令与接口返回值逐字一致 ——
把「接口值 → 渲染值 → 点击目标」这条链路一次钉死。

前置：后端 :8080、Gitee 桩 :8090、管理端 shell :5173 均已启动；
项目 id 由 `scripts/verify_v51_repo_urls.py` 写出到 `.workbuddy/artifacts/v51_ids.json`。
"""
import json
import os

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
IDS = os.path.join(".workbuddy", "artifacts", "v51_ids.json")
OUT = os.path.join(".workbuddy", "artifacts", "v51-ui")

C = httpx.Client(timeout=60, trust_env=False)
results = []


def chk(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(("  PASS " if cond else "  FAIL ") + tag + (f"  | {detail}" if detail else ""))


def login(name, pwd="User@123"):
    d = C.post(API + "/auth/login", json={"username": name, "password": pwd}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"].get("user") or {}


def api_project(tok, pid):
    d = C.get(API + f"/gitee/projects/{pid}",
              headers={"Authorization": "Bearer " + tok}).json()
    if d.get("code") != 0:
        raise SystemExit(f"读项目 {pid} 失败: {d.get('message')}")
    return d["data"]["project"], d["data"]["repository"]


def collect_links(page):
    """收集页面上三个仓库地址链接的 (文案, href, target)。"""
    out = []
    for a in page.locator("a").all():
        try:
            txt = (a.inner_text() or "").strip()
            href = a.get_attribute("href") or ""
        except Exception:
            continue
        if txt.startswith(("SSH ", "HTTPS ", "Gitee 网页 ")):
            out.append((txt.split(" ")[0], href, a.get_attribute("target") or ""))
    return out


def clone_input_value(page):
    for inp in page.locator("input").all():
        try:
            v = inp.input_value()
        except Exception:
            continue
        if v and v.startswith("git clone "):
            return v
    return ""


def check_one(ctx, label, tok, pid, expect_gitee):
    print(f"\n[{label}] 项目 {pid}")
    proj, repo = api_project(tok, pid)
    page = ctx.new_page()
    errs, bad = [], []
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 500 else None)
    page.goto(f"{SHELL}/gitee/projects/{pid}", wait_until="networkidle")
    page.wait_for_timeout(3000)

    links = dict((k, (h, t)) for k, h, t in collect_links(page))
    chk(f"{label} · 三个地址链接均已渲染", len(links) == 3, list(links.keys()))

    chk(f"{label} · SSH href == 接口 sshUrl",
        links.get("SSH", ("", ""))[0] == repo.get("sshUrl"),
        (links.get("SSH", ("", ""))[0], repo.get("sshUrl")))
    chk(f"{label} · HTTPS href == 接口 httpsUrl",
        links.get("HTTPS", ("", ""))[0] == repo.get("httpsUrl"),
        (links.get("HTTPS", ("", ""))[0], repo.get("httpsUrl")))
    chk(f"{label} · Gitee 网页 href == 接口 htmlUrl",
        links.get("Gitee", ("", ""))[0] == proj.get("htmlUrl"),
        (links.get("Gitee", ("", ""))[0], proj.get("htmlUrl")))
    chk(f"{label} · 三链接均为 target=_blank（新标签页打开）",
        all(v[1] == "_blank" for v in links.values()),
        [v[1] for v in links.values()])
    chk(f"{label} · 克隆命令输入框 == 接口 cloneCommand",
        clone_input_value(page) == repo.get("cloneCommand"),
        (clone_input_value(page), repo.get("cloneCommand")))

    # ---- 真点一下「Gitee 网页」，捕获新标签页 URL ----
    target_url = ""
    try:
        link = page.get_by_text("Gitee 网页", exact=False).first
        link.scroll_into_view_if_needed()
        with ctx.expect_page(timeout=10000) as newp:
            link.click()
        np = newp.value
        np.wait_for_timeout(2500)
        target_url = np.url
        np.close()
    except Exception as e:
        target_url = f"<点击失败 {type(e).__name__}>"

    if expect_gitee:
        chk(f"{label} · 【点击跳转】新标签页打开的是 Gitee 官网",
            target_url.startswith("https://gitee.com/"), target_url)
    else:
        chk(f"{label} · 【复现投诉】新标签页打开的是本地桩而非 Gitee",
            target_url.startswith("http://127.0.0.1:8090/"), target_url)

    chk(f"{label} · 无控制台错误", not errs, errs[:2])
    chk(f"{label} · 无 5xx 响应", not bad, bad[:2])

    os.makedirs(OUT, exist_ok=True)
    shot = os.path.join(OUT, f"{label}.png")
    page.screenshot(path=shot, full_page=True)
    print(f"    截图 {shot}")
    page.close()


def main():
    if not os.path.exists(IDS):
        raise SystemExit(f"缺少 {IDS}，请先运行 scripts/verify_v51_repo_urls.py")
    ids = json.loads(open(IDS, encoding="utf-8").read())
    tok, user = login("znkjyf_admin")
    print(f"  操作人 {user.get('username')} roles={user.get('roles')}")

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel="msedge", headless=True)
        ctx = br.new_context(viewport={"width": 1440, "height": 1100})
        ctx.add_init_script(
            "localStorage.setItem('aioa.token', %s); localStorage.setItem('aioa.user', %s);"
            % (json.dumps(tok), json.dumps(json.dumps(user, ensure_ascii=False)))
        )
        check_one(ctx, "本地地址项目", tok, ids["local_pid"], expect_gitee=False)
        check_one(ctx, "公网地址项目", tok, ids["public_pid"], expect_gitee=True)
        br.close()

    print("\n" + "=" * 74)
    print("PASS=%d  FAIL=%d" % (sum(1 for r in results if r[1]), sum(1 for r in results if not r[1])))
    print("=" * 74)
    return 0 if all(r[1] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
