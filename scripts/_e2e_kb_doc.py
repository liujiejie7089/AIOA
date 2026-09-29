#!/usr/bin/env python3
"""知识库「点开查看 / 删除」两形态端到端验证（用户端 H5 :5181 + 后端 :8080）。

为什么单独一个套件
    「上传的资料能点开看、能删掉」是一条跨层能力：后端要有**读单份正文**的入口、
    前端要能点开、删除要有二次确认。只验其中一层都会漏（接口能读 ≠ 界面上点得开）。

覆盖
    A 接口层（纯 HTTP，独立于界面）：404 / 403 / 正文逐字一致 / 越权 / 删除后读回
    B 新版形态 UI：列表行可点开、正文可见、本人资料可删（二次确认）、删后列表与接口都不再有
    C 经典形态 UI：「查看」入口可用并展示正文、删除保持原行为
    D 显示口径：他人上传但自己看得见的共享资料，**不**显示删除入口（只有本人上传才给）
    E 一致性：账号可见列表里的**每一份**都能点开（避免「列表看得到、点开 403」）

判定纪律
    凡「删掉了没有」一律**独立读回接口**判定，不读前端内存（前端内存说没删不算数）。

用法：python scripts/_e2e_kb_doc.py
"""
import asyncio
import sys
import time

import httpx
from playwright.async_api import async_playwright

H5 = 'http://127.0.0.1:5181/'
API = 'http://127.0.0.1:8080/api/v1'
PWD = 'User@123'

USER = 'wjj_xu'          # 租户 3 普通成员：新版/经典的主测账号
OTHER = 'wjj_admin'      # 租户 3 管理员：用来造一份「他人上传、但我看得见」的共享资料
CROSS = 'dsj_admin'      # 租户 2 管理员：用来验跨租户 403，并提供一批存量资料

fails = []
MARK = 'KBDOC-%d' % int(time.time())


def chk(name, ok, detail=''):
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name,
                         (' — ' + str(detail)) if detail else ''))
    if not ok:
        fails.append(name)


class Api:
    """独立 HTTP 客户端：套件里的「事实源」，与浏览器内存分账。"""

    def __init__(self):
        self.c = httpx.Client(timeout=30, trust_env=False)

    def login(self, username):
        d = self.c.post(API + '/auth/login', json={'username': username, 'password': PWD}).json()
        if d.get('code') != 0:
            raise RuntimeError('登录失败 %s: %s' % (username, d))
        tok = d['data']['accessToken']
        return {'Authorization': 'Bearer ' + tok}, (d['data'].get('user') or {})

    def get(self, path, h=None):
        r = self.c.get(API + path, headers=h or {})
        return r.status_code, self._body(r)

    def delete(self, path, h):
        r = self.c.delete(API + path, headers=h)
        return r.status_code, self._body(r)

    def upload(self, name, text, scope='PERSONAL', h=None):
        r = self.c.post(API + '/kb/documents/upload',
                        params={'scope': scope},
                        files={'file': (name, text.encode('utf-8'), 'text/plain')},
                        headers=h or {})
        return r.status_code, self._body(r)

    @staticmethod
    def _body(r):
        try:
            return r.json()
        except Exception:
            return {'raw': r.text[:200]}


def body_text(api, tok_h, doc_id):
    code, d = api.get('/kb/documents/%s' % doc_id, tok_h)
    if code != 200 or d.get('code') != 0:
        return code, None
    return code, d.get('data') or {}


async def main():
    api = Api()
    h_user, me_user = api.login(USER)
    h_other, me_other = api.login(OTHER)
    h_cross, me_cross = api.login(CROSS)
    print('账号：%s(tenant=%s uid=%s) / %s(uid=%s) / %s(tenant=%s)'
          % (USER, me_user.get('tenantId'), me_user.get('id'),
             OTHER, me_other.get('id'), CROSS, me_cross.get('tenantId')))

    text_a = '第一行 %s A\n第二行 换行必须原样保留\n第三行 end' % MARK
    text_c = '第一行 %s C\n第二行 经典形态查看\n第三行 end' % MARK
    text_share = '共享资料 %s\n由他人上传，我可见但不可删' % MARK
    ids = {}

    # ================= A. 接口层 =================
    print('\n--- A. 接口层（纯 HTTP） ---')
    # 注意：这一项必须带 token —— 漏传 Authorization 会拿到 401，
    # 于是「未登录」被当成「不存在」的失败，报出一个根本不存在的缺陷。
    code, _ = api.get('/kb/documents/999999999', h_user)
    chk('A1 已登录读不存在的资料 → 404', code == 404, code)
    code, _ = api.get('/kb/documents/1')
    chk('A2 未登录读详情 → 401', code == 401, code)

    # 跨租户：拿 dsj_admin（租户 2）可见的第一份，用 wjj_xu（租户 3）去读
    _, d = api.get('/kb/documents', h_cross)
    cross_docs = (d.get('data') or [])
    chk('A3 前置：跨租户账号有可见资料（否则本项无从验）', len(cross_docs) > 0, len(cross_docs))
    if cross_docs:
        cid = cross_docs[0]['id']
        code, d = api.get('/kb/documents/%s' % cid, h_user)
        chk('A4 跨租户读详情 → 403（不是 404，存在性不外泄给别的租户）', code == 403, code)
        code, _ = api.delete('/kb/documents/%s' % cid, h_user)
        chk('A5 跨租户删资料 → 403', code == 403, code)

    code, d = api.upload(MARK + '-A.txt', text_a, 'PERSONAL', h_user)
    ok_up = code == 200 and d.get('code') == 0
    chk('A6 上传 txt 成功且入库', ok_up, d if not ok_up else 'id=%s state=%s'
        % ((d.get('data') or {}).get('id'), (d.get('data') or {}).get('state')))
    ids['a'] = (d.get('data') or {}).get('id')
    code, det = body_text(api, h_user, ids['a'])
    chk('A7 详情可读（200/code=0）', code == 200 and det is not None, code)
    chk('A8 正文与上传内容逐字一致（含换行）', (det or {}).get('content') == text_a,
        repr(((det or {}).get('content') or '')[:60]))
    chk('A9 contentLength = 完整正文长度、truncated=false',
        (det or {}).get('contentLength') == len(text_a) and (det or {}).get('truncated') is False,
        '%s / %s' % ((det or {}).get('contentLength'), (det or {}).get('truncated')))

    # 一致性：该账号可见列表里的每一份都要能点开
    _, d = api.get('/kb/documents', h_user)
    mine = d.get('data') or []
    bad = []
    for m in mine:
        c2, det2 = api.get('/kb/documents/%s' % m['id'], h_user)
        if c2 != 200:
            bad.append((m['id'], c2))
    chk('A10 可见列表里每一份都能点开（0 个非 200）', not bad, bad or '%d 份全通过' % len(mine))

    code, d = api.upload(MARK + '-C.txt', text_c, 'PERSONAL', h_user)
    ids['c'] = (d.get('data') or {}).get('id')
    chk('A11 前置：经典形态用例的资料已就绪', code == 200 and ids['c'], ids['c'])
    code, d = api.upload(MARK + '-SHARE.txt', text_share, 'TENANT', h_other)
    ids['share'] = (d.get('data') or {}).get('id')
    chk('A12 前置：他人上传的租户共享资料已就绪', code == 200 and ids['share'], ids['share'])

    # ================= 浏览器 =================
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel='msedge', headless=True)
        ctx = await browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2)
        page = await ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))

        async def boot(mode):
            await page.goto(H5, wait_until='domcontentloaded')
            await page.evaluate("m => localStorage.setItem('aioa_mode', m)", mode)
            await page.reload(wait_until='domcontentloaded')
            await page.wait_for_timeout(800)
            if not await page.query_selector('body.auth'):
                await page.fill('#lgUser', USER)
                await page.fill('#lgPass', PWD)
                await page.click('#lgBtn')
                await page.wait_for_selector('body.auth', timeout=15000)
            await page.wait_for_timeout(2500)

        # ================= B. 新版形态 =================
        print('\n--- B. 新版形态 UI ---')
        await boot('oa')
        om = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
        chk('B1 前置：已进入新版形态', om is True)
        await page.click('#oaTabs .tab[data-view="kb"]')
        await page.wait_for_timeout(1200)

        row = '#oaKbList .docrow[data-doc="%s"]' % ids['a']
        chk('B2 上传的资料出现在新版知识库列表', await page.query_selector(row) is not None,
            await page.eval_on_selector('#oaKbList', 'el=>el.innerText.slice(0,90)')
            if await page.query_selector('#oaKbList') else 'no list')
        role = await page.get_attribute(row, 'role') if await page.query_selector(row) else None
        tabidx = await page.get_attribute(row, 'tabindex') if await page.query_selector(row) else None
        chk('B3 行是「可点开」的语义（role=button + tabindex）',
            role == 'button' and tabidx == '0', '%s/%s' % (role, tabidx))

        # 状态口径（顺带修掉的真缺陷）：徽标要中文，概览磁贴要与列表同源
        # 注意：磁贴的标签与数字是 flex 同行（innerText = '已就绪3'），
        # **不能**按换行切首行取标签（会永远取不到，得到 None 的假失败）。
        # 标签/数字各自从 span/b 子元素读，与布局无关。
        kb = await page.evaluate("""() => {
          const tiles = [...document.querySelectorAll('#oaKbGrid .kb-tile')].map(t => {
            const s = t.querySelector('span'), b = t.querySelector('b');
            return [s ? s.innerText.trim() : null, b ? b.innerText.trim() : null];
          });
          const chips = [...document.querySelectorAll('#oaKbList .docrow .chip')].map(c => c.innerText.trim());
          return {tiles, chips, rows: document.querySelectorAll('#oaKbList .docrow').length};
        }""")
        chk('B4 列表状态徽标是中文（不再显示后端原文 ok）',
            bool(kb['chips']) and all(c in ('已就绪', '失败', '处理中') for c in kb['chips']), kb['chips'])
        tiles = dict(kb['tiles'])
        # 前置：概览「我的文档」总数 = 列表实际渲染行数。
        # 列表只渲染前 30 行（docs.slice(0,30)），一旦被截断，「磁贴 vs 可见行」就不再可比，
        # 此时必须先报前置失败，而不是给出一个误导性的「同源不成立」。
        total_tile, rows = tiles.get('我的文档'), kb['rows']
        chk('B5a 前置：概览总数 = 列表渲染行数（列表未被 30 行截断）',
            str(total_tile) == str(rows), 'tile=%s rows=%s' % (total_tile, rows))
        tile_ready = tiles.get('已就绪')
        real_ready = str(kb['chips'].count('已就绪'))
        chk('B5 概览「已就绪」与列表同源（同一处判定）',
            str(tile_ready) == real_ready, 'tile=%s list=%s' % (tile_ready, real_ready))

        await page.click(row)
        await page.wait_for_timeout(900)
        opened = await page.evaluate("() => document.querySelector('#oaRoot').classList.contains('doc-open')")
        title = await page.inner_text('#oaDocTitle') if opened else ''
        chk('B6 点开后详情覆盖层打开且标题=文件名',
            opened and title.strip() == MARK + '-A.txt', '%s / %s' % (opened, title))
        body = await page.inner_text('#oaDocBody') if opened else ''
        chk('B7 详情里能看到正文原文（含第二行）',
            '第二行 换行必须原样保留' in body and MARK in body, body[:80].replace('\n', '⏎'))
        chk('B8 正文块用的是共用渲染（.kb-doc-text 存在）',
            await page.query_selector('#oaDocBody .kb-doc-text') is not None)
        chk('B9 元信息里给了「共 N 字」', ('共 %d 字' % len(text_a)) in body, body[:120].replace('\n', '⏎'))
        delbtn = await page.query_selector('#oaDocDel')
        delvis = await page.is_visible('#oaDocDel') if delbtn else False
        chk('B10 本人上传的资料显示「删除资料」', delvis)

        if delvis:
            await page.click('#oaDocDel')
            await page.wait_for_selector('.notif-mask.show [data-dlg-ok]', timeout=5000)
            dlg = await page.inner_text('.notif-modal')
            chk('B11 删除有二次确认（文案=删除资料）', '删除资料' in dlg, dlg.replace('\n', ' ')[:70])
            await page.click('.notif-mask.show [data-dlg-ok]')
            await page.wait_for_timeout(1500)
        closed = await page.evaluate("() => !document.querySelector('#oaRoot').classList.contains('doc-open')")
        chk('B12 删完覆盖层关闭', closed)
        still = await page.query_selector(row)
        chk('B13 列表里该资料已消失', still is None)
        code, _ = api.get('/kb/documents/%s' % ids['a'], h_user)
        chk('B14 独立读回：接口已 404（不看前端内存）', code == 404, code)

        # 显示口径：他人上传、我可见的共享资料不给删除入口
        await page.wait_for_timeout(600)
        share_row = '#oaKbList .docrow[data-doc="%s"]' % ids['share']
        if await page.query_selector(share_row):
            await page.click(share_row)
            await page.wait_for_timeout(900)
            chk('B15 共享资料不显示删除入口（只有本人上传才给）',
                not await page.is_visible('#oaDocDel'))
            chk('B16 但共享资料能点开查看',
                (await page.inner_text('#oaDocTitle')).strip() == MARK + '-SHARE.txt')
            await page.click('#oaDocDone')
            await page.wait_for_timeout(600)
        else:
            chk('B15 共享资料不显示删除入口（只有本人上传才给）', False, '共享资料未出现在列表')

        # ================= C. 经典形态 =================
        print('\n--- C. 经典形态 UI ---')
        await boot('classic')
        om2 = await page.evaluate("() => document.querySelector('.phone').classList.contains('oa-mode')")
        chk('C1 前置：已切回经典形态', om2 is False)
        await page.evaluate("() => go('page-me')")
        await page.wait_for_timeout(1200)
        vbtn = '#kbList button[onclick="openKbDoc(%s)"]' % ids['c']
        chk('C2 经典列表出现「查看」按钮', await page.query_selector(vbtn) is not None,
            await page.eval_on_selector('#kbList', 'el=>el.innerText.slice(0,90)')
            if await page.query_selector('#kbList') else 'no list')
        await page.click(vbtn)
        await page.wait_for_timeout(1200)
        cbody = await page.inner_text('.notif-modal') if await page.query_selector('.notif-modal') else ''
        chk('C3 点「查看」弹出详情且含正文原文',
            '第二行 经典形态查看' in cbody, cbody[:80].replace('\n', ' '))
        await page.click('.notif-modal .notif-close')
        await page.wait_for_timeout(400)
        await page.click('#kbList button[onclick="delKb(%s,this)"]' % ids['c'])
        await page.wait_for_selector('.notif-mask.show [data-dlg-ok]', timeout=5000)
        await page.click('.notif-mask.show [data-dlg-ok]')
        await page.wait_for_timeout(1500)
        chk('C4 经典删除后列表里不再有该资料',
            await page.query_selector('#kbList button[onclick="openKbDoc(%s)"]' % ids['c']) is None)
        code, _ = api.get('/kb/documents/%s' % ids['c'], h_user)
        chk('C5 独立读回：接口已 404', code == 404, code)

        chk('E1 console 无未捕获异常', not errs, errs[:2])
        await browser.close()

    # 清理：他人上传的共享资料由上传者本人删（不留垃圾）
    if ids.get('share'):
        code, d = api.delete('/kb/documents/%s' % ids['share'], h_other)
        chk('清理：共享资料已由上传者删除', code == 200, code)

    print('\n失败：%d 项' % len(fails))
    for f in fails:
        print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
