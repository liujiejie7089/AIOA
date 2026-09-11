package cn.aioa.org.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.entity.ApprovalFlowDef;
import cn.aioa.org.entity.CostAllocRule;
import cn.aioa.org.entity.LeaveType;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.org.service.AuditQueryService;
import cn.aioa.org.service.CostAllocService;
import cn.aioa.org.service.DashboardService;
import cn.aioa.org.service.InstitutionService;
import cn.aioa.org.service.LeaveService;
import cn.aioa.org.service.QuotaService;
import cn.aioa.org.service.ResourceGrantService;
import cn.aioa.org.support.OrgGuard;
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
 * 租户管理员端（FR-A ~ FR-F）。
 *
 * <p>范围纪律（规格书第七章）：本端**只**提供机构/资源池/配额/分摊/授权/审计能力，
 * 不提供机构内部组织管理（部门与员工属企业端 {@link OrgAdminController}）。</p>
 */
@RestController
@RequestMapping("/api/v1/tenant")
@RequiredArgsConstructor
public class TenantAdminController {

    private final OrgGuard guard;
    private final InstitutionService institutionService;
    private final QuotaService quotaService;
    private final CostAllocService costAllocService;
    private final ResourceGrantService grantService;
    private final AuditQueryService auditQueryService;
    private final DashboardService dashboardService;
    private final LeaveService leaveService;
    private final ApprovalFlowService flowService;

    private Long tenantId(AuthUser u) {
        return u.getTenantId() == null ? 0L : u.getTenantId();
    }

    // ================================================================== FR-B 机构管理

    @GetMapping("/institutions")
    public ApiResponse<List<Map<String, Object>>> institutions(
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "status", required = false) String status,
            @RequestParam(name = "orgType", required = false) String orgType) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(institutionService.list(tenantId(u), keyword, status, orgType));
    }

    @GetMapping("/institutions/{id}")
    public ApiResponse<Map<String, Object>> institution(@PathVariable Long id) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(institutionService.detail(tenantId(u), id));
    }

    /** FR-B1：新建机构（可同时指定企业管理员，等价于入驻第 2 步）。 */
    @PostMapping("/institutions")
    public ApiResponse<Map<String, Object>> createInstitution(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(institutionService.create(u, body));
    }

    /** FR-B1：编辑机构。 */
    @PutMapping("/institutions/{id}")
    public ApiResponse<Map<String, Object>> updateInstitution(@PathVariable Long id,
                                                              @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(institutionService.update(u, id, body));
    }

    /** FR-B1 + FR-A3：停用 / 恢复 / 注销（敏感操作，前后值全量留痕）。 */
    @PostMapping("/institutions/{id}/{action}")
    public ApiResponse<Map<String, Object>> changeInstitutionStatus(@PathVariable Long id,
                                                                   @PathVariable String action,
                                                                   @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(institutionService.changeStatus(u, id, action,
                reason == null ? null : String.valueOf(reason)));
    }

    /** FR-B2：指定 / 交接企业管理员。 */
    @PostMapping("/institutions/{id}/admin")
    public ApiResponse<Map<String, Object>> assignAdmin(@PathVariable Long id,
                                                        @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(institutionService.assignAdmin(u, id, body));
    }

    // ================================================================== FR-C 资源池与配额

    @GetMapping("/resource-pool")
    public ApiResponse<Map<String, Object>> pool(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.pool(tenantId(u), period));
    }

    /** FR-C1 / FR-C4：交付或扩容租户资源池。 */
    @PostMapping("/resource-pool")
    public ApiResponse<Map<String, Object>> deliverPool(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.upsertPool(tenantId(u), u, body));
    }

    @GetMapping("/org-quotas")
    public ApiResponse<List<Map<String, Object>>> orgQuotas(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.listOrgQuotas(tenantId(u), period));
    }

    /** FR-C2：向机构分配配额（Σ机构配额 ≤ 资源池总量）。 */
    @PostMapping("/org-quotas")
    public ApiResponse<Map<String, Object>> allocateOrgQuota(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.allocateOrgQuota(tenantId(u), u, body));
    }

    /** FR-H3：按增量调整机构配额（扩容申请审批通过亦走此逻辑）。 */
    @PostMapping("/org-quotas/{institutionId}/delta")
    public ApiResponse<Map<String, Object>> adjustOrgQuotaDelta(@PathVariable Long institutionId,
                                                                @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        long delta = body.get("delta") instanceof Number n ? n.longValue() : 0L;
        Object reason = body.get("reason");
        return ApiResponse.ok(quotaService.applyOrgQuotaDelta(tenantId(u), institutionId, delta,
                reason == null ? "租户端手工调整" : String.valueOf(reason), u));
    }

    /** FR-C3：冻结机构配额（耗尽自动冻结之外的强制操作）。 */
    @PostMapping("/org-quotas/{institutionId}/freeze")
    public ApiResponse<Map<String, Object>> freezeOrgQuota(@PathVariable Long institutionId,
                                                           @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(quotaService.freezeOrgQuota(tenantId(u), institutionId, true, u,
                reason == null ? null : String.valueOf(reason)));
    }

    @PostMapping("/org-quotas/{institutionId}/unfreeze")
    public ApiResponse<Map<String, Object>> unfreezeOrgQuota(@PathVariable Long institutionId,
                                                             @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        Object reason = body == null ? null : body.get("reason");
        return ApiResponse.ok(quotaService.freezeOrgQuota(tenantId(u), institutionId, false, u,
                reason == null ? null : String.valueOf(reason)));
    }

    /** 四级配额链路总览（资源池 → 机构 → 部门）。 */
    @GetMapping("/quota-chain")
    public ApiResponse<Map<String, Object>> quotaChain(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.chain(tenantId(u), period));
    }

    /** FR-C3：配额预警清单。 */
    @GetMapping("/quota-warnings")
    public ApiResponse<Map<String, Object>> quotaWarnings(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.warnings(tenantId(u), period));
    }

    /** 配额分配流水（审计依据）。 */
    @GetMapping("/quota-logs")
    public ApiResponse<List<cn.aioa.org.entity.QuotaAllocLog>> quotaLogs(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "limit", defaultValue = "100") int limit) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(quotaService.allocLogs(tenantId(u), institutionId, limit));
    }

    // ================================================================== FR-D 费用分摊

    @GetMapping("/cost-rules")
    public ApiResponse<List<CostAllocRule>> costRules() {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.listRules(tenantId(u)));
    }

    /** FR-D1：新建分摊规则（固定比例 / 按用量 / 成本中心）。 */
    @PostMapping("/cost-rules")
    public ApiResponse<CostAllocRule> createCostRule(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.createRule(tenantId(u), u, body));
    }

    /** FR-D1：修改规则 → 生成新版本并留痕（旧版 RETIRED）。 */
    @PutMapping("/cost-rules/{id}")
    public ApiResponse<CostAllocRule> updateCostRule(@PathVariable Long id,
                                                     @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.updateRule(tenantId(u), id, u, body));
    }

    /** FR-D3：分摊试算。 */
    @PostMapping("/cost-rules/{id}/simulate")
    public ApiResponse<Map<String, Object>> simulateCostRule(@PathVariable Long id,
                                                             @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.simulate(tenantId(u), id, body));
    }

    @GetMapping("/cost-bills")
    public ApiResponse<List<Map<String, Object>>> costBills(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.listBills(tenantId(u), period));
    }

    /** FR-D2：生成分摊账单（含序时流水号与账本核对标记）。 */
    @PostMapping("/cost-bills/generate")
    public ApiResponse<Map<String, Object>> generateCostBills(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.generateBills(tenantId(u), u, body));
    }

    /** FR-D2：账单与平台账本一致率核对。 */
    @GetMapping("/cost-bills/reconcile")
    public ApiResponse<Map<String, Object>> reconcileCostBills(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(costAllocService.reconcile(tenantId(u), period));
    }

    // ================================================================== FR-E 资源授权

    @GetMapping("/grants")
    public ApiResponse<List<Map<String, Object>>> grants(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "resType", required = false) String resType) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(grantService.listGrants(tenantId(u), institutionId, resType));
    }

    /** 可授权资源目录（专家 / 技能 / 模型 / 数字员工）。 */
    @GetMapping("/grants/catalog")
    public ApiResponse<Map<String, Object>> grantCatalog() {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(grantService.catalog(tenantId(u)));
    }

    /** FR-E1/E2：按机构授权（可携带计费倍率等差异化参数）。 */
    @PostMapping("/grants")
    public ApiResponse<Map<String, Object>> grant(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(grantService.grant(tenantId(u), u, body));
    }

    @PostMapping("/grants/batch")
    public ApiResponse<Map<String, Object>> grantBatch(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(grantService.batchGrant(tenantId(u), u, body));
    }

    @PostMapping("/grants/{id}/toggle")
    public ApiResponse<Map<String, Object>> toggleGrant(@PathVariable Long id,
                                                        @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        boolean enabled = body == null || !Boolean.FALSE.equals(body.get("enabled"));
        return ApiResponse.ok(grantService.setEnabled(tenantId(u), id, enabled, u));
    }

    @DeleteMapping("/grants/{id}")
    public ApiResponse<Map<String, Object>> revokeGrant(@PathVariable Long id) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(grantService.revoke(tenantId(u), id, u));
    }

    // ================================================================== FR-F 监控与审计

    /** FR-F1：跨机构用量总览。 */
    @GetMapping("/overview")
    public ApiResponse<Map<String, Object>> overview(
            @RequestParam(name = "period", required = false) String period) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(dashboardService.tenantOverview(tenantId(u), period));
    }

    /** FR-F2：租户级审计（可见全部机构）。 */
    @GetMapping("/audit")
    public ApiResponse<Map<String, Object>> audit(
            @RequestParam(name = "institutionId", required = false) Long institutionId,
            @RequestParam(name = "limit", defaultValue = "100") int limit) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(auditQueryService.tenantAudit(tenantId(u), institutionId, limit));
    }

    /** 审计链完整性校验。 */
    @GetMapping("/audit/verify")
    public ApiResponse<Map<String, Object>> verifyAudit() {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(auditQueryService.verify(tenantId(u)));
    }

    // ================================================================== 租户级配置（假种 / 审批流）

    @GetMapping("/leave-types")
    public ApiResponse<List<LeaveType>> leaveTypes() {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(leaveService.listTypes(tenantId(u)));
    }

    @PostMapping("/leave-types")
    public ApiResponse<LeaveType> saveLeaveType(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(leaveService.saveType(tenantId(u), u, body));
    }

    @GetMapping("/approval-flow-defs")
    public ApiResponse<List<ApprovalFlowDef>> flowDefs(
            @RequestParam(name = "institutionId", required = false) Long institutionId) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(flowService.listDefs(tenantId(u), institutionId));
    }

    @PostMapping("/approval-flow-defs")
    public ApiResponse<ApprovalFlowDef> saveFlowDef(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireTenantAdmin();
        return ApiResponse.ok(flowService.saveDef(tenantId(u), u, body));
    }
}
