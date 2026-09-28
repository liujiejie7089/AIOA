# -*- coding: utf-8 -*-
"""机构类型收敛 + 统一社会信用代码校验的静态守卫（docs/38 批次 B，无需启动服务）。

背景（2026-09-27 实测定位）：
    机构类型此前**两处各写一套且互不相同** —— 后端 `OrgInstitution` 只有
    GOVERNMENT / ENTERPRISE / ASSOCIATION，前端 `InstitutionView.vue` 却是
    GOVERNMENT / INSTITUTION / STATE_OWNED / PRIVATE / ASSOCIATION。后果全是**不报错**的那种：
      · 库里最多的 `ENTERPRISE` 在管理端下拉里**选不到**（编辑既有企业机构时下拉显示裸码）；
      · 用户选「国有企业 / 民营企业」→ 写库 `STATE_OWNED` / `PRIVATE` → 后端不认识、列表标签标不出来。
    信用代码则**完全不校验**（长度/字符/重复都能落库）。

    这类缺陷的共同点是：**收敛之后没有任何"报错"来提醒你又退回去了** ——
    只要有人图省事在前端再写一份下拉，或在别处再写一份正则，缺陷就静默复活。
    所以必须用静态守卫把它钉死。

本守卫断言：
    O1  机构类型的清单/常量只由 `OrgInstitution` 定义；全仓 Java 不得再出现旧取值字面量
    O2  五类齐全且标签与规格一致（政府机关/企业/事业单位/社会组织/其他）
    O3  写入侧一律经 `OrgInstitution.requireOrgType`（create 与 update 各一处，且不得绕过）
    O4  信用代码的判定（字符集/形状正则）只存在于 `CreditCode.java`
    O5  信用代码唯一性在建行之前判定，且**排除自身**（否则编辑自身必报重复）
    O6  字典端点存在、且与其它机构端点同权限口径（requireTenantAdmin）
    O7  前端已收敛：不得硬编码机构类型选项/标签表；必须取字典并用它渲染（**去注释后**判定）
    O8  前端不得自写信用代码正则（否则又是两处判定）
    O9  演示种子脚本不得再发旧取值（STATE_OWNED / PRIVATE）

★ 断言前**必须剥离注释**：本仓多处注释会复述这些关键字（如说明"此前硬编 STATE_OWNED"），
  按裸文本判定会把解释性注释当成违规 —— 那是"谁写注释谁报红"（pitfalls #75）。
用法：
    python scripts/_check_org_types_and_credit_guards.py            # 跑检查
    python scripts/_check_org_types_and_credit_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")
SCRIPTS = os.path.join(ROOT, "scripts")

ENTITY = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "entity", "OrgInstitution.java")
SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                   "org", "service", "InstitutionService.java")
CREDIT = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "support", "CreditCode.java")
TENANT_CTRL = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                           "org", "controller", "TenantAdminController.java")
VIEW = os.path.join(SHELL, "views", "InstitutionView.vue")
API_ORG = os.path.join(SHELL, "api", "org.ts")
SEED = os.path.join(SCRIPTS, "seed_multi_tenant.py")

# 旧前端取值：任何一个都不该再出现（DB 实测无这两类数据，故无需兼容映射）
LEGACY = ["STATE_OWNED", "PRIVATE"]
# 信用代码字符集的**唯一**合法归属
CREDIT_CHARSET = "[0-9A-HJ-NPQRTUWXY]"
EXPECT_LABELS = ["政府机关", "企业", "事业单位", "社会组织", "其他"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    """Vue/TS：再去掉 HTML 注释（`<!-- -->`）。"""
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def checks(t):
    out = []
    entity, svc, credit, ctrl = t["entity"], t["svc"], t["credit"], t["ctrl"]
    view, api, seed = t["view"], t["api"], t["seed"]

    # ---- O1 清单唯一：**定义**只在 OrgInstitution；全仓 Java 无旧取值
    # 注意判据必须是「定义」（`public static final String TYPE_GOVERNMENT =`）而不是「出现」——
    # 调用方（InstitutionService/Controller）当然会引用 `OrgInstitution.TYPE_ENTERPRISE`，
    # 把引用算成第二处定义会让这条断言永远报红（同族坑见 pitfalls #75：断言要判事实、不判"出现过"）。
    # 扫描的是**已装载的文本表**（而非现读磁盘），否则自检注入的突变到不了这里、这条断言无法被验证。
    defs = [p for p, s in t["java_all"].items()
            if re.search(r"public static final String TYPE_GOVERNMENT\s*=", s)]
    legacy_java = [p for p, s in t["java_all"].items()
                   if any('"%s"' % x in s for x in LEGACY)]
    out.append((
        "O1 机构类型清单只由 OrgInstitution 定义 + 全仓无旧取值字面量",
        len(defs) == 1 and os.path.basename(defs[0]) == "OrgInstitution.java" and not legacy_java,
        "定义处 %s；旧取值残留 %s" % ([os.path.basename(p) for p in defs],
                                     [os.path.basename(p) for p in legacy_java]),
    ))

    # ---- O2 五类齐全且标签一致
    out.append((
        "O2 五类齐全且标签与规格一致",
        all(('TYPES.put(TYPE_%s, "%s");' % (code, label)) in entity
            for code, label in zip(["GOVERNMENT", "ENTERPRISE", "INSTITUTION",
                                    "ASSOCIATION", "OTHER"], EXPECT_LABELS)),
        "缺类型或标签不符（当前 TYPES 段：%s）" % entity[entity.find("static {"):][:220],
    ))

    # ---- O3 写入侧一律经 requireOrgType
    # 允许的写法只有两种：① 参数是已经过校验的局部变量 `orgType`；② 参数是内联的 requireOrgType 调用。
    # 其它任何形态（例如直接 `it.setOrgType(Vals.str(body, "orgType"))`）就是绕过校验 ——
    # 这正是收敛前的老写法，必须报红。
    n_req = svc.count("OrgInstitution.requireOrgType(")
    args = [a.strip() for a in re.findall(r"it\.setOrgType\(([^;]*)\);", svc)]
    allowed = all(a == "orgType" or a.startswith("OrgInstitution.requireOrgType(") for a in args)
    out.append((
        "O3 写入侧一律经 requireOrgType（create/update 各一处，无绕过）",
        "String orgType = OrgInstitution.requireOrgType(" in svc
        and n_req >= 2 and bool(args) and allowed,
        "requireOrgType 调用 %d 处；setOrgType 实参 %s（n_req/args 不满足即有人绕过校验）"
        % (n_req, args),
    ))

    # ---- O4 信用代码判定唯一
    owners = [p for p, s in t["java_all"].items() if CREDIT_CHARSET in s]
    other = [p for p in owners if os.path.basename(p) != "CreditCode.java"]
    out.append((
        "O4 信用代码字符集/形状判定只在 CreditCode.java",
        len(owners) == 1 and not other
        and "public static String normalize(String raw)" in credit
        and "public static boolean isValid(String normalized)" in credit,
        "第二处实现：%s" % [os.path.basename(p) for p in other],
    ))

    # ---- O5 唯一性在建行之前 + 排除自身
    ok5 = False
    detail5 = "唯一性判定缺失、或未排除自身、或发生在建行之后"
    if "creditCodeOf(Vals.str(body, \"creditCode\"), null)" in svc \
            and "institutionMapper.insert(it);" in svc \
            and ".ne(OrgInstitution::getId, excludeInstitutionId)" in svc:
        i_call = svc.index("creditCodeOf(Vals.str(body, \"creditCode\"), null)")
        i_ins = svc.index("institutionMapper.insert(it);")
        ok5 = i_call < i_ins
        detail5 = "调用位=%s 建行位=%s" % (i_call, i_ins) if not ok5 else ""
    out.append(("O5 唯一性在建行之前判定且排除自身", ok5, detail5))

    # ---- O6 字典端点与权限口径
    ok6 = False
    detail6 = "缺字典端点，或权限口径与其它机构端点不一致"
    if '@GetMapping("/institution-types")' in ctrl:
        seg = ctrl.split('@GetMapping("/institution-types")', 1)[1][:400]
        ok6 = "guard.requireTenantAdmin()" in seg
    out.append(("O6 字典端点存在且要求租户管理员", ok6, detail6))

    # ---- O7 前端收敛
    hard_opts = re.findall(r'<el-option[^>]*value="(?:GOVERNMENT|ENTERPRISE|INSTITUTION'
                           r'|ASSOCIATION|OTHER|STATE_OWNED|PRIVATE)"', view)
    legacy_web = [x for x in LEGACY if x in view]
    out.append((
        "O7 前端不得硬编码机构类型选项/标签表，且必须用字典渲染",
        not hard_opts and not legacy_web and "ORG_TYPES" not in view
        and "listInstitutionTypes" in view
        and 'v-for="t in orgTypes"' in view,
        "硬编码选项 %s；旧取值 %s；ORG_TYPES=%s；取字典=%s；v-for=%s"
        % (hard_opts, legacy_web, "ORG_TYPES" in view,
           "listInstitutionTypes" in view, 'v-for="t in orgTypes"' in view),
    ))

    # ---- O8 前端不得自写信用代码正则
    web_credit = [n for n, s in (("InstitutionView.vue", view), ("api/org.ts", api))
                  if "[0-9A-HJ-NPQRTUWXY]" in s or "[A-HJ-NPQRTUWXY]" in s]
    out.append((
        "O8 前端不得自写信用代码正则（判定只在后端一处）",
        not web_credit, "前端第二处实现：%s" % web_credit,
    ))

    # ---- O9 种子脚本不得再发旧取值
    seed_legacy = [x for x in LEGACY if x in seed]
    out.append((
        "O9 演示种子脚本不得再发旧取值",
        not seed_legacy and "'orgType': 'ENTERPRISE'" in seed,
        "仍含 %s" % seed_legacy,
    ))

    return out


def load():
    java_files = [p for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True)
                  if os.sep + "target" + os.sep not in p]
    return {
        "entity": _strip_java(_read(ENTITY)),
        "svc": _strip_java(_read(SVC)),
        "credit": _strip_java(_read(CREDIT)),
        "ctrl": _strip_java(_read(TENANT_CTRL)),
        "view": _strip_web(_read(VIEW)),
        "api": _strip_web(_read(API_ORG)),
        "seed": _read(SEED),
        # 全仓 Java 文本（去注释）——"只在某一处" 类断言都基于它，自检可注入合成文件
        "java_all": {p: _strip_java(_read(p)) for p in java_files},
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
        ("O1 第二处定义机构类型清单",
         lambda t: dict(t, java_all=dict(t["java_all"], **{
             "__synthetic__.java":
                 'public static final String TYPE_GOVERNMENT = "GOVERNMENT";'})),
         ["O1"]),
        ("O1b 旧取值字面量回到 Java 里",
         lambda t: dict(t, java_add_legacy=(
             'String t = "STATE_OWNED";'),
             java_all=dict(t["java_all"], **{
                 "__synthetic_legacy__.java": 'String t = "STATE_OWNED";'})),
         ["O1"]),
        ("O2 标签写错",
         lambda t: dict(t, entity=t["entity"].replace(
             'TYPES.put(TYPE_ASSOCIATION, "社会组织");', 'TYPES.put(TYPE_ASSOCIATION, "社团");')),
         ["O2"]),
        ("O3 绕过校验直接 setOrgType",
         lambda t: dict(t, svc=t["svc"].replace(
             "it.setOrgType(orgType);", 'it.setOrgType(Vals.str(body, "orgType"));')),
         ["O3"]),
        ("O4 信用代码判定复制第二份",
         lambda t: dict(t, java_all=dict(t["java_all"], **{
             "__synthetic_cc__.java":
                 'String p = "[0-9A-HJ-NPQRTUWXY]{2}\\\\d{6}[0-9A-HJ-NPQRTUWXY]{10}";'})),
         ["O4"]),
        ("O5 唯一性不排除自身（编辑自身必报重复）",
         lambda t: dict(t, svc=t["svc"].replace(
             ".ne(OrgInstitution::getId, excludeInstitutionId)", "")),
         ["O5"]),
        ("O6 字典端点漏掉权限校验",
         lambda t: dict(t, ctrl=t["ctrl"].replace(
             '        guard.requireTenantAdmin();\n'
             '        return ApiResponse.ok(institutionService.typeOptions());',
             '        return ApiResponse.ok(institutionService.typeOptions());')),
         ["O6"]),
        ("O7 前端塞回硬编码选项",
         lambda t: dict(t, view=t["view"].replace(
             '<el-option v-for="t in orgTypes" :key="t.code" :label="t.label" :value="t.code" />',
             '<el-option label="政府机关" value="GOVERNMENT" />')),
         ["O7"]),
        ("O7b 前端标签表复活",
         lambda t: dict(t, view=t["view"].replace(
             "const orgTypes = ref<InstitutionType[]>([])",
             "const ORG_TYPES: Record<string, string> = { GOVERNMENT: '政府机关' }\n"
             "const orgTypes = ref<InstitutionType[]>([])")),
         ["O7"]),
        ("O8 前端自写信用代码正则",
         lambda t: dict(t, view=t["view"].replace(
             "function orgTypeText(v?: string) {",
             "const CREDIT_RE = /[0-9A-HJ-NPQRTUWXY]{2}\\d{6}[0-9A-HJ-NPQRTUWXY]{10}/\n"
             "function orgTypeText(v?: string) {")),
         ["O8"]),
        ("O9 种子脚本发旧取值",
         lambda t: dict(t, seed=t["seed"] + "\n{'orgType': 'STATE_OWNED'}\n"),
         ["O9"]),
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
    print("\n=== 自检 %d/%d 通过 ===" % (len(mutations) - bad, len(mutations)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
