# -*- coding: utf-8 -*-
"""原始字节抓取桩：把 Java HttpClient 真正发出的请求字节 dump 出来。

用途：定位「后端 -> agent /internal/v1/complete 请求体丢失（FastAPI 报 loc:["body"]）」
时，先确认客户端到底发了什么（是否带 Upgrade: h2c、body 是否在同一段、用的哪种 framing）。

起法：python _raw_dump_srv.py <port>
抓到的字节打印到 stdout（ASCII 可见 + 长度）。
"""
import socket
import sys
import threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123


def serve_once():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(8)
    print(f"[raw] listening 127.0.0.1:{PORT}", flush=True)

    def handle(conn, addr, idx):
        conn.settimeout(3.0)
        chunks = []
        try:
            while True:
                d = conn.recv(65536)
                if not d:
                    break
                chunks.append(d)
                if len(d) < 65536:
                    break
        except Exception:
            pass
        raw = b"".join(chunks)
        print(f"===== conn#{idx} from {addr} len={len(raw)} =====", flush=True)
        print(raw.decode("latin-1").replace("\r\n", "\n"), flush=True)
        print("===== end =====\n", flush=True)
        try:
            body = b'{"content":"ok","model":"stub","error":null}'
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
        except Exception:
            pass
        conn.close()

    idx = 0
    while True:
        conn, addr = s.accept()
        idx += 1
        threading.Thread(target=handle, args=(conn, addr, idx), daemon=True).start()


serve_once()
