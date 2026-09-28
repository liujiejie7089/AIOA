# -*- coding: utf-8 -*-
"""员工「开户口令可知性」链路的静态守卫（V67 批次 C·补（口令可知性），无需启动服务）。

背景（2026-09-28，用户报障「新增的员工无法登录用户端」）：
    实测新账号**能**登录（统一演示口令 User@123），真正的缺陷是**凭据不可知** ——
    管理端「新增员工（自动开户）」表单既没有口令输入、成功也不回显口令，
    服务端又只存 BCrypt 哈希、事后无法回读 ⇒ 操作员拿到一个"建好了但进不去"的账号。

    这一批的危险点全是**静默**的，一个都不会抛错：
      · 表单传了口令但服务层没接 ⇒ 输入的密码被悄悄丢弃，账号还是默认口令；
      · 回显的口令与真正写入的哈希不是同一决策点 ⇒ 操作员拿着**错的**凭据去试（比不回显更坏）；
      · 账号本来就存在（口令未被改动）却照样回显一个"初始口令" ⇒ 假话（铁律 #1）；
      · 批量导入没有口令列、又不回传统一口令 ⇒ 导入上千人后一个都登不进去（同一缺陷类）；
      · 漏记口令后没有「重置」这个正常出口 ⇒ 只能删员工重建，连带丢掉审批/通知归属；
      · 口令写进审计 ⇒ 长期留存、多人可见的凭据泄漏；
      · mapper 里同一方法声明两次 ⇒ **编译失败**（2026-09-28 真实踩到：本批与子租户批次各加了一份）；
      · 后端做了能力、管理端没有入口 ⇒ 能力事实上不可用（铁律 #4）。

本守卫断言：
    C1  `DEMO_PASSWORD_HASH` 只在 `hashOf` 一个方法体里被引用（明文与哈希同一决策点）
    C2  `effectivePassword`（回显用）与 `hashOf`（写库用）的判空分支必须同源
    C3  `createMember` 必须把表单 `password` 真的传进开户调用（不能丢弃）
    C4  `createMember` 只在**确实新建**账号时才回传 `initialPassword`（否则是假话）
    C5  `importMembers` 在新建账号时回传统一口令（导入表格没有口令列）
    C6  `updateUserPassword` 在 mapper 里**只声明一次**（重复声明 = 编译失败）
    C7  `resetPassword` 走 `updateUserPassword` 这个唯一写入口，且 0 行要报错
    C8  端点 `POST /org/members/{id}/password` 存在且要求写权限
    C9  管理端真接出来：新增弹窗有口令输入、行内有「口令」重置入口；且前端**不复刻**口令常量
    C10 名册列表不得把口令当可读字段渲染（只写不读）
    C11 重置口令的审计不得带明文口令

★ 断言前必须剥离注释（Java `//`、`/* */`；Web `<!-- -->`）—— 本仓注释会复述这些关键字，
  按裸文本判定就是"谁写注释谁报红"（pitfalls #75）。

用法：
    python scripts/_check_member_login_credential_guards.py            # 跑检查
    python scripts/_check_member_login_credential_guards.py --selftest # 自检：注入突变，必须真报红
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORG = os.path.join(ROOT, "server", "aioa-org", "src", "main", "java", "cn", "aioa", "org")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")

PROV = os.path.join(ORG, "support", "AccountProvisioner.java")
TREE = os.path.join(ORG, "service", "OrgTreeService.java")
CTRL = os.path.join(ORG, "controller", "OrgAdminController.java")
MAPPER = os.path.join(ORG, "mapper", "OrgStatMapper.java")
VIEW = os.path.join(SHELL, "views", "OrgStructureView.vue")
API = os.path.join(SHELL, "api", "org.ts")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def _body_containing(src, keyword):
    """返回所有「方法体」中含 keyword 的方法名集合（用 public/private 签名切段）。"""
    parts = re.split(r"\n    (?:public|private|protected)\s", "\n    public " + src)
    hits = set()
    for seg in parts:
        m = re.match(r"[\w<>,\[\]\. ]*\s+(\w+)\s*\(", seg)
        if m and keyword in seg:
            hits.add(m.group(1))
    return hits


def _method_body(src, name):
    """取某个方法（含签名）到下一个方法/注解之前的源码段。

    断言必须**切到方法体内**：本仓同一个关键字会在多处出现（`Vals.str(body, "password")`
    新建与重置各用一次），按全文匹配就会"改了 A 处、B 处还能顶替它通过"（pitfalls #77）。
    """
    m = re.search(r"\n    (?:public|private|protected)\s[^\n]*?\b" + re.escape(name) + r"\s*\(", src)
    if not m:
        return ""
    rest = src[m.end():]
    nxt = re.search(r"\n    (?:@|public |private |protected )", rest)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(rest))]


def checks(t):
    out = []
    prov, tree, ctrl, mapper, view, api = (t["prov"], t["tree"], t["ctrl"],
                                           t["mapper"], t["view"], t["api"])

    # ---- C1 明文与哈希同一决策点
    holders = sorted(_body_containing(prov, "DEMO_PASSWORD_HASH"))
    out.append((
        "C1 DEMO_PASSWORD_HASH 只在 hashOf 内被引用（单一决策点）",
        holders == ["hashOf"],
        "引用它的方法体：%s（应为 ['hashOf']）" % holders,
    ))

    # ---- C2 回显分支与写库分支同源
    cond = "plainPassword == null || plainPassword.isBlank()"
    hbody, ebody = _method_body(prov, "hashOf"), _method_body(prov, "effectivePassword")
    out.append((
        "C2 effectivePassword 与 hashOf 的判空分支同源",
        cond in hbody and cond in ebody,
        "hashOf=%s effectivePassword=%s（分叉 ⇒ 操作员会拿到错的口令，比不回显更坏）"
        % (cond in hbody, cond in ebody),
    ))

    # ---- C3 createMember 真传口令
    cbody = _method_body(tree, "createMember")
    out.append((
        "C3 createMember 把表单 password 传进开户调用",
        'Vals.str(body, "password")' in cbody and "plainPassword);" in cbody,
        "createMember 内未把 password 传入 ⇒ 表单里输入的口令被静默丢弃",
    ))

    # ---- C4 只在真新建时回传
    out.append((
        "C4 createMember 仅在新建账号时回传 initialPassword",
        # 判据必须取反：usernameExists=true 表示**已存在**。2026-09-28 真实写错过一次
        # （写成 `boolean newAccount = accounts.usernameExists(...)` ⇒ 新账号永远不回显）。
        "boolean newAccount = !accounts.usernameExists(username);" in cbody
        and "if (newAccount) {" in cbody
        and "public boolean usernameExists(String username)" in prov,
        "判据写反/无条件回传 ⇒ 要么永远不回显、要么在账号已存在时说假话（铁律 #1）",
    ))

    # ---- C5 批量导入也要回传
    ibody = _method_body(tree, "importMembers")
    out.append((
        "C5 importMembers 在新建账号时回传统一初始口令",
        "int newAccounts = 0;" in ibody and "if (newAccounts > 0) {" in ibody
        and 'out.put("initialPassword"' in ibody,
        "导入表格没有口令列 ⇒ 不回传就等于导进去的人全都登不进",
    ))

    # ---- C6 mapper 声明唯一（重复声明 = 编译失败）
    n_decl = len(re.findall(r"\n\s+int\s+updateUserPassword\s*\(", mapper))
    out.append((
        "C6 updateUserPassword 只声明一次",
        n_decl == 1,
        "声明 %d 次（>1 直接编译失败；2026-09-28 真实踩到）" % n_decl,
    ))

    # ---- C7 resetPassword 走唯一写入口且不静默
    rsp = _method_body(prov, "resetPassword")
    out.append((
        "C7 resetPassword 走 updateUserPassword 且 0 行报错",
        "statMapper.updateUserPassword(userId, hashOf(plainPassword)) == 0" in rsp,
        "重置口令必须复用同一写入口，且账号不存在时要报错（不可逆动作不得静默成功）",
    ))

    # ---- C8 重置端点存在且要写权限
    seg = ctrl.split('@PostMapping("/members/{id}/password")', 1)[-1][:500] \
        if '@PostMapping("/members/{id}/password")' in ctrl else ""
    out.append((
        "C8 重置口令端点存在且要求写权限",
        "resetMemberPassword(" in seg and "guard.requireOrgWriter()" in seg,
        "端点缺失或权限未校验（requireOrgWriter=%s）" % ("requireOrgWriter()" in seg),
    ))

    # ---- C9 管理端真接出来 + 不复刻口令常量
    out.append((
        "C9 管理端有口令输入与重置入口，且不复刻口令常量",
        'v-model="memberForm.password"' in view
        and "resetPwd(row)" in view
        and "resetMemberPassword" in api
        and "User@123" not in view
        and "User@123" not in api,
        "输入=%s 重置入口=%s api=%s 前端硬编码User@123=%s"
        % ('v-model="memberForm.password"' in view, "resetPwd(row)" in view,
           "resetMemberPassword" in api, "User@123" in view or "User@123" in api),
    ))

    # ---- C10 口令只写不读
    out.append((
        "C10 名册列表不得把口令当可读字段渲染",
        "prop=\"password\"" not in view and "row.password" not in view,
        "口令出现在读路径上 ⇒ 明文口令会随列表下发",
    ))

    # ---- C11 审计不带明文口令
    # 口径：审计的 after 载荷只能是 `Map.of("userId", uid)`（载荷里出现第二个键就可能夹带口令）；
    # 摘要里允许出现 `plain`，但只能是**判空**用法（`plain == null` / `plain.isBlank()`），
    # 不允许把它拼进文案（`+ plain`）——后者才是把凭据写进长期留存日志。
    rpbody = _method_body(tree, "resetMemberPassword")
    rb = rpbody.split("MEMBER_RESET_PASSWORD", 1)[-1].split(");", 1)[0] \
        if "MEMBER_RESET_PASSWORD" in rpbody else ""
    out.append((
        "C11 重置口令的审计不得带明文口令",
        rb != ""
        and "initialPassword" not in rb
        and 'Map.of("userId", uid, ' not in rb
        and "+ plain" not in rb,
        "审计载荷=%s（after 只应带 userId；摘要不得拼接明文）" % (rb.strip()[-60:] or "（未找到审计调用）"),
    ))

    # ---- C12 授权角色必须先复活软删行（否则同账号再入职 ⇒ 唯一键 500）
    gr = _method_body(prov, "grantRole")
    out.append((
        "C12 grantRole 先 revive 再 insert（sys_user_role 软删行占唯一键）",
        "statMapper.reviveUserRole(userId, roleId, operatorId) == 0" in gr
        and "reviveUserRole" in mapper
        and "UPDATE sys_user_role SET deleted_at = NULL" in mapper,
        "移除员工（revokeRole 软删角色行）后再用同一账号新增 ⇒ Duplicate entry '…' 500",
    ))

    return out


def load():
    return {
        "prov": _strip_java(_read(PROV)),
        "tree": _strip_java(_read(TREE)),
        "ctrl": _strip_java(_read(CTRL)),
        "mapper": _strip_java(_read(MAPPER)),
        "view": _strip_web(_read(VIEW)),
        "api": _strip_web(_read(API)),
    }


def run():
    base = load()
    results = checks(base)
    bad = [c for c in results if not c[1]]
    for cid, ok, detail in results:
        print(("  [OK]   " if ok else "  [FAIL] ") + cid + (("  " + detail) if (detail and not ok) else ""))
    print("\n=== 正向 %d/%d 通过 ===" % (len(results) - len(bad), len(results)))
    return 1 if bad else 0


def selftest():
    """注入突变，要求对应断言**必须真报红**；突变未生效（SKIP）同样计失败（pitfalls #77）。"""
    base = load()
    mutations = [
        ("C1 别处也写死哈希",
         lambda t: dict(t, prov=t["prov"].replace(
             "        row.put(\"passwordHash\", hash);",
             "        row.put(\"passwordHash\", DEMO_PASSWORD_HASH);")),
         ["C1"]),
        ("C2 回显分支与写库分叉",
         lambda t: dict(t, prov=t["prov"].replace(
             "return plainPassword == null || plainPassword.isBlank() ? DEMO_PASSWORD : plainPassword;",
             "return plainPassword == null || plainPassword.isEmpty() ? DEMO_PASSWORD : plainPassword;")),
         ["C2"]),
        ("C3 createMember 丢弃表单口令",
         lambda t: dict(t, tree=t["tree"].replace(
             "        String plainPassword = Vals.str(body, \"password\");",
             "        String plainPassword = null;")),
         ["C3"]),
        ("C4 无条件回传初始口令",
         lambda t: dict(t, tree=t["tree"].replace(
             "boolean newAccount = !accounts.usernameExists(username);",
             "boolean newAccount = true;")),
         ["C4"]),
        ("C5 导入不回传初始口令",
         lambda t: dict(t, tree=t["tree"].replace("if (newAccounts > 0) {", "if (false) {")),
         ["C5"]),
        ("C6 mapper 重复声明",
         lambda t: dict(t, mapper=t["mapper"].replace(
             "    int updateUserPassword(@Param(\"userId\") Long userId,",
             "    int updateUserPassword(@Param(\"userId\") Long uid2,\n"
             "                         @Param(\"passwordHash\") String h2);\n"
             "    int updateUserPassword(@Param(\"userId\") Long userId,")),
         ["C6"]),
        ("C7 resetPassword 静默成功",
         lambda t: dict(t, prov=t["prov"].replace(
             "if (statMapper.updateUserPassword(userId, hashOf(plainPassword)) == 0) {",
             "if (false) {")),
         ["C7"]),
        ("C8 重置端点漏权限校验",
         lambda t: dict(t, ctrl=t["ctrl"].replace(
             'guard.requireOrgWriter();\n        return ApiResponse.ok(treeService.resetMemberPassword(',
             'cn.aioa.security.AuthUserContext.require();\n        return ApiResponse.ok(treeService.resetMemberPassword(')),
         ["C8"]),
        ("C9 前端硬编码口令常量",
         lambda t: dict(t, view=t["view"].replace(
             "function resetPwd", "const PWD = 'User@123'\nfunction resetPwd")),
         ["C9"]),
        ("C10 列表渲染口令字段",
         lambda t: dict(t, view=t["view"].replace(
             "function resetPwd", "const leak = row.password\nfunction resetPwd")),
         ["C10"]),
        ("C11 审计带明文口令",
         lambda t: dict(t, tree=t["tree"].replace(
             'null, Map.of("userId", uid));', 'null, Map.of("userId", uid, "pwd", plain));')),
         ["C11"]),
        ("C12 角色授权不再复活软删行（同账号再入职必 500）",
         lambda t: dict(t, prov=t["prov"].replace(
             "if (statMapper.reviveUserRole(userId, roleId, operatorId) == 0) {",
             "if (true) {")),
         ["C12"]),
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
