# -*- coding: utf-8 -*-
"""机构作用域参数配置（需求二 / docs/44 §2）的**接口级**验收：B1 / B2 / B3。

为什么必须有它：docs/44 §2.8 把验收写成三条，其中两条只在**运行时**才成立 ——
  · **B1** 机构管理员能打开本机构参数（能力可用）；
  · **B2** 改本机构参数 → **另一个机构读同参数不变**（← 负向对照。没有它，「机构作用域」是真是假无法区分）；
  · **B3** 机构管理员直连**租户级**配置接口必须 403（← 最小权限。没有它，等于把租户参数下放了）。
静态哨兵 `_check_org_config_consistency.py` 只能证明「三处同源」，证明不了「写进去的值真的只影响本机构」。

判据回到事实源头（铁律 12）：B2 的「另一机构不变」**不读本脚本自己刚写入的返回值**，
而是用**另一机构的账号重新登录后重新取一次**；B2d 再回 `/api/v1/configs`（用户端真正的配置读取口）
确认覆盖值在**读取链路**上真的生效，而不只是在这个管理接口里自洽。

自净（铁律 11）：脚本写入的覆盖值在 finally 里删除；跑完 `sys_org_config` 不该留下探针行。

前置：后端已含本次改动、且已应用 V80/V81（否则 GET 会 404，脚本会明确报「前置不满足」并以非 0 退出，不伪装 PASS）。

用法：
    python scripts/_verify_org_config_scope.py                                  # 默认 :8080
    python scripts/_verify_org_config_scope.py --base http://127.0.0.1:8083     # 指定实例
"""
import argparse
import sys

import httpx

TENANT = '某某市某某区大数据管理局'
PWD = 'User@123'
# 两个机构管理员：同一租户、**不同机构** —— B2 负向对照就靠这一对
ORG_A = {'user': 'fagai_admin', 'inst': 1, 'inst_name': '某某区发展和改革局'}
ORG_B = {'user': 'shenpi_admin', 'inst': 2, 'inst_name': '某某区行政审批局'}

PROBE_KEY = 'billing.package.scenes'   # 必须是 ConfigController.USER_VISIBLE_KEYS 里的键，
#                                        否则 B2d 那条「读取链路生效」根本发不出去（会被 403 挡掉，
#                                        表现为恒真的负例 —— 探针键选错就等于没测）。
PROBE_VAL = '__probe_org_scope__'

PASS, FAIL = [], []


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print(("  [PASS] " if cond else "  [FAIL] ") + cid + ("" if cond else "  <- " + str(detail)[:400]))


def login(c, base, user):
    """登录；**后端不可达**要给出可读结论而不是裸 traceback（否则看起来像脚本坏了）。"""
    try:
        r = c.post(base + '/api/v1/auth/login',
                   json={'username': user, 'password': PWD, 'tenantName': TENANT}).json()
    except Exception as e:  # noqa: BLE001
        print("\n[后端不可达] %s：%s" % (base, e))
        print("  ⇒ 先确认目标实例在跑（本脚本默认 :8080；隔离实例常用 :8083）。")
        print("    提示：本环境用 `nohup ... &` 起的进程会在该次命令结束时被回收，"
              "需用工具后台常驻方式启动。")
        raise SystemExit(2)
    if r.get('code') != 0:
        return None
    return {'Authorization': 'Bearer ' + r['data']['accessToken']}


def get_items(c, base, h, inst):
    url = base + '/api/v1/admin/org-configs'
    params = {} if inst is None else {'institutionId': inst}
    return c.get(url, headers=h, params=params).json()


def item_of(data, key):
    for it in (data.get('data') or {}).get('items') or []:
        if it.get('configKey') == key:
            return it
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8080',
                    help='后端地址。两种写法都接受：主机根（http://host:port）或 API 前缀（…/api/v1）。'
                         '⚠️ 本仓其它哨兵的 --base 一律要求**带 /api/v1 的完整前缀**，'
                         '只传主机名会让登录请求打到 /auth/login（少了 api/v1）而回 401，'
                         '看起来像「登录失败」，实则调用姿势错——故这里对两种写法都做归一。')
    args = ap.parse_args()
    # 归一：允许传主机根，也允许传带 /api/v1（或 /api）的完整前缀
    base = args.base.rstrip('/')
    for suffix in ('/api/v1', '/api'):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break

    print("[机构作用域参数 · 接口级验收]  base=%s" % base)
    c = httpx.Client(timeout=30)

    hA = login(c, base, ORG_A['user'])
    hB = login(c, base, ORG_B['user'])
    chk("L1 两个机构管理员账号均可登录（%s / %s）" % (ORG_A['user'], ORG_B['user']),
        hA is not None and hB is not None)
    if not (hA and hB):
        print("\n合计：%d 通过 / %d 失败（登录失败，后续无法进行）" % (len(PASS), len(FAIL)))
        return 1

    # 前置体检：接口不存在（旧构建）时明确报出，别把 404 当成业务失败
    probe = c.get(base + '/api/v1/admin/org-configs', headers=hA).json()
    if probe.get('code') == 404 or '不存在' in str(probe.get('message', '')):
        print("\n[前置不满足] 该后端不含本次改动（/admin/org-configs 未注册）：%s" % probe)
        print("  ⇒ 需指向含 V80/V81 与新控制器的实例；本脚本以非 0 退出，不伪装 PASS。")
        return 2

    created = False
    try:
        # ---------------- B1：机构管理员能读本机构参数 ----------------
        dataA = get_items(c, base, hA, None)
        dA = dataA.get('data') or {}
        chk("B1 机构管理员可读本机构参数（code=0 且 items 非空）",
            dataA.get('code') == 0 and bool(dA.get('items')), str(dataA)[:200])
        chk("B1a 作用域被钉死：scopeLocked=true 且 institutionId=本人机构（%d）" % ORG_A['inst'],
            dA.get('scopeLocked') is True and dA.get('institutionId') == ORG_A['inst'], dA.get('institutionId'))
        chk("B1b 机构列表只含本人机构（不泄露同租户其它机构）",
            [i.get('id') for i in dA.get('institutions') or []] == [ORG_A['inst']],
            dA.get('institutions'))
        chk("B1c 分组中文名随接口返回（与「系统参数」页同源，前端不维护副本）",
            bool(dA.get('groups')), dA.get('groups'))

        before_A = item_of(dataA, PROBE_KEY)
        before_B = item_of(get_items(c, base, hB, None), PROBE_KEY)
        chk("B1d 探针键 %s 在两机构都存在且当前均未覆盖" % PROBE_KEY,
            before_A is not None and before_B is not None
            and before_A.get('overridden') is False and before_B.get('overridden') is False,
            (before_A, before_B))

        # ---------------- B2：写入只影响本机构 ----------------
        r = c.put(base + '/api/v1/admin/org-configs', headers=hA,
                  json={'configKey': PROBE_KEY, 'configValue': PROBE_VAL}).json()
        created = r.get('code') == 0
        chk("B2a 机构管理员写入本机构覆盖值 → code=0", created, str(r)[:200])

        after_A = item_of(get_items(c, base, hA, None), PROBE_KEY)
        chk("B2b 本机构读回：overridden=true 且 orgValue/effectiveValue 均为探针值",
            after_A and after_A.get('overridden') is True
            and after_A.get('orgValue') == PROBE_VAL and after_A.get('effectiveValue') == PROBE_VAL,
            after_A)

        # ★ 负向对照：换另一机构的账号**重新登录取一次**
        after_B = item_of(get_items(c, base, hB, None), PROBE_KEY)
        chk("B2c ★负向对照：另一机构（%s）读同参数仍未覆盖、值未被污染" % ORG_B['inst_name'],
            after_B and after_B.get('overridden') is False
            and after_B.get('effectiveValue') == before_B.get('effectiveValue')
            and after_B.get('effectiveValue') != PROBE_VAL,
            (before_B, after_B))

        # B2d：用户端真正的配置读取口也要跟着变（证明覆盖不是只在本接口自洽）
        uA = c.get(base + '/api/v1/configs', headers=hA, params={'keys': PROBE_KEY}).json()
        uB = c.get(base + '/api/v1/configs', headers=hB, params={'keys': PROBE_KEY}).json()
        chk("B2d ★读取链路生效：/api/v1/configs 对机构A返回探针值、对机构B仍返回原值",
            (uA.get('data') or {}).get(PROBE_KEY) == PROBE_VAL
            and (uB.get('data') or {}).get(PROBE_KEY) != PROBE_VAL,
            (uA, uB))

        # ---------------- B3：最小权限（不得动租户级配置） ----------------
        r403 = c.get(base + '/api/v1/admin/configs', headers=hA).json()
        chk("B3 ★最小权限：机构管理员直连租户级 /admin/configs 必须 403",
            r403.get('code') == 403, str(r403)[:200])

        # ---------------- 作用域硬边界 ----------------
        r_other = c.put(base + '/api/v1/admin/org-configs', headers=hA,
                        json={'institutionId': ORG_B['inst'], 'configKey': PROBE_KEY,
                              'configValue': PROBE_VAL}).json()
        chk("S1 ★作用域钉死：机构管理员传别的机构 id 必须 403（不得静默降级成自己的机构）",
            r_other.get('code') == 403, str(r_other)[:200])

        r_bad = c.put(base + '/api/v1/admin/org-configs', headers=hA,
                      json={'configKey': 'no.such.key.probe', 'configValue': 'x'}).json()
        chk("S2 未知参数键 → 400（不得写入垃圾键）", r_bad.get('code') == 400, str(r_bad)[:200])

        # 租户号一律取登录态：请求体里塞 tenantId 不得改变落库归属。
        # 判据只能这样写才有区分力：若该入参真被采纳（写进 tenant 999），
        # 则随后「按本人租户 + 本人机构」读取的 GET(A) 就**看不到**这次写入。
        r_tid = c.put(base + '/api/v1/admin/org-configs', headers=hA,
                      json={'tenantId': 999, 'configKey': PROBE_KEY, 'configValue': PROBE_VAL}).json()
        after_tid = item_of(get_items(c, base, hA, None), PROBE_KEY)
        chk("S3 传 tenantId 不生效：写入仍落在本人租户（GET 本人作用域可见探针值）",
            r_tid.get('code') == 0 and after_tid and after_tid.get('orgValue') == PROBE_VAL,
            (r_tid, after_tid))

    finally:
        if created:
            d = c.request('DELETE', base + '/api/v1/admin/org-configs', headers=hA,
                          params={'configKey': PROBE_KEY}).json()
            back = item_of(get_items(c, base, hA, None), PROBE_KEY)
            chk("Z1 自净：删除本机构覆盖值后恢复继承（overridden=false）",
                d.get('code') == 0 and back and back.get('overridden') is False, (d, back))

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
