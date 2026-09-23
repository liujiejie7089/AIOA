# -*- coding: utf-8 -*-
"""agent 侧「h2c 升级请求体会不会丢」的判别探针（不依赖 JDK）。

它复刻 java.net.http.HttpClient 默认（HTTP/2 优先）对明文 http:// 目标的行为：
    1. 先发请求头，其中带 Upgrade: h2c / Connection: Upgrade, HTTP2-Settings；
    2. **flush 之后再单独发请求体**（Java 正是把 body 推迟到 upgrade 之后）。
实测差异（2026-09-22）：
    uvicorn --http httptools（uvicorn[standard] / 生产镜像）-> 422，body 丢失
    uvicorn --http h11（裸 uvicorn）                        -> 200，body 正常

因此本探针同时是「agent 在跑哪个实现」的判别器，也是「缺陷有没有被环境掩盖」的闸门：
    422 = 未掩盖（可用来证明修复有效）
    200 = 已被 h11 掩盖（此时任何端到端通过都证明不了后端修复）

用法：
    python scripts/_probe_agent_h2c.py            # 打印状态码与判定
    python scripts/_probe_agent_h2c.py --quiet     # 只打印 MASKED / EXPOSED
退出码：0 = EXPOSED（未掩盖，符合预期）；2 = MASKED（被掩盖）；1 = 连不上。
"""
from __future__ import annotations

import argparse
import base64
import re
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 8000
PATH = "/internal/v1/complete"
BODY = b'{"prompt":"hi","system":"s","max_tokens":16}'
SETTINGS = base64.urlsafe_b64encode(b"\x00\x03\x00\x00\x00\x64\x00\x04\x00\x00\x00\x00").rstrip(b"=")
GAP = 0.25  # 秒：头与体之间的间隔，复刻 Java 的「推迟发送」


def probe(host: str = HOST, port: int = PORT, gap: float = GAP) -> tuple[int, bytes]:
    head = (
        f"POST {PATH} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Connection: Upgrade, HTTP2-Settings\r\n"
        "Upgrade: h2c\r\n"
        f"HTTP2-Settings: {SETTINGS.decode()}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(BODY)}\r\n"
        "\r\n"
    ).encode()
    s = socket.create_connection((host, port), timeout=20)
    try:
        s.sendall(head)
        time.sleep(gap)
        s.sendall(BODY)
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = s.recv(65536)
            if not d:
                break
            buf += d
            if len(buf) > 65536:
                break
        m = re.match(rb"HTTP/1\.[01]\s+(\d{3})", buf)
        return (int(m.group(1)) if m else -1), buf
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--gap", type=float, default=GAP)
    a = ap.parse_args()

    try:
        status, raw = probe(gap=a.gap)
    except OSError as e:
        print(f"[ERR] agent 不可达：{e}")
        return 1

    if status == 422:
        verdict, code = "EXPOSED", 0
        detail = "agent 在 httptools 实现下：h2c 升级请求的 body 会被丢掉（缺陷未被掩盖，可验证修复）"
    elif status == 200:
        verdict, code = "MASKED", 2
        detail = "agent 在 h11 实现下：h11 恰好保住了 body（缺陷被掩盖，端到端通过说明不了问题）"
    else:
        verdict, code = "UNEXPECTED", 1
        detail = f"未预期的状态码 {status}"

    if a.quiet:
        print(verdict)
    else:
        print(f"status={status} -> {verdict}")
        print(f"  {detail}")
        print(f"  响应首行：{raw.split(chr(13).encode())[0][:80]!r}")
    return code


if __name__ == "__main__":
    sys.exit(main())
