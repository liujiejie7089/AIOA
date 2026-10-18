# -*- coding: utf-8 -*-
"""专家 key 上报 + 专家 emoji 图标 —— 浏览器级回归哨兵（2026-10，expert-h5）。

为什么是浏览器级（而非只 grep 产物）：
  · grep 只能证明产物里**有** `expert_key` 这几个字，证明不了「发对话时请求体真的带上了它、
    且不再带 `expert` 名称字段」。
  · 图标同理：grep 只能证明 ICON_MAP 里有 emoji 键，证明不了「专家目录渲染出来的两条图标
    真的不同（不再是清一色 bot）」。
  本脚本用真实 Chromium 载入**重建后的产物** `user-client/index.html`，桩掉所有网络、驱动真实
  UI 选专家并发送，断言**真实请求体**与**真实渲染出的图标类名**。

网络桩机制（重要，避免伪装 PASS）：
  页面以 `file://` 载入。Chromium 在 file:// 下**禁止**对 `/api/...` 发起真实 fetch
  （scheme not supported，会直接抛 Failed to fetch），因此 `page.route` 拦截不到任何请求——
  同目录 `scripts/_verify_oa_action_popup.py` 正是因为这个原因改用 JS 层 `API.req` 重写的桩。
  本脚本沿用同一事实：在 `add_init_script` 里**覆盖 `window.fetch`**，对所有 `/api/v1/**` 调用
  返回可控响应，并在 `POST /v1/conversations/{id}/runs` 时把 `createRun` 已构造好的**真实请求体**
  原样抓进 `window.__runs`。效果与「page.route 打桩 /api/v1/**」完全等价：所有接口被截、请求体被捕获。
  （不需要任何真实后端；也不起本地 http server。）

用例（每条都有可打印判据）：
  EK1 从专家目录选 doc_writer → 真实 runs 请求体的 context.expert_key === 'doc_writer'。
  EK2 同一次请求体里**不应**再出现 `expert` 名称字段（负向对照，防回退）。
  EK3 选另一位 legal → context.expert_key === 'legal'（证明不是写死）。
  EK4 本地合成的目标（不选目录、直接进默认会话）→ context.expert_key 为 null。
  EK5 图标：专家目录渲染出的两条图标 href 不同（不再全是 bot）。

SKIP 口径：缺 playwright 包 / 未找到已下载的 Chromium / 产物缺失 → 打印原因并 exit 2，绝不伪装 PASS。
用法：python scripts/_verify_h5_expert_key.py
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "user-client" / "index.html"

PASS, FAIL, SKIP = [], [], []


def chromium_exe():
    """返回本机已安装的 Chromium 可执行文件路径；找不到返回 None（交给 playwright 默认解析）。

    理由同 scripts/_verify_oa_action_popup.py：playwright 包版本与 ms-playwright 里已下载的浏览器
    代号常常不一致 ⇒ 直接 launch 会报 Executable doesn't exist。按代号降序挑一个真实存在的。
    """
    root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not root.exists():
        return None
    for pat in ("chromium-*/chrome-win64/chrome.exe",
                "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"):
        hits = sorted(root.glob(pat))
        if hits:
            return str(hits[-1])
    return None


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:500]))


# 在页面脚本之前注入：登录态 + 覆盖 window.fetch 拦截所有 /api/v1/** 并抓参。
INIT_JS = r"""
(function(){
  try { localStorage.setItem('aios_session', JSON.stringify({token:'fake-token',
        user:{username:'zhangsan', nickname:'张三', roles:['ROLE_USER']}})); } catch(e){}
  window.__runs = [];
  window.__convN = 0;
  window.__origFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function(input, init){
    init = init || {};
    var url = (typeof input === 'string') ? input : ((input && input.url) || '');
    var method = (init.method || 'GET').toUpperCase();
    function json(data, status){
      return new Response(JSON.stringify(data), {status: status||200,
        headers:{'content-type':'application/json'}});
    }
    if (url.indexOf('/api/v1/') < 0) {
      return window.__origFetch ? window.__origFetch(input, init)
        : Promise.reject(new Error('no fetch for ' + url));
    }
    // 抓参：真实 POST /conversations/{id}/runs 请求体（createRun 已构造好的 body，含 expert_key）
    var mRuns = url.match(/\/v1\/conversations\/[^/]+\/runs$/);
    if (method === 'POST' && mRuns) {
      try { window.__runs.push(JSON.parse(init.body || '{}')); }
      catch(e){ window.__runs.push({__parseError:String(e), raw:init.body}); }
    }
    // 专家目录：返回两条带 emoji 图标的专家（驱动 EK1/EK3/EK5）
    if (method === 'GET' && /\/v1\/experts$/.test(url)) {
      return Promise.resolve(json({code:0, data:[
        {key:'doc_writer', name:'公文写作专家', icon:'✍️', desc:'公文写作', tags:['公文','写作'],
         recs:['帮我写一份会议通知']},
        {key:'legal', name:'法律咨询专家', icon:'⚖️', desc:'法律咨询', tags:['法律'],
         recs:['劳动合同怎么签']}
      ]}));
    }
    // 新建会话：顺序编号
    if (method === 'POST' && /\/v1\/conversations$/.test(url)) {
      window.__convN++;
      return Promise.resolve(json({code:0, data:{id:'conv-'+window.__convN,
        conversationId:'conv-'+window.__convN}}));
    }
    // 运行事件流：立即以 run.completed 收尾（让 send() 的 await stream 正常结束、busy 复位）
    if (method === 'GET' && /\/v1\/runs\/[^/]+\/events$/.test(url)) {
      var sse = "event: run.completed\ndata: {}\n\n";
      var stream = new ReadableStream({ start: function(c){
        c.enqueue(new TextEncoder().encode(sse)); c.close(); } });
      return Promise.resolve(new Response(stream, {status:200,
        headers:{'content-type':'text/event-stream'}}));
    }
    if (method === 'GET' && /\/v1\/auth\/me$/.test(url)) {
      return Promise.resolve(json({code:0, data:{id:1, username:'zhangsan',
        nickname:'张三', roles:['ROLE_USER']}}));
    }
    return Promise.resolve(json({code:0, data:{}}));
  };
})();
"""


def send_and_capture(page, q):
    """清空抓参缓冲 → 填问题 → 点真实 #sendBtn → 等捕获到 runs 请求体 → 返回该 body。"""
    page.evaluate("window.__runs = [];")
    page.evaluate("go('page-chat')")
    page.wait_for_timeout(150)
    page.fill("#chatInput", q)
    page.wait_for_timeout(150)          # 等 syncClassicInput 把「＋」切成「发送」
    page.click("#sendBtn")
    page.wait_for_function("() => window.__runs && window.__runs.length >= 1", timeout=10000)
    page.wait_for_timeout(500)          # 等 SSE 收尾（busy 复位），避免影响下一次
    return page.evaluate("() => window.__runs[0]")


def main():
    if not INDEX.exists():
        print("[SKIP] 产物不存在：%s（请先运行 user-client/_build_oa.py 重建）" % INDEX)
        SKIP.append("产物缺失")
        return 2

    # playwright 缺失 → 明确 SKIP，不伪装 PASS
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("[SKIP] 缺少 playwright 包：%s" % e)
        SKIP.append("playwright 包缺失")
        return 2

    with sync_playwright() as pw:
        exe = chromium_exe()
        try:
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as e:
            print("[SKIP] 未找到可用的 Chromium（playwright 默认解析与已下载浏览器代号不符）：%s" % e)
            SKIP.append("Chromium 缺失")
            return 2

        page_errors = []
        with browser.new_page(viewport={"width": 420, "height": 900}) as page:
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.add_init_script(INIT_JS)
            page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
            # 等 boot + 专家目录加载（桩已把 /v1/experts 喂成两条）
            page.wait_for_function(
                "() => (typeof state !== 'undefined') && state.experts && state.experts.length >= 2",
                timeout=10000)
            # 经典形态：专家目录 / #chatInput 都在经典形态下；页面默认是 OA，须切回经典
            page.evaluate("window.oaSetMode && window.oaSetMode('classic')")
            page.wait_for_timeout(300)

            # ---------- EK5：专家目录渲染出的图标不是全都一样 ----------
            page.evaluate("go('page-agent'); switchAgentTab('experts');")
            page.wait_for_timeout(400)
            hrefs = page.eval_on_selector_all(
                "#expertList .expert-row .avatar svg use",
                "els => els.map(function(e){ return e.getAttribute('href'); })")
            distinct = len(set(hrefs)) >= 2
            chk("EK5 专家目录两条图标 href 不同（不再全是 #i-bot）",
                distinct and len(hrefs) >= 2,
                "hrefs=%r" % (hrefs,))
            # 顺带：doc_writer 的 emoji ✍️ 应映射到 pen，legal 的 ⚖️ 应映射到 scale
            chk("EK5b doc_writer(✍️)→#i-pen、legal(⚖️)→#i-scale（ICON_MAP emoji 映射生效）",
                "i-pen" in (hrefs[0] or "") and "i-scale" in (hrefs[1] or ""),
                "hrefs=%r" % (hrefs,))

            # ---------- EK1：从目录选 doc_writer ----------
            # 专家面板默认 display:none，直接点 DOM 行需可见性；目录行 onclick 即 startChat(i)，
            # 故等价地用 evaluate 调 startChat(0)（即「从专家目录点进来」的同一条代码路径）。
            page.evaluate("startChat(0)")
            page.wait_for_timeout(200)
            b1 = send_and_capture(page, "请帮我写一份部门会议通知")
            ctx1 = (b1 or {}).get("context", {}) if isinstance(b1, dict) else {}
            chk("EK1 选 doc_writer → 真实 runs 请求体 context.expert_key === 'doc_writer'",
                ctx1.get("expert_key") == "doc_writer", "context=%r" % (ctx1,))

            # ---------- EK2：负向对照，同一次请求体不应再带 expert 名称字段 ----------
            no_expert_top = isinstance(b1, dict) and ("expert" not in b1)
            no_expert_ctx = "expert" not in ctx1
            chk("EK2 同一次请求体不再出现 expert 名称字段（防回退）",
                no_expert_top and no_expert_ctx,
                "top_has_expert=%s ctx_has_expert=%s" % (not no_expert_top, not no_expert_ctx))

            # ---------- EK3：选另一位 legal ----------
            page.evaluate("startChat(1)")
            page.wait_for_timeout(200)
            b3 = send_and_capture(page, "劳动合同到期不续签要赔钱吗")
            ctx3 = (b3 or {}).get("context", {}) if isinstance(b3, dict) else {}
            chk("EK3 选 legal → 真实 runs 请求体 context.expert_key === 'legal'（证明非写死）",
                ctx3.get("expert_key") == "legal", "context=%r" % (ctx3,))

            # ---------- EK4：本地合成目标（不选目录、直接进默认会话）→ null ----------
            page.evaluate("state.chatExpert = {name:'数字员工管家', icon:'bot'}; go('page-chat');")
            page.wait_for_timeout(150)
            b4 = send_and_capture(page, "帮我查一下上季度的考勤")
            ctx4 = (b4 or {}).get("context", {}) if isinstance(b4, dict) else {}
            chk("EK4 本地合成目标（无 key）→ 真实 runs 请求体 context.expert_key 为 null",
                ctx4.get("expert_key") is None, "context=%r" % (ctx4,))

            # 全程 JS 异常监控（回归硬指标）
            chk("R0 全程无未捕获 JS 异常（pageerror）",
                not page_errors, "; ".join(page_errors[:5]))

        browser.close()

    print("\n合计：%d 通过 / %d 失败 / %d 跳过" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
