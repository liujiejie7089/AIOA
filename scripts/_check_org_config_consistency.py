# -*- coding: utf-8 -*-
"""机构参数（需求二 / docs/44 §2）的「三处同源」静态哨兵。

为什么必须有这一条 —— 本文件 §2.8 的 B4 判据：
  「菜单 ↔ 路由 ↔ 接口三处一致：对矩阵里每个可见/不可见单元各断言一次
   （**这是防止「能见点不开」的唯一办法**）」。
  这类缺陷只靠人工 review 抓不住：
    · 菜单放开、路由没放开 ⇒ 用户看得到菜单、点进去被弹回首页（能见点不开）；
    · 路由放开、后端没放开 ⇒ 点得进去、接口 403（页面全空）；
    · 只给机构管理员放开了「系统参数」而没做作用域收窄 ⇒ **改到全租户参数（越权）**。
  三种表现都不报错、不抛异常、编译也过，只能在**静态层面**把三处摆在一起比。

判据（每条都锚定可核对的源码文本，不读运行时）：
  T1  常量唯一入口 permissions.ts 的 ORG_CONFIG_ROLES = [ADMIN, TENANT_ADMIN, ORG_ADMIN]
  T2  路由 settings/org-config 的 meta.allowRoles 必须**引用该常量**（而非另写角色数组）
  T3  菜单 computed showOrgConfigMenu 由同一常量推导
  T4  「系统配置」组守卫为「本组任一子项可见」（否则机构管理员整组仍被挡）
  T5  组内存在「机构参数」子项、且用 showOrgConfigMenu 控制
  T6  「系统参数」子项**必须保持** showTenantMenu —— 不得把租户级配置一并下放给机构
  T7  后端 PermissionCatalog 声明 org:config:manage 且角色集为 ORG_ADMINS（与 T1 同值）
  T8  V81 幂等播种该权限码（含 NOT EXISTS）
  T9  分组中文名有唯一定义 SysConfigGroups.NAMES
  T10 AdminConfigController **不得**再持有私有 GROUP_NAMES（单一事实源）
  T11 新 service 透出 groups
  T12 新控制器暴露 /admin/org-configs

用法：
    python scripts/_check_org_config_consistency.py              # 正跑
    python scripts/_check_org_config_consistency.py --selftest   # 判据有效性（喂变异副本，必须逐条报红）
"""
import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRM = 'web/apps/shell/src/constants/permissions.ts'
RTR = 'web/apps/shell/src/router/index.ts'
LAY = 'web/apps/shell/src/layouts/MainLayout.vue'
CAT = 'server/aioa-security/src/main/java/cn/aioa/security/PermissionCatalog.java'
ADM = 'server/aioa-resource/src/main/java/cn/aioa/resource/controller/AdminConfigController.java'
GRP = 'server/aioa-resource/src/main/java/cn/aioa/resource/support/SysConfigGroups.java'
SEED = 'server/aioa-boot/src/main/resources/db/migration/V81__org_config_perms.sql'
CTRL = 'server/aioa-chat/src/main/java/cn/aioa/chat/controller/OrgConfigController.java'
SVC = 'server/aioa-chat/src/main/java/cn/aioa/chat/service/OrgConfigService.java'

FILES = [PRM, RTR, LAY, CAT, ADM, GRP, SEED, CTRL, SVC]

PASS, FAIL = [], []


def chk(cid, cond, detail=""):
    (PASS if cond else FAIL).append(cid)
    print(("  [PASS] " if cond else "  [FAIL] ") + cid + ("" if cond else "  <- " + str(detail)[:300]))


def load(root=REPO):
    out = {}
    for rel in FILES:
        p = os.path.join(root, rel)
        out[rel] = open(p, encoding='utf-8').read() if os.path.exists(p) else None
    return out


def violations(f):
    """返回不满足的判据编号列表（纯函数：喂变异副本即可验证判据有没有区分力）。"""
    bad = []

    def need(cid, cond):
        if not cond:
            bad.append(cid)

    prm, rtr, lay = f.get(PRM), f.get(RTR), f.get(LAY)
    cat, adm, grp = f.get(CAT), f.get(ADM), f.get(GRP)
    seed, ctrl, svc = f.get(SEED), f.get(CTRL), f.get(SVC)

    need('T1', prm and re.search(
        r'ORG_CONFIG_ROLES[^=]*=\s*\[ROLE\.ADMIN,\s*ROLE\.TENANT_ADMIN,\s*ROLE\.ORG_ADMIN\]', prm))
    need('T2', rtr and re.search(
        r"path:\s*'settings/org-config'[^}]*allowRoles:\s*ORG_CONFIG_ROLES", rtr))
    need('T3', lay and re.search(
        r'showOrgConfigMenu[^=]*=\s*computed\(\(\)\s*=>\s*hasAnyRole\(roles(?:\.value)?,\s*ORG_CONFIG_ROLES\)\)', lay))
    need('T4', lay and re.search(r'v-if="showTenantMenu \|\| showOrgConfigMenu"', lay))
    need('T5', lay and re.search(r'v-if="showOrgConfigMenu"[^>]*index="/settings/org-config"', lay))
    need('T6', lay and re.search(r'v-if="showTenantMenu"[^>]*index="/settings"', lay))
    need('T7', cat and re.search(r'ORG_CONFIG_MANAGE\s*=\s*"org:config:manage"', cat)
         and re.search(r'Map\.entry\(ORG_CONFIG_MANAGE,\s*ORG_ADMINS\)', cat))
    need('T8', seed and 'org:config:manage' in seed and 'NOT EXISTS' in seed)
    need('T9', grp and 'NAMES' in grp and len(re.findall(r'put\(SysConfig\.GROUP_', grp)) >= 6)
    need('T10', adm and 'GROUP_NAMES' not in adm and 'SysConfigGroups.NAMES' in adm)
    need('T11', svc and 'SysConfigGroups.NAMES' in svc)
    need('T12', ctrl and '/admin/org-configs' in ctrl)
    return bad


def selftest():
    """判据有效性：对真实文件做**定点变异**，每条变异都必须让对应判据报红。

    不这么做就无法区分「真通过」与「判据写错了」—— 例如 T2 若误写成「包含 ORG_CONFIG_ROLES」
    这种宽松匹配，把 allowRoles 换成 TENANT_SCOPE_ROLES 也会绿。
    """
    print("\n[K] 判据有效性自检（--selftest）")
    base = load()
    miss = [c for c in FILES if base[c] is None]
    if miss:
        print("  [FAIL] 正本文件缺失，无法自检：" + ", ".join(miss))
        return 1

    cases = [
        ('T1', PRM, lambda s: s.replace('[ROLE.ADMIN, ROLE.TENANT_ADMIN, ROLE.ORG_ADMIN]', '[ROLE.ADMIN, ROLE.TENANT_ADMIN]')),
        ('T2', RTR, lambda s: s.replace("meta: { title: '机构参数', allowRoles: ORG_CONFIG_ROLES }",
                                        "meta: { title: '机构参数', allowRoles: TENANT_SCOPE_ROLES }")),
        ('T4', LAY, lambda s: s.replace('v-if="showTenantMenu || showOrgConfigMenu"', 'v-if="showTenantMenu"')),
        ('T6', LAY, lambda s: s.replace('v-if="showTenantMenu" index="/settings"',
                                        'v-if="showOrgConfigMenu" index="/settings"')),
        ('T7', CAT, lambda s: s.replace('Map.entry(ORG_CONFIG_MANAGE, ORG_ADMINS)',
                                        'Map.entry(ORG_CONFIG_MANAGE, TENANT_SCOPE)')),
        ('T8', SEED, lambda s: s.replace('NOT EXISTS', 'EXISTS')),
        ('T10', ADM, lambda s: s.replace('SysConfigGroups.NAMES', 'GROUP_NAMES')),
    ]
    ok = True
    for cid, rel, mut in cases:
        f = dict(base)
        mutated = mut(f[rel])
        if mutated == f[rel]:
            chk("K-%s 变异确实生效（否则该条自检形同虚设）" % cid, False, rel)
            ok = False
            continue
        f[rel] = mutated
        got = violations(f)
        chk("K-%s 变异后 %s 真报红" % (cid, cid), cid in got, "实际报红=" + str(got))
        ok = ok and (cid in got)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    print("[机构参数 · 三处同源静态哨兵]")
    f = load()
    missing = [c for c in FILES if f[c] is None]
    for c in missing:
        print("  [FAIL] 文件不存在：" + c)
    if missing:
        print("\n合计：0 通过 / %d 失败（文件缺失）" % len(missing))
        return 1

    bad = violations(f)
    for cid in ['T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12']:
        chk(cid, cid not in bad)

    print("\n合计：%d 通过 / %d 失败" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
