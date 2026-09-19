# -*- coding: utf-8 -*-
"""把本地库收敛为「平台基线 + 两个示例数据集（租户 2 / 3）」。

保留（平台基线，tenant_id=0）：sys_tenant / sys_user / sys_role / sys_permission /
sys_role_permission / sys_user_role / sys_config / model_config / model_provider /
tool_system / tool_definition / tool_permission / agent_definition
保留：tenant_id ∈ {2, 3} 的全部数据（两个示例数据集）
清除：其余所有 tenant_id=0 的业务与日志数据

用法：
    python scripts/_prod_baseline_cleanup.py            # 预演
    python scripts/_prod_baseline_cleanup.py --apply    # 备份 + 执行
"""
import datetime as dt
import os
import sys

import pymysql

DB = dict(host='127.0.0.1', port=3306, user='root', password='', database='aioa', charset='utf8mb4')
BACKUP_DIR = r'C:/Users/刘尖尖/AppData/Local/Temp/aioa-db-backup-20260920'

# 平台基线上必须保留 tenant_id=0 数据的表
KEEP_TENANT0 = {
    'sys_tenant', 'sys_user', 'sys_role', 'sys_permission', 'sys_role_permission',
    'sys_user_role', 'sys_config', 'model_config', 'model_provider',
    'tool_system', 'tool_definition', 'tool_permission', 'agent_definition',
}


def dump(cur, path):
    tables = []
    cur.execute('SHOW TABLES')
    for (t,) in cur.fetchall():
        tables.append(t)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'-- AIOA 本地库备份 {dt.datetime.now():%Y-%m-%d %H:%M:%S}\n')
        f.write('SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n')
        for t in tables:
            cur.execute(f'SHOW CREATE TABLE `{t}`')
            f.write(f'\nDROP TABLE IF EXISTS `{t}`;\n{cur.fetchone()[1]};\n')
            cur.execute(f'SELECT * FROM `{t}`')
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if not rows:
                continue
            head = 'INSERT INTO `%s` (`%s`) VALUES\n' % (t, '`,`'.join(cols))
            batch = []
            for r in rows:
                vals = []
                for v in r:
                    if v is None:
                        vals.append('NULL')
                    elif isinstance(v, (int, float)):
                        vals.append(str(v))
                    elif isinstance(v, (bytes, bytearray)):
                        vals.append("X'%s'" % v.hex())
                    else:
                        s = str(v).replace('\\', '\\\\').replace("'", "\\'")
                        vals.append("'%s'" % s)
                batch.append('(' + ','.join(vals) + ')')
                if len(batch) >= 200:
                    f.write(head + ',\n'.join(batch) + ';\n')
                    batch = []
            if batch:
                f.write(head + ',\n'.join(batch) + ';\n')
        f.write('\nSET FOREIGN_KEY_CHECKS=1;\n')
    return len(tables)


def main():
    apply = '--apply' in sys.argv
    conn = pymysql.connect(**DB)
    cur = conn.cursor()

    cur.execute('SHOW TABLES')
    tables = [r[0] for r in cur.fetchall()]

    # 保留租户 2 / 3（两个示例数据集）与租户 9（E2E 全链账号载体，待确认后再定）
    KEEP_TENANTS = '(2,3,9)'
    plan = []
    for t in tables:
        if t.startswith('flyway'):
            continue
        cur.execute(f"SHOW COLUMNS FROM `{t}` LIKE 'tenant_id'")
        if not cur.fetchone():
            continue
        if t in KEEP_TENANT0:
            where = f'tenant_id NOT IN (0,2,3,9)'
        else:
            where = f'tenant_id NOT IN {KEEP_TENANTS}'
        cur.execute(f'SELECT COUNT(*) FROM `{t}` WHERE {where}')
        n = cur.fetchone()[0]
        if not n:
            continue
        cur.execute(f'SELECT tenant_id,COUNT(*) FROM `{t}` WHERE {where} GROUP BY tenant_id ORDER BY tenant_id')
        dist = dict(cur.fetchall())
        plan.append((t, n, where, dist))

    print(f'将清除：{len(plan)} 张表 / {sum(n for _, n, _, _ in plan)} 行')
    print(f'{"表":<30}{"行数":>8}   涉及租户')
    for t, n, _, dist in sorted(plan, key=lambda x: -x[1]):
        print(f'   {t:<30}{n:>8}   {dist}')
    print('\n保留：租户 2 / 3 全部数据（两个示例数据集）')
    print('保留：租户 9 全部数据（E2E 全链账号 znkj_admin / znsfb_m01 在此，待你确认是否一并清除）')
    print('保留：平台基线 tenant_id=0 的 %d 张表' % len(KEEP_TENANT0))

    if not apply:
        print('\n（预演模式，未改动。加 --apply 执行）')
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f'aioa-full-{dt.datetime.now():%Y%m%d_%H%M%S}.sql')
    print(f'\n正在导出全库备份 -> {path}')
    n = dump(cur, path)
    size = os.path.getsize(path) / 1048576
    print(f'备份完成：{n} 张表，{size:.1f} MB')
    if size < 1:
        sys.exit('备份体积异常，已中止清理')

    total = 0
    for t, _, where, _dist in plan:
        cur.execute(f'DELETE FROM `{t}` WHERE {where}')
        total += cur.rowcount
    conn.commit()
    print(f'已清除 {total} 行（覆盖 {len(plan)} 张表）')
    print(f'恢复方式：mysql -uroot aioa < {path}')
    conn.close()


main()
