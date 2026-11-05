package cn.aios.org.controller;

import cn.aios.common.resp.ApiResponse;
import cn.aios.org.service.AttendanceService;
import cn.aios.security.AuthUser;
import cn.aios.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 定位授权与考勤打卡（2026-11-05，docs/74）。
 *
 * <pre>
 * POST /api/v1/attendance/location-consent              —— 发起一次「定位调用申请」（不取坐标）
 * GET  /api/v1/attendance/location-consent/pending      —— 有没有还没处理的申请（前端据此弹卡）
 * POST /api/v1/attendance/location-consent/{id}/deny    —— 用户点「不允许」（留痕）
 * POST /api/v1/attendance/clock                         —— 同意并打卡（body 必须带 token + 坐标）
 * GET  /api/v1/attendance/today                         —— 今日打卡状态
 * GET  /api/v1/attendance/recent?days=7                 —— 近 N 天记录
 * </pre>
 *
 * <p>两条入口（用户点页面「打卡」、数字人调用工具）都落到同一个
 * {@link AttendanceService#clock}，不存在「AI 能绕开授权」的第二套口径。</p>
 */
@RestController
@RequestMapping("/api/v1/attendance")
@RequiredArgsConstructor
public class AttendanceController {

    private final AttendanceService attendanceService;

    /** 发起定位申请。body 可空：{origin: H5|AI, purpose: ATTENDANCE}。 */
    @PostMapping("/location-consent")
    public ApiResponse<Map<String, Object>> requestConsent(@RequestBody(required = false) Map<String, Object> body) {
        Map<String, Object> b = body == null ? Map.of() : body;
        return ApiResponse.ok(attendanceService.requestConsent(
                AuthUserContext.require(),
                String.valueOf(b.getOrDefault("origin", "H5")),
                b.get("purpose") == null ? null : String.valueOf(b.get("purpose"))));
    }

    /** 待处理申请；没有则 data 为 null（前端据此静默，不弹空卡）。 */
    @GetMapping("/location-consent/pending")
    public ApiResponse<Map<String, Object>> pending() {
        return ApiResponse.ok(attendanceService.pending(AuthUserContext.require()));
    }

    /** 用户拒绝：留痕，方便统计「申请是否打扰」。 */
    @PostMapping("/location-consent/{id}/deny")
    public ApiResponse<Void> deny(@PathVariable Long id) {
        attendanceService.deny(AuthUserContext.require(), id);
        return ApiResponse.ok(null);
    }

    /** 同意并打卡。body: {token, latitude, longitude, accuracy?, clockType?, placeName?, source?} */
    @PostMapping("/clock")
    public ApiResponse<Map<String, Object>> clock(@RequestBody(required = false) Map<String, Object> body) {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(attendanceService.clock(user, body == null ? Map.of() : body));
    }

    @GetMapping("/today")
    public ApiResponse<Map<String, Object>> today() {
        return ApiResponse.ok(attendanceService.today(AuthUserContext.require()));
    }

    @GetMapping("/recent")
    public ApiResponse<Map<String, Object>> recent(@RequestParam(defaultValue = "7") int days) {
        return ApiResponse.ok(attendanceService.recent(AuthUserContext.require(), days));
    }
}
