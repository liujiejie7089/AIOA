"""回归探针：管理端左侧菜单的滚动隔离 + 分组结构（只读，不改任何数据）。

守护三条已修行为 / 结构约束：

  1. 高度链闭合：文档（html/body）不出滚动条；侧栏高度 = 视口 - 顶栏。
     历史缺陷：`.layout-menu{height:100%}` + 内侧 flex 行缺 `min-height:0`，
     整棵菜单把 `.layout` 撑到 1074px、文档 1130px → 整页滚动。
  2. 滚动隔离（用户报的现象）：在侧栏上滚轮时，只有侧栏内部在滚，
     右侧页面与文档纹丝不动。历史缺陷：`.layout-aside{overflow:hidden}`
     既裁不出内部滚动，也挡不住溢出撑高父级 → 滚左栏 = 滚整页。
  3. 分组深链：直接进入子菜单内的页面（如 /quotas）时，其所属分组默认展开
     且该项高亮 —— 否则会表现为「菜单里一项都没选中」。

同时核对分组的 RBAC 边界仍生效（租户管理员不应看到平台管理组）。

用法：python scripts/_check_menu_scroll.py
退出码 0 = 全部通过；非 0 = 有条目失败（打印在末尾）。
"""
import json
import sys

import httpx
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8080/api/v1"
SHELL = "http://127.0.0.1:5173"
C = httpx.Client(timeout=60, trust_env=False)

PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def login(name, pwd, tenant=None):
    body = {"username": name, "password": pwd}
    if tenant:
        body["tenantName"] = tenant
    d = C.post(f"{API}/auth/login", json=body).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败 {name}: {d.get('message')}")
    return d["data"]["accessToken"], d["data"]["user"], d["data"].get("refreshToken", "")


# ---------------------------------------------------------------- 页面度量
METRICS = """
() => {
  const aside = document.querySelector('.layout-aside');
  const menu = document.querySelector('.layout-menu');
  const main = document.querySelector('.layout-main');
  const doc = document.scrollingElement;
  const lastVisible = [...document.querySelectorAll('.layout-menu .el-menu-item')]
    .filter((el) => el.getBoundingClientRect().height > 0).pop();
  const lb = lastVisible ? lastVisible.getBoundingClientRect() : null;
  return {
    vh: window.innerHeight,
    doc: { sh: doc.scrollHeight, ch: doc.clientHeight, top: doc.scrollTop },
    aside: aside && { ch: aside.clientHeight, sh: aside.scrollHeight, top: aside.scrollTop,
                      oy: getComputedStyle(aside).overflowY },
    menu: menu && { h: Math.round(menu.getBoundingClientRect().height) },
    main: main && { ch: main.clientHeight, sh: main.scrollHeight, top: main.scrollTop,
                    oy: getComputedStyle(main).overflowY },
    subTitles: [...document.querySelectorAll('.layout-menu .el-sub-menu__title')].map((t) => ({
      text: t.innerText.trim(), opened: !!t.closest('.el-sub-menu').classList.contains('is-opened')
    })),
    activeItems: [...document.querySelectorAll('.layout-menu .el-menu-item.is-active')]
      .map((el) => el.innerText.trim()),
    lastVisible: lastVisible ? { text: lastVisible.innerText.trim(),
                                bottom: Math.round(lb.bottom), visible: lb.bottom <= window.innerHeight } : null
  };
}
"""


def m(page):
    return page.evaluate(METRICS)


def open_page(ctx, path):
    pg = ctx.new_page()
    pg.goto(f"{SHELL}{path}", wait_until="networkidle")
    pg.wait_for_timeout(1000)
    return pg


def wheel_over(page, selector, dy):
    box = page.locator(selector).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 200))
    page.mouse.wheel(0, dy)
    page.wait_for_timeout(400)


def new_ctx(browser, tok, user, ref):
    ctx = browser.new_context(viewport={"width": 1366, "height": 720})
    ctx.add_init_script(
        "localStorage.setItem('aioa.token', %s);"
        "localStorage.setItem('aioa.refreshToken', %s);"
        "localStorage.setItem('aioa.user', %s);"
        % (json.dumps(tok), json.dumps(ref), json.dumps(json.dumps(user, ensure_ascii=False)))
    )
    return ctx


def main():
    tok, user, ref = login("admin", "Admin@123")
    print("admin 登录成功，roles =", user.get("roles"))

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)

        # =============================================== 段 1：高度链 + 滚动隔离
        print("\n=== 段1 高度链与滚动隔离（平台管理员，1366x720）===")
        ctx = new_ctx(b, tok, user, ref)
        pg = open_page(ctx, "/home")
        s0 = m(pg)

        chk("文档不出滚动条（html/body 不滚）",
            s0["doc"]["sh"] <= s0["doc"]["ch"] + 1,
            f"sh={s0['doc']['sh']} ch={s0['doc']['ch']}")
        chk("侧栏高度 = 视口 - 顶栏（56）",
            abs(s0["aside"]["ch"] - (s0["vh"] - 56)) <= 2,
            f"aside.ch={s0['aside']['ch']} vh={s0['vh']}")
        chk("侧栏 overflow-y 已放开（不再是 hidden）",
            s0["aside"]["oy"] == "auto", f"overflowY={s0['aside']['oy']}")
        pg.screenshot(path="logs/_menu_collapsed.png")

        # 展开全部子菜单 → 菜单内容必然高于侧栏，制造「必须滚动」的场景
        titles = pg.locator(".layout-menu .el-sub-menu__title")
        for i in range(titles.count()):
            titles.nth(i).click()
            pg.wait_for_timeout(120)
        pg.wait_for_timeout(700)
        # 展开过程中浏览器会把刚点击的分组滚进视野，侧栏可能已停在中途；
        # 归零后再测，否则「还剩多少可滚」会随点击顺序变化，断言无法稳定。
        pg.evaluate("() => { const a = document.querySelector('.layout-aside'); if (a) a.scrollTop = 0 }")
        pg.wait_for_timeout(300)
        s1 = m(pg)
        print(f"  展开后：菜单高={s1['menu']['h']} 侧栏 ch={s1['aside']['ch']} sh={s1['aside']['sh']}")
        chk("菜单展开后确实超出侧栏（否则本段滚动无从检验）",
            s1["aside"]["sh"] > s1["aside"]["ch"] + 4,
            f"sh={s1['aside']['sh']} ch={s1['aside']['ch']}")
        chk("归零后侧栏确实停在顶部（测量基线）", s1["aside"]["top"] == 0, f"top={s1['aside']['top']}")
        pg.screenshot(path="logs/_menu_expanded.png")

        wheel_over(pg, ".layout-aside", 400)
        s2 = m(pg)
        d_aside = s2["aside"]["top"] - s1["aside"]["top"]
        d_main = s2["main"]["top"] - s1["main"]["top"]
        d_doc = s2["doc"]["top"] - s1["doc"]["top"]
        print(f"  左栏滚 400px ⇒ aside {s1['aside']['top']}→{s2['aside']['top']}"
              f"  main {s1['main']['top']}→{s2['main']['top']}  doc {s1['doc']['top']}→{s2['doc']['top']}")

        chk("滚左栏时侧栏自己在滚（内部滚动生效）", d_aside > 100, f"Δaside={d_aside}")
        chk("滚左栏时右侧页面不动（核心需求）", d_main == 0, f"Δmain={d_main}")
        chk("滚左栏时文档不动", d_doc == 0, f"Δdoc={d_doc}")

        # 反向：滚右栏不应带动侧栏
        before_aside = m(pg)["aside"]["top"]
        wheel_over(pg, ".layout-main", 400)
        after = m(pg)
        chk("滚右栏时侧栏不动", after["aside"]["top"] == before_aside,
            f"aside {before_aside}→{after['aside']['top']}")
        chk("右栏仍是独立滚动容器", after["main"]["oy"] == "auto", f"overflowY={after['main']['oy']}")
        ctx.close()

        # =============================================== 段 2：分组深链自动展开 + 高亮
        print("\n=== 段2 深链分组展开与高亮 ===")
        # (路径, 期望展开的分组标题, 期望高亮的项)
        deep = [
            ("/quotas", "运营管理", "配额管理"),
            ("/results", "成果与项目", "成果沉淀"),
            ("/experts", "智能服务", "专家配置"),
            ("/settings", "安全与治理", "系统参数"),
            ("/tenants", "平台管理", "租户管理"),
            ("/institutions", "租户与机构", "机构管理")
        ]
        for path, group, item in deep:
            ctx = new_ctx(b, tok, user, ref)
            pg = open_page(ctx, path)
            s = m(pg)
            opened = next((t for t in s["subTitles"] if t["text"] == group), None)
            chk(f"深链 {path} → 分组「{group}」默认展开",
                bool(opened and opened["opened"]),
                f"opened={opened}")
            chk(f"深链 {path} → 「{item}」高亮",
                item in s["activeItems"], f"active={s['activeItems']}")
            ctx.close()

        # 旧深链 /admin 归并到合并入口
        ctx = new_ctx(b, tok, user, ref)
        pg = open_page(ctx, "/admin")
        s = m(pg)
        chk("旧深链 /admin → 高亮归并到「系统管理」入口",
            "系统管理" in s["activeItems"] or "组织与员工" in s["activeItems"],
            f"active={s['activeItems']}")
        ctx.close()

        # =============================================== 段 3：分组 RBAC 边界
        print("\n=== 段3 分组 RBAC 边界（租户管理员）===")
        ttok, tuser, tref = login("dsj_admin", "User@123")
        ctx = new_ctx(b, ttok, tuser, tref)
        pg = open_page(ctx, "/home")
        s = m(pg)
        groups = {t["text"] for t in s["subTitles"]}
        print("  租户管理员可见分组:", sorted(groups))
        chk("租户管理员看不到「平台管理」组", "平台管理" not in groups, f"groups={sorted(groups)}")
        chk("租户管理员看得到「智能服务」组", "智能服务" in groups)
        chk("租户管理员看得到「安全与治理」组", "安全与治理" in groups)
        chk("租户管理员看不到「我的应用」以外的越权分组标题",
            "平台管理" not in groups and "租户与机构" in groups)
        ctx.close()

        b.close()

    print(f"\n===== 结果：{len(PASS)} passed, {len(FAIL)} failed =====")
    for f in FAIL:
        print("  FAILED:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
