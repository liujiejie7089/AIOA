#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OA 请假「无权限 ⇒ 权限申请卡」分支的**可重复跑**回归哨兵（Playwright + msedge 无头，390x844 @2x）。

覆盖 docs/51 §0 / §1.2 / §1.3 / §1.4 / §3（以文档口径为准，2026-10-17 修订）。

账号（docs/51 §0 实测，勿改）：
  fagai_liu  / User@123 → tenant2 普通成员，机构1（admin_user_id=4），held=false/pending=false
                        【主申请人，走完整成功链路：卡→申请→冻结→落库→幂等→收尾】
  zhangsan   / User@123 → tenant0 遗留账号，org_member 无归属；tenant0 下机构数为 0
                        【失败口径账号：apply 必被 FR-B2 拒绝，验证「失败就地显示后端 message」】
  fagai_admin/ User@123 → 机构1 管理员（user_id=4），收尾驳回人（首节点 ORG_ADMIN ⇒ 待办落机构管理员）
  admin      / Admin@123 → 平台管理员，收尾兜底 + 对照

断言纪律（与 _verify_oa_leave_submit.py / _e2e_oa.py 同源）：
  · 判定回事实源头：DOM 走真实渲染；判权走真实 HTTP（API.permissionCatalog() / requests 直连），
    绝不读界面缓存副本（如 state.permCatalog）；
  · 正向等明确 DOM 条件（wait_for_selector / wait_for_function），不猜毫秒；
  · 负向给足窗口；卡片交互前先判空再点；
  · 禁止恒真断言；禁止为转绿放宽。

两遍跑（同一命令）证明可重复：PENDING 不可自助撤回，故收尾驳回是硬要求，否则第二遍必红。

失败口径段（docs/51 §1.4）写成**按结果分支**而非硬编码失败：先看 apply 响应，
成功断言冻结+落库、失败断言「错误就地显示+按钮恢复+未假装落库」，并断言二者互斥 ——
环境修好后不会假红。
"""
import asyncio
import json
import os
import sys
import requests

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'           # H5 静态服务（同域代理 /api → :8080）
API_BASE = 'http://127.0.0.1:8080'          # 后端直连（Python requests 用）
APPL_USER, APPL_PWD = 'fagai_liu', 'User@123'     # 主申请人（成功链路）
FAIL_USER, FAIL_PWD = 'zhangsan', 'User@123'       # 失败口径账号
ADMIN_USER, ADMIN_PWD = 'fagai_admin', 'User@123'  # 收尾驳回（机构1管理员）
PLAT_USER, PLAT_PWD = 'admin', 'Admin@123'         # 平台管理员（兜底）
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_shot_oa_permcard')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

fails, envs, shots, apply_calls, apply_responses, errors = [], [], [], [], [], []
PASS_CNT = 0


def chk(name, ok, detail=''):
    global PASS_CNT
    if ok:
        PASS_CNT += 1
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


def env(note, detail=''):
    """环境未就绪 / 非代码缺陷导致无法判定：如实报出，计入非零退出，但不算代码 FAIL。"""
    envs.append(note + (' — ' + str(detail) if detail else ''))
    print('[ENV] %s%s' % (note, (' — ' + str(detail)) if detail else ''))


async def shot(page, name):
    p = os.path.join(OUT, name + '.png')
    try:
        await page.screenshot(path=p)
        shots.append(name)
    except Exception as e:
        print('  （截图失败 %s：%s）' % (name, str(e)[:60]))
    return p


def dump_logs():
    for fn in ('logs/backend.log', 'logs/agent.log'):
        path = os.path.join(ROOT, fn)
        print('  ── %s ──' % fn)
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                lines = fh.read().splitlines()
            tail = [l for l in lines[-60:] if ('ERROR' in l or 'Exception' in l
                                              or 'WARN' in l or 'Caused by' in l)]
            for l in (tail[-20:] if tail else lines[-12:]):
                print('     ' + l[:200])
        except Exception as e:
            print('     （读不到：%s）' % str(e)[:80])


# ---------------- HTTP 助手（requests 直连后端，真实 HTTP = 事实源头） ----------------
def http_login(user, pwd):
    r = requests.post(API_BASE + '/api/v1/auth/login',
                      json={'username': user, 'password': pwd}, timeout=30)
    if r.status_code != 200:
        return None, 'HTTP %d' % r.status_code
    b = r.json()
    if b.get('code') != 0:
        return None, 'code=%s msg=%s' % (b.get('code'), b.get('message'))
    tok = (b.get('data') or {}).get('accessToken')
    return (tok, None) if tok else (None, '无 accessToken')


def http_catalog(token):
    r = requests.get(API_BASE + '/api/v1/org/permissions/catalog',
                     headers={'Authorization': 'Bearer ' + token}, timeout=30)
    if r.status_code != 200:
        return None, 'HTTP %d' % r.status_code
    b = r.json()
    if b.get('code') != 0:
        return None, 'code=%s' % b.get('code')
    return b.get('data') or {}, None


def find_leave(cat):
    items = (cat or {}).get('items') or []
    for it in items:
        if it.get('permissionCode') == 'approval:leave':
            return it
    return None


def http_tasks_todo(token):
    r = requests.get(API_BASE + '/api/v1/workflow/tasks?scope=todo',
                     headers={'Authorization': 'Bearer ' + token}, timeout=30)
    if r.status_code != 200:
        return None, 'HTTP %d' % r.status_code
    b = r.json()
    if b.get('code') != 0:
        return None, 'code=%s' % b.get('code')
    return b.get('data') or [], None


def http_decide(task_id, token, decision='REJECT', note='e2e 复位'):
    r = requests.post(API_BASE + '/api/v1/workflow/tasks/%s/decide' % task_id,
                      json={'decision': decision, 'note': note},
                      headers={'Authorization': 'Bearer ' + token}, timeout=30)
    try:
        body = r.json()
    except Exception:
        body = {'_raw': r.text[:200]}
    return r.status_code, body


# ---------------- 抓包：路由拦截 apply 请求（CDP Fetch.requestPaused 透出请求体） ----------------
async def capture_apply(route):
    req = route.request
    pd = None
    try:
        pd = req.post_data
    except Exception:
        pd = None
    apply_calls.append({'url': req.url, 'post': pd})
    await route.continue_()


async def on_response(resp):
    u = resp.url
    if '/v1/org/permissions/apply' in u and resp.request.method == 'POST':
        pd = None
        try:
            pd = resp.request.post_data
        except Exception:
            pd = None
        body = None
        try:
            body = await resp.text()
        except Exception:
            body = None
        apply_responses.append({'url': u, 'post': pd, 'status': resp.status, 'body': body})


def on_console(m):
    if m.type == 'error':
        loc = ''
        try:
            loc = (m.location or {}).get('url', '') if m.location else ''
        except Exception:
            loc = ''
        errors.append({'src': 'console', 'text': m.text, 'url': loc})


def on_pageerror(e):
    errors.append({'src': 'pageerror', 'text': str(e), 'url': ''})


# ---------------- 浏览器交互助手 ----------------
async def login_ui(page, user, pwd):
    await page.goto(BASE, wait_until='domcontentloaded')
    await page.wait_for_timeout(900)
    await page.fill('#lgUser', user)
    await page.fill('#lgPass', pwd)
    await page.click('#lgBtn')
    await page.wait_for_selector('body.auth', timeout=15000)


async def enter_oa(page):
    await page.evaluate("() => window.oaSetMode && window.oaSetMode('oa')")
    await page.wait_for_timeout(800)
    chk('已切到 OA 形态（.phone.oa-mode 生效）',
        await page.evaluate("() => !!document.querySelector('.phone.oa-mode')"))
    try:
        await page.wait_for_selector('#oaInput', timeout=10000)
    except Exception:
        chk('OA 对话输入区就绪（#oaInput）', False, '超时')
        return False
    return True


async def send_msg(page, q):
    b0 = await page.evaluate("() => document.querySelectorAll('#oaDockList .bub').length")
    await page.fill('#oaInput', q)
    await page.click('#oaSendBtn')
    try:
        await page.wait_for_function("() => !window.oaState || !window.oaState.busy", timeout=90000)
    except Exception:
        pass
    try:
        await page.wait_for_function(
            "() => document.querySelectorAll('#oaDockList .bub').length > %d" % b0, timeout=90000)
    except Exception:
        pass
    return b0


async def card_present(page):
    try:
        await page.wait_for_selector('.notif-mask', timeout=30000)
        return True
    except Exception:
        return False


async def dock_last_text(page):
    return await page.evaluate("""() => {
      const bs = document.querySelectorAll('#oaDockList .bub');
      return bs.length ? (bs[bs.length-1].innerText || '') : ''; }""") or ''


async def close_card(page):
    has = await page.evaluate("() => !!document.querySelector('.notif-mask [data-dlg-cancel]')")
    if has:
        await page.evaluate("() => { const b=document.querySelector('.notif-mask [data-dlg-cancel]'); if(b) b.click(); }")
        await page.wait_for_timeout(500)


# ---------------- 前置自愈：fagai_liu 上轮残留 pending=true ⇒ fagai_admin 驳回 ----------------
def self_heal(admin_token, appl_token):
    tasks, te = http_tasks_todo(admin_token)
    if te:
        env('前置自愈：fagai_admin 取待办失败（%s）' % te)
        return
    cand = [t for t in tasks if ('请假' in str(t.get('title', ''))
            or 'PERMISSION' in str(t.get('bizType', ''))
            or '权限' in str(t.get('title', '')))]
    print('    候选：' + json.dumps(cand, ensure_ascii=False)[:600])
    if cand:
        tid = cand[0].get('taskId')
        st, body = http_decide(tid, admin_token, 'REJECT', 'e2e 自愈')
        print('    驳回 HTTP %s：%s' % (st, json.dumps(body, ensure_ascii=False)[:200]))
        cat_r, _ = http_catalog(appl_token)
        lv_r = find_leave(cat_r)
        chk('前置自愈：驳回后 fagai_liu pending 回 false', lv_r is not None and lv_r.get('pending') is False, lv_r)
    else:
        env('前置自愈：fagai_admin 待办中无 fagai_liu 请假申请任务')


# ---------------- 阶段 A：fagai_liu 成功链路 ----------------
async def run_success_path(page, appl_token, admin_token):
    apply_calls.clear()
    apply_responses.clear()

    # 意图前置：必须真返回 action=APPLY_LEAVE（旧契约无 action ⇒ 如实报「前置未就绪」并停）
    probe = await page.evaluate("""async () => {
      try {
        const r = await API.workerIntent('我要请假');
        return {ok:true, action:r&&r.action, held:r&&r.held, pending:r&&r.pending,
                role:r&&r.role, reqPerm:r&&r.requiredPermission};
      } catch(e){ return {ok:false, err:(e&&e.message)||String(e)}; }
    }""")
    if not probe.get('ok') or probe.get('action') != 'APPLY_LEAVE':
        chk('前置：intent 返回 action=APPLY_LEAVE（新契约已部署）', False, probe)
        env('前置未就绪：intent 无 action 字段（旧契约 / agent :8000 未起）')
        dump_logs()
        return False
    chk('前置：intent 返回 action=APPLY_LEAVE（新契约已部署）', True, probe)
    chk('前置：intent 含 held/pending 判权字段',
        probe.get('held') is not None and probe.get('pending') is not None, probe)

    # 前置：catalog + 自愈
    cat0, ce = http_catalog(appl_token)
    if ce:
        env('前置：读 fagai_liu catalog 失败（%s），跳过自愈' % ce)
    else:
        lv0 = find_leave(cat0)
        chk('前置：catalog 含 approval:leave 项', lv0 is not None, lv0)
        if lv0 and lv0.get('pending') is True:
            print('  · 前置自愈：fagai_liu 上轮残留 pending=true，fagai_admin 驳回复位…')
            self_heal(admin_token, appl_token)
        else:
            chk('前置：fagai_liu 初始 approval:leave.pending 为 false（无残留）',
                lv0 is not None and lv0.get('pending') is False, lv0)

    # 1 卡出现
    await close_card(page)
    await send_msg(page, '我要请假两天')
    appeared = await card_present(page)
    if not appeared:
        dtext = await dock_last_text(page)
        if any(k in dtext for k in ('额度', '请求失败', '403', '网络', '未返回内容')):
            env('步骤1(fagai_liu)：对话未产生回答（疑似额度/网络，非代码缺陷）', dtext[:120])
            dump_logs()
            return False
        chk('步骤1：说「我要请假两天」后弹出权限申请卡（.notif-mask）', False, dtext[:120])
        dump_logs()
        return False
    head = await page.evaluate("""() => {
      const m = document.querySelector('.notif-mask');
      const h = m && m.querySelector('.notif-head');
      return h ? h.textContent.trim() : ''; }""")
    has_apply = await page.evaluate("() => !!document.querySelector('.notif-mask [data-leave-apply]')")
    has_cancel = await page.evaluate("() => !!document.querySelector('.notif-mask [data-dlg-cancel]')")
    form_cnt = await page.evaluate("() => document.querySelectorAll('#leaveForm').length")
    chk('步骤1：卡标题含「请假审批」（办理请假需要「请假审批」权限）', '请假审批' in head, head)
    chk('步骤1：卡含 [帮我申请] 与 [取消] 两个按钮', has_apply and has_cancel,
        {'apply': has_apply, 'cancel': has_cancel})
    chk('步骤1：无权限 ⇒ 不直出请假表单（#leaveForm 计数 == 0，卡片与表单互斥）', form_cnt == 0, 'count=%d' % form_cnt)
    # 精准缺陷检测：发消息后、尚未点 [帮我申请] 前，pending 必须为 false。
    # 若已变 true ⇒ 后端在「说一句话」时就服务端自动申请了，违反 docs/51 §1.4「手动申请」契约。
    cat_b, _ = http_catalog(appl_token)
    lv_b = find_leave(cat_b) if cat_b else None
    chk('步骤1b：发「我要请假两天」后、未点[帮我申请]前，catalog.pending 仍 false（不应服务端自动申请）',
        lv_b is not None and lv_b.get('pending') is False, lv_b)
    await shot(page, 'A01-permcard')

    # 2 取消口径（§1.4：取消 = 不落库）
    n_before = len(apply_calls)
    await close_card(page)
    gone = await page.evaluate("() => document.querySelectorAll('.notif-mask').length == 0")
    chk('步骤2：点 [取消] 后卡片消失', gone)
    cat_c, _ = http_catalog(appl_token)
    lv_c = find_leave(cat_c) if cat_c else None
    chk('步骤2：取消后 catalog 中 pending 仍 false（未落库）',
        lv_c is not None and lv_c.get('pending') is False, lv_c)
    n_after = len(apply_calls)
    chk('步骤2：取消当轮 POST /v1/org/permissions/apply 请求数 == 0（硬证据：取消没提交）',
        n_after == n_before, {'before': n_before, 'after': n_after,
                              'calls': apply_calls[n_before:]})

    # 3 申请正向
    await send_msg(page, '我要请假两天')
    appeared2 = await card_present(page)
    if not appeared2:
        env('步骤3：二次触发卡片未出现（对话未回答？）', (await dock_last_text(page))[:120])
        return False
    has_apply2 = await page.evaluate("() => !!document.querySelector('.notif-mask [data-leave-apply]')")
    chk('步骤3：再次触发卡片且仍含 [帮我申请]（pending 仍 false）', has_apply2)
    if not has_apply2:
        return False
    n0 = len(apply_calls)
    await page.wait_for_selector('.notif-mask [data-leave-apply]', timeout=10000)
    await page.click('.notif-mask [data-leave-apply]')
    frozen = False
    try:
        await page.wait_for_function("""() => {
          const m = document.querySelector('.notif-mask');
          if(!m) return false;
          const msg = m.querySelector('.oa-perm-msg');
          const applyGone = !m.querySelector('[data-leave-apply]');
          const hasSubmitted = !!msg && /已提交/.test(msg.textContent||'');
          return applyGone && hasSubmitted;
        }""", timeout=25000)
        frozen = True
    except Exception:
        frozen = False
    delta = len(apply_calls) - n0
    chk('步骤3：恰好发出 1 条 POST /v1/org/permissions/apply', delta == 1,
        {'delta': delta, 'total': len(apply_calls)})
    resp = apply_responses[-1] if apply_responses else None
    if resp is not None:
        print('  · 申请响应 HTTP %s：%s' % (resp.get('status'), str(resp.get('body'))[:300]))
    if delta >= 1:
        post = apply_calls[n0].get('post')
        if post:
            try:
                body = json.loads(post)
            except Exception:
                body = {'_raw': post}
        elif resp is not None and resp.get('post'):
            try:
                body = json.loads(resp['post'])
            except Exception:
                body = {'_raw': resp.get('post')}
        else:
            body = None
            print('  · 申请请求体未被 harness 捕获（post_data 为空），详见响应回执。')
        chk('步骤3：apply body permissionCode==approval:leave',
            isinstance(body, dict) and body.get('permissionCode') == 'approval:leave', body)
        chk('步骤3：apply body targetWorkerType==LEAVE_APPROVER',
            isinstance(body, dict) and body.get('targetWorkerType') == 'LEAVE_APPROVER', body)
        chk('步骤3：apply body reason 非空',
            isinstance(body, dict) and bool(str(body.get('reason', '')).strip()), body)
    # 卡片冻结
    foot = await page.evaluate("""() => {
      const m = document.querySelector('.notif-mask');
      if(!m) return {none:true};
      return { applyGone: !m.querySelector('[data-leave-apply]'),
               cancelOnly: m.querySelectorAll('.notif-foot [data-dlg-cancel]').length === 1,
               msg: (m.querySelector('.oa-perm-msg')||{}).textContent || '' }; }""")
    chk('步骤3：卡片冻结（无 [帮我申请]、foot 仅剩 [关闭]、提示含「已提交」）',
        foot.get('applyGone') and foot.get('cancelOnly')
        and '已提交' in str(foot.get('msg', '')), foot)
    # 落库
    cat_p, _ = http_catalog(appl_token)
    lv_p = find_leave(cat_p) if cat_p else None
    chk('步骤3：申请后 catalog approval:leave.pending === true（真实落库）',
        lv_p is not None and lv_p.get('pending') is True, lv_p)
    await shot(page, 'A03-applied')
    await close_card(page)
    applied = lv_p is not None and lv_p.get('pending') is True

    # 4 pending 幂等
    if applied:
        await send_msg(page, '我要请假两天')
        appeared3 = await card_present(page)
        if appeared3:
            no_apply = await page.evaluate("() => !document.querySelector('.notif-mask [data-leave-apply]')")
            has_cancel3 = await page.evaluate("() => !!document.querySelector('.notif-mask [data-dlg-cancel]')")
            chk('步骤4：pending 态再问 ⇒ 卡片出现但无 [帮我申请]（不给二次提交）', no_apply, {'apply_gone': no_apply})
            chk('步骤4：pending 态卡片仍有 [取消] 可关', has_cancel3)
            await shot(page, 'A04-pending-idempotent')
            await close_card(page)
        else:
            chk('步骤4：pending 态再问弹出卡片', False, '未出现')
    else:
        chk('步骤4：pending 幂等（跳过，步骤3 未成功申请）', False, '步骤3 未落库')

    # 5 反例（§1.3）
    await close_card(page)
    await send_msg(page, '年假有几天')
    await page.wait_for_timeout(4000)
    mask_cnt = await page.evaluate("() => document.querySelectorAll('.notif-mask').length")
    form_cnt2 = await page.evaluate("() => document.querySelectorAll('#leaveForm').length")
    chk('步骤5：§1.3 反例「年假有几天」⇒ 不出申请卡（.notif-mask 计数 0）', mask_cnt == 0, 'count=%d' % mask_cnt)
    chk('步骤5：§1.3 反例「年假有几天」⇒ 不出表单（#leaveForm 计数 0）', form_cnt2 == 0, 'count=%d' % form_cnt2)
    return applied


# ---------------- 阶段 B：zhangsan 失败口径（docs/51 §1.4，按结果分支） ----------------
async def run_failure_path(page, fail_token):
    apply_calls.clear()
    apply_responses.clear()
    await close_card(page)
    await send_msg(page, '我要请假两天')
    appeared = await card_present(page)
    if not appeared:
        dtext = await dock_last_text(page)
        if any(k in dtext for k in ('额度', '请求失败', '403', '网络')):
            env('失败口径(zhangsan)：对话未回答（疑似额度/网络）', dtext[:120])
            return
        chk('失败口径(zhangsan)：无权限 ⇒ 弹出申请卡（前置）', False, dtext[:120])
        return
    chk('失败口径(zhangsan)：无权限（tenant0 无机构）⇒ 仍弹出申请卡', True)
    has_apply = await page.evaluate("() => !!document.querySelector('.notif-mask [data-leave-apply]')")
    if not has_apply:
        chk('失败口径(zhangsan)：卡含 [帮我申请]', False, '无按钮')
        return
    n0 = len(apply_calls)
    await page.wait_for_selector('.notif-mask [data-leave-apply]', timeout=10000)
    await page.click('.notif-mask [data-leave-apply]')
    await page.wait_for_timeout(3000)
    resp = apply_responses[-1] if apply_responses else None
    accepted = False
    bmsg = ''
    if resp is not None:
        try:
            rb = json.loads(resp['body']) if resp.get('body') else {}
        except Exception:
            rb = {}
        accepted = resp.get('status') == 200 and rb.get('code') == 0
        bmsg = rb.get('message', '')
    # 卡片状态
    frozen = await page.evaluate("""() => {
      const m = document.querySelector('.notif-mask');
      if(!m) return {none:true};
      const applyGone = !m.querySelector('[data-leave-apply]');
      const msg = (m.querySelector('.oa-perm-msg')||{}).textContent || '';
      return {applyGone, frozen: applyGone && /已提交/.test(msg), msg}; }""")
    errored = await page.evaluate("""() => {
      const e = document.querySelector('#leavePermErr');
      if(!e) return {visible:false, text:''};
      const st = getComputedStyle(e).display;
      return {visible: st !== 'none', text: e.textContent || ''}; }""")
    btn_enabled = await page.evaluate("""() => {
      const b = document.querySelector('.notif-mask [data-leave-apply]');
      return b ? !b.disabled : true; }""")
    cat_f, _ = http_catalog(fail_token)
    lv_f = find_leave(cat_f) if cat_f else None
    pending_after = lv_f.get('pending') if lv_f else None
    delta = len(apply_calls) - n0

    if accepted:
        # 环境若修复、zhangsan 也能申请时的预期
        chk('失败口径(zhangsan)：apply 成功 ⇒ 卡片冻结+落库',
            bool(frozen.get('frozen')) and pending_after is True, {'frozen': frozen, 'pending': pending_after})
    else:
        # 当前事实：FR-B2 拒绝。断言「失败就地显示后端 message，不吞掉、不弹通用 toast」
        chk('失败口径(zhangsan)：失败 ⇒ #leavePermErr 可见且含后端 message',
            errored.get('visible') and bool(bmsg) and bmsg in errored.get('text', ''),
            {'backend_msg': bmsg, 'err_text': errored.get('text', '')[:200]})
        chk('失败口径(zhangsan)：失败后 [帮我申请] 恢复可点（非永久 disabled）', btn_enabled, btn_enabled)
        chk('失败口径(zhangsan)：失败后 pending 仍为 false（未假装落库）', pending_after is False, pending_after)
    # 互斥：不会既失败又冻结
    chk('失败口径(zhangsan)：冻结态与错误态互斥（不既失败又冻结）',
        not (bool(frozen.get('frozen')) and errored.get('visible')),
        {'frozen': frozen.get('frozen'), 'errored': errored.get('visible'), 'delta': delta})
    print('  · 失败口径本轮落在：%s 分支（apply delta=%d，backend message=%s）'
          % ('成功' if accepted else '失败', delta, bmsg[:80]))
    await shot(page, 'B-failure-zhangsan')
    await close_card(page)


# ---------------- 收尾清理（机构管理员驳回，硬要求） ----------------
def do_cleanup(admin_token, plat_token, appl_token):
    cat, _ = http_catalog(appl_token)
    lv = find_leave(cat)
    if not lv or lv.get('pending') is not True:
        print('  · 收尾：fagai_liu 无在途 PENDING，无需驳回。')
        return
    tasks_a, te = http_tasks_todo(admin_token)
    if te:
        env('收尾：fagai_admin 取待办失败（%s）' % te)
        return
    cand = [t for t in tasks_a if ('请假' in str(t.get('title', ''))
            or 'PERMISSION' in str(t.get('bizType', ''))
            or '权限' in str(t.get('title', '')))]
    print('  · 收尾：fagai_admin 待办候选：' + json.dumps(cand, ensure_ascii=False)[:800])
    if not cand:
        # 兜底：平台 admin
        tasks_p, te2 = http_tasks_todo(plat_token)
        print('  · 收尾：平台 admin 待办候选：' + json.dumps(tasks_p, ensure_ascii=False)[:800])
        cand = [t for t in (tasks_p or []) if ('请假' in str(t.get('title', ''))
                or 'PERMISSION' in str(t.get('bizType', ''))
                or '权限' in str(t.get('title', '')))]
        token_used = plat_token
        if not cand:
            chk('收尾：定位到 fagai_liu 的请假权限申请任务', False,
                'fagai_admin 与平台 admin 待办均无匹配；全量待办=%s'
                % json.dumps(tasks_a + (tasks_p or []), ensure_ascii=False)[:400])
            return
    else:
        token_used = admin_token
    tid = cand[0].get('taskId')
    st, body = http_decide(tid, token_used, 'REJECT', 'e2e 复位')
    print('  · 收尾：驳回 HTTP %s：%s' % (st, json.dumps(body, ensure_ascii=False)[:200]))
    cat_r, _ = http_catalog(appl_token)
    lv_r = find_leave(cat_r)
    chk('收尾：驳回后 fagai_liu approval:leave.pending === false',
        lv_r is not None and lv_r.get('pending') is False, lv_r)
    chk('收尾：驳回后 fagai_liu approval:leave.held === false（驳回不误发权限）',
        lv_r is not None and lv_r.get('held') is False, lv_r)


def report():
    print('\n截图：%d 张 → %s/' % (len(shots), OUT))
    print('通过：%d / 失败：%d / 环境未就绪：%d' % (PASS_CNT, len(fails), len(envs)))
    for f in fails:
        print('  - FAIL ' + f)
    for e in envs:
        print('  - ENV  ' + e)
    if errors:
        real = [e for e in errors if e['src'] == 'pageerror' or 'Failed to load resource' not in e['text']]
        print('控制台事件 %d 条（真实异常 %d）：' % (len(errors), len(real)))
        for e in errors[:10]:
            print('  [%s] %s' % (e['src'], e['text'][:170]))
    return 1 if (fails or envs) else 0


async def main():
    os.makedirs(OUT, exist_ok=True)

    # 后端 / 静态服务存活探测
    try:
        requests.get(API_BASE + '/api/v1/auth/login', timeout=5)
    except Exception as e:
        env('前置未就绪：后端 :8080 不可达（%s）' % str(e)[:80])
        return report()
    try:
        requests.get(BASE, timeout=5)
    except Exception as e:
        env('前置未就绪：H5 :5181 不可达（%s）' % str(e)[:80])
        return report()

    appl_token, e0 = http_login(APPL_USER, APPL_PWD)
    if not appl_token:
        env('前置未就绪：fagai_liu 登录失败（%s）' % e0)
        return report()
    fail_token, e1 = http_login(FAIL_USER, FAIL_PWD)
    if not fail_token:
        env('前置未就绪：zhangsan 登录失败（%s）' % e1)
        return report()
    admin_token, e2 = http_login(ADMIN_USER, ADMIN_PWD)
    if not admin_token:
        env('前置未就绪：fagai_admin 登录失败（%s）' % e2)
        return report()
    plat_token, e3 = http_login(PLAT_USER, PLAT_PWD)
    if not plat_token:
        env('前置未就绪：admin 登录失败（%s）' % e3)
        return report()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)

        # ===== 阶段 A：fagai_liu 成功链路 =====
        ctx_a = await browser.new_context(viewport={'width': 390, 'height': 844},
                                          device_scale_factor=2, locale='zh-CN')
        await ctx_a.route('**/v1/org/permissions/apply', capture_apply)
        page = await ctx_a.new_page()
        page.on('response', lambda r: asyncio.ensure_future(on_response(r)))
        page.on('console', on_console)
        page.on('pageerror', on_pageerror)

        await login_ui(page, APPL_USER, APPL_PWD)
        chk('登录成功（%s，无权限分支 held=false）' % APPL_USER, True)
        if not await enter_oa(page):
            await browser.close()
            return report()
        applied = await run_success_path(page, appl_token, admin_token)
        await ctx_a.close()

        # ===== 阶段 B：zhangsan 失败口径 =====
        ctx_b = await browser.new_context(viewport={'width': 390, 'height': 844},
                                          device_scale_factor=2, locale='zh-CN')
        await ctx_b.route('**/v1/org/permissions/apply', capture_apply)
        page2 = await ctx_b.new_page()
        page2.on('response', lambda r: asyncio.ensure_future(on_response(r)))
        page2.on('console', on_console)
        page2.on('pageerror', on_pageerror)

        await login_ui(page2, FAIL_USER, FAIL_PWD)
        chk('登录成功（%s，tenant0 无机构 ⇒ apply 必被 FR-B2 拒）' % FAIL_USER, True)
        if await enter_oa(page2):
            await run_failure_path(page2, fail_token)
        await ctx_b.close()

        # ===== 收尾清理（fagai_admin 驳回；只要 fagai_liu 有在途 PENDING 就驳回，
        #   不论本次是「成功链路手动申请」还是「服务端自动申请」造成的残留）=====
        cat_final, _ = http_catalog(appl_token)
        lv_final = find_leave(cat_final)
        if lv_final and lv_final.get('pending') is True:
            print('  · 收尾：fagai_liu 有在途 PENDING（pendingOrderId=%s），fagai_admin 驳回复位…'
                  % lv_final.get('pendingOrderId'))
            do_cleanup(admin_token, plat_token, appl_token)
        else:
            print('  · 收尾：fagai_liu 无在途 PENDING，无需驳回。')

        # ===== 7 环境终态：两者都回到 held=false & pending=false =====
        cat_appl, _ = http_catalog(appl_token)
        lv_appl = find_leave(cat_appl)
        cat_fail, _ = http_catalog(fail_token)
        lv_fail = find_leave(cat_fail)
        print('\n环境最终态（原始 JSON，证明零残留）：')
        print('  fagai_liu : ' + json.dumps(lv_appl, ensure_ascii=False))
        print('  zhangsan  : ' + json.dumps(lv_fail, ensure_ascii=False))
        if lv_appl is not None:
            chk('环境终态：fagai_liu approval:leave 无残留（pending=false 且 held=false）',
                lv_appl.get('pending') is False and lv_appl.get('held') is False, lv_appl)
        else:
            chk('环境终态：能读到 fagai_liu 的 approval:leave 项', False, 'catalog 无该项')
        if lv_fail is not None:
            chk('环境终态：zhangsan approval:leave 无残留（pending=false 且 held=false）',
                lv_fail.get('pending') is False and lv_fail.get('held') is False, lv_fail)
        else:
            chk('环境终态：能读到 zhangsan 的 approval:leave 项', False, 'catalog 无该项')

        # 控制台真实异常（忽略资源类 401/403 环境噪声）
        real_errs = [e for e in errors if e['src'] == 'pageerror' or 'Failed to load resource' not in e['text']]
        ambient = [e for e in errors if e['src'] != 'pageerror' and 'Failed to load resource' in e['text']]
        chk('控制台无 JS 异常 / 无未捕获错误（忽略资源类 401/403 环境噪声）', len(real_errs) == 0, real_errs[:5])
        if ambient:
            print('  · 环境噪声（资源 401/403，与权限卡逻辑无关）：%d 条，例如：' % len(ambient))
            for e in ambient[:3]:
                print('     %s @ %s' % (e['text'][:110], (e['url'] or '')[:70]))

        await browser.close()
    return report()


if __name__ == '__main__':
    try:
        rc = asyncio.run(main())
    except Exception as exc:
        chk('流程未跑完（异常中断）', False, '%s: %s' % (type(exc).__name__, str(exc)[:160]))
        try:
            dump_logs()
        except Exception:
            pass
        rc = 1
    sys.exit(rc or (1 if fails else 0))
