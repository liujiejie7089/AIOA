"""Java → agent `/internal/v1/*` 调用必须携带服务间令牌（B-1 的结构性哨兵）。

为什么需要这条静态哨兵
----------------------
2026-10-18 之前 agent 的内部端点**零鉴权**，于是「漏带票」这个缺陷不存在。
补上中间件（`agent/app/main.py::_require_service_jwt`）之后，**任何新增的 Java 调用方**
只要忘了 `.header("Authorization", ...)`，就会在运行期拿到 401 —— 而症状千差万别：
  - `WorkerIntakeService` 会**静默降级**成 Java 本地关键词推断（`source=local-fallback`），
    用户只会觉得「意图识别变笨了」；
  - `WorkerScheduleService` 把 401 写进 run 的 `error_msg`，看起来像「模型不可用」；
  - `KpiInsightService` 抛「AI 服务返回 HTTP 401」，归因指向模型网关。
三种症状都不指向「少了一行 header」，靠人肉 review 抓不住。故把它变成静态检查。

判据
----
1. 扫描 `server/**/src/main/java/**/*.java`；
2. 定位所有 `.uri(...)` 里出现 `/internal/v1/` 的请求块，且该文件确实在调 agent
   （出现 `agentBaseUrl` 或 `agentWebClient` 之一）；
3. 每个块内（`.uri(` 起 12 行内）必须出现 `Authorization`；
4. `--selftest` 用内置样例证明「漏票会红、带票不会红」（否则这条哨兵可能是恒真的）。

用法
----
    python scripts/_check_internal_service_auth.py           # 静态检查
    python scripts/_check_internal_service_auth.py --selftest  # 判别力自检
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
WINDOW = 12                     # .uri( 之后看多少行
URI_RE = re.compile(r"\.uri\((.*?)\)", re.S)
URI_CALL_RE = re.compile(r"^\s*\.uri\(", re.M)
INTERNAL = "/internal/v1/"


def java_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.java") if "src\\main\\java" in str(p) or "src/main/java" in str(p))


def scan_text(text: str, name: str = "<inline>") -> list[str]:
    """返回违规描述列表（空 = 通过）。"""
    if "agentBaseUrl" not in text and "agentWebClient" not in text:
        return []                      # 不是调 agent 的文件（如 Java 侧自己的 InternalToolController）
    lines = text.splitlines()
    problems: list[str] = []
    for idx, line in enumerate(lines):
        if INTERNAL not in line:
            continue
        # 只认「请求构造行」：.uri(...) 或 f-string 形式的 uri 变量；否则会误报注释/文档
        if ".uri(" not in line and "INTERNAL" not in line:
            continue
        if line.strip().startswith("*") or line.strip().startswith("//"):
            continue
        window = "\n".join(lines[idx: idx + WINDOW])
        # 大小写不敏感：既接受字面量 "Authorization"，也接受 `HttpHeaders.AUTHORIZATION` 常量
        # （RunService 用的正是后者 —— 2026-10-18 首版哨兵在这里误报过一次）。
        if "authorization" not in window.lower():
            problems.append(f"{name}:{idx + 1}: {line.strip()[:90]}")
    return problems


def collect() -> tuple[list[str], int]:
    problems: list[str] = []
    checked = 0
    for path in java_files(SERVER):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = scan_text(text, str(path.relative_to(ROOT)))
        if INTERNAL in text and ("agentBaseUrl" in text or "agentWebClient" in text):
            checked += 1
        problems.extend(found)
    return problems, checked


SELFTEST_CASES = [
    # (说明, 源码, 期望是否有违规)
    ("漏票：builder 里没有 Authorization", """
private static final String X = "/internal/v1/complete";
HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create(agentBaseUrl + "/internal/v1/complete"))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(body))
        .build();
""", True),
    ("带票：同一 builder 上有 Authorization", """
HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create(agentBaseUrl + "/internal/v1/complete"))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer " + serviceTokenProvider.generate(SVC_SERVER))
        .POST(HttpRequest.BodyPublishers.ofString(body))
        .build();
""", False),
    ("WebClient 漏票", """
subscription = agentWebClient.post()
        .uri("/internal/v1/tasks")
        .accept(MediaType.TEXT_EVENT_STREAM)
        .bodyValue(request)
        .retrieve();
""", True),
    ("带票（HttpHeaders.AUTHORIZATION 常量形式）", """
subscription = agentWebClient.post()
        .uri("/internal/v1/tasks")
        .accept(MediaType.TEXT_EVENT_STREAM)
        .header(HttpHeaders.AUTHORIZATION,
                "Bearer " + serviceTokenProvider.generate(SVC_SERVER))
        .bodyValue(request);
""", False),
    ("非 agent 文件（不出现 agentBaseUrl）→ 不误报", """
// 本文件只在文档里提到 /internal/v1/tools
String s = "/internal/v1/tools";
""", False),
]


def selftest() -> int:
    bad = 0
    for label, src, expect in SELFTEST_CASES:
        got = bool(scan_text(src))
        ok = got == expect
        print(f"[{'PASS' if ok else 'FAIL'}] 自检 {label} —— 期望违规={expect} 实际={got}")
        bad += 0 if ok else 1
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    problems, checked = collect()
    print(f"扫描 {checked} 个调 agent 的 Java 文件")
    if problems:
        print(f"\n[FAIL] {len(problems)} 处 /internal/v1/ 请求未带服务间令牌：")
        for p in problems:
            print("  -", p)
        print("\n修法：在同一个 HttpRequest/WebClient 链上加")
        print('      .header("Authorization", "Bearer " + serviceTokenProvider.generate(SVC_SERVER))')
        return 1
    print("[OK] 所有 /internal/v1/ 请求都带 Authorization")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
