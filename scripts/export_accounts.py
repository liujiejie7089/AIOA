# -*- coding: utf-8 -*-
"""导出入驻租户账号清单（负责人 + 全部普通成员）为 Markdown 文件。"""
import pymysql

conn = pymysql.connect(host='127.0.0.1', port=3306, user='root', password='',
                       database='aioa', charset='utf8mb4')
cur = conn.cursor(pymysql.cursors.DictCursor)

CODES = ('JYJ-DEMO', 'GAJ-DEMO', 'CTJT-DEMO', 'RMYY-DEMO', 'KFGQ-DEMO', 'MYQY-DEMO', 'WJJ-DEMO')

# 租户信息 + 租户管理员
cur.execute(
    'SELECT t.id AS tid, t.code, t.name, '
    '(SELECT u.username FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id '
    '  JOIN sys_role r ON r.id=ur.role_id WHERE u.tenant_id=t.id AND r.role_code=%s '
    '  AND u.deleted_at IS NULL LIMIT 1) AS tenant_admin, '
    '(SELECT u.nickname FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id '
    '  JOIN sys_role r ON r.id=ur.role_id WHERE u.tenant_id=t.id AND r.role_code=%s '
    '  AND u.deleted_at IS NULL LIMIT 1) AS tenant_admin_name '
    'FROM sys_tenant t WHERE t.code IN (%s) ORDER BY t.id'
    % ('%s', '%s', ','.join(['%s'] * len(CODES))),
    ('ROLE_TENANT_ADMIN', 'ROLE_TENANT_ADMIN') + CODES)
tenants = cur.fetchall()

L = []
L.append('# AIOA 入驻租户账号清单（负责人 + 全部普通成员）')
L.append('')
L.append('> 统一密码：**User@123**（平台管理员 `admin / Admin@123`）')
L.append('> 生成时间：2026-09-12 · 数据来源：数据库实际落库账号')
L.append('')

for t in tenants:
    tid = t['tid']
    L.append('## %s（%s）' % (t['name'], t['code']))
    L.append('')
    L.append('| 角色 | 账号 | 姓名 | 密码 |')
    L.append('|---|---|---|---|')
    L.append('| 租户管理员 | `%s` | %s | User@123 |' % (t['tenant_admin'], t['tenant_admin_name'] or ''))
    L.append('')

    cur.execute('SELECT id, name, code, admin_user_id FROM org_institution '
                'WHERE tenant_id=%s AND deleted_at IS NULL ORDER BY id', (tid,))
    insts = cur.fetchall()
    for ins in insts:
        iid = ins['id']
        adm_username = None
        adm_name = None
        if ins['admin_user_id']:
            cur.execute('SELECT username, nickname FROM sys_user WHERE id=%s', (ins['admin_user_id'],))
            r = cur.fetchone()
            if r:
                adm_username = r['username']
                adm_name = r['nickname']
        L.append('### 机构：%s（%s）' % (ins['name'], ins['code']))
        L.append('')
        L.append('| 角色 | 账号 | 姓名 | 密码 |')
        L.append('|---|---|---|---|')
        if adm_username:
            L.append('| 机构管理员 | `%s` | %s | User@123 |' % (adm_username, adm_name or ''))
        L.append('')

        cur.execute('SELECT id, name, code FROM org_department '
                    'WHERE institution_id=%s AND deleted_at IS NULL ORDER BY id', (iid,))
        depts = cur.fetchall()
        for d in depts:
            did = d['id']
            cur.execute('SELECT m.name, m.job_title, u.username FROM org_member m '
                        'LEFT JOIN sys_user u ON u.id=m.user_id '
                        'WHERE m.department_id=%s AND m.deleted_at IS NULL ORDER BY m.id', (did,))
            members = cur.fetchall()
            L.append('**部门：%s（%s）**' % (d['name'], d['code']))
            L.append('')
            L.append('| 角色 | 账号 | 姓名 | 职务 | 密码 |')
            L.append('|---|---|---|---|---|')
            for m in members:
                uname = m['username'] or '（无账号）'
                L.append('| 成员 | `%s` | %s | %s | User@123 |' % (uname, m['name'] or '', m['job_title'] or ''))
            L.append('')

out = '\n'.join(L)
path = 'docs/14-入驻租户账号清单.md'
with open(path, 'w', encoding='utf-8') as f:
    f.write(out)
print('已生成:', path)
print('总行数:', len(L))
print('账号行数:', sum(1 for l in L if 'User@123' in l))
