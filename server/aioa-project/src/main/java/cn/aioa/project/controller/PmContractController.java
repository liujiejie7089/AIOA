package cn.aioa.project.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.project.service.PmContractService;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 项目合同 + 收付款接口（PM 批次 4，V73）。设计依据 {@code docs/40 §6.3} + {@code docs/43 §4}。
 *
 * <p>用户关键词「合同（采购，收款）」→ {@code direction=OUT} 采购付款 / {@code direction=IN} 收款。</p>
 *
 * <p><b>BR-09 单一事实源</b>：{@code .../payments/{pid}/confirm} 确认实收/实付时，
 * 服务层会在**同一事务**内自动生成一条 {@code pm_expense} —— 调用方（前端）不需要、也不允许
 * 另行登记经费流水，否则同笔业务会被记两遍。已确认的收付款不可改/删，只能
 * {@code .../reverse}（红冲：置 REVERSED + 追加反向流水）。</p>
 *
 * <p>权限一律在 {@link PmContractService} 内判定（{@code requireVisible} + {@code requireWrite}）。</p>
 */
@RestController
@RequestMapping("/api/v1/pm")
@RequiredArgsConstructor
public class PmContractController {

    private final OrgGuard guard;
    private final PmContractService contractService;

    // ======================================================================
    // 合同
    // ======================================================================

    @GetMapping("/projects/{id}/contracts")
    public ApiResponse<Map<String, Object>> list(@PathVariable Long id,
                                                 @RequestParam(required = false) String direction) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.list(u, id, direction));
    }

    @PostMapping("/projects/{id}/contracts")
    public ApiResponse<Map<String, Object>> create(@PathVariable Long id,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.create(u, id, body));
    }

    /** 修改合同要素（已结/已终止 → 409）。 */
    @PutMapping("/projects/{id}/contracts/{contractId}")
    public ApiResponse<Map<String, Object>> update(@PathVariable Long id,
                                                    @PathVariable Long contractId,
                                                    @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.update(u, id, contractId, body));
    }

    /** 流转合同状态（已结/已终止 → 409）。 */
    @PostMapping("/projects/{id}/contracts/{contractId}/status")
    public ApiResponse<Map<String, Object>> changeStatus(@PathVariable Long id,
                                                         @PathVariable Long contractId,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        String status = body == null ? null : String.valueOf(body.getOrDefault("status", ""));
        return ApiResponse.ok(contractService.changeStatus(u, id, contractId, status));
    }

    // ======================================================================
    // 收付款明细（BR-09）
    // ======================================================================

    @GetMapping("/projects/{id}/contracts/{contractId}/payments")
    public ApiResponse<Map<String, Object>> payments(@PathVariable Long id,
                                                      @PathVariable Long contractId) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.payments(u, id, contractId));
    }

    /** 新增一期收付款计划。 */
    @PostMapping("/projects/{id}/contracts/{contractId}/payments")
    public ApiResponse<Map<String, Object>> addPayment(@PathVariable Long id,
                                                       @PathVariable Long contractId,
                                                       @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.addPayment(u, id, contractId, body));
    }

    /**
     * 确认实收/实付 —— <b>BR-09</b>：同事务内置 CONFIRMED + 自动生成一条 pm_expense。
     * 只能确认状态为 {@code PLANNED} 的期次（否则 409）。
     */
    @PostMapping("/projects/{id}/contracts/{contractId}/payments/{paymentId}/confirm")
    public ApiResponse<Map<String, Object>> confirmPayment(@PathVariable Long id,
                                                           @PathVariable Long contractId,
                                                           @PathVariable Long paymentId,
                                                           @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(contractService.confirmPayment(u, id, contractId, paymentId,
                body == null ? Map.of() : body));
    }

    /** 红冲已确认的收付款：置 REVERSED + 追加反向经费流水（只有 CONFIRMED 可红冲，否则 409）。 */
    @PostMapping("/projects/{id}/contracts/{contractId}/payments/{paymentId}/reverse")
    public ApiResponse<Map<String, Object>> reversePayment(@PathVariable Long id,
                                                            @PathVariable Long contractId,
                                                            @PathVariable Long paymentId,
                                                            @RequestBody(required = false) Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        String reason = body == null ? null : String.valueOf(body.getOrDefault("reason", ""));
        return ApiResponse.ok(contractService.reversePayment(u, id, contractId, paymentId, reason));
    }
}
