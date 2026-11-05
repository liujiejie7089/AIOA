package cn.aios.chat.tool;

import cn.aios.org.service.AttendanceService;
import cn.aios.resource.support.ExternalToolHandler;
import cn.aios.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 「打卡」工具（2026-11-05）。
 *
 * <p><b>为什么这个工具不直接写考勤记录</b>：打卡必须有位置，而位置只有用户手机上才有 ——
 * 模型拿不到，也不该拿到。所以本工具做的事是：<b>发起一次「定位调用申请」</b>，
 * 由页面弹出卡片请用户明确同意；用户点「允许」后浏览器取坐标、调同一个打卡接口落库。</p>
 *
 * <p>这样一来，模型仍然「调用了打卡接口」（它决定了打什么卡、什么时候打），
 * 但写库那一步必须有人按过按钮。既满足「数字人可调用接口给员工打卡」，
 * 又不给模型一个能在后台悄悄记录员工位置的通道。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ClockInToolHandler implements ExternalToolHandler {

    public static final String TOOL_NAME = "attendance_clock";

    private final AttendanceService attendanceService;

    @Override
    public String name() {
        return TOOL_NAME;
    }

    @Override
    public String description() {
        return "帮当前用户打卡。因为打卡需要手机定位，本工具不会直接写入考勤，"
                + "而是向用户发起一次「定位调用申请」：页面会弹出卡片，用户点「允许」后才真正完成打卡。"
                + "用户说「帮我打卡」「上班打卡」「下班打卡」时调用；"
                + "调用后请告诉用户「已在页面发起定位申请，请点允许」，不要声称已经打好卡了。";
    }

    @Override
    public String parametersJson() {
        return "{\"type\":\"object\",\"properties\":{"
                + "\"clockType\":{\"type\":\"string\",\"enum\":[\"ON\",\"OFF\"],"
                + "\"description\":\"ON 上班卡 / OFF 下班卡；不确定就留空，系统按今天是否已打上班卡自动判断\"},"
                + "\"reason\":{\"type\":\"string\",\"description\":\"可选。用户为什么要打卡（如「刚到公司」），仅用于文案\"}"
                + "},\"required\":[]}";
    }

    @Override
    public Map<String, Object> invoke(Map<String, Object> args, AuthUser user) {
        try {
            // 已有未过期的申请就复用：用户说两遍「打卡」不该弹两张卡
            Map<String, Object> exist = attendanceService.pending(user);
            Map<String, Object> consent = exist != null ? exist : attendanceService.requestConsent(user, "AI", null);
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("needLocation", true);
            data.put("consentId", consent.get("id"));
            data.put("prompt", consent.get("prompt"));
            data.put("expiresInSeconds", consent.get("expiresInSeconds"));
            data.put("requestedClockType", args == null ? null : args.get("clockType"));
            data.put("message", "已在页面发起定位调用申请：请用户在卡片上点「允许定位」，"
                    + "允许后浏览器会上报当前位置并完成打卡。用户拒绝则本次不打卡，不要重复发起。");
            return Map.of("ok", true, "data", data);
        } catch (Exception e) {
            log.warn("attendance_clock failed: {}", e.getMessage());
            return Map.of("ok", false, "error", "发起打卡失败：" + e.getMessage());
        }
    }
}
