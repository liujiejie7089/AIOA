package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.org.service.AuditQueryService;
import cn.aioa.org.service.DashboardService;
import cn.aioa.org.service.DeptDeleteService;
import cn.aioa.org.service.InstitutionDeleteService;
import cn.aioa.org.service.LeaveService;
import cn.aioa.org.service.MemberAccountService;
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
    /** V67 / docs/38 批次 C：员工 ↔ 账号（多对多）的读写入口。 */
    private final MemberAccountService memberAccountService;
    private final InstitutionDeleteService institutionDeleteService;
    /** 部门删除（级联前置校验 + 上一级审核）。 */
    private final DeptDeleteService deptDeleteService;

    /**
     * V67：本租户的账号清单 —— 「给员工绑定账号」的候选，并显式标注**虚拟账号**
     * （没有绑定任何员工的账号，即规格里的「虚拟管理员账号」）。
     */
    @GetMapping("/accounts")
    public ApiResponse<List<Map<String, Object>>> accounts(
            @RequestParam(name = "keyword", required = false) String keyword) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(memberAccountService.candidates(guard.resolveRequestTenant(u), keyword));
    }

    /** 本机构画像（企业端首页头部）。 */
    @GetMapping("/profile")
    public ApiResponse<Map<String, Object>> profile() {
        AuthUser u = guard.requireOrgUser();
        Long iid = guard.requireInstitutionId();
        Map<String, Object> out = dashboardService.orgUsage(u.getTenantId(), iid, null);
        out.put("onboarding", onboardingService.progress(u.getTenantId(), iid));
        return ApiResponse.ok(out);
    }

    // ================================================================== 机构作用域

    /**
     * 当前账号可查看的机构清单 + 写入能力，供前端渲染机构选择器与按钮显隐。
     *
     * <p>机构成员只返回自己那一家（选择器自动隐藏）；租户管理员返回本租户全部启用机构；
     * 平台管理员返回全局全部启用机构（只读运维视角）。</p>
     */
    @GetMapping("/institutions")
    public ApiResponse<Map<String, Object>> institutions() {
        guard.requireOrgUser();
        return ApiResponse.ok(guard.selectableInstitutions());
    }

    /**
     * 申请删除机构（需求：级联前置校验 + 上一级审核）。
     *
     * <p><b>为什么没有「直接删除机构」的 DELETE 端点</b>：需求要求「任何一层级的首次删除操作
     * 都需要经过上一级审核后方可执行」。机构的上一级是租户管理员，故这里只能<b>申请</b>；
     * 批准后由 {@link InstitutionDeleteService#onApproved} 执行真正的删除。
     * 若为了「好用」额外开放一个直接删除端点，这个审核闸门就形同虚设。</p>
     *
     * <p>前置条件：该机构下无部门、无员工。不满足时 400，且文案说明<b>停在哪一级</b>。</p>
     */
    @PostMapping("/institutions/{id}/delete-request")
    public ApiResponse<Map<String, Object>> requestInstitutionDelete(
            @PathVariable Long id,
            @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(institutionDeleteService.apply(id,
                reason == null ? null : String.valueOf(reason), u));
    }

    // ================================================================== FR-G1 部门树

    @GetMapping("/departments")
    public ApiResponse<Map<String, Object>> departments(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        guard.requireOrgUser();
        return ApiResponse.ok(treeService.tree(guard.requireInstitutionId(institutionId)));
    }

    @PostMapping("/departments")
    public ApiResponse<Map<String, Object>> createDepartment(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.createDept(guard.requireInstitutionId(institutionId), u, body));
    }

    @PutMapping("/departments/{id}")
    public ApiResponse<Map<String, Object>> updateDepartment(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.updateDept(guard.requireInstitutionId(institutionId), id, u, body));
    }

    /** FR-G1：调整上级部门，自动迁移子树层级与路径。 */
    @PostMapping("/departments/{id}/move")
    public ApiResponse<Map<String, Object>> moveDepartment(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        Long parentId = Vals.lngObj(body, "parentId");
        return ApiResponse.ok(treeService.moveDept(guard.requireInstitutionId(institutionId), id,
                parentId == null ? 0L : parentId, u));
    }

    /**
     * 申请删除部门（需求：级联前置校验 + 上一级审核）。
     *
     * <p><b>这里为什么把原来的 {@code DELETE /departments/{id}} 换掉、而不是并存</b>：
     * 需求原文「<b>任何</b>一层级的首次删除操作都需要经过上一级审核后方可执行」。
     * 级联前置校验（无子部门、无员工）原本就有，缺的是审核闸门。若把直删端点保留成
     * 「快捷入口」，闸门就形同虚设 —— 前端只要调用它就能绕过审核，而这类绕过不会有任何
     * 编译错误或测试变红。故：部门删除只保留「申请」，执行只发生在审批回调里。</p>
     *
     * <p>前置条件：该部门下无子部门、无员工。不满足时 400，且文案说明<b>停在哪一级</b>。</p>
     */
    @PostMapping("/departments/{id}/delete-request")
    public ApiResponse<Map<String, Object>> requestDepartmentDelete(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(deptDeleteService.apply(institutionId, id,
                reason == null ? null : String.valueOf(reason), u));
    }

    // ================================================================== FR-G2/G3 员工

    @GetMapping("/members")
    public ApiResponse<Map<String, Object>> members(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "departmentId", required = false) Long departmentId,
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "includeSubDept", defaultValue = "false") boolean includeSubDept,
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "size", defaultValue = "50") int size) {
        guard.requireOrgUser();
        return ApiResponse.ok(treeService.listMembers(guard.requireInstitutionId(institutionId), departmentId,
                keyword, includeSubDept, page, size));
    }

    @PostMapping("/members")
    public ApiResponse<Map<String, Object>> createMember(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.createMember(guard.requireInstitutionId(institutionId), u, body));
    }

    @PutMapping("/members/{id}")
    public ApiResponse<Map<String, Object>> updateMember(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.updateMember(guard.requireInstitutionId(institutionId), id, u, body));
    }

    @DeleteMapping("/members/{id}")
    public ApiResponse<Map<String, Object>> deleteMember(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.deleteMember(guard.requireInstitutionId(institutionId), id, u));
    }

    /**
     * V67 / docs/38 批次 C：给员工**追加绑定**一个用户账号（「一个员工可以有多个用户帐号」）。
     *
     * <p>不动主账号（{@code org_member.user_id}）—— 通知/审批/鉴权/机构归属都读它，
     * 追加账号只是让这个人多了登录入口。</p>
     */
    @PostMapping("/members/{id}/accounts")
    public ApiResponse<List<Map<String, Object>>> attachMemberAccount(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.attachAccount(guard.requireInstitutionId(institutionId), id, u,
                Vals.lngObj(body, "userId")));
    }

    /** V67：解绑员工的**附加**账号（主账号不可解绑 —— 员工必须保留一个主账号）。 */
    @DeleteMapping("/members/{id}/accounts/{userId}")
    public ApiResponse<List<Map<String, Object>>> detachMemberAccount(
            @PathVariable Long id,
            @PathVariable Long userId,
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.detachAccount(guard.requireInstitutionId(institutionId), id, u,
                userId));
    }

    /**
     * V67 批次 C·补（口令可知性）：重置某员工**主账号**的登录口令。
     *
     * <p>开户口令只在创建那一刻回显一次（服务端只存哈希、事后不可回读）。没有这个动作，
     * 操作员漏记口令后该账号就永久登不进去，只能"删员工重建" —— 那会连带丢掉审批 / 通知归属。</p>
     */
    @PostMapping("/members/{id}/password")
    public ApiResponse<Map<String, Object>> resetMemberPassword(
            @PathVariable Long id,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.resetMemberPassword(guard.requireInstitutionId(institutionId),
                id, u, body));
    }

    /** FR-G3：批量导入员工（逐行返回失败清单，成功率可观测）。 */
    @PostMapping("/members/import")
    public ApiResponse<Map<String, Object>> importMembers(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(treeService.importMembers(guard.requireInstitutionId(institutionId), u,
                Vals.list(body, "rows")));
    }

    // ================================================================== FR-H1/H2 机构额度

    @GetMapping("/dept-quotas")
    public ApiResponse<List<Map<String, Object>>> deptQuotas(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "period", required = false) String period) {
        guard.requireOrgUser();
        return ApiResponse.ok(quotaService.listDeptQuotas(guard.requireInstitutionId(institutionId), period));
    }

    /** FR-H1：机构 → 部门二次分配（Σ部门额度 ≤ 机构配额）。 */
    @PostMapping("/dept-quotas")
    public ApiResponse<Map<String, Object>> allocateDeptQuota(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(quotaService.allocateDeptQuota(u.getTenantId(),
                guard.requireInstitutionId(institutionId), u, body));
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
    public ApiResponse<Map<String, Object>> kb(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        guard.requireOrgUser();
        return ApiResponse.ok(kbService.list(guard.requireInstitutionId(institutionId)));
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
    public ApiResponse<Map<String, Object>> grants(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(grantService.institutionResources(u.getTenantId(),
                guard.requireInstitutionId(institutionId)));
    }

    /** FR-J2：资源开通申请（走多级审批，通过后自动授权）。 */
    @PostMapping("/applications/resource-open")
    public ApiResponse<Map<String, Object>> applyResourceOpen(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        return ApiResponse.ok(grantService.submitOpenApplication(u.getTenantId(),
                guard.requireInstitutionId(institutionId), u, body));
    }

    // ================================================================== FR-K1/K2 用量与审计

    /** FR-K1：机构用量看板（部门 / 成员维度）。 */
    @GetMapping("/usage")
    public ApiResponse<Map<String, Object>> usage(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(dashboardService.orgUsage(u.getTenantId(),
                guard.requireInstitutionId(institutionId), period));
    }

    /** FR-K2：机构审计（强制机构硬边界）。 */
    @GetMapping("/audit")
    public ApiResponse<Map<String, Object>> audit(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "limit", defaultValue = "100") int limit) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(auditQueryService.orgAudit(u.getTenantId(),
                guard.requireInstitutionId(institutionId), limit));
    }

    // ================================================================== 请假与审批（企业端视角）

    @GetMapping("/leave/requests")
    public ApiResponse<List<Map<String, Object>>> leaveRequests(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "status", required = false) String status) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.institutionRequests(u.getTenantId(),
                guard.requireInstitutionId(institutionId), status));
    }

    @GetMapping("/leave/balances")
    public ApiResponse<List<Map<String, Object>>> leaveBalances(
            @RequestParam(name = "userId") Long userId,
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "year", required = false) Integer year) {
        AuthUser u = guard.requireOrgUser();
        // 机构硬边界：只能查本机构成员的余额
        Long iid = guard.requireInstitutionId(institutionId);
        OrgMember m = guard.memberOf(iid, userId);
        if (m == null) {
            throw cn.aioa.common.exception.BizException.notFound("该员工不属于本机构：" + userId);
        }
        return ApiResponse.ok(leaveService.balance(u.getTenantId(), iid, userId, year));
    }

    /** FR-H2：企业管理员调整本机构成员的假期额度。 */
    @PostMapping("/leave/balances")
    public ApiResponse<Map<String, Object>> upsertLeaveBalance(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgWriter();
        Long iid = guard.requireInstitutionId(institutionId);
        Long userId = Vals.lngObj(body, "userId");
        if (userId == null || guard.memberOf(iid, userId) == null) {
            throw cn.aioa.common.exception.BizException.notFound("该员工不属于本机构");
        }
        return ApiResponse.ok(leaveService.upsertBalance(u.getTenantId(), iid, u, body));
    }

    @GetMapping("/approver-candidates")
    public ApiResponse<List<OrgMember>> approverCandidates(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        guard.requireOrgUser();
        return ApiResponse.ok(flowService.approverCandidates(guard.requireInstitutionId(institutionId)));
    }
}
