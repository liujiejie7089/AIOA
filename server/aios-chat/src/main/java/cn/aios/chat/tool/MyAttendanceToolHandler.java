package cn.aios.chat.tool;

import cn.aios.org.service.AttendanceService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * 「我的考勤」工具（2026-11-05）。
 *
 * <p>回答「我今天打卡了吗」「这周我迟到了几次」这类问题。<b>只查自己的</b>：考勤是个人数据，
 * 查别人的必须走管理端权限，不在这里开口子（工具以当前登录用户身份执行，越权天然不可达）。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class MyAttendanceToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "my_attendance";

    private final AttendanceService attendanceService;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "查询当前用户的考勤打卡记录（今天 / 近 N 天）：上班卡、下班卡、打卡时间、地点、来源。"
                + "用户问「我今天打卡了吗」「昨天几点打的卡」「这周考勤怎么样」时调用。"
                + "如果今天还没打卡，可以接着调用 attendance_clock 发起打卡。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"days\":{\"type\":\"integer\",\"description\":\"查最近几天，默认 0 = 只看今天；1~31\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            int days = 0;
            Object raw = args == null ? null : args.get("days");
            if (raw != null && !String.valueOf(raw).isBlank()) {
                try {
                    days = Integer.parseInt(String.valueOf(raw).trim());
                } catch (NumberFormatException ignore) {
                    days = 0;
                }
            }
            Map<String, Object> data = days <= 1
                    ? attendanceService.today(user)
                    : attendanceService.recent(user, days);
            // 待处理申请只让模型知道「有一张在等用户同意」，token 不外抛（它是一次性凭据）
            Object pending = data.remove("pendingConsent");
            data.put("hasPendingConsent", pending != null);
            data.put("summary", summarize(data));
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            log.warn("my_attendance failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "查询考勤失败：" + e.getMessage());
        }
    }

    private static String summarize(Map<String, Object> data) {
        Object recs = data.get("records");
        if (!(recs instanceof List<?> list) || list.isEmpty()) {
            return "所选区间内没有打卡记录";
        }
        StringBuilder sb = new StringBuilder();
        for (Object o : list) {
            if (o instanceof Map<?, ?> m) {
                sb.append(m.get("date")).append(' ').append(m.get("clockTypeLabel"))
                        .append(' ').append(m.get("time"));
                Object place = m.get("placeName");
                if (place != null && !String.valueOf(place).isBlank()) {
                    sb.append(" @").append(place);
                }
                sb.append("；");
            }
        }
        return sb.toString();
    }
}
