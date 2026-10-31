package cn.aios.resource.service;

import cn.aios.resource.entity.PortalAnnouncement;
import cn.aios.resource.entity.PortalMeeting;
import cn.aios.resource.entity.PortalMeetingAttendee;
import cn.aios.resource.entity.PortalSchedule;
import cn.aios.resource.mapper.PortalAnnouncementMapper;
import cn.aios.resource.mapper.PortalMeetingAttendeeMapper;
import cn.aios.resource.mapper.PortalMeetingMapper;
import cn.aios.resource.mapper.PortalScheduleMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 管理端首页门户服务（公告 / 会议 / 日程）。
 *
 * <p>租户隔离口径与业务一致：普通登录用户可见「本租户 + tenant_id=0 公共」的数据；
 * 公告仅出 PUBLISHED；会议按 organizer_id（mine）或 attendee.user_id（invited）区分；
 * 日程按 user_id 属主 + 租户范围查询当月 / 今日。</p>
 */
@Service
@RequiredArgsConstructor
public class PortalService {

    private final PortalAnnouncementMapper announcementMapper;
    private final PortalMeetingMapper meetingMapper;
    private final PortalMeetingAttendeeMapper attendeeMapper;
    private final PortalScheduleMapper scheduleMapper;

    private static final DateTimeFormatter FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private static String fmt(LocalDateTime t) {
        return t == null ? null : t.format(FMT);
    }

    /** 本租户 + 平台公共（tenant_id=0）的可见租户集合。 */
    private static List<Long> tenantScope(Long tenantId) {
        Long tid = (tenantId == null || tenantId == 0L) ? 0L : tenantId;
        return List.of(tid, 0L);
    }

    private static int normPage(int page) {
        return Math.max(1, page);
    }

    private static int normSize(int size) {
        return Math.max(1, Math.min(size, 100));
    }

    private static Map<String, Object> pageMap(List<?> list, long total, int page, int size) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("list", list);
        m.put("total", total);
        m.put("page", page);
        m.put("size", size);
        return m;
    }

    // ── 公告：PUBLISHED，按 publish_at 倒序，本租户 + 公共 ──
    public Map<String, Object> listAnnouncements(Long tenantId, int page, int size) {
        int p = normPage(page);
        int s = normSize(size);
        List<Long> scope = tenantScope(tenantId);
        long total = announcementMapper.selectCount(new LambdaQueryWrapper<PortalAnnouncement>()
                .in(PortalAnnouncement::getTenantId, scope)
                .eq(PortalAnnouncement::getStatus, "PUBLISHED"));
        int offset = (p - 1) * s;
        List<PortalAnnouncement> rows = announcementMapper.selectList(new LambdaQueryWrapper<PortalAnnouncement>()
                .in(PortalAnnouncement::getTenantId, scope)
                .eq(PortalAnnouncement::getStatus, "PUBLISHED")
                .orderByDesc(PortalAnnouncement::getPublishAt)
                .last("LIMIT " + offset + ", " + s));
        List<AnnouncementView> list = rows.stream().map(AnnouncementView::from).toList();
        return pageMap(list, total, p, s);
    }

    // ── 会议：mine=我组织的；invited=邀请我的（带 inviteStatus）──
    public Map<String, Object> listMeetings(Long tenantId, Long userId, String scope, int page, int size) {
        int p = normPage(page);
        int s = normSize(size);
        List<Long> tScope = tenantScope(tenantId);
        long total;
        List<MeetingView> list;
        if ("invited".equalsIgnoreCase(scope)) {
            total = attendeeMapper.selectCount(new LambdaQueryWrapper<PortalMeetingAttendee>()
                    .in(PortalMeetingAttendee::getTenantId, tScope)
                    .eq(PortalMeetingAttendee::getUserId, userId));
            int offset = (p - 1) * s;
            List<PortalMeetingAttendee> atts = attendeeMapper.selectList(new LambdaQueryWrapper<PortalMeetingAttendee>()
                    .in(PortalMeetingAttendee::getTenantId, tScope)
                    .eq(PortalMeetingAttendee::getUserId, userId)
                    .orderByDesc(PortalMeetingAttendee::getCreatedAt)
                    .last("LIMIT " + offset + ", " + s));
            Map<Long, String> invMap = new LinkedHashMap<>();
            List<Long> mids = new ArrayList<>();
            for (PortalMeetingAttendee a : atts) {
                if (!invMap.containsKey(a.getMeetingId())) {
                    invMap.put(a.getMeetingId(), a.getInviteStatus());
                    mids.add(a.getMeetingId());
                }
            }
            List<PortalMeeting> meetings = mids.isEmpty() ? List.of() : meetingMapper.selectBatchIds(mids);
            Map<Long, String> finalInv = invMap;
            meetings.sort(Comparator.comparing(PortalMeeting::getStartAt,
                    Comparator.nullsLast(Comparator.reverseOrder())));
            list = meetings.stream().map(m -> MeetingView.from(m, finalInv.get(m.getId()))).toList();
        } else {
            total = meetingMapper.selectCount(new LambdaQueryWrapper<PortalMeeting>()
                    .in(PortalMeeting::getTenantId, tScope)
                    .eq(PortalMeeting::getOrganizerId, userId));
            int offset = (p - 1) * s;
            List<PortalMeeting> meetings = meetingMapper.selectList(new LambdaQueryWrapper<PortalMeeting>()
                    .in(PortalMeeting::getTenantId, tScope)
                    .eq(PortalMeeting::getOrganizerId, userId)
                    .orderByDesc(PortalMeeting::getStartAt)
                    .last("LIMIT " + offset + ", " + s));
            list = meetings.stream().map(m -> MeetingView.from(m, null)).toList();
        }
        return pageMap(list, total, p, s);
    }

    // ── 日程：当月（当前用户，本租户 + 公共）──
    public Map<String, Object> listSchedules(Long tenantId, Long userId, String month) {
        List<Long> tScope = tenantScope(tenantId);
        YearMonth ym;
        try {
            ym = YearMonth.parse(month);
        } catch (Exception e) {
            ym = YearMonth.from(LocalDate.now());
        }
        LocalDateTime from = ym.atDay(1).atStartOfDay();
        LocalDateTime to = ym.plusMonths(1).atDay(1).atStartOfDay();
        List<PortalSchedule> rows = scheduleMapper.selectList(new LambdaQueryWrapper<PortalSchedule>()
                .in(PortalSchedule::getTenantId, tScope)
                .eq(PortalSchedule::getUserId, userId)
                .ge(PortalSchedule::getStartAt, from)
                .lt(PortalSchedule::getStartAt, to)
                .orderByAsc(PortalSchedule::getStartAt));
        List<ScheduleView> list = rows.stream().map(ScheduleView::from).toList();
        return pageMap(list, list.size(), 1, list.size());
    }

    // ── 日程：今日（当前用户，本租户 + 公共）──
    public Map<String, Object> listSchedulesToday(Long tenantId, Long userId) {
        List<Long> tScope = tenantScope(tenantId);
        LocalDate today = LocalDate.now();
        LocalDateTime from = today.atStartOfDay();
        LocalDateTime to = today.plusDays(1).atStartOfDay();
        List<PortalSchedule> rows = scheduleMapper.selectList(new LambdaQueryWrapper<PortalSchedule>()
                .in(PortalSchedule::getTenantId, tScope)
                .eq(PortalSchedule::getUserId, userId)
                .ge(PortalSchedule::getStartAt, from)
                .lt(PortalSchedule::getStartAt, to)
                .orderByAsc(PortalSchedule::getStartAt));
        List<ScheduleView> list = rows.stream().map(ScheduleView::from).toList();
        return pageMap(list, list.size(), 1, list.size());
    }

    // ══════════════════════════════════════════════════════════════════════════
    //  写链路（2026-10-31 重构补充）
    // ------------------------------------------------------------------------
    // 为什么现在才补：V94 只建了表 + 只读查询，全仓 `/api/v1/portal` 零调用方（连管理端都
    // 改走表单了），等于「数据层建好了、业务层没有入口」。这里按**最小可用闭环**补齐：
    // 日程（个人 CRUD）+ 会议（发起 / 参会人邀请 / 取消 / 应答），四层全部打通到前端。
    //
    // 三条硬口径（与本项目其它模块一致，勿回退）：
    //   ① 租户隔离：可见 = 本租户 + tenant_id=0（平台公共）；**写必须落在用户自己的租户**，
    //      公共数据只可读不可改（否则普通用户能改平台数据）；
    //   ② 归属：日程只能改自己的（user_id 不符即 404，不告知「存在但无权」，避免探测他人数据）；
    //      会议只有组织者能取消，只有被邀请人能应答；
    //   ③ 逻辑删除：统一置 deleted_at，绝不物理删（审计口径）。
    // ══════════════════════════════════════════════════════════════════════════

    /** 时间解析：兼容 `yyyy-MM-dd HH:mm:ss`、`yyyy-MM-dd HH:mm`、datetime-local 的 `yyyy-MM-ddTHH:mm[:ss]`。 */
    private static LocalDateTime parseTime(Object raw, String field) {
        String s = raw == null ? null : String.valueOf(raw).trim();
        if (s == null || s.isEmpty()) {
            return null;
        }
        String norm = s.replace('T', ' ');
        for (DateTimeFormatter f : TIME_FORMATTERS) {
            try {
                return LocalDateTime.parse(norm, f);
            } catch (Exception ignored) {
                // 换下一个候选格式
            }
        }
        throw new IllegalArgumentException("时间格式不合法（" + field + "）：" + s
                + "，应为 yyyy-MM-dd HH:mm:ss 或 yyyy-MM-ddTHH:mm");
    }

    private static final List<DateTimeFormatter> TIME_FORMATTERS = List.of(
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS"));

    private static String requireText(Object raw, String field, int max) {
        String s = raw == null ? null : String.valueOf(raw).trim();
        if (s == null || s.isEmpty()) {
            throw new IllegalArgumentException(field + "不能为空");
        }
        if (s.length() > max) {
            throw new IllegalArgumentException(field + "过长（最多 " + max + " 字）");
        }
        return s;
    }

    /** 写入库用的租户：公共 tenant 的用户写入 0；否则写自己租户。 */
    private static Long writeTenant(Long tenantId) {
        return (tenantId == null) ? 0L : tenantId;
    }

    private static void checkOrder(LocalDateTime start, LocalDateTime end) {
        if (start != null && end != null && end.isBefore(start)) {
            throw new IllegalArgumentException("结束时间不能早于开始时间");
        }
    }

    // ── 日程：创建 ──
    public Map<String, Object> createSchedule(Long tenantId, Long userId, Map<String, Object> body) {
        LocalDateTime now = LocalDateTime.now();
        PortalSchedule row = new PortalSchedule();
        row.setTenantId(writeTenant(tenantId));
        row.setUserId(userId);
        row.setTitle(requireText(body.get("title"), "日程标题", 256));
        LocalDateTime start = parseTime(body.get("startAt"), "开始时间");
        LocalDateTime end = parseTime(body.get("endAt"), "结束时间");
        checkOrder(start, end);
        row.setStartAt(start);
        row.setEndAt(end);
        row.setLocation(body.get("location") == null ? null
                : String.valueOf(body.get("location")).trim());
        row.setRemark(body.get("remark") == null ? null
                : String.valueOf(body.get("remark")).trim());
        row.setCreatedAt(now);
        row.setUpdatedAt(now);
        scheduleMapper.insert(row);
        return new LinkedHashMap<>(Map.of("id", row.getId()));
    }

    // ── 日程：更新（仅本人）──
    public Map<String, Object> updateSchedule(Long tenantId, Long userId, Long id, Map<String, Object> body) {
        PortalSchedule row = ownSchedule(tenantId, userId, id);
        if (body.containsKey("title")) {
            row.setTitle(requireText(body.get("title"), "日程标题", 256));
        }
        if (body.containsKey("startAt")) {
            row.setStartAt(parseTime(body.get("startAt"), "开始时间"));
        }
        if (body.containsKey("endAt")) {
            row.setEndAt(parseTime(body.get("endAt"), "结束时间"));
        }
        checkOrder(row.getStartAt(), row.getEndAt());
        if (body.containsKey("location")) {
            row.setLocation(body.get("location") == null ? null
                    : String.valueOf(body.get("location")).trim());
        }
        if (body.containsKey("remark")) {
            row.setRemark(body.get("remark") == null ? null
                    : String.valueOf(body.get("remark")).trim());
        }
        row.setUpdatedAt(LocalDateTime.now());
        scheduleMapper.updateById(row);
        return new LinkedHashMap<>(Map.of("id", row.getId()));
    }

    // ── 日程：删除（逻辑删，仅本人）──
    public void deleteSchedule(Long tenantId, Long userId, Long id) {
        PortalSchedule row = ownSchedule(tenantId, userId, id);
        // 逻辑删除：不能走 setDeletedAt + updateById(null wrapper)（MP 的 NOT_NULL 策略会静默跳过空参），
        // 必须显式 LambdaUpdateWrapper.set(...) —— 这条坑 mcp_server 清 lastError 时踩过。
        scheduleMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<PortalSchedule>()
                .eq(PortalSchedule::getId, row.getId())
                .isNull(PortalSchedule::getDeletedAt)
                .set(PortalSchedule::getDeletedAt, LocalDateTime.now()));
    }

    private PortalSchedule ownSchedule(Long tenantId, Long userId, Long id) {
        PortalSchedule row = scheduleMapper.selectById(id);
        if (row == null || row.getDeletedAt() != null
                || !tenantScope(tenantId).contains(row.getTenantId())
                || !java.util.Objects.equals(row.getUserId(), userId)) {
            throw new cn.aios.common.exception.BizException(404, "日程不存在或无权操作");
        }
        return row;
    }

    // ── 会议：发起（含参会人 + 时间地点冲突校验）──
    public Map<String, Object> createMeeting(Long tenantId, Long userId, String userName,
                                             Map<String, Object> body) {
        LocalDateTime now = LocalDateTime.now();
        PortalMeeting m = new PortalMeeting();
        m.setTenantId(writeTenant(tenantId));
        m.setTitle(requireText(body.get("title"), "会议主题", 256));
        LocalDateTime start = parseTime(body.get("startAt"), "开始时间");
        LocalDateTime end = parseTime(body.get("endAt"), "结束时间");
        checkOrder(start, end);
        m.setStartAt(start);
        m.setEndAt(end);
        m.setLocation(body.get("location") == null ? null
                : String.valueOf(body.get("location")).trim());
        m.setOrganizerId(userId);
        m.setOrganizerName(userName == null || userName.isBlank() ? ("用户" + userId) : userName);
        m.setStatus(STATUS_SCHEDULED);
        m.setCreatedAt(now);
        m.setUpdatedAt(now);

        // 冲突校验：同一租户内、同一地点、时间区间重叠且未取消的会议 ⇒ 拒绝。
        // 只校验「有地点」的会议：无地点的线上会议不做房间冲突判断（判了会误伤）。
        if (start != null && end != null && m.getLocation() != null && !m.getLocation().isBlank()) {
            PortalMeeting clash = findRoomClash(m.getTenantId(), m.getLocation(), start, end, null);
            if (clash != null) {
                throw new IllegalArgumentException("该时间段「" + m.getLocation()
                        + "」已被占用：#" + clash.getId() + " " + clash.getTitle()
                        + "（" + fmt(clash.getStartAt()) + " ~ " + fmt(clash.getEndAt()) + "）");
            }
        }
        meetingMapper.insert(m);

        List<Long> attendeeIds = toLongList(body.get("attendeeIds"));
        int invited = 0;
        java.util.Set<Long> seen = new java.util.LinkedHashSet<>();
        for (Long uid : attendeeIds) {
            if (uid == null || uid.equals(userId) || !seen.add(uid)) {
                continue;                      // 组织者本身就是参会人，不重复写
            }
            PortalMeetingAttendee a = new PortalMeetingAttendee();
            a.setTenantId(m.getTenantId());
            a.setMeetingId(m.getId());
            a.setUserId(uid);
            a.setInviteStatus(INVITE_INVITED);
            a.setCreatedAt(now);
            a.setUpdatedAt(now);
            attendeeMapper.insert(a);
            invited++;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", m.getId());
        out.put("invited", invited);
        return out;
    }

    // ── 会议：取消（仅组织者）──
    public void cancelMeeting(Long tenantId, Long userId, Long id) {
        PortalMeeting m = ownMeeting(tenantId, userId, id);
        meetingMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<PortalMeeting>()
                .eq(PortalMeeting::getId, m.getId())
                .set(PortalMeeting::getStatus, STATUS_CANCELED)
                .set(PortalMeeting::getUpdatedAt, LocalDateTime.now()));
        // 参会人邀请态一并收敛：会议取消了，还挂着 INVITED 是脏数据（前端会显示「待应答」）。
        attendeeMapper.update(null, new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<PortalMeetingAttendee>()
                .eq(PortalMeetingAttendee::getMeetingId, m.getId())
                .eq(PortalMeetingAttendee::getInviteStatus, INVITE_INVITED)
                .set(PortalMeetingAttendee::getInviteStatus, INVITE_DECLINED)
                .set(PortalMeetingAttendee::getUpdatedAt, LocalDateTime.now()));
    }

    // ── 会议：应答（仅被邀请人）──
    public void respondMeeting(Long tenantId, Long userId, Long id, String decision) {
        String status = INVITE_ACCEPTED.equalsIgnoreCase(decision) ? INVITE_ACCEPTED
                : INVITE_DECLINED.equalsIgnoreCase(decision) ? INVITE_DECLINED : null;
        if (status == null) {
            throw new IllegalArgumentException("应答值只能是 ACCEPTED 或 DECLINED");
        }
        PortalMeeting m = meetingMapper.selectById(id);
        if (m == null || !tenantScope(tenantId).contains(m.getTenantId())) {
            throw new cn.aios.common.exception.BizException(404, "会议不存在或无权访问");
        }
        if (STATUS_CANCELED.equals(m.getStatus())) {
            throw new IllegalArgumentException("会议已取消，无法应答");
        }
        long updated = attendeeMapper.update(null,
                new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<PortalMeetingAttendee>()
                        .eq(PortalMeetingAttendee::getMeetingId, id)
                        .eq(PortalMeetingAttendee::getUserId, userId)
                        .set(PortalMeetingAttendee::getInviteStatus, status)
                        .set(PortalMeetingAttendee::getUpdatedAt, LocalDateTime.now()));
        if (updated == 0) {
            throw new cn.aios.common.exception.BizException(404, "你不在该会议的参会人名单中");
        }
    }

    private PortalMeeting ownMeeting(Long tenantId, Long userId, Long id) {
        PortalMeeting m = meetingMapper.selectById(id);
        if (m == null || m.getDeletedAt() != null
                || !tenantScope(tenantId).contains(m.getTenantId())
                || !java.util.Objects.equals(m.getOrganizerId(), userId)) {
            throw new cn.aios.common.exception.BizException(404, "会议不存在或只有组织者可以取消");
        }
        return m;
    }

    /** 同租户 + 同地点 + 时间区间重叠（排除自己、已取消、已删除）。 */
    private PortalMeeting findRoomClash(Long tenantId, String location, LocalDateTime start,
                                        LocalDateTime end, Long excludeId) {
        // 重叠判据：start < 已有.end AND end > 已有.start（端点相接不算冲突）
        List<PortalMeeting> rows = meetingMapper.selectList(new LambdaQueryWrapper<PortalMeeting>()
                .eq(PortalMeeting::getTenantId, tenantId)
                .eq(PortalMeeting::getLocation, location)
                .eq(PortalMeeting::getStatus, STATUS_SCHEDULED)
                .isNull(PortalMeeting::getDeletedAt)
                .lt(PortalMeeting::getStartAt, end)
                .gt(PortalMeeting::getEndAt, start)
                .last("LIMIT 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private static List<Long> toLongList(Object raw) {
        if (!(raw instanceof java.util.Collection<?> c)) {
            return List.of();
        }
        List<Long> out = new ArrayList<>();
        for (Object o : c) {
            if (o == null) {
                continue;
            }
            try {
                out.add(Long.valueOf(String.valueOf(o).trim()));
            } catch (NumberFormatException ignored) {
                // 非法 id 跳过而不是让整个会议创建失败（参会人名单是次要信息）
            }
        }
        return out;
    }

    private static final String STATUS_SCHEDULED = "SCHEDULED";
    private static final String STATUS_CANCELED = "CANCELED";
    private static final String INVITE_INVITED = "INVITED";
    private static final String INVITE_ACCEPTED = "ACCEPTED";
    private static final String INVITE_DECLINED = "DECLINED";

    public record AnnouncementView(Long id, String title, String category, String publisherName, String publishAt) {
        static AnnouncementView from(PortalAnnouncement a) {
            return new AnnouncementView(a.getId(), a.getTitle(), a.getCategory(),
                    a.getPublisherName(), fmt(a.getPublishAt()));
        }
    }

    public record MeetingView(Long id, String title, String startAt, String endAt,
                              String location, String organizerName, String status, String inviteStatus) {
        static MeetingView from(PortalMeeting m, String inviteStatus) {
            return new MeetingView(m.getId(), m.getTitle(), fmt(m.getStartAt()), fmt(m.getEndAt()),
                    m.getLocation(), m.getOrganizerName(), m.getStatus(), inviteStatus);
        }
    }

    public record ScheduleView(Long id, String title, String startAt, String endAt, String location) {
        static ScheduleView from(PortalSchedule s) {
            return new ScheduleView(s.getId(), s.getTitle(),
                    fmt(s.getStartAt()), fmt(s.getEndAt()), s.getLocation());
        }
    }
}
