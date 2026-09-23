# -*- coding: utf-8 -*-
"""知识库「共享资料可见性」口径静态守卫（防同类复发，无需启动服务）。

背景（2026-09-21 定位）：
    大数据管理局（租户管理员）共享了知识库后，自己在管理端「知识库」页一条都看不到 ——
    默认 tab 就是「租户全部资料」，而 `KbController` 的该分支裸判 `ROLE_ADMIN`，
    把租户管理员 403 掉，表格渲染成「租户内暂无资料」，提示语却是「仅租户管理员可见」
    （自相矛盾）。全仓其余管理端控制器（AdminQuota / AdminConfig / AdminAudit /
    AdminBizSystem / AdminResult / AdminKpi）一律按「平台管理员 ∨ 租户管理员」判定，
    `PermissionCatalog.isAdmin` 正是这条口径的唯一入口 —— KbController 是唯一漏网的一处。

本守卫断言：
    C1 KbController 不得出现裸判 ROLE_ADMIN（`contains("ROLE_ADMIN")` / `"ROLE_ADMIN".equals`）
    C2 KbController 的 `scope=tenant` 分支必须用 `PermissionCatalog.isAdmin(`
    C3 KbController 的 isAdmin 判据至少 4 处（list / update / remove / isVisible），
       保证「能看」与「能改」同源，不会各写一套
    C4 管理端 KbView「租户全部资料」tab 必须带 `v-if="canReadTenant"`
       （否则机构管理员/成员一进页面就落在注定 403 的空表上）
    C5 KbView 的 tab 初值必须由 canReadTenant 决定，不得硬编码 'tenant'
    C6 KbView 的行级「可见范围 / 操作」必须受 `canModify(row)` 约束
       （否则点了必 403，与用户端 H5 的「他人共享资料只读」规则不一致）

用法：
    python scripts/_check_kb_permission.py            # 跑检查
    python scripts/_check_kb_permission.py --selftest # 自检：注入突变，必须真报红
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_CTRL = os.path.join(
    ROOT, "server", "aioa-resource", "src", "main", "java", "cn", "aioa",
    "resource", "controller", "KbController.java")
KB_VIEW = os.path.join(ROOT, "web", "apps", "shell", "src", "views", "KbView.vue")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def checks(java: str, vue: str):
    """对给定文本跑全部断言，返回 [(id, ok, detail)]。"""
    out = []

    # ---- C1 后端：不得裸判 ROLE_ADMIN
    naked = re.findall(r'(?:contains\(\s*"ROLE_ADMIN"|"ROLE_ADMIN"\s*\.equals)', java)
    out.append(("C1 KbController 不得裸判 ROLE_ADMIN",
                not naked,
                "一处都不能有（租户管理员会被误 403）" if not naked
                else f"发现 {len(naked)} 处裸判：{naked}"))

    # ---- C2 后端：scope=tenant 分支必须走权威判据
    m = re.search(r'"tenant"\.equalsIgnoreCase\(scope\)\s*\)\s*\{(.*?\n\s*\}\s*else)',
                  java, re.S)
    if not m:
        out.append(("C2 scope=tenant 分支使用 PermissionCatalog.isAdmin",
                    False, "未能定位 scope=tenant 分支（源码结构变了，请同步本守卫）"))
    else:
        ok = "PermissionCatalog.isAdmin(" in m.group(1)
        out.append(("C2 scope=tenant 分支使用 PermissionCatalog.isAdmin", ok,
                    "已走唯一入口" if ok else "该分支没有调用 PermissionCatalog.isAdmin"))

    # ---- C3 后端：判据同源且数量到位
    n = len(re.findall(r"PermissionCatalog\.isAdmin\(", java))
    out.append(("C3 KbController 的 isAdmin 判据 >= 4 处（看/改同源）", n >= 4,
                f"实际 {n} 处"))

    # ---- C4 前端：租户 tab 受权限约束
    has_if = re.search(r'<el-tab-pane\s+v-if="canReadTenant"\s+label="租户全部资料"', vue)
    out.append(("C4 「租户全部资料」tab 带 v-if=\"canReadTenant\"", bool(has_if),
                "已受权限约束" if has_if else "该 tab 无条件渲染 ⇒ 非租户管理员会看到 403 空表"))

    # ---- C5 前端：默认 tab 由权限决定
    ok5 = bool(re.search(r"ref<'tenant'\s*\|\s*'mine'>\(canReadTenant\.value\s*\?", vue))
    out.append(("C5 默认 tab 由 canReadTenant 决定（不得硬编码 'tenant'）", ok5,
                "已按权限落地" if ok5 else "tab 初值未按权限选择"))

    # ---- C6 前端：行级操作受 canModify 约束
    ok6 = (len(re.findall(r"canModify\(row\)", vue)) >= 2
           and "function canModify(" in vue)
    out.append(("C6 行级「可见范围/操作」受 canModify(row) 约束", ok6,
                f"canModify 出现 {len(re.findall(r'canModify\(row\)', vue))} 次"
                if ok6 else "未对无权修改的行收口（点了必 403）"))
    return out


def run():
    java, vue = _read(KB_CTRL), _read(KB_VIEW)
    res = checks(java, vue)
    for cid, ok, detail in res:
        print(f"[{'PASS' if ok else 'FAIL'}] {cid}  —— {detail}")
    bad = [c for c in res if not c[1]]
    print(f"\n=== {len(res) - len(bad)}/{len(res)} passed ===")
    return 1 if bad else 0


# ------------------------------------------------------------------ 自检

def selftest():
    base_java, base_vue = _read(KB_CTRL), _read(KB_VIEW)
    assert not [c for c in checks(base_java, base_vue) if not c[1]], \
        "自检前提不成立：当前源码本身就有 FAIL，先修源码"

    mutations = [
        ("M1 后端改回裸判 ROLE_ADMIN",
         lambda j, v: (j.replace('if (!PermissionCatalog.isAdmin(user)) {',
                                 'if (!user.getRoles().contains("ROLE_ADMIN")) {', 1), v),
         ["C1", "C2"]),
        ("M2 去掉 tab 的 v-if=\"canReadTenant\"",
         lambda j, v: (j, v.replace('<el-tab-pane v-if="canReadTenant" label="租户全部资料"',
                                    '<el-tab-pane label="租户全部资料"', 1)),
         ["C4"]),
        ("M3 tab 初值改回硬编码 'tenant'",
         lambda j, v: (j, v.replace("ref<'tenant' | 'mine'>(canReadTenant.value ? 'tenant' : 'mine')",
                                    "ref<'tenant' | 'mine'>('tenant')", 1)),
         ["C5"]),
        ("M4 去掉可见范围 select 的 canModify 收口",
         lambda j, v: (j, v.replace('<el-select\n              v-if="canModify(row)"',
                                    '<el-select', 1)),
         ["C6"]),
    ]

    bad = 0
    for name, mutate, expect in mutations:
        j2, v2 = mutate(base_java, base_vue)
        if (j2, v2) == (base_java, base_vue):
            print(f"[FAIL] {name}：突变未生效（锚点文本变了，请同步本守卫）")
            bad += 1
            continue
        fired = {c[0].split()[0] for c in checks(j2, v2) if not c[1]}
        miss = [e for e in expect if e not in fired]
        if miss:
            print(f"[FAIL] {name}：注入后未报红 {miss}（守卫失效）")
            bad += 1
        else:
            print(f"[PASS] {name}：真报红 {sorted(fired)}")
    print(f"\n=== 自检 {len(mutations) - bad}/{len(mutations)} 通过 ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else run())
