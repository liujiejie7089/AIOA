#!/usr/bin/env python3
"""OA 形态端到端自检（Playwright + msedge 无头，390x844 @2x）。

覆盖：
  A 经典形态回归      —— 登录后五个 Tab 逐个走查，console 无错、无横向溢出
  B 双形态切换        —— 经典「我的」→ 新版；OA「我的」→ 回经典；刷新后记忆
  C OA 五个主视图     —— 首页 / 任务 / 知识库 / 部门 / 我的
  D 数字人链路        —— 点击 → 选择卡 → 数字员工清单 → 原地对话坞（不跳转）
  E 气泡三角几何      —— 逐气泡比对「计算方向角 θ+90°」与「实际 --tail-angle」，误差 < 1°
  F 抽屉与子页        —— 抽屉、定时任务、插件-技能、最近会话
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
        let got = parseFloat(t.style.getPropertyValue('--tail-angle')) || 0;
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

        # ---------------- A. 经典形态回归 ----------------
        om = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
        chk('A1 登录后默认经典形态（无 oa-mode）', om is False, 'oa-mode=%s' % om)
        for pid, label in [('page-home', '工作台'), ('page-todo', '待办'),
                           ('page-chat', '会话'), ('page-agent', '专家与员工')]:
            await page.evaluate("(p) => switchTabById(p)", pid)
            await page.wait_for_timeout(450)
            vis = await page.evaluate("(p) => document.getElementById(p).classList.contains('active')", pid)
            chk('A2 经典 Tab「%s」可进入' % label, vis)
            await no_overflow(page, '经典·' + label)
        await page.evaluate("() => switchTabById('page-me')")
        await page.wait_for_timeout(600)
        has_seg = await page.is_visible('#classicSeg')
        chk('A3 经典「我的」含界面版本切换控件', has_seg)
        await shot(page, '01-classic-me-with-switch')

        # ---------------- B. 切换到 OA ----------------
        await page.click('#classicSeg button[data-mode="oa"]')
        await page.wait_for_timeout(1200)
        st = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: state.mode,
          ls: localStorage.getItem('aioa_mode'),
          oaTabbar: !!document.querySelector('#oaTabs') && getComputedStyle(document.querySelector('#oaTabs')).display !== 'none',
          classicTabbar: getComputedStyle(document.querySelector('.phone > .tabbar')).display,
          pages: getComputedStyle(document.querySelector('.pages')).display
        })""")
        chk('B1 切到 OA：.phone.oa-mode 生效', st['oa'] is True, st)
        chk('B2 OA 底部菜单可见、经典底部菜单隐藏', st['oaTabbar'] and st['classicTabbar'] == 'none', st)
        chk('B3 经典页面层隐藏', st['pages'] == 'none', st)
        chk('B4 模式写入本地记忆', st['ls'] == 'oa', 'aioa_mode=%s' % st['ls'])
        await shot(page, '02-oa-home')

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
                    const x = parseFloat(b.querySelector('.tail').style.getPropertyValue('--tail-x'));
                    const y = parseFloat(b.querySelector('.tail').style.getPropertyValue('--tail-y'));
                    const eps = 1.5;
                    const okX = Math.abs(x) <= eps || Math.abs(x - br.width) <= eps;
                    const okY = Math.abs(y) <= eps || Math.abs(y - br.height) <= eps;
                    out.push(okX || okY);
                  });
                  return out;
                }""")
                chk('E2 三角落位在气泡边框上', all(on_edge), on_edge)

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

        # ---------------- B5. 回到经典 + 刷新记忆 ----------------
        await page.click('#oaTabs .tab[data-view="me"]')
        await page.wait_for_timeout(700)
        await shot(page, '13-oa-me')
        await page.click('#oaSeg button[data-mode="classic"]')
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
        await page.click('#classicSeg button[data-mode="oa"]')
        await page.wait_for_timeout(900)
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(2800)
        after2 = await page.evaluate("""() => ({
          oa: document.querySelector('.phone').classList.contains('oa-mode'),
          mode: localStorage.getItem('aioa_mode') })""")
        chk('B7 刷新后保持 OA 形态', after2['oa'] is True and after2['mode'] == 'oa', after2)
        await no_overflow(page, 'OA·刷新后')
        await shot(page, '14-oa-after-reload')

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
