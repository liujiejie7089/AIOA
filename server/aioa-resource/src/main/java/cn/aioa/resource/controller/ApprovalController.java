package cn.aioa.resource.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.resource.entity.ApprovalOrder;
import cn.aioa.resource.service.ApprovalService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 审批工作流（FR-D6 审批卡点）：
 *   POST /api/v1/approvals                  —— 用户端提交审批（落 PENDING）
 *   GET  /api/v1/approvals?scope=mine|todo  —— 我的审批 / 审批中心待办
 *   POST /api/v1/approvals/{id}/decision     —— 通过 / 驳回
 */
@RestController
@RequestMapping("/api/v1/approvals")
@RequiredArgsConstructor
public class ApprovalController {

    private final ApprovalService approvalService;

    public record SubmitBody(String bizType, String title, String content, String runId,
                             Long conversationId, Long resultId, String formData, String attachment) {
    }

    public record DecisionBody(String decision, String note) {
    }

    public record ApprovalView(Long id, Long userId, String applicantName, String creatorName, String bizType, String title,
                                String content, String status, String approver, String decisionNote,
                                String decidedAt, String createdAt, boolean mine,
                                String formData, String attachment) {

        static ApprovalView from(ApprovalOrder o, Long currentUserId) {
            return new ApprovalView(o.getId(), o.getUserId(), o.getApplicantName(), o.getApplicantName(), o.getBizType(), o.getTitle(),
                    o.getContent(), o.getStatus(), o.getApprover(), o.getDecisionNote(),
                    o.getDecidedAt() == null ? null : o.getDecidedAt().toString(),
                    o.getCreatedAt() == null ? null : o.getCreatedAt().toString(),
                    currentUserId != null && currentUserId.equals(o.getUserId()),
                    o.getFormData(), o.getAttachment());
        }
    }

    @PostMapping
    public ApiResponse<ApprovalView> submit(@RequestBody(required = false) SubmitBody body) {
        AuthUser user = AuthUserContext.require();
        String bizType = body == null ? null : body.bizType();
        String title = body == null ? null : body.title();
        String content = body == null ? null : body.content();
        String runId = body == null ? null : body.runId();
        Long convId = body == null ? null : body.conversationId();
        Long resultId = body == null ? null : body.resultId();
        String formData = body == null ? null : body.formData();
        String attachment = body == null ? null : body.attachment();
        ApprovalOrder order = approvalService.submit(user.getTenantId(), user.getUserId(),
                user.getNickname(), bizType, title, content, runId, convId, resultId, formData, attachment);
        return ApiResponse.ok(ApprovalView.from(order, user.getUserId()));
    }

    @GetMapping
    public ApiResponse<List<ApprovalView>> list(@RequestParam(name = "scope", defaultValue = "mine") String scope) {
        AuthUser user = AuthUserContext.require();
        boolean todo = "todo".equalsIgnoreCase(scope);
        // 审批中心（待我审批）仅租户管理员可见；我的审批对所有登录用户开放
        if (todo && !user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("审批中心仅租户管理员可访问");
        }
        List<ApprovalOrder> orders = todo
                ? approvalService.listTodo(user.getTenantId())
                : approvalService.listMine(user.getTenantId(), user.getUserId());
        return ApiResponse.ok(orders.stream().map(o -> ApprovalView.from(o, user.getUserId())).toList());
    }

    @PostMapping("/{id}/decision")
    public ApiResponse<ApprovalView> decide(@PathVariable Long id,
                                            @RequestBody(required = false) DecisionBody body) {
        AuthUser user = AuthUserContext.require();
        // 通过/驳回：仅租户管理员可操作（不使用 @PreAuthorize，避免 AOP 抛 AccessDeniedException
        // 被 GlobalExceptionHandler 兜底为 500；BizException(403) 由 handleBiz 映射为 HTTP 403）。
        if (!user.getRoles().contains("ROLE_ADMIN")) {
            throw BizException.forbidden("仅租户管理员可通过/驳回审批");
        }
        String decision = body == null || body.decision() == null ? "APPROVE" : body.decision();
        String note = body == null ? null : body.note();
        // 审批人显示名：nickname 优先，缺失回退 username，保证一定有值
        String approverName = user.getNickname();
        if (approverName == null || approverName.isBlank()) {
            approverName = user.getUsername();
        }
        ApprovalOrder order = approvalService.decide(id, user.getTenantId(), user.getUserId(),
                approverName, decision, note);
        return ApiResponse.ok(ApprovalView.from(order, user.getUserId()));
    }

    /**
     * 同租户管理员联系信息：用户端「无权限 → 请联系管理员开通相关权限」弹窗中展示。
     * 所有登录用户可访问（不含敏感信息，仅用户名与昵称）。
     */
    @GetMapping("/admin-contacts")
    public ApiResponse<List<java.util.Map<String, Object>>> adminContacts() {
        AuthUser user = AuthUserContext.require();
        return ApiResponse.ok(approvalService.listTenantAdmins(user.getTenantId()));
    }
}
