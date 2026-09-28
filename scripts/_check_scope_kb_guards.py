# -*- coding: utf-8 -*-
"""「配额管理随租户切换」+「知识库授权」两条链的静态守卫（无需启动服务）。

背景（2026-09-28，用户报障「配额管理不能切换租户，再修改知识库授权的问题」）：

**一、配额管理切换租户**
    管理端顶部的租户选择器只驱动 `api/tenantScope.ts` 里 `SCOPE_PARAMS` **声明过的**前缀。
    配额管理的接口挂在 `/admin/quotas*` 下，不在表里 ⇒ 切了租户请求里根本没有 `tenantId`，
    后端按 JWT 的 `tenantId`（平台管理员恒为 0）取数 ⇒ **看起来切了、数据纹丝不动**。
    这是 docs/37 §3 的同型缺陷，故守卫同时钉住「前端声明」与「后端真的接」两端：
    只声明不接（假声明）与只接不声明（哑接口）都是同一类静默失败。

**二、知识库授权**
    `catalog()` 不返回 `kb` 键，而前端读 `catalog.kb` ⇒ 下拉恒空，这一类资源授不出去。
    修法是把「授权」实现为既有的机构知识库挂载（生效态唯一来源 `kb_document.institution_id`），
    `resource_grant` 的 KB 行只是同一动作的账本镜像 —— 守卫要保证**两条路径同源**，
    不能出现「一方动了另一方没动」的幽灵行，也不能让写入退回「拿 UPDATE 影响行数当存在性判据」
    （MySQL 值未变化即报 0 行，会让重复保存被误判成资料不存在）。

本守卫断言：
    Q1  SCOPE_PARAMS 声明了 /admin/quotas → tenantId（不声明 = 切了不生效）
    Q2  AdminQuotaController 三个端点都接 tenantId 参数
    Q3  AdminQuotaController 的租户裁决走 ResourceTenantGuard（单一判定点）
    Q4  AdminQuotaController 不再直接用登录账号的 tenantId 取数（防回退）
    Q5  配额回执带 tenantId（展示与事实同源；前端据此对账）
    Q6  前端配额页的数据范围取自 tenantState（与切换器同一份来源）
    K1  catalog 返回 kb 键（缺它 = 下拉恒空）
    K2  可授权目录只含「租户共享」资料（不含他人 PERSONAL）
    K3  可授权目录只含未挂载（institution_id=0）的资料
    K4/K5/K6  grant / setEnabled / revoke 三条写路径都覆盖 KB
    K7  KB 生效动作带「占用守卫」（不静默搬走别家机构已挂的资料）
    K8  KB 存在性判据不依赖 UPDATE 影响行数（幂等重复保存不得误报 404）
    K9  OrgKbService.attach -> 账本同步（专线与授权清单同一份账本）
    K10 OrgKbService.detach -> 账本同步
    K11 前端「知识库」分组读 catalog.kb（映射未断）
    K12 授权套件含跨租户负向与收尾基线断言

★ 断言前**必须剥离注释**——本仓注释会复述这些关键字，按裸文本判定就是「谁写注释谁报红」。
用法：
    python scripts/_check_scope_kb_guards.py            # 跑检查
    python scripts/_check_scope_kb_guards.py --selftest # 自检：注入突变，必须真报红
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")

SCOPE_TS = os.path.join(SHELL, "api", "tenantScope.ts")
QUOTA_CTRL = os.path.join(SERVER, "aioa-resource", "src", "main", "java", "cn", "aioa",
                          "resource", "controller", "AdminQuotaController.java")
GRANT_SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                         "org", "service", "ResourceGrantService.java")
KB_SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "service", "OrgKbService.java")
KB_MAPPER = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                         "org", "mapper", "OrgStatMapper.java")
GRANT_VIEW = os.path.join(SHELL, "views", "ResourceGrantView.vue")
QUOTA_VIEW = os.path.join(SHELL, "views", "QuotaAdminView.vue")
SUITE = os.path.join(ROOT, "scripts", "e2e_quota_kb_fix.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_vue(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def load():
    return {
        "scope": _strip_vue(_read(SCOPE_TS)),
        "quota_ctrl": _strip_java(_read(QUOTA_CTRL)),
        "grant_svc": _strip_java(_read(GRANT_SVC)),
        "kb_svc": _strip_java(_read(KB_SVC)),
        "kb_mapper": _strip_java(_read(KB_MAPPER)),
        "grant_view": _strip_vue(_read(GRANT_VIEW)),
        "quota_view": _strip_vue(_read(QUOTA_VIEW)),
        "suite": _read(SUITE),
    }


def _seg(text, anchor, span=900):
    """取 anchor 之后的 span 个字符（用于把断言限定在某个方法体内）。"""
    i = text.find(anchor)
    return "" if i < 0 else text[i:i + span]


def _before(text, anchor, span=900):
    """取 anchor **之前**的 span 个字符。

    <p>为什么需要它：SQL 写在 `@Select(...)` 注解里，位于方法签名**上方**；
    从方法名往后切会拿到「只有签名、没有 SQL」的空段 —— 这类断言会永远不通过，
    于是守卫被改成恒真或干脆删掉（比没守卫更危险）。</p>
    """
    i = text.find(anchor)
    return "" if i < 0 else text[max(0, i - span):i]


def _between(text, start, end, span=4000):
    """取 [start, 下一个 end) 之间的正文 —— 长方法体必须按边界切，按字符数切会截断。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i)
    return text[i:j if j > i else i + span]


def checks(t):
    c = []
    scope, qc = t["scope"], t["quota_ctrl"]
    gs, ks, km = t["grant_svc"], t["kb_svc"], t["kb_mapper"]

    # ---------------- Q 配额管理随租户切换
    c.append(("Q1 SCOPE_PARAMS 声明了 /admin/quotas → tenantId",
              bool(re.search(r"\{\s*prefix:\s*'/admin/quotas'\s*,\s*param:\s*'tenantId'\s*\}", scope)),
              "未在作用域声明表里登记该前缀"))
    c.append(("Q2 AdminQuotaController 三个端点都接 tenantId 参数",
              len(re.findall(r'@RequestParam\(name = "tenantId"', qc)) >= 3,
              "命中 %d 处（应 ≥3：overview/assign/usage）"
              % len(re.findall(r'@RequestParam\(name = "tenantId"', qc))))
    c.append(("Q3 租户裁决走 ResourceTenantGuard（单一判定点）",
              "resolveTenantOrOwn" in qc and "ResourceTenantGuard" in qc,
              "未复用 ResourceTenantGuard"))
    c.append(("Q4 不再直接用登录账号的 tenantId 取数（防回退）",
              "getTenantId()" not in qc,
              "仍出现 getTenantId()：平台管理员会一直看到 tenant 0 的数据"))
    c.append(("Q5 配额回执带 tenantId（展示与事实同源）",
              qc.count('data.put("tenantId", tid)') >= 2
              and qc.count('"tenantId", tid') >= 3,
              "回执未回带实际作用租户"))
    c.append(("Q6 前端配额页数据范围取自 tenantState",
              "tenantState" in t["quota_view"] and "scopeText" in t["quota_view"],
              "页面未展示/未使用与顶部切换器同源的租户态"))

    # ---------------- K 知识库授权
    c.append(("K1 catalog 返回 kb 键（缺它 = 资源下拉恒空）",
              'out.put("kb"' in gs, "catalog() 未下发 kb"))
    kb_sql = _before(km, "List<Map<String, Object>> selectGrantableKb", 700)
    c.append(("K2 可授权目录只含租户共享资料（不含他人 PERSONAL）",
              "scope = 'TENANT'" in kb_sql, "目录 SQL 未限定 scope"))
    c.append(("K3 可授权目录只含未挂载（institution_id = 0）的资料",
              "institution_id = 0" in kb_sql, "目录 SQL 未限定未挂载"))
    for tag, start, end in (("K4", "public Map<String, Object> grant(", "public Map<String, Object> batchGrant("),
                            ("K5", "public Map<String, Object> setEnabled(", "@Transactional\n    public Map<String, Object> revoke("),
                            ("K6", "public Map<String, Object> revoke(", "// ================================================================== FR-J")):
        seg = _between(gs, start, end)
        name = start.split()[3].rstrip("(")
        if tag == "K6":
            # 撤销这一条光有「分支」不够：必须真的把资料解挂，否则「清单已删、机构知识库里还在」
            ok = "TYPE_KB.equals(" in seg and "bindKbDocument(g.getResId()" in seg
            detail = "该方法未处理 KB 或只删记录未解挂"
        else:
            ok, detail = "TYPE_KB.equals(" in seg, "该方法未处理 KB"
        c.append(("%s %s 覆盖 KB 分支" % (tag, name), ok, detail))
    bind = _seg(gs, "void applyKbBinding(")
    c.append(("K7 KB 生效动作带占用守卫（不静默搬走别家机构已挂的资料）",
              "selectKbInstitutionId" in bind, "applyKbBinding 未做占用检查"))
    c.append(("K8 存在性判据不依赖 UPDATE 影响行数（幂等不误报 404）",
              "selectKbNameInTenant" in bind
              and "int n = statMapper.bindKbDocument" not in ks,
              "仍在用 bindKbDocument 的影响行数判存在性"))
    attach = _between(ks, "public Map<String, Object> attach(", "public Map<String, Object> review(")
    c.append(("K9 OrgKbService.attach 同步授权账本",
              "syncKbLedger(" in attach and "true" in attach, "attach 未同步 resource_grant"))
    detach = _between(ks, "public Map<String, Object> detach(", "\n}")
    c.append(("K10 OrgKbService.detach 同步授权账本",
              "syncKbLedger(" in detach and "false" in detach, "detach 未同步 resource_grant"))
    c.append(("K11 前端「知识库」分组读 catalog.kb（映射未断）",
              "catalog.value.kb" in t["grant_view"], "分组未读 kb 键"))
    c.append(("K12 授权套件含跨租户负向 + 收尾基线断言",
              "B13" in t["suite"] and "D2" in t["suite"] and "D4" in t["suite"],
              "套件缺少跨租户负向或收尾断言"))
    return c


def run():
    cs = checks(load())
    bad = 0
    for name, ok, detail in cs:
        print(("  [OK]   " if ok else "  [FAIL] ") + name + ("" if ok else "  —— " + detail))
        bad += 0 if ok else 1
    print("\n=== 静态守卫 %d/%d 通过 ===" % (len(cs) - bad, len(cs)))
    return 1 if bad else 0


def selftest():
    base = load()
    mutations = [
        ("Q1 摘掉 /admin/quotas 作用域声明（退回「切了不生效」）",
         lambda t: dict(t, scope=t["scope"].replace(
             "{ prefix: '/admin/quotas', param: 'tenantId' }", "")),
         ["Q1"]),
        ("Q2 去掉 overview 的 tenantId 参数",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             '@RequestParam(name = "tenantId", required = false) Long tenantId) {\n        AuthUser actor = guard.requireTenantAdmin();\n        Long tid = tenantOf(actor, tenantId);\n        List<Map<String, Object>> users',
             ') {\n        AuthUser actor = guard.requireTenantAdmin();\n        Long tid = actor.getTenantId();\n        List<Map<String, Object>> users')),
         ["Q2", "Q4"]),
        ("Q3 退回各自裁决（不走守卫）",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             "guard.resolveTenantOrOwn(actor, tenantId)", "actor.getTenantId()")),
         ["Q3", "Q4"]),
        ("Q5 回执不再回带 tenantId",
         lambda t: dict(t, quota_ctrl=t["quota_ctrl"].replace(
             'data.put("tenantId", tid);', "")),
         ["Q5"]),
        ("K1 catalog 不下发 kb",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             'out.put("kb", statMapper.selectGrantableKb(tenantId));', "")),
         ["K1"]),
        ("K2 目录 SQL 放开 scope（会列出他人个人资料）",
         lambda t: dict(t, kb_mapper=t["kb_mapper"].replace(
             "AND institution_id = 0 AND scope = 'TENANT' ", "AND institution_id = 0 ")),
         ["K2"]),
        ("K4 grant() 不再处理 KB",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             'if (ResourceGrant.TYPE_KB.equals(resType)) {\n            applyKbBinding(tenantId, institutionId, resId, Boolean.TRUE.equals(g.getEnabled()));\n        }', "")),
         ["K4"]),
        ("K5 setEnabled() 不再处理 KB",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             'if (ResourceGrant.TYPE_KB.equals(g.getResType())) {\n            applyKbBinding(tenantId, g.getInstitutionId(), g.getResId(), enabled);\n        }', "")),
         ["K5"]),
        ("K6 revoke() 只删记录不解挂",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             'statMapper.bindKbDocument(g.getResId(), tenantId, 0L, 0L, "TENANT");', "")),
         ["K6"]),
        ("K7 去掉占用守卫（静默搬走别家机构的资料）",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             "Long current = statMapper.selectKbInstitutionId(docId);", "")),
         ["K7"]),
        ("K8 授权路径不再单独判存在性（退回拿影响行数当判据）",
         lambda t: dict(t, grant_svc=t["grant_svc"].replace(
             "statMapper.selectKbNameInTenant(docId, tenantId) == null",
             "false")),
         ["K8"]),
        ("K9 attach 不同步账本",
         lambda t: dict(t, kb_svc=t["kb_svc"].replace(
             "grantService.syncKbLedger(tenantId, institutionId, docId, docName, true);", "")),
         ["K9"]),
        ("K10 detach 不同步账本",
         lambda t: dict(t, kb_svc=t["kb_svc"].replace(
             "grantService.syncKbLedger(tenantId, institutionId, docId, null, false);", "")),
         ["K10"]),
        ("K11 前端分组改读不存在的键",
         lambda t: dict(t, grant_view=t["grant_view"].replace(
             "catalog.value.kb", "catalog.value.zzz")),
         ["K11"]),
        ("K12 套件去掉跨租户负向",
         lambda t: dict(t, suite=t["suite"].replace("B13", "X13")),
         ["K12"]),
    ]
    bad = 0
    for name, mutate, expect in mutations:
        t2 = mutate(base)
        if t2 == base:
            print("[FAIL] %s：突变未生效（锚点文本已变，请同步本守卫）" % name)
            bad += 1
            continue
        fired = {n.split()[0] for n, ok, _ in checks(t2) if not ok}
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
