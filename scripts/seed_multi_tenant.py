# -*- coding: utf-8 -*-
"""
多租户企业数据填充（平台开通视角）

按「地级市 AI 公共服务平台」的真实客户结构，开通多家不同行业 / 规模的租户，
每家配置：租户管理员账号 → 资源池 → 下属机构（含企业管理员）→ 部门与负责人 → 员工 → 机构配额 → 资源授权。

市面标准做法：开通租户 = 建租户主体 + 开管理员账号 + 初始化资源池（同一事务），
随后按机构下发配额并授权资源，避免「能登录但没额度 / 有机构但没资源」的半开通状态。

用法：
  python scripts/seed_multi_tenant.py --dry-run
  python scripts/seed_multi_tenant.py
"""
import argparse
import json
import os
import sys

import httpx

BASE = 'http://127.0.0.1:8080'
PLATFORM = ('admin', 'Admin@123')
DEFAULT_PWD = 'User@123'
PERIOD = '2026-09'

# ---------------------------------------------------------------------------
# 企业真实数据结构：租户 → 机构 → 部门 → 员工
# ---------------------------------------------------------------------------
TENANTS = [
    {
        'code': 'JYJ-DEMO', 'name': '某某市某某区教育局', 'industry': '政府机关',
        'adminUsername': 'jyj_admin', 'adminName': '周慧敏',
        'tokenTotal': 3_000_000, 'expertSeats': 10, 'skillSeats': 16,
        'scale': '大型（下属 3 家单位，约 60 人）',
        'institutions': [
            {
                'name': '某某区教育发展研究院', 'code': 'ORG-JYFZYJY', 'orgType': 'INSTITUTION',
                'creditCode': '12330102MB2001001X', 'legalPerson': '沈立群',
                'contactMobile': '0571-8802****', 'contactEmail': 'jyfzyjy@jyj.gov.cn',
                'establishedAt': '2001-09-01',
                'adminUsername': 'jyfzyjy_admin', 'adminName': '沈立群',
                'quotaTokens': 1_200_000,
                'remark': '承担区域教育科研、课程与教学质量监测',
                'depts': [
                    {'name': '办公室', 'code': 'JY-BGS', 'leader': '何雨薇', 'jobs': ['办公室主任', '行政干事']},
                    {'name': '教学研究室', 'code': 'JY-JXYS', 'leader': '许建国', 'jobs': ['教研员', '教研员', '学科带头人']},
                    {'name': '质量监测科', 'code': 'JY-ZLJC', 'leader': '范晓东', 'jobs': ['监测专员', '数据分析员']},
                ],
            },
            {
                'name': '某某区教育技术装备中心', 'code': 'ORG-JYJSZB', 'orgType': 'INSTITUTION',
                'creditCode': '12330102MB2002002Y', 'legalPerson': '陆志远',
                'contactMobile': '0571-8803****', 'adminUsername': 'jyjszb_admin', 'adminName': '陆志远',
                'quotaTokens': 900_000,
                'remark': '负责区属学校教育信息化装备与运维',
                'depts': [
                    {'name': '装备管理科', 'code': 'ZB-GLK', 'leader': '唐伟', 'jobs': ['装备管理员', '采购专员']},
                    {'name': '技术支持组', 'code': 'ZB-JSZC', 'leader': '钱磊', 'jobs': ['运维工程师', '运维工程师', '网络安全员']},
                ],
            },
            {
                'name': '某某区青少年活动中心', 'code': 'ORG-QSNHG', 'orgType': 'INSTITUTION',
                'creditCode': '12330102MB2003003Z', 'legalPerson': '苏婉',
                'contactMobile': '0571-8804****', 'adminUsername': 'qsnhd_admin', 'adminName': '苏婉',
                'quotaTokens': 600_000,
                'remark': '面向全区青少年的校外教育与科创活动阵地',
                'depts': [
                    {'name': '活动策划部', 'code': 'QS-HDCB', 'leader': '毛俊', 'jobs': ['活动策划', '项目主管']},
                ],
            },
        ],
    },
    {
        'code': 'GAJ-DEMO', 'name': '某某市某某区公安分局', 'industry': '政府机关',
        'adminUsername': 'gaj_admin', 'adminName': '郑东雷',
        'tokenTotal': 2_500_000, 'expertSeats': 8, 'skillSeats': 12,
        'scale': '大型（下属 2 家单位，约 40 人）',
        'institutions': [
            {
                'name': '某某区公安分局指挥中心', 'code': 'ORG-GAZZZX', 'orgType': 'GOVERNMENT',
                'creditCode': '11330102MB3001001A', 'legalPerson': '郑东雷',
                'contactMobile': '0571-8810****', 'adminUsername': 'gazzzx_admin', 'adminName': '韩磊',
                'quotaTokens': 1_500_000,
                'remark': '承担 110 接处警、应急指挥与情报研判',
                'depts': [
                    {'name': '指挥调度科', 'code': 'GA-ZHDD', 'leader': '韩磊', 'jobs': ['调度员', '调度员', '值班长']},
                    {'name': '情报研判组', 'code': 'GA-QBYP', 'leader': '邱国栋', 'jobs': ['研判分析师', '数据分析员']},
                ],
            },
            {
                'name': '某某区公安分局法制大队', 'code': 'ORG-GAFZDD', 'orgType': 'GOVERNMENT',
                'creditCode': '11330102MB3002002B', 'legalPerson': '林正',
                'contactMobile': '0571-8811****', 'adminUsername': 'gafzdd_admin', 'adminName': '林正',
                'quotaTokens': 800_000,
                'remark': '案件法制审核、执法规范化与复议应诉',
                'depts': [
                    {'name': '执法监督科', 'code': 'GA-ZFJD', 'leader': '施明', 'jobs': ['法制审核员', '案审专员']},
                ],
            },
        ],
    },
    {
        'code': 'CTJT-DEMO', 'name': '某某市城市建设投资集团', 'industry': '国有企业',
        'adminUsername': 'ctjt_admin', 'adminName': '赵文博',
        'tokenTotal': 4_000_000, 'expertSeats': 12, 'skillSeats': 20,
        'scale': '集团型（下属 3 家子公司，约 120 人）',
        'institutions': [
            {
                'name': '某某城投工程建设有限公司', 'code': 'ORG-CTGCJS', 'orgType': 'STATE_OWNED',
                'creditCode': '91330102MA2G10001C', 'legalPerson': '马建军',
                'contactMobile': '0571-8820****', 'contactEmail': 'gcjs@ctjt.com',
                'establishedAt': '2005-04-12',
                'adminUsername': 'ctgcjs_admin', 'adminName': '马建军',
                'quotaTokens': 1_800_000,
                'remark': '市政基础设施与房建工程施工总承包',
                'depts': [
                    {'name': '工程管理部', 'code': 'CT-GCGL', 'leader': '胡文静', 'jobs': ['项目经理', '项目经理', '施工员', '安全员']},
                    {'name': '成本控制部', 'code': 'CT-CBKZ', 'leader': '袁芳', 'jobs': ['造价工程师', '预算员']},
                    {'name': '质量安全部', 'code': 'CT-ZLAQ', 'leader': '崔广志', 'jobs': ['质量主管', '安全主管']},
                ],
            },
            {
                'name': '某某城投资产运营有限公司', 'code': 'ORG-CTZCYY', 'orgType': 'STATE_OWNED',
                'creditCode': '91330102MA2G10002D', 'legalPerson': '宋佳',
                'contactMobile': '0571-8821****', 'adminUsername': 'ctzcyy_admin', 'adminName': '宋佳',
                'quotaTokens': 1_200_000,
                'remark': '集团存量资产运营与物业管理',
                'depts': [
                    {'name': '招商运营部', 'code': 'ZY-ZSYY', 'leader': '聂远', 'jobs': ['招商经理', '运营专员']},
                    {'name': '物业服务部', 'code': 'ZY-WYFW', 'leader': '梁静', 'jobs': ['物业主管', '客服专员']},
                ],
            },
            {
                'name': '某某城投数字科技有限公司', 'code': 'ORG-CTSZKJ', 'orgType': 'STATE_OWNED',
                'creditCode': '91330102MA2G10003E', 'legalPerson': '方子谦',
                'contactMobile': '0571-8822****', 'adminUsername': 'ctszkj_admin', 'adminName': '方子谦',
                'quotaTokens': 900_000,
                'remark': '集团数字化转型与智慧工地平台建设',
                'depts': [
                    {'name': '研发部', 'code': 'SZ-YFB', 'leader': '邹凯', 'jobs': ['后端工程师', '前端工程师', '算法工程师']},
                    {'name': '交付服务部', 'code': 'SZ-JFW', 'leader': '董悦', 'jobs': ['实施顾问', '运维工程师']},
                ],
            },
        ],
    },
    {
        'code': 'RMYY-DEMO', 'name': '某某区人民医院', 'industry': '事业单位',
        'adminUsername': 'rmyy_admin', 'adminName': '吴明华',
        'tokenTotal': 2_000_000, 'expertSeats': 10, 'skillSeats': 14,
        'scale': '中型（1 家主体，约 80 人）',
        'institutions': [
            {
                'name': '某某区人民医院医务部', 'code': 'ORG-RMYYYW', 'orgType': 'INSTITUTION',
                'creditCode': '12330102MB4001001P', 'legalPerson': '吴明华',
                'contactMobile': '0571-8830****', 'adminUsername': 'rmyyywb_admin', 'adminName': '郑雅',
                'quotaTokens': 1_000_000,
                'remark': '医疗质量管理、病历质控与医务协调',
                'depts': [
                    {'name': '医务科', 'code': 'YY-YWK', 'leader': '郑雅', 'jobs': ['医务干事', '质控专员']},
                    {'name': '病案室', 'code': 'YY-BAS', 'leader': '蒋琳', 'jobs': ['病案编码员', '病案管理员']},
                ],
            },
            {
                'name': '某某区人民医院信息中心', 'code': 'ORG-RMYYXX', 'orgType': 'INSTITUTION',
                'creditCode': '12330102MB4002002Q', 'legalPerson': '孙浩',
                'contactMobile': '0571-8831****', 'adminUsername': 'rmyyxx_admin', 'adminName': '孙浩',
                'quotaTokens': 700_000,
                'remark': '医院信息系统建设与数据治理',
                'depts': [
                    {'name': '系统运维组', 'code': 'XX-XTYW', 'leader': '冯锐', 'jobs': ['运维工程师', '数据库管理员']},
                ],
            },
        ],
    },
    {
        'code': 'KFGQ-DEMO', 'name': '某某高新技术产业开发区管委会', 'industry': '政府机关',
        'adminUsername': 'kfgq_admin', 'adminName': '柳承志',
        'tokenTotal': 3_500_000, 'expertSeats': 12, 'skillSeats': 18,
        'scale': '大型（下属 2 家单位 + 服务大厅，约 90 人）',
        'institutions': [
            {
                'name': '某某高新区企业服务中心', 'code': 'ORG-GXQFW', 'orgType': 'GOVERNMENT',
                'creditCode': '11330102MB5001001M', 'legalPerson': '柳承志',
                'contactMobile': '0571-8840****', 'adminUsername': 'gxqqyfw_admin', 'adminName': '谭敏',
                'quotaTokens': 2_000_000,
                'remark': '企业开办、政策兑现与诉求闭环服务',
                'depts': [
                    {'name': '综合受理科', 'code': 'GX-ZHSL', 'leader': '谭敏', 'jobs': ['窗口受理员', '窗口受理员', '业务主管']},
                    {'name': '政策兑现科', 'code': 'GX-ZCDX', 'leader': '毕文', 'jobs': ['政策专员', '审核专员']},
                    {'name': '企业服务专员组', 'code': 'GX-QYZY', 'leader': '廖凡', 'jobs': ['服务专员', '服务专员']},
                ],
            },
            {
                'name': '某某高新区科技创新局', 'code': 'ORG-GXQKJ', 'orgType': 'GOVERNMENT',
                'creditCode': '11330102MB5002002N', 'legalPerson': '华瑾',
                'contactMobile': '0571-8841****', 'adminUsername': 'gxqkjcx_admin', 'adminName': '华瑾',
                'quotaTokens': 1_200_000,
                'remark': '高新技术企业培育、科技项目与人才政策',
                'depts': [
                    {'name': '项目服务科', 'code': 'KJ-XMFW', 'leader': '闵睿', 'jobs': ['项目专员', '项目专员']},
                    {'name': '人才工作科', 'code': 'KJ-RCGZ', 'leader': '章晗', 'jobs': ['人才服务专员']},
                ],
            },
        ],
    },
    {
        'code': 'MYQY-DEMO', 'name': '某某智能科技有限公司', 'industry': '民营企业',
        'adminUsername': 'znkj_admin', 'adminName': '傅宸',
        'tokenTotal': 1_200_000, 'expertSeats': 6, 'skillSeats': 10,
        'scale': '中小型（1 家主体，约 30 人）',
        'institutions': [
            {
                'name': '某某智能科技有限公司研发中心', 'code': 'ORG-ZNKJYF', 'orgType': 'PRIVATE',
                'creditCode': '91330102MA2H10001F', 'legalPerson': '傅宸',
                'contactMobile': '0571-8850****', 'contactEmail': 'rd@znkj-tech.com',
                'establishedAt': '2018-07-23',
                'adminUsername': 'znkjyf_admin', 'adminName': '傅宸',
                'quotaTokens': 700_000,
                'remark': '工业视觉与边缘智能算法研发',
                'depts': [
                    {'name': '算法部', 'code': 'ZN-SFB', 'leader': '祁野', 'jobs': ['算法工程师', '算法工程师', '研究员']},
                    {'name': '工程部', 'code': 'ZN-GCB', 'leader': '路遥', 'jobs': ['嵌入式工程师', '测试工程师']},
                ],
            },
            {
                'name': '某某智能科技有限公司市场部', 'code': 'ORG-ZNKJSC', 'orgType': 'PRIVATE',
                'creditCode': '91330102MA2H10002G', 'legalPerson': '简宁',
                'contactMobile': '0571-8851****', 'adminUsername': 'znkjsc_admin', 'adminName': '简宁',
                'quotaTokens': 300_000,
                'remark': '行业解决方案销售与渠道拓展',
                'depts': [
                    {'name': '销售一部', 'code': 'SC-XSYB', 'leader': '简宁', 'jobs': ['销售经理', '销售代表']},
                ],
            },
        ],
    },
]

created = []
skipped = []


def login(c, u, p):
    r = c.post('/api/v1/auth/login', json={'username': u, 'password': p})
    if r.status_code != 200 or r.json().get('code') != 0:
        raise SystemExit('login failed %s: %s' % (u, r.text[:200]))
    d = r.json()['data']
    return {'Authorization': 'Bearer ' + d['accessToken']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    c = httpx.Client(base_url=BASE, trust_env=False, timeout=60)
    H = login(c, *PLATFORM)

    # 已存在租户，避免重复开通
    exist = {t['code'] for t in c.get('/api/v1/admin/tenants', headers=H).json()['data']}

    for t in TENANTS:
        if t['code'] in exist:
            skipped.append(t['code'])
            print('skip %-12s %s（已存在）' % (t['code'], t['name']))
            continue
        print('--- 开通租户 %s %s' % (t['code'], t['name']))
        if args.dry_run:
            created.append({
                'code': t['code'], 'name': t['name'], 'industry': t['industry'], 'scale': t['scale'],
                'tokenTotal': t['tokenTotal'], 'expertSeats': t['expertSeats'], 'skillSeats': t['skillSeats'],
                'adminUsername': t['adminUsername'], 'adminName': t['adminName'],
                'institutionCount': len(t['institutions']),
                'memberCount': sum(len(d['jobs']) + 1 for i in t['institutions'] for d in i['depts']),
            })
            continue

        r = c.post('/api/v1/admin/tenants', headers=H, json={
            'code': t['code'], 'name': t['name'],
            'adminUsername': t['adminUsername'], 'adminName': t['adminName'],
            'adminPassword': DEFAULT_PWD,
            'tokenTotal': t['tokenTotal'],
            'expertSeats': t['expertSeats'], 'skillSeats': t['skillSeats'],
            'period': PERIOD,
        }).json()
        if r.get('code') != 0:
            print('   !! 开通失败：%s' % r.get('message'))
            continue
        tid = r['data']['tenantId']
        print('   tenantId=%s 管理员=%s 资源池=%d 词元' % (tid, t['adminUsername'], t['tokenTotal']))

        # 以租户管理员身份建机构 / 部门 / 员工 / 配额 / 授权
        HT = login(c, t['adminUsername'], DEFAULT_PWD)
        inst_ids = []
        member_total = 0
        for ins in t['institutions']:
            ri = c.post('/api/v1/tenant/institutions', headers=HT, json={
                'name': ins['name'], 'code': ins['code'], 'orgType': ins.get('orgType'),
                'creditCode': ins.get('creditCode'), 'legalPerson': ins.get('legalPerson'),
                'contactMobile': ins.get('contactMobile'), 'contactEmail': ins.get('contactEmail'),
                'establishedAt': ins.get('establishedAt'),
                'adminUsername': ins['adminUsername'], 'adminName': ins['adminName'],
                'adminPassword': DEFAULT_PWD,
                'remark': ins.get('remark'),
            }).json()
            if ri.get('code') != 0:
                print('   !! 机构失败 %s：%s' % (ins['code'], ri.get('message')))
                continue
            iid = ri['data']['id']
            inst_ids.append({'id': iid, 'code': ins['code'], 'name': ins['name']})
            print('   + 机构 %s（id=%s）' % (ins['code'], iid))

            # 机构配额
            c.post('/api/v1/tenant/org-quotas', headers=HT, json={
                'institutionId': iid, 'period': PERIOD,
                'quotaTokens': ins['quotaTokens'],
                'reason': '入驻配额下发',
            })

            # 以该机构的企业管理员身份建部门与员工
            HO = login(c, ins['adminUsername'], DEFAULT_PWD)
            rows = []
            for d in ins['depts']:
                rd = c.post('/api/v1/org/departments', headers=HO, json={
                    'name': d['name'], 'code': d['code'], 'parentId': 0, 'sort': 10,
                }).json()
                if rd.get('code') != 0:
                    print('      !! 部门失败 %s：%s' % (d['code'], rd.get('message')))
                    continue
                did = rd['data']['id']
                # 负责人：先建为员工，再回写部门负责人
                leader_username = '%s_ldr' % d['code'].lower().replace('-', '')
                rows.append({'name': d['leader'], 'username': leader_username,
                             'employeeNo': 'L%s' % d['code'][-3:], 'jobTitle': d['name'] + '负责人',
                             'departmentCode': d['code']})
                for i, job in enumerate(d['jobs']):
                    rows.append({
                        'name': '%s%02d' % (job, i + 1),
                        'username': '%s_m%02d' % (d['code'].lower().replace('-', ''), i + 1),
                        'employeeNo': '%s%03d' % (d['code'][-3:], 100 + i),
                        'jobTitle': job, 'departmentCode': d['code'],
                    })
            if rows:
                rim = c.post('/api/v1/org/members/import', headers=HO, json={'rows': rows}).json()
                ok = (rim.get('data') or {}).get('success', 0)
                member_total += ok
                print('      + 员工 %s 人' % ok)

            # 回写部门负责人（用刚导入的负责人账号）
            for d in ins['depts']:
                leader_username = '%s_ldr' % d['code'].lower().replace('-', '')
                rl = c.get('/api/v1/org/members?keyword=%s&size=5' % d['leader'], headers=HO).json()
                found = next((m for m in ((rl.get('data') or {}).get('items') or [])
                              if m.get('username') == leader_username), None)
                if not found:
                    continue
                rds = c.get('/api/v1/org/departments', headers=HO).json()
                flat = []
                def walk(ns):
                    for n in (ns or []):
                        flat.append(n)
                        walk(n.get('children'))
                walk((rds.get('data') or {}).get('tree'))
                dept = next((x for x in flat if x.get('code') == d['code']), None)
                if dept:
                    c.put('/api/v1/org/departments/%s' % dept['id'], headers=HO, json={
                        'leaderUserId': found['userId'], 'leaderName': d['leader'],
                    })

        # 资源授权：给每家机构授权 deepseek 模型
        cat = (c.get('/api/v1/tenant/grants/catalog', headers=HT).json().get('data') or {})
        models = cat.get('models') or []
        ds = next((m for m in models if m.get('providerKey') == 'deepseek'), None)
        if ds:
            for ins in inst_ids:
                c.post('/api/v1/tenant/grants', headers=HT, json={
                    'institutionId': ins['id'], 'resType': 'MODEL',
                    'resId': ds['id'], 'resKey': 'deepseek', 'resName': ds.get('name'),
                    'extra': json.dumps({'billing_ratio': 1.0}), 'enabled': True,
                })

        created.append({
            'tenantId': tid, 'code': t['code'], 'name': t['name'], 'industry': t['industry'],
            'scale': t['scale'], 'adminUsername': t['adminUsername'], 'adminName': t['adminName'],
            'tokenTotal': t['tokenTotal'], 'expertSeats': t['expertSeats'], 'skillSeats': t['skillSeats'],
            'institutionCount': len(inst_ids), 'memberCount': member_total,
            'institutions': inst_ids, 'password': DEFAULT_PWD,
        })

    out = {
        'period': PERIOD,
        'defaultPassword': DEFAULT_PWD,
        'created': created,
        'skipped': skipped,
    }
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'logs', 'seed_multi_tenant.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print('\n================ 开通汇总 ================')
    print('%-12s %-26s %-10s %8s %6s %6s %8s' % ('编码', '租户名称', '行业', '词元池', '机构', '员工', '管理员'))
    for t in created:
        print('%-12s %-26s %-10s %8s %6s %6s %8s' % (
            t['code'], t['name'][:26], t['industry'], f"{t['tokenTotal']:,}",
            t['institutionCount'], t['memberCount'], t['adminUsername']))
    print('\n结果已写入：%s' % path)


if __name__ == '__main__':
    main()
