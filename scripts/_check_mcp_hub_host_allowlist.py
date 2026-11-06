# -*- coding: utf-8 -*-
"""mcp-hub 的 Host 白名单哨兵（生产「连接器全部不可用」的回归闸）。

背景（2026-10-31 生产实测）：
    agent 用 `http://mcp-hub:8099/mcp/qq_mail` 访问 hub，拿到失败；模型手里一个 `mcp__*`
    工具都没有，前端只看到「连接器服务暂时不可用」。
根因：`mcp` 的 FastMCP 只在 `transport_security is None` **且** 自身 bind host 是
    127.0.0.1/localhost/::1 时才自动装「只信 localhost」的白名单
    （mcp/server/fastmcp/server.py:191）。hub 由 uvicorn 拉起，那个 host 参数恒为默认
    127.0.0.1 ⇒ 白名单恒生效 ⇒ `Host: mcp-hub:8099` 落不进 `["127.0.0.1:*",
    "localhost:*", "[::1]:*"]` ⇒ **421 Invalid Host header**，卡在所有业务逻辑之前。
    本地一律用 127.0.0.1 测 ⇒ 永远复现不出来。

判据（每条都能因缺陷变红，含运行时与负向对照）：
  H1  `mcp_hub/transport.py` 存在，默认 pattern 同时含 localhost 三件套与 `mcp-hub:*`。
  H2  **两处** FastMCP 构造（builtin 的代理工厂 + wecom_cli 原生工厂）都显式传了
      `transport_security=security_settings()` —— 少一处就等于那台服务器生产必 421。
  H3  运行时：默认 `allowed_hosts()` 含 mcp-hub:*；`AIOS_MCP_ALLOWED_HOSTS` 能追加。
  H4  运行时（用真实 SDK 的 `_validate_host`）：`mcp-hub:8099` 必须通过；
      `evil.example:8099` 必须**不**通过 —— 证明是「加白名单」而不是「关防护」。
  H5  负向自检：把 transport.py 里的 `mcp-hub:*` 抹掉后 H4 必须变红（判据非恒真）。

跑法（必须用 agent 的 venv，里面才有 mcp SDK）：
  D:/aios/agent/.venv/Scripts/python.exe scripts/_check_mcp_hub_host_allowlist.py
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import importlib
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUB = os.path.join(REPO, 'mcp-hub')
TRANSPORT = os.path.join(HUB, 'mcp_hub', 'transport.py')
BUILTIN = os.path.join(HUB, 'mcp_hub', 'builtin.py')
WECOM = os.path.join(HUB, 'mcp_hub', 'wecom_cli', 'server.py')

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


def read(p):
    with open(p, 'r', encoding='utf-8') as f:
        return f.read()


# ── H1 默认白名单含 mcp-hub ────────────────────────────────────
t_src = read(TRANSPORT) if os.path.exists(TRANSPORT) else ''
defaults = re.search(r'_DEFAULT_PATTERNS\s*=\s*\((.*?)\)', t_src, re.S)
h1 = bool(defaults) and 'mcp-hub:*' in defaults.group(1)
base = re.search(r'_BASE_PATTERNS\s*=\s*\((.*?)\)', t_src, re.S)
h1b = bool(base) and all(k in base.group(1) for k in ('127.0.0.1:*', 'localhost:*'))
chk('H1 默认白名单 = localhost 三件套 + mcp-hub:*', h1 and h1b,
    (defaults.group(1).strip() if defaults else '未找到 _DEFAULT_PATTERNS'))

# ── H2 两处 FastMCP 都显式传 transport_security ─────────────────
for tag, path in (('builtin(代理工厂)', BUILTIN), ('wecom_cli(原生工厂)', WECOM)):
    src = read(path)
    calls = re.findall(r'FastMCP\((?:[^()]|\([^()]*\))*\)', src, re.S)
    bad = [c for c in calls if 'transport_security=security_settings()' not in c]
    chk('H2 %s 的 FastMCP 显式传 transport_security' % tag, bool(calls) and not bad,
        bad[0][:80] if bad else '%d 处' % len(calls))

# ── H3/H4 运行时：真实 SDK 的 _validate_host ────────────────────
sys.path.insert(0, HUB)
os.environ.pop('AIOS_MCP_ALLOWED_HOSTS', None)
try:
    importlib.import_module('mcp_hub.transport')
    transport = importlib.import_module('mcp_hub.transport')
    from mcp.server.transport_security import TransportSecurityMiddleware

    hosts = transport.allowed_hosts()
    chk('H3a 默认 allowed_hosts 含 mcp-hub:*', 'mcp-hub:*' in hosts, str(hosts))

    os.environ['AIOS_MCP_ALLOWED_HOSTS'] = 'aios-hub.internal, example.com:*'
    hosts2 = transport.allowed_hosts()
    chk('H3b AIOS_MCP_ALLOWED_HOSTS 能追加（裸主机名补 :*，带端口的原样）',
        'aios-hub.internal:*' in hosts2 and 'example.com:*' in hosts2, str(hosts2))
    os.environ.pop('AIOS_MCP_ALLOWED_HOSTS', None)

    mw = TransportSecurityMiddleware(transport.security_settings())
    chk('H4a Host: mcp-hub:8099 通过（生产访问形态）', mw._validate_host('mcp-hub:8099') is True)
    chk('H4b Host: 127.0.0.1:8099 通过（本地保持可用）', mw._validate_host('127.0.0.1:8099') is True)
    chk('H4c Host: evil.example:8099 拒绝（防护没有被关掉）',
        mw._validate_host('evil.example:8099') is False)

    # ── H5 负向自检：抹掉 mcp-hub:* 后 H4a 必须变红 ─────────────
    from mcp.server.transport_security import TransportSecuritySettings as TSS
    broken = TSS(enable_dns_rebinding_protection=True,
                 allowed_hosts=[h for h in hosts if h != 'mcp-hub:*'])
    mw2 = TransportSecurityMiddleware(broken)
    chk('H5 负向：去掉 mcp-hub:* 后 H4a 必须变红', mw2._validate_host('mcp-hub:8099') is False)
except Exception as e:  # noqa: BLE001
    chk('H3/H4 运行时判据可执行', False, '%s: %s' % (type(e).__name__, e))

print()
if fails:
    print('FAILED %d / %d' % (len(fails), oks + len(fails)))
    for f in fails:
        print('  - ' + f)
    sys.exit(1)
print('PASS %d / %d' % (oks, oks))
