# -*- coding: utf-8 -*-
"""
组织与员工页无头渲染校验（回归「部门加载失败 / 员工加载失败 403」）。

对每个给定账号：注入会话 → 打开 /org-structure → 断言
  * 无 403 错误横幅
  * 部门树与员工名册有实际数据
  * 机构选择器与写入按钮按角色显隐正确

前置：管理端 shell 跑在 5173，后端跑在 8080（vite 已代理 /api）。

用法：
  python scripts/check_org_structure_render.py            # 默认账号集
  python scripts/check_org_structure_render.py jyj_admin  # 指定账号
"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8080'
SHELL = 'http://127.0.0.1:5173'

ACCOUNTS = [
    # (账号, 密码, 说明, 期望出现机构选择器, 期望出现写入按钮)
    ('jyj_admin', 'User@123', '纯租户管理员(tenant 4, 3 家机构)', True, True),
    ('jyfzyjy_admin', 'User@123', '机构管理员(inst 17, 单机构)', False, True),
    ('jybgs_m01', 'User@123', '普通成员(只读)', False, False),
    ('admin', 'Admin@123', '平台管理员(跨租户只读)', True, False),
]


def login(u, p):
    req = urllib.request.Request(BASE + '/api/v1/auth/login',
                                 data=json.dumps({'username': u, 'password': p}).encode(),
                                 method='POST')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())['data']


def session_js(d):
    u = d['user']
    user = {'id': u['id'], 'username': u['username'], 'displayName': u.get('nickname') or u['username'],
            'roles': u.get('roles') or [], 'tenantId': u.get('tenantId')}
    return ('localStorage.setItem("aioa.token", %s);'
            'localStorage.setItem("aioa.refreshToken", %s);'
            'localStorage.setItem("aioa.user", %s);'
            % (json.dumps(d['accessToken']), json.dumps(d.get('refreshToken') or ''),
               json.dumps(json.dumps(user))))


def main():
    users = sys.argv[1:] or None
    cases = [c for c in ACCOUNTS if not users or c[0] in users]
    fails = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        for acct, pwd, desc, expect_selector, expect_write in cases:
            d = login(acct, pwd)
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            ctx.add_init_script(session_js(d))
            page = ctx.new_page()
            errors = []
            bad = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('response', lambda r: bad.append('%s %s' % (r.status, r.url))
                    if r.status >= 400 else None)
            page.goto(SHELL + '/org-structure', wait_until='networkidle')
            page.wait_for_timeout(2500)

            body = page.inner_text('body')
            has403 = '403' in body
            dept_nodes = page.locator('.tree-node').count()
            rows = page.locator('.el-table__body tbody tr').count()
            selectors = page.locator('.scope-bar .el-select').count()
            add_btns = page.get_by_role('button', name='新增部门').count()
            scope_tags = page.locator('.scope-bar .el-tag').all_inner_texts()

            # 只把「业务接口」的 4xx 视为失败；favicon 等静态资源缺失不算
            api_bad = [b for b in bad if '/api/' in b]

            ok = (not has403) and dept_nodes > 0 and rows > 0 and not api_bad
            if expect_write is not None:
                ok = ok and (add_btns > 0) == expect_write
            if expect_selector is not None:
                ok = ok and (selectors > 0) == expect_selector

            print('%s %-16s %s' % ('PASS' if ok else 'FAIL', acct, desc))
            print('     deptNodes=%d memberRows=%d instSelectors=%d addDeptBtn=%d has403=%s'
                  % (dept_nodes, rows, selectors, add_btns, has403))
            print('     scopeTags=%s' % (scope_tags,))
            if api_bad:
                print('     apiFailures=%s' % api_bad[:5])
            elif bad:
                print('     非接口失败（忽略）=%s' % bad[:3])
            if errors:
                print('     consoleErrors=%s' % errors[:3])
            if not ok:
                fails.append(acct)
            ctx.close()
        browser.close()

    print('\n%s' % ('ALL PASS' if not fails else 'FAIL: ' + ', '.join(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
