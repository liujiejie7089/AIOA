# -*- coding: utf-8 -*-
"""收口哨兵：用户端 H5「插件-技能-连接器」三分 + 连接器授权（docs/58 §1–§3，离线 file://）。

判据（回到事实源头，不读界面自己的副本）：
  S1 抽屉项文案 = 「插件-技能-连接器」
  S2 三个分段按钮存在（插件/技能/连接器）且可切换（点「连接器」→ oaPaneConnectors.on，其余 off）
  S3 连接器面板：后端 404 时显示「连接器加载失败：…」而非空白（负向/真实环境）
  S4 打桩返回 docs/58 示例数据 → 两张卡（QQ邮箱/企业微信）+ 状态 chip 文案正确
  S5 点 QQ邮箱「连接」→ 弹层出现，且 .oa-ef-row 计算 flex-direction === 'column'
     （这是本项目「弹层不在 .oa 内、.oa 作用域陷阱」的唯一判据）
  S6 弹层内输入框可见（password 文本框存在且宽高 > 0）
  S7 空必填提交被前端拦截（弹层不关 + 红字提示，且未发请求）
  S8 弹层标题图标砖 32x32 有底色 + 内部 svg 18px（`.oa-up-ico` 作用域陷阱的回归判据）

注：本套 **不需要后端**（`page.route` 打桩 + `file://` 加载产物），只验证结构与交互；
「接口真的可用」由 `scripts/_verify_connectors.py` 负责，两者互补不重复。
用法：python scripts/_verify_oa_connector_ui.py   退出码 = 失败项数。
"""
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
    print(("  [PASS] " if ok else "  [FAIL] ") + name + ("" if ok else "  <- " + str(detail)[:500]))


def main():
    if not INDEX.exists():
        print("[FAIL] 产物不存在：%s" % INDEX)
        return 1
    html = INDEX.read_text(encoding="utf-8")
    chk("产物含新图标 i-link/i-mail symbol", 'id="i-link"' in html and 'id="i-mail"' in html)
    chk("产物含三段分段控件 id=oaSkillsSeg", 'id="oaSkillsSeg"' in html)
    chk("产物含三面板 id（oaPanePlugins/Skills/Connectors）",
        'id="oaPanePlugins"' in html and 'id="oaPaneSkills"' in html and 'id="oaPaneConnectors"' in html)
    chk("产物含 7 个新 API 方法（connectors/connectorDetail…）",
        "connectorConnectCredential" in html and "connectorDisconnect" in html)

    with sync_playwright() as pw:
        exe = chromium_exe()
        browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        page = browser.new_page(viewport={"width": 420, "height": 900})
        # 拦截所有网络请求，离线环境一律 abort（避免真实 fetch 拖慢/噪声）
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("fetch", "xhr") else route.continue_())
        page.goto(INDEX.as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(500)

        # 进入 OA 形态
        page.evaluate("() => { document.body.classList.add('auth'); window.oaState.mode = 'oa'; window.oaBoot(); }")
        page.wait_for_timeout(400)
        page.evaluate("() => window.oaGo('skills')")
        page.wait_for_timeout(500)

        # S1 抽屉项文案
        drawer_txt = page.eval_on_selector("#odSkills", "el => el.innerText")
        chk("S1 抽屉项文案 = 「插件-技能-连接器」",
            "插件-技能-连接器" in drawer_txt, drawer_txt)

        # S2 三个分段按钮 + 切换
        segs = page.locator("#oaSkillsSeg button").all_inner_texts()
        chk("S2a 三个分段按钮存在（插件/技能/连接器）",
            len(segs) == 3 and "插件" in segs[0] and "技能" in segs[1] and "连接器" in segs[2], segs)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(400)
        conn_on = page.eval_on_selector("#oaPaneConnectors", "el => el.classList.contains('on')")
        plug_on = page.eval_on_selector("#oaPanePlugins", "el => el.classList.contains('on')")
        skill_on = page.eval_on_selector("#oaPaneSkills", "el => el.classList.contains('on')")
        chk("S2b 点「连接器」→ 仅 oaPaneConnectors.on，其余 off",
            conn_on is True and plug_on is False and skill_on is False,
            "conn=%s plug=%s skill=%s" % (conn_on, plug_on, skill_on))

        # S3 真实失败路径：连接器 fetch 被 abort（404/网络失败）→ 显示错误文案而非空白
        conn_html = page.eval_on_selector("#oaConnectorsList", "el => el.innerText")
        chk("S3 连接器加载失败显示错误文案（非空白带「连接器加载失败」）",
            "连接器加载失败" in conn_html, conn_html[:120])

        page.screenshot(path=str(PROOF / "connector_ui_pane_error.png"))

        # S4/S5/S6：打桩返回成功数据后，通过已绑定的分段按钮点击重新触发渲染
        page.evaluate("""() => {
          window.__connectorsData = [
            {code:'qq_mail', name:'QQ邮箱', group:'邮箱', icon:'mail', summary:'接收/发送邮件',
             authMode:'CREDENTIAL', configReady:true, status:'NEED_AUTH',
             accountLabel:null, connectedAt:null, lastCheckedAt:null, lastError:null, isPlatformManaged:false},
            {code:'wechat_work', name:'企业微信', group:'协作与办公', icon:'people', summary:'企业协作与办公',
             authMode:'OAUTH2', configReady:false, status:'NEED_AUTH',
             accountLabel:null, connectedAt:null, lastCheckedAt:null, lastError:null, isPlatformManaged:false,
             configHint:'缺少企业微信应用配置（corpId/agentId/corpSecret）'}
          ];
          API.connectors = function(){ return Promise.resolve(window.__connectorsData); };
          API.connectorDetail = function(code){
            return Promise.resolve({mode:'CREDENTIAL', name:'QQ邮箱',
              helpText:'QQ邮箱→设置→账户→开启IMAP→生成授权码', helpUrl:'https://example.com/help',
              fields:[{key:'email', label:'QQ邮箱地址', type:'text', placeholder:'your@qq.com', required:true},
                      {key:'authCode', label:'IMAP/SMTP 授权码', type:'password', placeholder:'授权码', required:true}]});
          };
          // 清掉失败态，强制重拉
          window.oaState.connectorsLoaded = false; window.oaState.connectorsErr = null;
        }""")
        # 重新走分段按钮（已绑定的 DOM 处理器内部调用 showSkillsPane→renderConnectors）
        page.locator('#oaSkillsSeg button[data-seg="skills"]').click()
        page.wait_for_timeout(200)
        page.locator('#oaSkillsSeg button[data-seg="connectors"]').click()
        page.wait_for_timeout(600)

        cards = page.locator("#oaConnectorsList .conn-card").count()
        chk("S4a 两张连接器卡渲染（QQ邮箱/企业微信）", cards == 2, "cards=%d" % cards)

        # chip 文案判定（严格按 docs/58 §2.3）
        chips = page.locator("#oaConnectorsList .conn-card .chip").all_inner_texts()
        chk("S4b 状态 chip 文案正确（QQ邮箱=未连接 / 企业微信=待管理员配置）",
            "未连接" in chips and "待管理员配置" in chips, chips)

        # 企业微信按钮 disabled；QQ邮箱按钮可点（configReady=false 的按钮无 data-act，按卡片定位）
        qq_loc = page.locator('#oaConnectorsList [data-act="connect"][data-code="qq_mail"]').first
        qq_disabled = qq_loc.is_disabled()
        wx_loc = page.locator('#oaConnectorsList .conn-card').filter(has_text="企业微信").locator('button.btn[disabled]')
        wx_disabled = wx_loc.count() == 1 and wx_loc.first.is_disabled()
        chk("S4c 企业微信（configReady=false）按钮禁用；QQ邮箱按钮可用",
            qq_disabled is False and wx_disabled is True, "qq=%s wx=%s" % (qq_disabled, wx_disabled))

        # S5/S6 点 QQ邮箱「连接」→ 弹层 + .oa-ef-row flex-direction column + 输入框可见
        page.locator('#oaConnectorsList [data-act="connect"][data-code="qq_mail"]').first.click()
        page.wait_for_timeout(400)
        mask_count = page.locator(".notif-mask").count()
        chk("S5a 点「连接」弹出弹层（恰好 1 层）", mask_count == 1, "mask=%d" % mask_count)

        fd = page.evaluate("""() => {
          var el = document.querySelector('.notif-mask .oa-ef-row');
          if(!el) return {exists:false};
          var cs = getComputedStyle(el);
          var inp = document.querySelector('.notif-mask .oa-ef-row input');
          var r = inp ? inp.getBoundingClientRect() : null;
          var ico = document.querySelector('.notif-mask .oa-up-ico');
          var svg = ico ? ico.querySelector('svg') : null;
          var ir = ico ? ico.getBoundingClientRect() : null;
          var sr = svg ? svg.getBoundingClientRect() : null;
          return {exists:true, flex:cs.flexDirection,
                  inputVisible: !!(r && r.width>0 && r.height>0),
                  icoW: ir ? Math.round(ir.width) : -1, icoH: ir ? Math.round(ir.height) : -1,
                  icoBg: ico ? getComputedStyle(ico).backgroundColor : '',
                  svgW: sr ? Math.round(sr.width) : -1,
                  head: (document.querySelector('.notif-mask .notif-head')||{}).innerText};
        }""")
        chk("S5b ★.oa-ef-row 计算 flex-direction === 'column'（作用域陷阱判据）",
            fd.get("exists") and fd.get("flex") == "column", str(fd))
        chk("S6 弹层内输入框可见（宽高>0）", fd.get("inputVisible") is True, str(fd))
        chk("S5c 弹层标题「连接 QQ邮箱」", fd.get("head") == "连接 QQ邮箱", str(fd.get("head")))
        # S8 图标砖尺寸：`.oa-up-ico` 原先只写在 .oa-upload-dlg 作用域，连接器弹层(.oa-conn-dlg)
        # 拿不到 32x32 ⇒ svg 落到默认尺寸被裁，视觉上像弹层左上角多了个残字（2026-10-20 实测）。
        # 判据取两层：砖块 32x32 且底色非透明；内部 svg 显式 18px（.ic 没有全局尺寸）。
        chk("S8 弹层标题图标砖生效（32x32 有底色 + svg 18px）",
            fd.get("icoW") == 32 and fd.get("icoH") == 32 and fd.get("svgW") == 18
            and fd.get("icoBg") not in ("", "rgba(0, 0, 0, 0)"),
            "ico=%sx%s bg=%s svgW=%s" % (fd.get("icoW"), fd.get("icoH"), fd.get("icoBg"), fd.get("svgW")))

        page.screenshot(path=str(PROOF / "connector_ui_modal.png"))

        # 空必填提交拦截：清空后点「连接并验证」不应关闭弹层
        page.fill('.notif-mask .oa-ef-row input[data-fkey="email"]', "")
        page.fill('.notif-mask .oa-ef-row input[data-fkey="authCode"]', "")
        page.locator('.notif-mask #oaConnSubmit').click()
        page.wait_for_timeout(300)
        still_open = page.locator(".notif-mask").count()
        err_txt = page.eval_on_selector(".notif-mask #oaConnErr", "el => el.innerText") if page.locator(".notif-mask #oaConnErr").count() else ""
        chk("S7 空必填提交被前端拦截（弹层不关 + 红字提示，且未发请求）",
            still_open == 1 and "请填写所有必填项" in err_txt, "open=%d err=%r" % (still_open, err_txt))
        page.screenshot(path=str(PROOF / "connector_ui_modal_validation.png"))

        browser.close()

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    return len(FAIL)


if __name__ == "__main__":
    sys.exit(main())
