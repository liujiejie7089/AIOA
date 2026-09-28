# -*- coding: utf-8 -*-
"""资源授权（FR-E）类型清单与租户隔离 的静态守卫（无需启动服务）。

背景（2026-09-28，用户报障「数字员工无法授权」）：
    真机复现：管理端「资源授权 → 新增授权 → 资源类型=数字员工」→ 保存
    → 后端 `code=400 不支持的资源类型：WORKER`。数字员工**永远授不出去**。

    根因不是一处笔误，而是**同一份类型清单被抄了三份**，其中两份漏了 WORKER：
      · `grant()` 的白名单（硬编码 4 类）         ← 拦住保存的那一道
      · `catalog().resTypes`（硬编码 4 类）       ← 与白名单同源、也跟着漏
      · `institutionResources()` 的 byType 预置（硬编码 4 类）
    而管理端下拉是第 4 份（手写 5 个选项，含数字员工）⇒ 前端给了入口、后端焊死了门。

    顺带暴露的第二个缺陷：`selectWorkers()` **没有任何租户过滤**，租户 2 的授权下拉里
    混进了租户 3 的数字员工（实测 11 条 = t0 3 + t2 4 + t3 4），选中即构成跨租户授权，
    违反 docs/15 §八「tenant_id 只从 JWT 取、跨租户一律 404」。

    这两类缺陷都是**静默**的：不报错、不留痕，只让"能选但保存必失败"和"下拉里混着别人的资产"
    长期存在。故必须静态钉死，不能只靠一次人工点检。

本守卫断言：
    W1  类型清单只有一处权威定义（ResourceGrant.ALL_TYPES），且含 WORKER
    W2  grant() 的白名单来自 ALL_TYPES，服务里不再有 4 类硬编码字面量
    W3  catalog().resTypes 从 ALL_TYPES 派生（不自己再列一遍）
    W4  机构侧 byType 的预置分组用 ALL_TYPES（否则授权成功也不可见）
    W5  selectWorkers 的 SQL 带租户过滤（跨租户隔离）
    W6  selectWorkers 的调用方真的把 tenantId 传进去了（有参数不传 = 仍全表）
    W7  前端类型下拉不再硬编码，改由目录驱动
    W8  前端类型选项取自 catalog.resTypes
    W9  前端分组键覆盖后端全部类型码（新增类型必须同步，否则「能选但选项恒空」）
    W10 前端 GrantCatalog 类型声明含 resTypes（否则 TS 层拿不到、退回硬编码）
    W11 授权 e2e 套件收尾必须删自建授权并断言回到基线（防残留漂移）

★ 断言前**必须剥离注释**（Java `//`、`/* */`；Web `<!-- -->`）—— 本仓注释会复述这些关键字，
  按裸文本判定就是"谁写注释谁报红"（pitfalls #75）。
用法：
    python scripts/_check_worker_grant_guards.py            # 跑检查
    python scripts/_check_worker_grant_guards.py --selftest # 自检：注入突变，必须真报红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")

ENTITY = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "entity", "ResourceGrant.java")
SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                   "org", "service", "ResourceGrantService.java")
MAPPER = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                      "org", "mapper", "OrgStatMapper.java")
VIEW = os.path.join(SHELL, "views", "ResourceGrantView.vue")
API_ORG = os.path.join(SHELL, "api", "org.ts")
SUITE = os.path.join(ROOT, "scripts", "e2e_worker_grant.py")

# 4 类硬编码的典型字面量（服务里若再出现 = 又开始抄第二份清单）
FOURTYPE_LITERAL = "List.of(ResourceGrant.TYPE_EXPERT, ResourceGrant.TYPE_SKILL"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def _seg(src, anchor, span=420):
    """取 anchor 之后的一段文本（用来把断言限定在某个方法/标签内，而不是全文命中）。"""
    if anchor not in src:
        return ""
    i = src.index(anchor)
    return src[i:i + span]


def _before(src, anchor, span=520):
    """取 anchor 之前的一段文本（用来读它上面挂的 @Select 注解）。"""
    if anchor not in src:
        return ""
    i = src.index(anchor)
    return src[max(0, i - span):i]


def checks(t):
    out = []
    entity, svc, mapper = t["entity"], t["svc"], t["mapper"]
    view, api = t["view"], t["api"]

    codes = re.findall(r'public static final String TYPE_(\w+)\s*=\s*"(\w+)"', entity)
    all_types = re.search(r"ALL_TYPES\s*=\s*List\.of\(([^)]*)\)", entity, re.S)
    names_seg = _seg(entity, "TYPE_NAMES = Map.of", 800)

    # ---- W1 类型清单唯一权威
    out.append((
        "W1 类型清单唯一权威 ALL_TYPES，且含 WORKER",
        bool(all_types) and "TYPE_WORKER" in all_types.group(1)
        and any(c[0] == "WORKER" for c in codes),
        "ALL_TYPES 命中=%s；声明的类型码=%s"
        % (bool(all_types), [c[1] for c in codes]),
    ))
    out.append((
        "W1b TYPE_NAMES 覆盖全部类型码（目录下发中文名的唯一来源）",
        len(codes) >= 5 and all(("TYPE_" + c[0]) in names_seg for c in codes),
        "codes=%s 未覆盖=%s"
        % ([c[0] for c in codes], [c[0] for c in codes if ("TYPE_" + c[0]) not in names_seg]),
    ))

    # ---- W2 白名单同源
    out.append((
        "W2 grant() 的白名单来自 ALL_TYPES，服务里不再有 4 类硬编码",
        "ResourceGrant.ALL_TYPES.contains(resType)" in svc
        and FOURTYPE_LITERAL not in svc
        and not [p for p, s in t["java_all"].items() if FOURTYPE_LITERAL in s],
        "白名单同源=%s；4 类硬编码残留=%s"
        % ("ResourceGrant.ALL_TYPES.contains(resType)" in svc,
           [os.path.basename(p) for p, s in t["java_all"].items() if FOURTYPE_LITERAL in s]),
    ))

    # ---- W3 目录 resTypes 同源
    out.append((
        "W3 catalog().resTypes 从 ALL_TYPES 派生",
        "ResourceGrant.ALL_TYPES.stream()" in _seg(svc, 'put("resTypes"', 260)
        or "ResourceGrant.ALL_TYPES.stream()" in svc,
        "resTypes 又开始自己列一遍 ⇒ 与白名单必然分叉",
    ))

    # ---- W4 机构侧分组预置同源
    out.append((
        "W4 机构侧 byType 预置分组用 ALL_TYPES（否则授权成功也看不见）",
        "for (String t : ResourceGrant.ALL_TYPES)" in svc,
        "byType 预置仍是 4 类 ⇒ WORKER 授权成功却不进分组",
    ))

    # ---- W5 selectWorkers 租户过滤
    sig5 = _seg(mapper, "List<Map<String, Object>> selectWorkers(", 120)
    out.append((
        "W5 selectWorkers 的 SQL 带租户过滤（docs/15 §八：tenant_id 只从 JWT 取）",
        "tenant_id = #{tenantId}" in _before(mapper, "List<Map<String, Object>> selectWorkers(")
        and '@Param("tenantId")' in sig5,
        "签名片段=%s" % sig5.replace("\n", " ")[:120],
    ))

    # ---- W6 调用方真的传了 tenantId
    calls = re.findall(r"statMapper\.selectWorkers\(([^)]*)\)", svc)
    out.append((
        "W6 selectWorkers 调用方把 tenantId 传进去了（有参数不传 = 仍全表）",
        len(calls) == 1 and "tenantId" in calls[0],
        "调用点=%s" % calls,
    ))

    # ---- W7 前端下拉由目录驱动
    seg_new = _seg(view, 'v-model="form.resType"', 300)
    seg_batch = _seg(view, 'v-model="batchType"', 300)
    out.append((
        "W7 前端类型下拉由目录驱动，不再硬编码选项",
        'v-for="t in typeOptions"' in seg_new
        and 'v-for="t in typeOptions"' in seg_batch
        and '<el-option label="数字员工"' not in view
        and 'value="WORKER"' not in view,
        "新增=%s 批量=%s 残留硬编码=%s"
        % ('v-for="t in typeOptions"' in seg_new,
           'v-for="t in typeOptions"' in seg_batch,
           'value="WORKER"' in view or '<el-option label="数字员工"' in view),
    ))

    # ---- W8 选项取自 catalog.resTypes
    out.append((
        "W8 前端 typeOptions 取自 catalog.resTypes",
        "catalog.value.resTypes" in view and "typeOptions" in view,
        "view 未从目录取类型清单",
    ))

    # ---- W9 分组键覆盖全部类型码
    cat_key = _seg(view, "const CAT_KEY", 260)
    missing = [c[1] for c in codes if c[1] not in cat_key]
    out.append((
        "W9 前端分组键覆盖后端全部类型码（新增类型必须同步，否则「能选但选项恒空」）",
        not missing,
        "未在 CAT_KEY 中映射的类型=%s（CAT_KEY=%s）"
        % (missing, cat_key.replace("\n", " ")[:200]),
    ))

    # ---- W10 TS 类型声明
    out.append((
        "W10 前端 GrantCatalog 声明含 resTypes",
        "resTypes?" in _seg(api, "interface GrantCatalog", 700),
        "TS 层拿不到 resTypes ⇒ 迟早退回硬编码",
    ))

    # ---- W11 套件收尾防残留
    out.append((
        "W11 授权 e2e 套件收尾删除自建授权并断言回到基线",
        'DELETE", "/api/v1/tenant/grants/%s" % created_id' in t["suite"]
        and "len(final) == len(base_grants)" in t["suite"],
        "套件会写库却不清残留 ⇒「与基线一致≠干净」，下次运行前置条件漂移",
    ))

    # ---- W12 资源下拉标签不得拼出 undefined
    # 数字员工的目录行没有 resKey（agent_worker 只有 id/name/status），无脑拼 `名称（resKey）`
    # 会渲染成「政策快讯员（undefined）」—— 真机实测到的一眼脏数据。必须按有无 key 分支。
    out.append((
        "W12 资源下拉标签按有无 resKey 分支，不拼出 undefined",
        "optLabel(" in view and "optLabel(r)" in view
        and "'（' + r.resKey + '）'" not in view,
        "view 里仍有裸拼 resKey 的标签 ⇒ 数字员工会显示（undefined）",
    ))

    return out


def load():
    java_files = [p for p in glob.glob(os.path.join(SERVER, "**", "*.java"), recursive=True)
                  if os.sep + "target" + os.sep not in p]
    return {
        "entity": _strip_java(_read(ENTITY)),
        "svc": _strip_java(_read(SVC)),
        "mapper": _strip_java(_read(MAPPER)),
        "view": _strip_web(_read(VIEW)),
        "api": _strip_web(_read(API_ORG)),
        "suite": _read(SUITE),
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
    """注入突变，要求对应断言**必须真报红**；突变未生效（SKIP）同样计失败（pitfalls #77）。"""
    base = load()
    mutations = [
        ("W1 删掉 TYPE_WORKER（回到漏 WORKER 的旧状态）",
         lambda t: dict(t, entity=t["entity"].replace(
             'public static final String TYPE_WORKER = "WORKER";', "")),
         ["W1"]),
        ("W1b TYPE_NAMES 漏一个类型",
         lambda t: dict(t, entity=t["entity"].replace('TYPE_WORKER, "数字员工");', ");")),
         ["W1b"]),
        ("W2 白名单退回 4 类硬编码（就是本次缺陷的原形）",
         lambda t: dict(t, svc=t["svc"].replace(
             "if (!ResourceGrant.ALL_TYPES.contains(resType)) {",
             "if (!List.of(ResourceGrant.TYPE_EXPERT, ResourceGrant.TYPE_SKILL, "
             "ResourceGrant.TYPE_MODEL, ResourceGrant.TYPE_KB).contains(resType)) {")),
         ["W2"]),
        ("W3 目录 resTypes 自己再列一遍",
         lambda t: dict(t, svc=t["svc"].replace(
             "ResourceGrant.ALL_TYPES.stream()",
             "List.of(ResourceGrant.TYPE_EXPERT, ResourceGrant.TYPE_SKILL).stream()")),
         ["W2", "W3"]),
        ("W4 机构侧仍只预置 4 类",
         lambda t: dict(t, svc=t["svc"].replace(
             "for (String t : ResourceGrant.ALL_TYPES) {",
             "for (String t : List.of(ResourceGrant.TYPE_EXPERT)) {")),
         ["W4"]),
        ("W5 去掉 selectWorkers 的租户过滤（跨租户串号）",
         lambda t: dict(t, mapper=t["mapper"].replace(
             "WHERE deleted_at IS NULL AND tenant_id = #{tenantId} ORDER BY id LIMIT 200",
             "WHERE deleted_at IS NULL ORDER BY id LIMIT 200")),
         ["W5"]),
        ("W6 调用方不传 tenantId",
         lambda t: dict(t, svc=t["svc"].replace(
             "statMapper.selectWorkers(tenantId)", "statMapper.selectWorkers(0L)")),
         ["W6"]),
        ("W7 前端退回硬编码下拉",
         lambda t: dict(t, view=t["view"].replace(
             '<el-option v-for="t in typeOptions" :key="t.code" :label="t.name" :value="t.code" />',
             '<el-option label="数字员工" value="WORKER" />')),
         ["W7"]),
        ("W8 前端不从目录取类型",
         lambda t: dict(t, view="\n".join(
             ln for ln in t["view"].splitlines() if "catalog.value.resTypes" not in ln)),
         ["W8"]),
        ("W9 新增类型却不同步分组键",
         lambda t: dict(t, view=t["view"].replace(
             "KB: 'kb', WORKER: 'workers'", "KB: 'kb'")),
         ["W9"]),
        ("W10 TS 声明漏掉 resTypes",
         lambda t: dict(t, api=t["api"].replace("  resTypes?: { code: string; name: string }[]", "")),
         ["W10"]),
        ("W11 套件不再清理自建授权（残留漂移）",
         lambda t: dict(t, suite=t["suite"].replace(
             'call("DELETE", "/api/v1/tenant/grants/%s" % created_id, t_admin)',
             'None')),
         ["W11"]),
        ("W12 资源下拉退回裸拼 resKey（数字员工显示 undefined）",
         lambda t: dict(t, view=t["view"].replace(
             ':label="optLabel(r)"',
             ':label="' + "(r.name || r.resKey) + '（' + r.resKey + '）'" + '"')),
         ["W12"]),
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
