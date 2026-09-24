# -*- coding: utf-8 -*-
"""单端口入口（docs/33）一致性静态校验。

为什么需要它：docs/33 把线上入口收敛成「aioa-server :8080 一个端口，经 /aioa/h5、/aioa/web、
/aioa/api 三个前缀对外」。这个设计的脆弱点不在语法，而在**同一件事散落在 5 个文件里**：

    前缀 /aioa      : AioaWebProperties(Java) · application.yml · docker-compose.yml · user-client/index.html · vite base
    静态目录 /app/h5、/app/web : AioaWebProperties · application.yml · docker-compose.yml · Dockerfile.server
    子应用 base     : web/apps/*/vite.config.ts  ⇄  Dockerfile.server 的组装目录
    剥离顺序        : AioaWebPrefixConfig.setOrder(必须最先) · SecurityConfig 放行名单

只要其中**任何一处**漂移，症状都不是「校验器报错」，而是部署后：
管理端白屏（base 未生效）/ 入口全 404（目录没 COPY）/ 登录 401（剥离顺序晚于安全链）。
本机没有 docker、更跑不了生产镜像，所以用「同源比对 + 负向突变自检」替代人工目测。

用法：
    python scripts/_check_single_port.py              # 校验
    python scripts/_check_single_port.py --selftest   # 负向自检（把每项断言故意弄坏，必须都报红）
退出码：0 = 通过（允许有 WARN）；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMPOSE = "deploy/docker-compose.yml"
DOCKERFILE = "deploy/Dockerfile.server"
APP_YML = "server/aioa-boot/src/main/resources/application.yml"
PROPS = "server/aioa-boot/src/main/java/cn/aioa/boot/web/AioaWebProperties.java"
PREFIX_CFG = "server/aioa-boot/src/main/java/cn/aioa/boot/web/AioaWebPrefixConfig.java"
SUPPORT = "server/aioa-boot/src/main/java/cn/aioa/boot/web/AioaPathPrefixSupport.java"
STATIC_CFG = "server/aioa-boot/src/main/java/cn/aioa/boot/web/AioaStaticConfig.java"
SECURITY = "server/aioa-security/src/main/java/cn/aioa/security/SecurityConfig.java"
H5 = "user-client/index.html"
VITE = {
    "shell": "web/apps/shell/vite.config.ts",
    "demo-ticket": "web/apps/demo-ticket/vite.config.ts",
    "demo-dispatch": "web/apps/demo-dispatch/vite.config.ts",
}
SHELL_ROUTER = "web/apps/shell/src/router/index.ts"

# 期望的「唯一前缀 / 静态目录」口径（改这里 = 改契约，必须同步全部落点）
PREFIX = "/aioa"
H5_DIR = "/app/h5"
WEB_DIR = "/app/web"

# 已摘除的边缘组件：其**服务定义行**不得再出现在 compose 里。
# ★ 2026-09-24：`nginx` 从本名单移出 —— 它回来了，但**不是**当年那层边缘代理
#   （当年那层：80=H5 / 81=管理端 / web 容器存静态），而是「**入口别名**」：
#       /web → 管理端、/user → 用户端，后端仍是 server:8080 单端口（docs/33 不变）。
#   所以对它的约束从「禁止存在」改成「形态正确」——见 c11。
#   当年一起摘掉的 `web` 容器与 `ollama` 仍然禁止复活。
REMOVED_SERVICES = ("ollama", "web")

# 入口 nginx（2026-09-24 新增）：compose 服务定义与配置文件必须同源
NGINX_CONF = "deploy/nginx/aioa-entry.conf"

FILES = [COMPOSE, DOCKERFILE, APP_YML, PROPS, PREFIX_CFG, SUPPORT, STATIC_CFG, SECURITY,
         SHELL_ROUTER, H5, NGINX_CONF, *VITE.values()]

_OVERRIDES: dict[str, str | None] = {}   # selftest 用：rel -> 替换文本（None = 视为不存在）


def read(rel: str) -> str:
    if rel in _OVERRIDES:
        v = _OVERRIDES[rel]
        if v is None:
            return ""
        return v
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def exists(rel: str) -> bool:
    if rel in _OVERRIDES:
        return _OVERRIDES[rel] is not None
    return (ROOT / rel).is_file()


def hit(rel: str, pattern: str) -> bool:
    return re.search(pattern, read(rel), re.M) is not None


# --------------------------------------------------------------------------- 检查项
# 每项返回 (FAIL 列表, WARN 列表)，元素为字符串。全部为「同源比对」类断言。


def c1_compose_services() -> tuple[list, list]:
    """compose 的服务集合：已摘除的组件不得复活；server/agent 必须在。"""
    f, w = [], []
    text = read(COMPOSE)
    if not text:
        return ["找不到 %s" % COMPOSE], w
    # 只认「顶层 services 下的服务定义行」（两空格缩进 + 冒号 + 行尾无其它内容）
    svc = set(re.findall(r"^  ([a-z][a-z0-9_-]*):\s*$", text, re.M))
    for name in REMOVED_SERVICES:
        if name in svc:
            f.append("%s 里又出现了已摘除的服务定义 `%s:`（单端口入口不再需要它）" % (COMPOSE, name))
    for name in ("server", "agent"):
        if name not in svc:
            f.append("%s 缺少必需服务 `%s:`" % (COMPOSE, name))
    return f, w


def c2_compose_no_stale_artifacts() -> tuple[list, list]:
    """已摘除组件的**具体配置行**不得残留（注释里说明它被摘除是允许的）。

    ★ 2026-09-24：`image: nginx:*` 与 `80:80` 已从本名单移出 —— 入口 nginx 现在
      就应该是这个形态（正断言在 c11）。仍然禁止的是**当年那层边缘 nginx**的痕迹：
      81 端口、以及与它配套的历史配置文件（api-proxy.conf / nginx.conf）。
    """
    f, w = [], []
    text = read(COMPOSE)
    stale = [
        (r"^\s*image:\s*[\"']?ollama/ollama", "ollama 镜像行"),
        (r"^\s*-\s*ollamadata\s*:", "ollamadata 卷挂载"),
        (r"^\s*ollamadata:\s*$", "ollamadata 卷定义"),
        (r"^\s*-\s*[\"']?81:81", "81 端口发布（当年那层边缘 nginx 的双端口档）"),
        # 入口 nginx 应挂 nginx/aioa-entry.conf；挂回历史档说明在照抄旧部署资料。
        # （注意 `nginx/aioa-entry.conf` 不含 `nginx.conf` 子串，不会误报。）
        (r"api-proxy\.conf|nginx\.conf", "历史 nginx 配置文件挂载（现应为 nginx/aioa-entry.conf）"),
    ]
    for pat, what in stale:
        for m in re.finditer(pat, text, re.M):
            line = text[:m.start()].count("\n") + 1
            f.append("%s 第 %d 行仍有 %s —— 单端口改造后不应存在" % (COMPOSE, line, what))
    return f, w


def c3_ports() -> tuple[list, list]:
    """server 对外发布 8080；agent 只对本机开放 8000。"""
    f, w = [], []
    text = read(COMPOSE)
    if not re.search(r"^\s*-\s*[\"']8080:8080[\"']\s*$", text, re.M):
        f.append("%s 未把 server 的 8080 发布到宿主（没有这一行，入口就出不了容器）" % COMPOSE)
    if not re.search(r"^\s*-\s*[\"']127\.0\.0\.1:8000:8000[\"']\s*$", text, re.M):
        f.append("%s 的 agent 端口应为 `127.0.0.1:8000:8000`（仅本机排查用，不对内网暴露）" % COMPOSE)
    return f, w


def c4_no_backend_override() -> tuple[list, list]:
    """叠加文件已并入主 compose：文件不得存在，交付件里不得再引用。"""
    f, w = [], []
    rel = "deploy/docker-compose.backend.yml"
    if exists(rel):
        f.append("%s 仍存在 —— 端口已并入 %s，保留它会让现场误以为要叠加启动" % (rel, COMPOSE))
    scan_roots = ["deploy", "scripts", "server", "web"]
    suffixes = {".yml", ".yaml", ".sh", ".py", ".ts", ".js", ".json", ".properties"}
    self_rel = Path(__file__).resolve()
    # 允许提及该文件名的**白名单**：这些文件的职责就是「断言它不存在」，把它们算作残留
    # 会让校验器把守卫自己判红。每条都必须写明理由 —— 白名单是刻意的洞，不是便利。
    allowed_mentions = {
        self_rel,                                        # 本校验器（c4 要报出它）
        (ROOT / "scripts" / "e2e_v63_single_port.py").resolve(),  # 套件 A6：断言叠加文件已删除
    }
    for root in scan_roots:
        base = ROOT / root
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in suffixes:
                continue
            if "node_modules" in p.parts or "dist" in p.parts:
                continue
            if p.resolve() in allowed_mentions:
                continue
            # ★ 必须走 read()/exists() 而不是 p.read_text()：
            #   直接读盘会让**负向自检的 _OVERRIDES 覆盖机制够不到这里** ——
            #   于是「这段扫描被写坏」在自检里永远看不到（本脚本自检抓到过：加了这条
            #   之后才有一条能报红的 c4 文本扫描突变）。
            rel_key = p.relative_to(ROOT).as_posix()
            if not exists(rel_key):
                continue
            try:
                lines = read(rel_key).splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(lines, 1):
                if "docker-compose.backend.yml" not in line:
                    continue
                if line.lstrip().startswith("#"):
                    continue  # 注释里说明历史是允许的（改造计划就是靠这类注释留痕）
                f.append("%s 第 %d 行仍引用已删除的 docker-compose.backend.yml：%s"
                         % (p.relative_to(ROOT).as_posix(), i, line.strip()[:100]))
    return f, w


def c5_prefix_consistency() -> tuple[list, list]:
    """前缀 /aioa 的四个落点必须一致。"""
    f, w = [], []
    if not hit(PROPS, r'String\s+prefix\s*=\s*"%s"' % re.escape(PREFIX)):
        f.append("%s 里默认前缀不是 \"%s\"" % (PROPS, PREFIX))
    if not hit(APP_YML, r"AIOA_WEB_PREFIX:%s\b" % re.escape(PREFIX)):
        f.append("%s 里 AIOA_WEB_PREFIX 的默认值不是 %s" % (APP_YML, PREFIX))
    if not hit(COMPOSE, r"AIOA_WEB_PREFIX:-\s*%s\b" % re.escape(PREFIX)):
        f.append("%s 里 AIOA_WEB_PREFIX 的默认值不是 %s" % (COMPOSE, PREFIX))
    # vite 侧：三个应用的 build base 必须都在 /aioa/web/ 之下
    for name, rel in VITE.items():
        want = "%s/web/" % PREFIX if name == "shell" else "%s/web/subapps/%s/" % (PREFIX, name)
        if ("'%s'" % want) not in read(rel) and ('"%s"' % want) not in read(rel):
            f.append("%s 的 build base 不是 %s" % (rel, want))
    if not hit(SHELL_ROUTER, r"createWebHistory\(import\.meta\.env\.BASE_URL\)"):
        f.append("%s 未用 import.meta.env.BASE_URL 建 history（写死 '/' 会让 /aioa/web/ 白屏）" % SHELL_ROUTER)
    return f, w


def c6_static_dirs() -> tuple[list, list]:
    """静态目录 /app/h5、/app/web 在 Java / yml / compose / Dockerfile 四处一致。"""
    f, w = [], []
    pairs = [("h5", "h5Dir", "AIOA_WEB_H5_DIR", H5_DIR, "/out/h5"), ("web", "webDir", "AIOA_WEB_WEB_DIR", WEB_DIR, "/out/web")]
    for short, camel, env, container, out in pairs:
        if not hit(PROPS, r'String\s+%s\s*=\s*"%s"' % (camel, re.escape(container))):
            f.append("%s 里 %s 的默认值不是 %s" % (PROPS, camel, container))
        if not hit(APP_YML, r"%s:%s\b" % (env, re.escape(container))):
            f.append("%s 里 %s 的默认值不是 %s" % (APP_YML, env, container))
        if not hit(COMPOSE, r"%s:\s*%s\s*$" % (env, re.escape(container))):
            f.append("%s 里 %s 未指向 %s" % (COMPOSE, env, container))
        if not hit(DOCKERFILE, r"COPY --from=web %s %s\b" % (re.escape(out), re.escape(container))):
            f.append("%s 未把 %s 拷进镜像的 %s" % (DOCKERFILE, out, container))
        # 子应用组装目录 ⇄ vite base 一一对应
        if short == "web":
            for name, rel in VITE.items():
                if name == "shell":
                    continue
                sub = "%s/subapps/%s" % (out, name)
                if sub not in read(DOCKERFILE):
                    f.append("%s 未把 %s 组装到 %s（与 %s 的 base 不一致）" % (DOCKERFILE, name, sub, rel))
    return f, w


def c7_image_selfcheck() -> tuple[list, list]:
    """镜像内三块内容自检 + 管理端产物基址的构建期断言必须在。"""
    f, w = [], []
    d = read(DOCKERFILE)
    need = ["/app/aioa-server.jar", "%s/index.html" % H5_DIR, "%s/index.html" % WEB_DIR]
    if "test -f" not in d or any(n not in d for n in need):
        f.append("%s 缺少「三块内容缺一不可」的构建期自检（%s）" % (DOCKERFILE, "、".join(need)))
    if "grep -q '%s/web/assets/'" % PREFIX not in d:
        f.append("%s 缺少管理端产物基址的构建期断言（grep %s/web/assets/）：vite base 一旦回退到 '/'，"
                 "要到浏览器白屏才发现" % (DOCKERFILE, PREFIX))
    return f, w


def c8_filter_and_security() -> tuple[list, list]:
    """剥离 Filter 的顺序必须最先；安全链必须放行静态根与 /error；控制器仍映射 /api。"""
    f, w = [], []
    if not hit(PREFIX_CFG, r"setOrder\(Integer\.MIN_VALUE\)"):
        f.append("%s 未用 setOrder(Integer.MIN_VALUE)：剥离晚于安全链会导致 /aioa/api/** 登录 401" % PREFIX_CFG)
    sec = read(SECURITY)
    # ★ 必须断言**带引号的字面量**：注释里也出现 `/aioa/web/**` 这种字样，
    #   只搜裸子串会被注释满足 ⇒ 变成恒真断言（本脚本自检已抓到过一次）。
    #   注意 `"/aioa/web"` 是 `"/aioa/web/**"` 的子串，所以两个都要查、不能互相代替。
    for must in ('"%s/h5/**"' % PREFIX, '"%s/web/**"' % PREFIX,
                 '"%s/h5"' % PREFIX, '"%s/web"' % PREFIX, '"/error"'):
        if must not in sec:
            f.append("%s 放行名单缺少 %s（注释里出现同名字样不算）" % (SECURITY, must))
    if not hit(SUPPORT, r'"%s/api"' % re.escape(PREFIX)) and not hit(SUPPORT, r"\+ \"/api\""):
        f.append("%s 里未见 `<prefix>/api` 的剥离目标，确认剥离规则还在" % SUPPORT)
    return f, w


def c9_h5_base_derivation() -> tuple[list, list]:
    """H5 的接口基址必须由 location.pathname 推导，不得退回字面 '/api'。"""
    f, w = [], []
    h5 = read(H5)
    if "apiBaseFromPath" not in h5:
        f.append("%s 里没有 apiBaseFromPath：H5 挪到 /aioa/h5/ 后接口会打到根路径" % H5)
    m = re.search(r"const\s+API\s*=\s*\{(.{0,400}?)\}", h5, re.S)
    if not m:
        f.append("%s 里找不到 `const API = {...}` 定义" % H5)
    else:
        body = m.group(1)
        if "apiBaseFromPath(" not in body:
            f.append("%s 的 API.base 未接 apiBaseFromPath（仍是字面量 ⇒ 前缀形态下打错地址）" % H5)
        if re.search(r"base\s*:\s*['\"]/api['\"]", body):
            f.append("%s 的 API.base 被写回字面 '/api'（前缀形态下必错）" % H5)
    return f, w


def c10_static_root_local_note() -> tuple[list, list]:
    """静态根在本地跑时通常指仓库目录；容器路径不存在是正常的 —— 只记 WARN。"""
    f, w = [], []
    for label, d in (("h5", H5_DIR), ("web", WEB_DIR)):
        if Path(d).exists() and not (Path(d) / "index.html").is_file():
            w.append("%s 指向的本地目录 %s 存在但缺 index.html" % (label, d))
    if not (ROOT / "user-client" / "index.html").is_file():
        f.append("仓库里找不到 user-client/index.html（H5 源文件），Dockerfile 的 COPY 会失败")
    return f, w


def c11_nginx_entry() -> tuple[list, list]:
    """入口 nginx（2026-09-24）：/web 管理端 · /user 用户端。

    这层最容易漂移的三处：
      ① compose 里有服务、但没挂配置文件（或挂成历史档）⇒ 现场起的是默认站点；
      ② 配置里少 `/aioa/` ⇒ 管理端白屏（静态资源全打到 nginx 上 404）；
      ③ 配置里少 `/api/` ⇒ /user 下 H5 推导出的接口基址是 `/api`，登录就失败。
    以及一条**方向性**约定：`/web` 必须是 302 到 `/aioa/web/`，不能改成内部改写 ——
    管理端 base 固定为 `/aioa/web/`，地址栏停在 `/web/` 时 vue-router 会落在 base 之外。
    """
    f, w = [], []
    text = read(COMPOSE)
    svc = set(re.findall(r"^  ([a-z][a-z0-9_-]*):\s*$", text, re.M))
    if "nginx" not in svc:
        f.append("%s 缺少 `nginx:` 入口服务（/web 与 /user 靠它提供）" % COMPOSE)
    if not re.search(r"^\s*-\s*[\"']?80:80[\"']?\s*$", text, re.M):
        f.append("%s 的 nginx 未发布 80 端口（入口出不了容器）" % COMPOSE)
    if "./nginx/aioa-entry.conf:/etc/nginx/conf.d/default.conf:ro" not in text:
        f.append("%s 未把 %s 挂成 /etc/nginx/conf.d/default.conf" % (COMPOSE, NGINX_CONF))

    if not exists(NGINX_CONF):
        f.append("找不到入口配置 %s" % NGINX_CONF)
        return f, w
    conf = read(NGINX_CONF)

    must = [
        (r"location\s*=\s*/user\b", "/user 入口"),
        (r"location\s*/user/", "/user/（H5 内部改写回 /aioa/h5/）"),
        (r"location\s*=\s*/web\b", "/web 入口"),
        (r"location\s*/aioa/", "/aioa/（后端单端口三前缀）"),
        (r"location\s*/api/", "/api/（旧根前缀；/user 下 H5 推导到的就是它）"),
        (r"proxy_buffering\s+off", "SSE 关缓冲"),
    ]
    for pat, what in must:
        if not re.search(pat, conf, re.M):
            f.append("%s 缺少 %s" % (NGINX_CONF, what))

    if not re.search(r"return\s+302\s+/aioa/web/", conf):
        f.append("%s 的 /web 未 302 到 /aioa/web/（管理端 base 固定，内部改写会让"
                 "vue-router 落在 base 之外 ⇒ 白屏）" % NGINX_CONF)
    return f, w


CHECKS = [
    ("compose 服务集合", c1_compose_services),
    ("compose 无残留行", c2_compose_no_stale_artifacts),
    ("端口发布", c3_ports),
    ("叠加文件已清理", c4_no_backend_override),
    ("前缀 /aioa 四处一致", c5_prefix_consistency),
    ("静态目录四处一致", c6_static_dirs),
    ("镜像自检与产物基址断言", c7_image_selfcheck),
    ("剥离顺序与安全放行", c8_filter_and_security),
    ("H5 基址推导", c9_h5_base_derivation),
    ("静态根本地提示", c10_static_root_local_note),
    ("入口 nginx（/web · /user）", c11_nginx_entry),
]


def run() -> tuple[list, list]:
    fails, warns = [], []
    for label, fn in CHECKS:
        f, w = fn()
        fails.extend("「%s」%s" % (label, m) for m in f)
        warns.extend("「%s」%s" % (label, m) for m in w)
    return fails, warns


# --------------------------------------------------------------------------- 负向自检
# 把每项断言**故意弄坏**，断言它必须报红 —— 否则这条检查是「恒真断言」，比没有更危险。
MUTATIONS = [
    ("c1", "compose 复活 ollama 服务", COMPOSE,
     lambda t: t + "\n  ollama:\n    image: ollama/ollama:latest\n"),
    ("c2", "compose 残留 ollamadata 卷", COMPOSE,
     lambda t: t + "\nvolumes:\n  ollamadata:\n"),
    ("c2", "compose 残留 81 端口发布", COMPOSE,
     lambda t: t + '\n    ports:\n      - "81:81"\n'),
    ("c3", "server 端口改成 9090:8080", COMPOSE,
     lambda t: t.replace('"8080:8080"', '"9090:8080"', 1)),
    ("c3", "agent 端口改成 0.0.0.0", COMPOSE,
     lambda t: t.replace('"127.0.0.1:8000:8000"', '"8000:8000"', 1)),
    ("c4", "重建叠加文件", "deploy/docker-compose.backend.yml",
     lambda t: "services:\n  server:\n    ports:\n      - \"8080:8080\"\n"),
    # 钉住 c4 的**文本扫描**分支（上面那条只测「文件存在」分支）。
    # 为什么需要它：c4 加了对本校验器 / v63 套件的白名单，若扫描逻辑被写坏或被白名单吞掉，
    # 只测「文件存在」分支是看不出来的。
    ("c4", "别处又引用叠加文件", "deploy/ops/offline-images.sh",
     lambda t: t + "\ndocker compose -f docker-compose.yml -f docker-compose.backend.yml up -d\n"),
    ("c5", "前缀改成 /x", PROPS,
     lambda t: t.replace('String prefix = "/aioa"', 'String prefix = "/x"', 1)),
    ("c5", "子应用 base 回退到 '/'", VITE["demo-ticket"],
     lambda t: t.replace("'/aioa/web/subapps/demo-ticket/'", "'/'", 1)),
    ("c5", "shell router 写死 '/'", SHELL_ROUTER,
     lambda t: t.replace("createWebHistory(import.meta.env.BASE_URL)", "createWebHistory('/')", 1)),
    ("c6", "Dockerfile 不拷 /app/web", DOCKERFILE,
     lambda t: t.replace("COPY --from=web /out/web /app/web\n", "", 1)),
    ("c6", "Dockerfile 组装目录与 base 脱节", DOCKERFILE,
     lambda t: t.replace("/out/web/subapps/demo-dispatch", "/out/web/dispatch")),
    ("c7", "删掉产物基址构建期断言", DOCKERFILE,
     lambda t: t.replace("RUN grep -q '/aioa/web/assets/' /out/web/index.html || \\\n"
                         "    { echo \"❌ 管理端产物基址不对：/out/web/index.html 里找不到 /aioa/web/assets/（vite build 的 base 未生效）\"; exit 1; }\n", "", 1)),
    ("c7", "删掉镜像内容自检", DOCKERFILE,
     lambda t: t.replace("RUN test -f /app/aioa-server.jar && test -f /app/h5/index.html && test -f /app/web/index.html || \\\n"
                         "    { echo \"❌ 镜像内容不全：需要同时存在 /app/aioa-server.jar、/app/h5/index.html、/app/web/index.html\"; exit 1; }\n", "", 1)),
    ("c8", "Filter 顺序改回默认", PREFIX_CFG,
     lambda t: t.replace("registration.setOrder(Integer.MIN_VALUE);", "registration.setOrder(0);", 1)),
    ("c8", "安全链删掉 /aioa/web/** 放行", SECURITY,
     lambda t: t.replace('"/aioa/web/**",\n', "", 1)),
    ("c9", "H5 API.base 写回字面 /api", H5,
     lambda t: t.replace("base:apiBaseFromPath(location.pathname)", "base:'/api'", 1)),
    # ---- c11 入口 nginx（2026-09-24）：服务定义与配置三处都要能被弄坏即报红 ----
    ("c11", "nginx 未发布 80 端口", COMPOSE,
     lambda t: t.replace('      - "80:80"\n', "", 1)),
    ("c11", "nginx 未挂入口配置", COMPOSE,
     lambda t: t.replace("      - ./nginx/aioa-entry.conf:/etc/nginx/conf.d/default.conf:ro\n", "", 1)),
    ("c11", "/web 不再跳到 SPA base", NGINX_CONF,
     lambda t: t.replace("return 302 /aioa/web/;", "return 302 /web/;")),
    ("c11", "/user 路由被删", NGINX_CONF,
     lambda t: t.replace("location /user/ {", "location /nope/ {", 1)),
]


def selftest() -> int:
    """对每个突变：期望对应检查项报 FAIL。未报红 = 该断言恒真 ⇒ 自检失败。"""
    global _OVERRIDES
    print("=== 负向自检：故意弄坏 → 必须报红 ===")
    bad = 0
    for cid, desc, rel, mutate in MUTATIONS:
        original = read(rel)
        mutated = mutate(original)
        if mutated == original:
            print("  ✗ %-34s 突变未生效（锚点文本变了？需同步 MUTATIONS）" % desc)
            bad += 1
            continue
        _OVERRIDES = {rel: mutated}
        try:
            # 只跑 cid 对应的那项（编号 = CHECKS 下标 + 1）
            idx = int(cid[1:]) - 1
            label, fn = CHECKS[idx]
            f, _ = fn()
        finally:
            _OVERRIDES = {}
        if f:
            print("  ✓ %-34s → %s 报红" % (desc, label))
        else:
            print("  ✗ %-34s → %s 未报红（恒真断言，必须修）" % (desc, label))
            bad += 1
    print("自检结果：%s（%d / %d 项未按预期报红）"
          % ("通过" if bad == 0 else "未通过", bad, len(MUTATIONS)))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true", help="跑负向自检（不校验真实文件）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    missing = [r for r in FILES if not (ROOT / r).is_file()]
    fails, warns = run()
    print("=== 单端口入口（docs/33）一致性校验 ===")
    print("根目录       : %s" % ROOT)
    print("前缀/静态目录: %s | %s | %s" % (PREFIX, H5_DIR, WEB_DIR))
    print("检查项       : %d；被检文件 %d 个%s"
          % (len(CHECKS), len(FILES), "（缺失：%s）" % ", ".join(missing) if missing else ""))
    for m in warns:
        print("  WARN  %s" % m)
    for m in fails:
        print("  FAIL  %s" % m)
    print("结果：%s（%d 项失败 / %d 项警告）"
          % ("通过" if not fails else "未通过", len(fails), len(warns)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
