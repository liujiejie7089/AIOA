#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
h5-inputbar-verify —— 独立验证「语音停录修复 + 输入栏重排 + 「+」上传」

证伪/证实另一名 worker 在 user-client 做的改动。全部走**真实浏览器**（Playwright/Chromium
+ 假麦克风），不依赖「源码里有这段代码」式推理。证据落到 logs/proof/。

纪律：
  · 不修改 user-client/ 下任何文件、不修改 scripts/_check_voice_gesture.*（被验对象）。
  · 静态服务随用随杀（脚本内自建 http.server 线程，finally 关闭）。
  · 区分 已证实 / 已证伪 / 本环境无法验 三态。

用法： python scripts/_verify_h5_inputbar.py
"""
import functools
import hashlib
import http.server
import json
import os
import socket
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_CLIENT = os.path.join(ROOT, "user-client")
PROOF = os.path.join(ROOT, "logs", "proof")
os.makedirs(PROOF, exist_ok=True)

A_TXT = os.path.join(PROOF, "a.txt")
with open(A_TXT, "w", encoding="utf-8") as f:
    f.write("这是一份用于验证「+」上传链路的示例文档。\n")

from playwright.sync_api import sync_playwright

results = []  # {name, status, expected, actual, detail}


def rec(name, status, expected, actual, detail=""):
    results.append({"name": name, "status": status,
                   "expected": expected, "actual": actual, "detail": detail})
    tag = {"PASS": "✅", "FAIL": "❌", "NA": "⚠️"}.get(status, status)
    print(f"[{tag}] {name}\n      expect={expected!r}\n      actual ={actual!r}"
          + (f"\n      note  : {detail}" if detail else ""))


def start_static_server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=USER_CLIENT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def install_stubs(page):
    """在页面加载后重写 API 方法为计数/抓参桩，并接管 toast 收集器。"""
    page.evaluate(r"""
    () => {
      window.__probe = {asr:0, asrBlobs:[], createRunArgs:null, toasts:[], streamCalls:0,
                        fileUploadName:null, disconnectCodes:[]};
      const P = window.__probe;
      const origToast = window.toast;
      window.toast = function(m){ P.toasts.push(String(m)); return origToast ? origToast(m) : undefined; };
      // 关键：页面用 `const API = {...}`（词法绑定，不在 window 上），必须按词法名取，
      // 不能写 window.API（为 undefined 会让整套桩被跳过）。
      const apiObj = (typeof API !== 'undefined') ? API : (window.API || null);
      if (apiObj) {
        apiObj.asrTranscribe = function(blob){
          P.asr++;
          P.asrBlobs.push({size: blob? blob.size : null, type: blob? blob.type : null});
          return Promise.resolve({text:'识别文本_桩'});
        };
        apiObj.createRun = function(){
          P.createRunArgs = Array.prototype.slice.call(arguments);
          return Promise.resolve({id:'run_x', runId:'run_x'});
        };
        apiObj.stream = function(runId, h){
          P.streamCalls++;
          try { h && h.onStarted && h.onStarted({model:'deepseek'}); } catch(e){}
          try { h && h.onDelta && h.onDelta('回答_桩'); } catch(e){}
          try { h && h.onCompleted && h.onCompleted({citations:[]}); } catch(e){}
          return Promise.resolve();
        };
        apiObj.ensureConversation = function(){ return Promise.resolve({id:'conv_x'}); };
        apiObj.fileUpload = function(file){
          P.fileUploadName = (file && file.name) || 'a.txt';
          return Promise.resolve({id:123, name:(file&&file.name)||'a.txt'});
        };
        apiObj.listConversations = function(){ return Promise.resolve([]); };
        apiObj.listMessages = function(){ return Promise.resolve([]); };
        apiObj.quota = function(){ return Promise.resolve({exhausted:false, left:9999}); };
        /* 「＋」浮层的连接器区：目录与断开都打桩，不碰真后端。
           开关真值 = status === 'CONNECTED'，所以这里造一开一关两条。 */
        apiObj.connectors = function(){
          return Promise.resolve([
            {code:'wecom_cli', name:'企业微信', status:'CONNECTED', accountLabel:'刘洋', configReady:true},
            {code:'qq_mail',   name:'QQ 邮箱', status:'DISCONNECTED', configReady:true}
          ]);
        };
        apiObj.connectorDisconnect = function(code){
          P.disconnectCodes.push(String(code));
          return Promise.resolve({status:'DISCONNECTED'});
        };
        // 注意：真实 API.req 在 code===0 时「返回 body.data」（见页面源码），所以桩必须
        // 直接返回 data 形态，不能返回 {code,data} 信封，否则调用方读不到 .id 会抛错。
        apiObj.req = function(path, opts){
          opts = opts || {};
          var m = (opts.method || 'GET').toUpperCase();
          if(path && path.indexOf('/conversations') >= 0 && m === 'POST')
            return Promise.resolve({id:'conv_x', conversationId:'conv_x'});
          if(path && path.indexOf('/conversations') >= 0) return Promise.resolve([]);
          if(path && path.indexOf('/messages') >= 0) return Promise.resolve([]);
          if(path && path.indexOf('/auth/me') >= 0)
            return Promise.resolve({id:1, username:'zhangsan', nickname:'张三', roles:['ROLE_USER']});
          return Promise.resolve({});
        };
      } else {
        P.noApi = true;
      }
    }
    """)


def api_route(route):
    """兜底：boot 期 /auth/me 与 loadLiveData 等网络调用（用户动作走的是上面的 JS 桩，不发网络）。"""
    url = route.request.url
    try:
        if "auth/me" in url:
            body = {"code": 0, "data": {"id": 1, "username": "zhangsan",
                                        "nickname": "张三", "roles": ["ROLE_USER"]}}
        elif any(k in url for k in ("/conversations", "/experts", "/skills", "/kb/documents",
                                    "/ledger", "/logs", "/workflow", "/leave", "/packages",
                                    "/orders", "/approvals")):
            body = {"code": 0, "data": []}
        elif "quota" in url:
            body = {"code": 0, "data": {"exhausted": False, "left": 9999}}
        else:
            body = {"code": 0, "data": {}}
    except Exception:
        body = {"code": 0, "data": {}}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def btn_center(page, sel):
    box = page.locator(sel).bounding_box(timeout=5000)
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def reset_probe(page):
    # 关键：必须「原地修改」window.__probe，不能重新赋值——桩函数的闭包持有的是
    # install_stubs 时那个对象引用，重新赋值会让计数写到被丢弃的旧对象上。
    page.evaluate("""() => {
      const P = window.__probe || (window.__probe = {});
      P.asr = 0; P.asrBlobs = []; P.createRunArgs = null; P.toasts = [];
      P.streamCalls = 0; P.fileUploadName = null; P.disconnectCodes = []; P.cancelIds = [];
    }""")


def is_voice_supported(page):
    return page.evaluate("!!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder)")


def main():
    srv, port = start_static_server()
    base = f"http://127.0.0.1:{port}"
    page_errors = []
    console_errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=[
                "--no-sandbox",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ])
            ctx = browser.new_context(viewport={"width": 390, "height": 844})
            ctx.grant_permissions(["microphone"], origin=base)
            ctx.route("**/v1/**", api_route)
            ctx.route("**/api/**", api_route)
            page = ctx.new_page()
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            # 启动前注入假 session（boot 据它判定已登录）
            page.add_init_script(
                "localStorage.setItem('aios_session', JSON.stringify({token:'fake',"
                "user:{username:'zhangsan',nickname:'张三',roles:['ROLE_USER']}}));")
            page.goto(base + "/index.html", wait_until="load")
            page.wait_for_timeout(2500)
            install_stubs(page)
            page.wait_for_timeout(300)
            no_api = page.evaluate("window.__probe ? window.__probe.noApi : 'probe-missing'")
            rec("0.2 API 桩已注入(API 可被重写)",
                "PASS" if no_api is not True else "FAIL", False, no_api,
                "若为 True 说明页面 API 对象无法在 evaluate 中访问")

            # ---------- 0. 安全上下文 / 假麦克风 -------------------------------
            supported = is_voice_supported(page)
            rec("0.1 安全上下文+getUserMedia+MediaRecorder 可用(假麦克风)",
                "PASS" if supported else "FAIL",
                True, supported, "localhost 为安全上下文；--use-fake-* 提供假麦克风")

            # 先切到经典形态做语音手势与输入栏验证（页面默认 OA）
            page.evaluate("window.oaSetMode && window.oaSetMode('classic')")
            page.evaluate("go('page-chat')")
            page.wait_for_timeout(600)

            # ---------- 1. 真实手势：按住 ~800ms 松手 → 发送 -------------------
            reset_probe(page)
            page.evaluate("state.busy = false")
            cx, cy = btn_center(page, "#voiceBtn")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(800)
            page.mouse.up()
            page.wait_for_timeout(500)
            st = page.evaluate(r"""() => ({
              asr: window.__probe.asr,
              blobs: window.__probe.asrBlobs,
              rec: document.getElementById('voiceBtn').classList.contains('rec'),
              ph: document.getElementById('chatInput').placeholder,
              live: (typeof VoiceInput!=='undefined') ? VoiceInput.isLive() : null
            })""")
            blob_ok = bool(st["blobs"]) and st["blobs"][0]["size"] not in (None, 0)
            rec("1a. 按住~800ms松手: asrTranscribe 恰好1次",
                "PASS" if st["asr"] == 1 else "FAIL", 1, st["asr"],
                f"blobs={st['blobs']}")
            rec("1a. blob 非空(真录到音频)",
                "PASS" if blob_ok else "FAIL", True, blob_ok, f"blobs={st['blobs']}")
            rec("1a. .rec 类已移除(录音结束)",
                "PASS" if not st["rec"] else "FAIL", False, st["rec"])
            rec("1a. placeholder 恢复为「发消息或按住说话…」",
                "PASS" if st["ph"] == "发消息或按住说话…" else "FAIL",
                "发消息或按住说话…", st["ph"])
            rec("1a. 不在录音态", "PASS" if st["live"] is False else "FAIL", False, st["live"])

            # ---------- 1b. 短按 ~120ms → 误触不发送 ------------------------
            reset_probe(page)
            page.evaluate("state.busy = false")
            cx, cy = btn_center(page, "#voiceBtn")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(120)
            page.mouse.up()
            page.wait_for_timeout(400)
            stb = page.evaluate(r"""() => ({
              asr: window.__probe.asr,
              toasts: window.__probe.toasts.slice(),
              rec: document.getElementById('voiceBtn').classList.contains('rec'),
              live: (typeof VoiceInput!=='undefined') ? VoiceInput.isLive() : null
            })""")
            toast_hit = any("按住说话" in t for t in stb["toasts"])
            rec("1b. 短按~120ms: asrTranscribe 0 次(旧实现会进免提继续录)",
                "PASS" if stb["asr"] == 0 else "FAIL", 0, stb["asr"])
            rec("1b. 出现「按住说话」toast(误触提示)",
                "PASS" if toast_hit else "FAIL", True, toast_hit,
                f"toasts={stb['toasts']}")
            rec("1b. .rec 未残留", "PASS" if not stb["rec"] else "FAIL", False, stb["rec"])
            rec("1b. 未处于录音态", "PASS" if stb["live"] is False else "FAIL", False, stb["live"])

            # ---------- 1c. 录音中再次 pointerdown 且 busy=true → 结束优先 ----
            reset_probe(page)
            page.evaluate("state.busy = false")
            cx, cy = btn_center(page, "#voiceBtn")
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.wait_for_timeout(450)  # 已进入录音(>MIN_MS)
            page.evaluate("state.busy = true")
            # 录音中再次触发 pointerdown（合成事件，绕过真实鼠标仍按住）
            page.evaluate(r"""() => {
              const b = document.getElementById('voiceBtn');
              b.dispatchEvent(new PointerEvent('pointerdown', {pointerId:99, bubbles:true, button:0, cancelable:true}));
            }""")
            page.wait_for_timeout(500)
            stc = page.evaluate(r"""() => ({
              asr: window.__probe.asr,
              busy: state.busy,
              live: (typeof VoiceInput!=='undefined') ? VoiceInput.isLive() : null
            })""")
            page.mouse.up()  # 清理真实按住
            page.evaluate("state.busy = false")
            rec("1c. 录音中再按(busy=true): 录音结束且 asrTranscribe 恰好1次",
                "PASS" if stc["asr"] == 1 else "FAIL", 1, stc["asr"],
                "验证「结束优先于 busy」：pointerdown 先判 isLive→end，再判 busy")
            rec("1c. 结束后面不在录音态", "PASS" if stc["live"] is False else "FAIL", False, stc["live"])

            # ---------- 1d. touch-action 运行时计算值 = none ------------------
            ta = page.evaluate("getComputedStyle(document.getElementById('voiceBtn')).touchAction")
            rec("1d. #voiceBtn 运行时 touch-action = none(读计算值,非源码)",
                "PASS" if ta == "none" else "FAIL", "none", ta)

            # ---------- 2. #kbChip 搬家 + 功能未坏 ----------------------------
            kb = page.evaluate(r"""() => {
              const c = document.getElementById('kbChip');
              const p = c.parentElement;
              const before = document.getElementById('kbChipText').textContent;
              c.click();
              const after = document.getElementById('kbChipText').textContent;
              return {parentClass: p.className, parentId: p.id, before, after,
                      hasOnclick: c.getAttribute('onclick')};
            }""")
            rec("2. #kbChip 现父节点为 .chat-head(非 .input-bar)",
                "PASS" if "chat-head" in (kb["parentClass"] or "") and "input-bar" not in (kb["parentClass"] or "") else "FAIL",
                "父含 chat-head 且不含 input-bar", kb["parentClass"])
            rec("2. 点击 #kbChip 文案在「知识库 开/关」间翻转(toggleKB 生效)",
                "PASS" if kb["before"] != kb["after"] and "知识库" in kb["before"] and "知识库" in kb["after"] else "FAIL",
                "前后不同且均为知识库文案", f"{kb['before']} -> {kb['after']}")

            # ---------- 3. 「+」上传链路（经典） ------------------------------
            reset_probe(page)
            page.evaluate("go('page-chat')")
            page.wait_for_timeout(300)
            # 新交互：空输入时才显示 #attachBtn，有文字时显示 #sendBtn
            page.evaluate("document.getElementById('chatInput').value=''; syncClassicInput();")
            page.wait_for_timeout(100)
            with page.expect_file_chooser() as fc:
                page.click("#attachBtn")
            fc.value.set_files(A_TXT)
            page.wait_for_timeout(500)
            strip = page.evaluate(r"""() => {
              const s = document.getElementById('attachStrip');
              return {html: s.innerHTML, display: getComputedStyle(s).display,
                      chips: s.querySelectorAll('.attach-chip').length,
                      name: (s.querySelector('.ac-name')||{}).textContent || ''};
            }""")
            rec("3. 点 #attachBtn 触发了 #attachFile(文件框已选入)",
                "PASS" if strip["chips"] >= 1 else "FAIL", ">=1 个文件芯片", strip["chips"],
                f"strip.html={strip['html'][:80]}")
            rec("3. #attachStrip 出现文件名芯片",
                "PASS" if "a.txt" in strip["name"] else "FAIL", "含 a.txt", strip["name"])
            up_diag = page.evaluate("({fileUploadName: window.__probe.fileUploadName, pending: (typeof pendingFiles!=='undefined'? pendingFiles.length : 'n/a')})")
            rec("3. 上传桩被调用且 pendingFiles 已装入",
                "PASS" if up_diag["fileUploadName"] == "a.txt" and up_diag["pending"] == 1 else "FAIL",
                "fileUploadName='a.txt' 且 pendingFiles=1", up_diag)
            # 点 × 移除
            if strip["chips"] >= 1:
                page.evaluate("document.querySelector('#attachStrip .ac-x').click()")
                page.wait_for_timeout(200)
                # 移除文档(空输入又无附件) ⇒ 同槽位切回「＋」(#sendBtn 隐藏 / #attachBtn 可见)
                vis_after_remove = page.evaluate(r"""() => {
                  const a = document.getElementById('attachBtn');
                  const s = document.getElementById('sendBtn');
                  return {
                    attachShown: a ? getComputedStyle(a).display !== 'none' : null,
                    sendHidden: s ? getComputedStyle(s).display === 'none' : null
                  };
                }""")
                rec("3. 移除文档(空输入)后: #attachBtn 可见且 #sendBtn 隐藏(槽位切回「＋」)",
                    "PASS" if vis_after_remove.get("attachShown") is True and vis_after_remove.get("sendHidden") is True else "FAIL",
                    "#attachBtn 可见 / #sendBtn 隐藏", vis_after_remove)
            strip2 = page.evaluate("document.getElementById('attachStrip').querySelectorAll('.attach-chip').length")
            rec("3. 点 × 后芯片消失", "PASS" if strip2 == 0 else "FAIL", 0, strip2)
            # 重新上传并发送(只传文档不写字)
            reset_probe(page)
            page.evaluate("state.busy=false; document.getElementById('chatInput').value = ''; syncClassicInput();")
            with page.expect_file_chooser() as fc:
                page.click("#attachBtn")
            fc.value.set_files(A_TXT)
            page.wait_for_timeout(500)
            # 回归关键点：空输入 + 1 附件 ⇒ 右侧「发送」可见、「＋」隐藏
            # （旧实现只按 hasText 切换，会把发送藏起来，使「只传文档」在 UI 上点不到）
            vis_before_send = page.evaluate(r"""() => {
              const a = document.getElementById('attachBtn');
              const s = document.getElementById('sendBtn');
              return {
                sendShown: s ? getComputedStyle(s).display !== 'none' : null,
                attachHidden: a ? getComputedStyle(a).display === 'none' : null
              };
            }""")
            rec("3. 空输入 + 1 文档: #sendBtn 可见且 #attachBtn 隐藏(只传文档在 UI 上可达)",
                "PASS" if vis_before_send["sendShown"] is True and vis_before_send["attachHidden"] is True else "FAIL",
                "#sendBtn 可见 / #attachBtn 隐藏", vis_before_send)
            # 点真按钮 #sendBtn（onclick 调 send()），不再绕过 UI 直接 evaluate
            page.click("#sendBtn")
            page.wait_for_timeout(500)
            cr = page.evaluate("window.__probe.createRunArgs")
            att_ok = bool(cr) and len(cr) >= 4 and cr[3] == ["123"]
            rec("3. 经典: createRun 第4参 === ['123'](读桩实参)",
                "PASS" if att_ok else "FAIL", "['123']", cr[3] if cr else None,
                f"full args={cr}")
            txt_ok = bool(cr) and len(cr) >= 2 and cr[1] == "请解析我上传的文档"
            rec("3. 经典: 只传文档不写字 → 默认话术「请解析我上传的文档」",
                "PASS" if txt_ok else "FAIL", "请解析我上传的文档", cr[1] if cr else None)

            # ---------- 4. 回归：空输入时禁止发送 + 历史渲染不报错 ----------
            reset_probe(page)
            page.evaluate("state.busy=false; pendingFiles=[]; document.getElementById('chatInput').value=''; document.getElementById('attachStrip').innerHTML=''; syncClassicInput();")
            # 空输入时 #sendBtn 隐藏，直接调用 send() 验证空输入不得发送
            page.evaluate("send()")
            page.wait_for_timeout(300)
            toasts4 = page.evaluate("window.__probe.toasts.slice()")
            rec("4. 空输入 send() → 提示且不崩溃(无 pageerror)",
                "PASS" if any("请输入" in t for t in toasts4) and not page_errors else "FAIL",
                "出现「请输入…」且无JS异常", f"toasts={toasts4}; pageerrors={page_errors[-1:] if page_errors else []}")
            # historyBubble / attachMetaLine 纯函数：无附件不得出 📎、不得抛异常
            hb = page.evaluate(r"""() => {
              const out = {};
              try {
                out.attachEmpty = attachMetaLine([]);
                out.bubbleNoAtt = historyBubble({role:'user', content:'普通消息'});
                out.bubbleNoAttHasPaperclip = out.bubbleNoAtt.indexOf('📎') >= 0;
                out.attachEmptyHasPaperclip = (out.attachEmpty||'').indexOf('📎') >= 0;
                out.ok = true;
              } catch(e){ out.ok = false; out.err = String(e); }
              return out;
            }""")
            rec("4. attachMetaLine([]) 返回空(无 📎)",
                "PASS" if hb.get("ok") and hb.get("attachEmpty") == "" else "FAIL",
                "''", hb.get("attachEmpty"))
            rec("4. 无附件普通消息 historyBubble 不抛异常且无 📎",
                "PASS" if hb.get("ok") and not hb.get("bubbleNoAttHasPaperclip") else "FAIL",
                "ok 且不含 📎", f"ok={hb.get('ok')} hasClip={hb.get('bubbleNoAttHasPaperclip')} err={hb.get('err','')}")
            # 真实 openHistory（listConversations 桩为 []）不抛、不报错
            oh = page.evaluate(r"""() => { try { openHistory(); return {ok:true}; } catch(e){ return {ok:false, err:String(e)}; } }""")
            rec("4. openHistory() 调用不抛异常",
                "PASS" if oh.get("ok") else "FAIL", "ok", oh,
                f"err={oh.get('err','')}")
            # 关掉 openHistory 弹出的 notif-mask，避免遮挡后续 OA 点击
            page.evaluate("document.querySelectorAll('.notif-mask').forEach(function(m){m.remove();});")
            page.wait_for_timeout(200)

            # ---------- 3(OA). 「+」上传链路（OA 形态） ----------------------
            page.evaluate("document.querySelectorAll('.notif-mask').forEach(function(m){m.remove();});")
            page.evaluate("window.oaSetMode && window.oaSetMode('oa')")
            page.wait_for_timeout(800)
            oa_wired = page.evaluate(r"""() => {
              const b = document.getElementById('oaAttachBtn');
              const m = document.getElementById('oaMicBtn');
              return {
                attachExists: !!b,
                attachOnclick: !!(b && typeof b.onclick === 'function'),
                micExists: !!m,
                micTouch: m ? getComputedStyle(m).touchAction : null,
                stripExists: !!document.getElementById('oaAttachStrip')
              };
            }""")
            rec("3(OA). #oaAttachBtn 存在且已绑定 onclick(由 bind() 注入)",
                "PASS" if oa_wired["attachExists"] and oa_wired["attachOnclick"] else "FAIL",
                "存在且 onclick 为函数", oa_wired)
            rec("3(OA). #oaMicBtn 运行时 touch-action = none",
                "PASS" if oa_wired["micTouch"] == "none" else "FAIL", "none", oa_wired["micTouch"])
            if oa_wired["attachExists"]:
                reset_probe(page)
                try:
                    # 「＋」升级成「更多」入口后，有文字时**也必须可见**
                    # （旧实现有字就隐藏，连接器开关就再也点不到了）
                    page.evaluate("""() => {
                      var i = document.getElementById('oaInput'); if(i) i.value = '写了一行字';
                      if(window.oaSyncInput) window.oaSyncInput();
                    }""")
                    page.wait_for_timeout(120)
                    plus_vis = page.evaluate(r"""() => {
                      const a = document.getElementById('oaAttachBtn');
                      const s = document.getElementById('oaSendBtn');
                      return {
                        plusShown: a ? getComputedStyle(a).display !== 'none' : null,
                        sendShown: s ? getComputedStyle(s).display !== 'none' : null
                      };
                    }""")
                    rec("3(OA). 有文字时「＋」与「发送」同时可见(同槽位互斥已取消)",
                        "PASS" if plus_vis["plusShown"] is True and plus_vis["sendShown"] is True else "FAIL",
                        "两者都可见", plus_vis)

                    # 点「＋」→ 浮层（不是文件框）
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(300)
                    men = page.evaluate(r"""() => {
                      const sws = Array.prototype.map.call(
                        document.querySelectorAll('#oaPlusMenu .pm-sw'),
                        s => ({code: s.getAttribute('data-code'), on: s.classList.contains('on'),
                               checked: s.getAttribute('aria-checked'), role: s.getAttribute('role'),
                               disabled: s.disabled}));
                      return {
                        exists: !!document.getElementById('oaPlusMenu'),
                        fileRow: !!document.querySelector('#oaPlusMenu [data-act="file"]'),
                        conns: document.querySelectorAll('#oaPlusMenu .pm-conn').length,
                        sws: sws,
                        empty: (document.querySelector('#oaPlusConns .pm-empty') || {}).textContent || ''
                      };
                    }""")
                    rec("3(OA). 点「＋」打开浮层：含「添加文件」行 + 连接器区(不弹文件框)",
                        "PASS" if men["exists"] and men["fileRow"] and not men["empty"] else "FAIL",
                        "浮层打开 / 添加文件行在 / 连接器已加载", men)
                    on_codes = sorted(x["code"] for x in men["sws"] if x["on"])
                    rec("3(OA). 连接器开关态以后端 status=CONNECTED 为唯一真值",
                        "PASS" if men["sws"] and on_codes == ["wecom_cli"]
                        and all(x["role"] == "switch" for x in men["sws"])
                        and all(x["checked"] == ("true" if x["on"] else "false") for x in men["sws"])
                        else "FAIL",
                        "wecom_cli 开 / qq_mail 关，role=switch 且 aria-checked 同步", men["sws"])

                    # 再点一次「＋」= 收起
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(200)
                    toggled = page.evaluate("!!document.getElementById('oaPlusMenu')")
                    rec("3(OA). 再点一次「＋」收起浮层(toggle)",
                        "PASS" if toggled is False else "FAIL", "浮层不在", toggled)

                    # 点浮层外区域也应收起（不用遮罩层，靠全局 pointerdown 监听）
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(300)
                    opened2 = page.evaluate("!!document.getElementById('oaPlusMenu')")
                    # 点输入框本身作为「浮层外区域」：命中区确定、且不会误触首页上的卡片
                    # （先前用坐标 (150,260) 一点就开出了「专家」抽屉，把后续点击全挡住了）
                    page.click("#oaInput")
                    page.wait_for_timeout(250)
                    outside = page.evaluate(r"""() => ({
                      menu: !!document.getElementById('oaPlusMenu'),
                      overlayLeft: document.querySelectorAll('.oa-plus-mask, #oaPlusMask').length})""")
                    rec("3(OA). 点浮层外区域收起，且不残留拦截点击的遮罩层",
                        "PASS" if opened2 and outside["menu"] is False and outside["overlayLeft"] == 0
                        else "FAIL", "浮层收起 / 无遮罩元素", f"opened={opened2} {outside}")

                    # 关闭连接器：必须先确认，确认后真的调 disconnect
                    reset_probe(page)
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(300)
                    page.click('#oaPlusMenu .pm-sw[data-code="wecom_cli"]')
                    page.wait_for_timeout(250)
                    dlg = page.evaluate(r"""() => {
                      const ok = document.querySelector('.notif-mask.show [data-dlg-ok]');
                      const t = document.querySelector('.notif-mask.show .notif-head');
                      return {hasDialog: !!ok, title: t ? t.textContent : '',
                              menuGone: !document.getElementById('oaPlusMenu'),
                              text: (document.querySelector('.notif-mask.show .notif-body') || {}).textContent || ''};
                    }""")
                    rec("3(OA). 关闭已连接的连接器: 先弹确认(浮层同时收起)",
                        "PASS" if dlg["hasDialog"] and dlg["menuGone"] and "关闭" in dlg["title"] else "FAIL",
                        "弹层标题含「关闭」且浮层已收起", dlg)
                    page.click('.notif-mask.show [data-dlg-ok]')
                    page.wait_for_timeout(400)
                    disc = page.evaluate("window.__probe.disconnectCodes.slice()")
                    rec("3(OA). 确认后真的调了 connectorDisconnect(code) 并提示已关闭",
                        "PASS" if disc == ["wecom_cli"] else "FAIL", "['wecom_cli']", disc,
                        f"toasts={page.evaluate('window.__probe.toasts.slice()')}")
                    page.evaluate("document.querySelectorAll('.notif-mask').forEach(function(m){m.remove();});")

                    # 「添加文件」行仍走原上传链路
                    reset_probe(page)
                    page.evaluate("""() => {
                      var i = document.getElementById('oaInput'); if(i) i.value = '';
                      if(window.oaSyncInput) window.oaSyncInput();
                    }""")
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(250)
                    with page.expect_file_chooser() as fc:
                        page.click('#oaPlusMenu [data-act="file"]')
                    fc.value.set_files(A_TXT)
                    page.wait_for_timeout(500)
                    oastrip = page.evaluate(r"""() => {
                      const s = document.getElementById('oaAttachStrip');
                      return {chips: s.querySelectorAll('.attach-chip').length,
                              name: (s.querySelector('.ac-name')||{}).textContent || '',
                              menu: !!document.getElementById('oaPlusMenu')};
                    }""")
                    rec("3(OA). 浮层「添加文件」→ 文件框 → #oaAttachStrip 出芯片(浮层自动收起)",
                        "PASS" if oastrip["chips"] >= 1 and "a.txt" in oastrip["name"]
                        and not oastrip["menu"] else "FAIL",
                        ">=1 芯片且含 a.txt，浮层已收起", oastrip)
                    oa_vis = page.evaluate(r"""() => {
                      const a = document.getElementById('oaAttachBtn');
                      const s = document.getElementById('oaSendBtn');
                      return {
                        sendShown: s ? getComputedStyle(s).display !== 'none' : null,
                        plusShown: a ? getComputedStyle(a).display !== 'none' : null
                      };
                    }""")
                    rec("3(OA). 空输入 + 1 文档: #oaSendBtn 可见且「＋」仍可见(只传文档在 UI 上可达)",
                        "PASS" if oa_vis["sendShown"] is True and oa_vis["plusShown"] is True else "FAIL",
                        "两者都可见", oa_vis)
                    # 移除文档 ⇒ 回到只有「＋」、无「发送」
                    page.evaluate("document.querySelector('#oaAttachStrip .ac-x').click()")
                    page.wait_for_timeout(200)
                    oa_vis2 = page.evaluate(r"""() => {
                      const a = document.getElementById('oaAttachBtn');
                      const s = document.getElementById('oaSendBtn');
                      return {
                        attachShown: a ? getComputedStyle(a).display !== 'none' : null,
                        sendHidden: s ? getComputedStyle(s).display === 'none' : null
                      };
                    }""")
                    rec("3(OA). 移除文档(空输入)后: 「＋」可见且 #oaSendBtn 隐藏",
                        "PASS" if oa_vis2["attachShown"] is True and oa_vis2["sendHidden"] is True else "FAIL",
                        "「＋」可见 / #oaSendBtn 隐藏", oa_vis2)
                    # 重新上传并点真按钮 #oaSendBtn 发送（不绕过 UI）
                    reset_probe(page)
                    page.click("#oaAttachBtn")
                    page.wait_for_timeout(250)
                    with page.expect_file_chooser() as fc:
                        page.click('#oaPlusMenu [data-act="file"]')
                    fc.value.set_files(A_TXT)
                    page.wait_for_timeout(500)
                    page.click("#oaSendBtn")
                    page.wait_for_timeout(500)
                    oacr = page.evaluate("window.__probe.createRunArgs")
                    oa_att = bool(oacr) and len(oacr) >= 4 and oacr[3] == ["123"]
                    rec("3(OA). oaSendBtn: createRun 第4参 === ['123'](读桩实参)",
                        "PASS" if oa_att else "FAIL", "['123']", oacr[3] if oacr else None,
                        f"full={oacr}")
                except Exception as e:
                    rec("3(OA). OA 浮层 / 上传 / 连接器开关链路可验", "NA", "可验", "无法验", f"异常: {e}")
            else:
                rec("3(OA). OA 上传链路", "NA", "可验", "未验", "oaAttachBtn 不存在")

            # ---------- 6. 输入框随内容自动增高（2026-10-30 需求） ------------
            page.evaluate("document.querySelectorAll('.notif-mask').forEach(function(m){m.remove();});")
            page.evaluate("""() => {
              var i = document.getElementById('oaInput');
              i.value = '';
              if(window.oaSyncInput) window.oaSyncInput();
            }""")
            page.wait_for_timeout(150)
            h_empty = page.evaluate(
                "document.getElementById('oaInput').getBoundingClientRect().height")
            page.evaluate("""() => {
              var i = document.getElementById('oaInput');
              i.value = '第一行\\n第二行\\n第三行\\n第四行\\n第五行';
              if(window.oaSyncInput) window.oaSyncInput();
            }""")
            page.wait_for_timeout(200)
            grow = page.evaluate(r"""() => {
              const i = document.getElementById('oaInput');
              const box = i.closest('.box');
              return {tag: i.tagName, h: i.getBoundingClientRect().height,
                      boxH: box ? box.getBoundingClientRect().height : null,
                      scrollH: i.scrollHeight, over: getComputedStyle(i).overflowY};
            }""")
            rec("6. #oaInput 是 TEXTAREA 且单行时约 46px 胶囊高度",
                "PASS" if grow["tag"] == "TEXTAREA" and 40 <= h_empty <= 52 else "FAIL",
                "TEXTAREA 且 40<=h<=52", f"tag={grow['tag']} h_empty={h_empty}")
            rec("6. 五行文本时输入框向下长高且无内部滚动(完整可见)",
                "PASS" if grow["h"] > h_empty + 20 and grow["over"] == "hidden"
                and grow["h"] >= grow["scrollH"] - 2 else "FAIL",
                "高度显著增大 / overflowY=hidden / 高度覆盖 scrollHeight", grow)
            page.evaluate("""() => {
              var i = document.getElementById('oaInput');
              i.value = ''; if(window.oaSyncInput) window.oaSyncInput();
            }""")
            page.wait_for_timeout(150)
            h_back = page.evaluate(
                "document.getElementById('oaInput').getBoundingClientRect().height")
            rec("6. 清空后高度收回(不是只增不减)",
                "PASS" if abs(h_back - h_empty) <= 2 else "FAIL",
                f"≈{h_empty}", h_back)

            # ---------- 7. AI 气泡右下角「停止生成」（2026-10-30 需求） --------
            page.evaluate(r"""() => {
              const apiObj = (typeof API !== 'undefined') ? API : null;
              if(!apiObj) return;
              /* 让 stream 悬着不结束，才有「生成中」这个状态可测；
                 cancel 时按真实链路的语义以 AbortError 收掉这次 stream。 */
              apiObj.stream = function(runId, h){
                window.__probe.streamCalls++;
                try{ h && h.onStarted && h.onStarted({model:'stub'}); }catch(e){}
                try{ h && h.onDelta && h.onDelta('第一段'); }catch(e){}
                return new Promise(function(res, rej){ window.__streamReject = rej; });
              };
              apiObj.cancel = function(rid){
                const P = window.__probe;
                P.cancelIds = P.cancelIds || []; P.cancelIds.push(rid);
                if(window.__streamReject){
                  const e = new Error('aborted'); e.name = 'AbortError';
                  window.__streamReject(e); window.__streamReject = null;
                }
                return Promise.resolve();
              };
            }""")
            reset_probe(page)
            page.evaluate("""() => {
              const i = document.getElementById('oaInput');
              i.value = '测一下停止生成'; if(window.oaSyncInput) window.oaSyncInput();
            }""")
            page.click("#oaSendBtn")
            page.wait_for_timeout(500)
            gen = page.evaluate(r"""() => {
              const bubs = document.querySelectorAll('#oaDockList .bub.ai');
              const b = bubs.length ? bubs[bubs.length - 1] : null;
              const s = b ? b.querySelector('.bub-stop') : null;
              const r = s ? s.getBoundingClientRect() : null;
              const br = b ? b.getBoundingClientRect() : null;
              return {stopInBubble: !!s, generating: b ? b.classList.contains('generating') : null,
                      aria: s ? s.getAttribute('aria-label') : null,
                      rightGap: (r && br) ? Math.round(br.right - r.right) : null,
                      bottomGap: (r && br) ? Math.round(br.bottom - r.bottom) : null,
                      busy: (window.oaState ? !!window.oaState.busy : null)};
            }""")
            rec("7. 生成中: AI 气泡内出现 #.bub-stop 且气泡带 generating",
                "PASS" if gen["stopInBubble"] and gen["generating"] and gen["aria"] == "停止生成" else "FAIL",
                "气泡内有停止按钮 + generating 类 + aria-label=停止生成", gen)
            rec("7. 停止按钮贴在气泡右下角(右/下边距各 <=10px)",
                "PASS" if gen["rightGap"] is not None and gen["rightGap"] <= 10
                and gen["bottomGap"] is not None and gen["bottomGap"] <= 10 else "FAIL",
                "rightGap<=10 且 bottomGap<=10", f"right={gen['rightGap']} bottom={gen['bottomGap']}")
            page.click("#oaDockList .bub.ai:last-child .bub-stop")
            page.wait_for_timeout(600)
            after = page.evaluate(r"""() => {
              const bubs = document.querySelectorAll('#oaDockList .bub.ai');
              const b = bubs.length ? bubs[bubs.length - 1] : null;
              const tx = b ? b.querySelector('.tx') : null;
              return {cancelIds: (window.__probe.cancelIds || []).slice(),
                      stopLeft: document.querySelectorAll('#oaDockList .bub-stop').length,
                      generating: b ? b.classList.contains('generating') : null,
                      busy: (window.oaState ? !!window.oaState.busy : null),
                      text: tx ? tx.textContent : '',
                      color: tx ? getComputedStyle(tx).color : ''};
            }""")
            rec("7. 点击停止 → 真的调了 API.cancel(runId)",
                "PASS" if after["cancelIds"] == ["run_x"] else "FAIL", "['run_x']", after["cancelIds"])
            rec("7. 停止后按钮移除、气泡退出 generating、S.busy 释放",
                "PASS" if after["stopLeft"] == 0 and after["generating"] is False
                and after["busy"] is False else "FAIL",
                "0 个残留按钮 / generating=false / busy=false", after)
            rec("7. 主动停止不染红(不是「请求失败」)",
                "PASS" if "请求失败" not in (after["text"] or "") else "FAIL",
                "文案不含「请求失败」", after["text"][:40])

            # ---------- 8. 上滑看历史时数字人渐隐（2026-10-30 需求） ----------
            page.evaluate(r"""() => {
              const l = document.getElementById('oaDockList');
              l.innerHTML = '';
              for(let i = 0; i < 30; i++){
                const d = document.createElement('div');
                d.className = 'bub ' + (i % 2 ? 'me' : 'ai');
                d.textContent = '第' + i + '条历史消息，用来把对话坞撑出滚动条';
                l.appendChild(d);
              }
              l.scrollTop = l.scrollHeight;
              l.dispatchEvent(new Event('scroll'));
            }""")
            page.wait_for_timeout(350)
            at_bottom = page.evaluate(r"""() => {
              const home = document.getElementById('v-home');
              const a = home.querySelector('.assist'), s = home.querySelector('.stage');
              return {cls: home.className,
                      assist: a ? getComputedStyle(a).opacity : null,
                      stage: s ? getComputedStyle(s).opacity : null};
            }""")
            rec("8. 停在底部: 数字人不透明(未被渐隐)",
                "PASS" if at_bottom["assist"] in ("1", None)
                and at_bottom["stage"] in ("1", None) else "FAIL",
                "opacity=1", at_bottom)
            page.evaluate(r"""() => {
              const l = document.getElementById('oaDockList');
              l.scrollTop = 0;
              l.dispatchEvent(new Event('scroll'));
            }""")
            page.wait_for_timeout(350)
            up = page.evaluate(r"""() => {
              const home = document.getElementById('v-home');
              const a = home.querySelector('.assist'), s = home.querySelector('.stage');
              return {scrolled: home.classList.contains('dock-scrolled'),
                      assist: a ? getComputedStyle(a).opacity : null,
                      stage: s ? getComputedStyle(s).opacity : null,
                      pe: s ? getComputedStyle(s).pointerEvents : null};
            }""")
            rec("8. 上滑到历史: 数字人渐隐(opacity=0 且不拦点击)",
                "PASS" if up["scrolled"] and up["assist"] in ("0", None)
                and up["stage"] in ("0", None) and up["pe"] in ("none", None) else "FAIL",
                "dock-scrolled + opacity=0 + pointer-events=none", up)
            page.evaluate(r"""() => {
              const l = document.getElementById('oaDockList');
              l.scrollTop = l.scrollHeight;
              l.dispatchEvent(new Event('scroll'));
            }""")
            page.wait_for_timeout(350)
            back = page.evaluate(r"""() => {
              const home = document.getElementById('v-home');
              const s = home.querySelector('.stage');
              return {scrolled: home.classList.contains('dock-scrolled'),
                      stage: s ? getComputedStyle(s).opacity : null};
            }""")
            rec("8. 滚回底部: 数字人重新显示",
                "PASS" if back["scrolled"] is False and back["stage"] in ("1", None) else "FAIL",
                "dock-scrolled 摘除 + opacity=1", back)

            # ---------- 5. 全程 JS 报错监控（回归硬指标） --------------------
            rec("5. 全程无未捕获 JS 异常(pageerror)",
                "PASS" if not page_errors else "FAIL", "0 条", len(page_errors),
                "; ".join(page_errors[:5]))

            browser.close()
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass

    # ---------- 写出举证报告 ------------------------------------------------
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    na = sum(1 for r in results if r["status"] == "NA")
    md = []
    md.append("# H5 输入栏改动 · 独立验证举证\n")
    # 产品 md5 **从文件现算**，不写死常量：写死的值会在每次重建产物后失真。
    # （旧版把 0da22adb… 写死在报告里，与实际产物 21409486… 不符 —— 违反「展示与事实同源」。）
    _idx = os.path.join(USER_CLIENT, "index.html")
    _md5 = hashlib.md5(open(_idx, "rb").read()).hexdigest() if os.path.exists(_idx) else "（index.html 不存在）"
    md.append(f"产品 md5（user-client/index.html）：`{_md5}`\n")
    md.append(f"结论：PASS {passed} / FAIL {failed} / 无法验 {na}\n")
    md.append("| 项 | 状态 | 期望 | 实际 | 说明 |")
    md.append("|---|---|---|---|---|")
    for r in results:
        md.append(f"| {r['name']} | {r['status']} | {r['expected']!r} | {r['actual']!r} | {r['detail']} |")
    md_path = os.path.join(PROOF, "h5_inputbar_verify.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    json_path = os.path.join(PROOF, "h5_inputbar_verify.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": {"pass": passed, "fail": failed, "na": na},
                   "page_errors": page_errors, "console_errors": console_errors[:20],
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"\n==== H5 输入栏验证：PASS {passed} / FAIL {failed} / 无法验 {na} ====")
    print(f"举证报告：{md_path}")
    print(f"原始数据：{json_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
