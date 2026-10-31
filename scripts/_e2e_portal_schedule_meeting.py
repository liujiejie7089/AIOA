# -*- coding: utf-8 -*-
"""日程 / 会议模块端到端（**需真实服务**：:8080 + MySQL）。

覆盖：主流程 + 异常 + 边界分支（用例清单见下方 T1–T16）。
跑法（先确保后端与库已起）：
    C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_e2e_portal_schedule_meeting.py

★ 断言口径（本项目约定，勿按 HTTP 状态码断言业务失败）：
    `GlobalExceptionHandler` 只把 BizException 的 401/403/404 映射成对应 HTTP 状态，
    **其余业务错误一律 HTTP 200 + 信封 code=400**（docs/36 § / docs/38 § 均明确记载）。
    所以「标题为空 ⇒ 400」的正确判据是 `body.code == 400`，不是 `http_status == 400`。
    （2026-10-31 首版按 HTTP 状态码断言 ⇒ 6 条假红，已按信封口径修正。）

★ 参会人用真实用户：
    组织者 zhangsan（uid=2，tenant=0）邀请同租户真实用户 admin（uid=1）；
    早期版本写死 attendeeIds=[2,3] 恰好把组织者本人也算进去，invited 期望值对不上
    —— 现在从登录返回里取真实 uid，期望值按「真实受邀人集合」动态算。

用例清单
--------
 T1  登录（zhangsan / User@123）拿 token，并取到自己的真实 uid
 T2  创建日程（标题 + 起止 + 地点）⇒ 返回 id
 T3  边界：标题为空 ⇒ 业务拒绝（信封 code=400，不是 500）
 T4  边界：结束早于开始 ⇒ 业务拒绝（code=400）
 T5  边界：时间格式非法 ⇒ 业务拒绝（code=400）
 T6  更新自己的日程（改标题 + 时间）⇒ 生效且能读回新值
 T7  删除自己的日程 ⇒ 逻辑删（DB 行仍在、deleted_at 非空、列表里消失）
 T8  重复删除 ⇒ 404（已删不再可见，不泄露存在性）
 T9  边界：删一个他人/不存在的日程 ⇒ 404
 T10 发起会议（真实受邀人 1 人）⇒ 返回 id + invited 与真实受邀人数一致
 T11 边界：同地点同时段再发起 ⇒ 业务拒绝（code=400）且消息含冲突原因
 T12 边界：无地点的会议同时段 ⇒ 允许（不误伤线上会议）
 T13 受邀人应答 ACCEPTED ⇒ DB 邀请表状态真的变成 ACCEPTED（回库核对，不信接口回显）
 T14 边界：非法应答值 ⇒ 业务拒绝（code=400）
 T15 边界：非受邀人应答 ⇒ 404（不泄露参会名单）
 T16 组织者取消会议 ⇒ 状态 CANCELED，且未应答的参会人邀请态收敛为 DECLINED（回库核对）

判据原则：每条断言回到**接口返回值或 DB 行**，不信任何界面文案；
越权用例必须断言「信息不泄露」（404 而不是 403/200+空）。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ.get('AIOS_BASE', 'http://127.0.0.1:8080/api')
USER = os.environ.get('AIOS_USER', 'zhangsan')
PWD = os.environ.get('AIOS_PWD', 'User@123')
# 第二个真实账号（受邀人 / 越权断言的另一侧）：admin 是同租户真实用户，口令 Admin@123。
GUEST_USER = os.environ.get('AIOS_GUEST_USER', 'admin')
GUEST_PWD = os.environ.get('AIOS_GUEST_PWD', 'Admin@123')

DB = dict(host=os.environ.get('AIOS_DB_HOST', '127.0.0.1'),
          port=int(os.environ.get('AIOS_DB_PORT', '3306')),
          user=os.environ.get('AIOS_DB_USER', 'root'),
          password=os.environ.get('AIOS_DB_PASSWORD', ''),
          database=os.environ.get('AIOS_DB_NAME', 'aios'),
          charset='utf8mb4')

fails = []
oks = 0
db_ok = True


def chk(name, ok, detail=''):
    global oks
    print('[%s] %s%s' % ('OK  ' if ok else 'FAIL', name, (' — ' + str(detail)) if detail else ''))
    if ok:
        oks += 1
    else:
        fails.append(name)
    return ok


def call(method, path, token=None, body=None):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    if token:
        req.add_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = json.loads(r.read().decode('utf-8'))
            return r.status, payload
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'ignore')
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {'message': raw}
        payload.setdefault('status', e.code)
        return e.code, payload
    except Exception as e:
        return -1, {'message': str(e)[:200]}


def data_of(payload):
    return (payload or {}).get('data', payload)


def biz_code(payload):
    """取业务信封 code（成功=0，失败=400/404/…）。"""
    return (payload or {}).get('code')


def row0(rows):
    """取查询结果首行并安全转字符串。

    注意：'%s' % (tuple,) 会把 tuple 解包成多个参数 ⇒ "not all arguments converted"；
    行本身是 tuple，直接格式化会踩这个坑，这里统一收口。
    """
    if not rows:
        return 'None'
    return str(rows[0])


def db_query(sql, args=None):
    """回库核对。取不到库就返回 None（此时相关断言降级为「不可判」而不是假装通过）。"""
    global db_ok
    try:
        import pymysql
    except ImportError:
        db_ok = False
        return None
    try:
        c = pymysql.connect(**DB)
        try:
            cur = c.cursor()
            cur.execute(sql, args or ())
            return cur.fetchall()
        finally:
            c.close()
    except Exception as e:
        print('  [db] 查询失败：%s' % str(e)[:160])
        db_ok = False
        return None


def login(username, password):
    st, r = call('POST', '/v1/auth/login', body={'username': username, 'password': password})
    d = data_of(r) or {}
    tok = d.get('token') or d.get('accessToken')
    uid = (d.get('user') or {}).get('id')
    return st, tok, uid, r


def main():
    ts = lambda off: (datetime.now() + timedelta(days=3, minutes=off)).strftime('%Y-%m-%d %H:%M:%S')

    # ── T1 登录 ──
    st, tok, uid, r = login(USER, PWD)
    chk('T1 登录取到 token 与真实 uid', bool(tok) and bool(uid),
        'status=%s uid=%s' % (st, uid))
    if not tok:
        return report()

    # 受邀人：另一个真实账号，取不到就退化为「只测组织者侧」（并在报告里说明）
    gst, gtok, guid, _ = login(GUEST_USER, GUEST_PWD)
    chk('T1 第二个真实账号（受邀人）登录成功', bool(gtok) and bool(guid),
        'user=%s status=%s uid=%s' % (GUEST_USER, gst, guid))

    # ── T2 创建日程 ──
    st, r = call('POST', '/v1/portal/schedules', tok,
                 {'title': 'E2E 日程-' + datetime.now().strftime('%H%M%S'),
                  'startAt': ts(0), 'endAt': ts(60), 'location': '3 号会议室'})
    sid = (data_of(r) or {}).get('id')
    chk('T2 创建日程返回 id', biz_code(r) == 0 and bool(sid),
        'code=%s body=%s' % (biz_code(r), r))

    st, r = call('GET', '/v1/portal/schedules/today', tok)
    today = data_of(r) or {}
    chk('T2 今日日程接口可用（返回分页信封）', biz_code(r) == 0 and 'list' in today,
        'code=%s keys=%s' % (biz_code(r), list(today)[:6] if isinstance(today, dict) else type(today)))

    # ── T3/T4/T5 业务校验失败（信封 code=400，不是 500）──
    st, r = call('POST', '/v1/portal/schedules', tok, {'title': '', 'startAt': ts(0)})
    chk('T3 空标题 ⇒ 业务拒绝 code=400（不是 500）',
        biz_code(r) == 400 and st != 500, 'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))

    st, r = call('POST', '/v1/portal/schedules', tok,
                 {'title': '倒序时间', 'startAt': ts(60), 'endAt': ts(0)})
    chk('T4 结束早于开始 ⇒ 业务拒绝 code=400',
        biz_code(r) == 400 and st != 500, 'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))

    st, r = call('POST', '/v1/portal/schedules', tok, {'title': '坏时间', 'startAt': 'not-a-time'})
    chk('T5 时间格式非法 ⇒ 业务拒绝 code=400',
        biz_code(r) == 400 and st != 500, 'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))

    # ── T6 更新 ──
    if sid:
        st, r = call('PUT', '/v1/portal/schedules/%s' % sid, tok,
                     {'title': 'E2E 日程-已改', 'endAt': ts(120)})
        chk('T6 更新自己的日程 ⇒ 成功', biz_code(r) == 0, 'code=%s' % biz_code(r))
        rows = db_query("select title, end_at from portal_schedule where id=%s", (sid,))
        if rows is not None:
            chk('T6 更新已落库（回库核对标题/结束时间）',
                bool(rows) and rows[0][0] == 'E2E 日程-已改',
                'row=%s' % row0(rows))

    # ── T7/T8/T9 删除 ──
    if sid:
        st, r = call('DELETE', '/v1/portal/schedules/%s' % sid, tok)
        chk('T7 删除自己的日程 ⇒ 成功', biz_code(r) == 0, 'code=%s' % biz_code(r))
        rows = db_query("select deleted_at from portal_schedule where id=%s", (sid,))
        if rows is not None:
            chk('T7 是逻辑删（行仍在、deleted_at 非空）',
                bool(rows) and rows[0][0] is not None, 'deleted_at=%s' % row0(rows))
        st, r = call('DELETE', '/v1/portal/schedules/%s' % sid, tok)
        chk('T8 重复删除 ⇒ 404（已删不再可见，不泄露存在性）',
            st == 404 and biz_code(r) == 404, 'http=%s code=%s' % (st, biz_code(r)))

    st, r = call('DELETE', '/v1/portal/schedules/99999999', tok)
    chk('T9 删他人/不存在 ⇒ 404（不泄露是否存在）',
        st == 404 and biz_code(r) == 404, 'http=%s code=%s' % (st, biz_code(r)))

    # ── T10 发起会议（真实受邀人）──
    attendee_ids = [guid] if guid and guid != uid else []
    expected_invited = len(attendee_ids)
    st, r = call('POST', '/v1/portal/meetings', tok,
                 {'title': 'E2E 评审会', 'startAt': ts(0), 'endAt': ts(30),
                  'location': 'E2E 会议室 A', 'attendeeIds': attendee_ids})
    mid = (data_of(r) or {}).get('id')
    invited = (data_of(r) or {}).get('invited')
    chk('T10 发起会议返回 id + 邀请人数与真实受邀人一致',
        biz_code(r) == 0 and bool(mid) and invited == expected_invited,
        'code=%s invited=%s expected=%s attendeeIds=%s' % (biz_code(r), invited, expected_invited, attendee_ids))

    # ── T11 同地点同时段冲突 ──
    st, r = call('POST', '/v1/portal/meetings', tok,
                 {'title': 'E2E 撞车会', 'startAt': ts(10), 'endAt': ts(20),
                  'location': 'E2E 会议室 A', 'attendeeIds': []})
    msg = str((r or {}).get('message') or '')
    chk('T11 同地点同时段 ⇒ code=400 且给出冲突原因',
        biz_code(r) == 400 and '占用' in msg and st != 500,
        'http=%s code=%s msg=%s' % (st, biz_code(r), msg[:120]))

    # ── T12 无地点不误伤 ──
    st, r = call('POST', '/v1/portal/meetings', tok,
                 {'title': 'E2E 线上会', 'startAt': ts(10), 'endAt': ts(20), 'attendeeIds': []})
    chk('T12 无地点会议同时段不误伤 ⇒ 成功', biz_code(r) == 0, 'code=%s' % biz_code(r))

    # ── T13 受邀人应答（用受邀人自己的 token）──
    if mid and gtok:
        st, r = call('POST', '/v1/portal/meetings/%s/respond?decision=ACCEPTED' % mid, gtok)
        chk('T13 受邀人应答 ACCEPTED ⇒ 成功', biz_code(r) == 0,
            'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))
        rows = db_query("select invite_status from portal_meeting_attendee where meeting_id=%s and user_id=%s",
                        (mid, guid))
        if rows is not None:
            chk('T13 邀请表状态真的变成 ACCEPTED（回库核对）',
                bool(rows) and rows[0][0] == 'ACCEPTED',
                'row=%s' % row0(rows))
    else:
        chk('T13 受邀人应答（缺受邀人令牌，跳过）', False, '无第二个账号令牌')

    # ── T14 非法应答值 ──
    if mid:
        st, r = call('POST', '/v1/portal/meetings/%s/respond?decision=MAYBE' % mid,
                     gtok if gtok else tok)
        chk('T14 非法应答值 ⇒ code=400',
            biz_code(r) == 400 and st != 500,
            'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))

    # ── T15 非受邀人应答 ⇒ 404 ──
    if mid and gtok and guid:
        # 组织者本人不在参会人名单里（createMeeting 会跳过 organizer），故组织者应答 ⇒ 404
        st, r = call('POST', '/v1/portal/meetings/%s/respond?decision=ACCEPTED' % mid, tok)
        chk('T15 非受邀人（组织者本人）应答 ⇒ 404（不泄露参会名单）',
            st == 404 and biz_code(r) == 404, 'http=%s code=%s' % (st, biz_code(r)))

    # ── T16 取消会议 + 邀请态收敛 ──
    if mid:
        st, r = call('POST', '/v1/portal/meetings/%s/cancel' % mid, tok)
        chk('T16 组织者取消会议 ⇒ 成功', biz_code(r) == 0, 'code=%s' % biz_code(r))
        rows = db_query("select status from portal_meeting where id=%s", (mid,))
        if rows is not None:
            chk('T16 会议状态落 CANCELED（回库核对）',
                bool(rows) and rows[0][0] == 'CANCELED', 'row=%s' % row0(rows))
        rows = db_query("select invite_status from portal_meeting_attendee where meeting_id=%s", (mid,))
        if rows is not None:
            chk('T16 参会人邀请态收敛（无 INVITED 残留）',
                all(r[0] != 'INVITED' for r in rows), 'rows=%s' % rows)
        st, r = call('POST', '/v1/portal/meetings/%s/respond?decision=ACCEPTED' % mid,
                     gtok if gtok else tok)
        chk('T16 已取消的会议再应答 ⇒ 拒绝（code=400 或 404）',
            biz_code(r) in (400, 404) and st != 500,
            'http=%s code=%s msg=%s' % (st, biz_code(r), (r or {}).get('message')))

    if not db_ok:
        print('\n注意：数据库不可达 ⇒ 标「回库核对」的断言未执行（未计入失败，但也不代表通过）。')

    return report()


def report():
    print('\n通过：%d / 失败：%d' % (oks, len(fails)))
    if fails:
        print('失败项：')
        for f in fails:
            print('  - ' + f)
        print('\n提示：本脚本要求 :8080 与 MySQL 已启动；若全部用例都是网络错误，先起服务再跑。')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
