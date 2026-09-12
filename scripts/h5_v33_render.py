# -*- coding: utf-8 -*-
"""V33 用户端 H5 无头渲染校验：空卡片折叠 / 适用场景配置 / AI 解读真实生成。

用系统 Edge（channel="msedge"）免下载浏览器；用 add_init_script 注入 session 免登录。
"""
import json
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5181"
API = "http://127.0.0.1:8080/api/v1"

results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))
    return bool(cond)


def login(u, p):
    c = httpx.Client(timeout=30, trust_env=False)
    r = c.post(f"{API}/auth/login", json={"username": u, "password": p})
    d = r.json()
    return d["data"]["accessToken"], d["data"]


def main():
    token, me = login("zhangsan", "User@123")
    session = json.dumps({"token": token, "user": me.get("user", me)}, ensure_ascii=False)

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        ctx.add_init_script(f"localStorage.setItem('aioa_session', {json.dumps(session)})")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/index.html", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # ---------- 4. 空卡片自动折叠 ----------
        def disp(sel):
            return page.eval_on_selector(sel, "el => getComputedStyle(el).display") if page.query_selector(sel) else "MISSING"

        print("\n--- 4. 工作台空卡片折叠 ---")
        for sel, name in [("#cardKpi", "经营数据卡"), ("#cardToday", "今天要办的事"),
                          ("#secSkills", "快捷技能标题"), ("#skillGrid", "快捷技能格子"),
                          ("#secExperts", "推荐专家标题"), ("#homeExperts", "推荐专家卡")]:
            d = disp(sel)
            print(f"      {name}({sel}) display={d}")

        # 有数据的必须显示
        check("有数据的模块保持可见（#cardKpi 显示）", disp("#cardKpi") != "none",
              f"display={disp('#cardKpi')}")
        # 折叠兜底块：任一模块有数据时应隐藏
        he = disp("#homeEmpty")
        check("兜底空态在有数据时隐藏", he in ("none", "MISSING"), f"display={he}")

        # 构造「全空」：清空 state 后重渲染，验证四块全部折叠且兜底出现
        page.evaluate("""() => {
            state.kpi = {month:null, quarter:null};
            state.skills = []; state.experts = []; state.notifs = []; state.approvals = [];
            renderAll();
        }""")
        page.wait_for_timeout(600)
        collapsed = all(disp(s) == "none" for s in ["#cardKpi", "#cardToday", "#secSkills", "#secExperts"])
        check("全空时四块全部折叠", collapsed,
              " ".join(f"{s}={disp(s)}" for s in ["#cardKpi", "#cardToday", "#secSkills", "#secExperts"]))
        check("全空时兜底说明出现", disp("#homeEmpty") != "none", f"display={disp('#homeEmpty')}")

        # 恢复数据
        page.evaluate("() => location.reload()")
        page.wait_for_timeout(3500)

        # ---------- 6. AI 解读 ----------
        print("\n--- 6. AI 解读按钮 ---")
        if page.query_selector("#kpiInsightBtn"):
            before = page.inner_text("#kpiInsight")
            page.click("#kpiInsightBtn")
            page.wait_for_timeout(1000)
            # 等待按钮文案变化（生成中 → 重新解读），最多 90s
            try:
                page.wait_for_function(
                    "() => ['重新解读','AI 解读'].includes(document.getElementById('kpiInsightBtn').textContent.trim())"
                    " && !document.getElementById('kpiInsightBtn').disabled",
                    timeout=90000)
            except Exception:
                pass
            after = page.inner_text("#kpiInsight")
            btn = page.inner_text("#kpiInsightBtn").strip()
            check("点击后触发真实生成（按钮变为「重新解读」）", btn == "重新解读", f"btn={btn}")
            check("看板展示内容已更新", after != before and len(after) > 30,
                  f"长度 {len(before)}→{len(after)}")
            print(f"      解读摘要：{after[:100]}")
            src = page.inner_text("#kpiSource")
            check("来源标注为 AI 生成", "AI" in src, f"source={src}")
        else:
            check("存在 #kpiInsightBtn", False)

        # ---------- 5. 词元包适用场景 ----------
        print("\n--- 5. 词元包适用场景 ---")
        page.evaluate("() => go('page-buy')")
        page.wait_for_timeout(2500)
        scenes = page.inner_text("#pkgScenes") if page.query_selector("#pkgScenes") else ""
        check("适用场景已渲染", len(scenes.strip()) > 10, f"长度={len(scenes.strip())}")
        for kw in ["个人试用", "团队协作", "企业规模化"]:
            check(f"包含场景「{kw}」", kw in scenes)
        print(f"      场景文本片段：{scenes[:120]}".replace("\n", " / "))

        # ---------- 3. 数字员工自建入口 ----------
        print("\n--- 3. 数字员工自建/自改入口 ---")
        page.evaluate("() => go('page-agent')")
        page.wait_for_timeout(2000)
        act = disp("#agentActions")
        check("创建入口对普通用户可见", act != "none", f"display={act}")
        owned = page.evaluate(
            "() => (state.workers||[]).filter(w=>w.mine===true).length")
        check("本人创建的员工带 mine 标记", owned > 0, f"mine 数量={owned}")
        # 本人创建的卡片应出现「⋯」菜单（可编辑）
        has_menu = page.evaluate("""() => Array.from(document.querySelectorAll('#agentList .agent-card'))
            .some(c => c.querySelector('.agent-menu') && c.textContent.includes('仅我可见'))""")
        check("自建卡片出现「仅我可见」标记且有管理菜单", bool(has_menu))

        check("无 JS 运行时异常", len(errors) == 0, "; ".join(errors[:3]))

        page.screenshot(path="scripts/_v33_home.png", full_page=False)
        b.close()

    n = len(results)
    bad = [r for r in results if not r[1]]
    print(f"\n==== 结果：{n - len(bad)}/{n} 通过 ====")
    for t, _, d in bad:
        print(f"  FAIL {t} {d}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
