# -*- coding: utf-8 -*-
"""H5 查询结果图表渲染验证（断言 + 截图）。

覆盖用户需求：
  1. 统计表（分类+数值）自动渲染成 SVG 图表，标题/分类轴/数值列/图例自动映射
  2. 查询结果变化时图表同步更新（同一气泡重渲染）
  3. 非绘图表格保持原有表格展示
  4. 无数据 / 数据格式异常安全降级
  5. 显式「柱状图」意图不被正文「占比」描述带偏成饼图

跑法：agent/.venv/Scripts/python.exe scripts/_verify_answer_chart_render.py
产物：docs/screenshots/answer-chart-2026-11-21/
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import json
import os

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots", "answer-chart-2026-11-21")
BASE = "http://127.0.0.1:5181"
API = "http://127.0.0.1:8080/api/v1"

results = []
def chk(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS" if cond else "FAIL") + " | " + name + " | " + str(detail)[:160])

# 截图里的真实场景：成都市非遗工坊电商平台销量柱状图
BAR_ANSWER = (
    "成都市非遗工坊电商平台销量柱状图数据（shop_bar_chart，/show/shop/barChart）：\n"
    "| 维度层级 | 数量 | 数据来源·备注 |\n"
    "| --- | --- | --- |\n"
    "| 其他 | 27 | shop_bar_chart（cityName=成都市） |\n"
    "| 淘宝 | 14 | 同上 |\n"
    "| 京东 | 6 | 同上 |\n"
    "| 天猫 | 4 | 同上 |\n"
    "| 抖音 | 3 | 同上 |\n"
    "| 微店 | 2 | 同上 |\n"
    "| 美团 | 1 | 同上 |\n"
    "| 快手 | 1 | 同上 |\n"
    "| 合计 | 58 | 8 个平台 num 之和 |\n"
    "说明：其他为接口原样给出的未归类平台项，占比最高（27/58）。柱状图按上表数值渲染即可。"
)
PIE_ANSWER = (
    "非遗传承人学历构成饼图\n"
    "| 维度层级 | 数量 | 数据来源·备注 |\n"
    "| --- | --- | --- |\n"
    "| 大学 | 40 | inheritor_education_data |\n"
    "| 高中 | 35 | 同上 |\n"
    "| 初中 | 25 | 同上 |\n"
)
NON_CHART = "本次共办理 3 件，状态如下：\n| 字段 | 说明 |\n| --- | --- |\n| 办理量 | 若干 |\n| 在办 | 未知 |"


def login():
    d = httpx.Client(timeout=30, trust_env=False).post(
        f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"}).json()
    return d["data"]["accessToken"], d["data"]


def set_answer(pg, ans):
    """把一条 AI 回答塞进会话气泡，走真实 formatAnswer。

    用户端默认是 OA 形态（.phone.oa-mode），可见会话容器是 #oaDockList。
    oaPushBub 内部就是 el.innerHTML = html；这里按同样方式注入 formatAnswer(a)，
    等价于真实渲染路径（formatAnswer → innerHTML），且绕开作用域限制。
    """
    pg.evaluate("""(a) => {
        const list = document.getElementById('oaDockList');
        if(!list) return false;
        list.innerHTML = '';
        const q = document.createElement('div');
        q.className = 'bub me'; q.textContent = '工坊电商平台销量柱状图，成都市';
        list.appendChild(q);
        const bubble = document.createElement('div');
        bubble.className = 'bub ai ans';
        bubble.innerHTML = formatAnswer(a);   // 与 oaPushBub 一致：innerHTML = html
        list.appendChild(bubble);
        // oaSetChatting(true) 的作用就是给 #v-home 加 .chatting 让 .dock 显示
        const home = document.getElementById('v-home');
        if(home) home.classList.add('chatting');
        list.scrollTop = list.scrollHeight;
        return document.querySelector('.phone.oa-mode') ? 'oa' : 'classic';
    }""", ans)


def main():
    os.makedirs(OUT, exist_ok=True)
    tok, me = login()
    session = json.dumps({"token": tok, "user": me.get("user", me)}, ensure_ascii=False)

    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="msedge", headless=True)
        ctx = b.new_context(viewport={"width": 900, "height": 1000}, device_scale_factor=2)
        ctx.add_init_script(f"localStorage.setItem('aios_session', {json.dumps(session)})")
        pg = ctx.new_page()
        pg.goto(BASE + "/index.html", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        # 保持在默认 OA 形态：这就是用户截图里的界面，图表走 oaPushBub 的真实渲染路径
        mode = pg.evaluate("() => document.querySelector('.phone.oa-mode') ? 'oa' : 'classic'")
        print(f"[mode] {mode}")
        assert mode == "oa", "预期 OA 形态，实际 " + mode
        pg.wait_for_timeout(300)

        # 1) 柱状图场景
        set_answer(pg, BAR_ANSWER)
        pg.wait_for_timeout(300)
        svg_count = pg.locator(".ans-chart svg").count()
        chk("1 统计表渲染出 SVG 图表", svg_count == 1, f"svg_count={svg_count}")
        label = pg.locator(".ans-chart svg").get_attribute("aria-label") or ""
        chk("2 显式柱状图意图正确（正文含'占比'描述也不改饼图）", label.endswith("柱状图"), label)
        rect_count = pg.locator(".ans-chart svg rect").count()
        chk("3 柱状图有柱体（rect）", rect_count >= 8, f"rect={rect_count}")
        sub = pg.locator(".ans-chart-sub").inner_text()
        chk("4 分类轴/数值列自动映射", "横轴：维度层级" in sub and "纵轴：数量" in sub, sub)
        title = pg.locator(".ans-chart-title").inner_text()
        chk("5 标题取自表格上方文本", "电商平台销量柱状图数据" in title, title)
        chk("6 合计行不入图（8 平台 + 1 合计 → 8 根柱）", rect_count <= 8, f"rect={rect_count}")
        chk("7 原始表格折叠保留可核对来源", pg.locator(".ans-chart details").count() == 1
            and "shop_bar_chart" in (pg.locator(".ans-chart details").text_content() or ""))
        pg.screenshot(path=os.path.join(OUT, "01-bar-chart.png"))
        print("[shot] 柱状图 -> 01-bar-chart.png")

        # 2) 结果变化同步更新：换一组数据重渲染同一区域
        changed = BAR_ANSWER.replace("| 淘宝 | 14 |", "| 淘宝 | 88 |")
        set_answer(pg, changed)
        pg.wait_for_timeout(300)
        vals = pg.locator(".ans-chart svg rect").evaluate_all(
            "els => els.map(e => e.querySelector('title') ? e.querySelector('title').textContent : '')")
        chk("8 结果变化后图表同步更新（淘宝 14→88）", any("88" in v for v in vals), vals[:4])
        pg.screenshot(path=os.path.join(OUT, "02-chart-updated.png"))
        print("[shot] 图表同步更新 -> 02-chart-updated.png")

        # 3) 饼图场景
        set_answer(pg, PIE_ANSWER)
        pg.wait_for_timeout(300)
        label2 = pg.locator(".ans-chart svg").get_attribute("aria-label") or ""
        path_count = pg.locator(".ans-chart svg path").count()
        svg_text = pg.locator(".ans-chart svg").text_content() or ""
        chk("9 饼图意图→饼图扇形（path）+ 图例百分比", label2.endswith("饼图") and path_count >= 3 and "%" in svg_text,
            f"label={label2} path={path_count}")
        pg.screenshot(path=os.path.join(OUT, "03-pie-chart.png"))
        print("[shot] 饼图 -> 03-pie-chart.png")

        # 4) 非绘图表格保持原样
        set_answer(pg, NON_CHART)
        pg.wait_for_timeout(300)
        chk("10 非绘图表格保持原表格展示（无 svg）",
            pg.locator(".ans-chart").count() == 0 and pg.locator("table.ans-table").count() == 1,
            f"chart={pg.locator('.ans-chart').count()} table={pg.locator('table.ans-table').count()}")
        pg.screenshot(path=os.path.join(OUT, "04-non-chart-table.png"))
        print("[shot] 非绘图表格 -> 04-non-chart-table.png")

        # 5) 无数据 / 格式异常降级
        set_answer(pg, "柱状图统计\n| 维度层级 | 数量 |\n| --- | --- |")
        pg.wait_for_timeout(200)
        chk("11 无数据行安全降级为表格（不出空图）", pg.locator(".ans-chart").count() == 0
            and pg.locator("table.ans-table").count() == 1)
        set_answer(pg, "| 维度 | 数量 |\n| --- | --- |\n| 甲 | twelve |\n| 乙 | unknown |")
        pg.wait_for_timeout(200)
        chk("12 数值格式异常安全降级为表格", pg.locator(".ans-chart").count() == 0
            and pg.locator("table.ans-table").count() == 1)

        ctx.close(); b.close()

    print("\n[STATUS] " + ("PASS" if all(results) else "FAIL") + f" ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
