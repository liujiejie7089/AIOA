#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
端到端哨兵：MCP 三层贯通（Java 注册表/信任闸门 → mcp-hub → LangGraph agent）

为什么要有这一条（而不是只看各层单测）
------------------------------------
各层单测都绿、整体仍然不能用，在这类跨语言链路上是常态：
  - Java 发的 probe 请求体键名与 hub 期望的不一致（实测踩过：JDK HttpClient 默认发 h2c 升级，
    uvicorn 不收 HTTP/2，**请求体被丢**，hub 回「未知 transport：None」）；
  - hub 的 tool 名与 Java 种子的 tool 名不一致（模型调到 handler 不认识的工具）；
  - manifest 里的 url 拼错（拼成 /mcp/<code>/mcp）、或 trusted 过滤没生效。
所以这里**用一台真实的 MCP 服务器**（本地 FastMCP echo，监听 8098）走完整链路，
每一步都以「下一步真的能不能用」为判据。

链路（全部真实，无 mock）：
  E1 注册外部服务器  POST /api/v1/mcp/servers            （transport=STREAMABLE_HTTP, url=echo）
  E2 探测            POST /api/v1/mcp/servers/{c}/probe   → hub 真连 echo，拿到 tools
  E3 信任            POST /api/v1/mcp/servers/{c}/trust   → toolCount>0
  E4 manifest 含它   GET  /api/v1/mcp/manifest            → url == echo 地址
  E5 agent 发现工具  ToolClient.list_mcp_tools()          → 出现 mcp__<code>__echo
  E6 agent 真调用    ToolClient.invoke(...)               → ok=True 且含 echo:hi
  E7（负向）取消信任 GET  manifest 不含；新 ToolClient 发现 0 个 → 证明门是真的
  E8 清理            DELETE /api/v1/mcp/servers/{c}
  E9（回归）删除后用**同一个 code** 再注册必须成功
                     —— delete 是逻辑删除，而唯一键 uk_mcp_server(tenant_id, code) 不含 deleted_at
                        ⇒ 软删行会永久占位；不特殊处理时第二次注册直接撞 DuplicateKey 回 500
                        （这条缺陷就是被本哨兵「第二遍跑必红」暴露出来的）

用法：D:/aios/agent/.venv/Scripts/python.exe D:/aios/scripts/_verify_mcp_e2e.py [--base ...]
前置：后端在线（V97 已执行）+ mcp-hub 在 :8099 在线（未在线会明确 FATAL 说明前置）。
退出码 = 失败项数。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent"))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

RESULTS = []
ECHO_PORT = 8098
CODE = "echo_e2e"


def rec(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " —— " + detail)


def call(base, path, method="GET", token=None, body=None, timeout=40):
    url = base.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, "TRANSPORT_ERROR: %s: %s" % (type(e).__name__, e)


def jload(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None


def free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_echo():
    """起一台真实的 MCP 服务器（FastMCP echo），同进程后台线程。"""
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("echo-e2e", streamable_http_path="/mcp")

    @mcp.tool()
    def echo(text: str) -> str:
        """把输入原样回显，前缀 echo:（e2e 探针用，无副作用）"""
        return "echo:" + str(text)

    app = mcp.streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=ECHO_PORT, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(60):
        if not free(ECHO_PORT):
            return server
        time.sleep(0.1)
    raise RuntimeError("echo 服务器未能在 8098 启动")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("AIOS_BASE", "http://127.0.0.1:8080"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("== MCP 三层端到端 @ %s（echo :%d）==" % (base, ECHO_PORT))

    # 前置 1：hub
    st, raw = call("http://127.0.0.1:8099", "/health", timeout=5)
    if st != 200:
        print("  [FATAL] mcp-hub 不在 :8099（HTTP %s）—— 先启动：agent/.venv/Scripts/python.exe mcp-hub/run.py" % st)
        return 1
    # 前置 2：登录
    st, raw = call(base, "/api/v1/auth/login", "POST",
                   body={"username": args.user, "password": args.password})
    token = ((jload(raw) or {}).get("data") or {}).get("accessToken")
    if not token:
        print("  [FATAL] 登录失败（HTTP %s）—— 后端未就绪或账号变更" % st)
        return 1

    echo_app = None
    try:
        # 幂等：先清掉上次残留（DELETE 允许 404）
        call(base, "/api/v1/mcp/servers/" + CODE, "DELETE", token=token)

        # ---------- E1 注册 ----------
        st, raw = call(base, "/api/v1/mcp/servers", "POST", token=token, body={
            "code": CODE, "name": "E2E Echo", "transport": "STREAMABLE_HTTP",
            "url": "http://127.0.0.1:%d/mcp" % ECHO_PORT,
        })
        d = jload(raw) or {}
        item = d.get("data") or {}
        rec("E1 注册外部 MCP 服务器", st == 200 and d.get("code") == 0
            and item.get("code") == CODE and item.get("trusted") is False,
            "HTTP=%s code=%s trusted=%s" % (st, d.get("code"), item.get("trusted")))

        # ---------- E0a 探测失败要留痕（echo 还没起，必然连不上） ----------
        st, raw = call(base, "/api/v1/mcp/servers/%s/probe" % CODE, "POST", token=token)
        d = jload(raw) or {}
        pd0 = d.get("data") or {}
        st_l, raw_l = call(base, "/api/v1/mcp/servers", token=token)
        row0 = {i.get("code"): i for i in ((jload(raw_l) or {}).get("data") or [])}.get(CODE) or {}
        rec("E0a 探测失败 ⇒ ok=false 且 lastError 落库（失败要留痕）",
            pd0.get("ok") is False and bool(row0.get("lastError")),
            "ok=%s lastError=%r" % (pd0.get("ok"), row0.get("lastError")))

        # 现在才起 echo（这样下一步的探测是「由失败转成功」，才能验证 lastError 被清空）
        echo_app = start_echo()
        time.sleep(0.5)

        # ---------- E2 探测（真连 echo） ----------
        st, raw = call(base, "/api/v1/mcp/servers/%s/probe" % CODE, "POST", token=token)
        d = jload(raw) or {}
        pd = d.get("data") or {}
        names = [t.get("name") for t in (pd.get("tools") or [])]
        rec("E2 探测：hub 真连 echo 并列出工具", st == 200 and pd.get("ok") is True and "echo" in names,
            "ok=%s tools=%s error=%r" % (pd.get("ok"), names, pd.get("error")))

        # ---------- E2b 由失败转成功后 lastError 必须被清空（MyBatis-Plus 的 null 陷阱） ----------
        st_l, raw_l = call(base, "/api/v1/mcp/servers", token=token)
        row1 = {i.get("code"): i for i in ((jload(raw_l) or {}).get("data") or [])}.get(CODE) or {}
        rec("E2b 探测成功后 lastError 被清空（不是永远挂着上次的错误）",
            row1.get("lastError") is None and row1.get("status") == "OK",
            "lastError=%r status=%r" % (row1.get("lastError"), row1.get("status")))

        # ---------- E3 信任 ----------
        st, raw = call(base, "/api/v1/mcp/servers/%s/trust" % CODE, "POST", token=token)
        d = jload(raw) or {}
        td = d.get("data") or {}
        rec("E3 信任：探测通过才置 trusted 并登记目录",
            st == 200 and td.get("ok") is True and (td.get("toolCount") or 0) >= 1,
            "data=%s" % td)

        # ---------- E4 manifest ----------
        st, raw = call(base, "/api/v1/mcp/manifest", token=token)
        d = jload(raw) or {}
        ents = {i.get("code"): i for i in (d.get("data") or [])}
        ent = ents.get(CODE) or {}
        rec("E4 manifest 含该服务器且 url 指向 echo（不拼 hub 前缀）",
            ent.get("url") == "http://127.0.0.1:%d/mcp" % ECHO_PORT,
            "entries=%s url=%r" % (list(ents.keys()), ent.get("url")))

        # ---------- E5/E6 agent 侧 ----------
        from aios_ai.config import settings
        from aios_ai.tools.client import ToolClient

        os.environ["AIOS_MCP_HUB"] = "true"
        settings.mcp_hub_enabled = True
        client = ToolClient(base, token)
        import asyncio

        async def agent_side():
            tools = await client.list_mcp_tools()
            names = [((t.get("function") or {}).get("name")) for t in tools]
            want = "mcp__%s__echo" % CODE
            inv = await client.invoke(want, {"text": "hi"})
            return names, want, inv, client.mcp_error

        names, want, inv, mcp_err = asyncio.run(agent_side())
        rec("E5 agent 通过 MCP 协议发现工具（前缀 mcp__<server>__<tool>）",
            want in names, "names=%s want=%s mcp_error=%r" % (names, want, mcp_err))
        rec("E6 agent 真调用成功并拿到 echo:hi",
            inv.ok is True and "echo:hi" in str(inv.data),
            "ok=%s data=%r error=%r" % (inv.ok, inv.data, inv.error))

        # ---------- E7 负向：取消信任后立刻不可见 ----------
        st, raw = call(base, "/api/v1/mcp/servers/%s/untrust" % CODE, "POST", token=token)
        st2, raw2 = call(base, "/api/v1/mcp/manifest", token=token)
        codes = [i.get("code") for i in ((jload(raw2) or {}).get("data") or [])]
        client2 = ToolClient(base, token)
        names2 = asyncio.run(client2.list_mcp_tools())
        rec("E7（负向）取消信任 ⇒ manifest 与 agent 工具表都立刻清空",
            CODE not in codes and names2 == [],
            "manifest=%s agent_tools=%s" % (codes, [((t.get('function') or {}).get('name')) for t in names2]))

        # ---------- E8 清理 ----------
        st, raw = call(base, "/api/v1/mcp/servers/" + CODE, "DELETE", token=token)
        rec("E8 清理：删除外部服务器（幂等复原）", st == 200,
            "HTTP=%s body=%s" % (st, raw[:120]))

        # ---------- E9（回归）删除后同 code 再注册 ----------
        # 判据落点：注册接口的**状态码**必须是 200 而不是 500。
        st, raw = call(base, "/api/v1/mcp/servers", "POST", token=token, body={
            "code": CODE, "name": "E2E Echo (rereg)", "transport": "STREAMABLE_HTTP",
            "url": "http://127.0.0.1:%d/mcp" % ECHO_PORT,
        })
        d = jload(raw) or {}
        item = d.get("data") or {}
        rec("E9 删除后同 code 可再注册（软删残行不占唯一键）",
            st == 200 and d.get("code") == 0 and item.get("code") == CODE
            and item.get("trusted") is False,
            "HTTP=%s code=%s trusted=%s body=%s" % (st, d.get("code"), item.get("trusted"), raw[:120]))
        # 复原：删掉 E9 这行（下一轮 E1 前的幂等清理也能兜住）
        call(base, "/api/v1/mcp/servers/" + CODE, "DELETE", token=token)
    finally:
        try:
            if echo_app is not None:
                echo_app.should_exit = True
        except Exception:
            pass
        # 兜底清理：即使中途失败也不留下注册行
        try:
            call(base, "/api/v1/mcp/servers/" + CODE, "DELETE", token=token)
        except Exception:
            pass

    failed = [r for r in RESULTS if not r[1]]
    print("\n%s（%d/%d）" % ("全部通过 ✅" if not failed else "存在失败 ❌",
                             len(RESULTS) - len(failed), len(RESULTS)))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
