# -*- coding: utf-8 -*-
"""执行意图修复的**真实浏览器点击**验收哨兵（2026-10，verify-ui-scenarios）。

只验收刚修好的三类缺陷（不读任何产品源码、不重启任何服务）：
  D1  项目上下文从未下发给 agent ⇒ 项目内问「上传文档」agent 反问「上传到哪个系统或平台」。
      已修：RunService 注入 project brief + _build_messages 注入「当前项目：《X》…不要反问在哪个系统或平台」。
  D2  Agent 能力否认 + 与 H5 矛盾：项目内说「上传文档」时 LLM 答「抱歉，我无法直接处理文件上传…
      请使用系统提供的文件上传功能」，而 H5 同时自己开上传窗。已修：按 detect_action 注入动作提示 + 全局禁止能力否认硬规则。
  D3  「新建数字人」被走成权限申请咨询（worker:manage / apply_permission）。真实创建权限是 worker:create（对全体开放）、
      worker:manage 不可申请。已修：新增 CREATE_WORKER 动作 + 提示词明确入口与权限口径。
  D4  界面调试信息已移除：经典 #chatModel 不再显示「模型：智能路由」；回答下方不再有「本次消耗 X 词元…」；
      OA 形态 onStarted/onUsage 删除对应 .bub-meta。
  D5  「我要请假」被模型自行调用 apply_permission 提前落库（打穿「用户可以取消」）。已修：新增 APPLY_LEAVE 动作
      + 提示词明确「动作只在用户点击时发生于界面，绝不在此代用户落库」+ 全局硬规则（写操作工具只在用户显式要求时调用）。
      本哨兵断言：裸请假语料回答不含「已为你提交/已帮你申请」这类与界面不符的话、含请假界面指引、
      且 permission_grant 无新增行（approval:leave 的 pending 不变）。

纪律（本仓库铁律）：
  · 判据不得与被测对象同源：直接读 DOM 的对话坞/消息真实渲染文本，不读 JS 变量副本。
  · SKIP 必须给可复核的具体前置（如「fagai_li 可见项目数=0」），不伪装 PASS。
  · 每个断言失败把**原文片段**打进 detail，便于归因。
  · 唯一允许用 JS 的例外：切形态 oaSetMode、只读取值、observer 安装。其余必须真实点击。

场景：
  S1 普通对话（经典形态）：新建数字人 → 断言回答不含能力否认/权限申请话术、含创建入口指引 →
      引导条出现「＋ 创建数字员工」且真点击它 → 进入创建流程（#pageTitle 含「创建数字员工」、#chatName==「数字员工管家」）。
  S2 项目内（OA 形态）：进入第一个可见项目 → 上传文档 → 断言真弹「上传项目文档」、对话坞不含能力否认/反问话术、
      回答含当前项目名、负向对照「请简单介绍一下你能做什么」不弹窗。

结构照抄 _verify_oa_intent_e2e.py：chk 累计 / report() 末尾打印并以失败数作退出码。
截图落 scripts/_shot_exec_intent/。
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
# fixture 成员 fagai_li（T1008 两项目成员，可见项目数 >=1）。wjj_xu 当前可见项目数=0，别用。
USER, PWD = 'fagai_li', 'User@123'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_exec_intent')

PASS, FAIL, SKIP = [], [], []
errors = []
shots = []


def chk(name, ok, detail=''):
    (PASS if ok else FAIL).append(name + (' — ' + str(detail) if detail else ''))
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    return ok


async def shot(page, name):
    p = os.path.join(OUT, name + '.png')
    await page.screenshot(path=p)
    shots.append(name)
    return p


def ctx_of(text, token, span=24):
    """提取 token 在 text 中首次出现的上下文片段（用于 FAIL 归因）。"""
    i = text.find(token)
    if i < 0:
        return ''
    a = max(0, i - span)
    b = min(len(text), i + len(token) + span)
    return ('…' if a > 0 else '') + text[a:b].replace('\n', ' ') + ('…' if b < len(text) else '')


async def install_mask_observer(page):
    """监听 document.body 下新增的 .notif-mask 节点，累计计数（负向对照用）。"""
    await page.evaluate("""() => {
      if(window.__maskObsInstalled) return;
      window.__maskAdds = 0;
      const obs = new MutationObserver(function(muts){
        muts.forEach(function(m){ m.addedNodes.forEach(function(n){
          if(n && n.nodeType === 1 && n.classList && n.classList.contains('notif-mask')) window.__maskAdds++;
        }); });
      });
      obs.observe(document.body, {childList:true, subtree:true});
      window.__maskObsInstalled = true;
    }""")


def report():
    print('\n截图：%d 张 → %s/' % (len(shots), OUT))
    print('通过：%d / 失败：%d / SKIP：%d' % (len(PASS), len(FAIL), len(SKIP)))
    for f in FAIL:
        print('  - FAIL ' + f)
    for s in SKIP:
        print('  - SKIP ' + s)
    if errors:
        print('控制台错误 %d 条：' % len(errors))
        for e in errors[:10]:
            print('  ' + e[:180])
    return 1 if FAIL else (2 if SKIP else 0)


async def login(page):
    """登录；会话由 localStorage 恢复时（reload 后）无登录表单，按已登录处理。"""
    await page.goto(BASE, wait_until='domcontentloaded')
    await page.wait_for_timeout(1300)
    lg = await page.query_selector('#lgUser')
    need_login = lg is not None and await lg.is_visible()
    if need_login:
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        try:
            await page.wait_for_selector('body.auth', timeout=15000)
        except Exception as e:
            chk('登录成功', False, str(e)[:80])
            await shot(page, '00-login-fail')
            return False
        chk('登录成功（%s）' % USER, True)
    else:
        # 会话已恢复（reload 后 token 仍在）：等待任一已登录态界面就绪
        try:
            await page.wait_for_function(
                "() => document.body.classList.contains('auth') || !!document.querySelector('.tab[data-page=\"page-chat\"]')",
                timeout=15000)
        except Exception as e:
            chk('登录成功（会话恢复）', False, str(e)[:80])
            await shot(page, '00-auth-restore-fail')
            return False
        chk('登录成功（会话恢复，token 仍在）', True)
    await page.wait_for_timeout(2000)
    return True


async def scenario_classic(page):
    print('\n===== 场景 1 · 普通对话（经典形态）=====')
    # 切经典形态（唯一允许的 JS 例外：切形态）
    await page.evaluate("() => { if(window.oaSetMode) window.oaSetMode('classic'); }")
    await page.wait_for_timeout(900)
    classic = await page.evaluate("() => !document.querySelector('.phone').classList.contains('oa-mode')")
    chk('S1 已切到经典形态（.phone 不含 oa-mode）', classic)
    # 经典形态默认落在 page-home，对话输入框在 page-chat（底部「对话」tab）→ 真实点击进入
    await page.click('.tab[data-page="page-chat"]')
    await page.wait_for_timeout(700)
    try:
        await page.wait_for_selector('#chatInput', state='visible', timeout=15000)
    except Exception as e:
        chk('S1 经典输入框 #chatInput 可见', False, str(e)[:80])
        await shot(page, 's1-input-invisible')
        return
    chk('S1 经典输入框 #chatInput 可见', True)

    # 真实点击：在经典输入框输入「新建数字人」→ 点发送按钮
    await page.fill('#chatInput', '新建数字人')
    await page.wait_for_timeout(400)  # 触发 input 事件 → #sendBtn 由 display:none 变可见
    # 发送按钮可见性（真实用户路径：有字才出现发送图标）
    snd_visible = await page.evaluate("""() => {
      const b = document.getElementById('sendBtn');
      if(!b) return false;
      return b.offsetParent !== null && getComputedStyle(b).display !== 'none';
    }""")
    chk('S1 发送按钮 #sendBtn 在输入后可见', snd_visible)
    await page.click('#sendBtn')

    # 等回答落定：默认 AI 会话回答后固定注入 .guide-block（afterAnswer 末尾）
    try:
        await page.wait_for_selector('#msgs .guide-block', timeout=90000)
        landed = True
    except Exception:
        landed = False
    if not landed:
        diag = await page.evaluate("() => { const m=document.getElementById('msgs'); return m?m.innerText:''; }")
        chk('S1 回答落定（出现 .guide-block 引导条）', False, '90s 内未出现引导条；对话=%s' % diag[:160])
        await shot(page, 's1-no-answer')
        return
    chk('S1 回答落定（出现 .guide-block 引导条）', True)

    # 取**回答原文**（最后一条 .msg 里的 .bubble，不含引导条 UI）
    ans = await page.evaluate("""() => {
      const bs = Array.from(document.querySelectorAll('#msgs .msg .bubble'));
      return bs.length ? bs[bs.length-1].innerText : '';
    }""")
    print('  [回答原文] ' + ans.replace('\n', ' ⏎ ')[:400])
    await shot(page, 's1-answer')

    # ---- 断言 3(a)：不含禁用词 ----
    hard_forbid = ['worker:manage', '我无法', '抱歉，我无法']
    hit = [w for w in hard_forbid if w in ans]
    chk('S1 回答不含能力否认/权限申请话术（worker:manage / 我无法 / 抱歉，我无法）',
        not hit, ('命中：' + ','.join(hit) + ' | ' + ctx_of(ans, hit[0])) if hit else '未命中')

    # ---- 断言 3(a)-申请语境（需人工复核）----
    if '申请' in ans:
        chk('S1 回答出现「申请」需人工判断是否属权限申请语境', False,
            '片段：' + ctx_of(ans, '申请'))
    else:
        chk('S1 回答未出现「申请」（无权限申请咨询语境）', True)

    # ---- 断言 3(b)：含创建入口指引 ----
    has_guide = ('创建数字员工' in ans) or ('专家与员工' in ans)
    chk('S1 回答含创建入口指引（含「创建数字员工」或「专家与员工」）',
        has_guide, (ans[:120] if not has_guide else '命中'))

    # ---- 断言 4：引导条出现「＋ 创建数字员工」并真点击 ----
    guide_label = await page.evaluate("""() => {
      const els = Array.from(document.querySelectorAll('#msgs .guide-block .guide-label'));
      const t = els.map(e => e.innerText.trim());
      return t;
    }""")
    has_create_entry = any('创建数字员工' in g for g in guide_label)
    chk('S1 引导条出现「＋ 创建数字员工」条目', has_create_entry, '引导条标签=' + str(guide_label))
    if not has_create_entry:
        await shot(page, 's1-no-guide-entry')
        return

    # 真点击（真实用户点击，触发 onclick=guidanceGo('create') → createAgentFlow()）
    await page.locator('#msgs .guide-block .guide-main', has_text='＋ 创建数字员工').first.click()
    try:
        await page.wait_for_function(
            """() => {
              const t = document.getElementById('pageTitle');
              const n = document.getElementById('chatName');
              return t && t.innerText.indexOf('创建数字员工') >= 0 && n && n.textContent.trim() === '数字员工管家';
            }""", timeout=15000)
        entered = True
    except Exception:
        entered = False
    if not entered:
        pv = await page.evaluate("() => { const t=document.getElementById('pageTitle'); const n=document.getElementById('chatName'); return (t?t.innerText:'')+' | '+(n?n.textContent:''); }")
        chk('S1 真点击后进入创建流程（#pageTitle 含「创建数字员工」且 #chatName==「数字员工管家」）',
            False, '当前：' + pv)
        await shot(page, 's1-not-entered')
        return
    chk('S1 真点击后进入创建流程（#pageTitle 含「创建数字员工」且 #chatName==「数字员工管家」）', True)
    await shot(page, 's1-entered-create')

    # ---- 断言 6（通用）：调试信息已消失 ----
    cmodel = await page.evaluate("() => { const e=document.getElementById('chatModel'); return e?e.textContent:''; }")
    chk('S1 调试信息消失：页头 #chatModel（.cmodel）不再含「模型：」', '模型：' not in cmodel, 'chatModel=%r' % cmodel)
    no_usage = ('本次消耗' not in ans) and ('模型：智能路由' not in ans) and ('模型：' not in ans)
    chk('S1 调试信息消失：回答不含「本次消耗」/「模型：智能路由」', no_usage,
        (ctx_of(ans, '本次消耗') or ctx_of(ans, '模型：')) if not no_usage else '未命中')


async def scenario_leave(page):
    """场景 3 · 裸请假语料不得触发 apply_permission 自动落库（D5）。

    真实浏览器发「我要请假两天」：模型被识别为 APPLY_LEAVE 动作、提示词要求「动作只在用户点击时
    发生于界面，绝不在此代用户落库」。断言：回答不含「已为你提交/已帮你申请」这类与界面不符的话、
    含请假界面指引（弹卡片/进入请假数字人/《请假申请》表单）、且 permission_grant 无新增行
    （approval:leave 的 pending 不变）。
    """
    print('\n===== 场景 3 · 裸请假语料（D5：不得自动落库）=====')
    await page.evaluate("() => { if(window.oaSetMode) window.oaSetMode('classic'); }")
    await page.wait_for_timeout(900)
    classic = await page.evaluate("() => !document.querySelector('.phone').classList.contains('oa-mode')")
    chk('S3 已切到经典形态（.phone 不含 oa-mode）', classic)
    await page.click('.tab[data-page="page-chat"]')
    await page.wait_for_timeout(700)
    try:
        await page.wait_for_selector('#chatInput', state='visible', timeout=15000)
    except Exception as e:
        chk('S3 经典输入框 #chatInput 可见', False, str(e)[:80])
        await shot(page, 's3-input-invisible')
        return
    chk('S3 经典输入框 #chatInput 可见', True)

    # 阈值前：记录当前 approval:leave 的 pending（无新 PENDING 应为 false）
    def catalog_leave():
        return page.evaluate("""async () => {
          try {
            const c = await API.permissionCatalog();
            const items = c.items || c.list || c;
            const it = (items||[]).find(x => x.permissionCode === 'approval:leave');
            return it ? {held: it.held, pending: it.pending} : {missing: true};
          } catch(e){ return {err: String(e)}; }
        }""")
    pre = await catalog_leave()
    print('  [catalog.pre] ' + str(pre))

    # 真实点击：输入裸请假语料 → 发送
    await page.fill('#chatInput', '我要请假两天')
    await page.wait_for_timeout(400)
    snd_visible = await page.evaluate("""() => {
      const b = document.getElementById('sendBtn');
      if(!b) return false;
      return b.offsetParent !== null && getComputedStyle(b).display !== 'none';
    }""")
    chk('S3 发送按钮 #sendBtn 在输入后可见', snd_visible)
    await page.click('#sendBtn')

    try:
        await page.wait_for_selector('#msgs .guide-block', timeout=90000)
        landed = True
    except Exception:
        landed = False
    if not landed:
        diag = await page.evaluate("() => { const m=document.getElementById('msgs'); return m?m.innerText:''; }")
        chk('S3 回答落定（出现 .guide-block 引导条）', False, '90s 内未出现引导条；对话=%s' % diag[:160])
        await shot(page, 's3-no-answer')
        return
    chk('S3 回答落定（出现 .guide-block 引导条）', True)

    ans = await page.evaluate("""() => {
      const bs = Array.from(document.querySelectorAll('#msgs .msg .bubble'));
      return bs.length ? bs[bs.length-1].innerText : '';
    }""")
    print('  [回答原文] ' + ans.replace('\n', ' ⏎ ')[:400])
    await shot(page, 's3-answer')

    # ---- 断言 a：不含与界面不符的「已提交/已申请」话术 ----
    auto_apply_words = ['已为你提交', '已帮你申请', '已经提交', '已申请（', '已帮你提交了', '申请已提交', '已为你申请']
    hit = [w for w in auto_apply_words if w in ans]
    chk('S3 回答不含「已提交/已帮你申请」这类与界面不符的话（动作由界面点击触发）',
        not hit, ('命中：' + ','.join(hit) + ' | ' + ctx_of(ans, hit[0])) if hit else '未命中')

    # ---- 断言 b：含请假界面指引（弹卡片 / 进入请假数字人 / 《请假申请》表单）----
    has_guide = any(k in ans for k in ('请假审批', '请假数字人', '请假申请', '权限', '卡片', '帮我申请', '取消'))
    chk('S3 回答含请假界面指引（提及请假审批/数字人/申请表单/帮我申请）',
        has_guide, (ans[:160] if not has_guide else '命中'))

    # ---- 断言 c：permission_grant 无新增行（approval:leave 的 pending 不变）----
    await page.wait_for_timeout(2500)  # 等可能的异步落库窗口
    post = await catalog_leave()
    print('  [catalog.post] ' + str(post))
    if pre.get('missing') or post.get('missing'):
        chk('S3 目录含 approval:leave（可比对 pending）', False, 'pre=%s post=%s' % (pre, post))
    else:
        chk('S3 approval:leave 的 pending 未因裸请假语料变 true（无新增 grant 行）',
            post.get('pending') == pre.get('pending') and post.get('pending') is False,
            'pre.pending=%s post.pending=%s' % (pre.get('pending'), post.get('pending')))



async def scenario_oa(page):
    print('\n===== 场景 2 · 项目内（OA 形态）=====')
    # 重新加载并登录（场景 1 已切经典 + 进过创建流程，避免状态污染）
    if not await login(page):
        return
    await page.evaluate("() => { if(window.oaSetMode) window.oaSetMode('oa'); }")
    await page.wait_for_timeout(800)
    oa = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
    chk('S2 已切到 OA 形态（.phone.oa-mode 生效）', oa)

    await install_mask_observer(page)

    await page.click('#oaTabs .tab[data-view="collab"]')
    await page.wait_for_timeout(800)
    await page.click('#oaRail .rail-item[data-panel="projects"]')
    try:
        await page.wait_for_function(
            """() => {
              const el = document.getElementById('p-projects');
              if(!el) return false;
              if(el.querySelector('[data-project]')) return true;
              return el.innerText.indexOf('暂无可见项目') >= 0;
            }""", timeout=15000)
    except Exception:
        pass
    n_cards = await page.evaluate("() => document.querySelectorAll('#p-projects [data-project]').length")
    if n_cards == 0:
        why = await page.evaluate("""() => { const el=document.getElementById('p-projects'); return el?el.innerText.slice(0,80):'面板缺失'; }""")
        SKIP.append('S2 进入项目')
        print('  SKIP S2 进入项目 | 该账号当前没有可见项目（卡片数=0）：%s' % why)
        await shot(page, 's2-no-project')
        return
    await page.click('#p-projects [data-project]')
    try:
        await page.wait_for_function("() => !!(window.oaState && window.oaState.currentProject)", timeout=20000)
    except Exception as e:
        chk('S2 进入项目：window.oaState.currentProject 非空', False, str(e)[:80])
        await shot(page, 's2-project-fail')
        return
    cp = await page.evaluate("() => window.oaState.currentProject")
    pname = (cp or {}).get('name', '')
    chk('S2 进入项目：currentProject 非空（以状态对象为真值源）', bool(cp and cp.get('id')), cp)
    print('  [项目名] ' + pname)
    await page.wait_for_timeout(1500)
    await shot(page, 's2-in-project')

    # 分类器环境探针（agent :8000）：离线则后续拿不到 action → SKIP（环境），不硬跑断言
    probe = await page.evaluate("""async () => {
      try { const r = await API.workerIntent('上传文档'); return { action: (r && r.action) || null }; }
      catch(e){ return { action: 'ERR:' + (e && e.message || e) }; } }""")
    if not probe.get('action') or str(probe.get('action')).startswith('ERR'):
        SKIP.append('S2 上传意图（分类器）')
        print('  SKIP S2 上传意图 | 意图分类器不可用（agent :8000）：%s' % probe)
        await shot(page, 's2-classifier-offline')
        return

    # ---- 断言 a：真弹「上传项目文档」窗口（含 #upFile）----
    await page.fill('#oaInput', '上传文档')
    await page.wait_for_timeout(300)
    await page.click('#oaSendBtn')
    try:
        await page.wait_for_function(
            """() => { const m=document.querySelector('.notif-mask'); return !!m && !!m.querySelector('#upFile'); }""",
            timeout=90000)
        mask_ok = True
    except Exception:
        mask_ok = False
    if not mask_ok:
        diag = await page.evaluate("() => { const el=document.getElementById('oaDockList'); return el?el.innerText:''; }")
        chk('S2 a) 真弹出「上传项目文档」窗口（含 #upFile）', False, '90s 内未出现；对话坞=%s' % diag[:160])
        await shot(page, 's2-no-mask')
    else:
        head = await page.evaluate("""() => { const m=document.querySelector('.notif-mask'); const h=m&&m.querySelector('.notif-head'); return h?h.textContent.trim():''; }""")
        chk('S2 a) 窗口标题 == 「上传项目文档」', head == '上传项目文档', head)
        await shot(page, 's2-upload-window')

        # 关闭窗口，避免残留影响后续断言
        await page.evaluate("""() => { const m=document.querySelector('.notif-mask'); const c=m&&m.querySelector('[data-dlg-cancel]'); if(c) c.click(); }""")
        await page.wait_for_timeout(400)
        n_mask = await page.evaluate("() => document.querySelectorAll('.notif-mask').length")
        chk('S2 a) 关闭后 .notif-mask 计数回到 0', n_mask == 0, 'count=%d' % n_mask)

    # ---- 取对话坞真实渲染文本（含 agent 回答）----
    # OA 形态气泡类名是 .bub.ai（_oa_app.js oaPushBub），**不是**经典的 .msg .bubble（旧选择器匹配 0 元素 ⇒ 恒空 ⇒ 断言恒假）。
    # 其中 agent 的流式回答额外带 .ans（_oa_app.js:1666，仅在真产出回答时加），H5 自造的信息泡不带 —— 用 .bub.ai.ans 精确取「回答」。
    dock = await page.evaluate("() => { const el=document.getElementById('oaDockList'); return el?el.innerText:''; }")
    act_probe = await page.evaluate("""() => {
      const all = Array.from(document.querySelectorAll('#oaDockList .bub.ai'));
      const ans = Array.from(document.querySelectorAll('#oaDockList .bub.ai.ans'));
      const lastOf = arr => { for(let i=arr.length-1;i>=0;i--){ const t=(arr[i].innerText||'').trim(); if(t) return t; } return ''; };
      return { last: lastOf(all), lastAns: lastOf(ans), nAns: ans.length }; }""")
    print('  [动作轮最后一条 ai 泡] ' + act_probe['last'].replace('\n', ' ⏎ ')[:300])
    print('  [动作轮 agent 回答 .ans] ' + act_probe['lastAns'].replace('\n', ' ⏎ ')[:300])

    # ---- 断言 b：对话坞不含能力否认/反问话术 ----
    forbid = ['我无法', '抱歉，我无法', '请使用系统', '哪个系统或平台', '哪个平台']
    hit = [w for w in forbid if w in dock]
    chk('S2 b) 对话坞不含能力否认/反问话术（我无法/抱歉，我无法/请使用系统/哪个系统或平台/哪个平台）',
        not hit, ('命中：' + ','.join(hit) + ' | ' + ctx_of(dock, hit[0])) if hit else '未命中')

    # ---- 断言 c0：动作轮**确实产出了 agent 回答**（onUsage 崩溃回归哨兵）----
    # 旧缺陷：共享消费器无守卫调用 h.onUsage ⇒ OA 处理器未定义 ⇒ 整条回答流抛 TypeError ⇒
    #        气泡被写成「请求失败：h.onUsage is not a function」且**不加 .ans**、上传窗不弹。
    chk('S2 c0) ★ 动作轮产出了 agent 回答且非失败态（onUsage 崩溃回归哨兵：无 .ans 或出现「请求失败/生成失败」即红）',
        bool(act_probe['lastAns']) and act_probe['nAns'] >= 1
        and '请求失败' not in act_probe['lastAns'] and '生成失败' not in act_probe['lastAns'],
        'lastAns=%s | .bub.ai.ans 计数=%d' % (act_probe['lastAns'][:120], act_probe['nAns']))

    # ---- 断言 c：项目上下文真下发给 agent（判据必须回事实源头，不得与 H5 同源）----
    # 坑一：上传动作的短回复**不含**项目名（模型只答「正在为你打开上传窗口」）⇒ 动作轮回答不能当判据（API 侧 E5 同坑）。
    # 坑二：「好的，正在打开…登记到当前项目《X》」这条气泡是 H5 用 S.currentProject.name **自己拼**的，
    #       与「agent 是否收到项目上下文」同源（铁律12）—— 旧断言正是栽在这里（选择器还错，双错叠加）。
    # 正解：追问一句「我当前在哪个项目里？」，只有 agent 真拿到 project brief 才答得出项目名。
    await page.fill('#oaInput', '我当前在哪个项目里？')
    await page.wait_for_timeout(300)
    await page.click('#oaSendBtn')
    try:
        await page.wait_for_function("() => !window.oaState.busy", timeout=90000)
    except Exception:
        pass
    await page.wait_for_timeout(2500)
    ctx_ans = await page.evaluate("""() => {
      const ms = Array.from(document.querySelectorAll('#oaDockList .bub.ai.ans'));
      for(let i=ms.length-1;i>=0;i--){ const t=(ms[i].innerText||'').trim(); if(t) return t; }
      return ''; }""")
    print('  [项目上下文追问回答] ' + ctx_ans.replace('\n', ' ⏎ ')[:400])
    chk('S2 c) ★ 追问「我当前在哪个项目里？」的回答含项目名「%s」（证明 agent 真拿到项目上下文）' % pname,
        bool(pname) and pname in ctx_ans, ('未出现；回答=%s' % ctx_ans[:200]) if pname else '项目名为空')

    # ---- 断言 d：负向对照（判据必须能红）----
    await page.evaluate("() => { window.__maskAdds = 0; }")
    await page.fill('#oaInput', '请简单介绍一下你能做什么')
    await page.wait_for_timeout(300)
    await page.click('#oaSendBtn')
    try:
        await page.wait_for_function("() => !window.oaState.busy", timeout=90000)
    except Exception:
        pass
    await page.wait_for_timeout(8000)
    neg = await page.evaluate("""() => ({ adds: window.__maskAdds, live: document.querySelectorAll('.notif-mask').length })""")
    chk('S2 d) ★ 负向对照：非动作语句全程未弹任何 .notif-mask 窗口',
        neg['adds'] == 0 and neg['live'] == 0, neg)
    await shot(page, 's2-negative')

    # ---- 断言 6（通用）：调试信息已消失 ----
    bub_meta = await page.evaluate("""() => {
      const els = Array.from(document.querySelectorAll('#oaDockList .bub-meta'));
      return els.map(e => e.innerText.trim()); }""")
    bad_meta = [m for m in bub_meta if ('模型：' in m) or ('本次消耗' in m)]
    chk('S2 调试信息消失：OA 气泡 .bub-meta 不含「模型：」/「本次消耗」（已选择数字员工/专家属保留项）',
        not bad_meta, ('残留：' + str(bad_meta[:3]) if bad_meta else '无 bub-meta 残留') + ' | 全部bub-meta=%s' % bub_meta)
    no_usage = ('本次消耗' not in dock) and ('模型：智能路由' not in dock)
    chk('S2 调试信息消失：对话坞不含「本次消耗」/「模型：智能路由」',
        no_usage, (ctx_of(dock, '本次消耗') or ctx_of(dock, '模型：智能路由')) if not no_usage else '未命中')


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                         device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('console', lambda m: errors.append('console.' + m.type + ': ' + m.text)
                if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))

        # 场景 1：需先登录再切经典
        if not await login(page):
            await browser.close()
            return report()
        await scenario_leave(page)
        await scenario_classic(page)

        # 场景 2：重新加载并登录、切 OA
        await scenario_oa(page)

        # 控制台无未捕获错误
        chk('控制台无 error / 无未捕获异常', len(errors) == 0, errors[:5])

        await browser.close()
    return report()


if __name__ == '__main__':
    try:
        rc = asyncio.run(main())
    except Exception as exc:
        chk('流程未跑完（异常中断）', False, '%s: %s' % (type(exc).__name__, str(exc)[:160]))
        rc = 1
    sys.exit(rc or (1 if FAIL else 0))
