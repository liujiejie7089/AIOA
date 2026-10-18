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
  H 职责推荐与请假直达 —— 回答后按职责推荐更对口的数字人（理由必须来自后端分类器）、
                        点名称直接更换（并换会话）；wjj_xu 现 held=true（docs/51 §0 实测，
                        经 team-lead 重建重启后已生效），说「我要请假两天」
                        ⇒ action=APPLY_LEAVE、held=true ⇒ 直接跳转 / §1.5 创建，表单落进 OA 对话坞、
                        真填真提交、结果落对话坞且 #msgs 无新增（撤单收尾）；
                        申请卡分支（held=false）由 zhangsan 覆盖，见 _verify_oa_leave_permcard.py。
输出：scripts/_shot_oa/*.png + 控制台逐项结论
退出码非零 = 有断言失败。
"""
import asyncio
import json
import math
import os
import re
import sys

from playwright.async_api import async_playwright

import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:5181/'
BACKEND_BASE = 'http://127.0.0.1:8080'     # 后端直连（撤单等真实 HTTP 用）


def _leave_login(user, pwd):
    try:
        req = urllib.request.Request(
            BACKEND_BASE + '/api/v1/auth/login',
            data=json.dumps({'username': user, 'password': pwd}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=20) as resp:
            b = json.loads(resp.read().decode('utf-8'))
        return ((b or {}).get('data') or {}).get('accessToken')
    except Exception:
        return None


def _leave_mine(token):
    try:
        req = urllib.request.Request(
            BACKEND_BASE + '/api/v1/leave/requests',
            headers={'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _leave_cancel(token, rid):
    try:
        req = urllib.request.Request(
            BACKEND_BASE + '/api/v1/leave/requests/%s/cancel' % rid,
            headers={'Authorization': 'Bearer ' + token}, method='POST')
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8'))
        except Exception:
            return e.code, {'err': str(e)[:120]}
    except Exception as ex:
        return -1, {'err': str(ex)[:120]}
USER, PWD = 'wjj_xu', 'User@123'          # 普通成员（科员）：覆盖 ROLE_MEMBER 视角
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_oa')
# 构建产物（单次拼装后的零构建单文件 H5）；E3 的静态口径直接读它。
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'user-client', 'index.html')

errors, fails, notes, shots, bad_resp = [], [], [], [], []


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


async def tail_count(page):
    """数出对话坞气泡里「尾巴」的所有可能形态：子节点 .tail，以及用 ::after/::before
    画出来的三角。读真实 DOM + 计算样式，不依赖任何内联变量，避免自证。
    新口径：气泡不得有尾巴，这里只负责「数出来」，判据交给各 chk 断言。"""
    return await page.evaluate("""() => {
      const home = document.getElementById('v-home');
      if(!home || !home.classList.contains('chatting')) return {skip:'未进入对话态'};
      const bubbles = home.querySelectorAll('.bub').length;
      const tails = home.querySelectorAll('.bub .tail').length;
      // 任何人把三角加回成 ::after/::before（哪怕忘了走 .tail 子节点），这里也要能抓住。
      // 仅当伪元素真的渲染出可见形状（有背景/有边框/有非零尺寸）才计入，避免把
      // content:'' 的 clearfix 之类误判为三角。
      let pseudo = 0;
      home.querySelectorAll('.bub').forEach(b => {
        [':after', ':before'].forEach(p => {
          const cs = getComputedStyle(b, p);
          const c = cs.content;
          if (!c || c === 'none' || c === 'normal') return;
          const bg = cs.backgroundColor;
          const bgOpaque = !!bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
          const bw = ['borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth']
                       .reduce((s,k) => s + (parseFloat(cs[k]) || 0), 0);
          const w = parseFloat(cs.width) || 0, h = parseFloat(cs.height) || 0;
          if (bgOpaque || bw > 0 || (w > 0 && h > 0)) pseudo++;
        });
      });
      return {bubbles, tails, pseudo};
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
        # 捕获非 2xx 响应（定位 console 里的 401/4xx 究竟来自哪个 URL）
        def _on_bad_resp(resp):
            st = resp.status
            if st >= 400:
                u = resp.url or ''
                bad_resp.append('%d %s' % (st, u))
        page.on('response', _on_bad_resp)

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

            # —— 新口径：气泡不得有尾巴（三角）。这条存在的唯一理由就是抓「有人把三角加回来」：
            #    无论是 <svg class="tail"> 子节点，还是 ::after/::before 画出来的三角，都必红。
            tc = await tail_count(page)
            if tc.get('skip'):
                chk('E1 气泡尾巴判据可测', False, tc['skip'])
            else:
                chk('E1 坞内所有气泡均无尾巴（.bub .tail=0 且无 ::after/::before 三角，共 %d 个气泡）'
                    % tc['bubbles'],
                    tc['bubbles'] > 0 and tc['tails'] == 0 and tc['pseudo'] == 0,
                    'bubbles=%s tails=%s pseudo=%s' % (tc['bubbles'], tc['tails'], tc['pseudo']))

            # E2 固化自检（就地注入 → 断言 → 撤净）：把「数出来必须是 0」这类最容易恒真的判据，
            # 每次运行都实跑一次反例，确保 tail_count 真在数、且撤净后能回到 0。谁把 .tail 打成
            # .taill、或把 #v-home.chatting 判断写坏，这里会立刻红，而不是静默恒真绿。
            # 注入/撤净都放在 E1 之后、切视图之前，避免污染后续截图。
            probe = await page.evaluate("""() => {
              const home = document.getElementById('v-home');
              if(!home || !home.classList.contains('chatting')) return {err:'未进入对话态'};
              const b = home.querySelector('#oaDockList .bub') || home.querySelector('.bub');
              if(!b) return {err:'无可见气泡可注入'};
              // 1) 子节点三角（模拟「有人把 <svg class="tail"> 加回气泡」）
              const s = document.createElementNS('http://www.w3.org/2000/svg','svg');
              s.setAttribute('class','tail'); s.setAttribute('viewBox','0 0 13 13');
              s.innerHTML = '<path d="M0 13 L6.5 0 L13 13 Z"/>';
              b.appendChild(s);
              // 2) ::after 伪元素三角（绕过子节点路径，验证 pseudo 分支）
              b.classList.add('__probeTail');
              const st = document.createElement('style');
              st.id = '__probeTailStyle';
              st.textContent = '#oaDockList .bub.__probeTail::after,'
                + '.oa .bub.__probeTail::after{content:"";position:absolute;'
                + 'width:0;height:0;border:6px solid transparent;border-right-color:#f00;}';
              document.head.appendChild(st);
              return {ok:true};
            }""")
            if probe.get('err'):
                chk('E2 尾巴判据自检（注入子节点+伪元素三角，应被抓、撤净后回 0）', False, probe)
            else:
                inj = await tail_count(page)
                # 3) 撤净：移除子节点 / 类 / 样式
                await page.evaluate("""() => {
                  const home = document.getElementById('v-home');
                  home.querySelectorAll('.bub.__probeTail .tail').forEach(s => s.remove());
                  home.querySelectorAll('.bub.__probeTail').forEach(b => b.classList.remove('__probeTail'));
                  const st = document.getElementById('__probeTailStyle');
                  if(st) st.remove();
                }""")
                clean = await tail_count(page)
                ok = (inj['tails'] >= 1 and inj['pseudo'] >= 1
                      and clean['tails'] == 0 and clean['pseudo'] == 0)
                chk('E2 尾巴判据自检（注入子节点+伪元素三角，应被抓、撤净后回 0）',
                    ok,
                    {'基线': {'tails': 0, 'pseudo': 0},
                     '注入': {'tails': inj['tails'], 'pseudo': inj['pseudo']},
                     '撤净': {'tails': clean['tails'], 'pseudo': clean['pseudo']}})

            # E3 产物静态口径（不需浏览器）：构建产物 index.html 不得再生成 <svg class="tail">。
            # 只钉「生成串」—— .bub .tail 的 CSS 与 oaLayoutTails() 有意保留复用，不能一并禁。
            # 这条防「源码删了尾巴、却忘了重建 / 构建回退把尾巴又写回产物」。
            idx_text = ''
            try:
                idx_text = open(INDEX, encoding='utf-8').read()
            except Exception as e:
                chk('E3 构建产物 index.html 不再生成 <svg class="tail">', False, '读不到产物: ' + str(e)[:80])
            else:
                has_gen = '<svg class="tail"' in idx_text
                chk('E3 构建产物 index.html 不再生成 <svg class="tail">'
                    '（仅钉生成串；CSS 与 oaLayoutTails 保留）',
                    not has_gen, 'hit=%s' % has_gen)

            # E4 切走再切回首页：场景保留（当初为「几何落位」补的边界用例）。
            # 期望从「三角仍指向数字人」改为「仍然没有尾巴」——若有人把尾巴加回且
            # 忘记在切回时重新落位，这里仍会红。
            await page.click('#oaTabs .tab[data-view="kb"]')
            await page.wait_for_timeout(700)
            await page.click('#oaTabs .tab[data-view="home"]')
            await page.wait_for_timeout(900)
            tc2 = await tail_count(page)
            if tc2.get('skip'):
                chk('E4 切回首页后尾巴判据可测', False, tc2['skip'])
            else:
                chk('E4 切走再切回首页后气泡仍无尾巴（共 %d 个）' % tc2['bubbles'],
                    tc2['bubbles'] > 0 and tc2['tails'] == 0 and tc2['pseudo'] == 0,
                    'bubbles=%s tails=%s pseudo=%s' % (tc2['bubbles'], tc2['tails'], tc2['pseudo']))

            # E5 窄视口 320px：场景保留（原实现 <360px 退化，正是为「指向」补的边界）。
            # 期望从「三角仍指向数字人」改为「仍然没有尾巴」。
            await page.set_viewport_size({'width': 320, 'height': 844})
            await page.wait_for_timeout(700)
            await page.evaluate("() => window.oaLayoutTails()")
            await page.wait_for_timeout(250)
            tc3 = await tail_count(page)
            if tc3.get('skip'):
                chk('E5 窄视口下尾巴判据可测', False, tc3['skip'])
            else:
                chk('E5 窄视口 320px 下气泡仍无尾巴（共 %d 个）' % tc3['bubbles'],
                    tc3['bubbles'] > 0 and tc3['tails'] == 0 and tc3['pseudo'] == 0,
                    'bubbles=%s tails=%s pseudo=%s' % (tc3['bubbles'], tc3['tails'], tc3['pseudo']))
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
        # 序号即用户看到的自上而下顺序。第三项「OA 模块」是 43 个功能模块的目录入口
        # （每个模块一个数字人），由本轮需求新增，位置紧跟「新对话」。
        _dr_expected = ['新工作任务', '新对话', 'OA 模块', '定时任务', '插件-技能']
        chk('F2 抽屉动作项自上而下正确',
            len(dr['items']) >= len(_dr_expected) and
            all(x.startswith(y) for x, y in zip(dr['items'], _dr_expected)),
            'expected=%s got=%s' % (_dr_expected, dr['items']))
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

        async def ask(q, want_guide=False, want_form=False, want_permcard=False,
                     want_mask=False, settle_ms=700):
            """真实发一条消息并等回答收口（S.busy 释放 + 出现新的 AI 气泡）。

            收口（推荐块 / 请假表单 / 请假权限申请卡）要等一次 intent 调用才落地，故：
              · **正向**断言一律等明确的 DOM 条件（want_guide / want_form / want_permcard），不猜毫秒数；
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
            if want_permcard:
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('.notif-mask [data-leave-apply]').length > 0",
                        timeout=25000)
                except Exception:
                    pass
            if want_mask:
                try:
                    await page.wait_for_function(
                        "() => document.querySelectorAll('.notif-mask.show').length > 0",
                        timeout=25000)
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
        chk('H2b 推荐块无尾巴（与其它气泡同形，去掉了三角）', g1.get('hasTail') is False, g1)
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

        # ====================================================================
        # H5 段（新口径，docs/51 §1.4 / §1.5）：wjj_xu 现 held=true（docs/51 §0 实测，
        # 经 team-lead 重建重启后已生效），说「我要请假两天」
        # ⇒ action=APPLY_LEAVE、held=true ⇒ **直接跳转**（找不到 LEAVE_APPROVER 员工时
        # 先按 §1.5 创建再跳）→ 表单真出现在 OA 对话坞、且**真能被填并提交**（真实写操作，落一张请假单）。
        # 申请卡分支（held=false）由 zhangsan 覆盖，见 _verify_oa_leave_permcard.py。
        # 起点必须复位到「非请假数字人」——否则第一句就命中「已在请假数字人里 ⇒ 直接出表单」，
        # 跳转分支测不到。所有判定回源头：跳转/创建读 state.workers 与 oaState.worker.workerType；
        # 落库读提交后对话坞 .result-card 或表单 .lf-error 的后端 message；撤单走真实 HTTP。

        LEAVE_Q = '我要请假两天'      # 命中 APPLY_LEAVE（带申请意图，非 §1.3 反例词）

        # 环境闸门（非契约断言，暴露漂移）：本套件假定 wjj_xu 对 approval:leave 为 held=true
        # （新契约下有权限分支）；若漂移为 held=false，wjj_xu 会改走申请卡分支，本段前提失效。
        gate = await page.evaluate("""async () => {
          try { const c = await API.permissionCatalog();
            return ((c && c.items) || []).find(x => x.permissionCode === 'approval:leave') || null;
          } catch(e){ return {err: String((e && e.message) || e)}; } }""")
        chk('环境闸门：wjj_xu 对 approval:leave 应为 held=true（H5 跳转分支设计前提）',
            (gate or {}).get('held') is True, gate)

        # 计数助手：state.workers 里 LEAVE_APPROVER 数量
        def worker_count_js():
            return """() => {
              const ws = (typeof state !== 'undefined' && state.workers) || [];
              return ws.filter(w => String(w.workerType || '').toUpperCase() === 'LEAVE_APPROVER').length;
            }"""

        # ---- 复位到非请假数字人（H5 跳转分支起点；复用 H1 的选人机制） ----
        await page.click('#oaRobot')
        await page.wait_for_timeout(450)
        await page.click('#oaSheet .sheet-opt[data-target="workers"]')
        await page.wait_for_timeout(1000)
        await page.evaluate("""() => {
          const ws = state.workers || [];
          const rows = [...document.querySelectorAll('#oaWorkersList [data-worker]')];
          const pick = rows.find(r => {
            const w = ws.find(x => String(x.id) === r.dataset.worker) || {};
            return String(w.workerType || '').toUpperCase() !== 'LEAVE_APPROVER' && w.on !== false;
          });
          if(pick) pick.click();
        }""")
        await page.wait_for_timeout(900)
        before = await page.evaluate(worker_count_js())
        chk('§1.5 前置：演示库初始 LEAVE_APPROVER 员工数 = %d（0 表示本轮会创建）' % before, True)

        # ---- H5a 负向「不出现申请卡」+ 正向「跳转/§1.5 创建」 ----
        ha = await ask(LEAVE_Q, want_form=True)    # held=true ⇒ 表单出现（跳转后直出）
        chk_answered('H5a 回答已收口（有正文）', ha)
        await page.wait_for_timeout(1200)           # 负向给足窗口：确认不会 transient 弹卡
        mask_cnt = await page.evaluate("() => document.querySelectorAll('.notif-mask').length")
        chk('H5a 负向：held=true ⇒ 不弹权限申请卡（.notif-mask 计数 0）', mask_cnt == 0, {'mask': mask_cnt})
        cur = await page.evaluate("""() => {
          const w = window.oaState.worker || {};
          return { type: String(w.workerType || '').toUpperCase(), name: w.name || null };
        }""")
        form_now = await page.evaluate("() => document.querySelectorAll('#leaveForm').length")
        if cur['type'] != 'LEAVE_APPROVER' and form_now == 0:
            chk('H5a 跳转/§1.5 创建：当前对话对象切到 LEAVE_APPROVER 或表单直出', False,
                {'workerType': cur['type'], 'workerName': cur['name'], 'forms': form_now,
                 '归因': '既没跳到 LEAVE_APPROVER 也没出表单——前置未就绪'})
        else:
            chk('H5a 跳转/§1.5 创建：当前对话对象切到 LEAVE_APPROVER 或表单直出', True, cur)
        after1 = await page.evaluate(worker_count_js())
        if before == 0:
            chk('§1.5 无匹配员工 ⇒ 恰好创建 1 名 LEAVE_APPROVER', after1 == 1,
                {'before': before, 'after1': after1})
        else:
            chk('§1.5 已存在匹配员工 ⇒ 本次不再创建（after1 == before）', after1 == before,
                {'before': before, 'after1': after1})
        chk('H5a 已切到 LEAVE_APPROVER（顶栏/气泡可见反馈）', cur['type'] == 'LEAVE_APPROVER', cur)
        await shot(page, '17-oa-leave-jump')

        # 若跳转后未直接出表单（只在 LEAVE_APPROVER 上），再问一次 ⇒ 表单直出
        if form_now == 0:
            await ask(LEAVE_Q, want_form=True)
            await page.wait_for_timeout(600)
        after2 = await page.evaluate(worker_count_js())
        chk('§1.5.3 幂等：再触发一次后 LEAVE_APPROVER 员工数不变（不出现第二个）',
            after2 == after1, {'after1': after1, 'after2': after2})

        # ---- H5b §1.4 表单落在 OA 对话坞 + 假种来自后端 ----
        leave_info = await page.evaluate("""() => {
          const f = document.getElementById('leaveForm');
          const dock = document.getElementById('oaDockList');
          const sel = document.getElementById('lfType');
          const opts = sel ? [...sel.options].map(o => ({value: o.value, text: o.text})) : [];
          return { count: document.querySelectorAll('#leaveForm').length,
                   inDock: !!(f && dock && dock.contains(f)),
                   types: opts.length, firstText: opts.length ? opts[0].text : null, opts };
        }""")
        chk('H5b §1.4 表单出现在 OA 对话坞内（#leaveForm 祖先是 #oaDockList）',
            leave_info['inDock'] is True, leave_info)
        chk('H5b §1.4 假种下拉来自后端 GET /v1/leave/types（options>0 且首项非「暂无」）',
            leave_info['types'] > 0 and '暂无' not in str(leave_info['firstText']), leave_info)
        await shot(page, '18-oa-leave-form')

        # ---- H5c 真填真提交（真实写操作，会落一张请假单） ----
        # 选假种：年假有「提前 3 天申请」限制、病假「必须上传证明材料」，近日期/无附件必被业务驳回，
        # 拿不到可撤单据就没法验证撤单收尾。优先事假（不占额度，一般无提前/证明限制），其次病假，再次年假。
        pick_type = await page.evaluate("""() => {
          const sel = document.getElementById('lfType');
          if(!sel) return {err: '无 lfType'};
          const opts = [...sel.options].filter(x => x.value && x.value.trim() !== '');
          if(!opts.length) return {err: '无可选假种'};
          const pref = opts.find(x => x.value === 'CASUAL')
                    || opts.find(x => x.value === 'SICK')
                    || opts[0];
          return {value: pref.value, text: pref.text};
        }""")
        if pick_type.get('err'):
            chk('H5c 填表：取到可选假种', False, pick_type)
        else:
            reason_text = '自动化回归：wjj_xu 请假直达提交可见性验证'
            await page.select_option('#lfType', value=pick_type['value'])
            msgs_before = await page.evaluate(
                "() => document.querySelectorAll('#msgs .result-card').length")
            # 提交前先拉一次 leaveMine，记下已有单据 id 集合，用于提交后「差量」定位本次新建单据的 PK
            _tk = _leave_login(USER, PWD)
            _mine0 = _leave_mine(_tk) if _tk else None
            mine_before_ids = set(str(x.get('id')) for x in
                                 (((_mine0 or {}).get('data') or []) if isinstance(_mine0, dict) else (_mine0 or [])))

            # 捕获提交响应状态（resp.json 是协程必须 await）。
            # 注意：提交响应体的 leaveRequestId 实际是「工作流 orderId」而非请假单 PK，
            # 撤单接口 cancel(id) 要的是请假单 PK（leaveMine 的 id 字段），故 PK 一律以 leaveMine 差量为准。
            sub_order_id = {'v': None}
            sub_http = {'status': None, 'url': None}
            async def _on_resp(resp):
                u = resp.url or ''
                if (resp.request.method or '') == 'POST' and u.rstrip('/').endswith('/requests') \
                        and '/v1/leave/requests' in u:
                    sub_http['status'] = resp.status
                    sub_http['url'] = u
                    try:
                        b = await resp.json()
                    except Exception:
                        return
                    if isinstance(b, dict) and b.get('leaveRequestId'):
                        sub_order_id['v'] = b.get('leaveRequestId')
            page.on('response', _on_resp)

            # 真填真提交；若后端按「提前申请」规则驳回，按「最早可申请」日期后移再试（最多 3 次）。
            ok_dock = ok_err = False
            dock_card = {'count': 0, 'text': None}
            lf_err = {'shown': False, 'text': None}
            sub_res = None
            shift = 1
            for attempt in range(3):
                d = await page.evaluate("""(shift) => {
                  const pad = n => (n < 10 ? '0' + n : '' + n);
                  const add = days => { const t = new Date(); t.setDate(t.getDate() + days);
                    return t.getFullYear() + '-' + pad(t.getMonth()+1) + '-' + pad(t.getDate()); };
                  return { start: add(shift), end: add(shift + 1) };
                }""", shift)
                await page.fill('#lfStart', d['start'])
                await page.fill('#lfEnd', d['end'])
                await page.fill('#lfReason', reason_text)
                await page.wait_for_timeout(200)
                # 表单里三枚按钮：证明材料上传（最先）、提交、取消；
                # 必须精确点到「提交请假申请」那枚（onclick 含 submitLeave），否则会点到上传按钮、整条链路不提交。
                await page.click('#leaveForm button[onclick*="submitLeave"]')
                try:
                    await page.wait_for_function(
                        "() => { const dk = document.getElementById('oaDockList'); "
                        "if(dk && dk.querySelector('.result-card')) return true; "
                        "const e = document.getElementById('lfError'); "
                        "return !!e && e.style.display !== 'none' && e.textContent.trim() !== ''; }",
                        timeout=25000)
                except Exception:
                    pass
                await page.wait_for_timeout(400)
                dock_card = await page.evaluate("""() => {
                  const dk = document.getElementById('oaDockList');
                  const c = dk ? dk.querySelector('.result-card') : null;
                  return { count: dk ? dk.querySelectorAll('.result-card').length : 0,
                           text: c ? c.textContent.replace(/\\s+/g, ' ').trim() : null };
                }""")
                lf_err = await page.evaluate("""() => {
                  const e = document.getElementById('lfError');
                  return { shown: !!e && e.style.display !== 'none' && e.textContent.trim() !== '',
                           text: e ? e.textContent.trim() : null };
                }""")
                if dock_card['count'] > 0:
                    ok_dock = True
                    break
                if lf_err['shown']:
                    # 提前申请规则：最早可申请 YYYY-MM-DD → 起始日移到该日期后重试
                    try:
                        repl = await page.evaluate("""(txt) => {
                          const mm = (txt || '').match(/最早可申请\\s*(\\d{4}-\\d{2}-\\d{2})/);
                          if(!mm) return null;
                          const t = new Date(); t.setHours(0,0,0,0);
                          const e = new Date(mm[1] + 'T00:00:00');
                          return Math.ceil((e.getTime() - t.getTime()) / 86400000);
                        }""", lf_err['text'])
                    except Exception:
                        repl = None
                    if repl is not None:
                        shift = max(shift + 1, repl)
                        continue
                    ok_err = True
                    sub_res = lf_err['text']
                    break
                break  # 既无结果也无错误：异常，跳出

            chk('H5c 提交可见性：结果落在 OA 对话坞（.result-card）或 表单内显示后端 message',
                ok_dock or ok_err, {'dock': dock_card, 'lfError': lf_err, 'shift': shift})
            print('    · 提交 HTTP：%s %s（响应体 leaveRequestId(=orderId)=%s）' %
                  (sub_http['status'], sub_http['url'], sub_order_id['v']))
            if dock_card['text']:
                print('    · 提交回执（对话坞）：' + dock_card['text'][:220]); sub_res = dock_card['text']
            if lf_err['text'] and not sub_res:
                print('    · 后端拒绝原因（表单内）：' + lf_err['text'][:220]); sub_res = lf_err['text']
            if sub_res:
                print('    · 提交结果原文（真实写操作，已原样贴出）：' + sub_res[:240])
            msgs_after = await page.evaluate(
                "() => document.querySelectorAll('#msgs .result-card').length")
            chk('H5c 提交负向：结果未写进 #msgs（OA 下不可见容器不应出现结果卡）',
                msgs_after == 0, {'msgs_before': msgs_before, 'msgs_after': msgs_after})
            await shot(page, '19-oa-leave-submit')

            # ---- H5d 收尾撤单（真实写操作后必须复位，否则二次跑污染；撤不掉如实报告） ----
            # 撤单接口 cancel(id) 要的是请假单 PK（leaveMine 的 id 字段），不是提交响应里的 leaveRequestId（那是 orderId）。
            # 用「提交前后 leaveMine 差量」定位本次新建单据的 PK：优先按提交理由精确匹配，其次取新增的待审批单据。
            rid = None
            if ok_dock:
                try:
                    tk = _leave_login(USER, PWD)
                    mine = _leave_mine(tk) if tk else None
                    items = ((mine or {}).get('data') or []) if isinstance(mine, dict) else (mine or [])
                    fresh = [x for x in items if str(x.get('id')) not in mine_before_ids]
                    for x in fresh:
                        if (x.get('reason') or '') == reason_text and \
                                str(x.get('status', '')).upper() in ('PENDING', 'SUBMITTED', 'APPROVING'):
                            rid = x.get('id'); break
                    if rid is None and fresh:
                        rid = fresh[0].get('id')
                    if rid is not None:
                        rid = str(rid)
                except Exception as ex:
                    print('    · 收尾：leaveMine 差量定位失败：' + str(ex)[:120])
            if rid:
                st, body = _leave_cancel(_leave_login(USER, PWD), rid)
                ok_cancel = st == 200 and (str((body or {}).get('code', '')) == '0'
                                          or 'CANCEL' in json.dumps(body, ensure_ascii=False).upper())
                chk('H5d 收尾：撤单成功（单据 CANCELED）', ok_cancel,
                    {'rid': rid, 'http': st, 'body': body})
                if not ok_cancel:
                    print('    · 收尾：撤单未成功，单据可能残留，需手动复位！rid=%s' % rid)
            else:
                if ok_err:
                    chk('H5d 收尾：提交被业务规则驳回（无单据生成，无需撤单）', True,
                        '后端拒绝：' + (lf_err['text'] or '未知'))
                else:
                    chk('H5d 收尾：拿到请假单 PK 可撤单', False,
                        '提交成功但 leaveMine 差量未定位到新建单据 PK——单据可能残留，需手动复位')

        # ---- H8 经典形态仍可独立发放请假表单（OA 流程改走跳转/创建后，经典表单不应被影响） ----
        # 注：经典表单与 OA 请假直达是两条独立链路；这里只冒烟「经典侧仍能发一份表单」。
        await page.evaluate("() => window.oaSetMode('classic')")
        await page.wait_for_timeout(1500)
        await page.evaluate("() => { if(typeof openLeaveFlow === 'function') openLeaveFlow(); }")
        await page.wait_for_timeout(900)
        h8 = await page.evaluate("() => document.querySelectorAll('#leaveForm').length")
        chk('H8 经典形态可正常发放请假表单（文档内恰好 1 份）', h8 == 1, h8)
        await page.evaluate("() => window.oaSetMode('oa')")
        await page.wait_for_timeout(800)

        # ---------------- 控制台 ----------------
        # 401 /v1/asr/status 是输入栏初始化时的语音能力探活：此刻还没有 token，必然 401，
        # 应用侧 catch 后 fail-open（见 _backup_index_pre_oa.html:4539-4568 的注释）。
        # 但「整类不看」会掩盖真缺陷 ⇒ 只按身份放行，两条判据都必须成立：
        #   ① 非「资源加载失败」类的 console.error / 任何 pageerror：必须为零（真 JS 异常）
        #   ② 非 2xx 响应：必须全部是「401 …/v1/asr/status」，出现别的 URL 即红
        js_errors = [e for e in errors
                     if not e.startswith('console.error: Failed to load resource')]
        other_net = [r for r in bad_resp
                     if not ('/v1/asr/status' in r and r.startswith('401'))]
        chk('G1 console 无 error / 无未捕获异常（ASR 探活 401 按身份放行）',
            not js_errors and not other_net,
            'JS异常=%s 其它非2xx=%s' % (js_errors[:3], other_net[:3]))

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
    if bad_resp:
        print('非 2xx 响应 %d 条：' % len(bad_resp))
        for r in bad_resp[:15]:
            print('  ' + r[:200])
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        rc = asyncio.run(main())
    except Exception as exc:
        # 中途异常也要把已跑出的结论与截图交出来，否则「跑到一半崩了」会被误读成「全挂」
        chk('流程未跑完（异常中断）', False, '%s: %s' % (type(exc).__name__, str(exc)[:160]))
        rc = 1
    sys.exit(rc or (1 if fails else 0))
