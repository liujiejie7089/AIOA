# -*- coding: utf-8 -*-
"""「已注销机构退出运营面」+「组织与员工一级菜单」+「人员筛选」静态守卫（无需启动服务）。

背景（2026-09-29 用户报障）：
    以企业/租户管理侧**注销**（CLOSED）了机构之后，「人员管理 / 机构管理 / 入驻进度 / 资源授权」
    仍然都能看到它；在机构管理里点「申请删除」只得到「机构不存在或已停用」（实测报的是机构 id 162）。
    另有两项交互要求：人员管理要能筛选（不要全平铺）；菜单里「组织与员工」的二级子项要去掉。

定位结论（写清楚，后人别再走回头路）：
    · **注销 = 不可逆的法人档案终态**，它应当退出全部运营面，但档案行不删除 ——
      清理只有「删租户」的级联一条路（`_check_delete_guards.py` 的 D13/D15 已把这点钉死）。
      所以本次做的是「运营面默认排除 CLOSED + 显式 includeClosed 才看档案」，
      **不是**「把 CLOSED 变成可删/可达」——后者会直接破坏 D15。
    · 「申请删除」在已注销机构上必然 404（作用域解析对非 ACTIVE 机构一律 404），
      这是**设计**而非缺陷；正确处置是前端禁用该入口并说明路径，而不是给后端开例外。

    这类修复的共同点是：**改回去不会报任何错**，只是在某天又「还能看到它」。
    故必须用静态守卫把「默认排除」钉在唯一一处，并把"忘了加默认排除"变成一次报红。

本守卫断言：
    Z1  运营面规则只有一处权威：`InstitutionStatus.operational/sqlOperational`（aioa-common）
    Z2  五个运营面查询都调用了唯一的运营面过滤器（机构清单 / 入驻总览 / 资源授权 / 费用分摊 / 人员归属）
    Z3  默认口径是「排除」而非「包含」：服务端默认分支正确，且 Controller 的 includeClosed 默认值必须是 false
    Z4  前端不提供「已注销」筛选项、不得自建第二套状态过滤；「申请删除 / 注销」对 CLOSED 行禁用
    Z5  菜单：「组织与员工」是**一级项**（无 el-sub-menu index="org"），/admin 高亮归并到它
    Z6  人员管理筛选：四维筛选控件 + 选项来自后端 filterOptions（前端不自建枚举）
    Z7  D15 未被放开（回归钉）：作用域解析仍要求 ACTIVE，deleteMember 仍无 CLOSED 例外
    Z8  行为套件已入库、且自带「前提 / 构造夹具 / 负向自检」机件（否则它可能就是一组恒真断言）
    Z9  本地级联删除套件的档案断言显式传 includeClosed=true（`e2e_*.py` 不入库 ⇒ 不在本地时 skip）

★ 断言前必须剥离注释（本仓注释会复述关键字，按裸文本判定会变成"谁写注释谁报红"）。
用法：
    python scripts/_check_closed_institution_guards.py            # 跑检查
    python scripts/_check_closed_institution_guards.py --selftest # 自检：注入突变，必须真报红
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
SCRIPTS = os.path.join(ROOT, "scripts")


def _p(*parts):
    return os.path.join(*parts)


# 跳过项（不判失败，但必须打印出来 —— 静默跳过 = 无声失效）。典型场景：`e2e_*.py` 按仓库
# 约定不入库，所以「本地才有的套件」类断言在别的机器上无从检查，只能显式 skip。
SKIPS = []


STATUS = _p(SERVER, "aioa-common", "src", "main", "java", "cn", "aioa", "common", "org",
            "InstitutionStatus.java")
ENTITY = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "entity",
            "OrgInstitution.java")
INST_SVC = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "service",
              "InstitutionService.java")
ONB_SVC = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "service",
             "OnboardingService.java")
GRANT_SVC = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "service",
               "ResourceGrantService.java")
COST_SVC = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "service",
              "CostAllocService.java")
TENANT_CTRL = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "controller",
                 "TenantAdminController.java")
PERSONNEL = _p(SERVER, "aioa-admin", "src", "main", "java", "cn", "aioa", "admin", "service",
               "PersonnelService.java")
ORG_GUARD = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "support",
               "OrgGuard.java")
# deleteMember 不在 OrgGuard —— FR-B2（企业管理员不可直删）的判定长在 OrgTreeService 里。
# 首版 Z7 误拿 OrgGuard 取方法体 ⇒ 取到空串、该分支被静默跳过（恒真），靠自检才发现。
TREE_SVC = _p(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org", "service",
              "OrgTreeService.java")

INST_VIEW = _p(SHELL, "views", "InstitutionView.vue")
ADMIN_VIEW = _p(SHELL, "views", "AdminView.vue")
LAYOUT = _p(SHELL, "layouts", "MainLayout.vue")
API_RESOURCE = _p(SHELL, "api", "resource.ts")
CASCADE = _p(SCRIPTS, "e2e_cascade_delete.py")
# 行为套件。★ 命名规则：`e2e_*.py` 被 .gitignore 排除（本仓约定），**会入库的行为探针**
# 一律用 `verify_*` / `_check_*` / `_probe_*` / `admin_*` / `h5_*` 前缀。
# 首版把它叫 e2e_closed_institution_surfaces.py ⇒ 永远进不了仓库，等于「只在本地存在的验收」。
BEHAVIOR = _p(SCRIPTS, "verify_closed_institution_surfaces.py")

# 「默认排除」判定里最容易写反的两处（写反 = 修复完全无效，且不会有任何报错）
DEFAULT_GUARD = "if (!includeClosed && (status == null || status.isBlank()))"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def _method_body(src, signature):
    """按「签名起始 → 下一个同级方法」粗略切出方法体（够用即可，不做完整解析）。"""
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find("\n    public ", i + len(signature))
    return src[i:j if j > 0 else len(src)]


def _fn_block(src, marker, stop="): "):
    """切出 TS 函数签名块（从 marker 到返回类型前的 `): `）。

    用于把「参数是否声明了某字段」锚在该函数的**签名内**，而不是整个文件里搜字面量 ——
    后者会被同名的 interface / 注释 / 别处用法喂饱（Z6 首版就是这样：删掉 listPersonnel 的
    `scopeClass?: string` 后，`scopeClass` 仍出现在 PersonnelMember 定义里，断言照旧全绿）。
    """
    i = src.find(marker)
    if i < 0:
        return ""
    j = src.find(stop, i)
    return src[i:(j + len(stop)) if j > 0 else len(src)]


def checks(t):
    out = []
    inst_svc, onb, grant, cost = t["inst_svc"], t["onb"], t["grant"], t["cost"]
    ctrl, personnel, guard = t["ctrl"], t["personnel"], t["org_guard"]

    # ---- Z1 运营面规则唯一权威
    owners = [p for p, s in t["java_all"].items()
              if "public static String sqlOperational(" in s or "public static boolean operational(" in s]
    out.append((
        "Z1 运营面可见性规则只有一处权威（aioa-common 的 InstitutionStatus）",
        len(owners) == 1 and os.path.basename(owners[0]) == "InstitutionStatus.java"
        and "public static boolean operational(String status)" in t["status"]
        and "sqlOperational" in t["status"]
        and "excludeClosed" in t["entity"]
        and "isNull(OrgInstitution::getStatus)" in t["entity"]
        # 不能用裸 .ne(status, CLOSED)：SQL 三值逻辑会连 NULL 行一起排除（静默少展示）。
        # ★ 这条必须是**否定式**：只断言「有 isNull」挡不住「isNull 之外又加一句裸 ne」，
        #   而后者正是最像「顺手加固」的写法（首版只查 isNull，注入裸 ne 后照旧全绿）。
        and not re.search(r"w\s*\.\s*ne\s*\(\s*OrgInstitution::getStatus", t["entity"])
        and "STATUS_CLOSED" in t["entity"],
        "第二处实现：%s" % [os.path.basename(p) for p in owners if "InstitutionStatus.java" not in p],
    ))

    # ---- Z2 五个运营面查询都接了过滤器
    miss2 = []
    if "OrgInstitution.excludeClosed(w)" not in _method_body(inst_svc, "public List<Map<String, Object>> list("):
        miss2.append("机构清单 InstitutionService.list")
    if "OrgInstitution.excludeClosed(w)" not in onb:
        miss2.append("入驻总览 OnboardingService.overview")
    if "OrgInstitution.excludeClosed(instQuery)" not in _method_body(
            grant, "public List<Map<String, Object>> listGrants("):
        miss2.append("资源授权 ResourceGrantService.listGrants")
    cost_ops = _method_body(cost, "private List<OrgInstitution> operationalInstitutions(")
    if not cost_ops or "OrgInstitution.excludeClosed(w)" not in cost_ops:
        miss2.append("费用分摊 CostAllocService.operationalInstitutions")
    for m in ("public Map<String, Object> simulate(", "public Map<String, Object> generateBills(",
              "public List<Map<String, Object>> listBills(", "public Map<String, Object> reconcile("):
        if "operationalInstitution" not in _method_body(cost, m):
            miss2.append("费用分摊 %s 未走运营面机构" % m.split()[-1])
    if 'InstitutionStatus.sqlOperational("x")' not in personnel:
        miss2.append("人员归属 PersonnelService 未用权威 SQL 片段")
    out.append((
        "Z2 五个运营面查询（机构/入驻/授权/分摊/人员）都接上唯一的运营面过滤器",
        not miss2, "缺件：%s" % miss2,
    ))

    # ---- Z3 默认口径 = 排除（写反即修复无效）
    miss3 = []
    if DEFAULT_GUARD not in _method_body(inst_svc, "public List<Map<String, Object>> list("):
        miss3.append("InstitutionService.list 的默认排除分支缺失")
    seg = ctrl.split('@GetMapping("/institutions")', 1)[1][:600] if '/institutions"' in ctrl else ""
    if 'defaultValue = "false"' not in seg:
        miss3.append("TenantAdminController 的 includeClosed 默认值不是 false（必须默认隐藏）")
    if "includeClosed" not in seg:
        miss3.append("TenantAdminController 未暴露 includeClosed 档案开关")
    out.append((
        "Z3 默认口径是「排除已注销」，档案必须显式 includeClosed=true 才可取",
        not miss3, "缺件：%s" % miss3,
    ))

    # ---- Z4 前端不自建第二套过滤 / 危险入口对 CLOSED 禁用
    view = t["inst_view"]
    closed_options = re.findall(r'<el-option[^>]*value="CLOSED"', view)
    delete_guard = view.count('command="delete-request"') >= 1 and \
        len(re.findall(r':disabled="row\.status === \'CLOSED\'"', view)) >= 2
    miss4 = []
    if closed_options:
        miss4.append("机构页出现了「已注销」筛选项（会把刻意隐藏的行捞回来）")
    if "includeClosed" in view:
        miss4.append("机构页自己下发 includeClosed（档案开关不该出现在运营面 UI）")
    if not delete_guard:
        miss4.append("「注销 / 申请删除」未对 CLOSED 行同时禁用")
    if "listInstitutions(statusFilter.value" not in view:
        miss4.append("状态筛选未走服务端口径（前端自己过滤 = 第二处判定）")
    out.append(("Z4 机构页：无「已注销」筛选项、不下发档案开关、CLOSED 行的危险操作禁用", not miss4,
                "问题：%s" % miss4))

    # ---- Z5 组织与员工为一级菜单
    layout = t["layout"]
    miss5 = []
    if re.search(r'<el-sub-menu[^>]*index="org"', layout):
        miss5.append("el-sub-menu index=\"org\" 仍在（二级菜单未去掉）")
    if 'index="/org-structure"' not in layout or "组织与员工" not in layout:
        miss5.append("缺一级项「组织与员工」→ /org-structure")
    if "showPersonnelMenu" in layout or "PERSONNEL_VIEW_ROLES" in layout:
        miss5.append("仍引用「人员管理」二级入口（应只剩页内页签，由 OrgAdminView 收口）")
    if "'/admin': '/org-structure'" not in layout:
        miss5.append("旧深链 /admin 未高亮归并到「组织与员工」")
    if re.search(r"'/org-structure'\s*:\s*'org'", layout) or re.search(r"'/admin'\s*:\s*'org'", layout):
        miss5.append("PATH_GROUP 仍把 org-structure/admin 归到已不存在的 'org' 组")
    out.append(("Z5 菜单：「组织与员工」为一级项，无二级子项，/admin 高亮归并", not miss5,
                "问题：%s" % miss5))

    # ---- Z6 人员管理筛选
    admin_view = t["admin_view"]
    api = t["api_resource"]
    lp_sig = _fn_block(api, "export function listPersonnel")
    miss6 = []
    for token in ('filters.scopeClass', 'filters.institutionId', 'filters.status', 'filters.keyword',
                  'filterOptions'):
        if token not in admin_view:
            miss6.append("AdminView 缺 %s" % token)
    if not lp_sig:
        miss6.append("listPersonnel 签名未取到（锚点失效，守卫失效）")
    else:
        for token in ("scopeClass", "institutionId", "status"):
            if token not in lp_sig:
                miss6.append("listPersonnel 签名未声明 %s 参数" % token)
    if "institutionOptions" not in admin_view or "view.value?.filterOptions?.institutions" not in admin_view:
        miss6.append("筛选选项未来自后端 filterOptions（前端自建枚举 = 第二处口径）")
    if "resetFilters" not in admin_view:
        miss6.append("缺「重置」出口（筛选后回不到全集）")
    out.append(("Z6 人员管理提供四维筛选，且选项与列表同源（后端 filterOptions）", not miss6,
                "问题：%s" % miss6))

    # ---- Z7 D15 未被放开（回归钉；权威版在 _check_delete_guards.py 的 D15，这里只防「顺手放开」）
    del_body = _method_body(t["tree"], "public Map<String, Object> deleteMember(")
    miss7 = []
    if '!OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())' not in guard:
        miss7.append("作用域解析不再要求 ACTIVE（已注销机构变得可达）")
    if not del_body:
        miss7.append("OrgTreeService.deleteMember 方法体未取到（锚点失效 ⇒ 下面三条会恒真）")
    else:
        if "企业管理员不可直接删除" not in del_body:
            miss7.append("FR-B2（企业管理员不可直删）被拿掉")
        for bad in ("STATUS_CLOSED", "isInstitutionClosed", "pproval"):
            if bad in del_body:
                miss7.append("deleteMember 里出现 %s（为 CLOSED 开了例外 / 走了审批）" % bad)
    out.append(("Z7 D15 保持：已注销机构仍是不可达档案（删员工无 CLOSED 例外、不走审批）", not miss7,
                "问题：%s" % miss7))

    # ---- Z8 行为套件必须入库且自带「反恒真」机件
    #
    # 本守卫是静态的，只能证明「代码写对了」；「注销后四个页面真的看不到它」只能靠行为套件。
    # 而行为套件最容易长成一组恒真断言（四个面在修前也可能恰好没有 CLOSED 数据 —— 授权与人员
    # 两面**实测就是**），所以这里连它的「反恒真机件」一起钉住：前提断言、构造夹具、负向自检开关。
    b = t["behavior"]
    miss8 = []
    if b == "":
        miss8.append("已入库的行为套件 %s 缺失（e2e_*.py 会被 .gitignore 排除，必须用 verify_/check_ 前缀）"
                     % os.path.basename(BEHAVIOR))
    else:
        for token, why in (
                ("C1", "缺「档案必须非空」的前提断言（否则后面的『看不见』全是恒真）"),
                ("C7a", "缺授权面的构造夹具断言（真实数据里没有该数据 ⇒ 断言会恒真）"),
                ("C8b", "缺人员面的构造夹具断言（同上）"),
                ("--selftest", "缺负向自检入口（无法证明这些断言会红）"),
                ("SELFTEST", "缺负向自检的注入开关"),
        ):
            if token not in b:
                miss8.append(why)
    out.append(("Z8 行为套件 verify_closed_institution_surfaces.py 已入库，且自带前提/夹具/负向自检",
                not miss8, "问题：%s" % miss8))

    # ---- Z9 本地级联删除套件（e2e_*.py 不入库 ⇒ 不在本地时跳过，不判失败）
    cas = t["cascade"]
    if cas == "":
        SKIPS.append("Z9 级联删除套件的档案断言：本地无 scripts/e2e_cascade_delete.py"
                     "（e2e_*.py 按仓库约定不入库）⇒ 本机可查，仓库不查")
    else:
        miss9 = []
        n = cas.count('includeClosed": "true"')
        if n < 2:
            miss9.append('N7b/N14 至少两处要显式 includeClosed=true（当前 %d 处）' % n)
        if "N7c" not in cas:
            miss9.append("缺 N7c 反向断言（默认口径必须查不到已注销机构）")
        out.append(("Z9 级联删除套件的档案断言显式带 includeClosed + 有默认口径反向断言",
                    not miss9, "问题：%s" % miss9))

    return out


def load():
    java_files = [p for p in __import__("glob").glob(os.path.join(SERVER, "**", "*.java"),
                                                    recursive=True)
                  if os.sep + "target" + os.sep not in p]
    return {
        "status": _strip_java(_read(STATUS)),
        "entity": _strip_java(_read(ENTITY)),
        "inst_svc": _strip_java(_read(INST_SVC)),
        "onb": _strip_java(_read(ONB_SVC)),
        "grant": _strip_java(_read(GRANT_SVC)),
        "cost": _strip_java(_read(COST_SVC)),
        "ctrl": _strip_java(_read(TENANT_CTRL)),
        "personnel": _strip_java(_read(PERSONNEL)),
        "org_guard": _strip_java(_read(ORG_GUARD)),
        "tree": _strip_java(_read(TREE_SVC)),
        "inst_view": _strip_web(_read(INST_VIEW)),
        "admin_view": _strip_web(_read(ADMIN_VIEW)),
        "layout": _strip_web(_read(LAYOUT)),
        "api_resource": _strip_web(_read(API_RESOURCE)),
        "cascade": _read(CASCADE) if os.path.exists(CASCADE) else "",
        "behavior": _read(BEHAVIOR) if os.path.exists(BEHAVIOR) else "",
        "java_all": {p: _strip_java(_read(p)) for p in java_files},
    }


def run():
    results = checks(load())
    bad = [c for c in results if not c[1]]
    for cid, ok, detail in results:
        print(("  [OK]   " if ok else "  [FAIL] ") + cid
              + (("  " + detail) if (detail and not ok) else ""))
    for s in SKIPS:
        print("  [skip] " + s)
    print("\n=== 正向 %d/%d 通过（跳过 %d） ===" % (len(results) - len(bad), len(results), len(SKIPS)))
    return 1 if bad else 0


def selftest():
    base = load()
    mutations = [
        ("Z1 运营面规则复制第二份",
         lambda t: dict(t, java_all=dict(t["java_all"], **{
             "__synthetic_status__.java":
                 'public static boolean operational(String s) { return true; }'})),
         ["Z1"]),
        ("Z1b 实体用裸 ne(CLOSED)（NULL 行被静默排除）",
         lambda t: dict(t, entity=t["entity"].replace(
             "w.and(x -> x.isNull(OrgInstitution::getStatus)",
             "w.ne(OrgInstitution::getStatus, STATUS_CLOSED);\n        w.and(x -> x.isNull(OrgInstitution::getStatus)")),
         ["Z1"]),
        ("Z2 入驻总览忘了排除",
         lambda t: dict(t, onb=t["onb"].replace("OrgInstitution.excludeClosed(w);", "")),
         ["Z2"]),
        ("Z2b 机构清单忘了排除",
         lambda t: dict(t, inst_svc=t["inst_svc"].replace("OrgInstitution.excludeClosed(w);", "")),
         ["Z2"]),
        ("Z2c 费用分摊试算忘了走运营面机构",
         lambda t: dict(t, cost=t["cost"].replace(
             "List<OrgInstitution> insts = operationalInstitutions(tenantId);",
             "List<OrgInstitution> insts = institutionMapper.selectList(null);")),
         ["Z2"]),
        ("Z3 includeClosed 默认值写成 true（修复失效）",
         lambda t: dict(t, ctrl=t["ctrl"].replace(
             'defaultValue = "false"', 'defaultValue = "true"')),
         ["Z3"]),
        ("Z3b 默认排除分支写反",
         lambda t: dict(t, inst_svc=t["inst_svc"].replace(
             "if (!includeClosed && (status == null || status.isBlank())) {",
             "if (includeClosed && (status == null || status.isBlank())) {")),
         ["Z3"]),
        ("Z4 机构页加回「已注销」筛选项",
         lambda t: dict(t, inst_view=t["inst_view"].replace(
             '<el-option label="已停用" value="SUSPENDED" />',
             '<el-option label="已停用" value="SUSPENDED" /><el-option label="已注销" value="CLOSED" />')),
         ["Z4"]),
        ("Z4b 申请删除对 CLOSED 行不再禁用",
         lambda t: dict(t, inst_view=t["inst_view"].replace(
             ':disabled="row.status === \'CLOSED\'"\n                  >\n                    {{ row.status',
             '>\n                    {{ row.status')),
         ["Z4"]),
        ("Z5 二级菜单复活",
         lambda t: dict(t, layout=t["layout"].replace(
             '<el-menu-item v-if="showOrgMenu" index="/org-structure">',
             '<el-sub-menu v-if="showOrgMenu" index="org">\n'
             '  <template #title><span>组织与员工</span></template>\n'
             '  <el-menu-item index="/org-structure">')),
         ["Z5"]),
        ("Z5b /admin 高亮归并丢失",
         lambda t: dict(t, layout=t["layout"].replace(
             "const MENU_ALIAS: Record<string, string> = { '/admin': '/org-structure' }",
             "const MENU_ALIAS: Record<string, string> = { }")),
         ["Z5"]),
        ("Z6 筛选选项改为前端自建",
         lambda t: dict(t, admin_view=t["admin_view"].replace(
             "view.value?.filterOptions?.institutions", "view.value?.groups")),
         ["Z6"]),
        ("Z6b 后端 listPersonnel 少一个筛选参数",
         # ★ key 必须是 api_resource（checks 读的是这个名字）。首版写成 api= ⇒ 突变对判定不可见，
         #   自检报「未报红」，实际是突变根本没进去（再一次证明：自检本身就是断言的一部分）。
         lambda t: dict(t, api_resource=t["api_resource"].replace("scopeClass?: string", "")),
         ["Z6"]),
        ("Z7 为 CLOSED 放开删员工例外",
         # 注入**真代码**（不是注释）：守卫判定的是去注释后的源码，
         # 注一句 `// isInstitutionClosed 例外` 本来就不该报红。
         lambda t: dict(t, tree=t["tree"].replace(
             "OrgMember m = requireMember(institutionId, id);",
             "OrgMember m = requireMember(institutionId, id);\n"
             '        if ("CLOSED".equals(STATUS_CLOSED)) { return null; }')),
         ["Z7"]),
        ("Z7c FR-B2 文案被拿掉（不可直删的口径消失）",
         lambda t: dict(t, tree=t["tree"].replace("企业管理员不可直接删除", "可删除")),
         ["Z7"]),
        ("Z7d deleteMember 方法体取不到时不得静默跳过",
         lambda t: dict(t, tree=t["tree"].replace(
             "public Map<String, Object> deleteMember(Long institutionId, Long id, AuthUser actor) {",
             "public Map<String, Object> deleteMemberX(Long institutionId, Long id, AuthUser actor) {")),
         ["Z7"]),
        ("Z7b 作用域解析不再要求 ACTIVE",
         lambda t: dict(t, org_guard=t["org_guard"].replace(
             "!OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())", "false")),
         ["Z7"]),
        ("Z8 行为套件忘记入库（e2e_ 前缀会被 gitignore 吞掉）",
         lambda t: dict(t, behavior=""),
         ["Z8"]),
        ("Z8b 行为套件缺负向自检入口（断言可能恒真）",
         lambda t: dict(t, behavior=t["behavior"].replace("--selftest", "")),
         ["Z8"]),
        ("Z9 本地级联套件忘记显式要档案（默认口径会让断言恒真）",
         lambda t: dict(t, cascade=t["cascade"].replace('includeClosed": "true"',
                                                       'includeClosed": "false"')),
         ["Z9"]),
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
