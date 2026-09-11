package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.org.service.AuditQueryService;
import cn.aioa.org.service.DashboardService;
import cn.aioa.org.service.LeaveService;
import cn.aioa.org.service.OnboardingService;
import cn.aioa.org.service.OrgKbService;
import cn.aioa.org.service.OrgTreeService;
import cn.aioa.org.service.QuotaExpandService;
import cn.aioa.org.service.QuotaService;
import cn.aioa.org.service.ResourceGrantService;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 企业管理员端（FR-G ~ FR-K）。
 *
 * <p>机构硬边界：所有接口先解析当前登录企业管理员所属机构，
 * 任何指向其它机构的 id 一律 404（验收门禁「跨机构访问 0 成功」）。</p>
 */
@RestController
@RequestMapping("/api/v1/org")
@RequiredArgsConstructor
public class OrgAdminController {

    private final OrgGuard guard;
    private final OrgTreeService treeService;
    private final QuotaService quotaService;
    private final QuotaExpandService quotaExpandService;
    private final ResourceGrantService grantService;
    private final OrgKbService kbService;
    private final DashboardService dashboardService;
    private final AuditQueryService auditQueryService;
    private final LeaveService leaveService;
    private final ApprovalFlowService flowService;
    private final OnboardingService onboardingService;

    /** 本机构画像（企业端首页头部）。 */
    @GetMapping("/profile")
    public ApiResponse<Map<String, Object>> profile() {
        AuthUser u = guard.requireOrgUser();
        Long iid = guard.requireInstitutionId();
        Map<String, Object> out = dashboardService.orgUsage(u.getTenantId(), iid, null);
        out.put("onboarding", onboardingService.progress(u.getTenantId(), iid));
        return ApiResponse.ok(out);
    }

    // ================================================================== FR-G1 部门树

    @GetMapping("/departments")
    public ApiResponse<Map<String, Object>> departments() {
        guard.requireOrgUser();
        return ApiResponse.ok(treeService.tree(guard.requireInstitutionId()));
    }

    @PostMapping("/departments")
    public ApiResponse<Map<String, Object>> createDepartment(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.createDept(guard.requireInstitutionId(), u, body));
    }

    @PutMapping("/departments/{id}")
    public ApiResponse<Map<String, Object>> updateDepartment(@PathVariable Long id,
                                                             @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.updateDept(guard.requireInstitutionId(), id, u, body));
    }

    /** FR-G1：调整上级部门，自动迁移子树层级与路径。 */
    @PostMapping("/departments/{id}/move")
    public ApiResponse<Map<String, Object>> moveDepartment(@PathVariable Long id,
                                                           @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        Long parentId = Vals.lngObj(body, "parentId");
        return ApiResponse.ok(treeService.moveDept(guard.requireInstitutionId(), id,
                parentId == null ? 0L : parentId, u));
    }

    @DeleteMapping("/departments/{id}")
    public ApiResponse<Map<String, Object>> deleteDepartment(@PathVariable Long id) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.deleteDept(guard.requireInstitutionId(), id, u));
    }

    // ================================================================== FR-G2/G3 员工

    @GetMapping("/members")
    public ApiResponse<Map<String, Object>> members(
            @RequestParam(name = "departmentId", required = false) Long departmentId,
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "includeSubDept", defaultValue = "false") boolean includeSubDept,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "50") int size) {
        guard.requireOrgUser();
        return ApiResponse.ok(treeService.listMembers(guard.requireInstitutionId(), departmentId,
                keyword, includeSubDept, page, size));
    }

    @PostMapping("/members")
    public ApiResponse<Map<String, Object>> createMember(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.createMember(guard.requireInstitutionId(), u, body));
    }

    @PutMapping("/members/{id}")
    public ApiResponse<Map<String, Object>> updateMember(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.updateMember(guard.requireInstitutionId(), id, u, body));
    }

    @DeleteMapping("/members/{id}")
    public ApiResponse<Map<String, Object>> deleteMember(@PathVariable Long id) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.deleteMember(guard.requireInstitutionId(), id, u));
    }

    /** FR-G3：批量导入员工（逐行返回失败清单，成功率可观测）。 */
    @PostMapping("/members/import")
    public ApiResponse<Map<String, Object>> importMembers(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(treeService.importMembers(guard.requireInstitutionId(), u,
                Vals.list(body, "rows")));
    }

    // ================================================================== FR-H1/H2 机构额度

    @GetMapping("/dept-quotas")
    public ApiResponse<List<Map<String, Object>>> deptQuotas(
            @RequestParam(name = "period", required = false) String period) {
        guard.requireOrgUser();
        return ApiResponse.ok(quotaService.listDeptQuotas(guard.requireInstitutionId(), period));
    }

    /** FR-H1：机构 → 部门二次分配（Σ部门额度 ≤ 机构配额）。 */
    @PostMapping("/dept-quotas")
    public ApiResponse<Map<String, Object>> allocateDeptQuota(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(quotaService.allocateDeptQuota(u.getTenantId(),
                guard.requireInstitutionId(), u, body));
    }

    /** FR-H2：本机构配额与预警（含冻结状态）。 */
    @GetMapping("/org-quota")
    public ApiResponse<Map<String, Object>> orgQuota(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireOrgUser();
        Long iid = guard.requireInstitutionId();
        return ApiResponse.ok(quotaService.orgQuotaView(u.getTenantId(),
                quotaService.requireOrgQuota(u.getTenantId(), iid, period)));
    }

    // ================================================================== FR-H3 扩容申请

    @PostMapping("/applications/quota-expand")
    public ApiResponse<Map<String, Object>> applyQuotaExpand(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(quotaExpandService.submit(u.getTenantId(), guard.requireInstitutionId(), u, body));
    }

    // ================================================================== FR-I 机构知识库

    @GetMapping("/kb")
    public ApiResponse<Map<String, Object>> kb() {
        guard.requireOrgUser();
        return ApiResponse.ok(kbService.list(guard.requireInstitutionId()));
    }

    @GetMapping("/kb/candidates")
    public ApiResponse<List<Map<String, Object>>> kbCandidates() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(kbService.candidates(u.getTenantId()));
    }

    /** FR-I1：把共享库资料纳入机构知识库并配置可见部门。 */
    @PostMapping("/kb/attach")
    public ApiResponse<Map<String, Object>> kbAttach(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(kbService.attach(u.getTenantId(), guard.requireInstitutionId(), u, body));
    }

    /** FR-I2：条目审核。 */
    @PostMapping("/kb/{docId}/review")
    public ApiResponse<Map<String, Object>> kbReview(@PathVariable Long docId,
                                                     @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        boolean approve = body == null || !Boolean.FALSE.equals(body.get("approve"));
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(kbService.review(u.getTenantId(), guard.requireInstitutionId(), docId,
                approve, reason == null ? null : String.valueOf(reason), u));
    }

    @PostMapping("/kb/{docId}/detach")
    public ApiResponse<Map<String, Object>> kbDetach(@PathVariable Long docId) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(kbService.detach(u.getTenantId(), guard.requireInstitutionId(), docId, u));
    }

    // ================================================================== FR-J 授权资源与开通申请

    /** FR-J1：本机构已授权且启用的资源清单（成员端可见来源）。 */
    @GetMapping("/grants")
    public ApiResponse<Map<String, Object>> grants() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(grantService.institutionResources(u.getTenantId(), guard.requireInstitutionId()));
    }

    /** FR-J2：资源开通申请（走多级审批，通过后自动授权）。 */
    @PostMapping("/applications/resource-open")
    public ApiResponse<Map<String, Object>> applyResourceOpen(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        return ApiResponse.ok(grantService.submitOpenApplication(u.getTenantId(),
                guard.requireInstitutionId(), u, body));
    }

    // ================================================================== FR-K1/K2 用量与审计

    /** FR-K1：机构用量看板（部门 / 成员维度）。 */
    @GetMapping("/usage")
    public ApiResponse<Map<String, Object>> usage(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(dashboardService.orgUsage(u.getTenantId(), guard.requireInstitutionId(), period));
    }

    /** FR-K2：机构审计（强制机构硬边界）。 */
    @GetMapping("/audit")
    public ApiResponse<Map<String, Object>> audit(
            @RequestParam(name = "limit", defaultValue = "100") int limit) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(auditQueryService.orgAudit(u.getTenantId(), guard.requireInstitutionId(), limit));
    }

    // ================================================================== 请假与审批（企业端视角）

    @GetMapping("/leave/requests")
    public ApiResponse<List<Map<String, Object>>> leaveRequests(
            @RequestParam(name = "status", required = false) String status) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.institutionRequests(u.getTenantId(),
                guard.requireInstitutionId(), status));
    }

    @GetMapping("/leave/balances")
    public ApiResponse<List<Map<String, Object>>> leaveBalances(
            @RequestParam(name = "userId") Long userId,
            @RequestParam(name = "year", required = false) Integer year) {
        AuthUser u = guard.requireOrgUser();
        // 机构硬边界：只能查本机构成员的余额
        Long iid = guard.requireInstitutionId();
        OrgMember m = guard.memberOf(iid, userId);
        if (m == null) {
            throw cn.aioa.common.exception.BizException.notFound("该员工不属于本机构：" + userId);
        }
        return ApiResponse.ok(leaveService.balance(u.getTenantId(), iid, userId, year));
    }

    /** FR-H2：企业管理员调整本机构成员的假期额度。 */
    @PostMapping("/leave/balances")
    public ApiResponse<Map<String, Object>> upsertLeaveBalance(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgAdmin();
        Long iid = guard.requireInstitutionId();
        Long userId = Vals.lngObj(body, "userId");
        if (userId == null || guard.memberOf(iid, userId) == null) {
            throw cn.aioa.common.exception.BizException.notFound("该员工不属于本机构");
        }
        return ApiResponse.ok(leaveService.upsertBalance(u.getTenantId(), iid, u, body));
    }

    @GetMapping("/approver-candidates")
    public ApiResponse<List<OrgMember>> approverCandidates() {
        guard.requireOrgAdmin();
        return ApiResponse.ok(flowService.approverCandidates(guard.requireInstitutionId()));
    }
}
