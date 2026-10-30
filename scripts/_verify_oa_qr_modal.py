# -*- coding: utf-8 -*-
"""用户端 H5 · 企业微信「扫码绑定」弹层哨兵（auth_mode=QR，docs/64）。

要防的是什么
------------
扫码是**三段式**交互（出图 → 人扫码 → 服务端确认绑定），比填表弹层多三个容易写错的点：

  ① **弹层关了还在轮询** —— 用户点取消后 setInterval 没清，接口被持续打，且下次打开会
     叠两个定时器（授权成功时会重复调 /qr-bind）。
  ② **把「扫了码」当「绑定成功」** —— 轮询到 authorized 只说明码被扫了，凭据落盘与连接态
     落库要看 /qr-bind 的结果。前端若自己关掉弹层并 toast「已连接」，就会出现
     「界面已连接、manifest 不给工具」这种最难查的状态。
  ③ **二维码在深色主题下扫不出来** —— 容器必须白底（#fff），不能跟 --surface 走。

判据全部取「真实 DOM 计算值 / 真实 API 调用次数」，不看文案自己说自己成功。

用法：python scripts/_verify_oa_qr_modal.py     退出码 = 失败项数。
（Playwright 装在 agent/.venv 与托管 3.13 里，下面任一都能跑。）
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
INDEX = REPO / "user-client" / "index.html"
PROOF = REPO / "logs" / "proof"

PASS, FAIL = [], []


def chromium_exe():
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


STUB = """() => {
  window.__qr = {statusCalls:0, bindCalls:0, listCalls:0, mode:'pending', bindFail:false};
  window.__connectorsData = [
    {code:'qq_mail', name:'QQ邮箱', group:'邮箱', icon:'mail', summary:'接收/发送邮件',
     authMode:'CREDENTIAL', configReady:true, status:'NEED_AUTH',
     accountLabel:null, connectedAt:null, lastCheckedAt:null, lastError:null},
    {code:'wecom_cli', name:'企业微信（扫码）', group:'协作与办公', icon:'people',
     summary:'扫码绑定你自己的企业微信', authMode:'QR', configReady:true, status:'NEED_AUTH',
     accountLabel:null, connectedAt:null, lastCheckedAt:null, lastError:null}
  ];
  API.connectors = function(){
    window.__qr.listCalls++;
    return Promise.resolve(window.__connectorsData);
  };
  API.connectorDetail = function(code){
    if (code === 'wecom_cli')
      return Promise.resolve({code:'wecom_cli', name:'企业微信（扫码）', mode:'QR',
        summary:'打开手机企业微信扫一扫即可绑定', fields:[], helpText:null, helpUrl:null});
    return Promise.resolve({code:'qq_mail', name:'QQ邮箱', mode:'CREDENTIAL', fields:[]});
  };
  API.connectorQr = function(){
    // 1x1 透明 PNG 的 data URL：只为验证「src 被设成 data:image/png;base64,…」
    return Promise.resolve({qr:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
                            reused:false, expiresIn:300});
  };
  API.connectorQrStatus = function(){
    window.__qr.statusCalls++;
    var ok = (window.__qr.mode === 'auth' && window.__qr.statusCalls >= 2);
    return Promise.resolve({authorized: ok, accountLabel: ok ? '刘洋' : null});
  };
  API.connectorQrBind = function(){
    window.__qr.bindCalls++;
    if (window.__qr.bindFail) return Promise.reject(new Error('企业微信尚未完成扫码授权'));
    return Promise.resolve({status:'CONNECTED', accountLabel:'刘洋', sharedProfile:false});
  };
}"""


def main():
    if not INDEX.exists():
        print("[FAIL] 产物不存在：%s" % INDEX)
        return 1
    html = INDEX.read_text(encoding="utf-8")
    chk("Q0a 产物含二维码弹层实现（openQrModal + 三个 API 方法）",
        "function openQrModal" in html and "connectorQr(" in html
        and "connectorQrStatus(" in html and "connectorQrBind(" in html)
    # 去掉空白再比，避免因为换行/缩进改动而误红；但断言本身必须是「白底 + 固定尺寸」这条实质规则
    flat = "".join(html.split())
    chk("Q0b 产物含 .oa-qr-wrap 白底 + 200px 固定尺寸规则（深色主题也能扫）",
        ".oa-qr-wrap{display:flex" in flat and "background:#fff" in flat
        and ".oa-qr-img{display:block;width:200px;height:200px" in flat)

    with sync_playwright() as pw:
        exe = chromium_exe()
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 420, "height": 900})
        page.route("**/*", lambda r: r.abort() if r.request.resource_type in ("fetch", "xhr") else r.continue_())
        page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        page.evaluate("() => { document.body.classList.add('auth'); window.oaState.mode='oa'; window.oaBoot(); }")
        page.wait_for_timeout(300)
        page.evaluate("() => window.oaGo('skills')")
        page.wait_for_timeout(300)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(200)
        page.evaluate(STUB)
        # 注意：`refreshConnectors` / `openConnector` 这些函数在页面里是**块级作用域**的
        # （第二个 <script> 里裹在闭包内，`typeof refreshConnectors === 'undefined'`），
        # 只有 `API` 与 `oaBoot/oaState` 挂到了 window。所以不能直接调，必须走 UI：
        # 切到「技能」再切回「连接器」，分段按钮的处理器内部会重新拉取并渲染。
        page.evaluate("() => { window.oaState.connectorsLoaded=false; window.oaState.connectorsErr=null; }")
        page.locator('#oaSkillsSeg button[data-seg="skills"]').click()
        page.wait_for_timeout(200)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(500)

        cards = page.locator(".conn-card").count()
        chk("Q1 连接器面板出现 wecom_cli 卡（QR 连接器也走同一张卡）", cards >= 2, "卡数=%s" % cards)

        # ---- 打开弹层：出图 ----
        page.locator('.conn-card button[data-code="wecom_cli"]').first.click()
        page.wait_for_timeout(500)
        img = page.locator(".oa-qr-img")
        chk("Q2 点「连接」弹出二维码弹层并设上 data:image/png 源",
            img.count() == 1 and page.eval_on_selector(".oa-qr-img", "el => el.getAttribute('src')").startswith("data:image/png;base64,"),
            "%s 张图" % img.count())
        bg = page.eval_on_selector(".oa-qr-wrap", "el => getComputedStyle(el).backgroundColor")
        chk("Q3 二维码容器是白底 rgb(255,255,255)（不跟主题变量走）", bg == "rgb(255, 255, 255)", bg)
        page.screenshot(path=str(PROOF / "qr_modal.png"))

        # ---- 轮询：真的在问，且间隔约 2s ----
        page.wait_for_timeout(2300)
        n1 = page.evaluate("() => window.__qr.statusCalls")
        chk("Q4 弹出后开始轮询扫码状态（>=1 次）", n1 >= 1, "statusCalls=%s" % n1)

        # ---- 扫码完成：必须由 /qr-bind 定成败，前端不得自行宣布成功 ----
        page.evaluate("() => { window.__qr.mode='auth'; }")
        page.wait_for_timeout(2600)
        st = page.evaluate("() => window.__qr")
        bind_n = st["bindCalls"]
        closed = page.locator(".oa-qr-wrap").count() == 0
        toast_txt = page.eval_on_selector("#toast", "el => el.textContent") if page.locator("#toast").count() else ""
        chk("Q5 轮询到已授权 → 自动调 /qr-bind（1 次，不重复）", bind_n == 1, "bindCalls=%s" % bind_n)
        chk("Q6 绑定成功后弹层关闭并 toast 出账号名（凭据来自 bind 返回）",
            closed and "刘洋" in (toast_txt or ""), "closed=%s toast=%r" % (closed, toast_txt))

        # ---- 负向：bind 失败必须留在弹层里说原因，且给「重新获取」 ----
        page.evaluate("() => { window.__qr.mode='auth'; window.__qr.statusCalls=1; window.__qr.bindFail=true; }")
        page.locator('.conn-card button[data-code="wecom_cli"]').first.click()
        page.wait_for_timeout(2600)
        err_txt = ""
        if page.locator("#oaConnErr").count():
            err_txt = page.eval_on_selector("#oaConnErr", "el => el.textContent")
        still_open = page.locator(".oa-qr-wrap").count() == 1
        reload_vis = page.eval_on_selector("#oaQrReload", "el => getComputedStyle(el).display") if page.locator("#oaQrReload").count() else "none"
        chk("Q7 [负向] /qr-bind 失败 ⇒ 弹层不关 + 红字原因 + 出现「重新获取」",
            still_open and "扫码授权" in (err_txt or "") and reload_vis != "none",
            "open=%s err=%r reload=%s" % (still_open, err_txt, reload_vis))
        page.screenshot(path=str(PROOF / "qr_modal_bind_fail.png"))

        # ---- 关掉弹层必须停轮询（否则后台一直在打接口） ----
        page.locator('.oa-qr-wrap ~ * [data-dlg-cancel], [data-dlg-cancel]').first.click()
        page.wait_for_timeout(300)
        before = page.evaluate("() => window.__qr.statusCalls")
        page.wait_for_timeout(2600)
        after = page.evaluate("() => window.__qr.statusCalls")
        gone = page.locator(".oa-qr-wrap").count() == 0
        chk("Q8 取消关闭后停止轮询（3s 内 statusCalls 不再增长）",
            gone and after == before, "before=%s after=%s 弹层=%s" % (before, after, gone))

        browser.close()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    return len(FAIL)


if __name__ == "__main__":
    raise SystemExit(main())
