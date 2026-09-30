# -*- coding: utf-8 -*-
"""「级联删除（机构 / 租户）+ 上一级审核」的静态守卫（防同类复发，无需启动服务）。

需求原文：「新增级联删除功能：删除部门前必须先删除该部门下的所有成员；删除机构前必须先删除该机构下的
所有部门；删除租户前必须先删除该租户下的所有部门。此外，任何一层级的首次删除操作都需要经过上一级审核
后方可执行。」

为什么需要**静态**守卫（端到端套件已经验过一遍了）：
    本能力的正确性有一半不在「某个请求返回什么」，而在**结构**上：
      · 有没有人不小心又开一个「直接删除」端点（审核闸门瞬间形同虚设，且所有既有用例仍然全绿）；
      · 有没有人在申请入口就顺手把对象删了（申请 ≠ 删除，铁律 #2）；
      · 有没有人把「批准时重新校验前置条件」删掉（TOCTOU：批准的是空机构、删的是有人的机构）；
      · 有没有人把「先冻账号再删租户」的顺序调过来（留下「租户查不到、账号仍可登录」的黑洞）。
    这些都不会编译报错、也不会让任何既有套件变红 —— 只能靠静态断言钉住。

断言分组：
    D1  接口层**没有**「直接删除」端点（机构 / 租户都只能申请）
    D2  申请入口不执行删除（删除只允许出现在审批回调里）
    D3  onApproved **重新**校验前置条件，且校验不过时**抛错**（不是静默跳过）
    D4  审批单里取不到业务对象 id 时**抛错**（不可逆动作绝不静默成功）
    D5  租户删除顺序：先冻结账号、再软删租户
    D6  层级顶端不能当申请人（平台管理员没有「上一级」）；默认租户不可删
    D7  流程定义两处口径一致（V69 迁移 + 入驻播种器），且都是「申请人的上一级」
    D8  新建租户必须触发播种（否则未入驻租户的删除申请会以「请先指定企业管理员」报错，用户无从满足）
    D9  前端**只有申请入口**，没有直删调用；两个概念（注销 / 删除）不混用
    D10 前端 api 走 unwrap 校验 code（失败信封不能被当业务数据）
    D11 部门「能不能删」只有一处判定（申请与执行共用 deptBlockedReason）
    D12 **员工**删除保持直删（不提交审核单），且前端有真实调用（不是死代码）
    D13 租户删除：**已注销(CLOSED)机构不构成阻塞**，且审批通过时**级联终止全部下级行**
        （对应 2026-09-24 用户反馈：「删完机构租户仍无法注销」+「平台管理员删除后相关数据仍继续展示」）
    D14 数据变更后同步**全局作用域态**（顶部租户/机构选择器 + 「机构 N」计数），无需手动 F5
    D15 「已注销(CLOSED)机构」是**不可达档案**：作用域解析对它一律 404，且 FR-B2 无任何例外
        （清理只能走「删租户」一条路 —— 防后人为了「删干净」而放开它，造出第二条口径与越权面）

用法：
    python scripts/_check_delete_guards.py            # 跑检查
    python scripts/_check_delete_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
MIGRATION = os.path.join(SERVER, "aioa-boot", "src", "main", "resources", "db", "migration")
ORG = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa", "org")
ADMIN = os.path.join(SERVER, "aioa-admin", "src", "main", "java", "cn", "aioa", "admin")

ORG_GUARD = os.path.join(ORG, "support", "OrgGuard.java")

INST_DEL = os.path.join(ORG, "service", "InstitutionDeleteService.java")
TEN_DEL = os.path.join(ORG, "service", "TenantDeleteService.java")
DEPT_DEL = os.path.join(ORG, "service", "DeptDeleteService.java")
TREE_SVC = os.path.join(ORG, "service", "OrgTreeService.java")
ORG_CTRL = os.path.join(ORG, "controller", "OrgAdminController.java")
TEN_CTRL = os.path.join(ORG, "controller", "TenantAdminController.java")
PROV = os.path.join(ORG, "support", "ApprovalFlowProvisioner.java")
TENANT_CTRL = os.path.join(ADMIN, "controller", "TenantController.java")
ORG_API = os.path.join(SHELL, "api", "org.ts")
INST_VIEW = os.path.join(SHELL, "views", "InstitutionView.vue")
SYS_VIEW = os.path.join(SHELL, "views", "SystemConfigView.vue")
ORG_VIEW = os.path.join(SHELL, "views", "OrgStructureView.vue")
TEN_ADMIN_VIEW = os.path.join(SHELL, "views", "TenantAdminView.vue")
APPR_VIEW = os.path.join(SHELL, "views", "ApprovalsView.vue")

MISSING = "\x00"

# 任何一处出现这些删除路径 ⇒ 「直接删除」被开了后门
FORBIDDEN_DELETE_PATHS = ["/departments/{id}", "/institutions/{id}", "/tenants/{id}", "/sub-tenants/{id}"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _read_or_missing(path):
    return _read(path) if os.path.exists(path) else MISSING


def _strip_java_comments(src):
    """去注释再断言。

    **为什么必须去注释**：本能力的每个结论都伴随着「为什么这样做」的说明，注释里必然复述
    `deleteById` / `deleted_at` / `ORG_ADMIN` 这些关键字。若连注释一起数，
    D2「申请入口不执行删除」会因为这些解释而恒红（同型坑：V66 守卫必须只数真正下发的 label）。
    """
    if src == MISSING:
        return src
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _method_body(src, signature):
    """截取单个方法体（签名 → 下一个与类成员同缩进的 `}`）。

    **为什么必须限定在方法内**：D3 要断言「onApproved 里必须重新校验」，而同一个类的 `apply`
    里也调用 `blockedReason`（那里是「不让用户白填一张注定被拒的单」）。不限定范围，
    断言就变成「别的方法也调了就算过」—— 审批回调里那段被删掉也不会报红。
    """
    if src == MISSING:
        return MISSING
    i = src.find(signature)
    if i < 0:
        return MISSING
    j = src.find("\n    }", i)
    return src[i:j] if j > 0 else src[i:]


def _ts_code_body(src):
    """TS 源码去掉 import / 注释，只留「真的写了什么」（同 V66 守卫 K4 的理由）。"""
    if src == MISSING:
        return src
    src = re.sub(r"^\s*import\s.*$", "", src, flags=re.M)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _all_java_mappings():
    """全仓 `@XxxMapping("path")` 清单（(文件, 注解, 路径)）。"""
    out = []
    for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True):
        if os.sep + "target" + os.sep in p:
            continue
        src = _strip_java_comments(_read(p))
        for m in re.finditer(r'@(Delete|Post|Put|Get)Mapping\(\s*"([^"]*)"', src):
            out.append((os.path.basename(p), m.group(1), m.group(2)))
    return out


def checks(t):
    out = []

    inst = t["inst_del"]
    ten = t["ten_del"]
    dept = t["dept_del"]
    tree = t["tree_svc"]
    org_ctrl = t["org_ctrl"]
    ten_ctrl = t["ten_ctrl"]
    tc = t["tenant_ctrl"]
    prov = t["prov"]
    org_api = t["org_api"]
    inst_view = t["inst_view"]
    sys_view = t["sys_view"]
    org_view = t["org_view"]

    # ============================================================ D1 没有「直接删除」端点
    del_paths = [(f, p) for f, kind, p in t["mappings"] if kind == "Delete"]
    leaked = [(f, p) for f, p in del_paths
              if p in FORBIDDEN_DELETE_PATHS or p.rstrip("/").endswith("/tenants")]
    out.append((
        "D1 接口层不存在「直接删除部门/机构/租户」端点（只能申请，批准后才删）",
        not leaked
        and '@DeleteMapping("/departments' not in org_ctrl
        and '@DeleteMapping("/institutions' not in org_ctrl
        and '@DeleteMapping("/institutions' not in ten_ctrl
        and '@DeleteMapping' not in tc
        and '@PostMapping("/departments/{id}/delete-request")' in org_ctrl
        and '@PostMapping("/institutions/{id}/delete-request")' in org_ctrl
        and '@PostMapping("/delete-request")' in ten_ctrl,
        "后门端点：%s；或少了申请端点" % (leaked or "无"),
    ))

    # ============================================================ D2 申请入口不执行删除
    #
    # ★ 只找**写**动作，不能拿 "deleted_at" 一概而论：申请入口里有「同一对象只允许一条在途申请」
    #   的去重查询，那条 SQL 合法地写着 `AND deleted_at IS NULL`（读，不是写）。一概而论会把
    #   正确代码判红，也会逼后人删掉去重逻辑（同 V66 守卫 K6 must-scan-only-in-method 的理由）。
    WRITE_PATTERNS = [
        r"deleteById\s*\(",
        r'"DELETE\s+FROM',
        r'"UPDATE\s+sys_tenant\s+SET\s+deleted_at',
        r'"UPDATE\s+sys_user\s+SET\s+status',
        r'"UPDATE\s+org_institution',
    ]
    applies = [
        ("DeptDeleteService.apply", _method_body(dept, "public Map<String, Object> apply(")),
        ("InstitutionDeleteService.apply", _method_body(inst, "public Map<String, Object> apply(")),
        ("TenantDeleteService.apply", _method_body(ten, "public Map<String, Object> apply(")),
    ]
    dirty = []
    for n, v in applies:
        if v == MISSING:
            dirty.append(n + "（方法未找到，锚点漂移）")
            continue
        hits = [p for p in WRITE_PATTERNS if re.search(p, v)]
        if hits:
            dirty.append("%s %s" % (n, hits))
    out.append((
        "D2 三个申请入口（apply）都不执行任何删除/冻结（申请 ≠ 删除）",
        not dirty,
        "申请入口里出现了删除动作：%s" % dirty,
    ))

    # ============================================================ D3 onApproved 必须重新校验
    oks = [
        ("DeptDeleteService", _method_body(dept, "public void onApproved(Map<String, Object> order) {"),
         "deptBlockedReason(", "blocked"),
        ("InstitutionDeleteService", _method_body(inst, "public void onApproved(Map<String, Object> order) {"),
         "blockedReason(", "blocked"),
        ("TenantDeleteService", _method_body(ten, "public void onApproved(Map<String, Object> order) {"),
         "blockedReason(", "blocked"),
    ]
    bad3 = [n for n, b, call, var in oks
            if b == MISSING
            or call not in b
            or not re.search(r"if \(%s != null\)\s*\{[^}]*throw " % var, b, re.S)]
    out.append((
        "D3 onApproved 重新校验前置条件且不通过时**抛错**（TOCTOU：批准空对象 ≠ 删有下级的对象）",
        not bad3,
        "缺「重新校验 + 抛错」：%s" % bad3,
    ))

    # ============================================================ D4 取不到业务对象 id 必须抛错
    bad4 = []
    dept_ok = _method_body(dept, "public void onApproved(Map<String, Object> order) {")
    if not re.search(r"if \(departmentId == null \|\| institutionId == null\)\s*\{[^}]*throw ", dept_ok, re.S):
        bad4.append("部门删除")
    inst_ok = _method_body(inst, "public void onApproved(Map<String, Object> order) {")
    if not re.search(r"if \(institutionId == null\)\s*\{[^}]*throw ", inst_ok, re.S):
        bad4.append("机构删除")
    ten_ok = _method_body(ten, "public void onApproved(Map<String, Object> order) {")
    if not re.search(r"if \(tenantId == null\)\s*\{[^}]*throw ", ten_ok, re.S):
        bad4.append("租户删除")
    out.append((
        "D4 审批单里取不到业务对象 id ⇒ 抛错（不可逆动作绝不静默成功）",
        not bad4,
        "静默跳过风险：%s" % bad4,
    ))

    # ============================================================ D5 先冻账号、再软删租户
    #
    # ★ 2026-09-30 收紧：账号必须**冻结并软删**（`DISABLED` + `deleted_at`），角色行一并清理。
    #   只冻结的话，平台「人员管理」渲染的是 `sys_user`（跨租户全集）⇒ 已删租户的账号
    #   仍会挂成一个分组继续展示。用户反馈「我已经删除了 test 租户，但人员管理还能看到 test」即此。
    m_freeze = re.search(r'"UPDATE sys_user SET status = \'DISABLED\'.*?tenantId\);', ten_ok, re.S)
    freeze_stmt = m_freeze.group(0) if m_freeze else ""
    i_freeze = m_freeze.start() if m_freeze else -1
    i_soft = ten_ok.find("UPDATE sys_tenant SET deleted_at")
    out.append((
        "D5 租户删除顺序：先**冻结并清理**全部账号（DISABLED + deleted_at，角色行同清），"
        "再软删租户行（只冻结不清理 ⇒ 人员管理仍展示已删租户的账号；反序 ⇒ 「租户查不到、账号仍可登录」）",
        i_freeze >= 0 and i_soft >= 0 and i_freeze < i_soft
        and "deleted_at = NOW(6)" in freeze_stmt
        and '"UPDATE sys_user_role SET deleted_at' in ten_ok,
        "freeze@%s softdel@%s 账号含deleted_at=%s 角色已清=%s" % (
            i_freeze, i_soft, "deleted_at = NOW(6)" in freeze_stmt,
            '"UPDATE sys_user_role SET deleted_at' in ten_ok),
    ))

    # ============================================================ D6 层级顶端不能当申请人
    out.append((
        "D6 平台管理员不能当申请人（它没有「上一级」，放行会把审批人静默指错）；默认租户不可删",
        "actor.getTenantId() == 0" in inst and "actor.getTenantId() == 0" in ten
        and "DEFAULT_TENANT_ID = 1L" in ten and "默认租户不可删除" in ten
        and "ROLE_TENANT_ADMIN" in ten,
        "缺层级/默认租户拦截",
    ))

    # ============================================================ D7 流程定义两处口径一致
    #
    # ★ 两处的字面量写法不同，必须分别比对（这不是冗余，是「两处口径必须一致」这条断言的前提）：
    #   迁移是**裸 SQL** 字符串：'[{"seq": 1, ...}]'
    #   播种器是 **Java 字符串字面量**："[{\"seq\": 1, ...}]"（多了转义反斜杠）
    #   拿同一个串去比两处，必然有一处永远匹配不上 —— 首版就在这上踩到（把正确代码判红）。
    JAVA_STEP = '[{\\"seq\\": 1, \\"approver_type\\": \\"APPLICANT_SUPERIOR\\", \\"levels\\": 1}]'
    SQL_STEP_KEYS = ['"approver_type": "APPLICANT_SUPERIOR"', '"levels": 1']
    migs = t["migs"]                       # V69/V70 都要查
    mig_ok = all(m != MISSING and all(k in m for k in SQL_STEP_KEYS) for m in migs.values())
    out.append((
        "D7 删除类流程定义：迁移（V69 机构/租户 + V70 部门）与入驻播种器**三处口径一致**",
        mig_ok
        and "'INSTITUTION_DELETE'" in migs.get("v69", MISSING)
        and "'TENANT_DELETE'" in migs.get("v69", MISSING)
        and "'DEPT_DELETE'" in migs.get("v70", MISSING)
        and 'new Seed("DEPT_DELETE"' in prov
        and 'new Seed("INSTITUTION_DELETE"' in prov and 'new Seed("TENANT_DELETE"' in prov
        and prov.count(JAVA_STEP) == 3,
        "V69/V70/播种器口径不一致或缺件 → 引擎会退化成单节点 ORG_ADMIN 兜底，审批人被静默指错"
        "（部门那一层甚至可能变成「申请人自己审自己」）",
    ))

    # ============================================================ D8 新租户必须播种
    out.append((
        "D8 新建租户触发租户级播种（未入驻租户也要有删除流程，否则删除能力事实上不可用）",
        "events.publishEvent(new TenantProvisionedEvent(" in tc,
        "TenantController.create 未发布 TenantProvisionedEvent：未入驻租户一条流程定义都没有，"
        "删除申请会以「请先在机构管理中指定企业管理员」报错（用户无从满足）",
    ))

    # ============================================================ D9 前端只有申请入口
    api_code = _ts_code_body(org_api)
    # ★ 不能笼统断言「org.ts 里没有 http.delete」：该文件合法地在删员工/解绑账号/撤权限时用
    #   DELETE（`/org/members/{id}`、`/tenant/grants/{id}`…）。
    #   一概而论会把正确代码判红。这里只挑「作用对象是组织层级本体（部门/机构/租户）」的 DELETE。
    front_delete = [m.group(1) for m in re.finditer(r"http\.delete\(\s*'([^']*)'", api_code)
                    if "institution" in m.group(1) or "departments" in m.group(1)
                    or (m.group(1).startswith("/tenant/") and not m.group(1).startswith("/tenant/grants"))]
    out.append((
        "D9 前端只有「申请删除」入口，没有部门/机构/租户的直删调用",
        not front_delete
        and "'/org/departments/' + id + '/delete-request'" in api_code
        and "'/org/institutions/' + id + '/delete-request'" in api_code
        and "'/tenant/delete-request'" in api_code
        and "requestDepartmentDelete(" in _ts_code_body(org_view)
        and "requestInstitutionDelete(" in _ts_code_body(inst_view)
        and "requestTenantDelete(" in _ts_code_body(sys_view),
        "缺件：%s" % [n for n, v in (
            ("api 无「组织层级本体」的 DELETE 调用", not front_delete),
            ("部门删除申请走 POST delete-request",
             "'/org/departments/' + id + '/delete-request'" in api_code),
            ("机构删除申请走 POST delete-request",
             "'/org/institutions/' + id + '/delete-request'" in api_code),
            ("租户删除申请走 POST delete-request", "'/tenant/delete-request'" in api_code),
            ("组织架构页接出部门申请删除", "requestDepartmentDelete(" in _ts_code_body(org_view)),
            ("机构页接出机构申请删除", "requestInstitutionDelete(" in _ts_code_body(inst_view)),
            ("系统配置页接出租户申请删除", "requestTenantDelete(" in _ts_code_body(sys_view)),
        ) if not v] + ("越界 DELETE：%s" % front_delete if front_delete else ""),
    ))

    # ============================================================ D10 api 走 unwrap
    out.append((
        "D10 三处删除申请 api 都走 unwrap 校验 code（失败信封不能被当业务数据）",
        api_code.count("unwrap<DeleteRequestResult>(r)") == 3,
        "三处申请接口都必须 unwrap（少一处 ⇒ 失败信封被当业务数据，页面显示成功但没提交）",
    ))

    # ============================================================ D11 部门前置校验只在一处
    #
    # 铁律 #1（同一决策点只在一处判定）：能否删除部门，由 `OrgTreeService.deptBlockedReason`
    # 一处判定，`deleteDept`（执行）与 `DeptDeleteService`（申请）都调它。
    # 若两边各写一份，迟早漂移成「申请时说能删、执行时说不能删」——而且不会有任何测试变红。
    out.append((
        "D11 部门「能不能删」只有 OrgTreeService.deptBlockedReason 一处判定（执行与申请共用）",
        "public String deptBlockedReason(" in tree
        and tree.count("子部门，请先迁移或删除子部门") == 1
        and tree.count("名员工，请先调整员工归属") == 1
        and "deptBlockedReason(institutionId, id)" in tree
        and "treeService.deptBlockedReason(" in dept,
        "判定出现了第二份实现（或申请侧绕开了它）→ 申请与执行的口径会漂移",
    ))

    # ============================================================ D12 员工删除保持「直删」
    #
    # 需求只要求「**部门及以上**层级的首次删除经上一级审核」；员工层由企业管理员自行负责。
    # 这一条防的是**两个方向**的走样：
    #   ① 反向过头 —— 后人「顺手统一一下」，把员工删除也塞进审核闸门（本需求没要求，
    #      且会让「删错人只能等上一级批」变成不可接受的运维负担）；
    #   ② 死代码 —— `api/org.ts` 里有 `deleteMember` 却没有任何视图调用它。
    #      这正是本次用户报的「我没看到删除员工的地方」：能力事实上不可用，
    #      而**所有既有套件仍然全绿**（`e2e_member_accounts` 直接打接口，根本不经过界面）。
    #      同型坑见铁律 #4：管理端入口缺失 = 能力事实上不存在，静态断言必须覆盖到「有人在用」。
    del_member_body = _method_body(tree, "public Map<String, Object> deleteMember(")
    member_biz = re.findall(r'BIZ_TYPE\s*=\s*"([A-Z_]+)"', inst + ten + dept)
    out.append((
        "D12 员工删除保持「直删」（不提交审核单），且前端有**真实调用**（不是死代码）",
        '@DeleteMapping("/members/{id}")' in org_ctrl
        and del_member_body != MISSING
        and "pproval" not in del_member_body
        and "SubmitReq" not in del_member_body
        and sorted(member_biz) == ["DEPT_DELETE", "INSTITUTION_DELETE", "TENANT_DELETE"]
        and "MEMBER" not in prov
        and "MEMBER" not in t["migs"]["v69"]
        and "MEMBER" not in t["migs"]["v70"]
        and "deleteMember(" in _ts_code_body(org_view)
        and "unwrap<unknown>(r)" in api_code,
        "缺件：%s" % [n for n, v in (
            ("D12a 员工直删端点 DELETE /org/members/{id} 仍在", '@DeleteMapping("/members/{id}")' in org_ctrl),
            ("D12b deleteMember 不提交审批单", del_member_body != MISSING
             and "pproval" not in del_member_body and "SubmitReq" not in del_member_body),
            ("D12c 受审核的删除层级恰为 部门/机构/租户 三层（员工层未被塞进闸门）",
             sorted(member_biz) == ["DEPT_DELETE", "INSTITUTION_DELETE", "TENANT_DELETE"]),
            ("D12d 播种器无员工级删除流", "MEMBER" not in prov),
            ("D12e 迁移无员工级删除流", "MEMBER" not in t["migs"]["v69"] and "MEMBER" not in t["migs"]["v70"]),
            ("D12f 组织架构页真的调用了 deleteMember（否则就是死代码 = 界面无入口）",
             "deleteMember(" in _ts_code_body(org_view)),
            ("D12g 员工直删 api 走 unwrap", "unwrap<unknown>(r)" in api_code),
        ) if not v],
    ))

    # ============================================================ D13 已注销机构不阻塞 + 级联清理
    #
    # 2026-09-24 用户反馈：「在租户管理中删除该租户的机构后，租户仍无法注销；通过平台管理员删除后，
    # 相关数据仍继续展示。」两个症状在结构上各对应一处必须钉死的东西：
    #   ① **阻塞面**：机构「注销」是不可逆终态（管理端原文「注销后机构不可恢复」），它只保留法人档案，
    #      其下的部门/员工也随之一并失效。若阻塞校验仍按 `deleted_at IS NULL` 一概计数，
    #      「已注销但未软删」的机构会**永久**卡死租户删除 —— 用户把机构全注销后仍被告知「仍有 1 个机构」。
    #   ② **清理面**：删 `sys_tenant` 不会带走 `org_*` 行，而**平台管理员的机构列表是跨租户全集**
    #      （`OrgGuard.selectableInstitutions`）⇒ 租户在列表里没了、它名下的机构/员工照旧展示。
    # 两条都不会编译报错，也不会让既有套件变红（既有套件只验「空机构可删」），只能静态钉住。
    ten_ok2 = _method_body(ten, "public void onApproved(Map<String, Object> order) {")
    CASCADE = [
        # ★ 2026-09-30 补「账号 / 账号角色」：平台「人员管理」渲染的是 `sys_user`（跨租户全集），
        #   2026-09-24 那次级联只覆盖了 `org_*` ⇒ 已删租户的**账号**仍挂成一个分组继续展示
        #   （用户反馈「我已经删除了 test 租户，但人员管理还能看到 test」）。
        #   模式串**必须带上 deleted_at**：只判 `status = 'DISABLED'` 会把「退回只冻结」误判成已级联。
        ("账号", '"UPDATE sys_user SET status = \'DISABLED\', deleted_at = NOW(6)'),
        ("账号角色", '"UPDATE sys_user_role SET deleted_at'),
        ("员工账号绑定", '"UPDATE org_member_account SET deleted_at'),
        ("员工", '"UPDATE org_member SET deleted_at'),
        ("部门", '"UPDATE org_department SET deleted_at'),
        ("机构", '"UPDATE org_institution SET deleted_at'),
    ]
    missing_cascade = [n for n, pat in CASCADE if pat not in ten_ok2]
    i_inst_cascade = ten_ok2.find('"UPDATE org_institution SET deleted_at')
    i_tenant_soft = ten_ok2.find('"UPDATE sys_tenant SET deleted_at')
    out.append((
        "D13 租户删除：已注销(CLOSED)机构不构成阻塞，且审批通过时级联终止全部下级行"
        "（否则「删完机构仍无法注销」+「租户已删、机构仍展示」）",
        "status <> 'CLOSED'" in ten
        and "NOT EXISTS (SELECT 1 FROM org_institution i WHERE i.id = t.institution_id" in ten
        and "countLiveInstitutions(tenantId)" in _method_body(ten, "public String blockedReason(")
        # 旧的「不带状态过滤」计数助手不得复活（★ 比对**整条**旧 SQL 串，不比对 `" + table` 前缀 ——
        #   新的 countOutsideClosedInstitutions 同样用 `" + table +` 拼表名，拿前缀断言会把正确代码判红）
        and '"SELECT COUNT(*) FROM " + table + " WHERE tenant_id = ? AND deleted_at IS NULL"' not in ten
        and not missing_cascade
        and i_inst_cascade >= 0 and i_tenant_soft >= 0 and i_inst_cascade < i_tenant_soft,
        "缺件：%s" % [n for n, v in (
            ("D13a blockedReason 的机构计数排除 CLOSED", "status <> 'CLOSED'" in ten),
            ("D13b 部门/员工计数排除「属于已注销机构」的行",
             "NOT EXISTS (SELECT 1 FROM org_institution i WHERE i.id = t.institution_id" in ten),
            ("D13c blockedReason 走唯一的 countLiveInstitutions（否则出现第二份判定，铁律 #1）",
             "countLiveInstitutions(tenantId)" in _method_body(ten, "public String blockedReason(")),
            ("D13d 不带状态过滤的计数助手已移除（防复活）",
             '"SELECT COUNT(*) FROM " + table + " WHERE tenant_id = ? AND deleted_at IS NULL"' not in ten),
            ("D13e onApproved 级联软删下级行（缺：%s）" % missing_cascade, not missing_cascade),
            ("D13f 级联必须在软删租户行**之前**（反序会留下「租户已删、下级仍在」的不可逆脏状态）",
             i_inst_cascade >= 0 and i_tenant_soft >= 0 and i_inst_cascade < i_tenant_soft),
        ) if not v],
    ))

    # ============================================================ D14 变更后同步全局作用域态
    #
    # 2026-09-24 用户反馈：「我在管理端执行了注销、新增等修改数据的操作后，页面数据必须立即刷新…
    # 无需手动干预。」根因**不在本页表格**（那些地方早就 `await reload()` 了），而在**顶部选择器读的
    # 模块级全局态**：`tenantState` / `institutionState` 只在登录时 load 一次，而
    # `OrgGuard.selectableInstitutions` 只回 `status=ACTIVE` 的机构 ⇒
    # 新增机构选不到、注销机构还挂在列表里、租户选项的「机构 N」不动，全都要 F5。
    # 这类缺陷不会让任何既有套件变红（套件直接打接口，根本不读前端全局态），只能静态钉住。
    inst_code = _ts_code_body(inst_view)
    ten_admin_code = _ts_code_body(t["ten_admin_view"])
    appr_code = _ts_code_body(t["appr_view"])
    out.append((
        "D14 数据变更后同步全局作用域态（顶部租户/机构选择器 + 「机构 N」计数），无需手动 F5",
        "refreshScopeStores" in inst_code
        and "loadInstitutionScope()" in inst_code and "loadTenantScope()" in inst_code
        # 三个变更出口：保存（新增/编辑）、申请删除、状态流转（停用/恢复/注销/冻结）
        and inst_code.count("await refreshScopeStores()") >= 3
        # 机构清单不再吞错：`.catch(() => [])` 会把失败信封渲染成一张空表（铁律 #2/#3）
        # ★ 用正则而不是字面量 `listInstitutions().catch(`：该调用已参数化
        #   （`listInstitutions(statusFilter ? {status} : undefined)`），写死空参形态会让
        #   这条守卫在参数化之后**静默失效**（突变异步漂移，自检会报「突变未生效」）。
        and not re.search(r"listInstitutions\s*\([^)]*\)\s*\.catch\(", inst_code)
        and "refreshTenantScope" in ten_admin_code and "loadTenantScope()" in ten_admin_code
        # 两个变更出口：保存（开通/编辑租户）、停用/启用
        and ten_admin_code.count("await refreshTenantScope()") >= 2
        # 审批决定也会改真实状态（机构/部门/租户删除被通过的那一刻）
        and "loadInstitutionScope()" in appr_code and "loadTenantScope()" in appr_code,
        "缺件：%s" % [n for n, v in (
            ("D14a 机构页变更后刷新机构作用域", "loadInstitutionScope()" in inst_code),
            ("D14b 机构页同时刷新租户作用域（租户选项文案含「机构 N」）",
             "loadTenantScope()" in inst_code),
            ("D14c 机构页三个变更出口都调 refreshScopeStores（当前 %d 处）"
             % inst_code.count("await refreshScopeStores()"),
             inst_code.count("await refreshScopeStores()") >= 3),
            ("D14d 机构清单不再静默吞错（失败必须可见）", "listInstitutions().catch(" not in inst_code),
            ("D14e 租户页开通/编辑后刷新租户作用域", "loadTenantScope()" in ten_admin_code),
            ("D14f 租户页两个变更出口都调 refreshTenantScope（当前 %d 处）"
             % ten_admin_code.count("await refreshTenantScope()"),
             ten_admin_code.count("await refreshTenantScope()") >= 2),
            ("D14g 审批通过后同步两个作用域（删除类单据会改真实状态）",
             "loadInstitutionScope()" in appr_code and "loadTenantScope()" in appr_code),
        ) if not v],
    ))

    # ============================================================ D15 注销机构是不可达档案
    #
    # 修 D13 时**先写了一版「已注销机构的企业管理员可被移除」的改动，实测发现它是不可达代码**：
    # 作用域解析 {@code OrgGuard.resolveScopeInstitution → requireActiveInstitution} 对非 ACTIVE
    # 机构一律 404，所以 `DELETE /org/members/{id}?institutionId=<CLOSED>` 在进到 deleteMember 之前
    # 就挂了（实测 `code=404 机构不存在或已停用`）。这说明「注销」在设计上就是**不可达档案**：
    # 保留法人档案、不再对外服务、不参与任何组织操作。
    #
    # 于是清理路径**只能有一条**：删租户（D13 的级联）。这条断言防的是两个方向的走样：
    #   ① 后人为了「把已注销机构删干净」而放开 requireActiveInstitution / 给 deleteMember 加 CLOSED 例外
    #      ⇒ 立刻多出第二条清理口径 + 对已注销机构的可操作面（越权风险）；
    #   ② 把 FR-B2（企业管理员不可直删）的例外悄悄写进去 —— 那样任何机构的管理员都能被直删。
    # ★ 必须取 t["org_guard"]（load() 已去注释的副本），**不能**在这里 `_read(ORG_GUARD)`：
    #   从磁盘重读会让本断言对 selftest 注入的突变完全不敏感 ⇒ 断言恒真（首版就是这样，
    #   靠 D15a 的突变自检才暴露 —— 恒真断言比没断言更危险，铁律 #7）。
    guard_code = t["org_guard"]
    del_member_body3 = _method_body(tree, "public Map<String, Object> deleteMember(")
    out.append((
        "D15 「已注销(CLOSED)机构」是不可达档案：作用域解析对它一律 404，FR-B2 无例外"
        "（清理只能走「删租户」一条路）",
        '!OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())' in guard_code
        and "机构不存在或已停用" in guard_code
        and del_member_body3 != MISSING
        and "企业管理员不可直接删除" in del_member_body3
        and "isInstitutionClosed" not in del_member_body3
        and "STATUS_CLOSED" not in del_member_body3
        and "pproval" not in del_member_body3,
        "缺件：%s" % [n for n, v in (
            ("D15a 作用域解析仍要求机构为 ACTIVE（已注销机构不可达）",
             '!OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())' in guard_code),
            ("D15b deleteMember 不得为 CLOSED 开例外（否则多出第二条「清干净」口径）",
             "isInstitutionClosed" not in del_member_body3
             and "STATUS_CLOSED" not in del_member_body3),
            ("D15c FR-B2（企业管理员不可直删）保持无条件，且不走审批",
             "企业管理员不可直接删除" in del_member_body3 and "pproval" not in del_member_body3),
        ) if not v],
    ))

    return out


def load():
    def _mig(prefix):
        hits = glob.glob(os.path.join(MIGRATION, prefix + "*.sql"))
        return _read(hits[0]) if hits else MISSING

    return {
        "inst_del": _strip_java_comments(_read(INST_DEL)),
        "ten_del": _strip_java_comments(_read(TEN_DEL)),
        "dept_del": _strip_java_comments(_read(DEPT_DEL)),
        "tree_svc": _strip_java_comments(_read(TREE_SVC)),
        "org_ctrl": _strip_java_comments(_read(ORG_CTRL)),
        "ten_ctrl": _strip_java_comments(_read(TEN_CTRL)),
        "tenant_ctrl": _strip_java_comments(_read(TENANT_CTRL)),
        "prov": _strip_java_comments(_read(PROV)),
        # D15：作用域解析（已注销机构 404 的唯一判定点）
        "org_guard": _strip_java_comments(_read(ORG_GUARD)),
        # 删除类流程定义的迁移：V69（机构/租户）、V70（部门）—— 缺任一个都要报红
        "migs": {"v69": _mig("V69"), "v70": _mig("V70")},
        "org_api": _read(ORG_API),
        "inst_view": _read(INST_VIEW),
        "sys_view": _read(SYS_VIEW),
        "org_view": _read(ORG_VIEW),
        # D14 要读的三个「变更后必须同步作用域态」的页面
        "ten_admin_view": _read(TEN_ADMIN_VIEW),
        "appr_view": _read(APPR_VIEW),
        "mappings": _all_java_mappings(),
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

    def _d13f_order_swap(t):
        """把「软删租户行」挪到级联**之前** —— 正是 D13f 要拦的反序。

        ★ 锚点漂移时**返回原值**（而不是抛异常）：上层会据此报「突变未生效」，
          这比静默不报红更容易发现（同 D12b 的教训）。
        """
        src = t["ten_del"]
        m = re.search(r'int rows = jdbc\.update\("UPDATE sys_tenant SET deleted_at.*?tenantId\);', src, re.S)
        if not m:
            return t
        stmt = m.group(0)
        moved = src.replace(stmt, "int rows = 0;", 1).replace(
            "int bindings = jdbc.update(", stmt + "\n        int bindings = jdbc.update(", 1)
        return dict(t, ten_del=moved)

    mutations = [
        ("D1 有人补了个「直接删除机构」端点（审核闸门形同虚设）",
         lambda t: dict(t, org_ctrl=t["org_ctrl"].replace(
             '@PostMapping("/institutions/{id}/delete-request")',
             '@DeleteMapping("/institutions/{id}")\n    public void gone() {}\n\n'
             '    @PostMapping("/institutions/{id}/delete-request")')),
         ["D1"]),
        ("D1a 部门退回「直接删除」（最常删的一层，却最松）",
         lambda t: dict(t, org_ctrl=t["org_ctrl"].replace(
             '@PostMapping("/departments/{id}/delete-request")',
             '@DeleteMapping("/departments/{id}")\n    public void gone() {}\n\n'
             '    @PostMapping("/departments/{id}/delete-request")')),
         ["D1"]),
        ("D1b 平台租户控制器冒出一个 DELETE",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"] + '\n@DeleteMapping("/{id}")'),
         ["D1"]),
        ("D1c 申请端点被删掉（只剩直接删或者什么都没有）",
         lambda t: dict(t, ten_ctrl=t["ten_ctrl"].replace('@PostMapping("/delete-request")',
                                                          '@PostMapping("/gone-request")')),
         ["D1"]),
        ("D2 申请入口就把机构删了（申请 = 删除）",
         lambda t: dict(t, inst_del=t["inst_del"].replace(
             "String blocked = blockedReason(institutionId);",
             "institutionMapper.deleteById(institutionId);\n        String blocked = blockedReason(institutionId);", 1)),
         ["D2"]),
        ("D2a 申请入口就把部门删了",
         lambda t: dict(t, dept_del=t["dept_del"].replace(
             "String blocked = treeService.deptBlockedReason(institutionId, departmentId);",
             "deptMapper.deleteById(departmentId);\n"
             "        String blocked = treeService.deptBlockedReason(institutionId, departmentId);", 1)),
         ["D2"]),
        ("D2b 申请入口顺手把租户软删了",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             "String blocked = blockedReason(tenantId);",
             'jdbc.update("UPDATE sys_tenant SET deleted_at = NOW(6) WHERE id = ?", tenantId);\n'
             "        String blocked = blockedReason(tenantId);", 1)),
         ["D2"]),
        ("D3 批准时不再重新校验前置条件（TOCTOU）",
         # ★ 锚点必须**只命中 onApproved**：`String blocked = blockedReason(...)` 在 apply 里也有一份
         #   （那里是「不让用户白填一张注定被拒的单」）。首版用 `replace(..., 1)` 只改到 apply 那份，
         #   于是「审批回调删掉重校验」这条突变没生效、D3 静默变恒真 —— 正是自检要抓的形态。
         lambda t: dict(t, inst_del=t["inst_del"].replace(
             'String blocked = blockedReason(institutionId);\n'
             '        if (blocked != null) {\n'
             '            throw BizException.badRequest("审批期间该机构已不再满足删除条件，本次不执行删除：" + blocked);\n'
             '        }\n', "")),
         ["D3"]),
        ("D3a 部门批准时不再重新校验（批准空部门 ≠ 删有子部门的部门）",
         lambda t: dict(t, dept_del=t["dept_del"].replace(
             'String blocked = treeService.deptBlockedReason(institutionId, departmentId);\n'
             '        if (blocked != null) {\n'
             '            throw BizException.badRequest("审批期间该部门已不再满足删除条件，本次不执行删除：" + blocked);\n'
             '        }\n', "")),
         ["D3"]),
        ("D3b 校验不通过时静默跳过（改成 return 而不是抛错）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             'throw BizException.badRequest("审批期间该租户已不再满足删除条件，本次不执行删除：" + blocked);',
             "return;")),
         ["D3"]),
        ("D4 取不到 institutionId 时静默返回",
         lambda t: dict(t, inst_del=t["inst_del"].replace(
             'throw BizException.badRequest("机构删除审批通过，但审批单里没有机构标识（form_data 缺 institutionId），"\n'
             '                    + "拒绝静默跳过：orderId=" + order.get("id"));',
             "return;")),
         ["D4"]),
        ("D4a 部门取不到 departmentId 时静默返回",
         lambda t: dict(t, dept_del=t["dept_del"].replace(
             'throw BizException.badRequest("部门删除审批通过，但审批单里缺少部门/机构标识"\n'
             '                    + "（form_data 缺 departmentId 或 institutionId），拒绝静默跳过：orderId=" + order.get("id"));',
             "return;")),
         ["D4"]),
        ("D4b 取不到 tenantId 时静默返回",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             'throw BizException.badRequest("租户删除审批通过，但审批单里没有租户标识（form_data 缺 tenantId），"\n'
             '                    + "拒绝静默跳过：orderId=" + order.get("id"));',
             "return;")),
         ["D4"]),
        ("D5 顺序调反：先软删租户、再冻账号",
         # ★ 锚点里**不能带 `// ② 软删租户行` 这类注释**：load() 已用 _strip_java_comments 去掉注释，
         #   注释会留下一行只剩缩进的空白（`\n        \n        `），带注释的锚点永远匹配不上。
         #   故这里改用正则、用 `\s*` 跨过空白区间 —— 不要写死缩进（首版就是这样「突变未生效」）。
         #   ★ 变量名用 `\w+` 而不是写死：2026-09-30 把 `int frozen` 改名成 `int users`（语义从
         #     「冻结」变成「冻结并清理」），写死变量名会让这条突变**静默失效**。
         lambda t: dict(t, ten_del=re.sub(
             r"(int \w+ = jdbc\.update\(\"UPDATE sys_user SET status = 'DISABLED.*?tenantId\);)(\s*)"
             r"(int rows = jdbc\.update\(\"UPDATE sys_tenant SET deleted_at.*?tenantId\);)",
             r"\3\2\1", t["ten_del"], count=1, flags=re.S)),
         ["D5"]),
        ("D5b 账号只冻结不软删（已删租户的账号仍会挂成一个分组出现在人员管理里）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             "UPDATE sys_user SET status = 'DISABLED', deleted_at = NOW(6), ",
             "UPDATE sys_user SET status = 'DISABLED', ", 1)),
         ["D5", "D13"]),
        ("D13h 级联漏掉账号角色清理（角色行残留）",
         lambda t: dict(t, ten_del=re.sub(
             r'\s*int userRoles = jdbc\.update\("UPDATE sys_user_role SET deleted_at.*?tenantId\);',
             "", t["ten_del"], count=1, flags=re.S)),
         ["D5", "D13"]),
        ("D6 放开平台管理员发起机构删除（审批人会静默指错）",
         lambda t: dict(t, inst_del=t["inst_del"].replace(
             "if (actor.getTenantId() == null || actor.getTenantId() == 0L) {",
             "if (false) {")),
         ["D6"]),
        ("D6b 默认租户可删",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             'throw BizException.badRequest("默认租户不可删除");', "// gone")),
         ["D6"]),
        ("D7 V69 少播种一条（TENANT_DELETE 没有流程定义）",
         lambda t: dict(t, migs=dict(t["migs"], v69=t["migs"]["v69"].replace("'TENANT_DELETE'", "'GONE'"))),
         ["D7"]),
        ("D7a 漏了 V70（部门删除没有流程定义）",
         lambda t: dict(t, migs=dict(t["migs"], v70=MISSING)),
         ["D7"]),
        ("D7b 播种器漏掉租户删除流程",
         lambda t: dict(t, prov=t["prov"].replace(
             'new Seed("TENANT_DELETE",\n'
             '                    "租户默认租户删除审批流（上一级审批）",\n'
             '                    "[{\\"seq\\": 1, \\"approver_type\\": \\"APPLICANT_SUPERIOR\\", \\"levels\\": 1}]")',
             'new Seed("GONE", "占位", "[{\\"seq\\": 1}]")')),
         ["D7"]),
        ("D7c 流程改成固定 ORG_ADMIN（删租户会被派给机构管理员）",
         lambda t: dict(t, prov=t["prov"].replace('\\"levels\\": 1', '\\"levels\\": 2')),
         ["D7"]),
        ("D8 新建租户不再播种（未入驻租户删不掉）",
         lambda t: dict(t, tenant_ctrl=t["tenant_ctrl"].replace(
             "events.publishEvent(new TenantProvisionedEvent(t.getId(), null, t.getName()));",
             "// gone")),
         ["D8"]),
        ("D9 前端冒出直删调用",
         lambda t: dict(t, org_api=t["org_api"]
                        + "\nexport function deleteTenant(id: number) { return http.delete('/tenant/' + id) }\n"),
         ["D9"]),
        ("D9a 前端冒出部门直删调用",
         lambda t: dict(t, org_api=t["org_api"]
                        + "\nexport function deleteDept(id: number) { return http.delete('/org/departments/' + id) }\n"),
         ["D9"]),
        ("D9b 组织架构页的部门申请删除入口被删掉",
         lambda t: dict(t, org_view="\n".join(
             ln for ln in t["org_view"].splitlines() if "requestDepartmentDelete(" not in ln)),
         ["D9"]),
        ("D9c 机构页的「申请删除」入口被删掉",
         lambda t: dict(t, inst_view="\n".join(
             ln for ln in t["inst_view"].splitlines() if "requestInstitutionDelete(" not in ln)),
         ["D9"]),
        ("D9d 系统配置页的申请删租户入口被删掉",
         lambda t: dict(t, sys_view="\n".join(
             ln for ln in t["sys_view"].splitlines() if "requestTenantDelete(" not in ln)),
         ["D9"]),
        ("D10 一处 api 绕开 unwrap（失败信封当数据）",
         lambda t: dict(t, org_api=t["org_api"].replace(
             "unwrap<DeleteRequestResult>(r)", "r.data.data", 1)),
         ["D10"]),
        ("D11 部门能否删除出现了第二份判定（申请侧自己写一份）",
         # ★ 突变体里**不能靠注释**把原调用「留着」：`checks()` 收到的是 load() 已去注释的文本，
         #   突变阶段再写进注释也不会被再去一次 ⇒ 原字符串仍在文本里 ⇒ 断言照样通过（假绿）。
         #   必须**真的删掉**那次调用。
         lambda t: dict(t, dept_del=t["dept_del"].replace(
             "String blocked = treeService.deptBlockedReason(institutionId, departmentId);",
             'String blocked = (deptMapper.selectCount(null) > 0) ? "该部门下仍有子部门" : null;')),
         ["D11"]),
        ("D11b 执行侧不再走同一份判定（deleteDept 自己再写一遍）",
         # ★ key 必须与 load() 的键名一致（load 里是 tree_svc，不是 tree）。
         #   键名写错时 t2 与 base 不相等（多了一个没人读的键）⇒ 不会被判「突变未生效」，
         #   而是静默不报红 —— 比直接报错更难发现。
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             "String blocked = deptBlockedReason(institutionId, id);", "String blocked = null;")),
         ["D11"]),
        ("D12a 员工直删端点被撤掉（改成 POST，界面上的「移除」全 405）",
         lambda t: dict(t, org_ctrl=t["org_ctrl"].replace(
             '@DeleteMapping("/members/{id}")', '@PostMapping("/members/{id}")')),
         ["D12"]),
        ("D12b 员工删除被「顺手统一」塞进审核闸门（本需求只要求部门及以上）",
         # ★ 锚点**不能含注释**：load() 返回的 tree_svc 已经过 _strip_java_comments，
         #   带注释的锚点永远匹配不上 ⇒ t2 == base ⇒ 会报「突变未生效」而不是「守卫失效」。
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             "memberMapper.deleteById(id);",
             "approvalFlow.getObject().submit(m.getTenantId(), actor, null);\n"
             "        memberMapper.deleteById(id);")),
         ["D12"]),
        ("D12c 受审核的删除层级不再恰好是三层（有人挪走了一层）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             'public static final String BIZ_TYPE = "TENANT_DELETE";', "")),
         ["D12"]),
        ("D12d 播种器给员工层也播了一条删除审批流",
         lambda t: dict(t, prov=t["prov"].replace(
             'new Seed("TENANT_DELETE",',
             'new Seed("MEMBER_DELETE", "[{\\"seq\\": 1, \\"approver_type\\": \\"APPLICANT_SUPERIOR\\", \\"levels\\": 1}]"),\n'
             '            new Seed("TENANT_DELETE",')),
         ["D12"]),
        ("D12e 迁移里给员工层补了删除审批流",
         lambda t: dict(t, migs=dict(t["migs"], v69=t["migs"]["v69"].replace(
             "'TENANT_DELETE'", "'TENANT_DELETE', 'MEMBER_DELETE'", 1))),
         ["D12"]),
        ("D12f ★界面入口没了（api 函数还在，但没人调用 = 死代码；既有套件全绿也发现不了）",
         # 这正是本次用户报的「我没看到删除员工的地方」：能力事实上不可用，而
         # e2e_member_accounts 直接打接口、根本不经过界面 ⇒ 一条断言都不会红。
         lambda t: dict(t, org_view=t["org_view"].replace(
             "    await deleteMember(row.id!, instId.value)\n", "")),
         ["D12"]),
        # ---------------------------------------------------------------- D13 已注销机构不阻塞 + 级联清理
        ("D13a 阻塞校验退回「不带状态过滤」的计数（已注销机构又永久卡死租户删除）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             "long insts = countLiveInstitutions(tenantId);",
             'long insts = jdbc.queryForObject("SELECT COUNT(*) FROM org_institution '
             'WHERE tenant_id = ? AND deleted_at IS NULL", Long.class, tenantId);')),
         ["D13"]),
        ("D13b 部门/员工不再排除「属于已注销机构」的行（已注销机构里的残留员工又永久卡住）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             '"AND NOT EXISTS (SELECT 1 FROM org_institution i WHERE i.id = t.institution_id "',
             '"AND "')),
         ["D13"]),
        ("D13c 复活了旧的「无状态过滤」计数助手（阻塞面出现第二份判定）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             "long insts = countLiveInstitutions(tenantId);",
             'long insts = count("org_institution", tenantId);')
             + '\n    private long count(String table, Long tenantId) {\n'
               '        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table '
               '+ " WHERE tenant_id = ? AND deleted_at IS NULL", Long.class, tenantId);\n    }\n'),
         ["D13"]),
        ("D13d 员工未随租户删除一起终止（平台管理员的列表里仍能看到已删租户的员工）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             '"UPDATE org_member SET deleted_at', '"UPDATE org_member SET gone_at')),
         ["D13"]),
        ("D13e 机构未随租户删除一起终止（★用户原症状：租户已删、机构仍继续展示）",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             '"UPDATE org_institution SET deleted_at', '"UPDATE org_institution SET gone_at')),
         ["D13"]),
        ("D13f 部门未随租户删除一起终止",
         lambda t: dict(t, ten_del=t["ten_del"].replace(
             '"UPDATE org_department SET deleted_at', '"UPDATE org_department SET gone_at')),
         ["D13"]),
        ("D13g 级联与软删租户的顺序被调反（留下「租户已删、下级仍在」的不可逆脏状态）",
         _d13f_order_swap,
         ["D13"]),
        # ---------------------------------------------------------------- D14 变更后同步作用域态
        ("D14a 机构页变更后不再同步作用域（★用户原症状：新增机构选不到、已注销的还挂在下拉里）",
         lambda t: dict(t, inst_view="\n".join(
             ln for ln in t["inst_view"].splitlines() if "await refreshScopeStores()" not in ln)),
         ["D14"]),
        ("D14b 机构清单又退回静默吞错（403/500 被渲染成一张空表 = 看起来「数据没了」）",
         # ★ 锚点跟着调用形态走：该调用现在带筛选参数，写死 `"      listInstitutions(),"` 会匹配不上
         #   ⇒ 突变未生效（本条自检正是在 2026-09-30 参数化之后报出来的）。改成正则追加 `.catch(...)`。
         lambda t: dict(t, inst_view=re.sub(
             r"(listInstitutions\s*\([^)]*\))",
             r"\1.catch(() => [] as Institution[])", t["inst_view"], count=1)),
         ["D14"]),
        ("D14c 租户页开通后不再刷新租户作用域（新租户在顶部下拉里选不到）",
         lambda t: dict(t, ten_admin_view="\n".join(
             ln for ln in t["ten_admin_view"].splitlines() if "await refreshTenantScope()" not in ln)),
         ["D14"]),
        ("D14d 审批通过后不再同步作用域（单据已通过、下拉里那个机构/租户还在）",
         lambda t: dict(t, appr_view="\n".join(
             ln for ln in t["appr_view"].splitlines()
             if "loadInstitutionScope().catch(" not in ln and "loadTenantScope().catch(" not in ln)),
         ["D14"]),
        # ---------------------------------------------------------------- D15 注销机构是不可达档案
        ("D15a 放开作用域解析，让已注销机构变得可操作（多出第二条清理口径 + 越权面）",
         lambda t: dict(t, org_guard=t["org_guard"].replace(
             "if (ins == null || !OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())) {",
             "if (ins == null) {")),
         ["D15"]),
        ("D15b 给 deleteMember 加了「机构已注销则可直删管理员」的例外",
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             "        if (Boolean.TRUE.equals(m.getIsOrgAdmin())) {",
             "        if (Boolean.TRUE.equals(m.getIsOrgAdmin()) && !isInstitutionClosed(institutionId)) {")),
         ["D15"]),
        ("D15c FR-B2 被删掉（任何机构的企业管理员都能被直删）",
         lambda t: dict(t, tree_svc=t["tree_svc"].replace(
             'throw BizException.badRequest("企业管理员不可直接删除，请先在机构管理页完成管理员交接（FR-B2）");',
             "// gone")),
         ["D15"]),
    ]
    bad = 0
    for name, mutate, expect in mutations:
        t2 = mutate(base)
        if t2 == base:
            # ★ 锚点漂移必须计失败：没生效的突变＝没验过的断言（同 V66 守卫）
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
