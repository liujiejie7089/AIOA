# -*- coding: utf-8 -*-
"""「租户域名 + 平台调额度」能力 与「子租户已移除」的静态守卫（防同类复发，无需启动服务）。

历史（重要，别只看代码不看这段）：
    2026-09-27（docs/38 批次 A）落地了三件事：⑥ 租户登录域名、⑩ 子租户（租户层级）、
    ③ 平台管理员「事后调整某租户资源上限」。三件事写在同一个批次、同一版迁移（V66）里。
    2026-09-28（用户决定）：**去掉子租户这个功能**。
    ⇒ 只回退 ⑩：删 SubTenantController / SubTenantService / SubTenantView / api/subTenant.ts、
      删 OrgStatMapper 的子租户查询、删 SysTenant 的 parentId/level、V68 删 parent_id/level 列。
    ⇒ **不回退** ⑥ 域名与 ③ 调额度 —— 用户没有要求去掉它们，且与子租户没有依赖关系。
      这一批最容易犯的错，就是在拆 `api/subTenant.ts` 时把 `updateTenantQuota` 一起删掉，
      于是平台**静默失去**「事后调整租户资源上限」的入口（铁律 #4：能力无入口 = 事实上不可用）。

两类断言（本守卫的全部价值）：
    K* —— 保留能力必须还在（被误删 = 能力丢失）。多数是「唯一入口」类断言：
        K1 平台调额度：仅平台管理员 + forced forbidden + 走 QuotaService.upsertPool + 回执含 before/after
        K2 域名归一化/格式校验只有 TenantDomain 一处实现（两处 = 「平台不接受、别处接受」同一域名）
        K3 V66 迁移仍保留 domain 列与 uk_tenant_domain（别把域名一起回退掉）
        K4 前端入口齐备：调额度从 @/api/tenantQuota 调、域名控件在、api 走 unwrap 校验 code
        K5 平台停用租户仍同步冻结该租户账号（生效态与展示同源；这条是子租户的同族纪律，必须留下）
    R* —— 子租户必须**真的不在**（被动复活 = 能力边界无声变化，这类改动不会有编译错误）：
        R1 后端产物已删除（两个文件不存在，且全仓 Java 源码无 SubTenant 标识符）
        R2 SysTenant 实体不再映射 parentId/level（列已在 V68 删除；实体若不删，查询会带出
           不存在的列 ⇒ 平台租户列表直接 500）
        R3 OrgStatMapper 不再有任何读 parent_id 的查询，且平台调额度依赖的 selectTenantWithHierarchy 还在
        R4 TenantController 不再回吐 level/parentId/subTenantCount（回吐恒 null 的字段 = 展示与事实不同源）
        R5 V68 迁移真的删掉 parent_id / level / idx_tenant_parent，且**不碰** domain
        R6 前端入口已清除（无视图/无 api 文件；router、菜单、权限常量均无痕）

用法：
    python scripts/_check_v66_tenant_guards.py            # 跑检查
    python scripts/_check_v66_tenant_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
MIGRATION = os.path.join(SERVER, "aioa-boot", "src", "main", "resources", "db", "migration")

# ---- 已移除产物（R1：这两个文件必须不存在）
SUB_SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                       "org", "service", "SubTenantService.java")
SUB_CTRL = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                        "org", "controller", "SubTenantController.java")
# ---- 已移除的前端产物（R6）
SUB_API = os.path.join(SHELL, "api", "subTenant.ts")
SUB_VIEW = os.path.join(SHELL, "views", "SubTenantView.vue")

# ---- 保留能力的实现点
QUOTA_CTRL = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                          "org", "controller", "PlatformTenantQuotaController.java")
TENANT_CTRL = os.path.join(SERVER, "aioa-admin", "src", "main", "java", "cn", "aioa",
                           "admin", "controller", "TenantController.java")
TENANT_DOMAIN = os.path.join(SERVER, "aioa-common", "src", "main", "java", "cn", "aioa",
                             "common", "util", "TenantDomain.java")
SYS_TENANT = os.path.join(SERVER, "aioa-admin", "src", "main", "java", "cn", "aioa",
                          "admin", "entity", "SysTenant.java")
ORG_STAT_MAPPER = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                               "org", "mapper", "OrgStatMapper.java")

PERMISSIONS = os.path.join(SHELL, "constants", "permissions.ts")
ROUTER = os.path.join(SHELL, "router", "index.ts")
LAYOUT = os.path.join(SHELL, "layouts", "MainLayout.vue")
TENANT_VIEW = os.path.join(SHELL, "views", "TenantAdminView.vue")
TENANT_QUOTA_API = os.path.join(SHELL, "api", "tenantQuota.ts")

# 域名 label 正则的**唯一**合法归属（K2：换地方就是复制了第二份判定）
DOMAIN_LABEL_REGEX = "[a-z0-9]([a-z0-9-]"

# 子租户专属的 mapper 方法名（R3：这些名字重新出现 = 能力在被重建）
SUB_MAPPER_METHODS = [
    "selectSubTenants", "countSubTenants", "sumSubTenantPools", "insertTenant",
    "selfBindTenant", "countTenantByCode", "selectTenantByCode", "countTenantByDomain",
    "selectTenantAdmin", "countUsersOfTenant", "updateTenantUsersStatus",
    "selectPoolTotals", "sumOrgQuota",
]

MISSING = "\x00"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_or_missing(path):
    """文件不存在返回哨兵；R1/R6 正是靠这个哨兵断言「产物已删」。"""
    return _read(path) if os.path.exists(path) else MISSING


def _method_body(src, signature):
    """截取单个方法体（签名 → 下一个与类成员同缩进的 `}`）。

    **为什么必须限定在方法内**：K6 要断言「update() 不许用 updateById」，而同一个类里的
    changeStatus() 合法地用了 updateById（它改的是 status，不是可清空的列）。
    不限定范围 ⇒ 断言变成「别的同类方法有这个调用就报红」，那是假红，也会逼后人删掉正确代码。
    """
    i = src.find(signature)
    if i < 0:
        return MISSING
    j = src.find("\n    }", i)
    return src[i:j] if j > 0 else src[i:]


def _strip_java_comments(src):
    """去掉 Java 注释再计数。

    **为什么必须去注释**：R3 断言「OrgStatMapper 里不得再出现 parent_id」，而说明历史的注释
    里一定会写「V68 已删除 parent_id / level」—— 若连注释一起数，这条断言就变成
    「谁解释谁报红」，那是把守卫变成禁止解释（本仓已踩过同型坑：V65 守卫的 B7 指标 label
    必须只看真正下发的 label，不看注释）。
    """
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _ts_code_body(src):
    """TS 源码去掉 import / 注释，只留「真的写了什么」。

    **为什么必须去 import**：K4 断言「api 走 unwrap 校验 code」。若只看全文，
    `import { http, unwrap } from './index'` 这一行就足以让断言恒真 ——
    把调用改成 `r.data.data`（失败信封被当业务数据，pitfalls #18）时守卫**不会报红**。
    实测：本守卫首版就在这条上被自检抓出恒真（K4b 未报红）。
    """
    src = re.sub(r"^\s*import\s.*$", "", src, flags=re.M)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def checks(t):
    """t 是 {逻辑名: 文本} 的字典，返回 [(id, ok, detail)]。"""
    out = []

    quota_ctrl = t["quota_ctrl"]
    tenant_ctrl = t["tenant_ctrl"]
    domain_util = t["tenant_domain"]
    sys_tenant = t["sys_tenant"]
    mapper = t["org_stat_mapper"]
    tenant_view = t["tenant_view"]
    quota_api = t["tenant_quota_api"]

    # ==================================================================== K 保留能力
    # ---- K1 平台调额度端点：必须平台管理员 + 回执带前后值
    out.append((
        "K1 平台调额度端点仅平台管理员且回执含 before/after",
        "PermissionCatalog.isPlatformAdmin(actor)" in quota_ctrl
        and "BizException.forbidden(" in quota_ctrl
        and "quotaService.upsertPool(tenantId, actor, req)" in quota_ctrl
        and 'out.put("before", before)' in quota_ctrl
        and 'out.put("after", after)' in quota_ctrl,
        "权限判定缺失 / 未走 QuotaService / 回执缺前后值（前端无法展示 调整前→调整后）",
    ))

    # ---- K2 域名归一化只有一处实现（删掉租户端调用方后，调用点只剩平台侧）
    owners = [name for name, src in t["java_blobs"] if DOMAIN_LABEL_REGEX in src]
    foreign = [n for n in owners if n != "TenantDomain.java"]
    out.append((
        "K2 域名归一化/格式校验只有 TenantDomain 一处",
        owners == ["TenantDomain.java"] and not foreign
        and "public static String normalize(String raw)" in domain_util
        and "public static boolean isValid(String normalized)" in domain_util
        and "cn.aioa.common.util.TenantDomain.normalize(" in tenant_ctrl
        and "cn.aioa.common.util.TenantDomain.isValid(" in tenant_ctrl,
        "域名判定出现了第二份实现：%s" % (foreign or "（或平台侧绕开了 TenantDomain）"),
    ))

    # ---- K3 迁移：域名列与唯一键必须还在（别把保留能力一起回退掉）
    mig66 = t["mig_v66"]
    out.append((
        "K3 V66 迁移仍保留 domain 列 + uk_tenant_domain",
        "domain" in mig66 and "uk_tenant_domain" in mig66,
        "域名列/唯一键被删 ⇒ 「租户登录域名」在库层失去兜底（用户并未要求去掉这条能力）",
    ))

    # ---- K4 前端入口：调额度 + 域名控件都在，且 api 走 unwrap
    quota_api_code = _ts_code_body(quota_api)
    out.append((
        "K4 前端：调额度入口与域名控件齐备（拆分 api 时未被误删）",
        "from '@/api/tenantQuota'" in tenant_view
        and "updateTenantQuota(" in tenant_view
        and 'v-model="form.domain"' in tenant_view
        and "unwrap" in quota_api_code
        and "unwrap<QuotaBeforeAfter>(r)" in quota_api_code,
        "缺件：%s" % [n for n, v in (
            ("调额度从 @/api/tenantQuota 引入", "from '@/api/tenantQuota'" in tenant_view),
            ("真调用 updateTenantQuota", "updateTenantQuota(" in tenant_view),
            ("域名编辑控件仍在", 'v-model="form.domain"' in tenant_view),
            ("api 真用 unwrap 校验 code", "unwrap<QuotaBeforeAfter>(r)" in quota_api_code),
        ) if not v],
    ))

    # ---- K5 停用租户必须同步冻账号（与子租户同族的生效态纪律，子租户删了它必须留下）
    out.append((
        "K5 平台停用租户仍同步冻结其账号",
        'jdbc.update("UPDATE sys_user SET status = ? WHERE tenant_id = ? AND deleted_at IS NULL"'
        in tenant_ctrl,
        "只改租户状态不冻账号 ⇒ 停用后仍持有有效令牌（生效态与展示不同源）",
    ))

    # ---- K6 清空域名必须真的落库（updateById 的 NOT_NULL 策略会把「清空」吞掉）
    # 断言必须限定在 update() 方法体内：同类里 changeStatus() 也调 updateById（那是合法的，
    # 它改的是 status 不是可清空的列）。不限定范围 ⇒ 「别的方法有这个调用」就报红，是假红。
    upd = _method_body(tenant_ctrl, "public ApiResponse<SysTenant> update(@PathVariable Long id")
    out.append((
        "K6 编辑租户用显式 set 写域名为 NULL（否则「清空域名」是假成功）",
        upd != MISSING
        and "LambdaUpdateWrapper<SysTenant> w = new LambdaUpdateWrapper<SysTenant>()" in upd
        and "w.set(SysTenant::getDomain," in upd
        and "tenantMapper.update(null, w);" in upd
        and "updateById(" not in upd,
        "用了 updateById ⇒ MyBatis-Plus 默认 NOT_NULL 策略不把 null 字段写进 SET，"
        "接口回 200 + domain:null 但库里没变（用户在界面上清空域名会「保存成功」却清不掉）",
    ))

    # ---- K7 调额度弹窗必须预填席位当前值（硬写 0 = 一点保存就把席位静默清零）
    out.append((
        "K7 调额度弹窗预填席位当前值（否则保存即把租户席位清零）",
        "expertSeats: row.expertSeats ?? 0" in tenant_view
        and "skillSeats: row.skillSeats ?? 0" in tenant_view
        and "expertSeats?: number" in tenant_view,
        "弹窗席位写死 0 ⇒ 打开看到 0、点保存把真实席位清零；upsertPool 对席位没有「不得低于已用」兜底，"
        "数据直接丢且无提示（后端 list 早就回吐了这四个字段，注释写明就是给弹窗预填用的）",
    ))

    # ==================================================================== R 移除已落地
    # ---- R1 后端产物已删除
    # java_all 由 java_blobs 派生（单一来源）：R1 的「全仓无 SubTenant」与 K2 的「正则只有一处归属」
    # 必须看同一份文本，否则注入突变时两者会各自为政、出现「改了 A 却断言 B」的假红/假绿。
    java_all = "\n".join(src for _, src in t["java_blobs"])
    out.append((
        "R1 后端已无子租户产物（文件不存在 + 全仓 Java 无 SubTenant 标识符）",
        t["sub_svc"] == MISSING and t["sub_ctrl"] == MISSING and "SubTenant" not in java_all,
        "子租户后端又被建回来了（子租户能力已按用户决定移除，不该复活）",
    ))

    # ---- R2 SysTenant 实体不再映射层级列（列已删，实体残留 ⇒ 查询直接 500）
    out.append((
        "R2 SysTenant 实体不再映射 parentId/level（且仍是含 domain 的正常实体）",
        "parentId" not in sys_tenant and "level" not in sys_tenant
        and "private String domain;" in sys_tenant,
        "实体仍在映射 parent_id/level ⇒ 列已被 V68 删除，MyBatis-Plus 会带出不存在的列（列表页 500）",
    ))

    # ---- R3 OrgStatMapper 不再有子租户查询；平台调额度依赖的查询保留
    leftovers = [m for m in SUB_MAPPER_METHODS if m in mapper]
    out.append((
        "R3 OrgStatMapper 无子租户查询（parent_id 与子租户方法名均绝迹）",
        "parent_id" not in mapper and not leftovers
        and "selectTenantWithHierarchy" in mapper and "domain" in mapper,
        "残留：%s（parent_id 字面量是否出现=%s）；或平台调额度依赖的 selectTenantWithHierarchy 被误删"
        % (leftovers, "parent_id" in mapper),
    ))

    # ---- R4 TenantController 不再回吐层级字段
    out.append((
        "R4 TenantController 不再回吐 level/parentId/subTenantCount",
        "parent_id" not in tenant_ctrl and "subTenantCount" not in tenant_ctrl
        and "getLevel()" not in tenant_ctrl and "getParentId()" not in tenant_ctrl
        and 'm.put("domain", t.getDomain());' in tenant_ctrl,
        "仍在回吐被删列的字段 ⇒ 要么查不存在的列报错，要么给前端一个恒 null 的假字段（铁律 #1）",
    ))

    # ---- R5 V68 迁移真的删列，且不碰 domain
    mig68 = t["mig_v68"]
    out.append((
        "R5 V68 迁移删掉 parent_id/level/idx_tenant_parent 且不碰 domain",
        mig68 != MISSING
        and "DROP INDEX idx_tenant_parent" in mig68
        and "DROP COLUMN parent_id" in mig68
        and "DROP COLUMN level" in mig68
        and "DROP COLUMN domain" not in mig68
        and "DROP INDEX uk_tenant_domain" not in mig68,
        "V68 缺件或越界：%s" % [n for n, v in (
            ("文件存在", mig68 != MISSING),
            ("删 idx_tenant_parent", "DROP INDEX idx_tenant_parent" in mig68),
            ("删 parent_id", "DROP COLUMN parent_id" in mig68),
            ("删 level", "DROP COLUMN level" in mig68),
            ("未误删 domain", "DROP COLUMN domain" not in mig68),
            ("未误删域名唯一键", "DROP INDEX uk_tenant_domain" not in mig68),
        ) if not v],
    ))

    # ---- R6 前端入口已清除
    perms = t["permissions"]
    router = t["router"]
    layout = t["layout"]
    out.append((
        "R6 前端子租户入口已清除（视图/api/路由/菜单/常量）",
        t["sub_api"] == MISSING and t["sub_view"] == MISSING
        and "sub-tenants" not in router and "sub-tenants" not in layout
        and "SUB_TENANT_ROLES" not in perms and "SUB_TENANT_ROLES" not in router,
        "残留入口：%s" % [n for n, v in (
            ("api/subTenant.ts 已删", t["sub_api"] == MISSING),
            ("SubTenantView.vue 已删", t["sub_view"] == MISSING),
            ("路由无 sub-tenants", "sub-tenants" not in router),
            ("菜单无 /sub-tenants", "sub-tenants" not in layout),
            ("常量 SUB_TENANT_ROLES 已删", "SUB_TENANT_ROLES" not in perms
             and "SUB_TENANT_ROLES" not in router),
        ) if not v],
    ))

    return out


def load():
    mig66 = glob.glob(os.path.join(MIGRATION, "V66*.sql"))
    mig68 = glob.glob(os.path.join(MIGRATION, "V68*.sql"))
    java_files = [p for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True)
                  if os.sep + "target" + os.sep not in p]
    # Java 文本一律去注释后再断言：注释里为了说明纪律必然复述这些关键字（见 _strip_java_comments）。
    return {
        "quota_ctrl": _strip_java_comments(_read(QUOTA_CTRL)),
        "tenant_ctrl": _strip_java_comments(_read(TENANT_CTRL)),
        "tenant_domain": _strip_java_comments(_read(TENANT_DOMAIN)),
        "sys_tenant": _strip_java_comments(_read(SYS_TENANT)),
        "org_stat_mapper": _strip_java_comments(_read(ORG_STAT_MAPPER)),
        # (basename, 去注释正文) 列表 —— 保住「哪个文件说了什么」，同名文件不会互相淹没
        "java_blobs": [(os.path.basename(p), _strip_java_comments(_read(p))) for p in java_files],
        "mig_v66": _read(mig66[0]) if mig66 else MISSING,
        "mig_v68": _read(mig68[0]) if mig68 else MISSING,
        "permissions": _read(PERMISSIONS),
        "router": _read(ROUTER),
        "layout": _read(LAYOUT),
        "tenant_view": _read(TENANT_VIEW),
        "tenant_quota_api": _read_or_missing(TENANT_QUOTA_API),
        "sub_svc": _read_or_missing(SUB_SVC),
        "sub_ctrl": _read_or_missing(SUB_CTRL),
        "sub_api": _read_or_missing(SUB_API),
        "sub_view": _read_or_missing(SUB_VIEW),
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
    """注入突变，要求对应断言**必须真报红** —— 否则这些断言恒真（比没断言更危险，铁律 #7）。"""
    base = load()
    mutations = [
        # ---------------- K 类：破坏保留能力，必须报红
        ("K1 平台调额度去掉权限判定",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             "if (!PermissionCatalog.isPlatformAdmin(actor)) {", "if (false) {")),
         ["K1"]),
        ("K1b 平台调额度自行写池（不走 QuotaService）",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             "quotaService.upsertPool(tenantId, actor, req)",
             "statMapper.selectTenantWithHierarchy(tenantId)")),
         ["K1"]),
        ("K1c 回执丢掉 before（前端展示不了对照）",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             'out.put("before", before)', 'out.put("before2", before)')),
         ["K1"]),
        ("K2 域名判定复制第二份（在别的 java 里再写一遍正则）",
         lambda t: dict(t, java_blobs=t["java_blobs"] + [(
             "FakeTenantCtrl.java",
             'public class FakeTenantCtrl { Pattern P = Pattern.compile("'
             + DOMAIN_LABEL_REGEX + ']*[a-z0-9])?(\\\\.[a-z0-9-]+)+$"); }')]),
         ["K2"]),
        ("K3 把域名列一起回退掉（V66 里删除 domain）",
         lambda t: dict(t, mig_v66=t["mig_v66"].replace("domain", "x")),
         ["K3"]),
        ("K4 拆 api 时误删调额度入口",
         lambda t: dict(t, tenant_view="\n".join(
             ln for ln in t["tenant_view"].splitlines() if "updateTenantQuota(" not in ln)),
         ["K4"]),
        ("K4b 调额度 api 绕开 unwrap（失败信封当数据）",
         lambda t: dict(t, tenant_quota_api=t["tenant_quota_api"].replace(
             "unwrap<QuotaBeforeAfter>(r)", "r.data.data")),
         ["K4"]),
        ("K4c 拆分后 import 忘了改（仍指向已删的 api/subTenant）",
         lambda t: dict(t, tenant_view=t["tenant_view"].replace(
             "from '@/api/tenantQuota'", "from '@/api/subTenant'")),
         ["K4"]),
        ("K5 停用租户不再冻账号",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             'jdbc.update("UPDATE sys_user SET status = ? WHERE tenant_id = ? AND deleted_at IS NULL"',
             'jdbc.update("SELECT 1 WHERE tenant_id = ? AND deleted_at IS NULL"')),
         ["K5"]),
        ("K6 编辑租户退回 updateById（清空域名会被 NOT_NULL 策略吞掉）",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             "tenantMapper.update(null, w);", "tenantMapper.updateById(t);")),
         ["K6"]),
        ("K6b 域名不再走显式 set",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             "            w.set(SysTenant::getDomain, domainOf(body.get(\"domain\"), id));",
             "            t.setDomain(domainOf(body.get(\"domain\"), id));")),
         ["K6"]),
        ("K7 调额度弹窗席位退回硬写 0",
         lambda t: dict(t, tenant_view=t["tenant_view"].replace(
             "expertSeats: row.expertSeats ?? 0", "expertSeats: 0")),
         ["K7"]),
        ("K7b skillSeats 退回硬写 0",
         lambda t: dict(t, tenant_view=t["tenant_view"].replace(
             "skillSeats: row.skillSeats ?? 0", "skillSeats: 0")),
         ["K7"]),
        # ---------------- R 类：让已移除的东西复活，必须报红
        ("R1a 子租户 Service 复活（文件又在了）",
         lambda t: dict(t, sub_svc="public class SubTenantService { }"),
         ["R1"]),
        ("R1b 别处又冒出 SubTenant 标识符",
         lambda t: dict(t, java_blobs=t["java_blobs"]
                        + [("SomeController.java", "class SomeController extends SubTenantBase {}")]),
         ["R1"]),
        ("R1c 子租户 Controller 复活",
         lambda t: dict(t, sub_ctrl="public class SubTenantController { }"),
         ["R1"]),
        ("R2 实体又映射 parentId（列已删 ⇒ 查询 500）",
         lambda t: dict(t, sys_tenant=t["sys_tenant"].replace(
             "private String domain;", "private Long parentId;\n    private String domain;")),
         ["R2"]),
        ("R2b 实体又映射 level",
         lambda t: dict(t, sys_tenant=t["sys_tenant"].replace(
             "private String domain;", "private Integer level;\n    private String domain;")),
         ["R2"]),
        ("R3 mapper 又出现 parent_id 查询",
         lambda t: dict(t, org_stat_mapper=t["org_stat_mapper"].replace(
             "Map<String, Object> selectTenantWithHierarchy(",
             '@Select("SELECT COUNT(*) FROM sys_tenant WHERE parent_id = #{p}")\n'
             "    long countSubTenants(@Param(\"p\") Long p);\n\n"
             "    Map<String, Object> selectTenantWithHierarchy(")),
         ["R3"]),
        ("R3b 误删平台调额度依赖的 selectTenantWithHierarchy",
         lambda t: dict(t, org_stat_mapper=t["org_stat_mapper"].replace(
             "Map<String, Object> selectTenantWithHierarchy(", "Map<String, Object> gone(")),
         ["R3"]),
        ("R4 列表又回吐 subTenantCount",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             'm.put("domain", t.getDomain());',
             'm.put("domain", t.getDomain());\n            m.put("subTenantCount", 0L);')),
         ["R4"]),
        ("R4b 列表又回吐 level",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             'm.put("domain", t.getDomain());',
             'm.put("domain", t.getDomain());\n            m.put("level", t.getLevel());')),
         ["R4"]),
        ("R5 删 V68 迁移（列留在库里）",
         lambda t: dict(t, mig_v68=MISSING),
         ["R5"]),
        ("R5b V68 漏删 level 列",
         lambda t: dict(t, mig_v68=t["mig_v68"].replace("ALTER TABLE sys_tenant DROP COLUMN level;", "")),
         ["R5"]),
        ("R5c V68 越界把 domain 也删了",
         lambda t: dict(t, mig_v68=t["mig_v68"] + "\nALTER TABLE sys_tenant DROP COLUMN domain;\n"),
         ["R5"]),
        ("R6 路由重新挂上子租户页",
         lambda t: dict(t, router=t["router"].replace(
             "path: 'tenants',", "path: 'sub-tenants',\n        path: 'tenants',")),
         ["R6"]),
        ("R6b 菜单又加回 /sub-tenants",
         lambda t: dict(t, layout=t["layout"].replace(
             '<el-menu-item index="/cost-alloc">',
             '<el-menu-item index="/sub-tenants">子租户</el-menu-item>\n'
             '            <el-menu-item index="/cost-alloc">')),
         ["R6"]),
        ("R6c 权限常量复活",
         lambda t: dict(t, permissions=t["permissions"]
                        + "\nexport const SUB_TENANT_ROLES: readonly string[] = []\n"),
         ["R6"]),
        ("R6d 前端 api 文件复活",
         lambda t: dict(t, sub_api="export function listSubTenants() {}\n"),
         ["R6"]),
    ]
    bad = 0
    for name, mutate, expect in mutations:
        t2 = mutate(base)
        if t2 == base:
            # ★ SKIP 必须计入失败：锚点漂移会让这条突变**静默失效**，
            #   而"没验过的突变"和"没断言"一样不可信（与 pitfalls #75 同族）。
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
    checked = len(mutations)
    print("\n=== 自检 %d/%d 通过 ===" % (checked - bad, checked))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
