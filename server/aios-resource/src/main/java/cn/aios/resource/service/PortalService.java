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
