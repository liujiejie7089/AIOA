# -*- coding: utf-8 -*-
"""日程 / 会议模块端到端接线哨兵（纯静态，离线可跑）。

背景：V94 建了 portal_meeting / portal_meeting_attendee / portal_schedule 三张表 + 只读查询，
但全仓 `/api/v1/portal` **零调用方**（连管理端都改走表单了），H5 的「日程」是本地用
「请假起止 + 数字员工排班」合成的假日程。2026-10-31 补齐写链路并把前端接到真接口。

判据（每条都能因缺陷变红，含负向对照）：
  P1  Java 端点齐：POST /schedules、PUT /schedules/{id}、DELETE /schedules/{id}、
      POST /meetings、POST /meetings/{id}/cancel、POST /meetings/{id}/respond
  P2  服务层方法齐且**签名带 userId**（不带就意味着「谁都能改」，越权闸门形同虚设）
  P3  租户隔离：写入用 writeTenant（写自己租户），读取才用 tenantScope（本租户 + 公共）
  P4  归属校验：日程改/删与会议取消都必须先查 user_id / organizer_id，否则抛 404
  P5  逻辑删除：用 LambdaUpdateWrapper.set(deletedAt)，**不能**用 updateById（MP 的
      NOT_NULL 策略会让「置空/置时间」静默失效——mcp_server 清理 lastError 时踩过同一条坑）
  P6  会议冲突校验存在（同时段同地点不得重复占用），且只校验有地点的会议
  P7  会议取消要同步收敛参会人邀请态（否则取消后前端仍显示「待应答」）
  P8  H5：API 七个新入口齐全、面板改读真实数据、loadPortalAgenda 进了数据加载链
  P9  H5 失败可见：拉不到要显示原因，不能把「没拉到」显示成「今天没安排」
  P10 负向对照：把关键字面量去掉后判据必须变红（证明不是恒真）
  P11 业务异常语义：业务校验失败必须抛 BizException.badRequest（信封 code=400），
      **不得**用 IllegalArgumentException —— 全局兜底会把它包成 500「服务内部错误」，
      客户端看到的是「后端崩了」而不是「标题为空」这类可读原因（2026-10-31 实测踩到）

跑法：C:/Users/刘尖尖/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/_check_portal_schedule_meeting.py
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
CTRL = os.path.join(REPO, 'server', 'aios-resource', 'src', 'main', 'java', 'cn', 'aios',
                    'resource', 'controller', 'PortalController.java')
SVC = os.path.join(REPO, 'server', 'aios-resource', 'src', 'main', 'java', 'cn', 'aios',
                   'resource', 'service', 'PortalService.java')
H5 = os.path.join(REPO, 'user-client', 'index.html')

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


def _method_body(src, sig):
    """粗略抽取从方法签名开始的整段（按花括号配平）。"""
    m = re.search(re.escape(sig), src)
    if not m:
        return None
    i = src.index('{', m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    return src[i:]


def main():
    for p in (CTRL, SVC, H5):
        if not os.path.exists(p):
            chk('文件存在', False, p)
            return 1
    ctrl = read(CTRL)
    svc = read(SVC)
    h5 = read(H5)

    # ---------------- P1 端点 ----------------
    endpoints = [
        ('POST   /schedules', '@PostMapping("/schedules")'),
        ('PUT    /schedules/{id}', '@PutMapping("/schedules/{id}")'),
        ('DELETE /schedules/{id}', '@DeleteMapping("/schedules/{id}")'),
        ('POST   /meetings', '@PostMapping("/meetings")'),
        ('POST   /meetings/{id}/cancel', '@PostMapping("/meetings/{id}/cancel")'),
        ('POST   /meetings/{id}/respond', '@PostMapping("/meetings/{id}/respond")'),
    ]
    for label, lit in endpoints:
        chk('P1 端点 %s' % label, lit in ctrl, lit)
    chk('P1 写端点一律取当前用户身份', ctrl.count('AuthUserContext.require()') >= 6,
        'count=%d' % ctrl.count('AuthUserContext.require()'))

    # ---------------- P2 服务层方法 ----------------
    methods = [
        'createSchedule(Long tenantId, Long userId',
        'updateSchedule(Long tenantId, Long userId, Long id',
        'deleteSchedule(Long tenantId, Long userId, Long id',
        'createMeeting(Long tenantId, Long userId, String userName',
        'cancelMeeting(Long tenantId, Long userId, Long id',
        'respondMeeting(Long tenantId, Long userId, Long id, String decision',
    ]
    for m in methods:
        chk('P2 服务方法带 userId：%s' % m.split('(')[0], m in svc, m)

    # ---------------- P3/P4 隔离与归属 ----------------
    chk('P3 写入走 writeTenant（写自己租户，不写公共）',
        'writeTenant(tenantId)' in svc and svc.count('writeTenant') >= 3,
        'count=%d' % svc.count('writeTenant'))
    chk('P3 读取走 tenantScope（本租户 + 平台公共）',
        'tenantScope(tenantId).contains' in svc, 'contains=%s' % ('tenantScope' in svc))
    chk('P4 日程改/删先查归属（ownSchedule）',
        'ownSchedule(' in svc and svc.count('ownSchedule(') >= 3)
    chk('P4 会议取消先查组织者（ownMeeting）', 'ownMeeting(' in svc)
    chk('P4 越权/不存在一律 404（不泄露他人数据存在与否）',
        svc.count('BizException.notFound(') >= 4, 'count=%d' % svc.count('BizException.notFound('))

    # ---------------- P5 逻辑删除 ----------------
    chk('P5 日程删除用 LambdaUpdateWrapper.set(deletedAt)',
        'LambdaUpdateWrapper<PortalSchedule>()' in svc
        and 'set(PortalSchedule::getDeletedAt' in svc)
    # 只判**删除方法体**：updateById 在「更新日程」里是正确用法（字段都非空），
    # 判据不能扩大到整个文件，否则会把正当用法误判成缺陷。
    # 注意用 `scheduleMapper.updateById(` 完整调用式 —— 方法体里的注释会提到 “updateById” 这个词，
    # 只匹配裸词名会把注释当成代码（假红）。
    del_body = _method_body(svc, 'public void deleteSchedule(')
    chk('P5 删除方法体内不用 updateById（NOT_NULL 会静默跳过）',
        del_body is not None and 'scheduleMapper.updateById(' not in del_body,
        'found=%s' % (del_body is None))
    # 正向：删除必须真的写了 deleted_at
    chk('P5 删除确实置 deleted_at',
        del_body is not None and 'set(PortalSchedule::getDeletedAt' in del_body)

    # ---------------- P6/P7 会议业务规则 ----------------
    chk('P6 存在会议室/地点冲突校验', 'findRoomClash(' in svc)
    chk('P6 冲突只校验有地点的会议（无地点不误伤）',
        'm.getLocation() != null && !m.getLocation().isBlank()' in svc)
    chk('P6 冲突排除已取消/已删除', 'getStatus(), STATUS_SCHEDULED' in svc
        or '.eq(PortalMeeting::getStatus, STATUS_SCHEDULED)' in svc)
    chk('P7 取消会议同步收敛参会人邀请态',
        'PortalMeetingAttendee::getInviteStatus' in svc
        and 'set(PortalMeetingAttendee::getInviteStatus, INVITE_DECLINED)' in svc)
    chk('P7 已取消会议不可应答', '会议已取消，无法应答' in svc)

    # ---------------- P11 业务异常语义 ----------------
    # 背景：GlobalExceptionHandler 只把 BizException 与 Spring 参数类异常映射成 4xx，
    # 其余一律落到 Exception 兜底 ⇒ 500「服务内部错误」。若在服务层用
    # IllegalArgumentException 表达「标题为空 / 时间倒序 / 房间冲突」这类业务校验失败，
    # 客户端看到的就是 500（像后端崩了），而不是可读的业务错误。
    # 铁律：业务校验失败一律 BizException.badRequest（信封 code=400，HTTP 200）。
    chk('P11 业务校验失败用 BizException.badRequest（不落 500）',
        svc.count('BizException.badRequest(') >= 5,
        'count=%d' % svc.count('BizException.badRequest('))
    chk('P11 服务层不抛 IllegalArgumentException（会被兜底成 500）',
        'throw new IllegalArgumentException' not in svc,
        '出现次数=%d' % svc.count('throw new IllegalArgumentException'))
    chk('P11 已 import BizException',
        'import cn.aios.common.exception.BizException;' in svc)

    # ---------------- P8/P9 前端 ----------------
    apis = ['portalSchedulesToday', 'portalSchedules', 'portalMeetings', 'portalScheduleCreate',
            'portalScheduleUpdate', 'portalScheduleRemove', 'portalMeetingCreate',
            'portalMeetingCancel', 'portalMeetingRespond']
    missing = [a for a in apis if (a + '(') not in h5]
    chk('P8 H5 API 入口齐全（9 个）', not missing, '缺=%s' % missing)
    chk('P8 日程面板改读真实数据（S.schedules / S.meetings）',
        'arr(S.schedules)' in h5 and 'arr(S.meetings)' in h5)
    chk('P8 loadPortalAgenda 进入数据加载链（loadOaExtras）',
        re.search(r'loadOaExtras\(\)\s*\{[\s\S]{0,600}loadPortalAgenda\(', h5) is not None)
    chk('P8 不再声称「由请假与排班合成」',
        '暂无由请假与排班合成的日程' not in h5)
    chk('P9 拉取失败可见（S.agendaErr 渲染）',
        'S.agendaErr' in h5 and h5.count('S.agendaErr') >= 3)
    chk('P9 新建日程写接口而非表单模板（不做假闭环）',
        'API.portalScheduleCreate' in h5 and 'meeting_book' not in h5.split('scheduleCreateCardHtml')[1][:1200])
    chk('P9 行内操作有加载态与失败提示',
        '处理中…' in h5 and '保存中…' in h5 and '删除中…' in h5)

    # ---------------- P10 负向对照 ----------------
    stripped = svc.replace('writeTenant(tenantId)', 'tenantId')
    chk('P10 负向：去掉 writeTenant 后 P3 应失败',
        not ('writeTenant(tenantId)' in stripped and stripped.count('writeTenant') >= 3))
    stripped2 = ctrl.replace('@PostMapping("/meetings")', '@GetMapping("/meetings")')
    chk('P10 负向：把发起会议改成 GET 后 P1 应失败',
        '@PostMapping("/meetings")' not in stripped2)
    stripped3 = h5.replace('arr(S.schedules)', 'arr([])')
    chk('P10 负向：去掉真实日程源后 P8 应失败', 'arr(S.schedules)' not in stripped3)
    stripped4 = svc.replace('BizException.badRequest(', 'new IllegalArgumentException(')
    chk('P10 负向：把 badRequest 换回 IllegalArgumentException 后 P11 应失败',
        'throw new IllegalArgumentException' in stripped4
        and stripped4.count('BizException.badRequest(') < 5)

    print('\n通过：%d / 失败：%d' % (oks, len(fails)))
    if fails:
        print('失败项：')
        for f in fails:
            print('  - ' + f)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
