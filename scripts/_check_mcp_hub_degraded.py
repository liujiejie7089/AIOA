# -*- coding: utf-8 -*-
"""mcp-hub「存储不可用不得拖死全部连接器」的回归哨兵（离线、进程内驱动 ASGI，不开端口）。

背景（2026-10-31 生产事故链，三环相扣）：
    ① 容器内 `/app/data` 属主是 root，hub 以 uid 10001 运行 ⇒
       `wecom/store.py::init()` 抛 `PermissionError: [Errno 13] '/app/data'`；
    ② `app.py::_lifespan` 当时**直接 raise** ⇒ uvicorn 打印
       「ASGI 'lifespan' protocol appears unsupported.」却**照常开始服务**；
    ③ 子 app 全部没启动 ⇒ `/health` 仍 200（看起来健康）、`/api/v1/wecom_cli/qr`
       也还能出二维码，但 `/mcp/<code>` 全部落到死 app 上 ⇒ 连接器全线不可用
       （H5 只显示「连接器服务暂时不可用」）。

判据（每条都能因缺陷变红，含负向自检）：
  D1  存储 init 失败时 `_lifespan` 仍必须完成启动（不中断）。
  D2  此时 `/health` 必须 503，且 message 里带「初始化失败」+ 具体异常类型。
  D3  此时 `/mcp/qq_mail` 的 initialize 必须 **200** —— qq_mail 只是转发给 Java，
      不依赖 SQLite/密钥，不该被 wecom 的存储故障连坐（这是修复的核心价值）。
  D4  正常模式（临时可写目录）下 `/health` 与 `/mcp/qq_mail` 都必须 200。
  D5  负向自检：人为把 `_INIT_ERROR` 清空后 D2 必须变回 200（判据非恒真）。

★ 实现纪律：lifespan 与 HTTP 调用**必须在同一个事件循环**里跑。
  FastMCP 的 StreamableHTTPSessionManager 把 task group 绑在「跑 lifespan 的那个循环」上，
  分成两次 `asyncio.run()` 会拿到 500「Task group is not initialized」—— 那是哨兵自己的
  假失败（而且恒红，与缺陷无关），第一版就这么踩了。

跑法（必须用 agent 的 venv，里面才有 mcp SDK）：
  D:/aios/agent/.venv/Scripts/python.exe scripts/_check_mcp_hub_degraded.py
"""
import asyncio
import importlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(REPO, 'mcp-hub')
sys.path.insert(0, HUB)

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


INIT_BODY = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "degraded-probe", "version": "1"}},
}).encode('utf-8')


def make_scope(path):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"mcp-hub:8099"),  # 生产形态的 Host（坑 46）
                    (b"content-type", b"application/json"),
                    (b"accept", b"application/json, text/event-stream"),
                    (b"content-length", str(len(INIT_BODY)).encode())],
        "client": ("172.26.0.3", 50000), "server": ("mcp-hub", 8099),
    }


async def call_http(mod, path):
    """驱动一次 _handle_http，返回 (status, body_text)。"""
    msgs = []
    state = {'sent': False}

    async def receive():
        if not state['sent']:
            state['sent'] = True
            return {"type": "http.request", "body": INIT_BODY, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(m):
        msgs.append(m)

    await asyncio.wait_for(mod._handle_http(make_scope(path), receive, send), 30)
    start = next((m for m in msgs if m['type'] == 'http.response.start'), None)
    status = start['status'] if start else None
    headers = {k.decode().lower(): v.decode() for k, v in (start or {}).get('headers', [])}
    body = b''.join(m.get('body', b'') for m in msgs if m['type'] == 'http.response.body')
    # 说明：streamable-http 的 SSE 响应体是边算边发的，body 可能抓不全；
    # 判断「真的建了会话」要看 `mcp-session-id` 响应头（见 D3b），不要只看 body。
    return status, body.decode('utf-8', 'replace'), headers


async def scenario(mod):
    """同一事件循环内：启动 lifespan → 打 health/mcp → 负向改状态 → 关闭。"""
    q = asyncio.Queue()
    sent = []

    async def receive():
        return await q.get()

    async def send(m):
        sent.append(m)

    task = asyncio.create_task(mod._lifespan(receive, send))
    await q.put({"type": "lifespan.startup"})
    for _ in range(400):  # 等 startup.complete（最多 20s）
        if any(m["type"] == "lifespan.startup.complete" for m in sent):
            break
        await asyncio.sleep(0.05)

    out = {
        "started": any(m["type"] == "lifespan.startup.complete" for m in sent),
        "health": await call_http(mod, "/health"),
        "mcp": await call_http(mod, "/mcp/qq_mail"),
    }
    keep = mod._INIT_ERROR           # D5 负向：清空后 health 必须回 200
    mod._INIT_ERROR = None
    out["health_cleared"] = await call_http(mod, "/health")
    mod._INIT_ERROR = keep

    await q.put({"type": "lifespan.shutdown"})
    try:
        await asyncio.wait_for(task, 20)
    except Exception:  # noqa: BLE001
        task.cancel()
    return out


def boot(db_path):
    """以新的模块状态启动（避免模块级单例串味）。"""
    os.environ['WECOM_MOCK'] = '1'          # 免密钥，隔离掉「缺 key」这个无关变量
    os.environ['WECOM_DB_PATH'] = db_path
    for name in [m for m in list(sys.modules) if m == 'mcp_hub' or m.startswith('mcp_hub.')]:
        del sys.modules[name]
    return importlib.import_module('mcp_hub.app')


# ── 场景 A：存储不可用（DB 路径的父级是个文件 ⇒ 与生产 EACCES 同一类失败）──
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    blocker = os.path.join(td, 'blocker')
    with open(blocker, 'w', encoding='utf-8') as f:
        f.write('x')
    mod = boot(os.path.join(blocker, 'sub', 'wecom.db'))
    r = asyncio.run(scenario(mod))

    chk('D1 存储 init 失败仍完成 lifespan 启动（不中断）', r["started"])
    chk('D1b 已记录失败原因', bool(mod._INIT_ERROR), str(mod._INIT_ERROR)[:110])

    st, body, _hdrs = r["health"]
    chk('D2 /health 转 503（不再「健康但全废」）', st == 503, 'HTTP=%s' % st)
    chk('D2b /health 的 message 带原因与异常类型',
        '初始化失败' in body and ('Error' in body or 'Exception' in body), body[:130])

    st_mcp, _body_mcp, hdrs_mcp = r["mcp"]
    chk('D3 存储故障下 /mcp/qq_mail 仍 200（不依赖存储的连接器不被连坐）',
        st_mcp == 200, 'HTTP=%s' % st_mcp)
    chk('D3b 真的建了 MCP 会话（响应头带 mcp-session-id，不是空 200）',
        bool(hdrs_mcp.get('mcp-session-id')), 'headers=%s' % sorted(hdrs_mcp))

    st_clear, _c, _h = r["health_cleared"]
    chk('D5 负向：清空 _INIT_ERROR 后 /health 回到 200（D2 非恒真）',
        st_clear == 200, 'HTTP=%s' % st_clear)

# ── 场景 B：正常模式（可写目录）──
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td2:
    mod2 = boot(os.path.join(td2, 'wecom.db'))
    r2 = asyncio.run(scenario(mod2))
    st, _b, _h = r2["health"]
    chk('D4 正常模式 /health 200 且无 init 错误', st == 200 and mod2._INIT_ERROR is None,
        'HTTP=%s init_error=%s' % (st, mod2._INIT_ERROR))
    st_mcp, _b2, hdrs2 = r2["mcp"]
    chk('D4b 正常模式 /mcp/qq_mail 200 且建了会话',
        st_mcp == 200 and bool(hdrs2.get('mcp-session-id')), 'HTTP=%s' % st_mcp)

print()
if fails:
    print('FAILED %d / %d' % (len(fails), oks + len(fails)))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS %d / %d' % (oks, oks))
