package cn.aioa.chat.controller;

import cn.aioa.chat.service.WorkerIntakeService;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 数字员工准入接口（需求项 6 标准流程的前两段）。
 *
 * <pre>
 *   POST /api/v1/workers/intent     自然语言 → 数字员工类型 → 推荐权限（不让用户选权限码）
 *   POST /api/v1/workers/precheck   创建前六项前置检查（权限/能力/审批人/表单/审批流/计费）
 * </pre>
 *
 * <p><b>为什么在 aioa-chat 而不是 aioa-resource</b>：六项检查需要同时访问 aioa-resource
 * （权限/计费/工具）与 aioa-org（审批人/审批流/假种/知识库），这两个模块互不依赖，
 * 只有 aioa-chat 同时依赖二者 —— 与 {@code StatsController} 同一原因。
 * 端点路径仍是 {@code /api/v1/workers/**}，归属语义不变，只是实现落在唯一可见两个域的模块里。</p>
 *
 * <p>两个端点都只读不写：检查失败不产生任何数据，创建接口自身还会独立再校验一次。</p>
 */
@Tag(name = "数字员工准入")
@RestController
@RequestMapping("/api/v1/workers")
@RequiredArgsConstructor
public class WorkerIntakeController {

    private final WorkerIntakeService intakeService;

    public record IntentReq(String text) {
    }

    public record PrecheckReq(String text, String workerType, String name, String description,
                              String scheduleTime, String taskPrompt, String runMode) {
    }

    @Operation(summary = "意图识别：自然语言 → 数字员工类型与推荐权限")
    @PostMapping("/intent")
    public ApiResponse<Map<String, Object>> intent(@RequestBody IntentReq req) {
        AuthUserContext.require();
        return ApiResponse.ok(intakeService.intent(req == null || req.text() == null ? "" : req.text()));
    }

    @Operation(summary = "创建前六项前置检查")
    @PostMapping("/precheck")
    public ApiResponse<Map<String, Object>> precheck(@RequestBody PrecheckReq req) {
        AuthUser user = AuthUserContext.require();
        Map<String, Object> body = new java.util.LinkedHashMap<>();
        if (req != null) {
            body.put("text", req.text());
            body.put("workerType", req.workerType());
            body.put("name", req.name());
            body.put("description", req.description());
            body.put("scheduleTime", req.scheduleTime());
            body.put("taskPrompt", req.taskPrompt());
            body.put("runMode", req.runMode());
        }
        return ApiResponse.ok(intakeService.precheck(user, body));
    }
}
