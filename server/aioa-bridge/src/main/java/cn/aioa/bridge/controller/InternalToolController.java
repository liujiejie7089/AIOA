package cn.aioa.bridge.controller;

import cn.aioa.bridge.service.ToolInvocationService;
import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.security.AuthUser;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.Data;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

/**
 * 工具桥接内部接口（服务间调用，{@code /internal/**} 由服务令牌守卫）。
 *
 * <p>V59 起不再返回 501：真实执行「定义驱动」的工具调用。调用方（Python agent）
 * 已经在自己的链路上完成了用户认证，因此这里以<b>显式主体</b>
 * （tenantId / userId / institutionId / roles）传递调用者身份 —— 服务令牌保证
 * 「谁能访问这个端点」，显式主体保证「以谁的身份、在哪把闸门下执行」，两者职责不重叠。</p>
 *
 * <p>返回体不是简单的是/否：{@code status} 区分
 * {@code OK} / {@code PENDING_APPROVAL} / {@code DEDUPED} / {@code DENIED} / {@code ERROR}，
 * 让模型能如实告诉用户「已提交审批」而不是「调用成功」。</p>
 */
@Tag(name = "内部-工具桥接")
@RestController
@RequestMapping("/internal/v1/tools")
public class InternalToolController {

    private final ToolInvocationService invocationService;

    public InternalToolController(ToolInvocationService invocationService) {
        this.invocationService = invocationService;
    }

    @Operation(summary = "工具调用（定义驱动：权限 → 幂等 → 审批 → HTTP）")
    @PostMapping("/invoke")
    public ApiResponse<Map<String, Object>> invoke(@RequestBody(required = false) ToolInvokeRequest request) {
        if (request == null || request.getToolCode() == null || request.getToolCode().isBlank()) {
            throw BizException.badRequest("toolCode 不能为空");
        }
        if (request.getUserId() == null || request.getTenantId() == null) {
            throw BizException.badRequest("调用者身份缺失：tenantId / userId 必填");
        }
        AuthUser user = toUser(request.getTenantId(), request.getUserId(), request.getUsername(),
                request.getNickname(), request.getInstitutionId(), request.getDepartmentId(), request.getRoles());
        return ApiResponse.ok(invocationService.invoke(request.getToolCode(), request.getVersion(),
                request.getRunId(), request.getArgs(), request.getIdempotencyKey(), user));
    }

    @Operation(summary = "工具调用清单（OpenAI function 格式，已按角色过滤）")
    @GetMapping
    public ApiResponse<List<Map<String, Object>>> list(@RequestParam(required = false) Long tenantId,
                                                       @RequestParam(required = false) String roles) {
        return ApiResponse.ok(invocationService.catalog(
                tenantId == null ? 0L : tenantId, parseRoles(roles)));
    }

    @Operation(summary = "恢复执行：审批通过后由回调驱动（幂等，重复调用返回 NOOP）")
    @PostMapping("/resume")
    public ApiResponse<Map<String, Object>> resume(@RequestBody ResumeRequest request) {
        if (request == null || request.getApprovalId() == null || request.getApprovalId().isBlank()) {
            throw BizException.badRequest("approvalId 不能为空");
        }
        return ApiResponse.ok(invocationService.resume(request.getApprovalId()));
    }

    @Operation(summary = "终止挂起的调用：审批驳回时由回调驱动")
    @PostMapping("/abort")
    public ApiResponse<Map<String, Object>> abort(@RequestBody ResumeRequest request) {
        if (request == null || request.getApprovalId() == null || request.getApprovalId().isBlank()) {
            throw BizException.badRequest("approvalId 不能为空");
        }
        return ApiResponse.ok(invocationService.abort(request.getApprovalId(), request.getReason()));
    }

    private static AuthUser toUser(Long tenantId, Long userId, String username, String nickname,
                                   Long institutionId, Long departmentId, List<String> roles) {
        return AuthUser.builder()
                .tenantId(tenantId)
                .userId(userId)
                .username(username)
                .nickname(nickname)
                .institutionId(institutionId)
                .departmentId(departmentId)
                .roles(roles == null ? new ArrayList<>() : new ArrayList<>(roles))
                .permissions(new ArrayList<>())
                .build();
    }

    private static List<String> parseRoles(String roles) {
        if (roles == null || roles.isBlank()) {
            return List.of();
        }
        return Arrays.stream(roles.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }

    @Data
    public static class ToolInvokeRequest {

        private String toolCode;
        private String version;
        private String runId;
        /** 幂等键；也可放在 args.idempotencyKey。 */
        private String idempotencyKey;
        private Map<String, Object> args;
        // ---- 调用者身份（服务间显式传递）----
        private Long tenantId;
        private Long userId;
        private String username;
        private String nickname;
        private Long institutionId;
        private Long departmentId;
        private List<String> roles;
    }

    @Data
    public static class ResumeRequest {

        private String approvalId;
        private String reason;
    }
}
