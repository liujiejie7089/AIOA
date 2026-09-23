# -*- coding: utf-8 -*-
"""「后端访问 agent 的 HttpClient 必须显式 HTTP/1.1」静态守卫。

为什么需要它（2026-09-22 实测缺陷）：
    java.net.http.HttpClient 默认 HTTP/2 优先。对明文 http:// 目标它会先发一个
    h2c 升级请求（Upgrade: h2c + Connection: Upgrade, HTTP2-Settings），并把**请求体
    推迟到升级成功之后**才发送。agent 侧 uvicorn 不支持 h2c 升级（未装 httptools 时
    走 h11），会先把一个空 body 的请求派发给 FastAPI，于是：

        POST /internal/v1/complete -> 422 {"loc":["body"],"msg":"Field required"}

    用户端可见症状是「新建定时数字员工，报错无响应 / agent 服务返回 HTTP 422」。

    这条约束的脆弱点在于：它**不是语法错误、也不是类型错误**——`HttpClient.newBuilder()`
    编译得过、单测也过得去，只有真打 agent 才炸；而且只炸 POST（GET 无 body，正常 200）。
    所以任何新加入的「后端 -> agent」调用点都会静默重犯。用静态守卫把它锁住。

判定口径：
    判定对象 = 既出现「访问 agent 的痕迹（aioa.agent.base-url 配置键，或 /internal/v1/
    路径字面量）」、**又自己创建了 java.net.http.HttpClient** 的 .java 文件
    （即出现 HttpClient.newBuilder() / newHttpClient() / AgentHttpClient.agentBuilder()）。

    这类文件不得出现**裸** HttpClient.newBuilder() / newHttpClient()，必须改用
    cn.aioa.common.http.AgentHttpClient.agentBuilder()。

    只做 HTTP 服务端（controller）或只用 Spring WebClient（明文默认 HTTP/1.1，无此问题）
    的文件不受约束 —— 判据是「是否由本文件创建 java.net.http.HttpClient」，不是「有没有
    出现 /internal/v1/ 字样」。

用法：
    python scripts/_check_agent_httpclient.py              # 校验
    python scripts/_check_agent_httpclient.py --selftest    # 负向自检（故意弄坏，必须都报红）
退出码：0 = 通过；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "server"

FACTORY_REL = "aioa-common/src/main/java/cn/aioa/common/http/AgentHttpClient.java"
FACTORY_CLASS = "AgentHttpClient"
FACTORY_CALL = "AgentHttpClient.agentBuilder()"
PIN = "HttpClient.Version.HTTP_1_1"
BARE = re.compile(r"HttpClient\s*\.\s*(newBuilder|newHttpClient)\s*\(\s*\)")

# 访问 agent 的痕迹：配置键 or 内部端点路径
AGENT_TRACE = ("aioa.agent.base-url", "/internal/v1/")

# 明确**不能**用 AgentHttpClient 的（外网/第三方客户端：要保留 HTTP/2 与 ALPN 能力）
MUST_NOT_USE_FACTORY = (
    "aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteeClient.java",
    "aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteaProviderClient.java",
    "aioa-resource/src/main/java/cn/aioa/resource/service/notify/HttpGatewayChannel.java",
    "aioa-resource/src/main/java/cn/aioa/resource/service/HttpEmbeddingProvider.java",
    "aioa-bridge/src/main/java/cn/aioa/bridge/service/ToolDispatcher.java",
)

# selftest 用：rel -> 替换后的文本
_OVERRIDES: dict[str, str] = {}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return bool(ok)


def read(rel: str) -> str:
    if rel in _OVERRIDES:
        return _OVERRIDES[rel]
    p = SERVER / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def main_java_files() -> list[str]:
    out = []
    for p in sorted(SERVER.glob("*/src/main/java/**/*.java")):
        out.append(p.relative_to(SERVER).as_posix())
    return out


def main() -> int:
    files = main_java_files()
    check("扫到后端主源码 .java 文件", len(files) > 50, f"{len(files)} 个")

    # ---- C1 工厂存在，且真的把版本钉在 HTTP/1.1 ----
    factory = read(FACTORY_REL)
    check("AgentHttpClient 工厂文件存在", bool(factory), FACTORY_REL)
    check("工厂把客户端版本钉在 HTTP_1_1（这条被删则整个修复失效）",
          PIN in factory and FACTORY_CALL.startswith(FACTORY_CLASS),
          f"含 {PIN}")

    # ---- 找出所有「自己创建 HttpClient 且访问 agent」的类 ----
    agent_files, bare_in_agent = [], []
    for rel in files:
        if rel == FACTORY_REL:
            continue  # 工厂自身就是那个「裸 newBuilder」的正当例外
        text = read(rel)
        if not any(t in text for t in AGENT_TRACE):
            continue
        if not (BARE.search(text) or "agentBuilder()" in text):
            continue  # 只是提到 /internal/v1（controller 服务端、WebClient 调用方）
        agent_files.append(rel)
        m = BARE.search(text)
        if m:
            line = text[: m.start()].count("\n") + 1
            bare_in_agent.append(f"{rel}:{line}")

    check("存在「访问 agent 的 Java 调用点」", len(agent_files) > 0, f"{len(agent_files)} 个文件")

    # ---- C2 访问 agent 的类不得用裸 newBuilder() ----
    check("访问 agent 的类一律不得直接 HttpClient.newBuilder()（否则 body 会被 h2c 升级推迟）",
          not bare_in_agent, "; ".join(bare_in_agent))

    # ---- C3 光 import 不算：必须真的用上工厂 ----
    not_using = [rel for rel in agent_files if "agentBuilder()" not in read(rel)]
    check("每个访问 agent 的类都实际调用了 AgentHttpClient.agentBuilder()",
          not not_using, "; ".join(not_using) + f"  （判定对象 {len(agent_files)} 个："
          + ", ".join(f.split('/')[-1] for f in agent_files) + "）")

    # ---- C4 外网客户端不得顺手用 agent 工厂（要保留 HTTP/2 / ALPN） ----
    leaked = [rel for rel in MUST_NOT_USE_FACTORY if "agentBuilder()" in read(rel)]
    check("外网/第三方客户端未被套上 agent 专用工厂", not leaked, "; ".join(leaked))

    # ---- C5 别在 agent 调用点上把版本显式改回 HTTP/2 ----
    back_to_h2 = [rel for rel in agent_files if "Version.HTTP_2" in read(rel)]
    check("访问 agent 的类没有被显式改回 HTTP_2", not back_to_h2, "; ".join(back_to_h2))

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n===== agent HttpClient 契约：{passed}/{total} 通过 =====")
    return 0 if passed == total else 1


# --------------------------------------------------------------------------- 负向自检

def selftest() -> int:
    """把每项断言故意弄坏，必须每项都报 FAIL —— 否则守卫是恒真的假断言。"""
    cases = []

    # 1) 把工厂里的 HTTP_1_1 改成 HTTP_2 -> C1 必须红
    cases.append(("工厂不再钉 HTTP/1.1", {
        FACTORY_REL: read(FACTORY_REL).replace(PIN, "HttpClient.Version.HTTP_2"),
    }, "工厂把客户端版本钉在 HTTP_1_1"))

    # 2) 把 WorkerScheduleService 改回裸 newBuilder -> C2 必须红
    ws = "aioa-resource/src/main/java/cn/aioa/resource/service/WorkerScheduleService.java"
    cases.append(("定时员工服务回落裸 newBuilder", {
        ws: read(ws).replace(FACTORY_CALL, "HttpClient.newBuilder()"),
    }, "访问 agent 的类一律不得直接 HttpClient.newBuilder()"))

    # 3) 把 agent 工厂用到 GiteeClient 上 -> C4 必须红
    gitee = "aioa-gitee/src/main/java/cn/aioa/gitee/client/GiteeClient.java"
    cases.append(("外网客户端被套上 agent 工厂", {
        gitee: read(gitee).replace("HttpClient.newBuilder()", FACTORY_CALL),
    }, "外网/第三方客户端未被套上 agent 专用工厂"))

    # 4) 把某个 agent 调用点显式改回 HTTP_2 -> C5 必须红
    kpi = "aioa-resource/src/main/java/cn/aioa/resource/service/KpiInsightService.java"
    cases.append(("agent 调用点被改回 HTTP_2", {
        kpi: read(kpi).replace(FACTORY_CALL, "HttpClient.newBuilder().version(HttpClient.Version.HTTP_2)"),
    }, "访问 agent 的类没有被显式改回 HTTP_2"))

    bad = 0
    for title, overrides, expect_name in cases:
        _OVERRIDES.clear()
        _OVERRIDES.update(overrides)
        results.clear()
        print(f"\n--- 负向自检：{title} ---")
        # 静默捕获本轮断言，只留判定
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main()
        got = [(n, ok) for n, ok, _ in results if expect_name in n]
        if not got:
            print(f"[FAIL] 负向自检未命中预期断言名：{expect_name}")
            bad += 1
        elif got[0][1]:
            print(f"[FAIL] 负向自检失败：弄坏「{title}」后断言「{expect_name}」仍然为绿（假断言）")
            bad += 1
        else:
            print(f"[PASS] 负向自检：弄坏「{title}」后「{expect_name}」正确报红")

    _OVERRIDES.clear()
    results.clear()
    print(f"\n===== 负向自检：{len(cases) - bad}/{len(cases)} 项按预期报红 =====")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else main())
