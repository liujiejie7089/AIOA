# -*- coding: utf-8 -*-
"""提交前汇总确认卡 + 规则命中选项回填 浏览器级哨兵（Playwright + file://，不需要后端）。

验证目标：docs/53 自查报告确认的两个真实缺陷的修复——
  A) 提交前必须有「请核对以下信息」汇总确认节点（两段式：提交→汇总→确认提交）；
  B) 后端规则命中（HTTP 200 + code 40090 + data.rule_violation）时，前端把选项渲染成
     可点选按钮，点选后把值写回对应控件并重跑校验+汇总。

全部断言回到事实源头（真实 DOM / 拦截到的真实请求体），且每一条都能因缺陷变红。

判据
  C1  静态：构建源 _backup_index_pre_oa.html 含 data-form-confirm / formSummaryHtml /
           rule_violation / 40090 / .lf-rule-opt。
  C2  点一次「提交」：出现 .lf-confirm 且未发出任何 submit 请求（count==0），
      行数 == fields 数，且某行的值等于填写值。
  C3  点「确认提交」：submit count == 1，请求体 data 与填写值逐键一致。
  C4  负向对照：点「返回修改」→ count 仍为 0、.lf-confirm 消失、控件仍可编辑。
  C5  规则分支：打桩返回 40090(带 options) → 出现 .lf-rule-opt 且文案「改为年假」；
      点它 → 第二次 submit 的 data.leave_type == 'annual'。
  C6  负向对照：同 C5 但 options:[] → 只出 message，.lf-rule-opt 数量 == 0。

跑法（用 WorkBuddy 托管的 python，playwright 装在该环境）：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_verify_form_confirm.py

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
# C2~C4：普通表单（不触发规则），含 文本/数字/select/boolean 四种，用来验证两段式与值回显
FORM_A = {
    "form_code": "demo_a", "title": "测试表单", "submit_label": "提交",
    "fields": [
        {"name": "name", "label": "姓名", "type": "text", "required": True},
        {"name": "days", "label": "天数", "type": "number", "required": True},
        {"name": "leaveType", "label": "类型", "type": "select", "required": True,
         "options": [{"value": "sick", "label": "病假"}, {"value": "annual", "label": "年假"}]},
        {"name": "agree", "label": "同意条款", "type": "boolean", "required": True},
    ],
}

# C5/C6：请假表单，leave_type 默认 sick，规则命中后提供「改为年假」选项
FORM_B = {
    "form_code": "leave_request", "title": "请假申请", "submit_label": "提交",
    "fields": [
        {"name": "leave_type", "label": "请假类型", "type": "select", "required": True,
         "options": [{"value": "sick", "label": "病假"}, {"value": "annual", "label": "年假"}],
         "default": "sick"},
        {"name": "reason", "label": "事由", "type": "text"},
    ],
}

RULE_WITH_OPTS = {
    "code": 40090, "message": "病假需上传诊断证明",
    "data": {"rule_violation": {
        "rule_id": "r1", "field": "leave_type", "target_field": "leave_type",
        "message": "病假需上传诊断证明",
        "options": [{"value": "annual", "label": "改为年假"}]}}}
RULE_NO_OPTS = {
    "code": 40090, "message": "病假需上传诊断证明",
    "data": {"rule_violation": {
        "rule_id": "r1", "field": "leave_type", "target_field": "leave_type",
        "message": "病假需上传诊断证明", "options": []}}}
SUCCESS = {"code": 0, "data": {"submissionId": 1, "status": "已提交", "resume": False}}


# --------------------------------------------------------------------------- 主流程
async def main():
    if not os.path.exists(INDEX):
        print('[FAIL] 找不到构建产物：%s' % INDEX)
        return 1

    # 路由状态：response_body 可在两次点击之间热切换；bodies 记录每次真实请求体
    state = {'count': 0, 'bodies': [], 'response_body': json.dumps(SUCCESS)}

    async def submit_route(route, request):
        # 放行 CORS 预检（file:// 跨域到 sentinel.local 会触发 OPTIONS 预检）
        if request.method == 'OPTIONS':
            await route.fulfill(status=204, headers={
                'access-control-allow-origin': '*',
                'access-control-allow-methods': 'POST, OPTIONS',
                'access-control-allow-headers': 'content-type, authorization',
            })
            return
        state['count'] += 1
        try:
            state['bodies'].append(json.loads(request.post_data or '{}'))
        except Exception:
            state['bodies'].append(None)
        await route.fulfill(status=200, headers={
            'content-type': 'application/json',
            'access-control-allow-origin': '*',
        }, body=state['response_body'])

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

        # 把 API.base 指到可路由的绝对地址，避免 file:// 同源限制（与 _check_form_renderer 同套路）
        await page.evaluate("() => { API.base = 'https://sentinel.local'; }")
        await page.route('**/v1/forms/**/submit', submit_route)

        # 挂载一张表单卡（不 await 其 Promise，它只在提交/取消时 resolve，否则会挂起 evaluate）
        async def mount_form(host_id, payload):
            await page.evaluate("""(args) => {
              const host = document.createElement('div');
              host.id = args.hostId;
              document.body.appendChild(host);
              try { mountFormCard(host, args.payload, {standalone:true}); } catch(e){ window.__mountErr = String(e); }
              return true;
            }""", {'hostId': host_id, 'payload': payload})
            await page.wait_for_selector('#%s .leave-form' % host_id, timeout=4000)

        # 读汇总面板里某 label 对应行的 <b> 文案（label 为字段 label）
        async def summary_value(host_id, label):
            return await page.eval_on_selector_all(
                '#%s .lf-confirm-row' % host_id,
                '(els, label) => { for (const r of els) {'
                ' if (r.querySelector("span") && r.querySelector("span").textContent === label)'
                ' return r.querySelector("b").textContent; } return null; }',
                label)

        # ===================== C1：构建源静态一致性 =====================
        print('\n=== C1：构建源静态一致性 ===')
        if os.path.exists(BACKUP):
            src = open(BACKUP, 'r', encoding='utf-8').read()
            chk('C1 源含 data-form-confirm（汇总确认按钮）', 'data-form-confirm' in src)
            chk('C1 源含 formSummaryHtml（汇总纯函数）', 'function formSummaryHtml' in src)
            chk('C1 源含 rule_violation（规则命中字段）', 'rule_violation' in src)
            chk('C1 源含 40090（规则命中码）', '40090' in src)
            chk('C1 源含 .lf-rule-opt（规则选项按钮样式/类）', '.lf-rule-opt' in src)
        else:
            chk('C1 构建源存在', False, BACKUP)

        # ===================== C2 / C4 / C3：两段式提交（FORM_A）=====================
        print('\n=== C2/C4/C3：两段式提交（FORM_A）===')
        state['count'] = 0
        state['bodies'] = []
        state['response_body'] = json.dumps(SUCCESS)
        await mount_form('hostA', FORM_A)

        # 填写控件（用真实交互，覆盖 text/number/select/boolean）
        await page.fill('#hostA [data-field="name"]', '张三')
        await page.fill('#hostA [data-field="days"]', '3')
        await page.select_option('#hostA [data-field="leaveType"]', 'annual')
        # boolean 控件被 .lf-slider 视觉化、原生 input 不可见：直接置 checked（应用只在提交时读 c.checked）
        await page.eval_on_selector('#hostA [data-field="agree"]', 'el => { el.checked = true; }')

        # C2：点一次「提交」→ 应只出现汇总面板，绝不发请求
        await page.click('#hostA [data-form-submit]')
        await page.wait_for_selector('#hostA .lf-confirm', timeout=4000)
        chk('C2 点提交后出现 .lf-confirm 汇总面板', True)
        # 什么改动会让它红：若 submit 直接发请求（漏掉两段式），count 会 >0
        chk('C2 点一次提交未发出任何 submit 请求（count==0）',
            state['count'] == 0, 'count=%s' % state['count'])
        row_cnt = await page.eval_on_selector_all('#hostA .lf-confirm-row', 'els => els.length')
        chk('C2 汇总行数 == fields 数(4)', row_cnt == 4, 'rows=%s' % row_cnt)
        # 某行值 == 填写值（name=张三）
        summary_text = await page.eval_on_selector('#hostA .lf-confirm', 'el => el.textContent')
        chk('C2 汇总含填写值「张三」', '张三' in summary_text, 'summary=%r' % summary_text[:60])

        # C2b：单选 select 应回显选项名（label）而非裸 value
        # 什么改动会让它红：若删掉 formSummaryHtml 的 select 分支、或把命中不到也回落成裸值/「—」，
        #   这里必红（会显示 annual 而非「年假」）。
        lt_b = await summary_value('hostA', '类型')
        chk('C2b 单选 select 回显 label「年假」', lt_b is not None and '年假' in lt_b, 'val=%r' % lt_b)
        chk('C2b 单选 select 不显示裸 value「annual」', 'annual' not in (lt_b or ''), 'val=%r' % lt_b)

        # C4：负向对照 — 点「返回修改」→ count 仍为 0、.lf-confirm 消失、控件可编辑
        await page.click('#hostA [data-form-back]')
        await page.wait_for_timeout(150)
        gone = await page.eval_on_selector('#hostA .leave-form',
                                           'el => !el.querySelector(".lf-confirm")')
        chk('C4 返回修改后 .lf-confirm 消失', gone is True)
        chk('C4 返回修改后仍未发请求（count==0）', state['count'] == 0, 'count=%s' % state['count'])
        # 控件可编辑：提交按钮恢复可用，且 name 输入框可再次写入
        submit_disabled = await page.eval_on_selector('#hostA [data-form-submit]', 'el => el.disabled')
        chk('C4 提交按钮恢复可用', submit_disabled is False)
        await page.fill('#hostA [data-field="name"]', '李四')
        name_now = await page.eval_on_selector('#hostA [data-field="name"]', 'el => el.value')
        chk('C4 控件仍可编辑（name 改回「李四」）', name_now == '李四', 'name=%r' % name_now)

        # C2c（负向对照）：select 值不在 options 内 → 原样显示，绝不显示「—」。
        # 原生 <select> 无法持有 options 外的值（会回落成空 → 触发必填校验），故直接驱动纯函数
        # formSummaryHtml（与 _check_form_renderer 调 renderFormHtml 同套路），传入 options 外值
        # nonexistent，验证 select 分支「命中不到就原样显示」的回落。
        # 什么改动会让它红：若 select 分支把「命中不到」也回落成「—」（与空值混淆），这里必红
        #   （会显示「—」而非 nonexistent）。
        html_c2c = await page.evaluate(
            "(p) => formSummaryHtml(p, {name:'张三', days:3, leaveType:'nonexistent', agree:true})", FORM_A)
        chk('C2c 非 options 值原样显示「nonexistent」', 'nonexistent' in html_c2c, 'html=%r' % html_c2c[:140])
        chk('C2c 非 options 值不显示「—」', '—' not in html_c2c, 'html=%r' % html_c2c[:140])

        # C3：再点「提交」→ 汇总 → 点「确认提交」→ 真正发请求，且 data 与填写值一致
        await page.click('#hostA [data-form-submit]')
        await page.wait_for_selector('#hostA .lf-confirm', timeout=4000)
        await page.click('#hostA [data-form-confirm]')
        await page.wait_for_timeout(600)
        chk('C3 确认提交后 submit count==1', state['count'] == 1, 'count=%s' % state['count'])
        body = state['bodies'][-1] if state['bodies'] else None
        data = (body or {}).get('data', {})
        # 什么改动会让它红：若确认提交重读了 DOM 之外的旧值 / 漏字段，这里会不一致
        chk('C3 请求体 data.name==李四', data.get('name') == '李四', 'name=%r' % data.get('name'))
        chk('C3 请求体 data.days==3（数字）', data.get('days') == 3, 'days=%r' % data.get('days'))
        chk('C3 请求体 data.leaveType==annual', data.get('leaveType') == 'annual', 'lt=%r' % data.get('leaveType'))
        chk('C3 请求体 data.agree==True', data.get('agree') is True, 'agree=%r' % data.get('agree'))

        # ===================== C5：规则分支（FORM_B，带 options）=====================
        print('\n=== C5：规则命中 → 选项回填（FORM_B）===')
        state['count'] = 0
        state['bodies'] = []
        # 第一次提交返回 40090（带选项）
        state['response_body'] = json.dumps(RULE_WITH_OPTS)
        await mount_form('hostB', FORM_B)
        # leave_type 默认 sick（确诊会触发规则）

        await page.click('#hostB [data-form-submit]')
        await page.wait_for_selector('#hostB .lf-confirm', timeout=4000)
        await page.click('#hostB [data-form-confirm]')
        # 规则面板应出现
        await page.wait_for_selector('#hostB .lf-rule', timeout=4000)
        opt_cnt = await page.eval_on_selector_all('#hostB .lf-rule-opt', 'els => els.length')
        chk('C5 规则面板出现 .lf-rule-opt（数量=1）', opt_cnt == 1, 'opt_cnt=%s' % opt_cnt)
        opt_text = await page.eval_on_selector('#hostB .lf-rule-opt', 'el => el.textContent')
        chk('C5 选项文案为「改为年假」', opt_text == '改为年假', 'text=%r' % opt_text)
        # 什么改动会让它红：若后端 40090 未渲染选项 / 写回逻辑缺失，这里 opt_cnt==0 或文案不对

        # 点选项 → 写回 leave_type=annual → 重跑校验+汇总 → 再确认提交（第二次 submit）
        state['response_body'] = json.dumps(SUCCESS)  # 第二次提交返回成功
        await page.click('#hostB .lf-rule-opt')
        await page.wait_for_selector('#hostB .lf-confirm', timeout=4000)
        await page.click('#hostB [data-form-confirm]')
        await page.wait_for_timeout(600)
        chk('C5 共发出 2 次 submit（规则+重试）', state['count'] == 2, 'count=%s' % state['count'])
        second = state['bodies'][1] if len(state['bodies']) > 1 else None
        second_data = (second or {}).get('data', {})
        # 什么改动会让它红：若写回未生效 / 重跑时仍读旧 DOM，第二次 data.leave_type 会是 sick
        chk('C5 第二次 submit 的 data.leave_type==annual',
            second_data.get('leave_type') == 'annual', 'lt=%r' % second_data.get('leave_type'))

        # ===================== C6：负向对照（FORM_B，options:[]）=====================
        print('\n=== C6：负向对照（规则命中但 options 为空）===')
        state['count'] = 0
        state['bodies'] = []
        state['response_body'] = json.dumps(RULE_NO_OPTS)
        await mount_form('hostC', FORM_B)
        await page.click('#hostC [data-form-submit]')
        await page.wait_for_selector('#hostC .lf-confirm', timeout=4000)
        await page.click('#hostC [data-form-confirm]')
        await page.wait_for_selector('#hostC .lf-rule', timeout=4000)
        opt_cnt_c = await page.eval_on_selector_all('#hostC .lf-rule-opt', 'els => els.length')
        chk('C6 options 为空时 .lf-rule-opt 数量==0', opt_cnt_c == 0, 'opt_cnt=%s' % opt_cnt_c)
        msg_text = await page.eval_on_selector('#hostC .lf-rule-msg', 'el => el.textContent')
        chk('C6 仍显示规则 message', '病假需上传诊断证明' in msg_text, 'msg=%r' % msg_text)

        await browser.close()

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
