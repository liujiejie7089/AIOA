#!/usr/bin/env python3
"""
AIOA 用户端 —— 统一联调服务器

作用：
  1. 静态托管 user-client（H5 用户端）
  2. 把 /api/* 反向代理到后端 Spring Boot(:8080)，前端同源访问，规避 CORS
  3. 支持 SSE 流式转发（/api/v1/runs/{runId}/events），事件到达即刷给浏览器

用法：
  python serve.py [port]      默认 5180
"""
import http.client
import http.server
import os
import socketserver
import sys
from urllib.parse import parse_qs, urlencode, urlparse

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5180

HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "upgrade"}


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ---------- 路由 ----------
    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            self._proxy("DELETE")
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ---------- 代理核心 ----------
    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        fwd = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length", "connection", "accept-encoding")
        }

        # SSE 专用桥接：浏览器 EventSource 无法自定义请求头，
        # 因此允许用 ?token=xxx 传递 JWT，由代理翻译成 Authorization 头。
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        token = qs.pop("token", [None])[0]
        if token:
            fwd["Authorization"] = "Bearer " + token
            rest = urlencode({k: v[0] for k, v in qs.items()})
            self.path = parsed.path + (("?" + rest) if rest else "")

        try:
            conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=180)
            conn.request(method, self.path, body=body, headers=fwd)
            resp = conn.getresponse()
        except Exception as exc:  # 后端不可达
            msg = ("BACKEND_UNREACHABLE: %s" % exc).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self._cors()
            self.end_headers()
            self.wfile.write(msg)
            return

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in HOP_BY_HOP:
                continue
            self.send_header(k, v)
        # SSE / 流式：禁用代理层缓冲
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()

        try:
            while True:
                # 关键：http.client 的 read(amt) 会一直累积到 amt 字节才返回，
                # 会导致 SSE 被"攒着"不发。用 read(1) 保证收到 1 字节就立刻转发。
                chunk = resp.read(1)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type,Last-Event-ID")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")

    # ---------- 静态资源 ----------
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print("AIOA 用户端联调服务: http://127.0.0.1:%d  ->  backend %s:%d"
          % (PORT, BACKEND_HOST, BACKEND_PORT))
    with Server(("127.0.0.1", PORT), ProxyHandler) as httpd:
        httpd.serve_forever()
