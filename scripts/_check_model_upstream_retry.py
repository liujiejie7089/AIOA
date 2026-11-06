# -*- coding: utf-8 -*-
"""上游模型瞬时故障重试哨兵 —— 纯本地，不花 token、不依赖外网。

## 为什么要有这个

2026-10-31 用户现场：问「企业微信」→ 追问「2」→ 界面「生成失败：
`{"code":"MODEL_UPSTREAM_ERROR","message":"status=500 {...\"unknown error, 999 (1000)\"...request_id...}"}`」。
复核结论：**请求本身没问题**（同一份 messages+tools 重发即 200，agent 日志两轮都是 200 OK），
是 MiniMax 侧的瞬时 5xx。但原先一遇 500 就直接把裸 JSON 甩给用户、且**一次都不重试**。

两项修复：
  1. `_post_stream` / `_post_non_stream` 对 408/409/425/429/5xx 做指数退避重试
     （默认 3 次尝试；`AIOS_MODEL_RETRY_ATTEMPTS` 可调）。
  2. 报错文案改成「给人看的一句话」（`UpstreamError.user_message`），
     原始 JSON + request_id 只进日志（`detail` 字段留档）。

## 判据（每条都能因缺陷变红）

  R1  500,500,200 ⇒ 最终成功，上游收到 **3** 次请求，delta 完整（证明真重试了）。
  R2  持久 500 ⇒ 抛 UpstreamError(status=500)，上游收到 **3** 次（默认上限）。
  R3  401 ⇒ 只请求 **1** 次（认证失败重试没有意义，只会拖慢报错）。
  R4  **中途断流**（已吐过一个 delta 后连接被掐）⇒ 只请求 **1** 次、
      且 delta 只出现一次（重试会在界面上把同一段话打两遍，比重试失败更糟）。
  R5  HTTP 200 但 `base_resp.status_code=1000` ⇒ 必须当失败抛出，
      不能「成功」收口成空回答（MiniMax 的错会藏在 200 的 body 里）。
  R6  `user_message` 不含 JSON 花括号 / request_id，且按状态码给出可执行建议。
  R7  `AIOS_MODEL_RETRY_ATTEMPTS=1` ⇒ 只尝试 1 次（开关真的生效）。
  S1  静态：facade 用 `exc.user_message` 而非 `str(exc)`，且把原始串放进 `detail`。

跑法：
  cd agent && ./.venv/Scripts/python.exe ../scripts/_check_model_upstream_retry.py

退出码非零 = 有断言失败。
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import asyncio
import json
import os
import sys

AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agent')
sys.path.insert(0, AGENT_DIR)

import httpx  # noqa: E402

from aios_ai.llm import upstream  # noqa: E402

fails = []
oks = 0


def chk(name, ok, detail=''):
    global oks
    tag = 'OK  ' if ok else 'FAIL'
    print('[%s] %s%s' % (tag, name, (' — ' + str(detail)) if detail else ''), flush=True)
    if ok:
        oks += 1
    else:
        fails.append(name + (' — ' + str(detail) if detail else ''))
    return ok


class Provider:
    """最小 provider 桩：被测代码只用到 model / base_url 两个属性。"""

    def __init__(self, base_url):
        self.model = 'stub-model'
        self.base_url = base_url


SSE_OK = (b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0\xe5\xa5\xbd"}}]}\n\n'
          b'data: [DONE]\n\n')

# 场景：路径前缀 -> (响应序列, 行为)
#   行为 'plain'  : 按 Content-Length 整段返回
#   行为 'broken' : chunked 发一个 delta 后直接掐断（不发结束块）
SCENARIOS = {
    '/s1': {'codes': [500, 500, 200], 'count': 0},
    '/s2': {'codes': [500, 500, 500, 500, 500], 'count': 0},
    '/s3': {'codes': [401], 'count': 0},
    '/s5': {'codes': [200], 'count': 0},
}


class Server:
    """一个极简 HTTP/1.1 服务器：按路径前缀决定这一轮返回什么。"""

    def __init__(self):
        self.counts = {}
        self.server = None
        self.port = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    def base(self, prefix):
        return 'http://127.0.0.1:%d%s' % (self.port, prefix)

    async def _handle(self, reader, writer):
        try:
            head = b''
            while b'\r\n\r\n' not in head:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                head += chunk
            line = head.split(b'\r\n', 1)[0].decode('latin-1')
            path = line.split(' ')[1] if ' ' in line else '/'
            prefix = '/' + path.strip('/').split('/')[0] if path.strip('/') else '/'
            self.counts[prefix] = self.counts.get(prefix, 0) + 1
            n = self.counts[prefix]

            if prefix == '/s4':
                # 中途断流：先给一个合法 SSE 分片，然后**不发结束块**直接关连接
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                             b'Transfer-Encoding: chunked\r\n\r\n')
                first = b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n'
                writer.write(('%x\r\n' % len(first)).encode() + first + b'\r\n')
                await writer.drain()
                await asyncio.sleep(0.05)
                writer.close()
                return

            sc = SCENARIOS.get(prefix, {'codes': [200]})
            code = sc['codes'][min(n - 1, len(sc['codes']) - 1)]

            if prefix == '/s5':
                body = json.dumps({"base_resp": {"status_code": 1000, "status_msg": "unknown error"},
                                   "choices": []}).encode()
                ctype = b'application/json'
            elif code == 200:
                body = SSE_OK
                ctype = b'text/event-stream'
            else:
                body = json.dumps({"type": "error",
                                   "error": {"type": "server_error",
                                             "message": "unknown error, 999 (1000)",
                                             "http_code": str(code)}}).encode()
                ctype = b'application/json'

            writer.write(b'HTTP/1.1 %d X\r\nContent-Type: ' % code + ctype +
                         b'\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n'
                         b'Connection: close\r\n\r\n' + body)
            await writer.drain()
        except Exception as e:  # noqa: BLE001
            print('  [server] %r' % e, flush=True)
        finally:
            try:
                writer.close()
            except Exception:
                pass


async def call_stream(base_url, messages=None):
    """跑一次 _post_stream，返回 (deltas, done_message, 抛出的异常)。"""
    deltas, done, err = [], None, None
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        try:
            async for kind, *rest in upstream._post_stream(
                    client, Provider(base_url), 'k',
                    messages if messages is not None else [{'role': 'user', 'content': 'hi'}],
                    None, 0.3):
                if kind == 'delta':
                    deltas.append(rest[0])
                else:
                    done = rest[0]
        except Exception as exc:  # noqa: BLE001
            err = exc
    return deltas, done, err


async def main():
    srv = Server()
    await srv.start()
    try:
        # ================= R1：重试后成功 =================
        print('\n=== R1：500,500,200 应重试成功 ===')
        d1, done1, err1 = await call_stream(srv.base('/s1'))
        chk('R1 最终成功（无异常）', err1 is None and done1 is not None, repr(err1))
        chk('R1 delta 完整', ''.join(d1) == '你好', d1)
        chk('R1 上游收到 3 次请求（证明真重试）', srv.counts.get('/s1') == 3,
            'count=%s' % srv.counts.get('/s1'))

        # ================= R2：持久 500 =================
        print('\n=== R2：持久 500 应重试到上限再抛 ===')
        d2, done2, err2 = await call_stream(srv.base('/s2'))
        chk('R2 抛 UpstreamError', isinstance(err2, upstream.UpstreamError), repr(err2))
        chk('R2 status=500', getattr(err2, 'status', None) == 500, getattr(err2, 'status', None))
        chk('R2 尝试 3 次（默认上限）', srv.counts.get('/s2') == 3,
            'count=%s' % srv.counts.get('/s2'))
        chk('R2 无 delta 泄漏给用户', d2 == [], d2)

        # ================= R3：401 不重试 =================
        print('\n=== R3：401 不应重试 ===')
        d3, done3, err3 = await call_stream(srv.base('/s3'))
        chk('R3 抛 UpstreamError', isinstance(err3, upstream.UpstreamError), repr(err3))
        chk('R3 只请求 1 次（认证失败重试无意义）', srv.counts.get('/s3') == 1,
            'count=%s' % srv.counts.get('/s3'))

        # ================= R4：中途断流不重试 =================
        print('\n=== R4：吐过一个 delta 后断流 ⇒ 不得重试（否则正文重复两遍）===')
        d4, done4, err4 = await call_stream(srv.base('/s4'))
        chk('R4 已吐出的 delta 只出现一次', len(d4) == 1, d4)
        chk('R4 只请求 1 次（不重试）', srv.counts.get('/s4') == 1,
            'count=%s' % srv.counts.get('/s4'))
        chk('R4 断流异常向上抛（不静默当成完成）', err4 is not None, repr(err4))

        # ================= R5：HTTP 200 + base_resp 错误 =================
        print('\n=== R5：HTTP 200 但 base_resp.status_code=1000 ===')
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            try:
                await upstream._post_non_stream(
                    client, Provider(srv.base('/s5')), 'k', [{'role': 'user', 'content': 'hi'}], None)
                err5 = None
            except Exception as exc:  # noqa: BLE001
                err5 = exc
        chk('R5 必须抛错（不能当成功收口成空回答）',
            isinstance(err5, upstream.UpstreamError), repr(err5))

        # ================= R6：给人看的文案 =================
        print('\n=== R6：user_message 可读性 ===')
        msg500 = upstream.UpstreamError(500, '{"code":"MODEL_UPSTREAM_ERROR",'
                                             '"request_id":"073505e67e7655cf97df508dd3e45523"}')
        um = msg500.user_message
        chk('R6 含「模型服务暂时不可用」', '模型服务暂时不可用' in um, um)
        chk('R6 不含花括号/request_id（不是裸 JSON）',
            ('{' not in um) and ('request_id' not in um), um)
        chk('R6 429 给出「频繁」提示',
            '频繁' in upstream.UpstreamError(429, '').user_message,
            upstream.UpstreamError(429, '').user_message)
        chk('R6 401 指向「模型密钥」',
            '密钥' in upstream.UpstreamError(401, '').user_message,
            upstream.UpstreamError(401, '').user_message)
        chk('R6 retryable 只对 5xx/429 成立',
            upstream.UpstreamError(500, '').retryable is True
            and upstream.UpstreamError(401, '').retryable is False)

        # ================= R7：次数可配 =================
        print('\n=== R7：AIOS_MODEL_RETRY_ATTEMPTS=1 应只试 1 次 ===')
        old = os.environ.get('AIOS_MODEL_RETRY_ATTEMPTS')
        os.environ['AIOS_MODEL_RETRY_ATTEMPTS'] = '1'
        try:
            srv.counts['/s2'] = 0
            _, _, err7 = await call_stream(srv.base('/s2'))
        finally:
            if old is None:
                os.environ.pop('AIOS_MODEL_RETRY_ATTEMPTS', None)
            else:
                os.environ['AIOS_MODEL_RETRY_ATTEMPTS'] = old
        chk('R7 抛 UpstreamError', isinstance(err7, upstream.UpstreamError), repr(err7))
        chk('R7 只请求 1 次（开关生效）', srv.counts.get('/s2') == 1,
            'count=%s' % srv.counts.get('/s2'))
    finally:
        await srv.stop()

    # ================= S1：静态契约 =================
    print('\n=== S1：静态契约 ===')
    facade = os.path.join(AGENT_DIR, 'aios_ai', 'graph', 'facade.py')
    with open(facade, encoding='utf-8') as f:
        fsrc = f.read()
    chk('S1 facade 用 exc.user_message', 'exc.user_message' in fsrc)
    chk('S1 facade 不再把 str(exc) 当用户文案',
        '"message": str(exc)[:200]' not in fsrc)
    chk('S1 原始串仍留档（detail 字段）', '"detail": str(exc)[:200]' in fsrc)
    chk('S1 retryable 跟随实际可重试性', '"retryable": exc.retryable' in fsrc)

    print('\n' + ('=' * 60))
    if fails:
        print('FAILED %d / %d' % (len(fails), oks + len(fails)))
        for x in fails:
            print('  - ' + x)
        return 1
    print('ALL PASS  %d 项' % oks)
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
