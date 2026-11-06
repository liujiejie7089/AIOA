# -*- coding: utf-8 -*-
"""「一次交互交齐」的**截图 + 线上载荷证据**（Playwright，真实 H5）。

## 要证明的三件事

2026-11-02 现场：用户点「小亮」→ 卡片落款「已选择：小亮」→ **气泡再无下文**。
根因不在渲染，而在回填：`resume` 只送了裸标量 `userid`，模型拿不到「要发什么」，
只能再问一句 ⇒ 一次任务被拆成三轮，中途上下文就断了。

所以这里要证的是一条链，而不只是一张图：

    ① 选中带 needs_text 的选项  ⇒ 输入框**当场展开**且变必填（不留空交上去）
    ② 填写 + 确认               ⇒ **一次** resume，载荷是 {value,label,text}
    ③ resume 之后               ⇒ 助手在同一气泡里继续说话（循环没断）

第 ② 条是本脚本的重点：**直接读浏览器真实发出的 POST body**，
不是读我们的意图、也不是读 mock 的入参。

## 为什么走 send() 而不是直接 mountClarCard

`send()` 是生产入口（含 while(clar||form||cfm) 回填循环）。只有走它，
「选完之后循环有没有继续」才是被验的对象；直接调卡片函数等于绕过了被测逻辑。

## 跑法

    agent/.venv/Scripts/python.exe scripts/_shots_clar_once.py

产物：logs/proof/clar-once-{1-idle,2-picked,3-filled,4-sent,5-plain}.png
前置：只要求本机有 msedge（Playwright channel）；**不需要**后端与连接器在线
（网络全部在浏览器层被 route 拦下，载荷来自生产代码 `entity_clarify.build_clarify_call`）。
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

from aios_ai.tools import entity_clarify as ec          # noqa: E402

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

# 与真机同一句话：既是「发消息」动作（缺内容），又含「开会」（干扰词）
UTTERANCE = "帮我给同事发条消息说下午三点开会"
MEMBERS = [{"name": "刘洋", "userid": "wob_LiuYang", "departments": "成都易构"},
           {"name": "小亮", "userid": "wob_XiaoLiang", "departments": "成都易构"}]

REPLY = "已发给刘洋：「下午三点开会」。"          # resume 之后助手说的话


def clar_frame(options: list[dict], question: str = "要发给哪一位同事？") -> str:
    payload = json.dumps({"question": question, "suggested_options": options},
                         ensure_ascii=False)
    return f"event: need_clarification\ndata: {payload}\n\n"


def done_frame() -> str:
    """resume 之后的那一流：一句回执 + 收尾。"""
    return ("event: message.delta\ndata: " + json.dumps({"text": REPLY}, ensure_ascii=False) + "\n\n"
            "event: message.completed\ndata: " + json.dumps({"usage": {}}, ensure_ascii=False) + "\n\n"
            "event: run.completed\ndata: {}\n\n")


async def start_session(page, options: list[dict]) -> dict:
    """装好拦截 → 跑一遍 send() → 等到澄清卡挂载。

    ⚠️ 路由**不能**在这里卸掉：用户点「确认」之后 send() 才发 resume，
    那时如果没有拦截，请求会打到假域上失败（气泡里出现 fetch 报错），
    于是「回填后循环有没有继续」这件事就永远验不到了。
    卸载放在 `finish_session()`（run 收口之后）。
    """
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
            # 只有第一次是「暂停帧」；resume 走的是 /resume 分支，不会回到这里
            await route.fulfill(status=200, headers=SSE, body=clar_frame(options))
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
    """等 send() 收口（可选）→ 卸拦截。"""
    if wait:
        try:
            await asyncio.wait_for(sess["task"], timeout=8)
        except asyncio.TimeoutError:
            chk("send() 在回填后正常收口", False, "超时：回填后循环没退出")
    elif not sess["task"].done():
        sess["task"].cancel()
    try:
        await page.unroute("**/v1/**")
    except Exception:  # noqa: BLE001
        pass


async def snap(page, path: str) -> None:
    await page.wait_for_timeout(120)
    await page.screenshot(path=path)


def card_state(page):
    return page.evaluate("""() => {
      const c = document.querySelector('.clar-card');
      if(!c) return {ok:false};
      const wrap = c.querySelector('.clar-text-wrap');
      const box  = c.querySelector('.clar-text');
      const ok   = c.querySelector('.clar-ok');
      const lab  = c.querySelector('.clar-text-label');
      return {
        ok: true,
        textShown: !!(wrap && !wrap.hidden),
        hasBox: !!box,
        label: lab ? lab.textContent.trim() : '',
        value: box ? box.value : '',
        ph: box ? (box.getAttribute('placeholder') || '') : '',
        okDisabled: ok ? !!ok.disabled : null,
        selCount: c.querySelectorAll('.clar-opt.sel').length,
        picked: (c.querySelector('.clar-picked') || {}).textContent || ''
      };
    }""")


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    # 选项来自**生产代码**（不是这里手写 JSON）：证明 needs_text 是链路自己挂上的
    call = ec.build_clarify_call(MEMBERS, UTTERANCE)
    options = call["arguments"]["options"]
    chk("生产代码给「发消息」挂上了 needs_text",
        all(o.get("needs_text") is True for o in options),
        str([o.get("text_label") for o in options[:1]]))
    # 干扰项：不带 needs_text 的选项（用来验「切到它 ⇒ 输入框收起并清空」）
    plain_opt = {"value": "wob_plain", "label": "只看通讯录"}

    if not os.path.exists(INDEX):
        chk("user-client/index.html 存在", False, INDEX)
        return _report()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="msedge", headless=True)
        ctx = await browser.new_context(viewport={"width": 390, "height": 844},
                                        device_scale_factor=2, locale="zh-CN")
        page = await ctx.new_page()
        page.on("pageerror", lambda e: print("  [pageerror] " + str(e), flush=True))
        await page.goto("file:///" + urllib.parse.quote(INDEX.replace("\\", "/"), safe="/"),
                        wait_until="domcontentloaded")
        await page.wait_for_function("() => typeof state !== 'undefined' && !!$('msgs')",
                                     timeout=8000)
        await page.wait_for_timeout(1500)
        # file:// 下的相对 URL 不会被 page.route 接管（CORS origin 'null'）⇒ 指到假域
        await page.evaluate("() => { API.base = 'https://shot.local/api'; state.token = ''; }")

        # ---------------------------------------------------- A 正常路径
        r = await start_session(page, options + [plain_opt])
        seen = r["seen"]

        s = await card_state(page)
        chk("① 未选中时输入框是隐藏的（不无端撑高气泡）",
            s["ok"] and s["hasBox"] and s["textShown"] is False, str(s))
        chk("① 未选中时「确认」不可点", s["okDisabled"] is True, str(s.get("okDisabled")))
        await snap(page, os.path.join(OUT, "clar-once-1-idle.png"))

        # 选中带 needs_text 的项
        await page.locator(".clar-opt").first.click()
        s = await card_state(page)
        chk("① 选中项 ⇒ 输入框**当场展开**", s["textShown"] is True, str(s))
        chk("① 输入框标题点明缺什么（要发送的内容）", s["label"].startswith("要发送的内容"),
            s["label"])
        chk("① 必填但为空 ⇒ 「确认」仍不可点（不许留空交上去）",
            s["okDisabled"] is True, str(s.get("okDisabled")))
        chk("① 只有一个选项被选中（单选语义）", s["selCount"] == 1, str(s["selCount"]))
        await snap(page, os.path.join(OUT, "clar-once-2-picked.png"))

        # 填写内容
        await page.locator(".clar-text").fill("下午三点开会")
        s = await card_state(page)
        chk("② 填写后「确认」可点", s["okDisabled"] is False, str(s.get("okDisabled")))
        await snap(page, os.path.join(OUT, "clar-once-3-filled.png"))

        # ---------------------------------------------------- 提交（关键一步）
        await page.locator(".clar-ok").click()
        await finish_session(page, r)          # 等 run 收口 → 卸拦截
        body = seen.get("resume_body") or {}
        ans = body.get("answer")
        chk("② 只发了一次 resume（不是多轮往返）", seen["resume_hits"] == 1,
            f"{seen['resume_hits']} 次")
        chk("② resume 载荷是对象（不再是裸标量）",
            isinstance(ans, dict), str(ans))
        chk("② 载荷里同时有选中值和补充内容",
            isinstance(ans, dict) and ans.get("value") == "wob_LiuYang"
            and ans.get("text") == "下午三点开会",
            str(ans))
        chk("② 载荷带 label（人看的名字，模型不必再猜 userid 是谁）",
            isinstance(ans, dict) and ans.get("label") == "刘洋", str(ans))

        s = await card_state(page)
        chk("③ 卡片落款同时写明「已选择」与「已填写」",
            "已选择" in s["picked"] and "已填写" in s["picked"] and "下午三点开会" in s["picked"],
            s["picked"])
        bubble_tx = await page.evaluate("""() => {
          const bs = document.querySelectorAll('#msgs .bubble');
          return bs.length ? (bs[bs.length-1].innerText || '') : '';
        }""")
        chk("③ 回填后助手在同一气泡里继续说话（循环没断）",
            REPLY in bubble_tx, bubble_tx.replace("\n", " / ")[-80:])
        chk("③ 没有退化成「本轮没有新的内容返回」",
            "本轮没有新的内容返回" not in bubble_tx, "")
        order = await page.evaluate("""() => {
          const bs = document.querySelectorAll('#msgs .bubble');
          const last = bs[bs.length-1];
          const card = last && last.querySelector('.clar-card');
          const tx = last && last.querySelector('.tx');
          if(!card || !tx) return 'missing';
          return (card.compareDocumentPosition(tx) & Node.DOCUMENT_POSITION_FOLLOWING)
                 ? 'card-first' : 'tx-first';
        }""")
        chk("③ 回答落在卡片**之下**（读起来是「选完 → 结果」，不是反问句在上）",
            order == "card-first", order)
        await snap(page, os.path.join(OUT, "clar-once-4-sent.png"))

        # ---------------------------------------------------- B 切到不需要内容的项
        r2 = await start_session(page, options + [plain_opt])
        await page.locator(".clar-opt").first.click()
        await page.locator(".clar-text").fill("这段不该被带走")
        # 切到最后一个（plain）选项
        await page.locator(".clar-opt").last.click()
        s = await card_state(page)
        chk("④ 切到不需要内容的项 ⇒ 输入框收起", s["textShown"] is False, str(s))
        chk("④ 收起时清空，不把上一项的内容带过去",
            s["value"] == "", repr(s["value"]))
        chk("④ 该项不需要内容 ⇒ 「确认」立刻可点", s["okDisabled"] is False,
            str(s.get("okDisabled")))
        await snap(page, os.path.join(OUT, "clar-once-5-plain.png"))
        await page.evaluate("() => { if(typeof cancelClarCard==='function') cancelClarCard(); }")
        await finish_session(page, r2, wait=False)   # 用户放弃：不等回执，直接卸拦截

        await browser.close()

    return _report()


def _report() -> int:
    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    print("截图 → logs/proof/clar-once-*.png")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
