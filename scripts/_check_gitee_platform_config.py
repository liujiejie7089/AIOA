#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓库联动「平台级参数动态配置」哨兵 —— 静态断言 + 接口往返 + 负向对照。

## 它防的是什么

本次改造把 Gitee 平台参数（OAuth 应用凭据 / Webhook 公网基址 / 授权跳转域 / scope / 平台默认组织）
从「只能由环境变量注入」改为「管理端『仓库配置』页可改、落库、保存即生效」。这类改造有四类
**静默**失效，静态检查查不出来：

1. **适配器漏读覆盖层**：某个字段在 `RepoProviderSettingsAdapter` 里仍直读 `GiteeProperties`
   → 管理端改了它，页面显示「已保存」，业务却还用旧值。**这是最危险的一类**：症状是
   「配置保存成功但建仓还是建到老组织下」，没人会把这两件事联系起来。
2. **字段三处口径漂移**：覆盖层枚举 / 实体列 / 前端 `GiteePlatformFieldKey` 各写一份，
   加字段时漏改一处 → 某字段永远不可配或永远不渲染。
3. **Secret 以明文回传或明文落库**：一次泄漏就出现在浏览器内存、日志、抓包里。
4. **校验缺口**：scope 缺 `hook` 不报错（本项目实测过两次），配错后表现为「建仓成功但 Webhook 被拒」。

## 用法

    python scripts/_check_gitee_platform_config.py            # 只跑静态断言（无需服务）
    python scripts/_check_gitee_platform_config.py --api       # 静态 + 接口往返（需后端在跑）
    python scripts/_check_gitee_platform_config.py --selftest  # 自检：证明每条静态断言**会红**

## 退出码

    0  全部通过
    1  有断言失败
    2  前置不满足（未跑接口或接口不通过）—— **不伪装 PASS**

`--api` 需要：
  * 后端 :8080 在跑，且**已包含本次改动**（否则 /gitee/platform-config 404 → 记 SKIP）；
  * 平台管理员账号（默认 admin / Admin@123，可用 --user/--password 覆盖）。

**安全约定（2026-10-10 修）**：Secret 子项写入后**读不回明文**，故一旦覆盖即不可还原。
若平台参数里**已配置真实 Secret**（生产常态），本脚本改为**只读校验**（不回写）；
仅在原本未配置时才写入测试假值，并在复原时**显式清空**（空串＝显式清空），
避免把「未配置」伪装成「已配置」、或把真实凭据覆盖成假值。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 常量（与代码同源的单一词表）

FIELDS = [
    "enabled", "clientId", "clientSecret", "redirectUri", "oauthAuthorizeBaseUrl",
    "scope", "org", "webhookBaseUrl", "bindReturnUrl",
]

# 刻意**不在**可覆盖范围内的参数（放进 UI 会产生「保存了但没生效」或「自毁密文」）
FORBIDDEN_FIELDS = ["tokenEncKey", "baseUrl", "webBaseUrl", "webhookSecret"]

ADAPTER = "server/aioa-gitee/src/main/java/cn/aioa/gitee/config/RepoProviderSettingsAdapter.java"
OVERLAY = "server/aioa-gitee/src/main/java/cn/aioa/gitee/config/PlatformConfigOverlay.java"
ENTITY = "server/aioa-gitee/src/main/java/cn/aioa/gitee/entity/GiteePlatformConfig.java"
SERVICE = "server/aioa-gitee/src/main/java/cn/aioa/gitee/service/GiteePlatformConfigService.java"
CONTROLLER = "server/aioa-gitee/src/main/java/cn/aioa/gitee/controller/GiteeController.java"
MIGRATION = "server/aioa-boot/src/main/resources/db/migration/V77__gitee_platform_config.sql"
TS_API = "web/apps/shell/src/api/gitee.ts"
VUE = "web/apps/shell/src/views/GiteeProjectsView.vue"
GITEE_CLIENT = "server/aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteeClient.java"
GITEA_CLIENT = "server/aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteaProviderClient.java"

# 可覆盖字段的 getter：客户端**必须经 RepoProviderSettings 端口**取这些值，
# 不得直接读原始 *Properties bean（原始 bean 只含环境变量值，绕过管理端覆盖层）。
OVERRIDABLE_GETTERS = [
    "getClientId", "getClientSecret", "getRedirectUri",
    "getOauthAuthorizeBaseUrl", "getScope",
]


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        raise FileNotFoundError(rel)
    return p.read_text(encoding="utf-8", errors="replace")


def enum_to_key(enum_name: str) -> str:
    """CLIENT_ID → clientId；OAUTH_AUTHORIZE_BASE_URL → oauthAuthorizeBaseUrl。"""
    parts = enum_name.lower().split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


# ---------------------------------------------------------------- 静态断言（纯函数，便于自检）


def s1_adapter_covers_all(adapter_src: str):
    """适配器对所有可覆盖字段都必须走 adminValue 覆盖层。"""
    found = {enum_to_key(m) for m in re.findall(r"adminValue\(Field\.([A-Z_]+)\)", adapter_src)}
    missing = [f for f in FIELDS if f not in found]
    return (not missing, f"覆盖层命中 {len(found)}/{len(FIELDS)}，缺 {missing or '无'}")


def s2_overlay_field_names(overlay_src: str):
    """覆盖层的 FIELD_NAMES 必须与词表一致（它是静态断言的锚点）。"""
    m = re.search(r"FIELD_NAMES\s*=\s*\{(.*?)\};", overlay_src, re.S)
    if not m:
        return (False, "未找到 FIELD_NAMES 声明")
    got = re.findall(r'"([^"]+)"', m.group(1))
    return (got == FIELDS, f"FIELD_NAMES={got}")


def s3_entity_columns(entity_src: str):
    """实体必须含 provider + 全部 9 个字段（列缺失 ⇒ 该字段永远无法落库）。"""
    got = set(re.findall(r"private\s+\w+\s+(\w+)\s*;", entity_src))
    missing = [f for f in FIELDS if f not in got]
    ok = "provider" in got and not missing
    return (ok, f"缺字段 {missing or '无'}；provider={'有' if 'provider' in got else '缺'}")


def s4_ts_field_union(ts_src: str):
    """前端 GiteePlatformFieldKey 必须与词表一致（否则字段渲染不出来）。"""
    m = re.search(r"export type GiteePlatformFieldKey\s*=(.*?)\n\n", ts_src, re.S)
    if not m:
        return (False, "未找到 GiteePlatformFieldKey 联合类型")
    got = re.findall(r"'([^']+)'", m.group(1))
    return (got == FIELDS, f"前端键={got}")


def s5_service_keys(service_src: str):
    """服务里的 KEYS 映射必须登记全部 9 个字段（视图与保存都按它走）。"""
    got = [enum_to_key(m) for m in re.findall(r"KEYS\.put\(K_\w+,\s*Field\.([A-Z_]+)\)", service_src)]
    return (got == FIELDS, f"KEYS={got}")


def s6_forbidden_excluded(overlay_src: str):
    """会自毁密文 / 属部署身份的参数**不得**进入可覆盖集合。"""
    m = re.search(r"FIELD_NAMES\s*=\s*\{(.*?)\};", overlay_src, re.S)
    if not m:
        return (False, "未找到 FIELD_NAMES 声明")
    names = re.findall(r'"([^"]+)"', m.group(1))
    # 必须按**完整字段名**比对，不能子串匹配：`baseUrl` 是 `webhookBaseUrl` 的子串，
    # 子串匹配会把合法字段误判成违规（假阳性），而假阳性会让人开始忽略这条断言。
    bad = [f for f in FORBIDDEN_FIELDS if f in names]
    return (not bad, f"被禁止的字段出现在 FIELD_NAMES：{bad or '无'}")


def s7_migration_present(migration_src: str):
    """迁移必须建表，且写明「刻意不纳入」的理由（否则后人会顺手补上自毁按钮）。"""
    ok_tbl = "gitee_platform_config" in migration_src and "CREATE TABLE IF NOT EXISTS" in migration_src
    ok_reason = "token-enc-key" in migration_src and "刻意" in migration_src
    return (ok_tbl and ok_reason, f"建表={ok_tbl} 写明排除理由={ok_reason}")


def s8_secret_encrypted(service_src: str):
    """Secret 落库前必须加密、读出后必须解密。"""
    ok_enc = "crypto.encrypt(" in service_src
    ok_dec = "crypto.decrypt(" in service_src
    return (ok_enc and ok_dec, f"加密={ok_enc} 解密={ok_dec}")


def s9_controller_endpoints(controller_src: str):
    """三个端点必须存在，且都过平台管理员守卫。"""
    has_get = '@GetMapping("/platform-config")' in controller_src
    has_put = '@PutMapping("/platform-config")' in controller_src
    has_del = '@DeleteMapping("/platform-config")' in controller_src
    guards = controller_src.count("requirePlatformAdmin()")
    return (has_get and has_put and has_del and guards >= 4,
            f"GET={has_get} PUT={has_put} DELETE={has_del} 守卫调用={guards}")


def s10_secret_not_returned(service_src: str):
    """视图层必须把 Secret 恒置空串（唯一对外口径是 clientSecretConfigured）。"""
    m = re.search(r'values\.put\(K_CLIENT_SECRET,\s*"([^"]*)"\)', service_src)
    ok = bool(m) and m.group(1) == ""
    return (ok, "视图 Secret 恒为空串" if ok else "视图可能回传了 Secret")


def s11_card_outside_module_guard(vue_src: str):
    """
    「平台参数」卡必须渲染在 `moduleEnabled` 守卫**之外**。

    它是把模块 enabled 打开的地方 —— 若跟着「未启用就不取数」一起被跳过，
    模块一旦 `enabled=false`（生产默认即如此），管理员就**再也进不去把它打开**（死锁）。
    2026-10-10 实测：卡片曾被放在 `<template v-else>`（= moduleEnabled 为真的那一支）里，
    注释写着「不在守卫内」而结构上却在守内 ⇒ 必须由断言钉死，不能靠注释。
    """
    m = re.search(r'<el-card\s+v-if="([^"]*isPlatformAdmin[^"]*)"', vue_src)
    if not m:
        return (False, "未找到平台参数卡（带 isPlatformAdmin 守卫的 el-card）")
    cond = m.group(1)
    if "moduleEnabled" in cond:
        return (False, f"卡片自身 v-if 含 moduleEnabled：{cond}")
    card_at = m.start()
    guards = [mm.start() for mm in re.finditer(
        r'<template\s+v-else\s*>|<template\s+v-if="[^"]*moduleEnabled', vue_src)]
    if not guards:
        return (False, "未找到 moduleEnabled 守卫块（模板结构已变，需人工确认）")
    first_guard = min(guards)
    return (card_at < first_guard, f"卡片@ {card_at} 早于 moduleEnabled 守卫@ {first_guard}")


def s12_clients_route_overridable_fields_through_port(gitee_src: str):
    """
    两个 Provider 客户端对**可覆盖字段**必须走端口（`settings.*`），不得读原始 `*Properties`。

    缺陷背景（2026-10-10 生产实测）：用户绑定 Gitee 时登录后被回
    `{"error":"Application does not exist"}`；抓到的授权 URL 是
    `https://gitee.com/oauth/authorize?client_id=&redirect_uri=...` —— `client_id` 为空。
    根因：`GiteeClient.authorizeUrl()` 当时直接读 `props.getClientId()`（原始 bean 只有**环境变量**值），
    绕过了「管理端覆盖层 → 回落环境变量」的 `RepoProviderSettings` 端口 ⇒
    **页面改的是这个值、真正发出去的是另一个值**（页面显示 client-id 已配置，URL 里却是空）。

    这类缺陷**不报错**、单测 happy-path 也测不出（除非专门断言「生效值进了 URL」），
    只在真机上表现为「配了却没用」。故此处静态钉死：凡可覆盖字段的 getter，客户端里
    只允许出现 `settings.` 前缀；不可覆盖项（`getBaseUrl` / `getWebBaseUrl` / 超时 / 分页 /
    `getRepoNameMaxLength`）不在此列，仍取原始 bean（那是部署身份与调优参数）。
    """
    bad = []
    pairs = ((GITEE_CLIENT, gitee_src),)
    # 第二个文件自行读取：断言契约是「一文件一函数」，而本约束跨两个文件
    pairs += ((GITEA_CLIENT, read(GITEA_CLIENT)),)
    for rel, src in pairs:
        short = Path(rel).name
        for g in OVERRIDABLE_GETTERS:
            if f"props.{g}(" in src:
                bad.append(f"{short}:props.{g}(")
        # Gitea 的授权域经 oauthAuthorizeUrl() 从原始 bean 派生，同属绕过端口
        if "props.oauthAuthorizeUrl(" in src:
            bad.append(f"{short}:props.oauthAuthorizeUrl(")
    return (not bad, f"客户端直读原始 bean 的可覆盖字段：{bad or '无'}")


STATIC_CHECKS = [
    ("S1 适配器全部字段走覆盖层", ADAPTER, s1_adapter_covers_all),
    ("S2 覆盖层 FIELD_NAMES 与词表一致", OVERLAY, s2_overlay_field_names),
    ("S3 实体含 provider + 9 字段", ENTITY, s3_entity_columns),
    ("S4 前端字段联合类型与词表一致", TS_API, s4_ts_field_union),
    ("S5 服务 KEYS 登记全部字段", SERVICE, s5_service_keys),
    ("S6 自毁/部署类参数未被纳入覆盖", OVERLAY, s6_forbidden_excluded),
    ("S7 迁移建表且写明排除理由", MIGRATION, s7_migration_present),
    ("S8 Secret 落库加密、读出解密", SERVICE, s8_secret_encrypted),
    ("S9 三端点齐备且过平台管理员守卫", CONTROLLER, s9_controller_endpoints),
    ("S10 视图不回传 Secret", SERVICE, s10_secret_not_returned),
    ("S11 平台参数卡在 moduleEnabled 守卫之外", VUE, s11_card_outside_module_guard),
    ("S12 客户端可覆盖字段走端口（非原始 bean）", GITEE_CLIENT,
     s12_clients_route_overridable_fields_through_port),
]


def run_static(verbose=True):
    passed, failed = 0, []
    for name, rel, fn in STATIC_CHECKS:
        try:
            ok, detail = fn(read(rel))
        except FileNotFoundError:
            ok, detail = False, f"文件不存在：{rel}"
        if ok:
            passed += 1
            if verbose:
                print(f"  [PASS] {name} —— {detail}")
        else:
            failed.append(f"{name} —— {detail}")
            print(f"  [FAIL] {name} —— {detail}")
    return passed, failed


# ---------------------------------------------------------------- 自检（证明断言会红）


def selftest():
    """
    负向自检：把每条静态断言依赖的源码做「一处真实退化」，断言**必须变红**。

    不这么做的话，「全绿」无法区分「真的合规」与「断言写错了、恒真」——
    后者比没有断言更危险（本项目已有 `chk(name, True, "")` 的前车之鉴）。
    """
    print("== 自检：逐条制造退化，断言必须变红 ==")
    fails = []

    def expect_red(name, fn, mutated):
        ok, detail = fn(mutated)
        if ok:
            fails.append(f"{name} 退化后仍为绿 —— 断言失效")
            print(f"  [FAIL] {name} 退化后**仍绿**（断言无效）")
        else:
            print(f"  [ok] {name} 退化后变红：{detail[:70]}")

    adapter = read(ADAPTER)
    expect_red("S1", s1_adapter_covers_all, adapter.replace("adminValue(Field.SCOPE)", "null"))
    overlay = read(OVERLAY)
    expect_red("S2", s2_overlay_field_names, overlay.replace('"webhookBaseUrl",', ""))
    expect_red("S6", s6_forbidden_excluded,
               overlay.replace('"scope", "org",', '"scope", "tokenEncKey", "org",'))
    entity = read(ENTITY)
    expect_red("S3", s3_entity_columns, entity.replace("private String webhookBaseUrl;", ""))
    ts = read(TS_API)
    expect_red("S4", s4_ts_field_union, ts.replace("  | 'bindReturnUrl'\n", ""))
    service = read(SERVICE)
    expect_red("S5", s5_service_keys, service.replace("KEYS.put(K_ORG, Field.ORG);", ""))
    expect_red("S8", s8_secret_encrypted, service.replace("crypto.encrypt(", "noop("))
    expect_red("S10", s10_secret_not_returned, service.replace('values.put(K_CLIENT_SECRET, "")',
                                                              "values.put(K_CLIENT_SECRET, rawSecret)"))
    migration = read(MIGRATION)
    expect_red("S7", s7_migration_present, migration.replace("token-enc-key", "nothing"))
    controller = read(CONTROLLER)
    expect_red("S9", s9_controller_endpoints, controller.replace('@PutMapping("/platform-config")',
                                                                 '@PostMapping("/platform-config-x")'))
    vue = read(VUE)
    # 退化形态 = 把「开总开关的那张卡」重新挂回 moduleEnabled 守卫（即 2026-10-10 修掉的死锁）
    expect_red("S11", s11_card_outside_module_guard,
               vue.replace('<el-card v-if="isPlatformAdmin && !configError"',
                           '<el-card v-if="isPlatformAdmin && !configError && moduleEnabled"'))
    # 退化形态 = 客户端重新直读原始 bean（即 2026-10-10 修掉的空 client_id 缺陷）
    expect_red("S12", s12_clients_route_overridable_fields_through_port,
               read(GITEE_CLIENT).replace("settings.getClientId()", "props.getClientId()"))

    print(f"\n自检结果：{'全部断言均会随退化变红' if not fails else '存在无效断言'}")
    for f in fails:
        print("  - " + f)
    return 0 if not fails else 1


# ---------------------------------------------------------------- 接口往返


class Api:
    def __init__(self, base, token=None):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, method, path, body=None, raw=False):
        url = self.base + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                txt = r.read().decode("utf-8", "replace")
                return r.status, (txt if raw else _json_or_text(txt))
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            return e.code, (txt if raw else _json_or_text(txt))
        except Exception as e:  # 连接失败等
            return 0, {"code": -1, "message": f"请求失败：{e}"}


def _json_or_text(txt):
    try:
        return json.loads(txt)
    except Exception:
        return {"code": -1, "message": txt[:200]}


def login(base, user, pwd):
    st, resp = Api(base).call("POST", "/api/v1/auth/login", {"username": user, "password": pwd})
    if st != 200 or not isinstance(resp, dict):
        return None, f"登录失败 HTTP {st}：{resp}"
    data = resp.get("data") or {}
    tok = data.get("token") or data.get("accessToken")
    return (tok, None) if tok else (None, f"登录响应无 token：{str(resp)[:200]}")


def run_api(base, user, pwd):
    """接口往返：保存→生效→负向→清除。全程记录原始状态并在结束前复原。"""
    results = []

    def chk(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} —— {detail}")

    token, err = login(base, user, pwd)
    if not token:
        return results, err, True  # 前置不满足
    api = Api(base, token)

    st, cfg = api.call("GET", "/api/v1/gitee/platform-config")
    if st == 404:
        return results, "接口 404：后端尚未包含本次改动（需重新打包并重启）", True
    if st == 403:
        return results, f"{user} 非平台管理员，无法验证（403）", True
    if st != 200 or not isinstance(cfg, dict) or cfg.get("code") != 0:
        return results, f"读取平台参数失败 HTTP {st}：{str(cfg)[:200]}", True

    data = cfg.get("data") or {}
    fields = [f.get("key") for f in (data.get("fields") or [])]
    chk("A1 视图字段齐备", fields == FIELDS, f"{fields}")
    chk("A2 视图带每字段来源", set((data.get("sources") or {}).keys()) == set(FIELDS),
        f"sources={list((data.get('sources') or {}).keys())}")

    # 记录原始状态以便复原
    orig_configured = bool(data.get("configured"))
    orig_values = dict(data.get("values") or {})
    orig_secret_configured = bool(data.get("clientSecretConfigured"))
    orig_admin = data.get("adminOverridden")
    print(f"  （原始状态：configured={orig_configured} adminOverridden={orig_admin} "
          f"secretConfigured={orig_secret_configured}）")

    def cfg_flags():
        st2, r2 = api.call("GET", "/api/v1/gitee/config")
        return (r2.get("data") or {}) if isinstance(r2, dict) else {}

    secret_written = False
    try:
        # --- 正向：改平台默认组织，应立即生效且来源为 ADMIN ---
        st, r = api.call("PUT", "/api/v1/gitee/platform-config", {"org": "__check_tmp_org__"})
        ok = st == 200 and isinstance(r, dict) and r.get("code") == 0
        chk("A3 保存平台默认组织", ok, f"HTTP {st} {str(r)[:120]}")
        if ok:
            v = (r.get("data") or {}).get("values") or {}
            src = (r.get("data") or {}).get("sources") or {}
            chk("A4 保存后立即生效（值回读一致）", v.get("org") == "__check_tmp_org__", f"org={v.get('org')}")
            chk("A5 来源标记为 ADMIN", src.get("org") == "ADMIN", f"source={src.get('org')}")

        # --- 负向：scope 缺 hook 必须被拒（Gitee hook 是独立 scope，缺它静默失败） ---
        st, r = api.call("PUT", "/api/v1/gitee/platform-config", {"scope": "user_info projects"})
        ok = st == 200 and isinstance(r, dict) and r.get("code") not in (0, None)
        chk("A6 负向·scope 缺 hook 被拒", ok, f"HTTP {st} code={(r or {}).get('code')} msg={str((r or {}).get('message'))[:60]}")

        # --- 负向：非 http(s) 的 Webhook 基址必须被拒 ---
        st, r = api.call("PUT", "/api/v1/gitee/platform-config", {"webhookBaseUrl": "ftp://x"})
        ok = st == 200 and isinstance(r, dict) and r.get("code") not in (0, None)
        chk("A7 负向·非 http(s) 地址被拒", ok, f"code={(r or {}).get('code')} msg={str((r or {}).get('message'))[:60]}")

        # --- Secret：写入后不得回传明文 ---
        # ★ 不可逆风险（2026-10-10 修）：Secret 写入后**读不回明文**（设计如此），因此一旦覆盖就无法还原。
        #   若原本已配置（生产常态），此处写入会**静默毁掉真实凭据** ⇒ 改为「复用现有配置做只读校验」。
        if orig_secret_configured:
            view_secret = (data.get("values") or {}).get("clientSecret")
            chk("A9 Secret 不回传明文（复用现有配置，只读）", view_secret == "",
                f"视图 clientSecret={view_secret!r}")
            chk("A10 只回「已配置」", data.get("clientSecretConfigured") is True,
                f"clientSecretConfigured={data.get('clientSecretConfigured')}")
            print("  [NOTE] 原本已配置真实 Secret，未做写入（写入后无法还原，会毁凭据）——只做只读校验。")
        else:
            st, r = api.call("PUT", "/api/v1/gitee/platform-config", {"clientSecret": "__check_secret_value__"})
            ok = st == 200 and isinstance(r, dict) and r.get("code") == 0
            chk("A8 保存 Client Secret", ok, f"HTTP {st} {str(r)[:100]}")
            if ok:
                secret_written = True
                chk("A9 Secret 不回传明文", "__check_secret_value__" not in json.dumps(r, ensure_ascii=False),
                    "响应体中未出现明文")
                chk("A10 只回「已配置」", bool((r.get("data") or {}).get("clientSecretConfigured")) is True,
                    f"clientSecretConfigured={(r.get('data') or {}).get('clientSecretConfigured')}")
    finally:
        # --- 复原：有原配置就写回原值（含 Secret 状态），否则删除整行 ---
        if orig_configured:
            body = {k: v for k, v in orig_values.items() if k != "clientSecret"}
            if secret_written:
                # 原本**没有** Secret，我们写进去过一份假值 ⇒ 必须显式清空（空串＝显式清空）。
                # 不这么做就会在库里留下一份假密钥，把「未配置」伪装成「已配置」。
                body["clientSecret"] = ""
            api.call("PUT", "/api/v1/gitee/platform-config", body)
            st, r = api.call("GET", "/api/v1/gitee/platform-config")
            now = ((r or {}).get("data") or {}).get("values") or {}
            chk("A11 已复原原配置", now.get("org") == orig_values.get("org"),
                f"org={now.get('org')}（原 {orig_values.get('org')}）")
            if secret_written and (r or {}).get("data", {}).get("clientSecretConfigured"):
                chk("A11b 假 Secret 已清空", False, "复原后仍显示已配置 ⇒ 留下了假密钥")
        else:
            st, r = api.call("DELETE", "/api/v1/gitee/platform-config")
            ok = st == 200 and isinstance(r, dict) and r.get("code") == 0
            chk("A11 清除后回落环境变量", ok and not (r.get("data") or {}).get("configured"),
                f"configured={(r.get('data') or {}).get('configured')}")

    # --- 负向：未认证必须被拒 ---
    st, r = Api(base).call("GET", "/api/v1/gitee/platform-config")
    chk("A12 负向·未认证被拒", st in (401, 403), f"HTTP {st}")

    return results, None, False


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description="仓库联动平台参数动态配置哨兵")
    ap.add_argument("--api", action="store_true", help="额外跑接口往返（需后端在跑）")
    ap.add_argument("--selftest", action="store_true", help="自检：证明静态断言会随退化变红")
    ap.add_argument("--base", default=os.environ.get("AIOA_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default=os.environ.get("AIOA_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("AIOA_PASSWORD", "Admin@123"))
    args = ap.parse_args()

    print("== 静态断言 ==")
    passed, failed = run_static()

    if args.selftest:
        print()
        rc = selftest()
        print(f"\n静态小结：{passed}/{len(STATIC_CHECKS)} 通过；自检退出码={rc}")
        return 1 if (failed or rc) else 0

    api_skip = False
    if args.api:
        print("\n== 接口往返 ==")
        results, err, skip = run_api(args.base, args.user, args.password)
        if err:
            api_skip = True
            print(f"  [SKIP] {err}")
        else:
            for name, ok, detail in results:
                if not ok:
                    failed.append(f"{name} —— {detail}")

    print()
    if failed:
        print(f"[FAIL] 静态 {passed}/{len(STATIC_CHECKS)} 通过；失败项：")
        for f in failed:
            print("  - " + f)
        return 1
    if api_skip:
        print(f"[SKIP] 静态 {passed}/{len(STATIC_CHECKS)} 全部通过；接口往返**未验证**（前置不满足）。")
        print("       这不等于通过——请重新打包后端并重启后再跑 --api。")
        return 2
    print(f"[OK] 静态 {passed}/{len(STATIC_CHECKS)} 全部通过"
          + ("；接口往返全部通过" if args.api else "（未跑接口；加 --api 可验证往返）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
