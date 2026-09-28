# -*- coding: utf-8 -*-
"""V65「用户反馈 8 项问题」修复的静态守卫（防同类复发，无需启动服务）。

背景（2026-09-27 定位，见 docs/37）：
    用户反馈的 8 项问题里，多数不是"功能没做"，而是**展示与事实同源被破坏**的几种固定形态：

      A. **字段名失配**：前端读 `username` / `roleName` / `permName`，后端回吐的却是
         `org_member` 裸实体 / `sys_role.name` / `sys_permission.name` ⇒ 列恒空，
         而编辑守卫又拿这个空字段做必填校验 ⇒「员工完全无法编辑」。
      B. **能力有 API 无入口**：`/workers/{id}/visible-scope` 与专家「指定机构/部门/用户」
         选项都在，但模板里没有任何控件 ⇒ 能力事实上不可用（铁律 #4）。
      C. **作用域注入只兑现一半**：注入只认 `/tenant/` 前缀，`/org/*` 不吃 ⇒
         「选择机构后页面和数据没有随之改变」。
      D. **统计期由前端时钟推导**：`new Date()` 拼 `YYYY-MM`，与服务器时钟/时区一错就查到
         不存在的周期 ⇒ 空表 + 归因错误的提示。
      E. **同一件事两处呈现**：首页「待我处理 / 会话」与待办页、「我的数据」重复。

本守卫断言（每条都对应一处已修缺陷，回归即报红）：
    B1  AdminController.roles() 不得裸吐实体，必须回吐 roleName
    B2  AdminController.permissions() 必须回吐 permName
    B3  OrgTreeService.listMembers 的 items 必须经 memberViews 组装（含账号/部门名）
    B4  OrgTreeService 的员工视图必须带 username
    B5  ExpertConfigController.visible() 必须接收目标清单形参（不得退回「有归属即可见」）
    B6  调用 visible() 时必须一并传 getVisibleTargets()
    B7  OrgScopeStatsService 首页卡不得再出现「待我处理」/「会话」指标（与待办页、我的数据重复）
    F1  tenantScope.ts 必须存在声明式作用域表，且 /org/ ⇒ institutionId
    F2  拦截器必须剔除空的 period（周期只能由服务端裁决）
    F3  MainLayout 重挂载键必须含 currentInstitutionId
    F4  views 内不得出现「getFullYear() 与 getMonth() 同现」的周期推导
    F5  WorkersView 必须真正调用 setWorkerVisibleScope（不只是 import）
    F6  ExpertConfigView 必须为「指定机构/部门/用户」渲染目标选择器并提交 visibleTargets
    F7  OrgStructureView.submitMember 必须按新增/编辑分叉（编辑态不得强求账号）
    F8  MainLayout 的「租户管理」必须落在「租户与机构」组内且带 isPlatformAdmin 守卫
    F9  前端 SysRole/SysPermission 契约必须含 dataScope / permName

用法：
    python scripts/_check_v65_scope_and_field_guards.py            # 跑检查
    python scripts/_check_v65_scope_and_field_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")

ADMIN_CTRL = os.path.join(SERVER, "aioa-admin", "src", "main", "java", "cn", "aioa",
                          "admin", "controller", "AdminController.java")
ORG_TREE = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                        "org", "service", "OrgTreeService.java")
EXPERT_CTRL = os.path.join(SERVER, "aioa-resource", "src", "main", "java", "cn", "aioa",
                           "resource", "controller", "ExpertConfigController.java")
EXPERT_SETTINGS = os.path.join(SERVER, "aioa-resource", "src", "main", "java", "cn", "aioa",
                               "resource", "model", "ExpertSettings.java")
CATALOG_SVC = os.path.join(SERVER, "aioa-resource", "src", "main", "java", "cn", "aioa",
                           "resource", "service", "CatalogService.java")
ORG_STATS = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                         "org", "service", "OrgScopeStatsService.java")
TENANT_SCOPE = os.path.join(SHELL, "api", "tenantScope.ts")
MAIN_LAYOUT = os.path.join(SHELL, "layouts", "MainLayout.vue")
WORKERS_VIEW = os.path.join(SHELL, "views", "WorkersView.vue")
EXPERT_VIEW = os.path.join(SHELL, "views", "ExpertConfigView.vue")
ORG_VIEW = os.path.join(SHELL, "views", "OrgStructureView.vue")
RESOURCE_API = os.path.join(SHELL, "api", "resource.ts")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def checks(t):
    """t 是 {逻辑名: 文本} 的字典，返回 [(id, ok, detail)]。"""
    out = []

    admin = t["admin"]
    # ---- B1 角色必须回吐 roleName
    out.append((
        "B1 AdminController.roles 回吐 roleName",
        'm.put("roleName", r.getName())' in admin
        and "ApiResponse.ok(roleMapper.selectList(null))" not in admin,
        "缺失 roleName 映射，或仍在裸吐实体",
    ))
    # ---- B2 权限点必须回吐 permName
    out.append((
        "B2 AdminController.permissions 回吐 permName",
        'm.put("permName", p.getName())' in admin
        and "ApiResponse.ok(permissionMapper.selectList(null))" not in admin,
        "缺失 permName 映射，或仍在裸吐实体",
    ))

    org_tree = t["org_tree"]
    # ---- B3 员工列表必须经公共视图组装
    out.append((
        "B3 listMembers 的 items 经 memberViews 组装",
        'out.put("items", memberViews(rows))' in org_tree,
        "items 又回吐裸实体（账号 / 部门名列会再次恒空）",
    ))
    # ---- B4 员工视图必须带 username
    out.append((
        "B4 员工视图含 username",
        'o.put("username", user == null ? null : user.get("username"))' in org_tree,
        "视图缺 username 字段",
    ))

    expert = t["expert"]
    settings_txt = t["settings"]
    catalog = t["catalog"]
    # ---- B5 可见范围判定的实现必须只在一处（ExpertSettings.visibleTo），且按目标清单命中
    out.append((
        "B5 可见范围判定落在 ExpertSettings.visibleTo 且按清单命中",
        "public boolean visibleTo(cn.aioa.security.AuthUser user)" in settings_txt
        and 'case "INSTITUTION"' in settings_txt
        and "t.contains(user.getInstitutionId())" in settings_txt
        and "return false;" in settings_txt.split('case "USER"', 1)[-1][:400],
        "判定实现不在 ExpertSettings，或未按清单命中 / 未知枚举未拒绝",
    ))
    # ---- B6 用户端目录必须用同一判据（否则管理端配的范围在 H5 完全失效）
    out.append((
        "B6 CatalogService.availableExperts 应用同一可见范围判据",
        "settings().visibleTo(user)" in catalog and "PermissionCatalog.EXPERT_MANAGE" in catalog,
        "用户端目录不判可见范围 ⇒ 管理端「指定机构/部门/用户可见」配了等于没配",
    ))
    # ---- B8 管理端不得再私自实现一份 visible() 语义（铁律 #1：同一决策点只在一处判定）
    out.append((
        "B8 管理端 visible() 仅为转发、不再自行实现",
        "settings.visibleTo(user)" in expert
        and 'switch (scope.toUpperCase())' not in expert,
        "管理端又复制了一份作用域 switch ⇒ 两处判定迟早打架",
    ))
    out.append((
        "B6b 调用 visible() 时传解析后的设置对象",
        "visible(rc.settings(), user)" in expert,
        "调用点未传设置对象（目标清单会再次丢失）",
    ))

    stats = t["stats"]
    # ---- B7 首页卡不得再放「待我处理」/「会话」（与待办页、我的数据重复）
    # 只看真正下发的指标 label（metric("key", "label", …)），不看注释 —— 注释里为了说明历史
    # 一定会提到这两个词，把它们也算进来会让守卫变成「禁止解释」，反而没人敢写注释。
    metric_labels = re.findall(r'metric\(\s*"[^"]+"\s*,\s*"([^"]+)"', stats)
    bad_labels = [s for s in metric_labels if "待我处理" in s or "会话" in s]
    out.append((
        "B7 首页本组织数据卡不含「待我处理 / 本月会话」",
        not bad_labels,
        "重新出现：%s（待办归待办页、会话只留「我的数据」一处）" % bad_labels,
    ))

    scope = t["tenant_scope"]
    # ---- F1 声明式作用域表
    out.append((
        "F1 声明式作用域表含 /org/ => institutionId",
        "SCOPE_PARAMS" in scope and "{ prefix: '/org/', param: 'institutionId' }" in scope,
        "缺少 /org/ 的作用域声明（「选择机构后随之改变」会再次失效）",
    ))
    # ---- F2 空 period 必须剔除
    out.append((
        "F2 拦截器剔除空 period",
        "k === 'period'" in scope and "delete params[k]" in scope,
        "空 period 会被下发给后端，查到不存在的周期",
    ))

    layout = t["layout"]
    # ---- F3 重挂载键含机构
    out.append((
        "F3 重挂载键含 currentInstitutionId",
        "${route.path}@${currentTenantId ?? 0}@${currentInstitutionId ?? 0}" in layout,
        "键只含租户 ⇒ 同租户内换机构不会重新取数",
    ))
    # ---- F8 「租户管理」归位且带守卫
    tenant_group = layout.split('index="tenant"', 1)[-1].split('index="org"', 1)[0] \
        if 'index="tenant"' in layout else ""
    out.append((
        "F8 租户管理在「租户与机构」组内且带 isPlatformAdmin 守卫",
        'v-if="isPlatformAdmin" index="/tenants"' in tenant_group,
        "要么没归位，要么缺子项守卫（租户管理员会看到点不开的入口）",
    ))

    # ---- F4 views 内不得出现周期推导（getFullYear 与 getMonth 同现）
    view_texts = {os.path.basename(p): _read(p)
                  for p in glob.glob(os.path.join(SHELL, "views", "*.vue"))}
    # 自检注入一份「合成视图」，让这条断言也可被突变验证（否则它只能靠真实改文件才能验红）
    if t.get("synthetic_view"):
        view_texts["__synthetic__.vue"] = t["synthetic_view"]
    offenders = [name for name, s in view_texts.items()
                 if "getFullYear()" in s and "getMonth()" in s]
    out.append((
        "F4 views 无本地周期推导",
        not offenders,
        "仍在用本机时钟拼统计期：%s" % offenders,
    ))

    workers = t["workers"]
    calls = [ln for ln in workers.splitlines()
             if "setWorkerVisibleScope(" in ln and not ln.strip().startswith(("import", "setWorkerVisibleScope,"))]
    # ---- F5 数字员工可见范围必须有真实调用
    out.append((
        "F5 WorkersView 真调用 setWorkerVisibleScope",
        len(calls) >= 1,
        "只 import 不调用（「有 API 无入口」复发）",
    ))

    expert_view = t["expert_view"]
    # ---- F6 专家可见范围目标选择器 + 提交
    out.append((
        "F6 专家配置页有目标选择器且提交 visibleTargets",
        "TARGET_SCOPES" in expert_view and "v-model=\"form.visibleTargets\"" in expert_view
        and "visibleTargets: targetScope.value ? form.visibleTargets || [] : []" in expert_view,
        "下拉有「指定机构/部门/用户」却没有目标选择器（配了等于没配）",
    ))

    org_view = t["org_view"]
    # ---- F7 员工保存守卫必须按新增/编辑分叉
    out.append((
        "F7 submitMember 按新增/编辑分叉",
        "const isEdit = !!memberForm.value.id" in org_view
        and "if (!isEdit && !memberForm.value.username)" in org_view,
        "编辑态仍强求 username（而列表行没有该字段）⇒ 守卫恒真、员工存不下去",
    ))

    res = t["resource"]
    # ---- F9 前端契约字段
    out.append((
        "F9 SysRole/SysPermission 契约含 dataScope / permName",
        "dataScope?: string" in res and "permName: string" in res,
        "类型契约缺字段（页面回填会再次拿到 undefined）",
    ))

    return out


def _load():
    return {
        "admin": _read(ADMIN_CTRL),
        "org_tree": _read(ORG_TREE),
        "expert": _read(EXPERT_CTRL),
        "settings": _read(EXPERT_SETTINGS),
        "catalog": _read(CATALOG_SVC),
        "stats": _read(ORG_STATS),
        "tenant_scope": _read(TENANT_SCOPE),
        "layout": _read(MAIN_LAYOUT),
        "workers": _read(WORKERS_VIEW),
        "expert_view": _read(EXPERT_VIEW),
        "org_view": _read(ORG_VIEW),
        "resource": _read(RESOURCE_API),
    }


def run():
    res = checks(_load())
    bad = [r for r in res if not r[1]]
    for rid, ok, detail in res:
        print(("[PASS] " if ok else "[FAIL] ") + rid + ("" if ok else "  —— " + str(detail)))
    print("\n=== %d/%d 通过 ===" % (len(res) - len(bad), len(res)))
    return 1 if bad else 0


def selftest():
    """注入突变，必须真报红 —— 否则守卫是"恒真断言"，比没断言更危险。"""
    base = _load()
    mutations = [
        ("B1 去掉 roleName 映射",
         lambda t: dict(t, admin=t["admin"].replace('m.put("roleName", r.getName());', "")),
         ["B1"]),
        ("B2 去掉 permName 映射",
         lambda t: dict(t, admin=t["admin"].replace('m.put("permName", p.getName());', "")),
         ["B2"]),
        ("B3 items 回吐裸实体",
         lambda t: dict(t, org_tree=t["org_tree"].replace(
             'out.put("items", memberViews(rows))', 'out.put("items", rows)')),
         ["B3"]),
        ("B4 视图去掉 username",
         lambda t: dict(t, org_tree=t["org_tree"].replace(
             'o.put("username", user == null ? null : user.get("username"));', "")),
         ["B4"]),
        ("B5 判定实现挪出 ExpertSettings（退回「只判有无归属」）",
         lambda t: dict(t, settings=t["settings"].replace(
             "public boolean visibleTo(cn.aioa.security.AuthUser user)",
             "public boolean visibleToLegacy(cn.aioa.security.AuthUser user)")),
         ["B5"]),
        ("B5b INSTITUTION 退回「凡有机构归属者可见」",
         lambda t: dict(t, settings=t["settings"].replace(
             "&& t.contains(user.getInstitutionId())", "")),
         ["B5"]),
        ("B6 用户端目录去掉可见范围判据",
         lambda t: dict(t, catalog=t["catalog"].replace(
             "settings().visibleTo(user)", "true")),
         ["B6"]),
        ("B8 管理端又自行实现一份作用域 switch",
         lambda t: dict(t, expert=t["expert"].replace(
             "return settings.visibleTo(user);",
             'switch (settings.getVisibleScope().toUpperCase()) { default: return true; }')),
         ["B8"]),
        ("B7 首页卡塞回「待我处理」",
         lambda t: dict(t, stats=t["stats"].replace(
             "public Map<String, Object> orgScope() {",
             'public Map<String, Object> orgScope() {\n'
             '        if (true) { return metric("myTodos", "待我处理", 0, "件"); }')),
         ["B7"]),
        ("F1 去掉 /org/ 作用域声明",
         lambda t: dict(t, tenant_scope=t["tenant_scope"].replace(
             "{ prefix: '/org/', param: 'institutionId' }", "")),
         ["F1"]),
        ("F2 去掉空 period 剔除",
         lambda t: dict(t, tenant_scope=t["tenant_scope"].replace(
             "if (k === 'period' && (v == null || v === '')) {", "if (false) {")),
         ["F2"]),
        ("F3 重挂载键退回只带租户",
         lambda t: dict(t, layout=t["layout"].replace(
             "${route.path}@${currentTenantId ?? 0}@${currentInstitutionId ?? 0}",
             "${route.path}@${currentTenantId ?? 0}")),
         ["F3"]),
        ("F4 重新在视图里用本机时钟拼周期",
         lambda t: dict(t, synthetic_view=(
             "const d = new Date()\n"
             "const period = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0')\n")),
         ["F4"]),
        ("F5 WorkersView 只 import 不调用",
         lambda t: dict(t, workers="\n".join(
             ln for ln in t["workers"].splitlines() if "setWorkerVisibleScope(" not in ln
             or ln.strip().startswith(("import", "setWorkerVisibleScope,")))),
         ["F5"]),
        ("F6 去掉目标选择器",
         lambda t: dict(t, expert_view=t["expert_view"].replace(
             'v-model="form.visibleTargets"', 'v-model="form.noSuchField"')),
         ["F6"]),
        ("F7 submitMember 退回恒真守卫",
         lambda t: dict(t, org_view=t["org_view"].replace(
             "if (!isEdit && !memberForm.value.username)", "if (!memberForm.value.username)")),
         ["F7"]),
        ("F8 去掉「租户管理」子项守卫",
         lambda t: dict(t, layout=t["layout"].replace(
             'v-if="isPlatformAdmin" index="/tenants"', 'index="/tenants"')),
         ["F8"]),
        ("F9 去掉 dataScope 契约",
         lambda t: dict(t, resource=t["resource"].replace("dataScope?: string", "")),
         ["F9"]),
    ]
    bad = 0
    for name, mutate, expect in mutations:
        t2 = mutate(base)
        if t2 == base:
            print("[SKIP] %s：突变未生效（锚点文本可能已变，请同步本守卫）" % name)
            continue
        fired = {c[0].split()[0] for c in checks(t2) if not c[1]}
        if not expect:
            print("[INFO] %s：未约定期望，实际报红 %s" % (name, sorted(fired) or "无"))
            continue
        miss = [e for e in expect if e not in fired]
        if miss:
            print("[FAIL] %s：注入后未报红 %s（守卫失效）" % (name, miss))
            bad += 1
        else:
            print("[PASS] %s：真报红 %s" % (name, sorted(fired)))
    checked = len([1 for m in mutations if m[2]])
    print("\n=== 自检 %d/%d 通过 ===" % (checked - bad, checked))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
