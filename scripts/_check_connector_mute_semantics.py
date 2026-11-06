# -*- coding: utf-8 -*-
"""收口哨兵：2026-10-31 用户反馈的五条修复（连接器关闭语义 / 录音按钮 / 插件口径 /
chat_id / 滚动渐隐）。

设计原则（铁律 7/12）
    判据必须**回被测对象**取，不与被测对象同源：
      · A 组（静态）：断言源码里**语义相反**的东西**不存在**
        （例如「关闭连接器」分支里不得出现 connectorDisconnect）——
        只断言「某段代码存在」会被同名函数骗过去。
      · B 组（运行时）：用浏览器量**真实盒模型**与**真实 CSS 变量**，
        不读源码里的 CSS 文本（源码写对了但被后面的规则覆盖，源码断言照样绿）。

A 组不需要任何服务；B 组需要 H5 在 5181（缺失则 B 组记 SKIP 并说明原因）。

用法：
    python scripts/_check_connector_mute_semantics.py
    python scripts/_check_connector_mute_semantics.py --static-only
退出码 0 = 全部通过（SKIP 不算失败，但会打印原因）。
"""
from __future__ import annotations

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
H5 = REPO / "user-client" / "index.html"
H5_BASE = "http://127.0.0.1:5181/"

PASS, FAIL, SKIP = [], [], []


def chk(name, ok, detail=""):
    if ok:
        PASS.append(name)
        print("  [PASS] %s" % name)
    else:
        FAIL.append(name)
        print("  [FAIL] %s  <- %s" % (name, str(detail)[:400]))


def skip(name, why):
    SKIP.append(name)
    print("  [SKIP] %s  <- %s" % (name, why))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def block(src: str, start_marker: str, end_marker: str, start_from: int = 0) -> str:
    """截取 start_marker 到 end_marker 之间的源码片段（找不到返回空串）。"""
    i = src.find(start_marker, start_from)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(start_marker))
    if j < 0:
        return src[i:]
    return src[i:j]


# =========================================================== A 组：静态语义

def a_static():
    print("\n=== A 组：静态语义（源码层）===")
    h5 = read(H5)
    contracts = read(REPO / "agent" / "aios_ai" / "contracts.py")
    nodes = read(REPO / "agent" / "aios_ai" / "graph" / "nodes.py")
    create_req = read(REPO / "server" / "aios-chat" / "src" / "main" / "java" / "cn" / "aios" / "chat" / "dto" / "CreateRunRequest.java")
    agent_req = read(REPO / "server" / "aios-chat" / "src" / "main" / "java" / "cn" / "aios" / "chat" / "dto" / "AgentRunRequest.java")
    run_service = read(REPO / "server" / "aios-chat" / "src" / "main" / "java" / "cn" / "aios" / "chat" / "service" / "RunService.java")
    controller = read(REPO / "server" / "aios-chat" / "src" / "main" / "java" / "cn" / "aios" / "chat" / "controller" / "ConversationController.java")
    hub_server = read(REPO / "mcp-hub" / "mcp_hub" / "wecom_cli" / "server.py")
    hub_catalog = read(REPO / "mcp-hub" / "mcp_hub" / "wecom_cli" / "catalog.py")

    # ---------- ① 连接器「关闭 = 本次对话不调用」，不解绑 ----------
    toggle = block(h5, "function oaToggleConnector(", "\n}\n")
    chk("A1 OA 开关的「关闭」分支不得调用 connectorDisconnect（关闭=不调用，不是解绑）",
        "connectorDisconnect" not in toggle,
        "oaToggleConnector 里出现了 connectorDisconnect：关闭仍会解绑")
    chk("A2 OA 开关的「关闭」分支改为置对话级屏蔽标记",
        "oaSetConnectorMuted(code, true)" in toggle or "setConnectorMuted(code, true)" in toggle,
        toggle[:300])
    mute_fn = block(h5, "function muteConnectorForConversation(", "\n}\n")
    chk("A3 经典形态提供「本次对话不调用」入口且只改会话级标记",
        bool(mute_fn) and "setConnectorMuted" in mute_fn and "connectorDisconnect" not in mute_fn,
        mute_fn[:300])
    # 断开（解绑）必须仍在，且带明确说明 —— 不能把「断开」功能也删掉
    dis = block(h5, "function disconnectConnector(", "\n}\n")
    chk("A4 「断开」（真解绑）保留且文案点明会删凭据",
        "connectorDisconnect" in dis and ("解绑" in dis or "重新扫码" in dis),
        dis[:300])
    # 两形态各写一次（经典态无空格、OA 态有空格 ⇒ 不能只数一种写法）
    n_dc = len(re.findall(r"disabled_connectors\s*:\s*mutedConnectorCodes\(\)", h5))
    chk("A5 两形态的 createRun 都下发 disabled_connectors",
        n_dc >= 2,
        "出现次数=%d" % n_dc)
    chk("A6 createRun 把 disabled_connectors 提升到 body 顶层（与 kb_on 同构）",
        re.search(r"if\('disabled_connectors' in ctx\)\s*\{\s*body\.disabled_connectors", h5) is not None,
        "未找到顶层提升逻辑")
    chk("A7 对话级集合两形态共用同一组读写函数（避免语义漂移）",
        "function mutedConnectorCodes()" in h5 and "function setConnectorMuted(" in h5,
        "缺少共用函数")

    # 后端链路
    chk("A8 CreateRunRequest 收 disabled_connectors（顶层）",
        '@JsonProperty("disabled_connectors")' in create_req and "disabledConnectors" in create_req,
        "")
    chk("A9 AgentRunRequest 透传 disabled_connectors",
        '@JsonProperty("disabled_connectors")' in agent_req and "disabledConnectors" in agent_req,
        "")
    chk("A10 RunService 把 disabled_connectors 合并进 context 快照（落库可回读）",
        'context.put("disabled_connectors"' in run_service,
        "未合并进 context")
    chk("A11 RunService 从 context 回读并下发（buildAgentRequest）",
        "setDisabledConnectors(" in run_service,
        "")
    chk("A12 Controller 把请求字段透传给 RunService",
        "getDisabledConnectors()" in controller,
        "")
    # agent 侧
    chk("A13 agent 契约 RunRequest 有 disabled_connectors 字段",
        re.search(r"disabled_connectors:\s*list\[str\]\s*\|\s*None", contracts) is not None,
        "")
    chk("A14 prepare 按连接器过滤 MCP 工具清单",
        "_connector_of_tool_name" in nodes and "kept = [t for t in mcp_tools if" in nodes,
        "")
    chk("A15 tools 节点执行前二次拦截被屏蔽连接器的调用",
        "_blocked_connector_calls" in nodes and "blocked_calls" in nodes,
        "")
    chk("A16 被拦下的调用仍回注 ok=False 的 tool 结果（不得丢 tool 消息）",
        '"ok": False' in nodes and "该连接器在本次对话中已被关闭" in nodes,
        "")
    chk("A17 effective_params 回带 disabledConnectors（可解释「模型为何看不到」）",
        'effective["disabledConnectors"]' in nodes,
        "")

    # ---------- ③ 插件口径 ----------
    chk("A18 分段控件把「插件」改名为「系统工具」",
        'data-seg="plugins" role="tab">系统工具' in h5,
        "未改名")
    chk("A19 系统工具面板说明来源（管理员预置，不是用户添加）",
        "由管理员在管理端预置" in h5,
        "缺少来源说明")
    chk("A20 空态文案改写为系统工具口径",
        "暂无系统工具" in h5,
        "")

    # ---------- ④ chat_id ----------
    chk("A21 wecom_cli recent_group_sessions 返回 chat_id 字段（不是 ref）",
        '"chat_id"' in hub_server,
        "未找到 chat_id")
    chk("A22 chat_id 保留 ref 兼容别名（旧调用不断）",
        re.search(r'"ref"\s*:\s*', hub_server) is not None,
        "缺少兼容别名")
    chk("A23 工具描述写明 chat_id 要原样回传（模型不再自造）",
        "chat_id" in hub_catalog and "原样" in hub_catalog,
        "")

    # ---------- ② 录音按钮尺寸（CSS 层）----------
    cbtn = re.search(r"\.oa \.cbtn\{([^}]*)\}", h5)
    cbtn_body = cbtn.group(1) if cbtn else ""
    chk("A24 .oa .cbtn 固定尺寸不参与 flex 伸缩（flex:0 0 auto）",
        "flex:0 0 auto" in cbtn_body,
        cbtn_body)
    chk("A25 .oa .cbtn 解除通用 .cbtn 的 min-height:36px（否则被顶高）",
        "min-height:0" in cbtn_body.replace(" ", ""),
        cbtn_body)
    tl = re.search(r"\.oa \.tl-act \.cbtn\{([^}]*)\}", h5)
    tl_body = tl.group(1) if tl else ""
    chk("A26 日程行内文字按钮不被 34px 图标尺寸压扁（width:auto）",
        "width:auto" in tl_body.replace(" ", ""),
        tl_body)

    # ---------- ⑤ 滚动渐隐 ----------
    # ⚠️ `.oa #v-home.chatting .stage` 有**多条**规则（布局的 flex:0 0 auto + 渐隐的 opacity），
    #    只取第一条会拿到布局那条 ⇒ 必须遍历全部，取含 --hd 的那条。
    stage_bodies = re.findall(r"\.oa #v-home\.chatting \.stage\{([^}]*)\}", h5)
    fade_bodies = [b for b in stage_bodies if "var(--hd" in b]
    stage_body = fade_bodies[0] if fade_bodies else ""
    chk("A27 顶部机器人区随滚动渐隐（.stage 接 --hd 插值）",
        bool(fade_bodies) and "opacity" in stage_body,
        "共 %d 条 .stage 规则，命中渐隐的=%d" % (len(stage_bodies), len(fade_bodies)))
    chk("A28 渐隐只作用在聊天态（首页不淡出整屏主体）",
        ".oa #v-home.chatting .stage" in h5,
        "")
    assist = re.search(r"\.oa #v-home \.assist\{([^}]*)\}", h5)
    chk("A29 标题块渐隐机制仍在（--hd 单一真值源）",
        bool(assist) and "var(--hd" in assist.group(1),
        assist.group(1) if assist else "")


# =========================================================== B 组：运行时盒模型

def b_runtime():
    print("\n=== B 组：运行时量测（浏览器真实盒模型 / CSS 变量）===")
    try:
        import httpx
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        skip("B 组（运行时量测）", "缺少依赖：%s" % exc)
        return

    try:
        with httpx.Client(timeout=5, trust_env=False) as c:
            r = c.get(H5_BASE)
        if r.status_code != 200:
            skip("B 组（运行时量测）", "H5 未在线（%s 返回 %s）" % (H5_BASE, r.status_code))
            return
    except Exception as exc:  # noqa: BLE001
        skip("B 组（运行时量测）", "H5 不可达：%s" % exc)
        return

    exe = None
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if root.exists():
        for pat in ("chromium-*/chrome-win64/chrome.exe",
                    "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
            hits = sorted(root.glob(pat))
            if hits:
                exe = str(hits[-1])
                break

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(H5_BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        # 进 OA 形态
        page.evaluate("""()=>{
            document.body.classList.add('auth');
            if(window.oaState) window.oaState.mode='oa';
            if(typeof window.oaBoot==='function') window.oaBoot();
        }""")
        page.wait_for_timeout(800)

        # ---- B1 录音按钮尺寸 ----
        # ⚠️ 目标值是 **44×44**，不是 34×34：`.oa .cbtn` 自己的 34px 会被后面的
        #    「命中区 ≥44px」全局规则（.oa .cbtn{width:44px;height:44px}）覆盖 ⇒
        #    最终渲染就是 44×44。修复前的缺陷是**宽 89px 的椭圆**（被 flex 撑开），
        #    所以判据是「宽高相等且 ≈44」，不是「34×34」。
        mic = page.evaluate("""()=>{
            const el = document.querySelector('#oaMicBtn');
            if(!el) return null;
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            return {w: Math.round(r.width), h: Math.round(r.height),
                    flex: cs.flex, minHeight: cs.minHeight, radius: cs.borderRadius};
        }""")
        if not mic:
            skip("B1 录音按钮盒模型", "未找到 #oaMicBtn")
        else:
            chk("B1 录音按钮是正方形且尺寸正常（≈44×44，不是被撑开的椭圆）",
                abs(mic["w"] - mic["h"]) <= 2 and 40 <= mic["w"] <= 48,
                "实测 %sx%s flex=%s minHeight=%s radius=%s" % (mic["w"], mic["h"], mic["flex"], mic["minHeight"], mic["radius"]))
            chk("B1b 录音按钮计算后的 flex 不参与伸缩（0 0 auto）",
                mic["flex"].replace(" ", "") == "00auto",
                "flex=%s" % mic["flex"])

        # ---- B2 滚动渐隐：--hd 连续插值 + .stage 透明度单调 ----
        # ⚠️ 两个取数要点（否则必假红）：
        #   ① 对话坞是 #oaDockList（.dock-list，overflow-y:auto）；#oaDock 只是外壳。
        #      必须先给 #v-home 加 .chatting（否则 .dock 是 display:none，高度为 0、不可滚）
        #      并塞足量气泡把 scrollHeight 撑起来。
        #   ② --hd 是在 **scroll 事件监听器**里写的（oaSyncDockFade 是 IIFE 内函数，
        #      不挂在 window 上、不能直接调）⇒ scrollTop 赋值后必须**等一拍**再读。
        page.evaluate("""()=>{
            const home = document.querySelector('#v-home');
            home.classList.add('chatting');
            const list = document.querySelector('#oaDockList');
            for(let i=0;i<40;i++){
                const d = document.createElement('div');
                d.className = 'bub';
                d.textContent = '历史消息 ' + i;
                list.appendChild(d);
            }
        }""")
        page.wait_for_timeout(300)

        samples = []
        for top in (0, 30, 60, 90, 120):
            page.evaluate("(t)=>{document.querySelector('#oaDockList').scrollTop=t;}", top)
            page.wait_for_timeout(200)          # 等 scroll 事件 → oaSyncDockFade 写 --hd
            samples.append(page.evaluate("""()=>{
                const home = document.querySelector('#v-home');
                const stage = document.querySelector('#oaStage');
                const l = document.querySelector('#oaDockList');
                const st = getComputedStyle(stage);
                return {top: l.scrollTop,
                        hd: home.style.getPropertyValue('--hd'),
                        opacity: Number(st.opacity),
                        ty: st.transform};
            }"""))

        if not samples:
            skip("B2 滚动渐隐量测", "未找到 #v-home / 对话坞")
        else:
            hds = []
            for s in samples:
                # ⚠️ scrollTop=0 且从未滚动过时 --hd 是**空串**（属性没被写过），
                #    CSS 端靠 var(--hd, 0) 兜底 ⇒ 语义上就是 0，不能判成 None。
                raw = (s["hd"] or "").strip()
                hds.append(float(raw) if raw else 0.0)
            chk("B2 --hd 随 scrollTop 连续插值（0→1，无跳变）",
                all(h is not None for h in hds) and hds[0] == 0.0 and hds[-1] >= 0.99
                and all(hds[i] <= hds[i + 1] for i in range(len(hds) - 1)),
                str(samples))
            ops = [s["opacity"] for s in samples]
            chk("B3 顶部机器人区随滚动淡出（opacity 单调递减到 0）",
                len(ops) >= 3 and ops[0] >= 0.99 and ops[-1] <= 0.02
                and all(ops[i] >= ops[i + 1] - 1e-6 for i in range(len(ops) - 1)),
                str(ops))
            tys = [s["ty"] for s in samples]
            chk("B4 渐隐是位移淡出而非瞬跳（translateY 随 --hd 连续变化）",
                len(set(tys)) >= 3,
                str(tys))

        # ---- B5 ★「关闭连接器」不得发 disconnect 请求（浏览器行为层）----
        # 这是本轮需求的核心判据，且**只能**在浏览器里判：
        # 静态断言只能证明「代码里没有那行」，不能证明「点了开关真的没发请求」。
        # 做法：**新开一个 page**（先拦截再加载，避免与前面的真实请求串味），
        #      拦截 /api/v1/** 全量请求并记录 URL + method，
        #      点「＋」→ 点开关 → 确认 → 断言没有任何 disconnect 请求。
        reqs: list = []

        def _route(route):
            url = route.request.url
            reqs.append((route.request.method, url))
            body = {"code": 0, "message": "ok", "data": []}
            if url.rstrip("/").endswith("/v1/connectors"):
                body["data"] = [{"code": "wecom_cli", "name": "企业微信（扫码）",
                                 "group": "协作与办公", "icon": "people",
                                 "summary": "扫码绑定", "authMode": "QR",
                                 "configReady": True, "status": "CONNECTED"}]
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))

        page2 = browser.new_page(viewport={"width": 390, "height": 844})
        page2.route("**/api/v1/**", _route)
        page2.goto(H5_BASE, wait_until="domcontentloaded")
        page2.wait_for_timeout(1000)
        page2.evaluate("""()=>{
            document.body.classList.add('auth');
            if(window.oaState) window.oaState.mode='oa';
            if(typeof window.oaBoot==='function') window.oaBoot();
        }""")
        page2.wait_for_timeout(600)
        # 点「＋」（真实用户路径：#oaAttachBtn → oaOpenPlusMenu）
        page2.evaluate("""()=>{
            const b = document.querySelector('#oaAttachBtn');
            if(b) b.click();
        }""")
        page2.wait_for_timeout(1200)     # 等 API.connectors() 回来并渲染

        switched = page2.evaluate("""()=>{
            const sw = document.querySelector('#oaPlusConns .pm-sw');
            if(!sw) return null;
            const before = sw.classList.contains('on');
            sw.click();
            return {before: before, code: sw.getAttribute('data-code')};
        }""")
        if not switched:
            skip("B5 关闭连接器不发 disconnect 请求", "未找到 OA 连接器开关（#oaPlusConns .pm-sw）")
        else:
            page2.wait_for_timeout(400)
            # 弹确认框 → 点「不再调用」
            page2.evaluate("""()=>{
                const ok = document.querySelector('[data-dlg-ok]');
                if(ok) ok.click();
            }""")
            page2.wait_for_timeout(900)
            disc = [u for m, u in reqs if "disconnect" in u]
            chk("B5 ★关闭连接器不调 disconnect（不解绑、不删本机凭据）",
                not disc, "捕获到 disconnect 请求：%s" % disc)
            # ⚠️ 关闭时浮层会被收起（oaClosePlusMenu）⇒ 必须**重新打开**才能看到新状态。
            page2.evaluate("""()=>{
                const b = document.querySelector('#oaAttachBtn');
                if(b) b.click();
            }""")
            page2.wait_for_timeout(1200)
            after = page2.evaluate("""()=>{
                const sw = document.querySelector('#oaPlusConns .pm-sw');
                const row = document.querySelector('#oaPlusConns .pm-conn');
                return {on: sw ? sw.classList.contains('on') : null,
                        aria: sw ? sw.getAttribute('aria-label') : null,
                        sub: row ? (row.querySelector('.pm-main span') || {}).textContent : null};
            }""")
            chk("B5b 关闭后开关态为关、且文案点明「授权仍保留」",
                after.get("on") is False and "授权仍保留" in (after.get("sub") or ""),
                str(after))

            # ---- B6 ★重新开启：不得触发授权/扫码流程，且恢复为「开」 ----
            # 用户口径：「关闭只是本次对话不调用，重新开启随时可以（无需重新扫码）」。
            # 判据：再点一次开关 ⇒ 开关态回到「开」；**不出现**授权相关请求
            #      （qr / qr-status / qr-bind / connect/credential）。
            n_before = len(reqs)
            page2.evaluate("""()=>{
                const sw = document.querySelector('#oaPlusConns .pm-sw');
                if(sw) sw.click();
            }""")
            page2.wait_for_timeout(1200)
            # 重新开启不走 askDialog（走 openConnector），若真的触发授权会开二维码弹层
            page2.evaluate("""()=>{
                const ok = document.querySelector('[data-dlg-ok]');
                if(ok) ok.click();
            }""")
            page2.wait_for_timeout(900)
            newly = [u for m, u in reqs[n_before:]]
            auth_like = [u for u in newly
                         if any(k in u for k in ("/qr", "qr-status", "qr-bind",
                                                "connect/credential"))]
            chk("B6 ★重新开启不触发扫码/授权流程（无需重新扫码）",
                not auth_like, "重新开启时发起了授权请求：%s" % auth_like)
            page2.evaluate("""()=>{
                const b = document.querySelector('#oaAttachBtn');
                if(b) b.click();
            }""")
            page2.wait_for_timeout(1200)
            reopened = page2.evaluate("""()=>{
                const sw = document.querySelector('#oaPlusConns .pm-sw');
                const row = document.querySelector('#oaPlusConns .pm-conn');
                return {on: sw ? sw.classList.contains('on') : null,
                        sub: row ? (row.querySelector('.pm-main span') || {}).textContent : null};
            }""")
            chk("B6b 重新开启后开关态恢复为「开」且显示已连接",
                reopened.get("on") is True and "已连接" in (reopened.get("sub") or ""),
                str(reopened))
            page2.close()

        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static-only", action="store_true", help="只跑 A 组（不需要 H5 在线）")
    args = ap.parse_args()

    a_static()
    if not args.static_only:
        b_runtime()

    print("\n合计：%d 通过 / %d 失败 / %d 跳过" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败项：" + "; ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
