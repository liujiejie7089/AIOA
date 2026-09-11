# -*- coding: utf-8 -*-
"""
管理端全模块巡检：逐个打开菜单，捕获控制台错误 / 失败请求 / 页面空白，并截图。

用法：C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe audit_admin_ui.py
"""
import os
import re
import time
import json

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5173'
USER, PWD = 'admin', 'Admin@123'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ux-review', 'admin-audit')
os.makedirs(OUT, exist_ok=True)

ROUTES = [
    ('home', '/home', '首页'),
    ('approvals', '/approvals', '审批中心'),
    ('kb', '/kb', '知识库'),
    ('kpi', '/kpi', '经营数据'),
    ('workers', '/workers', '数字员工'),
    ('biz-systems', '/biz-systems', '业务系统'),
    ('quotas', '/quotas', '配额管理'),
    ('audit', '/audit', '操作审计'),
    ('settings', '/settings', '系统参数'),
    ('results', '/results', '成果沉淀'),
    ('admin', '/admin', '系统管理'),
    ('profile', '/profile', '个人信息'),
]

rows = []


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={'width': 1600, 'height': 1000})
        pg = ctx.new_page()

        errors, failed = [], []
        pg.on('console', lambda m: errors.append('%s: %s' % (m.type, m.text))
              if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errors.append('pageerror: %s' % e))
        pg.on('requestfailed', lambda r: failed.append('%s %s' % (r.method, r.url)))
        pg.on('response', lambda r: failed.append('HTTP %s %s %s' % (r.status, r.method, r.url))
              if r.status >= 400 and '/api/' in r.url else None)

        # 登录
        pg.goto(BASE + '/login', wait_until='networkidle')
        pg.fill('input[type="text"], input[name="username"]', USER)
        pg.fill('input[type="password"]', PWD)
        pg.click('button[type="submit"], .el-button--primary')
        pg.wait_for_timeout(2500)
        print('after login url =', pg.url)
        pg.screenshot(path=os.path.join(OUT, '00-after-login.png'))

        for key, path, name in ROUTES:
            errs, fails = [], []
            n_err, n_fail = len(errors), len(failed)
            try:
                pg.goto(BASE + path, wait_until='domcontentloaded')
                pg.wait_for_timeout(2200)
                # 页面主体文本
                try:
                    body = pg.inner_text('.el-main') or pg.inner_text('body')
                except Exception:
                    body = ''
                body = re.sub(r'\s+', ' ', body).strip()
                shot = os.path.join(OUT, '%s.png' % key)
                pg.screenshot(path=shot, full_page=False)
                errs = errors[n_err:]
                fails = failed[n_fail:]
                status = 'OK'
                if errs:
                    status = 'CONSOLE_ERR'
                if any('HTTP 5' in f for f in fails):
                    status = 'API_5XX'
                elif fails and status == 'OK':
                    status = 'API_4XX'
                rows.append({
                    'key': key, 'name': name, 'path': path, 'status': status,
                    'len': len(body), 'errors': errs[:4], 'failed': fails[:6],
                    'head': body[:260],
                })
                print('%-14s %-6s len=%-5d %s' % (key, status, len(body), fails[:2]))
            except Exception as e:
                rows.append({'key': key, 'name': name, 'path': path, 'status': 'EXCEPTION',
                             'len': 0, 'errors': [str(e)[:300]], 'failed': [], 'head': ''})
                print('%-14s EXCEPTION %s' % (key, str(e)[:120]))

        b.close()

    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print('\nreport ->', os.path.join(OUT, 'report.json'))


if __name__ == '__main__':
    main()
