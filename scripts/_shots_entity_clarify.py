# -*- coding: utf-8 -*-
"""模糊实体澄清卡的**截图证据**（Playwright + 真实连接器数据）。

## 这个脚本证明什么

不是「我们写了提示词」，而是这条链**真的通**：

    entity_clarify.prefetch()  ──►  真实 MCP 工具（企微通讯录 / QQ 邮箱收发件人）
            │                                   │
            └──── 真实候选 ──► build_options ────┘
                                    │
                          真实 H5（user-client/index.html）
                                    │
                            need_clarification 帧 ──► 按钮

三处都走**生产代码**，只把「模型那一轮只回了句反问」替换成直接投一帧澄清事件 ——
因为要验的是「候选从哪来 + 界面长什么样」，不是再验一遍模型。

## 为什么是「连接器无关」

脚本不认识 `wecom_cli` / `qq_mail`：它只按**工具短名**发现人源（见
`agent/aios_ai/tools/entity_clarify.py`），所以同一份截图脚本对两个连接器都成立。
企微走 `contact_search`（value=userid），QQ 邮箱走 `list_messages`
（value=邮箱，且「已发送的收件人」优先于「收件箱的发件人」）。

## 前置

Java :8080 与 mcp-hub :8099 在线；企微扫码态属于 zhangsan、QQ 邮箱授权态属于 admin
（脚本内各自登录，不共用 token）。缺任何一个连接器就**只跳过那一个场景**并明确打印，
不伪造数据。

跑法：
  agent/.venv/Scripts/python.exe scripts/_shots_entity_clarify.py
产物：logs/proof/entity-clarify-{wecom,mail,empty,many}.png
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse

import httpx
from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "agent"))

from aios_ai.tools import entity_clarify as ec          # noqa: E402

INDEX = os.path.join(REPO, "user-client", "index.html")
OUT = os.path.join(REPO, "logs", "proof")
BASE = os.environ.get("AIOS_BASE", "http://127.0.0.1:8080")
HUB = os.environ.get("AIOS_HUB", "http://127.0.0.1:8099")

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


# --------------------------------------------------------------- 真实连接器访问

async def login(user: str, pwd: str) -> str:
    async with httpx.AsyncClient(timeout=20, trust_env=False) as c:
        r = await c.post(f"{BASE}/api/v1/auth/login", json={"username": user, "password": pwd})
        return (r.json().get("data") or {}).get("accessToken") or ""


class _Outcome:
    def __init__(self, ok: bool, data="", error=""):
        self.ok, self.data, self.error = ok, data, error


class _McpToolClient:
    """`ToolClient.invoke` 的最小等价物：把 mcp__<code>__<short> 打到 hub 的真实工具。

    只做名字映射与 TextContent 归一，**不做任何数据加工** —— 加工全在
    `entity_clarify.prefetch()` 里（那才是被测代码）。
    """

    def __init__(self, session, code: str):
        self._s, self._code = session, code

    async def invoke(self, name: str, args: dict | None = None) -> _Outcome:
        short = name.split("__")[-1]
        try:
            res = await self._s.call_tool(short, args or {})
        except Exception as exc:  # noqa: BLE001
            return _Outcome(False, error=str(exc)[:200])
        text = "\n".join(getattr(c, "text", "") for c in res.content)
        return _Outcome(not res.isError, data=text, error="" if not res.isError else text)


async def real_candidates(code: str, token: str, user: str) -> tuple[list[dict], str, list[str]]:
    """跑一遍生产 prefetch，返回 (候选, kind, 用到的工具名)。"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(f"{HUB}/mcp/{code}",
                                     headers={"Authorization": "Bearer " + token}) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            listed = await s.list_tools()
            # 与 agent 侧同构：mcp__<serverCode>__<shortName>
            tools = [{"type": "function",
                      "function": {"name": f"mcp__{code}__{t.name}"}} for t in listed.tools]
            client = _McpToolClient(s, code)
            src = ec.find_people_source(tools)
            members, kind = await ec.prefetch(client, tools)
            used = sorted({t.split("__")[-1] for t in (src and [src["tool"]] or [])})
            return members, kind, used


# --------------------------------------------------------------- H5 驱动

SSE = {"content-type": "text/event-stream",
       "access-control-allow-origin": "*",
       "cache-control": "no-cache"}
JSON = {"content-type": "application/json", "access-control-allow-origin": "*"}


def clar_frame(question: str, options: list[dict]) -> str:
    payload = json.dumps({"question": question, "suggested_options": options}, ensure_ascii=False)
    return f"event: need_clarification\ndata: {payload}\n\n"


async def shoot(page, frame: str, path: str) -> dict:
    """投一帧澄清事件 → 等卡片挂载 → 量取 + 截图整条气泡 → 收掉卡片（解锁 send）。

    顺序是有讲究的：`send()` 在 `mountClarCard()` 处 **await 用户选择**，
    所以卡片挂载之后 `send()` 还没返回。必须先截图、再 `cancelClarCard()` 把它
    以 null 收掉，否则这个 pending 的 send 会一直挂在那儿，下一场景的 send 被
    「还在忙」挡住（表现为第二张卡永远不出现）。
    """

    async def handler(route, request):
        url = request.url
        if url.endswith("/events"):
            await route.fulfill(status=200, headers=SSE, body=frame)
            return
        if "/v1/conversations" in url and url.rstrip("/").endswith("conversations"):
            await route.fulfill(status=200, headers=JSON, body='{"code":0,"data":{"id":"c1"}}')
            return
        await route.fulfill(status=200, headers=JSON, body='{"code":0,"data":{"id":"r1"}}')

    await page.route("**/v1/**", handler)
    try:
        await page.evaluate("""() => {
          state.busy = false;
          state.conversationId = 'c1';
          state.quotaInfo = null;
          state.controller = null;
          clarPendingResolve = null;
          const box = $('msgs'); if (box) box.innerHTML = '';
        }""")
        await page.evaluate("() => { $('chatInput').value = '帮我给同事发条消息说下午三点开会'; }")
        task = asyncio.ensure_future(page.evaluate("() => send()"))
        try:
            await page.wait_for_selector(".clar-card", timeout=8000)
        except Exception:
            if not task.done():
                task.cancel()
            return {"ok": False, "reason": "卡片没渲染出来"}

        # 挂载后**立刻**量取并克隆快照（同一个 evaluate 内完成，不给重渲染留窗口）：
        # `send()` 在卡片挂载后仍会继续跑收口逻辑，气泡随时可能被整体重绘；
        # 克隆到固定定位的容器里，截的就是「用户这一刻看到的」这一帧，且再也不受打扰。
        info = await page.evaluate("""() => {
          const card = document.querySelector('.clar-card');
          if (!card) return {ok:false, reason:'卡片已消失'};
          const opts = Array.from(card.querySelectorAll('.clar-opt'));
          const wrap = card.querySelector('.clar-opts');
          const measure = {
            ok: true,
            many: card.classList.contains('many'),
            free: !!card.querySelector('.clar-free'),
            question: (card.querySelector('.clar-q') || {}).textContent || '',
            labels: opts.map(function(o){ return (o.textContent||'').trim(); }),
            scrollable: wrap ? (wrap.scrollHeight > wrap.clientHeight + 1) : false,
            cardH: Math.round(card.getBoundingClientRect().height),
            cardW: Math.round(card.getBoundingClientRect().width)
          };
          const msgs = document.querySelectorAll('#msgs .msg');
          const picks = Array.prototype.slice.call(msgs, -2);   // 用户提问 + 助手卡片
          const old = document.getElementById('proofHost');
          if (old) old.remove();
          const host = document.createElement('div');
          host.id = 'proofHost';
          host.style.cssText = 'position:fixed;left:0;top:0;width:390px;z-index:99999;'
                             + 'background:#fff;padding:14px 12px;'
                             + 'animation:none!important;transition:none!important';
          picks.forEach(function(m){ host.appendChild(m.cloneNode(true)); });
          document.body.appendChild(host);
          return measure;
        }""")

        await page.locator("#proofHost").screenshot(path=path)
        await page.evaluate("() => { const h=document.getElementById('proofHost'); if(h) h.remove(); }")

        # 收掉未决卡片（等价于用户放弃），把 send() 放出来
        await page.evaluate("() => { if(typeof cancelClarCard==='function') cancelClarCard(); }")
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:  # noqa: BLE001 —— send 的收口与本脚本无关
            if not task.done():
                task.cancel()
        return info
    finally:
        await page.unroute("**/v1/**")


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)

    # ---- 真实候选：两个连接器各走一遍 ----
    print("\n=== 真实候选（走生产 prefetch + 真实 MCP 工具）===")
    wecom_members: list[dict] = []
    mail_members: list[dict] = []
    try:
        t = await login("zhangsan", "User@123")
        wecom_members, kind, used = await real_candidates("wecom_cli", t, "zhangsan")
        print(f"[wecom_cli] kind={kind} 候选={len(wecom_members)} 工具={used}")
        for m in wecom_members:
            print("   ·", ec.build_options([m])[0]["label"] if ec.build_options([m]) else m)
    except Exception as exc:  # noqa: BLE001
        print(f"[wecom_cli] 取候选失败（跳过该场景）：{exc}")

    try:
        t = await login("admin", "Admin@123")
        mail_members, kind, used = await real_candidates("qq_mail", t, "admin")
        print(f"[qq_mail]  kind={kind} 候选={len(mail_members)} 工具={used}")
        for m in mail_members:
            print("   ·", ec.build_options([m])[0]["label"] if ec.build_options([m]) else m)
    except Exception as exc:  # noqa: BLE001
        print(f"[qq_mail] 取候选失败（跳过该场景）：{exc}")

    wecom_opts = ec.build_options(wecom_members)
    mail_opts = ec.build_options(mail_members)
    chk("企微候选来自真实通讯录工具", len(wecom_opts) >= 1, f"{len(wecom_opts)} 个")
    chk("企微候选的 value 是 userid",
        all(o["value"].startswith("wob") or len(o["value"]) > 20 for o in wecom_opts),
        str([o["value"][:12] for o in wecom_opts]))
    chk("QQ 邮箱候选来自真实邮件（收发件人）", len(mail_opts) >= 1, f"{len(mail_opts)} 个")
    chk("邮箱候选的 value 是邮箱地址",
        all("@" in o["value"] for o in mail_opts), str([o["value"] for o in mail_opts][:3]))

    # ---- 渲染 + 截图 ----
    print("\n=== H5 渲染截图 ===")
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
        # 必须等 boot() 跑完，否则它初始化时会盖掉我们设的 state
        await page.wait_for_function("() => typeof state !== 'undefined' && !!$('msgs')",
                                     timeout=8000)
        await page.wait_for_timeout(1500)
        # ★ 关键：file:// 下的 `file:///api/v1/...` **无法被 page.route 拦截**
        #   （Playwright 不代理 file 协议请求），表现是 CORS 报错 + send() 直接进 catch，
        #   卡片永远不出现。把 base 指到一个假域，请求才会真的走网络栈、被 page.route 接管。
        await page.evaluate("() => { API.base = 'https://shot.local'; state.token = ''; }")

        if wecom_opts:
            f = "entity-clarify-wecom.png"
            info = await shoot(page, clar_frame("要发给哪一位同事？", wecom_opts), os.path.join(OUT, f))
            chk("企微：澄清卡渲染出真按钮", bool(info.get("ok")) and len(info["labels"]) == len(wecom_opts),
                str(info.get("labels")))
            print("      截图 →", os.path.join("logs", "proof", f))

        if mail_opts:
            f = "entity-clarify-mail.png"
            info = await shoot(page, clar_frame("要发给哪一位？", mail_opts), os.path.join(OUT, f))
            chk("QQ 邮箱：澄清卡渲染出真按钮",
                bool(info.get("ok")) and len(info["labels"]) == len(mail_opts), str(info.get("labels")))
            print("      截图 →", os.path.join("logs", "proof", f))

        # 退化：一个候选都没有 ⇒ 输入框（而不是死胡同）
        f = "entity-clarify-empty.png"
        info = await shoot(page, clar_frame("要发给哪位同事？请输入姓名或工号", []),
                           os.path.join(OUT, f))
        chk("空候选：渲染输入框而非死胡同", bool(info.get("free")), str(info))
        print("      截图 →", os.path.join("logs", "proof", f))

        # 10 个候选：靠内滚动 + 底部渐隐（不把气泡顶出一屏）
        many = [{"value": f"wob{i}", "label": f"同名人{i}（研发部 / 工程师）"} for i in range(10)]
        f = "entity-clarify-many.png"
        info = await shoot(page, clar_frame("要发给哪一位同事？", many), os.path.join(OUT, f))
        chk("10 个候选：容器内滚动 + .many 渐隐",
            bool(info.get("many")) and bool(info.get("scrollable")), str(info))
        print("      截图 →", os.path.join("logs", "proof", f))

        await browser.close()

    return _report()


def _report() -> int:
    print("\n" + "=" * 60)
    if fails:
        print(f"FAILED  {len(fails)} 项 — " + "；".join(fails))
        return len(fails)
    print(f"ALL PASS  {oks} 项")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
