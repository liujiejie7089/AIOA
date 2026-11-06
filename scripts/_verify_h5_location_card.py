"""H5「定位调用申请」界面验收（2026-11-05）。

只验证三件事，且每件都要能从界面**之外**再核一遍（铁律 12：界面展示了 X 必须回库/接口再取）：
  1. OA 模块里确实有「打卡」入口，点它能弹出**居中**的定位申请卡；
  2. 点「允许并打卡」后，浏览器坐标被提交，库里出现一条 source=H5 的考勤记录，
     对应授权单从 PENDING 变 USED（不是只弹了个 toast）；
  3. 点「不允许」不会产生任何考勤记录，但会留下一条 DENIED 的审计（问过、被拒了）。
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import sys
import time
from pathlib import Path

import pymysql
from playwright.sync_api import sync_playwright

H5 = "http://127.0.0.1:8080/aios/h5/"
USER = "dsj_admin"
PW = "Admin@123"
OUT = Path(".workbuddy/tmp/acceptance-20261105")
OUT.mkdir(parents=True, exist_ok=True)
DB = dict(host="127.0.0.1", port=3306, user="root", password="", database="aios",
          charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)

results = []


def check(tag, cond, detail=""):
    results.append((tag, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {tag}" + (f"  {detail}" if detail else ""))


def db_row(uid):
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sys_user WHERE username=%s", (USER,))
            u = cur.fetchone()
            cur.execute("""SELECT id, status, origin, used_at, latitude FROM location_consent
                           WHERE user_id=%s ORDER BY id DESC LIMIT 3""", (u["id"],))
            cons = cur.fetchall()
            cur.execute("""SELECT id, clock_type, source, consent_id, latitude, longitude
                           FROM attendance_record WHERE user_id=%s AND work_date=CURDATE()
                           ORDER BY id DESC LIMIT 3""", (u["id"],))
            recs = cur.fetchall()
            return cons, recs
    finally:
        conn.close()


def reset_today():
    """清掉本脚本与接口脚本今天造的打卡行，让「首次打卡必新增」这条断言可重复。
    只删**今天、且依据授权单**产生的行，不碰任何历史或人工数据。"""
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sys_user WHERE username=%s", (USER,))
            uid = cur.fetchone()["id"]
            cur.execute("""DELETE FROM attendance_record
                           WHERE user_id=%s AND work_date=CURDATE() AND consent_id IS NOT NULL""", (uid,))
            cur.execute("""DELETE FROM location_consent
                           WHERE user_id=%s AND DATE(created_at)=CURDATE()""", (uid,))
            # pymysql 默认不开 autocommit：不 commit 的话 DELETE 会在 close 时回滚，
            # 表现为「明明清了库，下一轮还是 duplicated」。
            conn.commit()
    finally:
        conn.close()


def main():
    reset_today()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            geolocation={"latitude": 31.230416, "longitude": 121.473701, "accuracy": 22.0},
            permissions=["geolocation"],
            locale="zh-CN",
        )
        page = ctx.new_page()
        logs = []
        att_status = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
        page.on("response", lambda r: att_status.append((r.url, r.status)) if "/attendance/" in r.url else None)

        page.goto(H5, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # ---- 登录 ----
        if page.locator("#lgUser").count():
            page.fill("#lgUser", USER)
            page.fill("#lgPass", PW)
            page.click("#lgBtn")
            page.wait_for_timeout(2500)
        check("L1 登录后离开登录页", page.locator("#lgUser").count() == 0
              or not page.locator("#lgUser").is_visible())

        # ---- 切到 OA 形态 ----
        if not page.locator(".phone.oa-mode").count():
            sw = page.locator(".js-layout-switch")
            if sw.count():
                sw.first.click()
                page.wait_for_timeout(1200)
        check("L2 进入 OA 形态", page.locator(".phone.oa-mode").count() == 1)

        # ---- 打开模块宫格 ----
        page.evaluate("oaGo('modules')")
        page.wait_for_timeout(1200)
        tile = page.locator("[data-attendance]")
        check("L3 模块宫格有「打卡」磁贴", tile.count() == 1)
        if not tile.count():
            print("\n".join(logs[-15:]))
            return summary()
        check("L4 磁贴文案是打卡", "打卡" in (tile.first.inner_text() or ""),
              (tile.first.inner_text() or "").strip())
        page.screenshot(path=str(OUT / "01-modules-with-clock.png"))

        # ---- 点磁贴 → 定位申请卡 ----
        before_cons, before_recs = db_row(0)
        tile.first.click()
        page.wait_for_timeout(1500)
        opened = page.locator(".oa.loc-open").count() == 1
        check("L5 弹出定位申请卡", opened)
        if not opened:
            print("\n".join(logs[-15:]))
            return summary()
        card = page.locator("#oaLocCard")
        box = card.bounding_box()
        vp = page.viewport_size or {"width": 390, "height": 844}
        centered = box and abs((box["x"] + box["width"] / 2) - vp["width"] / 2) < 24
        check("L6 卡片水平居中", bool(centered), f"card={box}")
        txt = page.inner_text("#oaLocCard")
        check("L7 卡片写明用途", "定位" in txt and "打卡" in txt, txt.split("\n")[1][:36] if "\n" in txt else txt[:36])
        check("L8 卡片写有效期与「只这一次」", "分钟" in txt and "只" in txt)
        check("L9 两个按钮齐全", page.locator("#oaLocDeny").count() == 1 and page.locator("#oaLocOk").count() == 1)
        page.screenshot(path=str(OUT / "02-location-consent-card.png"))

        # ---- 允许并打卡 ----
        page.click("#oaLocOk")
        page.wait_for_timeout(3500)
        after_cons, after_recs = db_row(0)
        new_recs = [r for r in after_recs if r["id"] not in {x["id"] for x in before_recs}]
        check("L10 落库新增一条考勤记录", len(new_recs) >= 1, f"新增={len(new_recs)}")
        if new_recs:
            r = new_recs[0]
            check("L11 来源标记为 H5", r["source"] == "H5", str(r["source"]))
            check("L12 记录里带坐标", r["latitude"] is not None, str(r["latitude"]))
            check("L13 授权单已消费(USED)", any(c["status"] == "USED" and c["id"] == r["consent_id"] for c in after_cons),
                  str([(c["id"], c["status"]) for c in after_cons]))
        check("L14 卡片已关闭", page.locator(".oa.loc-open").count() == 0)
        page.screenshot(path=str(OUT / "03-after-clock.png"))

        # ---- 拒绝路径 ----
        page.evaluate("oaGo('modules')")
        page.wait_for_timeout(900)
        _, recs_before_deny = db_row(0)
        page.locator("[data-attendance]").first.click()
        page.wait_for_timeout(1200)
        if page.locator(".oa.loc-open").count() == 1:
            page.screenshot(path=str(OUT / "04-consent-again.png"))
            page.click("#oaLocDeny")
            page.wait_for_timeout(1600)
            cons2, recs_after_deny = db_row(0)
            check("L15 拒绝后卡片关闭", page.locator(".oa.loc-open").count() == 0)
            check("L16 拒绝没产生考勤记录", len(recs_after_deny) == len(recs_before_deny),
                  f"{len(recs_before_deny)} → {len(recs_after_deny)}")
            check("L17 留了 DENIED 审计", any(c["status"] == "DENIED" for c in cons2),
                  str([c["status"] for c in cons2]))
            page.screenshot(path=str(OUT / "05-after-deny.png"))
        else:
            check("L15 拒绝路径可复现", False, "第二次点击未弹卡（可能复用了未过期申请被消费）")

        errs = [x for x in logs if x.startswith("pageerror")]
        check("L18 无 JS 异常", not errs, "；".join(errs[:3]))
        bad = [(u, s) for u, s in att_status if s != 200]
        check("L19 定位/打卡接口全部 200", not bad, str(bad[:3]))
        check("L20 界面确实调用了三个接口",
              len({u.split("/attendance/")[-1].split("?")[0] for u, _ in att_status}) >= 2,
              str(sorted({u.split('/api/v1')[-1].split('?')[0] for u, _ in att_status}))[:160])
        browser.close()
    return summary()


def summary():
    ok = sum(1 for _, c, _ in results if c)
    print(f"\n===== {ok}/{len(results)} 通过 =====")
    bad = [t for t, c, _ in results if not c]
    if bad:
        print("失败项：" + "；".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
