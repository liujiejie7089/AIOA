#!/usr/bin/env python3
"""OA 形态端到端自检（Playwright + msedge 无头，390x844 @2x）。

覆盖：
  A 经典形态回归      —— 登录后五个 Tab 逐个走查，console 无错、无横向溢出
  B 双形态切换        —— 经典「我的」单按钮 → 新版；OA「我的」单按钮 → 回经典；刷新后记忆
  C OA 五个主视图     —— 首页 / 任务 / 知识库 / 部门 / 我的
     C9 账户四内页    —— 额度与账单 / 操作记录 / 权限申请 / 投诉与建议：全部留在新版内，
                        判据查「逃逸后果」（oa-mode / mode / localStorage）而非某经典页有无 .active
  D 数字人链路        —— 点击 → 选择卡 → 数字员工清单 → 原地对话坞（不跳转）
  E 气泡三角几何      —— 逐气泡比对「计算方向角 θ+90°」与「实际 --tail-angle」，误差 < 1°
  F 抽屉与子页        —— 抽屉、定时任务、插件-技能、最近会话
  H 职责推荐与表单直出 —— 回答后按职责推荐更对口的数字人（理由必须来自后端分类器）、
                        点名称直接更换（并换会话）、请假表单由数字人当场给出（两个条件缺一不可）、
                        两形态共用同一 id 时互不遮挡
输出：scripts/_shot_oa/*.png + 控制台逐项结论
退出码非零 = 有断言失败。
"""
import asyncio
import json
import math
import os
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'          # 普通成员（科员）：覆盖 ROLE_MEMBER 视角
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_oa')

errors, fails, notes, shots = [], [], [], []


def chk(name, ok, detail=''):
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


async def no_overflow(page, where):
    v = await page.evaluate("() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})")
    chk('横向溢出=0 · ' + where, v['sw'] <= v['cw'] + 1, 'scrollWidth=%s clientWidth=%s' % (v['sw'], v['cw']))


# 「回答」里出现这些字样 = 这一轮根本没有产出正文（额度耗尽 / 后端报错 / 未返回）。
# 必须**单列一条断言**判它：否则「回答已收口（有正文）」会被一条 27 字的错误文案满足，
# 真因（环境额度耗尽）就被后面一连串「推荐块没出现」误报成功能缺陷 —— 实测踩过一次。
# 用**完整错误句**而不是裸词：请假表单里就有「年假/病假/事假（不占额度）」，
# 用裸词 `额度` 会把一张正常发出的表单判成环境错误（也实测踩过一次）。
ENV_ERR_WORDS = ('免费额度已用完', '额度已用完', '额度不足', '请求失败：', '生成失败：',
                 '本次未返回内容', '请检查网络或后端服务')


def chk_answered(tag, r):
    """断言这一轮真的产出了正文，并把「这是环境错误文案」直接写在结论里。"""
    text = str(r.get('text', ''))
    bad = [w for w in ENV_ERR_WORDS if w in text]
    ok = r['answerLen'] > 0 and not bad
    detail = {'len': r['answerLen'], 'text': text[:60]}
    if not ok:
        detail['归因'] = ('【环境】回答是错误文案而非正文（命中 %s）——先修环境（如额度）'
                          '再看后面各条，别当成功能缺陷' % bad) if bad else '回答为空'
    return chk(tag, ok, detail)


async def shot(page, name):
    p = os.path.join(OUT, name + '.png')
    await page.screenshot(path=p)
    shots.append(name)
    return p


async def tail_geometry(page):
    """逐气泡比对三角方向角。计算口径与页面内 oaLayoutTails 完全独立，避免自证。"""
    return await page.evaluate("""() => {
      const home = document.getElementById('v-home');
      if(!home || !home.classList.contains('chatting')) return {skip:'未进入对话态'};
      const anchor = home.querySelector('.robot-wrap');
      if(!anchor) return {skip:'未找到数字人锚点'};
      const r = anchor.getBoundingClientRect();
      const A = {x: r.left + r.width/2, y: r.top + r.height/2};
      const out = [];
      home.querySelectorAll('.bub').forEach(b => {
        const t = b.querySelector('.tail');
        if(!t) return;                       // 三角缺失本身由 E2 断言兜底，这里不制造假阴性
        const br = b.getBoundingClientRect();
        const cx = br.left + br.width/2, cy = br.top + br.height/2;
        const theta = Math.atan2(A.y - cy, A.x - cx);
        let expect = (theta + Math.PI/2) * 180 / Math.PI;
        /* 取**计算值**而非内联值：内联值把「JS 把变量写在哪个节点」这个实现细节焊进了断言，
           变量一旦改写到宿主（.bub）上，内联读法就恒得 0、误报「三角没落位」。
           计算值带继承，写在宿主还是三角节点都读得到真实渲染结果。 */
        let got = parseFloat(getComputedStyle(t).getPropertyValue('--tail-angle')) || 0;
        let d = Math.abs(expect - got) % 360;
        if (d > 180) d = 360 - d;
        out.push({err: +d.toFixed(3), expect: +expect.toFixed(2), got: +got.toFixed(2)});
      });
      const total = home.querySelectorAll('.bub').length;
      return {items: out, bubbles: total, tails: home.querySelectorAll('.bub .tail').length};
    }""")


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

        # ---------------- 登录 ----------------
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        try:
            await page.wait_for_selector('body.auth', timeout=15000)
        except Exception as e:
            chk('登录成功', False, str(e)[:80])
            await shot(page, '00-login-fail')
            await browser.close()
            return report()
        chk('登录成功（%s）' % USER, True)
        await page.wait_for_timeout(2500)

        # ---------------- A. 默认形态 + 经典形态回归 ----------------
        # A0 全新访客默认进入新版（本轮口径翻转：原为「默认经典」）。
        #    判据必须是「默认」本身，故先确认本上下文没有 aioa_mode 记忆 ——
        #    否则测到的是「记忆」而不是「默认」，换个浏览器就是另一个结果。
        fresh = await page.evaluate("""() => ({
          om: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: state.mode,
          ls: localStorage.getItem('aioa_mode'),
          oaTabbar: getComputedStyle(document.getElementById('oaTabs')).display,
          classicPages: getComputedStyle(document.querySelector('.pages')).display
        })""")
        chk('A0 全新访客默认进入新版（oa-mode / mode=oa / 无记忆 / 经典层隐藏）',
            fresh['om'] is True and fresh['mode'] == 'oa' and fresh['ls'] is None
            and fresh['oaTabbar'] != 'none' and fresh['classicPages'] == 'none', fresh)
        await shot(page, '01-oa-default-home')

        # A1 新版「我的」的镜像按钮可切到经典 —— 切过去是为了跑下面的经典回归；
        #    这一步同时也覆盖了「新版里那个按钮真的能出去」。
        await page.click('#oaTabs .tab[data-view="me"]')
        await page.wait_for_timeout(600)
        await page.click('#oaMeSwitch')
        await page.wait_for_timeout(900)
        sw = await page.evaluate("""() => ({
          om: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: state.mode,
          ls: localStorage.getItem('aioa_mode'),
          classicTabbar: getComputedStyle(document.querySelector('.phone > .tabbar')).display,
          oaRoot: getComputedStyle(document.getElementById('oaRoot')).display })""")
        chk('A1 新版「我的」按钮切到经典形态（并写入记忆）',
            sw['om'] is False and sw['mode'] == 'classic' and sw['ls'] == 'classic'
            and sw['classicTabbar'] != 'none' and sw['oaRoot'] == 'none', sw)

        for pid, label in [('page-home', '工作台'), ('page-todo', '待办'),
                           ('page-chat', '会话'), ('page-agent', '专家与员工')]:
            await page.evaluate("(p) => switchTabById(p)", pid)
            await page.wait_for_timeout(450)
            vis = await page.evaluate("(p) => document.getElementById(p).classList.contains('active')", pid)
            chk('A2 经典 Tab「%s」可进入' % label, vis)
            await no_overflow(page, '经典·' + label)
        await page.evaluate("() => switchTabById('page-me')")
        await page.wait_for_timeout(600)
        # 经典「我的」的布局切换：单个按钮，钉在名字最右侧；原「界面版本」分段控件已移除
        cme = await page.evaluate("""() => {
          const b = document.getElementById('classicMeSwitch');
          const n = document.getElementById('meName');
          const seg = document.querySelector('#classicSeg');
          if(!b || !n) return {ok:false, why:'按钮或名字缺失'};
          const rb = b.getBoundingClientRect(), rn = n.getBoundingClientRect();
          return {ok:true, text: b.textContent.trim(),
                  rightOfName: rb.left > rn.right - 1,
                  sameRow: rb.top < rn.bottom && rb.bottom > rn.top,
                  segGone: seg === null,
                  btnRight: Math.round(rb.right), nameRight: Math.round(rn.right),
                  vw: document.documentElement.clientWidth};
        }""")
        chk('A3 经典「我的」布局控件=名字最右侧单个按钮',
            cme.get('ok') and cme['text'] == '切换布局' and cme['rightOfName']
            and cme['sameRow'] and cme['segGone'], cme)
        await shot(page, '01-classic-me-with-switch')

        # A4-A6 经典形态回归：本轮把账单/留痕/额度的口径抽成了共享纯函数
        # （billTokens / logIsOk / quotaNumbers / fbRouteLine），被抽走的实现若漏接线，
        # 现象是经典页静默变空白 —— 这里按「容器已渲染」判定，不依赖是否真有数据。
        cl = await page.evaluate("""() => ({
          meName: (document.getElementById('meName')||{}).textContent,
          meRole: (document.getElementById('meRole')||{}).textContent,
          quotaNum: (document.getElementById('quotaNum')||{}).textContent,
          bill: (document.getElementById('billList')||{}).innerHTML || '',
          log: (document.getElementById('logList')||{}).innerHTML || '',
          fbRoute: (document.getElementById('fbRouteHint')||{}).innerHTML || ''
        })""")
        chk('A4 经典「我的」姓名/身份/额度均已渲染',
            cl['meName'] not in (None, '', '—') and cl['meRole'] not in (None, '', '—')
            and cl['quotaNum'] not in (None, ''),
            {'name': cl['meName'], 'role': cl['meRole'], 'quota': cl['quotaNum']})
        chk('A5 经典「用量账单」「我的操作记录」容器已渲染',
            len(cl['bill'].strip()) > 0 and len(cl['log'].strip()) > 0,
            {'billLen': len(cl['bill']), 'logLen': len(cl['log'])})
        chk('A6 经典「投诉与建议」路由说明已渲染', len(cl['fbRoute'].strip()) > 0,
            cl['fbRoute'][:60])

        # ---------------- B. 切换到 OA ----------------
        await page.click('#classicMeSwitch')
        await page.wait_for_timeout(1200)
        st = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: state.mode,
          ls: localStorage.getItem('aioa_mode'),
          /* #oaTabs 自身的 computed display 恒为 flex —— oa-mode 之外是由祖先
             .oa 整体 display:none 收起的。所以「可见」只能问 .oa 容器本身，
             问 #oaTabs 得到的是恒真值（原 B2 就是这样一条假断言）。 */
          oaRoot: getComputedStyle(document.getElementById('oaRoot')).display,
          classicTabbar: getComputedStyle(document.querySelector('.phone > .tabbar')).display,
          pages: getComputedStyle(document.querySelector('.pages')).display
        })""")
        chk('B1 切到 OA：.phone.oa-mode 生效', st['oa'] is True, st)
        chk('B2 OA 外壳可见、经典底部菜单隐藏', st['oaRoot'] != 'none' and st['classicTabbar'] == 'none', st)
        chk('B3 经典页面层隐藏', st['pages'] == 'none', st)
        chk('B4 模式写入本地记忆', st['ls'] == 'oa', 'aioa_mode=%s' % st['ls'])
        await shot(page, '02-oa-home')

        # 显式回到 OA 首页：本轮是从新版「我的」切出去再切回来的，S.view 还停在 me。
        # 不点回首页，下面 C1/C2 读到的是「上一次渲染留在 DOM 里的旧值」——
        # 看着是绿的，实际测的是缓存，这类假绿比失败更危险。
        await page.click('#oaTabs .tab[data-view="home"]')
        await page.wait_for_timeout(900)

        # C. 首页数据
        home = await page.evaluate("""() => ({
          k1: document.getElementById('oaK1').textContent,
          k2: document.getElementById('oaK2').textContent,
          k3: document.getElementById('oaK3').textContent,
          k4: document.getElementById('oaK4').textContent,
          robot: (function(){ const i = document.querySelector('#oaRobot img');
            return i ? (i.complete && i.naturalWidth > 0 ? 'loaded' : 'broken') : 'missing'; })()
        })""")
        chk('C1 数字人位图已内联且加载成功', home['robot'] == 'loaded', home['robot'])
        chk('C2 首页四枚指标已接真实数据（非占位符）',
            all('—' not in home[k] for k in ('k1', 'k2', 'k3', 'k4')), home)
        await no_overflow(page, 'OA·首页')

        # ---------------- D. 数字人链路 ----------------
        await page.click('#oaRobot')
        await page.wait_for_timeout(500)
        sheet = await page.evaluate("""() => ({
          open: document.querySelector('#oaRoot').classList.contains('sheet-open'),
          w: document.getElementById('oaSheetWN').textContent,
          e: document.getElementById('oaSheetEN').textContent })""")
        chk('D1 点数字人弹出选择卡', sheet['open'] is True, sheet)
        await shot(page, '03-sheet-choose')
        await page.click('#oaSheet .sheet-opt[data-target="workers"]')
        await page.wait_for_timeout(900)
        sig = await page.evaluate("""() => ({
          view: window.oaState.view,
          stillOa: document.querySelector('.phone').classList.contains('oa-mode'),
          classicChat: document.getElementById('page-chat').classList.contains('active'),
          n: document.querySelectorAll('#oaWorkersList [data-worker]').length })""")
        chk('D2 进入数字员工清单（仍在 OA 层内）', sig['view'] == 'workers' and sig['stillOa'], sig)
        chk('D3 未跳到经典会话页（不跳转）', sig['classicChat'] is False, sig)
        chk('D4 数字员工清单来自接口且非空', sig['n'] > 0, 'N=%s' % sig['n'])
        await shot(page, '04-oa-workers')

        if sig['n'] > 0:
            await page.click('#oaWorkersList [data-worker]')
            await page.wait_for_timeout(900)
            pick = await page.evaluate("""() => ({
              view: window.oaState.view,
              chatting: document.getElementById('v-home').classList.contains('chatting'),
              bar: (function(){ const d = document.querySelector('.dock-list .oa-who');
                     return d ? d.textContent : null; })(),
              bubbles: document.querySelectorAll('.bub').length })""")
            chk('D5 选中后回到首页并进入对话态（原地）',
                pick['view'] == 'home' and pick['chatting'], pick)
            chk('D6 对话坞已出现气泡', pick['bubbles'] > 0, pick)
            await shot(page, '05-oa-dock-chat')

            # 发一条消息：只断言「用户气泡立即出现 + 三角落位」，不依赖模型是否可用
            await page.fill('#oaInput', '你好，请简单介绍一下你能做什么')
            await page.click('#oaSendBtn')
            await page.wait_for_timeout(2500)
            await shot(page, '06-oa-dock-sending')

            geo = await tail_geometry(page)
            if geo.get('skip'):
                chk('E1 三角几何可测', False, geo['skip'])
            else:
                items = geo['items']
                worst = max((i['err'] for i in items), default=0)
                chk('E1 气泡三角朝向数字人（误差 < 1°，共 %d 个气泡）' % len(items),
                    bool(items) and worst < 1.0, '最大误差 %s°' % worst)
                chk('E3 每个气泡都有三角节点（流式写入不得抹掉它）',
                    geo.get('tails') == geo.get('bubbles'),
                    'bubbles=%s tails=%s' % (geo.get('bubbles'), geo.get('tails')))
                # 三角落位必须在气泡边框上（不在内部漂移）
                on_edge = await page.evaluate("""() => {
                  const out = [];
                  document.querySelectorAll('.bub').forEach(b => {
                    const br = b.getBoundingClientRect();
                    const tcs = getComputedStyle(b.querySelector('.tail'));
                    const x = parseFloat(tcs.getPropertyValue('--tail-x'));
                    const y = parseFloat(tcs.getPropertyValue('--tail-y'));
                    const eps = 1.5;
                    const okX = Math.abs(x) <= eps || Math.abs(x - br.width) <= eps;
                    const okY = Math.abs(y) <= eps || Math.abs(y - br.height) <= eps;
                    out.push(okX || okY);
                  });
                  return out;
                }""")
                chk('E2 三角落位在气泡边框上', all(on_edge), on_edge)

            # E4 切走再切回首页：气泡若是在别的视图里追加的（首页当时 display:none，
            #    量到零矩形），回到首页必须重新落位 —— 否则那批三角停在初始态 0deg。
            await page.click('#oaTabs .tab[data-view="kb"]')
            await page.wait_for_timeout(700)
            await page.click('#oaTabs .tab[data-view="home"]')
            await page.wait_for_timeout(900)
            geo2 = await tail_geometry(page)
            if geo2.get('skip'):
                chk('E4 切回首页后三角几何可测', False, geo2['skip'])
            else:
                items2 = geo2['items']
                worst2 = max((i['err'] for i in items2), default=999)
                chk('E4 切走再切回首页后三角仍指向数字人（误差 < 1°，共 %d 个）' % len(items2),
                    bool(items2) and worst2 < 1.0,
                    '最大误差 %s°' % worst2)

            # E5 窄视口 320px：原实现在 <360px 时退化成「恒朝正上方」，
            #    那就不再指向数字人了 —— 这里正是为「指向」这一条补的边界断言。
            await page.set_viewport_size({'width': 320, 'height': 844})
            await page.wait_for_timeout(700)
            await page.evaluate("() => window.oaLayoutTails()")
            await page.wait_for_timeout(250)
            geo3 = await tail_geometry(page)
            if geo3.get('skip'):
                chk('E5 窄视口下三角几何可测', False, geo3['skip'])
            else:
                items3 = geo3['items']
                worst3 = max((i['err'] for i in items3), default=999)
                chk('E5 窄视口 320px 下三角仍指向数字人（误差 < 1°，共 %d 个）' % len(items3),
                    bool(items3) and worst3 < 1.0,
                    '最大误差 %s°' % worst3)
            await shot(page, '06b-oa-narrow-320')
            await page.set_viewport_size({'width': 390, 'height': 844})
            await page.wait_for_timeout(700)
            await page.evaluate("() => window.oaLayoutTails()")

        await page.evaluate("() => window.oaSetMode && window.oaSetMode('oa')")
        await page.wait_for_timeout(400)

        # ---------------- C2. 其余 OA 主视图 ----------------
        for view, label in [('collab', '任务'), ('kb', '知识库'), ('org', '部门')]:
            await page.click('#oaTabs .tab[data-view="%s"]' % view)
            await page.wait_for_timeout(1400)
            active = await page.evaluate("(v) => document.getElementById('v-' + v).classList.contains('on')", view)
            chk('C3 OA 视图「%s」可进入' % label, active)
            await no_overflow(page, 'OA·' + label)
            await shot(page, '07-oa-' + view)
        # 任务页左导轨四个面板（必须先切回「任务」页 —— 导轨在 v-collab 内，隐藏时点不到）
        await page.click('#oaTabs .tab[data-view="collab"]')
        await page.wait_for_timeout(900)
        for panel in ['tasks', 'projects', 'approvals', 'schedule']:
            await page.click('#oaRail .rail-item[data-panel="%s"]' % panel)
            await page.wait_for_timeout(700)
            on = await page.evaluate("(p) => document.getElementById('p-' + p).classList.contains('on')", panel)
            only = await page.evaluate("() => document.querySelectorAll('#v-collab .panel.on').length")
            chk('C4 导轨「%s」互斥显示' % panel, on and only == 1, 'on=%s' % only)
            await shot(page, '08-rail-' + panel)
        await no_overflow(page, 'OA·任务导轨')

        # C8 审批详情（OA 内联打开，不跳经典）+ 决策按钮的范围派生正确性
        await page.click('#oaRail .rail-item[data-panel="approvals"]')
        await page.wait_for_timeout(700)
        await page.click('#v-collab .org-chip[data-scope="mine"]')
        await page.wait_for_timeout(900)
        op = await page.evaluate("""() => {
          const rows = [...document.querySelectorAll('#v-collab [data-appr]')];
          if(!rows.length) return {n: 0, title: ''};
          const t = rows[0].querySelector('.tl-name');
          const title = t ? t.textContent.trim() : '';
          rows[0].click();
          return {n: rows.length, title: title};
        }""")
        chk('C8 「我发起的」列表有可点审批行', op['n'] > 0, op)
        await page.wait_for_timeout(900)
        det = await page.evaluate("""(title) => {
          const v = document.getElementById('v-appr');
          const tx = v ? v.textContent : '';
          return { view: window.oaState.view, titleIn: !!title && tx.includes(title),
                   body: tx.slice(0, 160),
                   hasOk: !!document.getElementById('oaApOk'),
                   hasRej: !!document.getElementById('oaApRej'),
                   hasBack: !!document.getElementById('oaApBack'),
                   hasFlow: tx.includes('流转路径') };
        }""", op['title'])
        chk('C8 详情在 OA 层内打开（未跳经典形态）',
            det['view'] == 'appr' and det['hasBack'] is True, det['view'])
        chk('C8 详情渲染真实字段（标题与列表同源、含流转路径）',
            det['titleIn'] is True and det['hasFlow'] is True, det['body'][:70])
        chk('C8 非「待我审批」范围不出现通过/驳回（按钮由 scope 派生）',
            det['hasOk'] is False and det['hasRej'] is False,
            {'ok': det['hasOk'], 'rej': det['hasRej']})
        await shot(page, '08b-oa-appr-detail')
        # C8 若失败不应吞掉后续用例（F/B5~B7/G1 仍需跑），故返回按钮点击容错
        try:
            await page.click('#oaApBack', timeout=5000)
            await page.wait_for_timeout(700)
        except Exception:
            # 兜底：直接点底部「任务」Tab 回到列表（tabbar 在 OA 各视图恒可见）
            await page.click('#oaTabs .tab[data-view="collab"]')
            await page.wait_for_timeout(700)

        # 部门页：联系方式默认隐藏
        await page.click('#oaTabs .tab[data-view="org"]')
        await page.wait_for_timeout(1200)
        rev = await page.evaluate("""() => {
          const b = document.querySelector('#oaOrgList [data-reveal]');
          if(!b) return {n:0};
          const before = document.getElementById('oac-' + b.dataset.reveal).textContent;
          b.click();
          const after = document.getElementById('oac-' + b.dataset.reveal).textContent;
          return {n:1, before: before, after: after, stored: localStorage.getItem('aioa_contacts')};
        }""")
        if rev['n']:
            chk('C5 联系方式默认隐藏、点击才展开',
                rev['before'].strip() == '' and ('@' in rev['after'] or '手机' in rev['after'] or rev['after'].strip() != ''),
                rev)
            chk('C6 联系方式未写入本地存储', rev['stored'] is None, rev['stored'])
        await shot(page, '09-oa-org-revealed')

        # C7 部门筛选器必须真的由接口喂出来。
        # 判据取接口原始返回（/v1/org/departments 是对象 {flat,tree}，不是数组），
        # 不读 S.org.departments —— 否则与渲染器同源、空筛选器会被判成通过。
        dp = await page.evaluate("""async () => {
          const raw = await API.req('/v1/org/departments');
          const flat = Array.isArray(raw) ? raw : ((raw && (raw.flat || raw.tree)) || []);
          const chips = [...document.querySelectorAll('#oaOrgChips .org-chip')];
          return { apiN: flat.length, apiNames: flat.map(d => d.name),
                   chipN: chips.length,
                   chipNames: chips.map(c => c.textContent.trim()) };
        }""")
        chk('C7 部门筛选器含「全部」+ 每个接口部门各一枚',
            dp['chipN'] == dp['apiN'] + 1
            and dp['chipNames'][:1] == ['全部']
            and sorted(dp['chipNames'][1:]) == sorted(dp['apiNames']),
            dp)
        if dp['apiN']:
            # 点第二个 chip（真实部门）应触发按部门过滤，且可切回「全部」
            await page.click('#oaOrgChips .org-chip:nth-child(2)')
            await page.wait_for_timeout(1100)
            filt = await page.evaluate("() => ({dept: window.oaState.deptId, on: document.querySelectorAll('#oaOrgChips .org-chip.on').length})")
            chk('C7 部门 chip 可切换且互斥选中', filt['dept'] is not None and filt['on'] == 1, filt)
            await page.click('#oaOrgChips .org-chip[data-dept=""]')
            await page.wait_for_timeout(1000)
            back2 = await page.evaluate("() => window.oaState.deptId")
            chk('C7 可切回「全部」', back2 is None, back2)
        await no_overflow(page, 'OA·部门')
        await shot(page, '09b-oa-org-dept')

        # ---------------- F. 抽屉与子页 ----------------
        await page.click('#oaTabs .tab[data-view="home"]')
        await page.wait_for_timeout(500)
        await page.click('#oaLeft')
        await page.wait_for_timeout(600)
        dr = await page.evaluate("""() => ({
          open: document.querySelector('#oaRoot').classList.contains('drawer-open'),
          items: [...document.querySelectorAll('.dnav-item')].map(x => x.textContent.trim()),
          recent: document.querySelectorAll('#oaDrawerRecent [data-conv]').length })""")
        chk('F1 抽屉可打开', dr['open'] is True)
        chk('F2 抽屉动作项自上而下正确',
            dr['items'][:4] == ['新工作任务', '新对话', '定时任务0', '插件-技能0'] or
            all(x.startswith(y) for x, y in zip(dr['items'][:4], ['新工作任务', '新对话', '定时任务', '插件-技能'])),
            dr['items'])
        await shot(page, '10-oa-drawer')
        await page.click('#odTimers')
        await page.wait_for_timeout(1200)
        tv = await page.evaluate("() => window.oaState.view")
        chk('F3 定时任务子页可进入', tv == 'timers', tv)
        await shot(page, '11-oa-timers')

        # F3a 启停口径与事实同源：接口字段名是 on（不是 enabled）。
        # 判据必须拿「接口原始返回」独立比对渲染结果 —— 若读 state.workers，
        # 判据与渲染器同源，缺陷会一起漏过（负向测试已证明）。
        tl = await page.evaluate("""async () => {
          const r = await API.workers();
          const api = Array.isArray(r) ? r : (r.items || r.data || []);
          const sch = api.filter(w => w.scheduleTime);
          const byName = {};
          sch.forEach(w => { byName[String(w.name)] = w; });
          const cards = [...document.querySelectorAll('#oaTimersList .task-card')];
          const rows = cards.map(c => {
            const nb = c.querySelector('.who b');
            const sp = c.querySelector('.who span');
            const ch = c.querySelector('.chip');
            const nm = nb ? nb.textContent.trim() : '';
            const w = byName[nm] || {};
            return { name: nm, on: w.on, matched: !!byName[nm],
                     text: sp ? sp.textContent : '', chip: ch ? ch.textContent : '' };
          });
          return {
            hasOnKey: sch.length ? Object.prototype.hasOwnProperty.call(sch[0], 'on') : false,
            n: sch.length, cards: cards.length, rows: rows };
        }""")
        chk('F3a 定时任务卡片数与接口排班数一致', tl['cards'] == tl['n'] and tl['n'] > 0,
            'cards=%s api=%s' % (tl['cards'], tl['n']))
        chk('F3a 接口启停字段名为 on（非 enabled）', tl['hasOnKey'] is True,
            'hasOwnProperty(on)=%s' % tl['hasOnKey'])
        bad = [r for r in tl['rows']
               if not r['matched'] or r['on'] is None
               or ('已启用' if r['on'] else '已停用') not in r['text']
               or r['chip'] != ('运行中' if r['on'] else '已停用')]
        chk('F3a 启停文案/徽标与接口 on 一致（不出现恒停用）', len(bad) == 0,
            bad if bad else 'api_on=%s' % [r['on'] for r in tl['rows']])

        # 子页上左键=「返回」（不是开抽屉），回首页后左键才=「开抽屉」
        await page.click('#oaLeft')
        await page.wait_for_timeout(600)
        at_home = await page.evaluate("() => window.oaState.view")
        chk('F3b 子页左键语义为「返回首页」', at_home == 'home', at_home)
        await page.click('#oaLeft')
        await page.wait_for_timeout(500)
        await page.click('#odSkills')
        await page.wait_for_timeout(1100)
        sv = await page.evaluate("() => window.oaState.view")
        chk('F4 插件·技能子页可进入', sv == 'skills', sv)
        await shot(page, '12-oa-skills')

        # G2 全文档图标自洽：每个 <use href="#i-*"> 都要能解析到真实 <symbol>。
        # 数组字面量键（首页/KB 指标）与 iconKey() 动态映射靠静态扫描扫不全，
        # 而缺符号的 <use> 会渲染成空白 —— 这里按渲染结果判定。
        ic = await page.evaluate("""() => {
          const keys = [...document.querySelectorAll('use')]
            .map(u => (u.getAttribute('href') || u.getAttribute('xlink:href') || ''))
            .filter(h => h.startsWith('#i-')).map(h => h.slice(3));
          const uniq = [...new Set(keys)];
          const missing = uniq.filter(k => !document.getElementById('i-' + k));
          return { total: uniq.length, missing: missing };
        }""")
        chk('G2 文档内所有图标引用都能解析到符号（无空白图标）',
            len(ic['missing']) == 0,
            '引用 %d 个唯一图标；缺失=%s' % (ic['total'], ic['missing']))

        # G3 已挂载元素里不得有重复 id。
        # 两形态（经典 page-* 与 OA .oa）**同时在 DOM**，各自渲染时若拼同一个 id，
        # getElementById 恒返回文档中靠前的那个 ⇒ 在新版里操作却读到老版的空值
        # （本轮真实修掉过一处：反馈回复框 fbReply<id>）。
        # 必须查运行时 DOM，不能查源码文本：同一个 ?: 的两臂各写一次 id 是正常的。
        dup = await page.evaluate("""() => {
          const seen = {};
          document.querySelectorAll('[id]').forEach(el => {
            seen[el.id] = (seen[el.id] || 0) + 1;
          });
          const out = Object.keys(seen).filter(k => seen[k] > 1).map(k => k + '×' + seen[k]);
          return {total: Object.keys(seen).length, dup: out};
        }""")
        chk('G3 DOM 内无重复 id（两形态并存不得撞名）',
            len(dup['dup']) == 0, '已挂载 id %d 个；重复=%s' % (dup['total'], dup['dup']))

        # ---------------- C9. 「我的」账户四内页：跳转一律留在新版内 ----------------
        # 判据必须查「逃逸的后果」本身（mode / oa-mode / localStorage），
        # 而不是查某个经典页有没有 .active —— 经典页可能保留上一次的 .active，会假阴性。
        await page.click('#oaTabs .tab[data-view="me"]')
        await page.wait_for_timeout(800)
        me = await page.evaluate("""() => {
          const b = document.getElementById('oaMeSwitch');
          const n = document.getElementById('oaMeName');
          const rb = b ? b.getBoundingClientRect() : null;
          const rn = n ? n.getBoundingClientRect() : null;
          return {
            card: !!document.querySelector('#v-me .switch-card'),
            btn: b ? b.textContent.trim() : null,
            rightOfName: !!(rb && rn && rb.left > rn.right - 1),
            sameRow: !!(rb && rn && rb.top < rn.bottom && rb.bottom > rn.top),
            rows: [...document.querySelectorAll('#oaMeActions [data-view]')].map(r => r.dataset.view)
          };
        }""")
        chk('C9a OA「我的」已无「界面版本」卡片', me['card'] is False)
        chk('C9b OA「我的」布局按钮=名字最右侧单个按钮「切换布局」',
            me['btn'] == '切换布局' and me['rightOfName'] and me['sameRow'], me)
        chk('C9c 账户四入口顺序与视图名正确',
            me['rows'] == ['bill', 'log', 'perm', 'feedback'], me['rows'])
        await no_overflow(page, 'OA·我的')
        await shot(page, '15-oa-me-account')

        for view, label, box in [('bill', '额度与账单', 'oaBillQuota'),
                                 ('log', '我的操作记录', 'oaLogList'),
                                 ('perm', '权限申请', 'oaPermCatalog'),
                                 ('feedback', '投诉与建议', 'oaFbRoute')]:
            await page.click('#oaTabs .tab[data-view="me"]')
            await page.wait_for_timeout(600)
            await page.click('#oaMeActions [data-view="%s"]' % view)
            await page.wait_for_timeout(1100)
            got = await page.evaluate("""(id) => {
              const el = document.getElementById(id);
              return {
                view: window.oaState.view,
                oa: document.querySelector('.phone').classList.contains('oa-mode'),
                mode: localStorage.getItem('aioa_mode'),
                rendered: !!el && el.innerHTML.trim().length > 0,
                title: document.getElementById('oaTitle').textContent.trim()
              };
            }""", box)
            chk('C9d 入口「%s」进入新版内视图 %s' % (label, view),
                got['view'] == view and got['oa'] is True and got['mode'] == 'oa', got)
            chk('C9e 入口「%s」页面已渲染（非空白）' % label, got['rendered'], got)
            await no_overflow(page, 'OA·' + label)
            await shot(page, '16-oa-' + view)

        # 回「我的」再验一次：新版内往返不应把模式改回去
        await page.click('#oaTabs .tab[data-view="me"]')
        await page.wait_for_timeout(600)
        round = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: localStorage.getItem('aioa_mode'),
          view: window.oaState.view })""")
        chk('C9f 四页往返后仍在新版（未被弹回经典）',
            round['oa'] is True and round['mode'] == 'oa' and round['view'] == 'me', round)

        # ---------------- B5. 回到经典 + 刷新记忆 ----------------
        await page.click('#oaTabs .tab[data-view="me"]')
        await page.wait_for_timeout(700)
        await shot(page, '13-oa-me')
        await page.click('#oaMeSwitch')
        await page.wait_for_timeout(900)
        back = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          classicTabbar: getComputedStyle(document.querySelector('.phone > .tabbar')).display })""")
        chk('B5 OA「我的」可切回经典', back['oa'] is False and back['classicTabbar'] == 'flex', back)

        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(2600)
        after = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: localStorage.getItem('aioa_mode'),
          auth: document.body.classList.contains('auth') })""")
        chk('B6 刷新后记忆生效（保持经典）', after['mode'] == 'classic' and after['oa'] is False and after['auth'], after)
        # 再切到 OA 后刷新，验证反向记忆
        await page.evaluate("() => switchTabById('page-me')")
        await page.wait_for_timeout(600)
        await page.click('#classicMeSwitch')
        await page.wait_for_timeout(900)
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(2800)
        after2 = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: localStorage.getItem('aioa_mode') })""")
        chk('B7 刷新后保持 OA 形态', after2['oa'] is True and after2['mode'] == 'oa', after2)
        await no_overflow(page, 'OA·刷新后')
        await shot(page, '14-oa-after-reload')

        # ---------------- H. 职责推荐 / 换人 / 表单直出（与老版同一套逻辑） ----------------
        # 每条断言都要能说清理由来自哪里：
        #   推荐行 = 后端职责分类器（POST /v1/workers/intent）或问句字面命中；
        #   请假表单 = 「用户主动提请假」且「当前数字人是请假类」**两个条件同时成立**。
        # 语料取本租户真实在册员工：先选一个**非**请假类数字员工，再问请假 —— 负向与正向各一遍。
        await page.click('#oaTabs .tab[data-view="home"]')
        await page.wait_for_timeout(700)

        # H1 选一个非请假类数字员工（负向场景的起点；类型取自接口，不写死名字）
        await page.click('#oaRobot')
        await page.wait_for_timeout(450)
        await page.click('#oaSheet .sheet-opt[data-target="workers"]')
        await page.wait_for_timeout(1000)
        h1 = await page.evaluate("""() => {
          const ws = state.workers || [];
          const rows = [...document.querySelectorAll('#oaWorkersList [data-worker]')];
          const pick = rows.find(r => {
            const w = ws.find(x => String(x.id) === r.dataset.worker) || {};
            return String(w.workerType || '').toUpperCase() !== 'LEAVE_APPROVER' && w.on !== false;
          });
          if(!pick) return {err: '没有非请假类数字员工可选'};
          pick.click();
          const w = ws.find(x => String(x.id) === pick.dataset.worker) || {};
          return {id: pick.dataset.worker, name: w.name, type: w.workerType};
        }""")
        await page.wait_for_timeout(900)
        h1s = await page.evaluate("() => ({name: (window.oaState.worker||{}).name, conv: window.oaState.convId})")
        chk('H1 已选中一个非请假类数字员工（负向场景起点）',
            bool(h1.get('name')) and h1s['name'] == h1.get('name'), h1)

        LEAVEY_Q = '我想请假三天，需要走什么流程'
        NONLEAVE_Q = '帮我把这句话写得更正式一些：明天开会'

        async def ask(q, want_guide=False, want_form=False, settle_ms=700):
            """真实发一条消息并等回答收口（S.busy 释放 + 出现新的 AI 气泡）。

            收口（推荐块 / 请假表单）要等一次 intent 调用才落地，故：
              · **正向**断言一律等明确的 DOM 条件（want_guide / want_form），不猜毫秒数；
              · **负向**断言没有可等的条件，只能给足窗口 —— 负向的唯一失败模式是「等太早」，
                所以窗口给宽（等太早 = 假绿；等太久不会造成假红）。"""
            st0 = await page.evaluate("""() => ({
              bubs: document.querySelectorAll('#oaDockList .bub').length,
              ai: document.querySelectorAll('#oaDockList .bub.ai').length,
              guides: document.querySelectorAll('#oaDockList .bub.guide').length,
              forms: document.querySelectorAll('#leaveForm').length })""")
            await page.fill('#oaInput', q)
            await page.click('#oaSendBtn')
            await page.wait_for_function(
                "() => !window.oaState.busy && document.querySelectorAll('#oaDockList .bub').length > "
                + str(st0['bubs']), timeout=90000)
            if want_guide:
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('#oaDockList .bub.guide').length > "
                        + str(st0['guides']), timeout=20000)
                except Exception:
                    pass          # 等不到就交给断言报红，不在这里吞掉
            if want_form:
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('#leaveForm').length > "
                        + str(st0['forms']), timeout=25000)
                except Exception:
                    pass
            await page.wait_for_timeout(settle_ms)
            # 取「本轮新增的第一个 ai 气泡」= 回答气泡本身（收口推的推荐块/表单排在它后面）。
            # 若取「最后一个 ai 气泡」，请假那轮量到的会是**表单**，把「有没有正文」问错对象。
            text = await page.evaluate("""(n) => {
              const bs = [...document.querySelectorAll('#oaDockList .bub.ai')].slice(n);
              const a = bs[0];
              return a ? (a.textContent || '').trim() : '';
            }""", st0['ai'])
            return {'before': st0['bubs'], 'answerLen': len(text), 'text': text}

        async def guide_state():
            return await page.evaluate("""() => {
              const gs = [...document.querySelectorAll('#oaDockList .bub.guide')];
              const g = gs[gs.length - 1];
              if(!g) return {found: false};
              return {found: true, hasTail: !!g.querySelector('.tail'),
                rows: [...g.querySelectorAll('.g-row')].map(r => ({
                  label: ((r.querySelector('.g-label') || {}).textContent || '').trim(),
                  why: ((r.querySelector('.g-why') || {}).textContent || '').trim(),
                  re: !!(r.querySelector('.g-re'))
                }))};
            }""")

        async def guide_rows_all():
            """坞内**全部**推荐块的行标签，按出现顺序（旧 → 新）。"""
            return await page.evaluate("""() => [...document.querySelectorAll('#oaDockList .bub.guide')]
              .map(g => [...g.querySelectorAll('.g-row')].map(r =>
                ((r.querySelector('.g-label') || {}).textContent || '').trim()))""")

        async def leave_forms():
            return await page.evaluate("""() => {
              const dock = document.getElementById('oaDockList');
              const f = document.getElementById('leaveForm');
              const sel = document.getElementById('lfType');
              return {
                count: document.querySelectorAll('#leaveForm').length,
                inDock: !!(f && dock && dock.contains(f)),
                types: sel ? sel.options.length : 0,
                placeholder: sel ? sel.options[0].textContent : null
              };
            }""")

        # H2 问「请假」，但当前数字人不管请假 ⇒ 出推荐、**不出表单**（负向：两个条件缺一不可）
        h2 = await ask(LEAVEY_Q, want_guide=True)
        chk_answered('H2 回答已收口（有正文）', h2)
        g1 = await guide_state()
        chk('H2a 回答后出现「转给更专业的同事」推荐块', g1['found'] is True, g1)
        chk('H2b 推荐块带三角（与其它气泡同形，指向数字人）', g1.get('hasTail') is True, g1)
        rows_txt = ' | '.join(r['label'] + '/' + r['why'] for r in g1.get('rows', []))
        hit = [r for r in g1.get('rows', []) if '请假' in r['label']]
        chk('H2c 推荐里含职责对口的请假类数字员工', len(hit) > 0, rows_txt)
        chk('H2d 推荐理由来自后端职责分类器（识别为「…」）',
            bool(hit) and any('识别为' in r['why'] for r in hit), rows_txt)
        # 先要求「有行」再逐行判：只写 all(...) 的话，空列表会让它恒真（没有推荐 = 通过）。
        chk('H2e 推荐行都带「换他重答」',
            bool(g1.get('rows')) and all(r['re'] for r in g1['rows']), g1.get('rows'))
        f2 = await leave_forms()
        chk('H2f 负向：数字人不具请假职责 ⇒ 不发表单', f2['count'] == 0, f2)
        await shot(page, '17-oa-guide-suggest')

        # H3 点推荐行 ⇒ 直接更换数字人（同老版点名称切换），且换人真的要换会话
        # 没有推荐块时**不在这里崩**（会掩盖 H2a 的真因），只返回 False，交给下面的断言报红。
        h3click = await page.evaluate("""() => {
          const gs = [...document.querySelectorAll('#oaDockList .bub.guide')];
          const g = gs[gs.length - 1];
          if(!g) return false;
          const r = [...g.querySelectorAll('.g-row')].find(x => x.textContent.indexOf('请假') >= 0);
          if(!r) return false;
          r.click();
          return true;
        }""")
        await page.wait_for_timeout(1000)
        h3 = await page.evaluate("""() => {
          const w = window.oaState.worker || {};
          const full = (state.workers || []).find(x => String(x.id) === String(w.id)) || {};
          return {name: w.name, type: String(full.workerType || ''),
                  conv: window.oaState.convId,
                  bar: (document.querySelector('.dock-list .oa-who') || {}).textContent || ''};
        }""")
        h3['clicked'] = h3click
        chk('H3 点推荐行即更换数字人（顶部标出当前对话对象）',
            h3click and '请假' in str(h3['name']) and '请假' in str(h3['bar']), h3)
        chk('H3a 换人即换会话（会话在创建时绑定数字员工，沿用旧会话会让「换人」不生效）',
            h3['conv'] is None, h3)
        await shot(page, '18-oa-guide-switched')

        # H4 负向：数字人已是请假类，但问句不是请假 ⇒ 仍不发表单
        await page.evaluate("() => { const f = document.getElementById('leaveForm'); if(f) f.remove(); }")
        h4 = await ask(NONLEAVE_Q, settle_ms=4000)     # 负向：给足窗口，等太早 = 假绿
        chk_answered('H4 回答已收口（有正文）', h4)
        f4 = await leave_forms()
        chk('H4a 负向：问句不是请假 ⇒ 请假类数字人也不发表单', f4['count'] == 0, f4)

        # H5 正向：请假类数字人 + 请假问句 ⇒ 表单由数字人当场给出（同老版「表单融入对话流」）
        gpre = await guide_rows_all()      # H5d 的快照：本轮之前坞里已有的推荐块
        h5 = await ask('我要请假两天', want_form=True)
        chk_answered('H5 回答已收口（有正文）', h5)
        f5 = await leave_forms()
        chk('H5a 表单直出：请假表单落在对话坞内（不跳转、不换页）', f5['inDock'] is True, f5)
        chk('H5b 假种下拉来自后端配置（非「暂无可用假种」占位）',
            f5['types'] > 0 and '暂无' not in str(f5['placeholder']), f5)
        chk('H5c 文档内 #leaveForm 恰好 1 份（两形态共用同一 id，不得撞名）', f5['count'] == 1, f5)

        # H5d 自己不会被推荐给自己：「更换」的语义是换一位，不是再推荐当前这位。
        #      此刻当前对象就是那位「会命中推荐判据」的请假助手，所以规则只在这一刻验得到。
        #      判据必须落在**本轮新产出的块**上：坞里那块 H2 留下的推荐是当时（当前对象=政策快讯员）
        #      合法生成的、并且刻意保留在坞里 —— 拿它当证据会得到一个假阳性（实测踩过一次）。
        #      同时必须带**阳性对照**：更早那轮确实推荐过请假助手（H2c 已证），否则「本轮没推荐它」
        #      可能只是因为「这个问句本来就推不出它」，整条断言退化成恒真。
        gpost = await guide_rows_all()
        new_blocks = gpost[len(gpre):]
        uname = await page.evaluate("() => ((window.oaState.worker || {}).name || '')")
        has_self = lambda rows: any(uname and uname in lb for lb in rows)
        pre_hit = any(has_self(rows) for rows in gpre)        # 阳性对照
        new_hit = any(has_self(rows) for rows in new_blocks)  # 被测规则
        chk('H5d 当前就是请假助手 ⇒ 本轮不再把「请假助手」推荐给自己（对照：更早那轮确实推荐过它）',
            pre_hit and not new_hit,
            {'self': uname, 'pre_blocks': len(gpre), 'new_blocks': len(new_blocks),
             '对照_更早块命中': pre_hit, '本轮命中': new_hit, 'new_rows': new_blocks})
        await shot(page, '19-oa-leave-form')

        # H6 表单气泡与其它气泡同形：三角仍指向数字人
        geo_h = await tail_geometry(page)
        chk('H6 表单在坞里时三角几何仍成立（气泡数 %s）' % geo_h.get('bubbles'),
            not geo_h.get('skip') and len(geo_h.get('items', [])) > 0
            and max(i['err'] for i in geo_h['items']) < 1.0,
            geo_h.get('skip') or [i for i in geo_h.get('items', []) if i['err'] >= 1.0])

        # H7 离开新版 ⇒ 新版注入的表单必须撤掉，否则经典的「文档里已有表单就不再发」判据会被挡住。
        # 多等一会儿是刻意的：若「在途收口」漏过代次判据，它会正好在这段时间里补一份表单出来。
        await page.evaluate("() => window.oaSetMode('classic')")
        await page.wait_for_timeout(2500)
        h7 = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          count: document.querySelectorAll('#leaveForm').length })""")
        chk('H7 切回经典时撤掉新版注入的请假表单（解除对经典发放判据的遮挡）',
            h7['oa'] is False and h7['count'] == 0, h7)

        # H8 反向：经典形态自己发一份表单时，文档里仍恰好 1 份（同一 id 共用，不互相遮挡）
        await page.evaluate("() => { if(typeof openLeaveFlow === 'function') openLeaveFlow(); }")
        await page.wait_for_timeout(900)
        h8 = await page.evaluate("() => document.querySelectorAll('#leaveForm').length")
        chk('H8 经典形态可正常发放请假表单（文档内恰好 1 份）', h8 == 1, h8)
        await page.evaluate("() => window.oaSetMode('oa')")
        await page.wait_for_timeout(800)

        # ---------------- 控制台 ----------------
        chk('G1 console 无 error / 无未捕获异常', len(errors) == 0, errors[:5])

        await browser.close()
    return report()


def report():
    print('\n截图：%d 张 → scripts/_shot_oa/' % len(shots))
    print('失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    if errors:
        print('控制台错误 %d 条：' % len(errors))
        for e in errors[:10]:
            print('  ' + e[:180])
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        rc = asyncio.run(main())
    except Exception as exc:
        # 中途异常也要把已跑出的结论与截图交出来，否则「跑到一半崩了」会被误读成「全挂」
        chk('流程未跑完（异常中断）', False, '%s: %s' % (type(exc).__name__, str(exc)[:160]))
        rc = 1
    sys.exit(rc or (1 if fails else 0))
