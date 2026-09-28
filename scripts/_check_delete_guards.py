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
    i_freeze = ten_ok.find("UPDATE sys_user SET status = 'DISABLED'")
    i_soft = ten_ok.find("UPDATE sys_tenant SET deleted_at")
    out.append((
        "D5 租户删除顺序：先冻结全部账号，再软删租户行（反序会留下「租户查不到、账号仍可登录」）",
        i_freeze >= 0 and i_soft >= 0 and i_freeze < i_soft,
        "freeze@%s softdel@%s" % (i_freeze, i_soft),
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
        # 删除类流程定义的迁移：V69（机构/租户）、V70（部门）—— 缺任一个都要报红
        "migs": {"v69": _mig("V69"), "v70": _mig("V70")},
        "org_api": _read(ORG_API),
        "inst_view": _read(INST_VIEW),
        "sys_view": _read(SYS_VIEW),
        "org_view": _read(ORG_VIEW),
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
         lambda t: dict(t, ten_del=re.sub(
             r"(int frozen = jdbc\.update\(\"UPDATE sys_user SET status = 'DISABLED.*?tenantId\);)(\s*)"
             r"(int rows = jdbc\.update\(\"UPDATE sys_tenant SET deleted_at.*?tenantId\);)",
             r"\3\2\1", t["ten_del"], count=1, flags=re.S)),
         ["D5"]),
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
