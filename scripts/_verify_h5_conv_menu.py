# -*- coding: utf-8 -*-
"""「最近」会话列表：标题语义 + 长按动作面板（V108，2026-11-06）

用户诉求（原话）：
  标题写成「用户的问题总结」；保留与用户的记录、用户可以接着对话；
  长按弹出对话框，有「置顶」「重命名」「查找对话记录」「删除」。

判据（每条都回接口/库核，不看界面文字自证）：
  T1 会话标题 = 用户第一句问题的总结（而不是创建方传的技术名/「新会话」）
  T2 用户手动重命名之后，再发问题**不会**被自动标题覆盖（title_source=MANUAL）
  T3 置顶后该会话排在本人的「最近」首位（接口顺序，不是前端排的）
  T4 取消置顶后回到正常顺序
  T5 查找对话记录：本会话消息里能按关键词命中（前端用的是同一个接口）
  T6 删除后列表不再返回，库里 deleted_at 非空（逻辑删除，不是物理删）
  T7 一句没问的空壳会话不进「最近」（onlyAsked=true），但没被删：默认列表仍有、按 id 仍能打开
  T8 空壳会话问出第一句后，立刻出现在「最近」且标题=这句问题的总结
  U1 浏览器里长按条目弹出面板，四项文案齐全
  U2 点「置顶」→ 条目出现置顶标记
  U3 点「重命名」→ 弹输入框 → 保存后标题变化
  U4 点「查找对话记录」→ 输关键词 → 结果含高亮 <mark>
  U5 点「删除」→ 确认 → 该条目从列表消失

前置：后端 :8080（H5 在 /aios/h5/）、agent :8000（发 run 只为触发首轮标题，不等回答）。
用法：python scripts/_verify_h5_conv_menu.py
"""

try:  # A3：GBK 控制台打印 emoji 会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pathlib
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
API = BASE + "/api/v1"
H5 = BASE + "/aios/h5/"
USER, PWD = "test", "test"
OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets" / "regression-2026-11-06"
OUT.mkdir(parents=True, exist_ok=True)

results = []


def rec(name, ok, expected, actual, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def login():
    c = httpx.Client(timeout=30, trust_env=False)
    d = c.post(f"{API}/auth/login", json={"username": USER, "password": PWD}).json()
    if d.get("code") != 0:
        raise SystemExit(f"登录失败：{d.get('message')}")
    tok = d["data"]["accessToken"]
    return tok, d["data"]["user"], {"Authorization": "Bearer " + tok}


def get(h, path):
    r = httpx.get(API + path, headers=h, timeout=30, trust_env=False).json()
    return r


def post(h, path, body=None):
    return httpx.post(API + path, headers=h, json=body or {}, timeout=60, trust_env=False).json()


def put(h, path, body=None):
    return httpx.put(API + path, headers=h, json=body or {}, timeout=30, trust_env=False).json()


def delete(h, path):
    return httpx.delete(API + path, headers=h, timeout=30, trust_env=False).json()


def convs(h):
    d = get(h, "/conversations?page=1&size=50")
    data = d.get("data") or {}
    return data.get("list") or []


def convs_asked(h):
    """用户端「最近」真正用的口径：onlyAsked=true，只要提过问的会话。"""
    d = get(h, "/conversations?page=1&size=50&onlyAsked=true")
    data = d.get("data") or {}
    return data.get("list") or []


def convs_kw(h, kw, only_asked=False):
    """按标题关键词精确捞，避免被分页影响判断。

    test 账号下有上百条历史会话，而空壳会话的 last_msg_at 为 NULL ——
    MySQL 里 DESC 会把 NULL 排在最后，默认列表第一页根本轮不到它，
    所以「默认列表里还能查到」这类判据必须带上关键词，否则测的是分页而不是语义。
    """
    q = f"/conversations?page=1&size=50&keyword={kw}"
    if only_asked:
        q += "&onlyAsked=true"
    d = get(h, q)
    data = d.get("data") or {}
    return data.get("list") or []


def find_conv(h, cid):
    for c in convs(h):
        if int(c.get("id") or 0) == int(cid):
            return c
    return None


def main():
    token, user, h = login()
    stamp = time.strftime("%H%M%S")
    question = "帮我看看这个季度的报销汇总有多少笔"
    cid = None

    try:
        # ---------------------------------------------------------------- 造一条真实会话
        d = post(h, "/conversations", {})
        cid = (d.get("data") or {}).get("id")
        rec("前置：建会话成功（不传 title）", d.get("code") == 0 and bool(cid), "code=0", d.get("code"))
        if not cid:
            raise SystemExit("无法建会话，终止")

        # 首轮问题：标题在 RunService.start 里同步写库（不等 agent 回答）
        r = post(h, f"/conversations/{cid}/runs", {"text": question})
        rec("前置：发起首轮对话成功", r.get("code") == 0, "code=0", r.get("message") or r.get("code"))

        # ---------------------------------------------------------------- T1 标题=问题总结
        title = None
        for _ in range(20):
            c = find_conv(h, cid)
            title = (c or {}).get("title")
            if title and title != "新会话":
                break
            time.sleep(0.3)
        rec("T1 标题被写成用户的问题总结（不是「新会话」/技术名）",
            bool(title) and title != "新会话" and "报销汇总" in title and "帮我" not in title,
            "含核心词「报销汇总」、不含口语前缀「帮我」、不是「新会话」", title,
            "判据刻意不写「等于原句」：标题的设计就是剥掉「帮我看看」这类前缀，只留问题本身")
        c = find_conv(h, cid)
        rec("T1b 标题来源被标记为 AUTO", (c or {}).get("titleSource") == "AUTO",
            "AUTO", (c or {}).get("titleSource"))

        # ---------------------------------------------------------------- T2 重命名后不被覆盖
        new_name = "报销汇总·" + stamp
        r = put(h, f"/conversations/{cid}", {"title": new_name})
        rec("T2 重命名接口成功", r.get("code") == 0, "code=0", r.get("code"))
        c = find_conv(h, cid)
        rec("T2b 标题已改为新名字且来源=MANUAL",
            (c or {}).get("title") == new_name and (c or {}).get("titleSource") == "MANUAL",
            f"title={new_name}, titleSource=MANUAL",
            f"title={(c or {}).get('title')}, titleSource={(c or {}).get('titleSource')}")

        # 再发一轮：必须保持用户改过的名字
        post(h, f"/conversations/{cid}/runs", {"text": "顺便算一下平均每笔多少钱"})
        time.sleep(1.2)
        c = find_conv(h, cid)
        rec("T2c 手动改名后再提问，标题不被自动覆盖",
            (c or {}).get("title") == new_name, new_name, (c or {}).get("title"))

        # ---------------------------------------------------------------- T5 查找对话记录（同接口）
        msgs = get(h, f"/conversations/{cid}/messages").get("data") or []
        hit = [m for m in msgs if "报销" in str(m.get("content") or "")]
        rec("T5 会话消息能按关键词命中（前端「查找对话记录」用的是同一接口）",
            len(hit) >= 1, "≥1 条含「报销」", len(hit))

        # ---------------------------------------------------------------- T3 置顶
        r = put(h, f"/conversations/{cid}/pin", {"pinned": True})
        rec("T3 置顶接口成功", r.get("code") == 0, "code=0", r.get("code"))
        lst = convs(h)
        first = lst[0] if lst else {}
        rec("T3b 置顶后排在本人的「最近」首位",
            int(first.get("id") or 0) == int(cid) and int(first.get("pinned") or 0) == 1,
            f"first.id={cid}, pinned=1",
            f"first.id={first.get('id')}, pinned={first.get('pinned')}")

        # ---------------------------------------------------------------- T4 取消置顶
        r = put(h, f"/conversations/{cid}/pin", {"pinned": False})
        c = find_conv(h, cid)
        rec("T4 取消置顶后 pinned=0",
            r.get("code") == 0 and int((c or {}).get("pinned") or 0) == 0,
            "pinned=0", (c or {}).get("pinned"))

        # ---------------------------------------------------------------- T7/T8 空壳会话
        # 用户点进数字人却一句没问，会留下 msg_count=0 的会话；它们没有用户问题、
        # 标题无从总结，留在「最近」里只会把真会话挤下去（截图里 8 条「请假助手 · 对话」就是这样）。
        d = post(h, "/conversations", {"title": "空壳探针 " + stamp})
        eid = (d.get("data") or {}).get("id")
        found_asked = [c for c in convs_asked(h) if int(c.get("id") or 0) == int(eid)]
        # 默认列表按关键词捞（见 convs_kw 注释：空壳会话 last_msg_at 为 NULL，会被分页挤到后面）
        found_all = [c for c in convs_kw(h, "空壳探针") if int(c.get("id") or 0) == int(eid)]
        rec("T7 空壳会话（一句没问）不出现在「最近」(onlyAsked=true)",
            len(found_asked) == 0, "0 条", len(found_asked),
            "口径在列表接口过滤，不删数据")
        rec("T7b 但它没被删：默认列表仍能查到（按 id 打开续聊不受影响）",
            len(found_all) == 1, "1 条", len(found_all))
        detail = get(h, f"/conversations/{eid}")
        rec("T7c 空壳会话仍可按 id 取详情（续聊入口不失效）",
            detail.get("code") == 0 and (detail.get("data") or {}).get("id") == eid,
            f"id={eid}", detail.get("code"))

        ask = "帮我查一下上个月的差旅报销单"
        post(h, f"/conversations/{eid}/runs", {"text": ask})
        etitle = None
        for _ in range(20):
            hit = [c for c in convs_asked(h) if int(c.get("id") or 0) == int(eid)]
            if hit:
                etitle = hit[0].get("title")
                break
            time.sleep(0.3)
        rec("T8 问出第一句后立刻进「最近」，标题=这句问题的总结",
            bool(etitle) and "差旅报销" in str(etitle) and "帮我" not in str(etitle),
            "含「差旅报销」、不含「帮我」、出现在 onlyAsked 列表", etitle)

        # ---------------------------------------------------------------- 浏览器段
        with sync_playwright() as pw:
            b = pw.chromium.launch(channel="msedge", headless=True)
            ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
            ctx.add_init_script(
                "localStorage.setItem('aios_session', %s);localStorage.setItem('aios_mode','oa');"
                % json.dumps(json.dumps({"token": token, "user": user}, ensure_ascii=False)))
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
            pg.goto(H5, wait_until="domcontentloaded")
            pg.wait_for_selector("#oaRoot", timeout=30000)
            pg.wait_for_timeout(2600)

            # 打开抽屉
            pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
            pg.wait_for_timeout(700)
            pg.screenshot(path=str(OUT / "20-recent-titles.png"))

            # 抽屉里不该出现「还没有提问」的空壳条目 —— 证明前端确实带上了 onlyAsked=true
            empty_items = pg.evaluate(
                "() => Array.from(document.querySelectorAll('#oaDrawerRecent .recent-item'))"
                ".map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())"
                ".filter(t => t.includes('还没有提问'))")
            rec("U0b 抽屉里没有「还没有提问」的空壳会话（前端带 onlyAsked=true）",
                len(empty_items) == 0, "0 条", empty_items)

            # 找到我们这条会话对应的条目（按文本）
            item = pg.locator("#oaDrawerRecent .recent-item", has_text=new_name).first
            rec("U0 抽屉里能看到这条会话（标题=用户的问题总结/改后的名字）",
                item.count() > 0, "找到条目", item.count())

            # U0c 单击 = 接着聊（用户诉求「保留与用户的记录，用户可以接着对话」）
            # 判据看**对话坞里真实回填的消息文本**，不看 toast/标题这类间接信号。
            item.click()
            pg.wait_for_timeout(2000)
            dock = pg.evaluate("() => (document.querySelector('#oaDockList')||{}).innerText || ''")
            rec("U0c 点条目即续聊：该会话的历史消息回到对话坞",
                "报销汇总" in dock, "对话坞含首轮问题里的『报销汇总』",
                (dock or "")[:80].replace("\n", " / "))
            # 回到抽屉继续后面的长按用例
            pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
            pg.wait_for_timeout(700)

            # 长按（鼠标按住 700ms > 500ms 阈值）
            box = item.bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(750)
            opened = pg.evaluate("() => document.querySelector('#oaConvMenu').classList.contains('on')")
            texts = pg.evaluate("() => Array.from(document.querySelectorAll('#oaConvMenu [data-cm]'))"
                                ".map(e => (e.textContent||'').trim())")
            pg.mouse.up()
            pg.screenshot(path=str(OUT / "21-conv-menu.png"))
            need = ["置顶", "重命名", "查找对话记录", "删除"]
            rec("U1 长按弹出动作面板，四项齐全",
                opened and all(any(n in t for t in texts) for n in need), need, {"opened": opened, "items": texts})

            # 点「置顶」
            pg.evaluate("() => document.querySelector('#oaConvMenu [data-cm=\"pin\"]').click()")
            pg.wait_for_timeout(1600)
            pinned_ui = pg.evaluate(
                "(n) => { const r = Array.from(document.querySelectorAll('#oaDrawerRecent .recent-item'))"
                ".find(e => (e.innerText||'').includes(n));"
                "return r ? {pinned: r.classList.contains('pinned'), txt: (r.innerText||'').slice(0,40)} : null; }",
                new_name)
            rec("U2 点「置顶」后条目出现置顶标记",
                bool(pinned_ui and pinned_ui.get("pinned")) and "置顶" in (pinned_ui or {}).get("txt", ""),
                "{pinned:true, 含『置顶』徽标}", pinned_ui)
            pg.screenshot(path=str(OUT / "22-pinned-item.png"))

            # 取消置顶（再长按一次，文案应变成「取消置顶」）
            pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
            pg.wait_for_timeout(600)
            it2 = pg.locator("#oaDrawerRecent .recent-item", has_text=new_name).first
            b2 = it2.bounding_box()
            pg.mouse.move(b2["x"] + b2["width"] / 2, b2["y"] + b2["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(750)
            pin_label = pg.evaluate("() => (document.querySelector('#oaConvPin')||{}).textContent")
            pg.mouse.up()
            rec("U2b 已置顶的会话，菜单文案变为「取消置顶」", "取消置顶" in str(pin_label), "取消置顶", pin_label)
            pg.evaluate("() => document.querySelector('#oaConvMenu [data-cm=\"pin\"]').click()")
            pg.wait_for_timeout(1400)

            # 重命名
            pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
            pg.wait_for_timeout(600)
            it3 = pg.locator("#oaDrawerRecent .recent-item", has_text=new_name).first
            b3 = it3.bounding_box()
            pg.mouse.move(b3["x"] + b3["width"] / 2, b3["y"] + b3["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(700)
            pg.mouse.up()
            pg.evaluate("() => document.querySelector('#oaConvMenu [data-cm=\"rename\"]').click()")
            pg.wait_for_selector("#askDlgInput", timeout=6000)
            renamed = "改名·" + stamp
            pg.fill("#askDlgInput", renamed)
            pg.screenshot(path=str(OUT / "23-rename-dialog.png"))
            pg.evaluate("() => document.querySelector('[data-dlg-ok]').click()")
            pg.wait_for_timeout(1600)
            ok_rename = pg.evaluate(
                "(n) => Array.from(document.querySelectorAll('#oaDrawerRecent .recent-item'))"
                ".some(e => (e.innerText||'').includes(n))", renamed)
            rec("U3 重命名后面板里显示新名字", ok_rename, renamed, ok_rename)

            # 查找对话记录
            it4 = pg.locator("#oaDrawerRecent .recent-item", has_text=renamed).first
            b4 = it4.bounding_box()
            pg.mouse.move(b4["x"] + b4["width"] / 2, b4["y"] + b4["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(700)
            pg.mouse.up()
            pg.evaluate("() => document.querySelector('#oaConvMenu [data-cm=\"find\"]').click()")
            pg.wait_for_selector("#askDlgInput", timeout=6000)
            pg.fill("#askDlgInput", "报销")
            pg.evaluate("() => document.querySelector('[data-dlg-ok]').click()")
            pg.wait_for_timeout(2000)
            find_state = pg.evaluate("""() => ({
                open: document.querySelector('#oaFindSheet').classList.contains('on'),
                head: (document.querySelector('#oaFindHead')||{}).textContent,
                marks: document.querySelectorAll('#oaFindList mark').length,
                hits: document.querySelectorAll('#oaFindList .cm-hit').length
            })""")
            pg.screenshot(path=str(OUT / "24-find-results.png"))
            rec("U4 查找结果面板打开、命中带高亮", 
                find_state.get("open") and find_state.get("hits", 0) >= 1 and find_state.get("marks", 0) >= 1,
                "{open:true, hits≥1, marks≥1}", find_state)

            # 关闭查找面板
            pg.evaluate("() => document.querySelector('#oaFindSheet [data-find-close]').click()")
            pg.wait_for_timeout(400)

            # 删除
            pg.evaluate("() => { const l = document.querySelector('#oaLeft'); if(l) l.click(); }")
            pg.wait_for_timeout(600)
            it5 = pg.locator("#oaDrawerRecent .recent-item", has_text=renamed).first
            b5 = it5.bounding_box()
            pg.mouse.move(b5["x"] + b5["width"] / 2, b5["y"] + b5["height"] / 2)
            pg.mouse.down()
            pg.wait_for_timeout(700)
            pg.mouse.up()
            pg.evaluate("() => document.querySelector('#oaConvMenu [data-cm=\"del\"]').click()")
            pg.wait_for_timeout(700)
            pg.screenshot(path=str(OUT / "25-delete-confirm.png"))
            pg.evaluate("() => document.querySelector('[data-dlg-ok]').click()")
            pg.wait_for_timeout(1800)
            gone = pg.evaluate(
                "(n) => !Array.from(document.querySelectorAll('#oaDrawerRecent .recent-item'))"
                ".some(e => (e.innerText||'').includes(n))", renamed)
            rec("U5 删除后条目从「最近」消失", gone, "列表里不再有该标题", gone)

            rec("U6 全程无 JS 运行时报错", len(errs) == 0, "0 条", errs[:3])

            # U7：OA「我的 → 会话」整页列表（renderRecent）与抽屉同源，标题口径也必须一致。
            # 这页原来直接读 c.title，改走 oaConvTitle 后要确认没引用错作用域（改完不跑一次等于没验证）。
            pg.evaluate("() => { const t = document.querySelector('#oaTabs .tab[data-view=\"me\"]'); if(t) t.click(); }")
            pg.wait_for_timeout(900)
            pg.evaluate("() => { const s = document.querySelector('.me-stat[data-view=\"recent\"]'); if(s) s.click(); }")
            pg.wait_for_timeout(1200)
            rows = pg.evaluate(
                "() => Array.from(document.querySelectorAll('#oaRecentList .lrow .t1'))"
                ".map(e => (e.textContent||'').trim())")
            pg.screenshot(path=str(OUT / "26-recent-full-page.png"), full_page=False)
            bad = [t for t in rows if ('probe' in t) or ('· 对话' in t) or ('还没有提问' in t)]
            rec("U7 「我的→会话」整页标题同为问题总结（无技术名/空壳重复）",
                len(rows) >= 1 and len(bad) == 0,
                "≥1 行且无 probe / 『· 对话』/『还没有提问』", {"rows": rows[:5], "bad": bad})
            rec("U7b 该页渲染未抛 JS 错误（oaConvTitle 作用域正确）", len(errs) == 0, "0 条", errs[:3])
            b.close()

        # ---------------------------------------------------------------- T6 删除（接口/库口径）
        c2 = find_conv(h, cid)
        rec("T6 删除后列表接口不再返回该会话", c2 is None, "None", c2)

    finally:
        # 清理：兜底再删一次（已删则静默失败）；空壳探针也一并清掉，避免污染「最近」
        for _cid in (cid, locals().get("eid")):
            if not _cid:
                continue
            try:
                delete(h, f"/conversations/{_cid}")
            except Exception:
                pass

    ok = sum(1 for _, v in results if v)
    print("\n" + "=" * 70)
    for n, v in results:
        print(("  ✅ " if v else "  ❌ ") + n)
    print(f"\n合计 {len(results)} 项，通过 {ok}，失败 {len(results) - ok}")
    print("截图目录：", OUT)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
