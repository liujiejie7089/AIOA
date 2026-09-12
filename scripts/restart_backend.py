#!/usr/bin/env python
"""
一键重打后端 fat-jar（含停进程 / 打包 / 校验体积）。

用法：
    python scripts/restart_backend.py            # 停 :8080 → mvnw package → 打印结果
    python scripts/restart_backend.py --no-stop  # 只打包（后端已停时）

注意：只负责「停在 :8080 的进程」与「打包」，不负责启动 —— 启动请用 run_in_background
的常驻任务，否则沙箱会在 tool call 结束后回收子进程：
    java -Dspring.flyway.validate-on-migrate=false -jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar

硬约束（曾踩过）：repackage 期间后端必须已停，否则 JVM 占用 fat-jar，
maven 半路 rename 出 20KB 的 stripped-jar，原 jar 消失、运行中的 JVM 立刻
NoClassDefFoundError 崩。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
JAR = os.path.join(SERVER, "aioa-boot", "target", "aioa-boot-0.1.0-SNAPSHOT.jar")
MIN_JAR_BYTES = 20 * 1024 * 1024  # 真 fat-jar 约 82MB；stripped 版只有 ~20KB


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Windows 控制台默认 GBK，显式指定编码并容错，避免 UnicodeDecodeError。"""
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="gbk", errors="replace", shell=True,
    )


def port_pids(port: int = 8080) -> list[int]:
    out = _run(["netstat", "-ano"]).stdout or ""
    pids: list[int] = []
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            parts = line.split()
            try:
                pid = int(parts[-1])
            except (ValueError, IndexError):
                continue
            if pid and pid not in pids:
                pids.append(pid)
    return pids


def stop_backend() -> None:
    pids = port_pids()
    if not pids:
        print("[stop] :8080 无进程，跳过")
        return
    for pid in pids:
        _run(["powershell", "-NoProfile", "-Command",
              f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"])
        print(f"[stop] 已停 PID {pid}")
    time.sleep(2)
    left = port_pids()
    if left:
        sys.exit(f"[stop] 仍有进程占用 :8080 -> {left}，请手工处理")


def package() -> int:
    t0 = time.time()
    r = _run(["bash", "mvnw", "-o", "-q", "-DskipTests", "package"], cwd=SERVER)
    if r.returncode != 0:
        print((r.stdout or "")[-4000:])
        print((r.stderr or "")[-2000:])
        return r.returncode
    print(f"[build] 打包成功，用时 {time.time() - t0:.0f}s")
    return 0


def verify_jar() -> bool:
    if not os.path.exists(JAR):
        print("[verify] jar 不存在：" + JAR)
        return False
    size = os.path.getsize(JAR)
    mb = size / 1024 / 1024
    if size < MIN_JAR_BYTES:
        print(f"[verify] ❌ jar 仅 {mb:.1f}MB，疑似 stripped-jar（repackage 期间后端未停）")
        return False
    print(f"[verify] ✅ jar {mb:.1f}MB")
    return True


def main() -> None:
    if "--no-stop" not in sys.argv:
        stop_backend()
    rc = package()
    if rc != 0:
        sys.exit(rc)
    if not verify_jar():
        sys.exit(1)
    print("[done] 请再用常驻任务启动后端：")
    print("  cd server && java -Dspring.flyway.validate-on-migrate=false "
          "-jar aioa-boot/target/aioa-boot-0.1.0-SNAPSHOT.jar")


if __name__ == "__main__":
    main()
