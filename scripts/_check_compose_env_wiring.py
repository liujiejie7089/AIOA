# -*- coding: utf-8 -*-
"""compose 环境变量「透传面」静态校验（防静默空转）。

为什么需要它：容器拿到的环境变量 = ``deploy/docker-compose.yml`` 里 ``server`` 服务
``environment:`` 块中**显式列出**的那些 —— 本 compose **没有 env_file**，``deploy/.env``
只作为 ``${}`` 插值源，不会整份塞进容器。于是存在一整类**静默空转**：

    application.yml 里写了 ``${AIOA_XXX:default}``，``.env`` 里也老老实实填了值，
    但 compose 没透传 ⇒ 容器拿不到 ⇒ 只有 yml 的 default 生效，而且**不报任何错**。

真实实例（2026-10-09，本次修复）：``AIOA_GITEE_SYNC_ENABLED`` / ``AIOA_GITEE_SYNC_CRON``
未透传 ⇒ 在 .env 里把 sync 关掉是空转（容器永远按 yml 默认 ``true`` 跑）。
同类历史实例见 ``.workbuddy/memory/topics/production-deploy.md`` 的
「★ 环境变量注入路径」一节（``SPRING_DATASOURCE_*`` 同名键被 compose 现拼覆盖）。

判据（二选一，缺一即 FAIL）：
    ① 该 ``${VAR}`` 在 compose ``server.environment`` 里被透传；或
    ② 该 ``${VAR}`` 在下方 ``BENIGN`` 白名单里，且写明「为什么它不是空转」。
    ⇒ **白名单是唯一的豁免出口**：新增豁免必须给理由，防止「反正没人看」地放行。

用法：
    python scripts/_check_compose_env_wiring.py              # 校验
    python scripts/_check_compose_env_wiring.py --selftest   # 负向自检（判据必须能报红）
退出码：0 = 通过（允许 WARN）；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = "deploy/docker-compose.yml"
APP_YML = "server/aioa-boot/src/main/resources/application.yml"
SERVICE = "server"

# 反恒真的下限：解析器真坏了（正则不匹配）会得到 0 个引用，那会「恒绿」。
MIN_REFS = 60
MIN_PASSED = 50

# 唯一的豁免出口：未透传但**确认不构成空转**的键，必须给理由。
BENIGN = {
    "SPRING_PROFILES_ACTIVE": (
        "resources 下只有 application.yml，**没有** application-{dev,prod}.yml "
        "⇒ 无论激活哪个 profile 都只加载同一份配置，不改任何行为"
        "（仅 `java -jar` 直跑时可选设）"
    ),
    "AIOA_SCFY_BASE_URL": "SCfy（四川法院）集成未纳入本部署，enabled 默认 false",
    "AIOA_SCFY_ENABLED": "同上：SCfy 集成未纳入本部署",
    "AIOA_SCFY_USERNAME": "同上：SCfy 集成未纳入本部署（且 yml 中该行为注释）",
    "AIOA_SCFY_PASSWORD": "同上：SCfy 集成未纳入本部署（且 yml 中该行为注释）",
    "AIOA_GITEA_INSECURE_SKIP_VERIFY": (
        "Gitea 段默认 disabled；**启用 Gitea 前必须把这 4 个 TLS 键一并加进 compose**（待办）"
    ),
    "AIOA_GITEA_TRUST_STORE": "同上：Gitea 未启用；启用前需透传",
    "AIOA_GITEA_TRUST_STORE_PASSWORD": "同上：Gitea 未启用；启用前需透传",
    "AIOA_GITEA_TRUST_STORE_TYPE": "同上：Gitea 未启用；启用前需透传",
}

REF_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def extract_refs(yml_text: str) -> "dict[str, str]":
    """返回 {VAR: yml 内联默认值}（无默认值记为空串）。"""
    out: "dict[str, str]" = {}
    for m in REF_RE.finditer(yml_text):
        out.setdefault(m.group(1), m.group(2) if m.group(2) is not None else "")
    return out


def compose_env_keys(compose_text: str, service: str = SERVICE) -> "set[str]":
    """按缩进取出 <service>.environment 下显式列出的键。

    不依赖 pyyaml（跑脚本的 python 未必装），只认本文件的结构：
      services:            (0 缩进)
        <service>:         (2)
          environment:     (4)
            KEY: value     (6)
    """
    lines = compose_text.splitlines()
    svc_re = re.compile(r"^ {2}" + re.escape(service) + r":\s*$")
    start = None
    for i, ln in enumerate(lines):
        if svc_re.match(ln):
            start = i
            break
    if start is None:
        raise AssertionError("compose 里找不到服务 %r（缩进结构变了？）" % service)

    env_re = re.compile(r"^ {4}environment:\s*$")
    env_start = None
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent <= 2:
            break
        if env_re.match(ln):
            env_start = i
            break
    if env_start is None:
        raise AssertionError("服务 %r 下找不到 environment: 块" % service)

    keys: "set[str]" = set()
    key_re = re.compile(r"^ {6}([A-Z0-9_]+):")
    for i in range(env_start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() == "" or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent <= 4:
            break
        m = key_re.match(ln)
        if m:
            keys.add(m.group(1))
    return keys


def classify(refs, passed, benign) -> "tuple[list[str], list[str]]":
    """-> (fails, warns)：未透传且不在白名单 = FAIL；在白名单 = WARN(带理由)。"""
    missing = sorted(v for v in refs if v not in passed)
    fails = [v for v in missing if v not in benign]
    warns = [v for v in missing if v in benign]
    return fails, warns


def run_selftest() -> int:
    """证明判据能报红（否则是恒真断言）。"""
    bad = 0

    def chk(name: str, ok: bool, detail: str = "") -> None:
        nonlocal bad
        print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  " + detail) if detail else ""))
        if not ok:
            bad += 1

    print("[SELFTEST] 判据可证伪性")
    fake_yml = 'spring:\n  x: ${AIOA_FAKE_MISSING_VAR:}\n'
    fake_compose = "services:\n  server:\n    environment:\n      OTHER_KEY: ${OTHER_KEY:-}\n"

    r = extract_refs(fake_yml)
    chk("S1 能抽出真实引用（非空）", r.get("AIOA_FAKE_MISSING_VAR") == "", repr(r))

    fails, warns = classify(r, compose_env_keys(fake_compose), BENIGN)
    chk("S2 未透传且非白名单 => FAIL", fails == ["AIOA_FAKE_MISSING_VAR"], repr(fails))
    chk("S2b 此时不应有 WARN", warns == [], repr(warns))

    benign2 = dict(BENIGN)
    benign2["AIOA_FAKE_MISSING_VAR"] = "自检占位"
    fails2, warns2 = classify(r, compose_env_keys(fake_compose), benign2)
    chk("S3 白名单内的豁免 => 降为 WARN", fails2 == [] and warns2 == ["AIOA_FAKE_MISSING_VAR"], repr((fails2, warns2)))

    passed_real = compose_env_keys(Path(ROOT / COMPOSE).read_text(encoding="utf-8"))
    chk("S4 真实 compose 能解析出 environment 键（>50）", len(passed_real) > 50, "keys=%d" % len(passed_real))

    refs_real = extract_refs(Path(ROOT / APP_YML).read_text(encoding="utf-8"))
    chk("S5 真实 application.yml 能抽出引用（>60）", len(refs_real) > 60, "refs=%d" % len(refs_real))

    fake_refs = dict(refs_real)
    fake_refs["AIOA_GITEE_SYNC_ENABLED"] = ""
    f3, _ = classify(fake_refs, passed_real - {"AIOA_GITEE_SYNC_ENABLED"}, BENIGN)
    chk("S6 把真实键从透传里摘掉 => 必须报 FAIL", "AIOA_GITEE_SYNC_ENABLED" in f3, repr(f3))

    print("[SELFTEST] %s" % ("全部通过" if bad == 0 else "%d 项失败" % bad))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return run_selftest()

    refs = extract_refs(Path(ROOT / APP_YML).read_text(encoding="utf-8"))
    passed = compose_env_keys(Path(ROOT / COMPOSE).read_text(encoding="utf-8"))

    if len(refs) < MIN_REFS or len(passed) < MIN_PASSED:
        print("[FAIL] 解析下限未达标（refs=%d/%d, passed=%d/%d）—— 判据可能已恒真，先修解析器"
              % (len(refs), MIN_REFS, len(passed), MIN_PASSED))
        return 1

    fails, warns = classify(refs, passed, BENIGN)

    print("application.yml 引用 %d 个环境变量；compose server 透传 %d 个" % (len(refs), len(passed)))
    for v in warns:
        print("[WARN] %s 未透传（白名单豁免）：%s" % (v, BENIGN[v]))
    for v in fails:
        print("[FAIL] %s 被 application.yml 引用、但 compose 未透传 ⇒ 在 .env 里设它**是空转**"
              % v)
        print("       修法：在 deploy/docker-compose.yml 的 server.environment 补 "
              "`%s: ${%s:-<yml默认值>}`（或登记进 BENIGN 并写清理由）" % (v, v))

    if fails:
        print("\n结论：FAIL —— 有 %d 个键在 .env 里改不出效果（静默空转）" % len(fails))
        return 1
    print("\n结论：PASS（%d 项白名单豁免已注明理由）" % len(warns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
