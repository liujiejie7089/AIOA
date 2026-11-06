# -*- coding: utf-8 -*-
"""动态字段卡的**行为 + 截图 + 线上载荷证据**（Playwright，真实 H5）。

## 证明什么

用户要求：「根据用户的语义动态生成菜单、候选框和文本框等交互控件，并依据用户在其中的
输入内容驱动后续流程」。落到判据上，一张字段卡必须同时满足：

    ① 触发：只有该问的字段才显示 —— 依赖条件（visible_when）成立才出现；
    ② 类型：菜单（按钮组）/ 候选框（可输入过滤）/ 文本框 / 多行 / 日期 / 数字 各自渲染成
       合适的原生控件，不是「一律一个文本框」；
    ③ 依赖与状态：切换主导字段 ⇒ 依赖字段**收起且清空**（不能把上一支的内容带过去）；
    ④ 校验：必填未填 / 数字越界 / 非数字 ⇒ 就地红字 + 禁止提交，点确认要点亮问题字段；
    ⑤ 流转：一次提交 = **一次** resume，载荷里带全部可见字段（values）；
    ⑥ 连续性：resume 之后助手在同一气泡里继续说话（循环没断）。

载荷不是读我们的意图，而是**读浏览器实际发出的 POST body**。

## 跑法

    agent/.venv/Scripts/python.exe scripts/_shots_clar_fields.py

产物：logs/proof/clar-fields-{1-init,2-msg,3-meet,4-search,5-invalid,6-sent,7-num}.png
前置：只需本机 msedge（Playwright channel）；不需要后端与连接器在线。
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import asyncio
import json
import os
import sys
import urllib.parse

from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "agent"))

from aios_ai.tools import ask_user as ask_user_tool      # noqa: E402
from aios_ai.tools import entity_clarify as ec           # noqa: E402

INDEX = os.path.join(REPO, "user-client", "index.html")
OUT = os.path.join(REPO, "logs", "proof")

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


SSE = {"content-type": "text/event-stream",
       "access-control-allow-origin": "*",
       "cache-control": "no-cache"}
JSON = {"content-type": "application/json", "access-control-allow-origin": "*"}

UTTERANCE = "帮我和同事说个事"
REPLY = "已发出：「下午三点开会」→ 刘洋。"

# 候选用固定样本（本脚本不依赖后端/连接器在线）；**卡的形状由生产代码生成** ——
# `entity_clarify.build_action_fields_call` 正是「人称 + 泛动作 ⇒ 字段卡」那条路。
# 真实通讯录候选的版本见 `scripts/_e2e_clar_once.py`（真机，返回 3 位同事）。
MEMBERS = [{"userid": f"wob{i}", "name": n} for i, n in enumerate(
    ["刘洋", "小亮", "阿修bot.", "王敏", "李强", "赵磊", "陈静", "周涛"], 1)]

# 控件面板本身用**生产代码**归一（ask_user.build_clarification），
# 这样顺带证明「未知类型降级 / 悬挂依赖剪除 / 成环剪除」在真链路上生效。
CARD_ARGS = ec.build_action_fields_call(MEMBERS)["arguments"]


def frame(spec: dict) -> str:
    payload = {"question": spec["question"], "suggested_options": spec.get("suggested_options") or []}
    if spec.get("fields"):
        payload["fields"] = spec["fields"]
    return "event: need_clarification\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def done_frame() -> str:
    return ("event: message.delta\ndata: " + json.dumps({"text": REPLY}, ensure_ascii=False) + "\n\n"
            "event: message.completed\ndata: {}\n\n"
            "event: run.completed\ndata: {}\n\n")


async def start_session(page, spec: dict) -> dict:
    """装拦截（活到 run 收口）→ 跑 send() → 等卡片挂载。"""
    seen = {"resume_body": None, "resume_hits": 0}

    async def handler(route, request):
        url = request.url
        if "/resume" in url:
            seen["resume_hits"] += 1
            try:
                seen["resume_body"] = json.loads(request.post_data or "{}")
            except ValueError:
                seen["resume_body"] = {"_raw": request.post_data}
            await route.fulfill(status=200, headers=SSE, body=done_frame())
            return
        if url.endswith("/events"):
            await route.fulfill(status=200, headers=SSE, body=frame(spec))
            return
        if "/v1/conversations" in url and url.rstrip("/").endswith("conversations"):
            await route.fulfill(status=200, headers=JSON, body='{"code":0,"data":{"id":"c1"}}')
            return
        await route.fulfill(status=200, headers=JSON, body='{"code":0,"data":{"id":"r1"}}')

    await page.route("**/v1/**", handler)
    await page.evaluate("""(u) => {
      state.busy = false;
      state.conversationId = 'c1';
      state.quotaInfo = null;
      state.controller = null;
      clarPendingResolve = null;
      const box = $('msgs'); if (box) box.innerHTML = '';
      $('chatInput').value = u;
    }""", UTTERANCE)
    task = asyncio.ensure_future(page.evaluate("() => send()"))
    await page.wait_for_selector(".clar-card", timeout=8000)
    return {"task": task, "seen": seen}


async def finish_session(page, sess: dict, *, wait: bool = True) -> None:
    if wait:
        try:
            await asyncio.wait_for(sess["task"], timeout=8)
        except asyncio.TimeoutError:
            chk("send() 在回填后正常收口", False, "超时：回填后循环没退出")
    elif not sess["task"].done():
        sess["task"].cancel()
    try:
        await page.unroute("**/v1/**")
    except Exception:      # noqa: BLE001
        pass


async def snap(page, path: str) -> None:
    await page.wait_for_timeout(120)
    await page.screenshot(path=path)


def field_state(page, fid: str):
    return page.evaluate("""(fid) => {
      const w = document.querySelector('.clar-field[data-fid="' + fid + '"]');
      if(!w) return {ok:false};
      const inp = w.querySelector('.clar-inp, .clar-text');
      const err = w.querySelector('.clar-err');
      const ok = document.querySelector('.clar-ok');
      return {
        ok: true,
        hidden: !!w.hidden,
        type: w.getAttribute('data-type'),
        bad: w.classList.contains('bad'),
        err: (err && !err.hidden) ? (err.textContent || '') : '',
        value: inp ? inp.value : '',
        okDisabled: ok ? !!ok.disabled : null,
        selCount: w.querySelectorAll('.clar-opt.sel, .clar-cand.sel').length,
        candVisible: w.querySelectorAll('.clar-cand:not([hidden])').length
      };
    }""", fid)


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    spec = ask_user_tool.build_clarification(CARD_ARGS)
    fields = spec.get("fields") or []
    chk("生产代码按语义生成 6 个字段（菜单/候选框/多行/日期/文本/长文本）",
        len(fields) == 6, str([f["type"] for f in fields]))
    chk("字段 id 就是语义骨架（action/person/三支依赖/其它出口）",
        [f["id"] for f in fields] == ["action", "person", "content", "when", "title", "other"],
        str([f["id"] for f in fields]))
    chk("依赖条件原样保留（content ← action=message）",
        fields[2].get("visible_when") == {"field": "action", "op": "eq", "value": "message"},
        str(fields[2].get("visible_when")))
    chk("有字段卡时不再带旧选项（避免两套控件两套规则）",
        spec["suggested_options"] == [], str(spec["suggested_options"]))

    if not os.path.exists(INDEX):
        chk("user-client/index.html 存在", False, INDEX)
        return _report()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)
        ctx = await browser.new_context(viewport={"width": 390, "height": 1180},
                                        device_scale_factor=2, locale="zh-CN")
        page = await ctx.new_page()
        page.on("pageerror", lambda e: print("  [pageerror] " + str(e), flush=True))
        await page.goto("file:///" + urllib.parse.quote(INDEX.replace("\\", "/"), safe="/"),
                        wait_until="domcontentloaded")
        await page.wait_for_function("() => typeof state !== 'undefined' && !!$('msgs')",
                                     timeout=8000)
        await page.wait_for_timeout(1500)
        await page.evaluate("() => { API.base = 'https://shot.local/api'; state.token = ''; }")

        sess = await start_session(page, spec)

        # ------------------------------------------------ ① 初始：依赖字段全部隐藏
        a = await field_state(page, "action")
        c = await field_state(page, "content")
        w = await field_state(page, "when")
        t = await field_state(page, "title")
        p = await field_state(page, "person")
        chk("① 动作字段渲染成菜单（4 个选项，含「其它」出口）",
            a["type"] == "select" and not a["hidden"], str(a))
        chk("① 对象字段渲染成可检索候选框（8 个候选可见）",
            p["type"] == "select" and p["candVisible"] == 8, str(p["candVisible"]))
        chk("① 依赖字段初始**全部隐藏**（还没选动作）",
            c["hidden"] and w["hidden"] and t["hidden"],
            f"content={c['hidden']} when={w['hidden']} title={t['hidden']}")
        chk("① 刚挂上来不先红一片（没碰过的字段不报错）",
            not a["bad"] and not p["bad"], f"action={a['bad']} person={p['bad']}")
        await snap(page, os.path.join(OUT, "clar-fields-1-init.png"))

        # ------------------------------------------------ ③ 选「发消息」⇒ 只展开消息内容
        await page.locator('.clar-field[data-fid="action"] .clar-opt').first.click()
        c = await field_state(page, "content")
        w = await field_state(page, "when")
        chk("③ 选「发消息」⇒ 消息内容展开", c["hidden"] is False, str(c))
        chk("③ 其余依赖字段仍隐藏（会议时间 / 待办标题）", w["hidden"] and t["hidden"],
            f"when={w['hidden']} title={t['hidden']}")

        # ------------------------------------------------ ② 候选框：输入即过滤
        await page.locator('.clar-field[data-fid="person"] .clar-search').fill("刘")
        p = await field_state(page, "person")
        chk("② 候选框输入「刘」⇒ 只剩 1 个候选（就地过滤，无远程请求）",
            p["candVisible"] == 1, str(p["candVisible"]))
        await snap(page, os.path.join(OUT, "clar-fields-4-search.png"))
        await page.locator('.clar-field[data-fid="person"] .clar-cand:not([hidden])').first.click()
        p = await field_state(page, "person")
        chk("② 选中候选后高亮", p["selCount"] == 1, str(p["selCount"]))

        # 填内容，再切到「约会议」⇒ 内容框应**收起且清空**
        await page.locator('.clar-field[data-fid="content"] .clar-text').fill("下午三点开会")
        await snap(page, os.path.join(OUT, "clar-fields-2-msg.png"))
        await page.locator('.clar-field[data-fid="action"] .clar-opt').nth(1).click()
        c = await field_state(page, "content")
        w = await field_state(page, "when")
        chk("③ 切到「约会议」⇒ 消息内容收起", c["hidden"] is True, str(c["hidden"]))
        chk("③ 收起时清空，不把上一支的内容带过去", c["value"] == "", repr(c["value"]))
        chk("③ 会议时间随之展开", w["hidden"] is False, str(w["hidden"]))
        await snap(page, os.path.join(OUT, "clar-fields-3-meet.png"))

        # 填好 ⇒ 红字消失
        await page.locator('.clar-field[data-fid="when"] .clar-inp').fill("2026-11-03T15:00")
        w = await field_state(page, "when")
        chk("④ 填好后红字消失", w["bad"] is False and w["err"] == "", str(w))

        # ------------------------------------------------ ⑤ 一次提交 ⇒ 载荷带全部可见字段
        await page.locator(".clar-ok").click()
        await finish_session(page, sess)
        seen = sess["seen"]
        ans = (seen.get("resume_body") or {}).get("answer") or {}
        vals = ans.get("values") or {}
        chk("⑤ 只发了一次 resume", seen["resume_hits"] == 1, f"{seen['resume_hits']} 次")
        chk("⑤ 载荷 values 含全部**可见**字段", set(vals) == {"action", "person", "when"},
            str(sorted(vals)))
        chk("⑤ 隐藏字段（消息内容 / 待办标题）**没有**被提交",
            "content" not in vals and "title" not in vals, str(sorted(vals)))
        chk("⑤ 值正确", vals.get("action") == "meeting" and vals.get("person") == "wob1"
            and vals.get("when") == "2026-11-03T15:00", str(vals))
        chk("⑤ 兼容键 value/label 指向第一个选择型字段",
            ans.get("value") == "meeting" and ans.get("label") == "约会议", str(ans))

        s = await page.evaluate("""() => {
          const c = document.querySelector('.clar-card');
          return (c && c.querySelector('.clar-picked')) ? c.querySelector('.clar-picked').textContent : '';
        }""")
        chk("⑤ 落款逐字段列出（动作/对象/会议时间）",
            "想做什么" in s and "对象" in s and "会议时间" in s, s)

        bubble_tx = await page.evaluate("""() => {
          const bs = document.querySelectorAll('#msgs .bubble');
          return bs.length ? (bs[bs.length-1].innerText || '') : '';
        }""")
        chk("⑥ 提交后助手继续说话（循环没断）", REPLY in bubble_tx, bubble_tx[-60:].replace("\n", " / "))
        await snap(page, os.path.join(OUT, "clar-fields-6-sent.png"))

        # ------------------------------------------------ ④ 空表提交：不提交 + 点亮必填
        # 单独开一张卡来验「什么都没填就点确认」：混在上一张里会先被别的操作"碰过"，
        # 就看不出「一进来不红、点了才红」这条体验约束。
        sess_v = await start_session(page, spec)
        await page.locator(".clar-ok").click()
        a = await field_state(page, "action")
        p = await field_state(page, "person")
        chk("④ 空表点确认 ⇒ **不提交**（resume 一次都没发）",
            sess_v["seen"]["resume_hits"] == 0, f"{sess_v['seen']['resume_hits']} 次")
        chk("④ 空表点确认 ⇒ 必填字段亮红并说明「必填」",
            a["bad"] and a["err"] == "必填" and p["bad"], f"action={a['err']!r} person_bad={p['bad']}")
        await snap(page, os.path.join(OUT, "clar-fields-5-invalid.png"))
        await page.evaluate("() => { if(typeof cancelClarCard==='function') cancelClarCard(); }")
        await finish_session(page, sess_v, wait=False)

        # ------------------------------------------------ 数字/日期校验（另一张卡）
        num = ask_user_tool.build_clarification({
            "question": "报销多少、哪天、算哪个项目？",
            "fields": [
                {"id": "amount", "label": "金额（元）", "type": "number", "required": True,
                 "min": 1, "max": 1000, "placeholder": "例如：128"},
                {"id": "day", "label": "发生日期", "type": "date", "required": True},
                # 多选：与菜单/候选框同一套卡（可多值，值形状是数组）
                {"id": "tags", "label": "归属项目", "type": "multi",
                 "options": [{"value": "p1", "label": "智慧园区"},
                             {"value": "p2", "label": "内部工具"}]},
            ],
        })
        sess2 = await start_session(page, num)
        await page.locator('.clar-field[data-fid="amount"] .clar-inp').fill("5000")
        a = await field_state(page, "amount")
        chk("④ 数字越界 ⇒ 就地提示「不能大于 1000」", a["err"] == "不能大于 1000", repr(a["err"]))
        await page.locator(".clar-ok").click()
        chk("④ 越界时点确认 ⇒ 不提交", sess2["seen"]["resume_hits"] == 0, "")
        await page.locator('.clar-field[data-fid="amount"] .clar-inp').fill("128")
        await page.locator('.clar-field[data-fid="day"] .clar-inp').fill("2026-11-01")
        a = await field_state(page, "amount")
        chk("④ 改回合法值后红字消失", a["bad"] is False and a["err"] == "", str(a))
        await snap(page, os.path.join(OUT, "clar-fields-7-num.png"))
        await page.locator(".clar-ok").click()
        await finish_session(page, sess2)
        ans2 = (sess2["seen"].get("resume_body") or {}).get("answer") or {}
        v2 = ans2.get("values") or {}
        chk("⑤ 数字/日期/多选卡也能一次提交", v2.get("amount") == "128" and v2.get("day") == "2026-11-01",
            str(v2))
        chk("⑤ 多选的值是数组（没选就是空数组，不是 null）", v2.get("tags") == [], str(v2.get("tags")))

        await browser.close()

    return _report()


def _report() -> int:
    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    print("截图 → logs/proof/clar-fields-*.png")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
