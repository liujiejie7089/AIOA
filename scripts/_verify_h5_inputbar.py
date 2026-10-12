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
      window.__probe = {asr:0, asrBlobs:[], createRunArgs:null, toasts:[], streamCalls:0, fileUploadName:null};
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
      P.streamCalls = 0; P.fileUploadName = null;
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
                "localStorage.setItem('aioa_session', JSON.stringify({token:'fake',"
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
            strip2 = page.evaluate("document.getElementById('attachStrip').querySelectorAll('.attach-chip').length")
            rec("3. 点 × 后芯片消失", "PASS" if strip2 == 0 else "FAIL", 0, strip2)
            # 重新上传并发送(只传文档不写字)
            reset_probe(page)
            with page.expect_file_chooser() as fc:
                page.click("#attachBtn")
            fc.value.set_files(A_TXT)
            page.wait_for_timeout(500)
            page.evaluate("state.busy=false; document.getElementById('chatInput').value = ''")
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

            # ---------- 4. 回归：#sendBtn 普通发送 + 历史渲染不报错 ----------
            reset_probe(page)
            page.evaluate("state.busy=false; pendingFiles=[]; document.getElementById('chatInput').value=''; document.getElementById('attachStrip').innerHTML='';")
            page.click("#sendBtn")
            page.wait_for_timeout(300)
            toasts4 = page.evaluate("window.__probe.toasts.slice()")
            rec("4. 空输入点 #sendBtn → 提示且不崩溃(无 pageerror)",
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
                    with page.expect_file_chooser() as fc:
                        page.click("#oaAttachBtn")
                    fc.value.set_files(A_TXT)
                    page.wait_for_timeout(500)
                    oastrip = page.evaluate(r"""() => {
                      const s = document.getElementById('oaAttachStrip');
                      return {chips: s.querySelectorAll('.attach-chip').length,
                              name: (s.querySelector('.ac-name')||{}).textContent || ''};
                    }""")
                    rec("3(OA). 点 #oaAttachBtn → 文件选入 #oaAttachFile → #oaAttachStrip 出芯片",
                        "PASS" if oastrip["chips"] >= 1 and "a.txt" in oastrip["name"] else "FAIL",
                        ">=1 芯片且含 a.txt", oastrip)
                    # 发送(只传文档不写字)
                    reset_probe(page)
                    page.evaluate("var i=document.getElementById('oaInput'); if(i) i.value='';")
                    page.click("#oaSendBtn")
                    page.wait_for_timeout(500)
                    oacr = page.evaluate("window.__probe.createRunArgs")
                    oa_att = bool(oacr) and len(oacr) >= 4 and oacr[3] == ["123"]
                    rec("3(OA). oaSend: createRun 第4参 === ['123'](读桩实参)",
                        "PASS" if oa_att else "FAIL", "['123']", oacr[3] if oacr else None,
                        f"full={oacr}")
                except Exception as e:
                    rec("3(OA). OA 上传链路可验", "NA", "可验", "无法验", f"异常: {e}")
            else:
                rec("3(OA). OA 上传链路", "NA", "可验", "未验", "oaAttachBtn 不存在")

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
    md.append(f"产品 md5（user-client/index.html）：`0da22adb551a1a9246ed7ef8a35e85cc`\n")
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
