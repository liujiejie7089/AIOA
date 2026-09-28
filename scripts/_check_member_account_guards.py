# -*- coding: utf-8 -*-
"""员工 ↔ 用户账号 多对多 的静态守卫（docs/38 批次 C，无需启动服务）。

背景（2026-09-27）：
    规格要求「一个员工也可以有多个用户帐号」「有些管理员用户帐号是虚拟的，没有对应的员工」。
    此前 `org_member.user_id` 是**单值**外键，多账号无从表达。本批新增中间表 `org_member_account`，
    **保留 `org_member.user_id` 作为主账号**（通知/审批/鉴权/机构归属都读它）。

    这一批的危险点全部是"**静默**"性质的：
      · 中间表插入了、但 `org_member.user_id` 没同步 ⇒ 出现两个口径的"主账号"；
      · 各处自己写 `setIsPrimary(1)` ⇒ 一个员工出现两个主账号；
      · 解绑把主账号也解掉 ⇒ 员工失去唯一身份（通知发给谁、归属哪个机构全碎）；
      · 绑定不校验租户 ⇒ 把别的租户的账号挂到本租户员工上（越权）；
      · 删除员工不清绑定 ⇒ 中间表留下指向已删员工的孤儿行，"虚拟账号"判据跟着失真；
      · 后端做了能力、前端没有入口 ⇒ 能力事实上不可用（铁律 #4）；
      · 旧文案「如需换账号，请移除该员工后重新新增」在多账号上线后已失真，却被照抄不动（铁律 #1）。
    以上任何一条都不会报错，只会让数据慢慢失真 —— 故必须静态钉死。

本守卫断言：
    M1  中间表只有一处定义（迁移建表 + 一个实体），不重复建
    M2  `is_primary=1` 只允许在 MemberAccountService 里产生（同步主账号的唯一出口）
    M3  主账号同步被**新建**与**批量导入**两条建档路径都调用（漏一条就有"隐性虚拟"员工）
    M4  主账号不可解绑（且给出明确文案，不静默降级）
    M5  跨租户绑定必须被拒（越权入口）
    M6  删除员工必须清掉它的账号绑定（不留孤儿行）
    M7  端点权限：追加/解绑须 requireOrgWriter；账号候选须 requireOrgUser
    M8  前端必须真接出来：名册页用 accounts，且调候选/绑定/解绑三个接口
    M9  前端不得复刻后端的裁决文案（避免两处口径）
    M10 名册页不得再出现已失真的旧文案「移除该员工后重新新增」
    M11 候选池不得被 E2E 残留反噬（造账号的套件收尾必须让账号退出候选池）

★ 断言前**必须剥离注释**（Java `//`、`/* */`；Web `<!-- -->`）—— 本仓注释会复述这些关键字，
  按裸文本判定就是"谁写注释谁报红"（pitfalls #75）。
用法：
    python scripts/_check_member_account_guards.py            # 跑检查
    python scripts/_check_member_account_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
MIGRATION = os.path.join(SERVER, "aioa-boot", "src", "main", "resources", "db", "migration")

MA_SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "service", "MemberAccountService.java")
TREE_SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                        "org", "service", "OrgTreeService.java")
ORG_CTRL = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                        "org", "controller", "OrgAdminController.java")
VIEW = os.path.join(SHELL, "views", "OrgStructureView.vue")
API_ORG = os.path.join(SHELL, "api", "org.ts")
V63_SUITE = os.path.join(ROOT, "scripts", "e2e_v63_org_feedback.py")

STALE_COPY = "移除该员工后重新新增"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def checks(t):
    out = []
    svc, tree, ctrl = t["ma_svc"], t["tree_svc"], t["ctrl"]
    view, api = t["view"], t["api"]

    # ---- M1 中间表只有一处定义
    creates = [p for p, s in t["java_all"].items() if "org_member_account` (" in s]
    mig_hits = [p for p, s in t["migrations"].items() if "CREATE TABLE org_member_account" in s]
    out.append((
        "M1 中间表定义唯一（一处建表 + 一个实体）",
        len(mig_hits) == 1 and len(creates) <= 1,
        "建表处 %s；实体定义处 %s" % ([os.path.basename(p) for p in mig_hits],
                                     [os.path.basename(p) for p in creates]),
    ))

    # ---- M2 is_primary=1 的唯一产生处
    writers = [p for p, s in t["java_all"].items()
               if "setIsPrimary(PRIMARY)" in s or "setIsPrimary(1)" in s]
    other = [p for p in writers if os.path.basename(p) != "MemberAccountService.java"]
    out.append((
        "M2 is_primary=1 只在 MemberAccountService 产生",
        len(writers) >= 1 and not other
        and "insert(memberId, member.getTenantId(), uid, PRIMARY, actorId);" in svc,
        "其它写入点：%s" % [os.path.basename(p) for p in other],
    ))

    # ---- M3 两条建档路径都要同步主账号
    out.append((
        "M3 主账号同步被「新建」与「批量导入」都调用",
        tree.count("memberAccounts.syncPrimary(") >= 2,
        "syncPrimary 调用 %d 处（应 ≥2：createMember + importMembers）"
        % tree.count("memberAccounts.syncPrimary("),
    ))

    # ---- M4 主账号不可解绑
    out.append((
        "M4 解绑主账号必须被拒且给明确文案",
        "if (userId.equals(member.getUserId())) {" in svc
        and "主账号不可解绑" in svc,
        "缺少主账号解绑保护，或没有可读文案（静默降级）",
    ))

    # ---- M5 跨租户绑定必须被拒
    out.append((
        "M5 跨租户绑定必须被拒（403）",
        "!ut.equals(member.getTenantId()" in svc and "BizException.forbidden(" in svc,
        "缺少跨租户校验 ⇒ 可以把别的租户账号挂到本租户员工上",
    ))

    # ---- M6 删除员工要清绑定
    out.append((
        "M6 删除员工必须清掉其账号绑定",
        "memberAccounts.dropAll(" in tree and "public void dropAll(Long memberId)" in svc,
        "deleteMember 未清绑定 ⇒ 中间表留下孤儿行，「虚拟账号」判据失真",
    ))

    # ---- M7 权限口径
    attach_seg = ctrl.split('@PostMapping("/members/{id}/accounts")', 1)[-1][:600] \
        if '@PostMapping("/members/{id}/accounts")' in ctrl else ""
    detach_seg = ctrl.split('@DeleteMapping("/members/{id}/accounts/{userId}")', 1)[-1][:600] \
        if '@DeleteMapping("/members/{id}/accounts/{userId}")' in ctrl else ""
    cand_seg = ctrl.split('@GetMapping("/accounts")', 1)[-1][:400] \
        if '@GetMapping("/accounts")' in ctrl else ""
    out.append((
        "M7 端点权限：绑定/解绑 requireOrgWriter，候选 requireOrgUser",
        "guard.requireOrgWriter()" in attach_seg
        and "guard.requireOrgWriter()" in detach_seg
        and "guard.requireOrgUser()" in cand_seg,
        "attach=%s detach=%s candidates=%s"
        % ("requireOrgWriter" in attach_seg, "requireOrgWriter" in detach_seg,
           "requireOrgUser" in cand_seg),
    ))

    # ---- M8 前端真接出来（铁律 #4）
    out.append((
        "M8 名册页真用 accounts 与候选/绑定/解绑三个接口",
        "accounts" in view
        and "listAccountCandidates(" in view
        and "attachMemberAccount(" in view
        and "detachMemberAccount(" in view
        and "listAccountCandidates" in api
        and "attachMemberAccount" in api
        and "detachMemberAccount" in api,
        "view: accounts=%s cand=%s attach=%s detach=%s | api: cand=%s attach=%s detach=%s"
        % ("accounts" in view, "listAccountCandidates(" in view,
           "attachMemberAccount(" in view, "detachMemberAccount(" in view,
           "listAccountCandidates" in api, "attachMemberAccount" in api,
           "detachMemberAccount" in api),
    ))

    # ---- M9 前端不得复刻裁决文案
    out.append((
        "M9 前端不得复刻后端裁决文案（避免两处口径）",
        "主账号不可解绑" not in view,
        "前端出现了后端特有的错误文案 ⇒ 裁决又开始在两处各写一份",
    ))

    # ---- M10 旧文案已失真，不得照抄
    out.append((
        "M10 名册页不得再出现已失真的旧文案「%s」" % STALE_COPY,
        STALE_COPY not in view,
        "多账号上线后「换账号要重建员工」已不成立，文案必须与今天的能力同源（铁律 #1）",
    ))

    # ---- M11 候选池不得被 E2E 残留反噬
    # 候选接口是**租户级**查询（规格要求「虚拟管理员账号」也要能选），因此任何「留了账号却没人管」的
    # 套件都会持续往下拉里灌噪音。2026-09-27 实测：e2e_v63 只置机构 CLOSED、不处理账号，
    # 11 次运行攒下 44 个 e2e* 账号，把真实候选（12 个）淹掉。故钉住「收尾必须软删自建账号」。
    out.append((
        "M11 造账号的套件收尾必须让账号退出候选池（e2e_v63 软删自建账号）",
        "soft_delete_accounts((admin_user, led_user, mem_user, mem2_user))" in t["v63"],
        "e2e_v63 收尾未软删其新建账号 ⇒ 会计入候选池，污染「追加绑定」下拉",
    ))

    return out


def load():
    java_files = [p for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True)
                  if os.sep + "target" + os.sep not in p]
    mig_files = glob.glob(os.path.join(MIGRATION, "*.sql"))
    return {
        "ma_svc": _strip_java(_read(MA_SVC)),
        "tree_svc": _strip_java(_read(TREE_SVC)),
        "ctrl": _strip_java(_read(ORG_CTRL)),
        "view": _strip_web(_read(VIEW)),
        "api": _strip_web(_read(API_ORG)),
        "v63": _read(V63_SUITE),
        "java_all": {p: _strip_java(_read(p)) for p in java_files},
        "migrations": {p: _read(p) for p in mig_files},
    }


def run():
    base = load()
    results = checks(base)
    bad = [c for c in results if not c[1]]
    for cid, ok, detail in results:
        print(("  [OK]   " if ok else "  [FAIL] ") + cid
              + (("  " + detail) if (detail and not ok) else ""))
    print("\n=== 正向 %d/%d 通过 ===" % (len(results) - len(bad), len(results)))
    return 1 if bad else 0


def selftest():
    """注入突变，要求对应断言**必须真报红**；突变未生效（SKIP）同样计失败（pitfalls #77）。"""
    base = load()
    mutations = [
        ("M1 第二处建表",
         lambda t: dict(t, migrations=dict(t["migrations"], **{
             "__synthetic__.sql": "CREATE TABLE org_member_account ( id BIGINT );"})),
         ["M1"]),
        ("M2 别处也写 is_primary",
         lambda t: dict(t, java_all=dict(t["java_all"], **{
             "__synthetic__.java": "a.setIsPrimary(1);"})),
         ["M2"]),
        ("M3 批量导入漏掉主账号同步",
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             "                memberAccounts.syncPrimary(m, actor.getUserId());\n", "")),
         ["M3"]),
        ("M4 放开主账号解绑",
         lambda t: dict(t, ma_svc=t["ma_svc"].replace(
             "if (userId.equals(member.getUserId())) {", "if (false) {")),
         ["M4"]),
        ("M5 去掉跨租户校验",
         lambda t: dict(t, ma_svc=t["ma_svc"].replace(
             "!ut.equals(member.getTenantId() == null ? 0L : member.getTenantId())", "false")),
         ["M5"]),
        ("M6 删员工不清绑定",
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             "memberAccounts.dropAll(id);", "")),
         ["M6"]),
        ("M7 候选端点漏权限校验",
         lambda t: dict(t, ctrl=t["ctrl"].replace(
             '        AuthUser u = guard.requireOrgUser();\n'
             '        return ApiResponse.ok(memberAccountService.candidates(',
             '        AuthUser u = cn.aioa.security.AuthUserContext.require();\n'
             '        return ApiResponse.ok(memberAccountService.candidates(')),
         ["M7"]),
        ("M8 前端只 import 不调用",
         lambda t: dict(t, view="\n".join(
             ln for ln in t["view"].splitlines() if "attachMemberAccount(" not in ln)),
         ["M8"]),
        ("M9 前端复刻裁决文案",
         lambda t: dict(t, view=t["view"].replace(
             "function submitMember", "const RULE = '主账号不可解绑'\nfunction submitMember")),
         ["M9"]),
        ("M10 旧文案回归",
         lambda t: dict(t, view=t["view"].replace(
             "function submitMember",
             "const OLD = '账号在开户后不可改；如需换账号，请移除该员工后重新新增。'\n"
             "function submitMember")),
         ["M10"]),
        ("M11 套件收尾不再软删自建账号（残留会反噬候选池）",
         lambda t: dict(t, v63=t["v63"].replace(
             "soft_delete_accounts((admin_user, led_user, mem_user, mem2_user))", "0")),
         ["M11"]),
    ]
    bad = 0
    for name, mutate, expect in mutations:
        t2 = mutate(base)
        if t2 == base:
            print("[FAIL] %s：突变未生效（锚点文本已变，请同步本守卫）" % name)
            bad += 1
            continue
        fired = {c[0].split()[0] for c in checks(t2) if not c[1]}
        miss = [e for e in expect if e not in fired]
        if miss:
            print("[FAIL] %s：注入后未报红 %s（守卫失效）" % (name, miss))
            bad += 1
        else:
            print("[PASS] %s：真报红 %s" % (name, sorted(fired)))
    print("\n=== 自检 %d/%d 通过 ===" % (len(mutations) - bad, len(mutations)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
