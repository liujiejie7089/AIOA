# -*- coding: utf-8 -*-
"""收口哨兵：连接器「关闭 / 开启」的界面行为（离线 file://，2026-10-31）

用户口径：
    「对话框"+"号关闭连接器后再开启还需要重新认证，你把这一步去掉，
      连接器开启是不需要重新连接。」

本套只验**界面与交互**（打桩，不起后端）；「接口真的没清凭据、闸门真的关了」
由 `scripts/_check_connector_disable_keep_auth.py` 用真后端 + 回库核对负责，两者互补。

判据：
  U1 已连接卡上的按钮是「关闭」+「解除绑定」，**不再有**「断开」
     （「断开」是解绑语义，用户正是把那个按钮当"关闭"用才撞上重新认证）
  U2 点「关闭」⇒ 调的是 API.connectorDisable（**不是** connectorDisconnect）
  U3 点「关闭」⇒ **不弹任何认证层**（无 .notif-mask、且全程没调 connectorDetail）
     —— openConnector() 必先取 detail 才弹凭据/二维码，没调 detail 就等于没有认证步骤
  U4 关闭后该卡：chip=「已关闭」、副标题写明「授权保留…无需重新认证」、出现「开启」按钮
  U5 点「开启」⇒ 调 API.connectorEnable，且**仍不弹层、不取 detail**
  U6 开启后恢复：「已连接」chip + 「关闭」按钮回来
  U7 内置 MCP 提示区分两种未生效：关闭态说「已关闭…开启即可恢复」，
     而不是笼统的「连接器连接后才会对 AI 生效」（后者会让用户以为还要去认证）

用法：python scripts/_check_oa_connector_toggle_ui.py   退出码 = 失败项数。
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
        page.evaluate("() => window.oaGo('skills')")
        page.wait_for_timeout(400)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(300)

        # 打桩：连接器列表 + MCP 列表 + 关闭/开启 + 详情（专用来抓「是否走了认证路径」）
        page.evaluate("""() => {
          window.__calls = {disable:0, enable:0, disconnect:0, detail:0};
          window.__connState = 'CONNECTED';
          function item(){
            var connected = window.__connState === 'CONNECTED';
            return {code:'wecom_cli', name:'企业微信（扫码）', group:'协作与办公', icon:'people',
                    summary:'扫码绑定你自己的企业微信', authMode:'QR', configReady:true,
                    status:window.__connState,
                    accountLabel: '刘洋',
                    connectedAt:'2026-10-31T10:00:00', lastCheckedAt:null, lastError:null};
          }
          API.connectors = function(){ return Promise.resolve([item()]); };
          API.mcpServers = function(){ return Promise.resolve([
            {code:'wecom_cli', name:'企业微信', source:'BUILTIN', connectorCode:'wecom_cli',
             trusted:true, connected: window.__connState === 'CONNECTED',
             toolCount:5, status:'OK', lastError:null, lastProbeAt:null}
          ]); };
          API.connectorDisable = function(){
            window.__calls.disable++;
            window.__connState = 'DISABLED';
            return Promise.resolve({status:'DISABLED'});
          };
          API.connectorEnable = function(){
            window.__calls.enable++;
            window.__connState = 'CONNECTED';
            return Promise.resolve({status:'CONNECTED'});
          };
          API.connectorDisconnect = function(){ window.__calls.disconnect++; return Promise.resolve({}); };
          /* 只要这个被调到，说明走了 openConnector ⇒ 会弹凭据/二维码 ⇒ 就是「要求重新认证」 */
          API.connectorDetail = function(code){
            window.__calls.detail++;
            return Promise.resolve({mode:'QR', name:'企业微信（扫码）', fields:[]});
          };
          window.oaState.connectorsLoaded = false; window.oaState.connectorsErr = null;
          window.oaState.mcpLoaded = false; window.oaState.mcpErr = null;
        }""")
        # 重新点分段触发渲染（走已绑定的处理器 → renderConnectors）
        page.locator('#oaSkillsSeg button[data-seg="skills"]').click()
        page.wait_for_timeout(150)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(500)

        # ---- U1 按钮语义 ----
        acts = page.eval_on_selector_all("#oaConnectorsList [data-act]",
                                        "els => els.map(e => e.getAttribute('data-act') + ':' + e.innerText.trim())")
        has_disable = any(a.startswith("disable:") for a in acts)
        has_enable = any(a.startswith("enable:") for a in acts)
        has_old_disconnect = any("断开" == a.split(":", 1)[1] for a in acts if a.startswith("disconnect:"))
        chk("U1 已连接卡：「关闭」在、旧的「断开」已不在", has_disable and not has_old_disconnect, acts)

        # ---- U2/U3 点关闭 ----
        page.locator('#oaConnectorsList [data-act="disable"]').first.click()
        page.wait_for_timeout(500)
        calls = page.evaluate("() => window.__calls")
        masks = page.locator(".notif-mask").count()
        chk("U2 点「关闭」走 disable 接口（不调 disconnect）",
            calls["disable"] == 1 and calls["disconnect"] == 0, calls)
        chk("U3 点「关闭」全程没有弹认证层、也没取过详情",
            masks == 0 and calls["detail"] == 0, "masks=%d detail=%d" % (masks, calls["detail"]))

        # ---- U4 关闭后的卡面 ----
        chips = page.locator("#oaConnectorsList .conn-card .chip").all_inner_texts()
        txt = page.eval_on_selector("#oaConnectorsList", "el => el.innerText")
        acts2 = page.eval_on_selector_all("#oaConnectorsList [data-act]",
                                         "els => els.map(e => e.getAttribute('data-act'))")
        chk("U4a 关闭后 chip = 已关闭，且出现「开启」按钮",
            "已关闭" in chips and "enable" in acts2, "chips=%s acts=%s" % (chips, acts2))
        chk("U4b 关闭后副标题写明「授权保留…无需重新认证」（用户敢点、也知道不用重连）",
            "授权保留" in txt and "无需重新认证" in txt, txt[:200])
        chk("U7 内置 MCP 提示区分「已关闭」而不是笼统的「连接后会生效」",
            "连接器已关闭" in txt, txt[:260])
        page.screenshot(path=str(PROOF / "connector_toggle_disabled.png"))

        # ---- U5/U6 点开启 ----
        page.locator('#oaConnectorsList [data-act="enable"]').first.click()
        page.wait_for_timeout(500)
        calls2 = page.evaluate("() => window.__calls")
        masks2 = page.locator(".notif-mask").count()
        chips2 = page.locator("#oaConnectorsList .conn-card .chip").all_inner_texts()
        acts3 = page.eval_on_selector_all("#oaConnectorsList [data-act]",
                                         "els => els.map(e => e.getAttribute('data-act'))")
        chk("U5 点「开启」走 enable 接口，且仍不弹层、不取详情",
            calls2["enable"] == 1 and masks2 == 0 and calls2["detail"] == 0, calls2)
        chk("U6 开启后恢复：已连接 chip + 「关闭」按钮回来",
            "已连接" in chips2 and "disable" in acts3, "chips=%s acts=%s" % (chips2, acts3))
        page.screenshot(path=str(PROOF / "connector_toggle_enabled.png"))

        browser.close()

    print("\n" + "=" * 56)
    print("合计 %d 项，通过 %d 项，失败 %d 项" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    return len(FAIL)


if __name__ == "__main__":
    sys.exit(main())
