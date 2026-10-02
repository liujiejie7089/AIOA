# -*- coding: utf-8 -*-
"""项目管理（PM，docs/40 批次 1）的静态守卫。

为什么需要**静态**守卫（而不是只靠跑接口）：
    本批次的危险点大多不表现为「某个请求返回什么」，而是**结构**上的：
      · 类型守卫只写在某个 controller 里 ⇒ 另一条写入路径（如任务）绕过它，
        业务项目照样能被写入仓库字段，而界面上根本看不到这个入口；
      · 前端把仓库输入框藏了、后端没校验 ⇒ 直接 curl 就能给业务项目挂仓库；
      · 权限码只加在后端、前端菜单/路由没同步 ⇒ 菜单能进但接口 403（或反之）；
      · 任务状态机在两处各写一份 ⇒ 后端放行、前端拦死（或更糟：后端放行 DONE→DOING）；
      · 成员移除不校验「最后一个负责人」⇒ 项目变成无人可管的孤儿。
    这些都不会编译报错、也不一定让某个既有套件变红 —— 必须静态钉死。

本守卫断言：
    P1  三张 pm_* 表各只有一处建表定义；gitee_project.pm_project_id 只在一处 ALTER 加入
    P2  BR-01「业务项目不接受仓库配置」的判定点唯一（ProjectTypeGuard.assertRepoAllowed），
        且被项目新建/修改与任务新建/修改四条写入路径全部调用
    P3  BR-02 类型变更：升级放行、降级须「已绑仓库数 + 带仓库任务数」双零，且拒绝码为 409
    P4  BR-12 任务仓库字段成对约束在任务新建与修改两处都调用
    P5  业务任务表叫 pm_task；PM 模块**不得**引用 GiteeTask / GiteeTaskService（防与异步队列混淆）
    P6  权限码三处同源：PermissionCatalog（Java 常量 + GRANTS）、V71 的 sys_permission 种子、
        前端 permissions.ts + router + MainLayout
    P7  前端「仓库配置面」由项目类型驱动（业务项目不渲染仓库页签 / 仓库列 / 仓库策略块）
    P8  前端 api 一律走 unwrap（不得把 res.data 直接当业务数据，否则失败信封会被当数据）
    P9  列表按数据范围过滤（不是只判权限码就返回全量）
    P10 软删项目级联软删成员与任务，且**不**删 gitee_project 仓库行
    P11 任务状态机判定点唯一（PmTaskStatus.canTransition），DONE 为终态
    P12 不移除最后一个项目负责人（assertNotLastOwner 在移除与改角色两处都被调用）

★ 断言前**必须剥离注释**（Java `//`、`/* */`；Web `<!-- -->`）——
  本仓注释会复述这些关键字，按裸文本判定就是「谁写注释谁报红」。

用法：
    python scripts/_check_pm_guards.py            # 跑检查
    python scripts/_check_pm_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
MIGRATION = os.path.join(SERVER, "aioa-boot", "src", "main", "resources", "db", "migration")

PM = os.path.join(SERVER, "aioa-project", "src", "main", "java", "cn", "aioa", "project")
PROJ_SVC = os.path.join(PM, "service", "PmProjectService.java")
MEMBER_SVC = os.path.join(PM, "service", "PmProjectMemberService.java")
TASK_SVC = os.path.join(PM, "service", "PmTaskService.java")
GUARD = os.path.join(PM, "support", "ProjectTypeGuard.java")
TASK_STATUS = os.path.join(PM, "support", "PmTaskStatus.java")
ROLES = os.path.join(PM, "support", "PmProjectRoles.java")
PROJ_CTRL = os.path.join(PM, "controller", "PmProjectController.java")
TASK_CTRL = os.path.join(PM, "controller", "PmTaskController.java")
REPO_MAPPER = os.path.join(PM, "mapper", "PmRepoBindMapper.java")

CATALOG = os.path.join(SERVER, "aioa-security", "src", "main", "java", "cn", "aioa",
                       "security", "PermissionCatalog.java")
PERMS_TS = os.path.join(SHELL, "constants", "permissions.ts")
ROUTER = os.path.join(SHELL, "router", "index.ts")
LAYOUT = os.path.join(SHELL, "layouts", "MainLayout.vue")
API_PM = os.path.join(SHELL, "api", "pm.ts")
VIEW_LIST = os.path.join(SHELL, "views", "PmProjectsView.vue")
VIEW_DETAIL = os.path.join(SHELL, "views", "PmProjectDetailView.vue")

MISSING = "\x00"

PM_PERMS = ["pm:project:view", "pm:project:create", "pm:project:manage",
            "pm:member:manage", "pm:task:manage"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_or_missing(path):
    return _read(path) if os.path.exists(path) else MISSING


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def checks(t):
    out = []
    java = t["java_all"]
    mig = t["migrations"]

    # ---- P1 表定义唯一
    tbl_hits = {}
    for tbl in ("`pm_project`", "`pm_project_member`", "`pm_task`"):
        tbl_hits[tbl] = [p for p, s in mig.items() if ("CREATE TABLE " + tbl) in s]
    alter_hits = [p for p, s in mig.items() if "ADD COLUMN `pm_project_id`" in s]
    out.append((
        "P1 三张 pm_* 表各只有一处建表；pm_project_id 只在一处 ALTER 加入",
        all(len(v) == 1 for v in tbl_hits.values()) and len(alter_hits) == 1,
        "建表处 %s；加列处 %s"
        % ({k: [os.path.basename(p) for p in v] for k, v in tbl_hits.items()},
           [os.path.basename(p) for p in alter_hits]),
    ))

    # ---- P2 BR-01 判定点唯一 + 四条写入路径都调用
    guard_def = "public static void assertRepoAllowed(" in t["guard"]
    proj_calls = t["proj_svc"].count("ProjectTypeGuard.assertRepoAllowed(")
    task_calls = t["task_svc"].count("ProjectTypeGuard.assertRepoAllowed(")
    out.append((
        "P2 BR-01 判定点唯一，且项目/任务的新建与修改四条路径都调用 assertRepoAllowed",
        guard_def and proj_calls >= 2 and task_calls >= 2,
        "guard 定义=%s；project 调用 %d 处、task 调用 %d 处（各应 >=2：create + update）"
        % (guard_def, proj_calls, task_calls),
    ))

    # ---- P3 BR-02 类型变更
    type_guard_def = "public static void assertTypeChangeable(" in t["guard"]
    conflict_409 = "new BizException(409," in t["guard"]
    dual_count = "countBound(" in t["proj_svc"] and "countTasksWithRepo(" in t["proj_svc"]
    type_guard_call = "ProjectTypeGuard.assertTypeChangeable(" in t["proj_svc"]
    out.append((
        "P3 BR-02 类型降级须仓库/任务双零，且拒绝码为 409",
        type_guard_def and conflict_409 and dual_count and type_guard_call,
        "guard 定义=%s / 409=%s；双计数=%s；调用=%s"
        % (type_guard_def, conflict_409, dual_count, type_guard_call),
    ))

    # ---- P4 BR-12 成对约束
    pairing_def = "public static void assertRepoPairing(" in t["guard"]
    pairing_calls = t["task_svc"].count("ProjectTypeGuard.assertRepoPairing(")
    out.append((
        "P4 BR-12 任务仓库字段成对约束在任务新建与修改两处都调用",
        pairing_def and pairing_calls >= 2,
        "guard 定义=%s；task 调用 %d 处（应 >=2）" % (pairing_def, pairing_calls),
    ))

    # ---- P5 命名不与异步队列混淆
    gitee_task_refs = [p for p, s in java.items() if "GiteeTask" in s and os.sep + "aioa-project" + os.sep in p]
    out.append((
        "P5 业务任务表为 pm_task；PM 模块不得引用 GiteeTask / GiteeTaskService",
        '@TableName("pm_task")' in t["task_entity"] and not gitee_task_refs,
        "pm_task 实体=%s；PM 模块内 GiteeTask 引用=%s"
        % ('@TableName("pm_task")' in t["task_entity"], [os.path.basename(p) for p in gitee_task_refs]),
    ))

    # ---- P6 权限码三处同源
    catalog_ok = all(('"%s"' % c) in t["catalog"] for c in PM_PERMS)
    catalog_grants = all(("Map.entry(PM_" in t["catalog"]) for _ in [0]) and t["catalog"].count("PM_") >= 5
    seed_ok = all(("'%s'" % c) in t["v71"] for c in PM_PERMS)
    ts_ok = "PM_VIEW_ROLES" in t["perms_ts"]
    router_ok = "PM_VIEW_ROLES" in t["router"] and "pm/projects" in t["router"]
    menu_ok = "showPmMenu" in t["layout"] and "PM_VIEW_ROLES" in t["layout"]
    out.append((
        "P6 权限码三处同源（PermissionCatalog / sys_permission 种子 / 前端 ts+router+菜单）",
        catalog_ok and catalog_grants and seed_ok and ts_ok and router_ok and menu_ok,
        "catalog=%s grants=%s 种子=%s ts=%s router=%s 菜单=%s"
        % (catalog_ok, catalog_grants, seed_ok, ts_ok, router_ok, menu_ok),
    ))

    # ---- P7 前端仓库配置面由类型驱动
    detail = t["view_detail"]
    listv = t["view_list"]
    out.append((
        "P7 前端仓库配置面由项目类型驱动（仓库页签 / 任务仓库列 / 仓库策略块 均有 DEV 条件）",
        'v-if="isDev"' in detail
        and detail.count('v-if="isDev"') >= 3
        and "isDev = computed(() => project.value?.projectType === 'DEV'" in detail
        and "form.projectType === 'DEV'" in listv,
        "detail 中 v-if=\"isDev\" %d 处（应 ≥3：页签 + 任务仓库列 + 成员同步列/表单）；"
        "list 有 projectType === 'DEV' 条件=%s"
        % (detail.count('v-if="isDev"'), "form.projectType === 'DEV'" in listv),
    ))

    # ---- P8 前端 api 走 unwrap
    api_lines = [ln.strip() for ln in t["api_pm"].splitlines() if ln.strip().startswith("return http.")]
    bad_api = [ln for ln in api_lines if "unwrap<" not in ln]
    out.append((
        "P8 前端 PM api 全部走 unwrap（失败信封不得当业务数据）",
        not bad_api and "unwrap" in t["api_pm"],
        "未走 unwrap 的返回：%s" % bad_api,
    ))

    # ---- P9 列表按数据范围过滤
    out.append((
        "P9 列表按数据范围过滤（不只判权限码就返回全量）",
        "public PmProject requireVisible(" in t["proj_svc"]
        and "visibleDepartmentIds(" in t["proj_svc"]
        and "memberProjectIds(" in t["proj_svc"]
        and "visible.add(p);" in t["proj_svc"],
        "requireVisible=%s visibleDepartmentIds=%s memberProjectIds=%s 过滤=%s"
        % ("public PmProject requireVisible(" in t["proj_svc"],
           "visibleDepartmentIds(" in t["proj_svc"],
           "memberProjectIds(" in t["proj_svc"], "visible.add(p);" in t["proj_svc"]),
    ))

    # ---- P10 级联软删且不动仓库行
    out.append((
        "P10 软删项目级联软删成员+任务，且只解绑仓库不删 gitee_project 行",
        "public void softDelete(" in t["proj_svc"]
        and "memberMapper.delete(" in t["proj_svc"]
        and "taskMapper.delete(" in t["proj_svc"]
        and "repoBindMapper.unbind(" in t["proj_svc"]
        and "DELETE FROM gitee_project" not in t["repo_mapper"],
        "softDelete=%s 删成员=%s 删任务=%s 解绑=%s 无物理删仓库=%s"
        % ("public void softDelete(" in t["proj_svc"],
           "memberMapper.delete(" in t["proj_svc"],
           "taskMapper.delete(" in t["proj_svc"],
           "repoBindMapper.unbind(" in t["proj_svc"],
           "DELETE FROM gitee_project" not in t["repo_mapper"]),
    ))

    # ---- P11 任务状态机判定点唯一，DONE 终态
    ts = t["task_status"]
    done_block = re.search(r'DONE,\s*Set\.of\(\)', ts)
    out.append((
        "P11 任务状态机判定点唯一（canTransition）且 DONE 为终态",
        "public static boolean canTransition(" in ts
        and "PmTaskStatus.canTransition(" in t["task_svc"]
        and done_block is not None
        and "isTerminal(" in ts,
        "canTransition 定义=%s 调用=%s DONE 空集=%s isTerminal=%s"
        % ("public static boolean canTransition(" in ts,
           "PmTaskStatus.canTransition(" in t["task_svc"],
           done_block is not None, "isTerminal(" in ts),
    ))

    # ---- P12 不移除最后一个负责人
    out.append((
        "P12 不可移除/降级最后一个项目负责人（assertNotLastOwner 在移除与改角色两处调用）",
        "private void assertNotLastOwner(" in t["member_svc"]
        and t["member_svc"].count("assertNotLastOwner(") >= 3
        and "项目至少需要保留一名项目负责人" in t["member_svc"],
        "定义=%s 调用 %d 处（定义 1 + 调用 2）"
        % ("private void assertNotLastOwner(" in t["member_svc"],
           t["member_svc"].count("assertNotLastOwner(")),
    ))

    return out


def load():
    java_files = [p for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True)
                  if os.sep + "target" + os.sep not in p]
    mig_files = glob.glob(os.path.join(MIGRATION, "*.sql"))
    v71 = os.path.join(MIGRATION, "V71__pm_project.sql")
    return {
        "guard": _strip_java(_read(GUARD)),
        "proj_svc": _strip_java(_read(PROJ_SVC)),
        "member_svc": _strip_java(_read(MEMBER_SVC)),
        "task_svc": _strip_java(_read(TASK_SVC)),
        "task_status": _strip_java(_read(TASK_STATUS)),
        "task_entity": _strip_java(_read(os.path.join(PM, "entity", "PmTask.java"))),
        "repo_mapper": _strip_java(_read(REPO_MAPPER)),
        "proj_ctrl": _strip_java(_read(PROJ_CTRL)),
        "task_ctrl": _strip_java(_read(TASK_CTRL)),
        "catalog": _strip_java(_read(CATALOG)),
        "perms_ts": _strip_web(_read(PERMS_TS)),
        "router": _strip_web(_read(ROUTER)),
        "layout": _strip_web(_read(LAYOUT)),
        "api_pm": _strip_web(_read(API_PM)),
        "view_list": _strip_web(_read(VIEW_LIST)),
        "view_detail": _strip_web(_read(VIEW_DETAIL)),
        "v71": _read_or_missing(v71),
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
    """注入突变，要求对应断言**必须真报红**；突变未生效（锚点漂移）同样计失败。"""
    base = load()
    mutations = [
        ("P1 第二处建表",
         lambda t: dict(t, migrations=dict(t["migrations"], **{
             "__synthetic__.sql": "CREATE TABLE `pm_task` ( id BIGINT );"})),
         ["P1"]),
        ("P2 任务写入路径绕过类型守卫",
         lambda t: dict(t, task_svc=t["task_svc"].replace(
             "ProjectTypeGuard.assertRepoAllowed(", "/*disabled*/(")),
         ["P2"]),
        ("P3 降级改成 400 且不看计数",
         lambda t: dict(t, guard=t["guard"].replace("new BizException(409,", "new BizException(400,")),
         ["P3"]),
        ("P4 成对约束被摘掉",
         lambda t: dict(t, guard=t["guard"].replace(
             "public static void assertRepoPairing(Long repoId, String repoIssueNo,",
             "public static void disabledPairing(Long repoId, String repoIssueNo,")),
         ["P4"]),
        ("P5 PM 模块引入 GiteeTask",
         lambda t: dict(t, java_all=dict(t["java_all"], **{
             os.path.join(PM, "synthetic", "X.java"):
                 "import cn.aioa.gitee.entity.GiteeTask;\nclass X { GiteeTask t; }"})),
         ["P5"]),
        ("P6 前端漏登记权限常量",
         lambda t: dict(t, perms_ts=t["perms_ts"].replace("PM_VIEW_ROLES", "PMVIEWROLES")),
         ["P6"]),
        ("P7 任务仓库列去掉 DEV 条件",
         lambda t: dict(t, view_detail=t["view_detail"].replace('v-if="isDev"', '')),
         ["P7"]),
        ("P8 前端 api 绕过 unwrap",
         lambda t: dict(t, api_pm=t["api_pm"].replace(
             "http.get('/pm/projects', { params }).then((r) => unwrap<PmProject[]>(r))",
             "http.get('/pm/projects', { params }).then((r) => r.data)")),
         ["P8"]),
        ("P9 列表不做数据范围过滤",
         lambda t: dict(t, proj_svc=t["proj_svc"].replace("visible.add(p);", "")),
         ["P9"]),
        ("P10 软删不再级联成员",
         lambda t: dict(t, proj_svc=t["proj_svc"].replace("memberMapper.delete(", "/*x*/(")),
         ["P10"]),
        ("P11 DONE 允许回退",
         lambda t: dict(t, task_status=t["task_status"].replace(
             "DONE, Set.of(),", "DONE, Set.of(TODO),")),
         ["P11"]),
        ("P12 移除负责人不再校验",
         lambda t: dict(t, member_svc=t["member_svc"].replace("assertNotLastOwner(", "/*x*/(")),
         ["P12"]),
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
