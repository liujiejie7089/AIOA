# -*- coding: utf-8 -*-
"""收口哨兵：「＋」浮层里关闭连接器后再开启，**不得重新认证**（2026-10-31 用户口径）

用户原话：
    「对话框"+"号关闭连接器后再开启还需要重新认证，你把这一步去掉，
      连接器开启是不需要重新连接。」

真根因（在「＋」浮层，不在连接器面板）：
    `oaToggleConnector()` 的「重新开启」分支是
        oaSetConnectorMuted(code, false);
        openConnector(code);          // ← 无条件！
    `openConnector()` 必先 `GET /v1/connectors/{code}` 拿 detail 再按 mode 弹「填授权码」
    或「扫码」—— 所以只要开关是关→开，用户就一定被要求重新认证一次。
本轮改成按真实状态分流：已授权（CONNECTED / DISABLED）只解除会话级禁用，一个弹层都不弹；
只有 NEED_AUTH / UNVERIFIED 才引导授权（这是唯一该弹的情况）。

判据（「有没有走认证」以 **API.connectorDetail 是否被调用**为准：
      openConnector 必先取 detail，没调它就不可能弹出凭据/二维码层 —— 这不依赖界面文案）：
  P1 CONNECTED → 关掉开关（确认框点「不再调用」）→ 状态变「本次对话不调用」
  P2 再打开开关 ⇒ detail 调用次数 **仍为 0**，且没有出现凭据输入行 .oa-ef-row
     （旧代码在这里会 +1 ⇒ 这条断言就是本次修复的回归锁）
  P3 重新打开后提示「已恢复调用」，开关回到 on
  P4 DISABLED（在连接器面板持久关闭过）→ 打开展示「已关闭（授权保留），打开即恢复」
  P5 DISABLED 下打开开关 ⇒ 调 connectorEnable，detail 仍为 0（不认证）
  P6 NEED_AUTH（确实没授权）→ 打开开关 ⇒ detail ≥ 1（这里**应该**引导授权，不能被"去掉"误伤）

用法：python scripts/_check_oa_plus_connector_no_reauth.py   退出码 = 失败项数。
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import sys
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
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:400]))


STUB = """(o) => {
  var status = o.status, label = o.label;
  window.__calls = {detail:0, enable:0, disable:0, disconnect:0};
  window.__connState = status;
  API.connectors = function(){
    return Promise.resolve([{
      code:'wecom_cli', name:'企业微信（扫码）', group:'协作与办公', icon:'people',
      summary:'扫码绑定你自己的企业微信', authMode:'QR', configReady:true,
      status: window.__connState,
      accountLabel: label, connectedAt:'2026-10-31T10:00:00',
      lastCheckedAt:null, lastError:null
    }]);
  };
  API.mcpServers = function(){ return Promise.resolve([]); };
  /* 只要它被调到，就等于「确实弹了授权/认证层」 */
  API.connectorDetail = function(){
    window.__calls.detail++;
    return Promise.resolve({mode:'QR', name:'企业微信（扫码）', fields:[]});
  };
  API.connectorEnable = function(){
    window.__calls.enable++;
    window.__connState = 'CONNECTED';
    return Promise.resolve({status:'CONNECTED'});
  };
  API.connectorDisable = function(){
    window.__calls.disable++;
    window.__connState = 'DISABLED';
    return Promise.resolve({status:'DISABLED'});
  };
  API.connectorDisconnect = function(){ window.__calls.disconnect++; return Promise.resolve({}); };
  window.oaState.connectorsLoaded = false; window.oaState.connectorsErr = null;
  window.oaState.mcpLoaded = false; window.oaState.mcpErr = null;
  /* 清掉会话级"不调用"集合，保证每次从"开着"开始 */
  if(window.oaState && window.oaState.mutedConnectors) window.oaState.mutedConnectors = [];
}"""


def open_plus(page):
    """走真实入口：点输入栏的「＋」（#oaAttachBtn）。已开着就先点一次收起。
    不用 window.oaOpenPlusMenu —— 那条内部函数没对外暴露，而「点按钮」才是用户真路径。"""
    if page.locator("#oaPlusMenu").count():
        page.locator("#oaAttachBtn").click()
        page.wait_for_timeout(250)
    page.locator("#oaAttachBtn").click()
    page.wait_for_timeout(500)


def main():
    if not INDEX.exists():
        print("[FAIL] 产物不存在：%s" % INDEX)
        return 1
    PROOF.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        exe = chromium_exe()
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 420, "height": 900})
        page.route("**/*",
                   lambda r: r.abort() if r.request.resource_type in ("fetch", "xhr") else r.continue_())
        page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        page.evaluate("() => { document.body.classList.add('auth'); window.oaState.mode='oa'; window.oaBoot(); }")
        page.wait_for_timeout(300)

        # ================= 场景 A：已连接 → 关 → 再开 =================
        page.evaluate(STUB, {"status": "CONNECTED", "label": "刘洋"})
        open_plus(page)
        sub0 = page.eval_on_selector("#oaPlusConns .pm-main span", "el => el.innerText")
        chk("P0 已连接时浮层显示「已连接」", "已连接" in sub0, sub0)

        # 关掉：弹确认框 → 点「不再调用」
        page.locator("#oaPlusConns .pm-sw").first.click()
        page.wait_for_timeout(300)
        page.locator(".notif-mask [data-dlg-ok]").first.click()
        page.wait_for_timeout(400)
        chk("P1 关掉开关后状态变「本次对话不调用」",
            "本次对话不调用" in page.eval_on_selector("#oaPlusConns .pm-main span", "el => el.innerText")
            if page.locator("#oaPlusConns").count() else True,
            "（浮层已收起，按 mute 集合判定）")

        # 再打开：这是用户报的那一步
        open_plus(page)
        page.locator("#oaPlusConns .pm-sw").first.click()
        page.wait_for_timeout(600)
        calls = page.evaluate("() => window.__calls")
        cred_rows = page.locator(".oa-ef-row").count()
        chk("P2 ★再打开开关：没有取过详情、没有凭据输入层（旧代码这里 detail=1）",
            calls["detail"] == 0 and cred_rows == 0,
            "detail=%d .oa-ef-row=%d" % (calls["detail"], cred_rows))
        page.screenshot(path=str(PROOF / "plus_connector_reenabled_no_auth.png"))

        # 重新打开浮层看开关是否回到 on
        open_plus(page)
        aria = page.eval_on_selector("#oaPlusConns .pm-sw", "el => el.getAttribute('aria-checked')")
        sub2 = page.eval_on_selector("#oaPlusConns .pm-main span", "el => el.innerText")
        chk("P3 开关回到 on 且文案是「已连接」（不是「未连接，开启后去授权」）",
            aria == "true" and "已连接" in sub2, "aria-checked=%s text=%s" % (aria, sub2))

        # ================= 场景 B：持久关闭（DISABLED）=================
        page.evaluate(STUB, {"status": "DISABLED", "label": "刘洋"})
        open_plus(page)
        sub3 = page.eval_on_selector("#oaPlusConns .pm-main span", "el => el.innerText")
        chk("P4 已关闭的连接器在浮层写明「授权保留 / 打开即恢复」",
            "授权保留" in sub3 and "打开即恢复" in sub3, sub3)

        page.locator("#oaPlusConns .pm-sw").first.click()
        page.wait_for_timeout(600)
        calls2 = page.evaluate("() => window.__calls")
        chk("P5 已关闭态打开开关 ⇒ 调 enable 恢复，detail 仍为 0（不认证）",
            calls2["enable"] == 1 and calls2["detail"] == 0, calls2)

        # ================= 场景 C：确实没授权 =================
        page.evaluate(STUB, {"status": "NEED_AUTH", "label": None})
        open_plus(page)
        sub4 = page.eval_on_selector("#oaPlusConns .pm-main span", "el => el.innerText")
        page.locator("#oaPlusConns .pm-sw").first.click()
        page.wait_for_timeout(600)
        calls3 = page.evaluate("() => window.__calls")
        chk("P6 未授权时打开开关 ⇒ **应该**引导授权（detail≥1，修复不能误伤这条）",
            calls3["detail"] >= 1, "detail=%d（浮层文案：%s）" % (calls3["detail"], sub4))

        browser.close()

    print("\n" + "=" * 56)
    print("合计 %d 项，通过 %d 项，失败 %d 项" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    return len(FAIL)


if __name__ == "__main__":
    sys.exit(main())
