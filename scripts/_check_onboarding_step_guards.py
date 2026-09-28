# -*- coding: utf-8 -*-
"""入驻「8 步路线图」的静态守卫（无需启动服务）。

背景（2026-09-28，用户需求）：
    「入驻进度页面应展示完整的 8 个步骤，每个步骤需标注已完成/未完成状态；
      对于未完成的步骤，支持点击后跳转至该步骤对应的设置页面，
      并明确步骤之间的先后顺序与当前所处的步骤位置。」

    这条需求有三处**静默失败**风险，全靠静态约定兜住：

      · **「完整 8 步」可能被截断** —— 若某步的展示依赖「已解锁/已通过」，页面就画不满 8 个。
        故 `progress()` 必须对全部 STEPS 出项，`TOTAL_STEPS` 必须等于 STEPS 条数。
      · **「当前步骤」可能有两个口径** —— 既有持久化游标 `onboard_step`，又有实时门禁 `passed`；
        两者跨月会分叉（第 3/5/7/8 步按 nowPeriod 取数）。若 `unlocked` 只看「前序全通过」，
        已推进的机构会在每月 1 号被**级联锁死** 4~8 步。故 `unlocked` 必须由
        `prevConfirmed = prevConfirmed && (done || recorded)` 推出。
      · **「点击跳转」可能跳空或跳错页** —— 每步的落点必须由后端下发（`route`），
        前端一旦自己再写一份路由字面量，后端改路由时前端会静默失效（铁律 #1）。

本守卫断言：
    S1  STEPS 定义唯一且条数 == TOTAL_STEPS（8），步骤号 1..8 连续无洞
    S2  每步都有非空的 route 与 routeLabel（不给死按钮）
    S3  定义接口与进度接口同源（Controller 的 steps() 用 service 的定义，不复刻）
    S4  unlocked 由「通过或已确认推进」累积推出（跨月不级联锁死）
    S5  currentStep 在「已推进满 8 步」时为 null（不每月重现「当前步」）
    S6  前端用后端下发的 route，且**不复刻**任何步骤路由字面量
    S7  前端对 currentStep=null 有明确呈现（「8 步已全部完成」）
    S8  每步 route 都在前端路由表里真实存在（避免点了跳空白页）
    S9  未解锁步骤给出「需先完成第 N 步」（顺序可见，不只是灰掉）

★ 断言前**必须剥离注释**（Java `//`、`/* */`；Web `<!-- -->`）—— 本仓注释会复述这些关键字，
  按裸文本判定就是"谁写注释谁报红"（pitfalls #75）。
用法：
    python scripts/_check_onboarding_step_guards.py            # 跑检查
    python scripts/_check_onboarding_step_guards.py --selftest # 自检：注入突变，必须真报红
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
SHELL = os.path.join(ROOT, "web", "apps", "shell", "src")

SVC = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                   "org", "service", "OnboardingService.java")
CTRL = os.path.join(SERVER, "aioa-org", "src", "main", "java", "cn", "aioa",
                    "org", "controller", "OnboardingController.java")
VIEW = os.path.join(SHELL, "views", "OnboardingView.vue")
ROUTER = os.path.join(SHELL, "router", "index.ts")

EXPECT_KEYS = ["TENANT_PROVISION", "INSTITUTION_BUILD", "RESOURCE_GRANT", "COST_RULE",
               "ORG_BUILD", "CAPABILITY_ON", "MEMBER_RUN", "SETTLE_RECONCILE"]

# 前端不得出现的路由字面量（这些都是「每步跳哪里」的答案，只能来自后端 route）
ROUTE_LITERALS = ["'/quotas'", "'/institutions'", "'/resource-grants'", "'/cost-alloc'",
                  "'/org-structure'", "'/kb'", "'/approvals'"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_java(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _strip_web(src):
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    return _strip_java(src)


def steps_block(svc):
    """截取 STEPS = List.of(...) 的定义块。"""
    m = re.search(r"List<StepDef>\s+STEPS\s*=\s*List\.of\(", svc)
    if not m:
        return ""
    i = m.end()
    depth = 1
    while i < len(svc) and depth > 0:
        if svc[i] == "(":
            depth += 1
        elif svc[i] == ")":
            depth -= 1
        i += 1
    return svc[m.start():i]


def parse_steps(block):
    """返回 [(step, key, name, owner, gate, route, routeLabel), ...]"""
    pat = (r'new StepDef\(\s*(\d+)\s*,\s*"([A-Z_]+)"\s*,\s*"([^"]+)"\s*,\s*"([A-Z_]+)"\s*,'
           r'\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')
    return [(int(a), b, c, d, e, f, g) for a, b, c, d, e, f, g in re.findall(pat, block, re.S)]


def router_paths(router_src):
    out = set()
    for m in re.finditer(r"path:\s*'([^']+)'", router_src):
        p = m.group(1)
        out.add(p if p.startswith("/") else "/" + p)
    return out


def checks(t):
    out = []
    svc, ctrl, view = t["svc"], t["ctrl"], t["view"]
    block = steps_block(svc)
    steps = parse_steps(block)

    # ---- S1 定义唯一、条数与 TOTAL_STEPS 一致、步骤号连续
    total = re.search(r"TOTAL_STEPS\s*=\s*(\d+)", svc)
    total_n = int(total.group(1)) if total else -1
    out.append((
        "S1 STEPS 条数与 TOTAL_STEPS 一致，且步骤号 1..8 连续",
        len(steps) == 8 and total_n == 8
        and [s[0] for s in steps] == list(range(1, 9))
        and [s[1] for s in steps] == EXPECT_KEYS,
        "解析到 %d 步(step=%s key=%s) TOTAL_STEPS=%s"
        % (len(steps), [s[0] for s in steps], [s[1] for s in steps], total_n),
    ))

    # ---- S2 每步都有落点
    missing = [s[0] for s in steps
               if not s[5].strip().startswith("/") or not s[6].strip()]
    out.append((
        "S2 每步都有可跳转的 route 与 routeLabel（不给死按钮）",
        not missing, "缺落点的步骤=%s" % missing,
    ))

    # ---- S3 定义与进度同源
    out.append((
        "S3 定义接口复用 service 的步骤定义（不复刻一份）",
        "onboardingService.stepDefinitions()" in ctrl
        and "public List<Map<String, Object>> stepDefinitions()" in svc,
        "Controller 里的 steps() 没有走 service 定义 ⇒ 两处口径",
    ))

    # ---- S4 unlocked 由「通过或已确认」累积
    out.append((
        "S4 unlocked = 前序每步「已通过或已确认推进」（跨月不级联锁死）",
        "prevConfirmed = prevConfirmed && (done || recorded);" in svc
        and "boolean unlocked = prevConfirmed;" in svc,
        "unlocked 未由已确认累积推出 ⇒ 新月份会把历史进度锁死",
    ))

    # ---- S5 满 8 步时 currentStep 为 null
    out.append((
        "S5 currentStep 在已推进满 8 步时为 null",
        re.search(r"if\s*\(\s*reached\s*<\s*TOTAL_STEPS\s*&&\s*firstNotPassed\s*!=\s*0\s*\)", svc)
        is not None,
        "缺少「已满 8 步则不给当前步」的判定 ⇒ 每月 1 号重现「当前步」",
    ))

    # ---- S6 前端用后端 route，不复刻字面量
    copied = [lit for lit in ROUTE_LITERALS if lit in view]
    out.append((
        "S6 前端跳转用后端下发的 route，不复刻路由字面量",
        "router.push(s.route)" in view and not copied,
        "硬编码的路由字面量=%s（应改用 s.route，铁律 #1）" % copied,
    ))

    # ---- S7 前端处理 currentStep=null
    out.append((
        "S7 前端对 currentStep=null 给出明确呈现（8 步已全部完成）",
        "8 步" in view and "已全部完成" in view and "headCurrentStep != null" in view,
        "currentStep 为 null 时页面文案不明 ⇒ 用户以为卡住了",
    ))

    # ---- S8 route 都真实存在
    paths = router_paths(t["router"])
    dead = sorted({s[5] for s in steps if s[5] not in paths})
    out.append((
        "S8 每步 route 都在前端路由表里真实存在（避免点了跳空白页）",
        len(paths) >= 20 and not dead,
        "路由表命中 %d 条；不存在的 route=%s" % (len(paths), dead),
    ))

    # ---- S9 未解锁给出「需先完成第 N 步」
    out.append((
        "S9 未解锁步骤给出「需先完成第 N 步」（顺序可见）",
        "blockedByStep" in view and "需先完成第" in view,
        "未解锁只灰掉不说为什么 ⇒ 顺序性看不见",
    ))

    return out


def load():
    return {
        "svc": _strip_java(_read(SVC)),
        "ctrl": _strip_java(_read(CTRL)),
        "view": _strip_web(_read(VIEW)),
        "router": _read(ROUTER),
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
        ("S1 少定义一步（8 → 7）",
         lambda t: dict(t, svc=t["svc"].replace(
             'new StepDef(8, "SETTLE_RECONCILE"', 'new StepDefX(8, "SETTLE_RECONCILE"')),
         ["S1"]),
        ("S1b TOTAL_STEPS 与实际条数脱节",
         lambda t: dict(t, svc=t["svc"].replace("TOTAL_STEPS = 8", "TOTAL_STEPS = 7")),
         ["S1"]),
        ("S2 某步漏了 route",
         lambda t: dict(t, svc=t["svc"].replace('"/org-structure", "去搭建组织"', '"", ""')),
         ["S2"]),
        ("S3 定义接口自己复刻一份",
         lambda t: dict(t, ctrl=t["ctrl"].replace(
             "onboardingService.stepDefinitions()", "List.of()")),
         ["S3"]),
        ("S4 unlocked 退回「前序全通过」（跨月级联锁死）",
         lambda t: dict(t, svc=t["svc"].replace(
             "prevConfirmed = prevConfirmed && (done || recorded);",
             "prevConfirmed = prevConfirmed && done;")),
         ["S4"]),
        ("S5 去掉「满 8 步不给当前步」判定",
         lambda t: dict(t, svc=t["svc"].replace(
             "if (reached < TOTAL_STEPS && firstNotPassed != 0) {", "if (firstNotPassed != 0) {")),
         ["S5"]),
        ("S6 前端硬编码路由字面量",
         lambda t: dict(t, view=t["view"].replace(
             "await router.push(s.route)", "await router.push('/quotas')")),
         ["S6"]),
        ("S7 前端不再处理 currentStep=null",
         lambda t: dict(t, view=t["view"].replace("8 步", "N 步")),
         ["S7"]),
        ("S8 某步 route 指向不存在的页面",
         lambda t: dict(t, svc=t["svc"].replace('"/kb", "去启用能力"', '"/kb-not-exist", "去启用能力"')),
         ["S8"]),
        ("S9 未解锁不再说明卡在第几步",
         lambda t: dict(t, view=t["view"].replace("需先完成第", "按顺序")),
         ["S9"]),
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
