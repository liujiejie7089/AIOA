# -*- coding: utf-8 -*-
"""
为所有「还没有数字员工」的租户，从平台全局模板预置一套初始数字员工。

解决：租户开通后数字员工列表为空、页面白板、用户无从下手。
幂等：已有数字员工的租户自动跳过，重复执行不会产生重复数据。

用法：
  python scripts/seed_worker_templates.py --dry-run
  python scripts/seed_worker_templates.py
"""
import argparse
import sys

import httpx

BASE = 'http://127.0.0.1:8080'
PLATFORM = ('admin', 'Admin@123')
PWD = 'User@123'

# 租户管理员账号（与 docs/14-入驻租户账号清单.md 一致）
TENANT_ADMINS = [
    'jyj_admin',    # 教育局
    'gaj_admin',    # 公安分局
    'ctjt_admin',   # 城投集团
    'rmyy_admin',   # 人民医院
    'kfgq_admin',   # 高新区管委会
    'znkj_admin',   # 智能科技
    'wjj_admin',    # 卫健局
    'dsj_admin',    # 大数据管理局
]


def login(c, u, p):
    r = c.post('/api/v1/auth/login', json={'username': u, 'password': p})
    if r.status_code != 200 or r.json().get('code') != 0:
        return None
    return {'Authorization': 'Bearer ' + r.json()['data']['accessToken']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    c = httpx.Client(base_url=BASE, trust_env=False, timeout=30)
    H = login(c, *PLATFORM)
    if not H:
        raise SystemExit('平台管理员登录失败')

    # 平台模板
    r = c.get('/api/v1/workers/templates', headers=login(c, 'jyj_admin', PWD))
    templates = (r.json().get('data') or []) if r.status_code == 200 else []
    if not templates:
        raise SystemExit('没有可用的平台模板')
    print('平台模板 %d 个：%s' % (len(templates), '、'.join(t['name'] for t in templates)))

    total = 0
    for admin in TENANT_ADMINS:
        HT = login(c, admin, PWD)
        if not HT:
            print('  [skip] %-14s 登录失败' % admin)
            continue
        existing = c.get('/api/v1/workers', headers=HT).json().get('data') or []
        if existing:
            print('  [skip] %-14s 已有 %d 个数字员工' % (admin, len(existing)))
            continue
        if args.dry_run:
            print('  [dry ] %-14s 将预置 %d 个数字员工' % (admin, len(templates)))
            total += len(templates)
            continue

        ok = 0
        for t in templates:
            rr = c.post('/api/v1/workers/from-template/%s' % t['id'], headers=HT, json={})
            if rr.status_code == 200 and rr.json().get('code') == 0:
                ok += 1
            else:
                print('      !! 模板 %s 复制失败：%s' % (t['name'], rr.text[:100]))
        print('  [ ok ] %-14s 预置 %d 个数字员工' % (admin, ok))
        total += ok

    print('\n合计预置 %d 个数字员工' % total)


if __name__ == '__main__':
    main()
