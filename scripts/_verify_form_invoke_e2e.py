# -*- coding: utf-8 -*-
"""_verify_form_invoke_e2e.py — docs/52 P2「对话内发起表单 → 填写 → 提交 → 续跑」端到端哨兵
================================================================================

链路分两半，各有各的哨兵，**本脚本负责 H5 那一半**（并且把提交打到**真实后端**）：

  Python/Java 那一半：agent `request_form` → `need_form` 帧 → Java 用表单库补全 fields
    ⇒ `agent/tests/test_aioa_ai_form_hitl.py` + `RunServiceFormFrameTest`（Java 单测，5 条）
  浏览器那一半（本脚本）：
    need_form 帧到达 → 渲染卡片（真实字段定义） → 用户填写 → **真提交** → 续跑请求对象化

判据（每条都能因缺陷变红）：
  I0  :5181 上的 H5 产物与服务端定义都可取（前置；否则后面全是空转）
  I1  need_form 帧到达后，气泡里出现 `.leave-form[data-code=leave_request]` 卡片
  I2  卡片行数 == 后端定义字段数（不是「渲染了一部分就算过」）
  I3  卡片标题 == 后端定义 name（标签取自库，不是帧里硬写的）
  I4  提交按钮文案是中文字面量（不是 LEDGER / APPROVAL+RESUME 这类内部枚举）
  I5  点提交 → **真实** POST /api/v1/forms/leave_request/submit 返回 200 且 resume=true
  I6  续跑请求真的发出，且 answer 是**对象**（form_code/submission_id/status/data/receipt 全在）
      —— 这是「resume 对象化」的判据：标量回填会在这里露馅
  I7  卡片进入已提交态（disabled + 「已提交，正在继续…」），不会重复提交
  N1  负向对照：帧里给一个不支持的字段类型，卡片刻意**不能**把它渲染成输入控件
      （证明 I2 的等值断言不是「任何字段都通过」）
  G   自清理：删掉本次真实提交产生的 form_submission / approval_order / approval_task

跑法（:5181 静态+反代、:8080 后端在线）：
    C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe \
        scripts/_verify_form_invoke_e2e.py

退出码 = 失败条数。**不 stub 提交端点**：只伪造 SSE 流（避免依赖真实 LLM 的随机性），
提交打到真后端，所以「表单校验 / 落库 / 分流 / 回执」都是真的。
"""
import asyncio
import json
import os
import sys

import pymysql
from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'
FORM = 'leave_request'
RUN_ID = 'e2e-form-run-1'
DB = dict(host='127.0.0.1', port=3306, user='root', password='', database='aioa')

fails, oks = [], []
state = {'frame': None, 'resume_body': None, 'submit_resp': None}


def chk(name, ok, detail=''):
    (oks if ok else fails).append(name)
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''), flush=True)
    return ok


async def main():
    if not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       'user-client', 'index.html')):
        print('[FAIL] 找不到 H5 产物 user-client/index.html')
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('pageerror', lambda e: print('  [pageerror] ' + str(e), flush=True))

        # ---- 只伪造 SSE 流与「建 run」；提交 / 定义 / 登录全走真实后端 ----
        async def on_create_run(route, request):
            await route.fulfill(status=200, content_type='application/json',
                                body=json.dumps({'code': 0, 'message': 'ok', 'data': {'id': RUN_ID}}))

        async def on_events(route, request):
            frame = state['frame'] or {}
            sse = ('event: need_form\ndata: %s\n\n'
                   'event: run.completed\ndata: {"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n'
                   % json.dumps(frame, ensure_ascii=False))
            await route.fulfill(status=200, headers={'content-type': 'text/event-stream'},
                                body=sse)

        async def on_resume(route, request):
            state['resume_body'] = json.loads(request.post_data or '{}')
            sse = ('event: message.completed\ndata: {"content":"已收到你的表单，正在继续处理。"}\n\n'
                   'event: run.completed\ndata: {"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\n')
            await route.fulfill(status=200, headers={'content-type': 'text/event-stream'}, body=sse)

        await page.route('**/v1/conversations/*/runs', on_create_run)
        await page.route('**/v1/runs/%s/events' % RUN_ID, on_events)
        await page.route('**/v1/runs/%s/resume' % RUN_ID, on_resume)

        # ---------------- 登录 ----------------
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        try:
            await page.wait_for_selector('body.auth', timeout=20000)
        except Exception:
            chk('I0 登录成功', False, 'body.auth 未出现')
            await browser.close()
            return 1

        # ---------------- I0 真实定义（不是硬编码字段） ----------------
        definition = await page.evaluate("""async () => {
            const saved = JSON.parse(localStorage.getItem('aioa_session') || 'null') || {};
            const tok = saved.token || '';
            const r = await fetch('/api/v1/forms/%s', {headers:{Authorization:'Bearer '+tok}});
            const j = await r.json();
            return j.data || null;
        }""" % FORM)
        if not chk('I0 后端能取到表单定义（真源）',
                   bool(definition and definition.get('fields')),
                   'fields=%s' % (len(definition.get('fields') or []) if definition else None)):
            await browser.close()
            return 1
        fields = definition['fields']
        # 构造 need_form 帧：字段**来自真实定义**，submit_label 用 Java 会产出的中文文案
        state['frame'] = {
            'form_code': FORM, 'version': definition.get('version'),
            'title': definition.get('name'), 'submit_label': '提交审批',
            'reason': '提交后送部门负责人审批', 'fields': fields,
            'origin': {'kind': 'worker', 'worker_id': 1, 'worker_name': '请假助手'},
        }

        async def send(text):
            await page.fill('#oaInput', text)
            await page.wait_for_timeout(150)
            await page.click('#oaSendBtn', force=True)

        # ---------------- I1..I4 渲染 ----------------
        await send('我要请假')
        card_sel = '.leave-form[data-code="%s"]' % FORM
        try:
            await page.wait_for_selector(card_sel, timeout=15000)
        except Exception:
            chk('I1 need_form 帧后出现表单卡片', False, '未找到 %s' % card_sel)
            await browser.close()
            return 1
        chk('I1 need_form 帧后出现表单卡片', True, card_sel)

        rows = await page.eval_on_selector_all(card_sel + ' .lf-row', 'els => els.length')
        chk('I2 卡片行数 == 定义字段数', rows == len(fields), 'rows=%s fields=%s' % (rows, len(fields)))

        title = await page.eval_on_selector(card_sel + ' .lf-title', 'el => el.textContent.trim()')
        chk('I3 标题取自表单库', title == definition.get('name'), 'title=%s name=%s' % (title, definition.get('name')))

        btn_text = await page.eval_on_selector(card_sel + ' [data-form-submit]', 'el => el.textContent.trim()')
        chk('I4 提交按钮是中文文案（不是内部策略串）',
            btn_text not in ('LEDGER', 'APPROVAL+RESUME', '') and any('\u4e00' <= c <= '\u9fff' for c in btn_text),
            'btn=%s' % btn_text)

        # ---------------- N1 负向对照：不支持的字段类型不得渲染成控件 ----------------
        # 用同一张卡片之外的独立渲染验证（避免污染主流程）：直接调 renderFormHtml
        neg = await page.evaluate("""() => {
            const html = renderFormHtml({form_code:'neg', title:'负向', fields:[
                {name:'evil', label:'坏字段', type:'evil_type'} ]});
            const d = document.createElement('div'); d.innerHTML = html;
            return {inputs: d.querySelectorAll('input,select,textarea').length,
                    unknown: d.querySelectorAll('.lf-unknown').length};
        }""")
        chk('N1 不支持的类型不渲染控件、只给提示',
            neg['inputs'] == 0 and neg['unknown'] == 1, neg)

        # ---------------- I5 真提交 ----------------
        # 按定义填写（日期给合法值，select 选第一个枚举）
        for f in fields:
            name, t = f['name'], f.get('type')
            sel = '%s [data-field="%s"]' % (card_sel, name)
            if t in ('select',):
                opts = await page.eval_on_selector_all(sel + ' option',
                                                       'els => els.map(e => e.value).filter(v => v)')
                if opts:
                    await page.select_option(sel, opts[0])
            elif t == 'multiselect':
                opts = await page.eval_on_selector_all(sel + ' option',
                                                       'els => els.map(e => e.value).filter(v => v)')
                if opts:
                    await page.select_option(sel, [opts[0]])
            elif t == 'boolean':
                await page.check(sel)
            elif t == 'file':
                pass  # 选填文件跳过（必填文件场景由 _verify_form_flow.py 覆盖）
            elif t == 'date':
                await page.fill(sel, '2026-11-02')
            elif t == 'datetime':
                await page.fill(sel, '2026-11-02T09:30')
            elif t in ('number', 'amount'):
                await page.fill(sel, '2' if t == 'number' else '128.5')
            else:
                await page.fill(sel, 'E2E-FORM-INVOKE 自动化填写')

        async with page.expect_response(lambda r: '/forms/%s/submit' % FORM in r.url, timeout=20000) as ri:
            await page.click(card_sel + ' [data-form-submit]')
        resp = await ri.value
        body = await resp.json()
        data = body.get('data') or {}
        state['submit_resp'] = data
        chk('I5 真提交返回 200 且 code=0',
            resp.status == 200 and body.get('code') == 0, 'http=%s body=%s' % (resp.status, json.dumps(body, ensure_ascii=False)[:200]))
        chk('I5b 后端判定需要续跑（resume=true，APPROVAL+RESUME 策略）',
            data.get('resume') is True and bool(data.get('submissionId')),
            'resume=%s submissionId=%s' % (data.get('resume'), data.get('submissionId')))

        # ---------------- I6 续跑对象化 ----------------
        try:
            await page.wait_for_function('() => true', timeout=100)
        except Exception:
            pass
        for _ in range(40):
            if state['resume_body']:
                break
            await page.wait_for_timeout(250)
        rb = state['resume_body'] or {}
        ans = rb.get('answer')
        chk('I6 续跑请求已发出（POST /runs/{id}/resume）', bool(rb), 'body=%s' % json.dumps(rb, ensure_ascii=False)[:160])
        chk('I6b answer 是对象而非标量（resume 对象化）', isinstance(ans, dict), 'type=%s' % type(ans).__name__)
        if isinstance(ans, dict):
            need = {'form_code', 'submission_id', 'status'}
            chk('I6c answer 含 form_code / submission_id / status',
                need.issubset(ans.keys()) and str(ans.get('submission_id')) == str(data.get('submissionId')),
                'keys=%s' % sorted(ans.keys()))
            chk('I6d answer 回带 receipt（后端渲染的声明式回执）',
                isinstance(ans.get('receipt'), dict) and bool((ans.get('receipt') or {}).get('lines')),
                'receipt=%s' % json.dumps(ans.get('receipt'), ensure_ascii=False)[:160])

        # ---------------- I7 已提交态 ----------------
        await page.wait_for_timeout(600)
        done = await page.evaluate("""(sel) => {
            const c = document.querySelector(sel);
            if(!c) return {found:false};
            const btn = c.querySelector('[data-form-submit]');
            return {found:true, done:c.classList.contains('done'),
                    disabled: !!(btn && btn.disabled),
                    note: (c.querySelector('.lf-submitted') || {}).textContent || ''};
        }""", card_sel)
        chk('I7 卡片进入已提交态（禁点 + 提示 + 不重复提交）',
            done.get('done') and done.get('disabled') and '已提交' in (done.get('note') or ''), done)

        await browser.close()

    # ---------------- G 自清理 ----------------
    sub_id = (state['submit_resp'] or {}).get('submissionId')
    order_id = (state['submit_resp'] or {}).get('approvalOrderId')
    if sub_id:
        c = pymysql.connect(charset='utf8mb4', autocommit=True, **DB)
        cur = c.cursor()
        cur.execute('DELETE FROM form_submission WHERE id=%s', (sub_id,))
        print('  [clean] form_submission -%d' % cur.rowcount)
        if order_id:
            cur.execute('DELETE FROM notification WHERE ref_id=%s', (order_id,))
            cur.execute('DELETE FROM approval_task WHERE order_id=%s', (order_id,))
            print('  [clean] approval_task -%d' % cur.rowcount)
            cur.execute('DELETE FROM approval_order WHERE id=%s', (order_id,))
            print('  [clean] approval_order -%d' % cur.rowcount)
        cur.execute('SELECT COUNT(*) FROM form_submission WHERE id=%s', (sub_id,))
        left = cur.fetchone()[0]
        chk('G1 本次提交已清理（可重复跑）', left == 0, 'left=%s' % left)
        c.close()

    print('\n[RESULT] 通过 %d / 失败 %d' % (len(oks), len(fails)))
    for f in fails:
        print('  - ' + f)
    return len(fails)


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
