# -*- coding: utf-8 -*-
"""按角色登录管理端，对比各自可见菜单，确认 V24 租户端/企业端能力是否有入口。"""
import os
import json
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5173'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ux-review', 'admin-audit')
os.makedirs(OUT, exist_ok=True)

USERS = [
    ('admin', 'Admin@123', '平台管理员 ROLE_ADMIN'),
    ('dsj_admin', 'User@123', '租户管理员 ROLE_TENANT_ADMIN(租户2)'),
    ('fagai_admin', 'User@123', '企业管理员 ROLE_ORG_ADMIN(发改局)'),
    ('fagai_chen', 'User@123', '机构成员 ROLE_MEMBER'),
]

result = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for u, pwd, label in USERS:
        ctx = b.new_context(viewport={'width': 1600, 'height': 1000})
        pg = ctx.new_page()
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
        try:
            pg.goto(BASE + '/login', wait_until='networkidle')
            pg.fill('input[type="text"], input[name="username"]', u)
            pg.fill('input[type="password"]', pwd)
            pg.click('button[type="submit"], .el-button--primary')
            pg.wait_for_timeout(2500)
            url = pg.url
            pg.goto(BASE + '/home', wait_until='domcontentloaded')
            pg.wait_for_timeout(1800)
            menus = pg.eval_on_selector_all(
                '.el-menu .el-menu-item', 'els => els.map(e => e.innerText.trim()).filter(Boolean)')
            subs = pg.eval_on_selector_all(
                '.el-menu .el-sub-menu__title', 'els => els.map(e => e.innerText.trim()).filter(Boolean)')
            result[u] = {'label': label, 'url': url, 'menus': menus, 'subs': subs, 'errors': errs[:3]}
            print('%-14s url=%-30s menus=%s' % (u, url.replace(BASE, ''), menus))
            pg.screenshot(path=os.path.join(OUT, 'menu-%s.png' % u))
        except Exception as e:
            result[u] = {'label': label, 'error': str(e)[:300]}
            print('%-14s EXCEPTION %s' % (u, str(e)[:150]))
        ctx.close()
    b.close()

with open(os.path.join(OUT, 'menu-by-role.json'), 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print('\n->', os.path.join(OUT, 'menu-by-role.json'))
