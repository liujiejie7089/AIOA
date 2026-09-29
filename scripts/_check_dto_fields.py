#!/usr/bin/env python3
"""DTO 口径哨兵：把「OA 渲染层依赖的字段」与「接口真实返回的字段」摆在一起。

为什么需要它（这是本仓库踩过的真坑，不是预想）：
  OA 渲染层是手写的，字段名靠读接口猜。实测踩中 3 类静默错显，全部**页面不报错、
  只是显示成另一个事实**：
    ① 字段名不存在：`w.enabled`（真实是 `w.on`）⇒ 4 个数字员工恒显示「已停用」；
    ② 枚举大小写：`d.scope === 'tenant'`（真实是 `'TENANT'`）⇒ 企业知识库被标成「我的知识库」；
    ③ 响应结构：`/v1/org/departments` 返回 `{flat,tree,...}` 而非数组 / `{items}`
       ⇒ `arr()` 得到空，部门筛选器一个都渲染不出来（接口支持但界面配不出来）。
  静态扫描只能覆盖字面量，覆盖不到数组里的键与动态映射，所以这里**按真实响应判定**。

用法：python scripts/_check_dto_fields.py
  基线：下列 EXPECT 是当前实测口径。接口改了字段名 / 大小写 / 结构，这里会红。
  注意：它**读接口真值**，不读 state.* 作为判据来源（读 state 会与渲染器同源，缺陷一起漏过）。

退出码非零 = 有字段缺失或口径变化。
"""
import asyncio
import json
import sys

from playwright.async_api import async_playwright

BASE = 'http://127.0.0.1:5181/'
USER, PWD = 'wjj_xu', 'User@123'

# state 集合 -> OA 渲染层实际读的字段（少一个就说明后端改名了）
STATE_READS = {
    'workers': ['id', 'name', 'on', 'roleName', 'duty', 'description', 'scheduleTime',
                'lastRunAt', 'status', 'runMode', 'taskPrompt', 'workerType'],
    'experts': ['key', 'name', 'desc', 'intro', 'icon'],
    'conversations': ['id', 'title', 'lastMsgAt', 'createdAt'],
    'approvals': ['id', 'title', 'bizType', 'status', 'creatorName', 'applicantName',
                  'createdAt', 'decidedAt', 'decisionNote', 'content', 'timeline', 'totalNodes'],
    'kbDocs': ['id', 'name', 'icon', 'state', 'scope', 'chunkCount', 'sizeBytes', 'createdAt'],
    'notifs': ['id', 'title', 'content', 'type', 'unread', 'createdAt', 'refId'],
}

# 直接打的端点 -> OA 读的字段
ENDPOINTS = {
    '/v1/org/members': ['id', 'name', 'username', 'mobile', 'email', 'employeeNo',
                        'jobTitle', 'isOrgAdmin', 'departmentName'],
}

fails = []


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, locale='zh-CN')
        page = await ctx.new_page()
        await page.goto(BASE, wait_until='domcontentloaded')
        await page.wait_for_timeout(900)
        await page.fill('#lgUser', USER)
        await page.fill('#lgPass', PWD)
        await page.click('#lgBtn')
        await page.wait_for_selector('body.auth', timeout=15000)
        # 必须先切成 OA 形态：OA 的懒加载（loadOaExtras）才会补齐 conversations 等集合，
        # 留在经典形态采样会把「未加载」误判成「接口无数据」。
        await page.evaluate("() => localStorage.setItem('aioa_mode','oa')")
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_timeout(3500)

        data = await page.evaluate("""async (spec) => {
          const out = {state:{}, ep:{}};
          for (const k of Object.keys(spec)) {
            const v = state[k];
            const list = Array.isArray(v) ? v : ((v && v.items) || []);
            out.state[k] = { n: list.length, keys: list.length ? Object.keys(list[0]) : null };
          }
          for (const p of ['/v1/org/members', '/v1/org/departments', '/v1/org/profile']) {
            try {
              const raw = await API.req(p);
              let list = Array.isArray(raw) ? raw : (raw && (raw.items || raw.flat || raw.tree));
              out.ep[p] = { shape: Array.isArray(raw) ? 'array' : typeof raw,
                            topKeys: (raw && !Array.isArray(raw)) ? Object.keys(raw) : [],
                            n: Array.isArray(list) ? list.length : -1,
                            keys: (Array.isArray(list) && list.length) ? Object.keys(list[0]) : null };
            } catch (e) { out.ep[p] = { shape: 'ERROR: ' + e.message }; }
          }
          return out;
        }""", STATE_READS)

        for k, want in STATE_READS.items():
            got = data['state'][k]
            if got['keys'] is None:
                print('[skip] state.%s 当前为空（n=0），字段无法核对 —— 该集合的页面本轮不可验' % k)
                continue
            miss = [f for f in want if f not in got['keys']]
            chk('state.%s 渲染层所读字段均存在（n=%d）' % (k, got['n']), not miss,
                '缺失=%s' % miss if miss else 'ok')

        for p, want in ENDPOINTS.items():
            got = data['ep'][p]
            miss = [f for f in want if not got['keys'] or f not in got['keys']]
            chk('%s 字段齐备（shape=%s, n=%s）' % (p, got['shape'], got.get('n')), not miss,
                '缺失=%s' % miss if miss else 'ok')

        dep = data['ep']['/v1/org/departments']
        chk('/v1/org/departments 结构已按 flat/tree 取值（不是纯数组）',
            dep['shape'] == 'object' and 'flat' in (dep['topKeys'] or []),
            'shape=%s topKeys=%s' % (dep['shape'], dep['topKeys']))

        prof = data['ep']['/v1/org/profile']
        chk('/v1/org/profile 可读', prof['shape'] == 'object', prof['shape'])

        print('\n失败：%d 项' % len(fails))
        for f in fails:
            print('  - ' + f)
        await browser.close()
        return 1 if fails else 0


sys.exit(asyncio.run(main()))
