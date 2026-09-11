# -*- coding: utf-8 -*-
"""
全模块巡检（第二轮）：按角色登录，逐个打开菜单，捕获控制台错误 / 失败请求 / 空白页，并截图。

覆盖 V24 新增页面（机构管理 / 入驻进度 / 组织与员工 / 资源授权 / 费用分摊）+ 租户管理。
"""
import os
import re
import json

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5173'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ux-review', 'full-audit')
os.makedirs(OUT, exist_ok=True)

# 角色 -> 期望可访问的路由
ROLES = [
    ('admin', 'Admin@123', '平台管理员', ['home', 'institutions', 'onboarding', 'org-structure',
                                      'resource-grants', 'cost-alloc', 'tenants', 'admin',
                                      'approvals', 'kb', 'kpi', 'workers', 'quotas', 'audit',
                                      'settings', 'results', 'profile']),
    ('dsj_admin', 'User@123', '租户管理员', ['home', 'institutions', 'onboarding', 'resource-grants',
                                         'cost-alloc', 'approvals', 'kb', 'kpi', 'workers',
                                         'quotas', 'audit', 'results', 'profile']),
    ('jyj_admin', 'User@123', '新租户管理员(教育局)', ['home', 'institutions', 'onboarding',
                                                'resource-grants', 'cost-alloc', 'approvals',
                                                'kb', 'kpi', 'workers', 'quotas', 'audit',
                                                'results', 'profile']),
    ('fagai_admin', 'User@123', '企业管理员(发改局)', ['home', 'org-structure', 'approvals', 'kb',
                                                 'kpi', 'workers', 'quotas', 'audit', 'results',
                                                 'profile']),
]

rows = []


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        for user, pwd, label, routes in ROLES:
            ctx = b.new_context(viewport={'width': 1600, 'height': 1000})
            pg = ctx.new_page()
            errs_all, fails_all = [], []
            pg.on('console', lambda m, e=errs_all: e.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
            pg.on('pageerror', lambda ex, e=errs_all: e.append('pageerror: %s' % ex))
            pg.on('response', lambda r, f=fails_all: f.append('HTTP %s %s %s' % (r.status, r.method, r.url))
                  if r.status >= 400 and '/api/' in r.url else None)

            pg.goto(BASE + '/login', wait_until='networkidle')
            pg.fill('input[type="text"], input[name="username"]', user)
            pg.fill('input[type="password"]', pwd)
            pg.click('button[type="submit"], .el-button--primary')
            pg.wait_for_timeout(2500)

            menus = pg.eval_on_selector_all(
                '.el-menu .el-menu-item', 'els => els.map(e => e.innerText.trim()).filter(Boolean)')
            print('\n######## %s（%s）菜单：%s' % (user, label, menus))

            for path in routes:
                n_err, n_fail = len(errs_all), len(fails_all)
                try:
                    pg.goto(BASE + '/' + path, wait_until='domcontentloaded')
                    pg.wait_for_timeout(2000)
                    try:
                        body = pg.inner_text('.el-main') or pg.inner_text('body')
                    except Exception:
                        body = ''
                    body = re.sub(r'\s+', ' ', body).strip()
                    errs = errs_all[n_err:]
                    fails = fails_all[n_fail:]
                    status = 'OK'
                    if any('HTTP 5' in f for f in fails):
                        status = 'API_5XX'
                    elif errs:
                        status = 'CONSOLE_ERR'
                    elif len(body) < 120:
                        status = 'NEARLY_EMPTY'
                    pg.screenshot(path=os.path.join(OUT, '%s-%s.png' % (user, path)))
                    rows.append({'user': user, 'role': label, 'path': path, 'status': status,
                                 'len': len(body), 'errors': errs[:3], 'failed': fails[:4],
                                 'head': body[:200]})
                    print('  %-18s %-13s len=%-6d %s' % (path, status, len(body), fails[:1]))
                except Exception as ex:
                    rows.append({'user': user, 'role': label, 'path': path, 'status': 'EXCEPTION',
                                 'len': 0, 'errors': [str(ex)[:250]], 'failed': [], 'head': ''})
                    print('  %-18s EXCEPTION %s' % (path, str(ex)[:110]))
            ctx.close()
        b.close()

    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    bad = [r for r in rows if r['status'] != 'OK']
    print('\n================ 汇总 ================')
    print('总页面 %d，异常 %d' % (len(rows), len(bad)))
    for r in bad:
        print('  %(user)-12s %(path)-18s %(status)-13s %(errors)s %(failed)s' % r)
    print('\n->', os.path.join(OUT, 'report.json'))


if __name__ == '__main__':
    main()
