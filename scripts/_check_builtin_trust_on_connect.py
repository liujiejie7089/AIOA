# -*- coding: utf-8 -*-
"""内置连接器「连上即信任」哨兵 —— 纯静态契约 + 负向自检，不需要跑 Spring。

## 现场问题（2026-10-31 生产）

企微扫码成功了、`/api/v1/connectors` 回 `wecom_cli | CONNECTED | 刘洋`，
但 `/api/v1/mcp/manifest` 里只有 `qq_mail`，AI 于是回「没有可用的企业微信连接」。

根因：内置 MCP 服务器的种子行是 **`trusted = 0`**（V97 / V102 都刻意如此），
而 `manifest()` 与 `McpBuiltinBridge.doCall()` **都只认 `trusted = 1`**。
「连上」和「给 AI 用」是两个独立的闸，而从来没人去点过「信任」。

修法：连接态回写成功之后，对**内置**服务器自动过一遍信任闸门。

## 判据

  C1  种子行 trusted=0（V97 的 qq_mail / wechat_work、V102 的 wecom_cli）
      —— 这条固定住「为什么必须有自动信任」。哪天有人把种子改成 1，
      这条会红，提醒复核「信任闸门」的安全语义是否被无意绕过。
  C2  `manifest()` 仍然只返回 trusted=1（闸门不能因为本次改动被放宽）。
  C3  `McpBuiltinBridge.doCall()` 仍然要求 trusted=1（执行期第二道闸）。
  C4  `InternalConnectorController.upsert` 在连接回写**之后**调用自动信任，
      且整段包在 try/catch 里（探测抖不得让授权白扫）。
  C5  自动信任只匹配 `SOURCE_BUILTIN`，绝不碰 EXTERNAL。
  C6  幂等：已 trusted=1 直接返回，不重复探测、不重写工具目录。
  C7  探测失败**仍然**置 trusted=1（setTrusted 在 `if (r.isOk())` 之外）。
  C8  负向自检：把 setTrusted 挪进 `if (r.isOk())` 里 ⇒ C7 必须变红。

跑法：
  C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_builtin_trust_on_connect.py
"""

try:  # A3：GBK 控制台打印 ✅ 会 UnicodeEncodeError；统一按 utf-8 输出（Windows 控制台/伪终端都正确）
    import sys
    sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(REPO, 'server', 'aios-resource', 'src', 'main', 'java', 'cn', 'aios', 'resource')
REGISTRY = os.path.join(RES, 'connector', 'mcp', 'service', 'McpRegistryService.java')
BRIDGE = os.path.join(RES, 'connector', 'mcp', 'service', 'McpBuiltinBridge.java')
INTERNAL = os.path.join(RES, 'connector', 'controller', 'InternalConnectorController.java')
MIG = os.path.join(REPO, 'server', 'aios-boot', 'src', 'main', 'resources', 'db', 'migration')

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


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def strip_comments(src):
    """去掉 // 与 /* */ 注释：判据只认代码，不能被注释里的同名字符串骗过去。"""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)
    return src


def method_body(src, signature):
    """按大括号配对抠出一个方法体（含签名行）。找不到返回空串。"""
    i = src.find(signature)
    if i < 0:
        return ''
    j = src.find('{', i)
    if j < 0:
        return ''
    depth = 0
    for k in range(j, len(src)):
        if src[k] == '{':
            depth += 1
        elif src[k] == '}':
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    return ''


def main():
    for p in (REGISTRY, BRIDGE, INTERNAL):
        if not os.path.exists(p):
            chk('文件存在 %s' % os.path.basename(p), False, p)
            print('\nFAILED')
            return 1

    reg = strip_comments(read(REGISTRY))
    bridge = strip_comments(read(BRIDGE))
    internal = strip_comments(read(INTERNAL))

    # ============ C1：种子行 trusted=0 ============
    print('\n=== C1：内置种子行 trusted=0（自动信任这一步是必需的）===')
    seeds = {}
    for name in ('V97__mcp_server_registry.sql', 'V102__wecom_cli_connector.sql'):
        p = os.path.join(MIG, name)
        if not os.path.exists(p):
            chk('C1 %s 存在' % name, False, p)
            continue
        txt = read(p)
        # 取所有 mcp_server 的 INSERT 行，抓 trusted 列（第 7 个值）
        for m in re.finditer(r"\((\d+),\s*0,\s*'([a-z_]+)',[^)]*?'BUILTIN',\s*'[A-Z_]+',\s*(\d)", txt):
            seeds[m.group(2)] = int(m.group(3))
    chk('C1 抓到内置种子行', len(seeds) >= 3, seeds)
    for code, trusted in seeds.items():
        chk('C1 %s 种子 trusted=0' % code, trusted == 0, trusted)

    # ============ C2 / C3：闸门仍只认 trusted=1 ============
    print('\n=== C2/C3：manifest 与执行闸门仍只认 trusted=1 ===')
    man = method_body(reg, 'public List<ManifestItem> manifest(')
    chk('C2 manifest 里按 trusted=1 过滤',
        '.eq(McpServer::getTrusted, 1)' in man, 'len=%d' % len(man))
    call = method_body(bridge, 'private CallResult doCall(')
    chk('C3 doCall 仍要求 trusted==1',
        'getTrusted()' in call and '!= 1' in call, call[:120])
    chk('C3 doCall 仍要求 CONNECTED',
        'STATUS_CONNECTED' in call)

    # ============ C4：upsert 之后调用、且不阻断连接态 ============
    print('\n=== C4：连接回写后自动信任，且失败不阻断 ===')
    upsert = method_body(internal, 'public ApiResponse<Map<String, Object>> upsert(')
    pos_conn = upsert.find('upsertConnectedByUser')
    pos_trust = upsert.find('trustBuiltinByConnector')
    chk('C4 先写连接态、后自动信任', 0 <= pos_conn < pos_trust, (pos_conn, pos_trust))
    seg = upsert[pos_conn:pos_trust] if pos_trust > pos_conn else ''
    after = upsert[pos_trust:] if pos_trust > 0 else ''
    chk('C4 自动信任包在 try 里', 'try {' in seg)
    chk('C4 自动信任有 catch（不把连接态一起打翻）', 'catch (Exception' in after)
    chk('C4 控制器持有 McpRegistryService', 'McpRegistryService mcpRegistry' in internal)

    # ============ C5 / C6 / C7：自动信任方法本身 ============
    print('\n=== C5/C6/C7：trustBuiltinByConnector 的语义 ===')
    tb = method_body(reg, 'public TrustResult trustBuiltinByConnector(')
    chk('C5 方法存在', bool(tb), 'len=%d' % len(tb))
    chk('C5 只匹配 SOURCE_BUILTIN', 'McpServer.SOURCE_BUILTIN.equals' in tb or
        'eq(McpServer::getSource, McpServer.SOURCE_BUILTIN)' in tb)
    chk('C5 明确不在 EXTERNAL 上自动信任（注释或条件均可）',
        'SOURCE_EXTERNAL' in tb or 'EXTERNAL' not in tb.replace('SOURCE_BUILTIN', ''))
    chk('C5 按 tenant 0 定位内置行', 'eq(McpServer::getTenantId, 0L)' in tb)
    chk('C6 幂等：已 trusted=1 直接返回', 'getTrusted() == 1' in tb and 'return new TrustResult(true' in tb)

    # C7：setTrusted(1) 必须出现在 `if (r.isOk())` 之前（即不受探测结果约束）
    i_trust = tb.find('fresh.setTrusted(1)')
    i_ok = tb.find('if (r.isOk())')
    chk('C7 探测失败也置 trusted=1（setTrusted 在 if(r.isOk()) 之外）',
        i_trust > 0 and (i_ok < 0 or i_trust < i_ok), (i_trust, i_ok))
    chk('C7 只在探测成功时才写工具目录', 'r.isOk() ? syncTools(' in tb or 'if (r.isOk())' in tb)

    # ============ C8：负向自检 ============
    print('\n=== C8：负向自检（把 setTrusted 挪进 if(r.isOk()) 里 ⇒ C7 必须变红）===')
    broken = tb.replace(
        """        fresh.setTrusted(1);
        if (r.isOk()) {
            fresh.setStatus(McpServer.STATUS_OK);
        }""",
        """        if (r.isOk()) {
            fresh.setTrusted(1);
            fresh.setStatus(McpServer.STATUS_OK);
        }""")
    if broken == tb:
        chk('C8 能构造出退化形态（否则这条自检无效）', False, '源码结构与预期不符')
    else:
        bi_trust = broken.find('fresh.setTrusted(1)')
        bi_ok = broken.find('if (r.isOk())')
        degraded_red = not (bi_trust > 0 and (bi_ok < 0 or bi_trust < bi_ok))
        chk('C8 退化后 C7 判据确实变红（证明 C7 有牙）', degraded_red, (bi_trust, bi_ok))

    print('\n' + ('=' * 60))
    if fails:
        print('FAILED %d / %d' % (len(fails), oks + len(fails)))
        for x in fails:
            print('  - ' + x)
        return 1
    print('ALL PASS  %d 项' % oks)
    return 0


if __name__ == '__main__':
    sys.exit(main())
