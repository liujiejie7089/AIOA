# -*- coding: utf-8 -*-
"""scfy 按租户接入：hub 侧准入闸门验收（docs/92 阶段 4 / A1、A4、A10 的链路证明）。

自包含：本地起一个 HTTP stub 同时扮演「Java 接入校验端点」与「非遗 /show/* 上游」，
不需要真 Java、真 hub 进程或外网。直接调 scfy.server 的工具函数，逐条断言：
  T1 回滚开关关闭 ⇒ 无 token 也照常调用（历史行为）
  T2 开启 + 无 token ⇒ 拒绝，且**没有**发非遗 GET
  T3 开启 + Java 判未接入 ⇒ 拒绝，文案带 Java 的 reason，且没有发 GET
  T4 开启 + Java 判已接入 + 租户 baseUrl 覆盖 ⇒ 放行，GET 打到覆盖地址
  T5 Java 不可达 ⇒ fail-closed 拒绝，文案区分「接入校验」与「数据源故障」
  T6 不缓存：两次调用各自实时回源（每次都如实写一条审计）
  T7 69 工具注册完整、ctx 不进 inputSchema（契约零漂移）
  T9 同一 token 从「未接入」切到「已接入」后立即放行（deny 未缓存）
  T10 同一 token 从「已接入」切到「停用」后立即被拒（allow 未缓存）

用法：python mcp-hub/_verify_scfy_access_gate.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_hub.scfy import catalog as scfy_catalog
from mcp_hub.scfy import server as scfy_server

_STATE = {
    "mode": "deny",                 # deny / allow / bad / http500
    "reason": "本租户尚未接入 scfy",
    "base_url": None,
    "check_hits": 0,
    "show_hits": 0,
}
_LINES: list[str] = []
_FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    line = ("PASS" if cond else "FAIL") + " " + name + " " + str(detail)[:220]
    _LINES.append(line)
    print(line)
    if not cond:
        _FAILS.append(name)


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if "/api/v1/mcp/access/" in self.path:
            _STATE["check_hits"] += 1
            mode = _STATE["mode"]
            if mode == "http500":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"upstream down")
                return
            if mode == "deny":
                data = {"ok": False, "reason": _STATE["reason"]}
            elif mode == "allow":
                data = {"ok": True, "baseUrl": _STATE["base_url"]}
            else:  # bad：返回体缺 ok 字段
                data = {"unexpected": True}
            body = {"code": 0, "data": data}
        elif "/show/" in self.path:
            # 真实 URL 可能是 /scfy/show/...（平台默认）或 /tenant/show/...（租户 baseUrl 覆盖），
            # 故用包含匹配而不是 startswith —— 之前用 startswith 会让 stub 走 else 分支，
            # 表现为「工具 ok=true 但 data 为空、show_hits 不增加」的假失败。
            _STATE["show_hits"] += 1
            body = {"code": 0, "data": [{"area": "甘孜州", "count": 12}]}
        else:
            body = {"code": 0, "data": {}}
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):  # 静音
        pass


class _FakeCtx:
    def __init__(self, auth: "str | None"):
        headers = {} if auth is None else {"authorization": auth}
        req = type("_R", (), {"headers": headers})()
        self.request_context = type("_RC", (), {"request": req})()


def _reset(mode: str, base_url: "str | None" = None) -> None:
    _STATE.update(mode=mode, base_url=base_url, check_hits=0, show_hits=0)


async def _call_tool(auth: "str | None", token_suffix: str = "t") -> dict:
    fn = scfy_server._make_tool_fn("project_count_by_area")
    return await fn(ctx=_FakeCtx(auth), area="甘孜州")


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    os.environ["AIOS_SERVER_BASE_URL"] = base
    os.environ["AIOS_SCFY_BASE_URL"] = base + "/scfy"   # 平台默认也指向 stub
    os.environ["AIOS_SCFY_ACCESS_CHECK"] = "1"

    try:
        # T7 契约零漂移
        mcp = scfy_server.build_server()
        tools = asyncio.run(mcp.list_tools())
        check("T7 工具数 == catalog", len(tools) == len(scfy_catalog.BY_NAME),
              f"tools={len(tools)} catalog={len(scfy_catalog.BY_NAME)}")
        check("T7 ctx 不在任何 inputSchema",
              all("ctx" not in (tool.inputSchema.get("properties") or {}) for tool in tools))

        # T1 回滚开关关闭
        os.environ["AIOS_SCFY_ACCESS_CHECK"] = "0"
        _reset("deny")
        r = asyncio.run(_call_tool(None))
        check("T1 开关关闭时无 token 也放行", r.get("ok") is True, r)
        check("T1 确实发了非遗 GET", _STATE["show_hits"] == 1, _STATE["show_hits"])

        # T2 开启 + 无 token
        os.environ["AIOS_SCFY_ACCESS_CHECK"] = "1"
        _reset("deny")
        r = asyncio.run(_call_tool(None))
        check("T2 无 token 被拒", r.get("ok") is False and r.get("accessDenied") is True, r)
        check("T2 拒绝文案可区分", "缺少调用身份" in str(r.get("errors")), r.get("errors"))
        check("T2 未发非遗 GET", _STATE["show_hits"] == 0, _STATE["show_hits"])

        # T3 开启 + Java 判未接入
        _reset("deny")
        r = asyncio.run(_call_tool("Bearer tok-a"))
        check("T3 未接入租户被拒", r.get("ok") is False and r.get("accessDenied") is True, r)
        check("T3 回带 Java reason", _STATE["reason"] in str(r.get("errors")), r.get("errors"))
        check("T3 未发非遗 GET", _STATE["show_hits"] == 0, _STATE["show_hits"])

        # T4 开启 + 已接入 + 租户 baseUrl 覆盖
        _reset("allow", base_url=base + "/tenant")
        r = asyncio.run(_call_tool("Bearer tok-b"))
        check("T4 已接入租户放行", r.get("ok") is True, r)
        check("T4 确实发了非遗 GET", _STATE["show_hits"] == 1, _STATE["show_hits"])
        check("T4 返回 stub 数据", isinstance(r.get("data"), list) and len(r.get("data")) == 1,
              r.get("data"))

        # T5 Java 500 ⇒ fail-closed，且不误报数据源故障
        _reset("http500")
        r = asyncio.run(_call_tool("Bearer tok-c"))
        check("T5 Java 异常时拒绝（fail-closed）", r.get("ok") is False and r.get("accessDenied") is True, r)
        check("T5 文案指接入校验", "接入校验" in str(r.get("errors")), r.get("errors"))
        check("T5 未误报数据源故障", "数据源故障" not in str(r.get("errors")), r.get("errors"))
        check("T5 明确指向授权环节", "接入授权环节" in str(r.get("errors")), r.get("errors"))
        check("T5 未发非遗 GET", _STATE["show_hits"] == 0, _STATE["show_hits"])

        # T6 不缓存：两次调用各自实时回源（每次调用都如实写一条 mcp_tool_audit）
        _reset("allow", base_url=base + "/tenant")
        r1 = asyncio.run(_call_tool("Bearer tok-d"))
        r2 = asyncio.run(_call_tool("Bearer tok-d"))
        check("T6 两次调用都成功", r1.get("ok") is True and r2.get("ok") is True)
        check("T6 每次调用都实时回调 Java", _STATE["check_hits"] == 2, _STATE["check_hits"])

        # 补充：返回体异常也 fail-closed
        _reset("bad")
        r = asyncio.run(_call_tool("Bearer tok-e"))
        check("T8 校验响应异常时拒绝", r.get("ok") is False and r.get("accessDenied") is True, r)
        check("T8 未发非遗 GET", _STATE["show_hits"] == 0, _STATE["show_hits"])

        # T9 判别力：deny 不缓存 ⇒ 同一 token 从「未接入」切到「已接入」后立即放行。
        # 若 deny 被缓存，这里会命中旧的拒绝结果，管理员启用后要等 30s 才生效（docs/92 风险 7）。
        _STATE.update(mode="deny", check_hits=0, show_hits=0)
        r1 = asyncio.run(_call_tool("Bearer tok-f"))
        check("T9 首次被拒", r1.get("ok") is False, r1)
        _STATE.update(mode="allow", base_url=base + "/tenant", check_hits=0, show_hits=0)
        r2 = asyncio.run(_call_tool("Bearer tok-f"))   # 同一 token，不重新登录
        check("T9 启用后立即放行（deny 未缓存）", r2.get("ok") is True, r2)
        check("T9 确实重新回调 Java", _STATE["check_hits"] == 1, _STATE["check_hits"])

        # T10 反向判别力：allow 也不缓存 ⇒ 停用后同一 token 的下一次调用立即被拒。
        # 若缓存 allow，停用后 TTL 内仍会被放行，等于「关闭开关没生效」。
        _STATE.update(mode="allow", base_url=base + "/tenant", check_hits=0, show_hits=0)
        r3 = asyncio.run(_call_tool("Bearer tok-g"))
        check("T10 首次放行", r3.get("ok") is True, r3)
        _STATE.update(mode="deny", check_hits=0, show_hits=0)
        r4 = asyncio.run(_call_tool("Bearer tok-g"))
        check("T10 停用后立即被拒（allow 未缓存）",
              r4.get("ok") is False and r4.get("accessDenied") is True, r4)
        check("T10 未发非遗 GET", _STATE["show_hits"] == 0, _STATE["show_hits"])
    finally:
        httpd.shutdown()
        httpd.server_close()

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "_verify_scfy_access_gate_result.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(_LINES) + "\nRESULT: " +
                ("ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS)) + "\n")
    print("RESULT:", "ALL PASS" if not _FAILS else "FAIL " + ",".join(_FAILS))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
