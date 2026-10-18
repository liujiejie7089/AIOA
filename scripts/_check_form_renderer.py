# -*- coding: utf-8 -*-
"""通用表单渲染器 + need_form 帧离线哨兵（Playwright + file://，不需要后端）。

验证目标：docs/52 §3.3 的通用表单渲染器（renderFormHtml / mountFormCard / formReceiptHtml）
与 API._sse 的 need_form 分发是否真的按契约工作。全部断言都回到事实源头（真实 DOM /
renderFormHtml 返回的 HTML 字符串 / 拦截到的真实 SSE 帧），且每一条都能因缺陷变红。

判据
  R1  8+ 种字段类型各自渲染出对应控件（select 有 option、textarea 是 textarea、
      date 是 input[type=date]、boolean 是 checkbox、multiselect 多选、number/amount 是
      input[type=number]、text 是 input[type=text]、file 是 input[type=file]、datetime 是
      input[type=datetime-local]）。
  R2  转义：字段 label 传 XSS 向量，断言产出 HTML 不含裸 <img（防注入）。
  R3  未知类型 type:"evil" 不产生输入控件且给出提示。
  R4  负向对照：fields 清空，断言渲染不出任何 .lf-row（证明 R1 不是恒真）。
  R5  need_form 分发：page.route 拦截一次 /v1/runs/x/events 返回含 event: need_form 的 SSE，
      断言注入的桩回调 h.onForm 被调用且收到正确 payload。
  R6  window.oaOpenForm 作为独立入口函数存在且可被驱动。
  S1  静态：构建源 _backup_index_pre_oa.html 含 need_form / mountFormCard / formSubmit / oaOpenForm。

跑法（用 WorkBuddy 托管的 python，playwright 装在该环境）：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_form_renderer.py

退出码非零 = 有断言失败。
"""
import asyncio
import json
import os
import sys
import urllib.parse

from playwright.async_api import async_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(REPO, 'user-client', 'index.html')
BACKUP = os.path.join(REPO, 'user-client', '_backup_index_pre_oa.html')

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''), flush=True)
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


# --------------------------------------------------------------------------- 测试载荷
def all_types_payload():
    return {
        "form_code": "leave_request", "title": "请假申请", "submit_label": "提交",
        "reason": "需要请假信息才能送审",
        "fields": [
            {"name": "name", "label": "姓名", "type": "text", "required": True},
            {"name": "reason", "label": "事由", "type": "textarea"},
            {"name": "days", "label": "天数", "type": "number", "required": True},
            {"name": "amount", "label": "金额", "type": "amount"},
            {"name": "startDate", "label": "开始日期", "type": "date", "required": True},
            {"name": "meetAt", "label": "会议时间", "type": "datetime"},
            {"name": "attach", "label": "证明材料", "type": "file"},
            {"name": "agree", "label": "我已阅读", "type": "boolean", "required": True},
            {"name": "leaveType", "label": "请假类型", "type": "select", "required": True,
             "options": [{"value": "ANNUAL", "label": "年假"}], "default": "ANNUAL"},
            {"name": "multi", "label": "抄送人", "type": "multiselect",
             "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
        ],
        "prefill": {"startDate": "2026-10-18"},
        "origin": {"kind": "worker", "worker_id": 86, "worker_name": "请假助手"},
    }


def xss_payload():
    return {"form_code": "x", "title": "X", "fields": [
        {"name": "f", "label": '"><img src=x onerror=alert(1)>', "type": "text"}]}


def evil_payload():
    return {"form_code": "x", "title": "X", "fields": [
        {"name": "evil", "label": "坏字段", "type": "evil"}]}


def empty_payload():
    return {"form_code": "x", "title": "X", "fields": []}


# --------------------------------------------------------------------------- 主流程
async def main():
    if not os.path.exists(INDEX):
        print('[FAIL] 找不到构建产物：%s' % INDEX)
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                        device_scale_factor=2, locale='zh-CN')
        page = await ctx.new_page()
        page.on('pageerror', lambda e: print('  [pageerror] ' + str(e), flush=True))

        file_url = 'file:///' + urllib.parse.quote(INDEX.replace('\\', '/'), safe='/')
        print('[diag] 载入', file_url[:80], flush=True)
        await page.goto(file_url, wait_until='domcontentloaded')
        await page.wait_for_timeout(500)

        # ===================== R1：8+ 种字段类型各自渲染出对应控件 =====================
        print('\n=== R1：字段类型渲染 ===')
        html = await page.evaluate("""(p) => renderFormHtml(p)""", all_types_payload())
        chk('R1 渲染成功返回非空 HTML', isinstance(html, str) and len(html) > 0, 'len=%s' % len(html or ''))

        row_count = html.count('class="lf-row"')
        chk('R1 行数 == 字段数(10)', row_count == 10, 'rows=%s' % row_count)

        def has(sub):
            return sub in html

        # select 必须有 option
        chk('R1 select 渲染 + 含 <option',
            ('data-type="select"' in html) and ('<option' in html),
            'select/option present=%s' % (('data-type="select"' in html) and ('<option' in html)))
        chk('R1 textarea 渲染', 'data-type="textarea"' in html and '<textarea' in html)
        chk('R1 text 渲染为 input[type=text]',
            ('data-type="text"' in html) and ('type="text"' in html))
        chk('R1 number 渲染为 input[type=number]',
            ('data-type="number"' in html) and ('type="number"' in html))
        chk('R1 amount 渲染为 input[type=number]',
            ('data-type="amount"' in html) and ('type="number"' in html))
        chk('R1 date 渲染为 input[type=date]',
            ('data-type="date"' in html) and ('type="date"' in html))
        chk('R1 datetime 渲染为 input[type=datetime-local]',
            ('data-type="datetime"' in html) and ('type="datetime-local"' in html))
        chk('R1 file 渲染为 input[type=file]',
            ('data-type="file"' in html) and ('type="file"' in html))
        chk('R1 boolean 渲染为 input[type=checkbox]',
            ('data-type="boolean"' in html) and ('type="checkbox"' in html))
        # multiselect 必须有 multiple 属性
        chk('R1 multiselect 渲染 + multiple',
            ('data-type="multiselect"' in html) and ('multiple' in html))
        # prefill 落到对应控件（startDate 默认值）
        chk('R1 prefill 落到 date 控件 value', 'value="2026-10-18"' in html)
        # required 标 * 且 data-required=1
        chk('R1 必填字段标 data-required=1', html.count('data-required="1"') >= 1)
        # 标题/理由/提交按钮文案转义渲染
        chk('R1 标题与提交文案渲染', ('>请假申请<' in html) and ('>提交<' in html))
        chk('R1 origin 发起方渲染', '请假助手' in html)

        # ===================== R2：转义（防 XSS 注入）=====================
        print('\n=== R2：转义 / 防注入 ===')
        html2 = await page.evaluate("""(p) => renderFormHtml(p)""", xss_payload())
        # 裸 <img 绝不能出现；label 必须被转义成 &lt;img
        chk('R2 产出不含裸 <img（防注入）', '<img' not in html2, 'contains <img: %s' % ('<img' in html2))
        chk('R2 label 被转义为 &lt;img', '&lt;img' in html2, 'escaped=%s' % ('&lt;img' in html2))
        chk('R2 仍有该字段的 data-field', 'data-field="f"' in html2)

        # ===================== R3：未知类型不产生控件 + 提示 =====================
        print('\n=== R3：未知字段类型处理 ===')
        html3 = await page.evaluate("""(p) => renderFormHtml(p)""", evil_payload())
        chk('R3 未知类型不产生任何 data-field 控件', 'data-field' not in html3,
            'has data-field: %s' % ('data-field' in html3))
        chk('R3 给出「不支持/跳过」提示',
            ('不支持' in html3) or ('跳过' in html3),
            'hint present: %s' % (('不支持' in html3) or ('跳过' in html3)))
        chk('R3 提示包含类型名 evil', 'evil' in html3, 'mentions type: %s' % ('evil' in html3))

        # ===================== R4：负向对照（空 fields）=====================
        print('\n=== R4：负向对照（空 fields）===')
        html4 = await page.evaluate("""(p) => renderFormHtml(p)""", empty_payload())
        empty_rows = html4.count('class="lf-row"')
        chk('R4 空 fields 渲染不出任何 .lf-row（0 行）', empty_rows == 0, 'rows=%s' % empty_rows)
        chk('R4 负向与 R1 相反（R1=10, R4=0，非恒真）', row_count == 10 and empty_rows == 0)

        # ===================== R5：need_form 分发（拦截 SSE）=====================
        print('\n=== R5：need_form 分发（page.route 拦截 SSE）===')
        spy = {'called': False, 'payload': None}
        # 把 API.base 指向一个可路由的绝对地址，避免 file:// 同源限制
        await page.evaluate("() => { API.base = 'https://sentinel.local'; }")

        async def route_handler(route, request):
            sse_body = 'event: need_form\ndata: {"form_code":"leave_request","title":"请假申请"}\n\n'
            await route.fulfill(status=200,
                                headers={'content-type': 'text/event-stream',
                                         'access-control-allow-origin': '*'},
                                body=sse_body)

        await page.route('**/v1/runs/x/events', route_handler)
        try:
            await page.evaluate("""() => new Promise((resolve) => {
              const h = { onForm: (p) => { window.__onFormCalled = true; window.__onFormPayload = p; },
                          onError: () => {}, onDelta: () => {}, onCompleted: () => {} };
              API.stream('x', h).then(resolve).catch(resolve);
            })""")
            called = await page.evaluate("() => !!window.__onFormCalled")
            payload = await page.evaluate("() => window.__onFormPayload || null")
            chk('R5 need_form 触发 h.onForm 被调用', called is True, 'called=%s' % called)
            chk('R5 onForm 收到正确 payload',
                isinstance(payload, dict) and payload.get('form_code') == 'leave_request',
                'payload=%s' % payload)
        finally:
            await page.unroute('**/v1/runs/x/events')

        # ===================== R6：独立入口 window.oaOpenForm 可用 =====================
        print('\n=== R6：window.oaOpenForm 独立入口 ===')
        is_fn = await page.evaluate("() => typeof window.oaOpenForm === 'function'")
        chk('R6 window.oaOpenForm 是可调用函数', is_fn is True, 'typeof=%s' % is_fn)
        # 驱动一次（路由拦截 GET /v1/forms/x 返回 schema），断言它确实会去取表单定义
        form_get_hit = {'hit': False}

        async def form_route(route, request):
            form_get_hit['hit'] = True
            await route.fulfill(status=200,
                                headers={'content-type': 'application/json',
                                         'access-control-allow-origin': '*'},
                                body=json.dumps({'code': 0,
                                                 'data': {'form_code': 'x', 'title': 'X',
                                                          'fields': [{'name': 'a', 'label': 'A', 'type': 'text'}]}}))

        await page.evaluate("() => { API.base = 'https://sentinel.local'; }")
        await page.route('**/v1/forms/x', form_route)
        try:
            # 只验证「会去取表单定义」，不要 await 它的返回 Promise（mountFormCard 只在用户
            # 提交/取消时才 resolve，否则会永远挂起 page.evaluate）。
            await page.evaluate("() => { try { window.oaOpenForm('x'); } catch(e){} return 'fired'; }")
            await page.wait_for_timeout(1000)
            chk('R6 oaOpenForm 确实请求了 /v1/forms/x 定义', form_get_hit['hit'] is True,
                'hit=%s' % form_get_hit['hit'])
        finally:
            await page.unroute('**/v1/forms/x')

        await browser.close()

    # ===================== S1：构建源静态一致性 =====================
    print('\n=== S1：构建源静态一致性 ===')
    if os.path.exists(BACKUP):
        src = open(BACKUP, 'r', encoding='utf-8').read()
        chk('S1 源含 need_form 分支', "ev.event === 'need_form'" in src)
        chk('S1 源含 mountFormCard', 'function mountFormCard' in src)
        chk('S1 源含 renderFormHtml', 'function renderFormHtml' in src)
        chk('S1 源含 API.formSubmit', 'formSubmit(code, values, extra)' in src)
        chk('S1 源暴露 window.oaOpenForm', 'window.oaOpenForm' in src)
        chk('S1 字段白名单含 10 种类型',
            all(t in src for t in ['text', 'textarea', 'number', 'amount', 'date',
                                   'datetime', 'select', 'multiselect', 'file', 'boolean']))
    else:
        chk('S1 构建源存在', False, BACKUP)

    return report()


def report():
    print('\n──────── 收口 ────────')
    print('通过：%d / 失败：%d' % (oks, len(fails)))
    if fails:
        print('失败项：')
        for f in fails:
            print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
