package cn.aioa.org.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.entity.LeaveRequest;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.org.service.LeaveService;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 多级审批与请假流程（升级后）。
 *
 * <p>审批流：待我审批 → 逐级通过 / 驳回 → 终审触发业务后置动作；
 * 请假：假种 → 余额 → 全量校验 → 多级审批 → 通过扣减 / 驳回释放。</p>
 */
@RestController
@RequestMapping("/api/v1")
@RequiredArgsConstructor
public class WorkflowController {

    private final OrgGuard guard;
    private final ApprovalFlowService flowService;
    private final LeaveService leaveService;

    // ================================================================== 审批

    /** 待我审批（scope=todo 默认）或我发起的（scope=mine）。 */
    @GetMapping("/workflow/tasks")
    public ApiResponse<List<Map<String, Object>>> tasks(
            @RequestParam(name = "scope", defaultValue = "todo") String scope) {
        AuthUser u = guard.requireApprover();
        if ("mine".equalsIgnoreCase(scope)) {
            return ApiResponse.ok(flowService.mine(u));
        }
        return ApiResponse.ok(flowService.todo(u));
    }

    /** 审批决策（通过 / 驳回 + 意见）。 */
    @PostMapping("/workflow/tasks/{id}/decide")
    public ApiResponse<Map<String, Object>> decide(@PathVariable Long id,
                                                   @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireApprover();
        Object decision = body == null ? null : body.get("decision");
        boolean approve = decision == null
                || "APPROVE".equalsIgnoreCase(String.valueOf(decision))
                || "APPROVED".equalsIgnoreCase(String.valueOf(decision))
                || Boolean.TRUE.equals(decision);
        Object note = body == null ? null : body.get("note");
        return ApiResponse.ok(flowService.decide(id, u, approve, note == null ? null : String.valueOf(note)));
    }

    /** 审批轨迹（按节点顺序）。 */
    @GetMapping("/workflow/orders/{orderId}/timeline")
    public ApiResponse<List<Map<String, Object>>> timeline(@PathVariable Long orderId) {
        guard.requireApprover();
        return ApiResponse.ok(flowService.timeline(orderId));
    }

    // ================================================================== 请假

    /** 假种列表（含是否需证明 / 提前天数 / 最长连续天数）。 */
    @GetMapping("/leave/types")
    public ApiResponse<List<cn.aioa.org.entity.LeaveType>> leaveTypes() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.listTypes(u.getTenantId()));
    }

    /** 我的假期余额（可用 = 额度 - 已用 - 在途）。 */
    @GetMapping("/leave/balance")
    public ApiResponse<List<Map<String, Object>>> leaveBalance(
            @RequestParam(name = "userId", required = false) Long userId,
            @RequestParam(name = "year", required = false) Integer year) {
        AuthUser u = guard.requireOrgUser();
        Long target = userId == null ? u.getUserId() : userId;
        if (!target.equals(u.getUserId()) && !OrgGuard.hasRole(u, OrgGuard.ROLE_ORG_ADMIN)
                && !OrgGuard.hasRole(u, OrgGuard.ROLE_DEPT_LEADER)) {
            throw BizException.forbidden("只能查看本人的假期余额");
        }
        Long iid = guard.requireInstitutionId();
        return ApiResponse.ok(leaveService.balance(u.getTenantId(), iid, target, year));
    }

    /** 提交请假（服务端全量校验；通过后展开多级审批并占用在途额度）。 */
    @PostMapping("/leave/requests")
    public ApiResponse<Map<String, Object>> submitLeave(@RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.submit(u, body));
    }

    /** 我的请假记录。 */
    @GetMapping("/leave/requests")
    public ApiResponse<List<Map<String, Object>>> leaveRequests() {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.myRequests(u.getTenantId(), u.getUserId()));
    }

    /** 撤销请假（释放在途额度）。 */
    @PostMapping("/leave/requests/{id}/cancel")
    public ApiResponse<Map<String, Object>> cancelLeave(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(leaveService.cancel(id, u));
    }

    /** 请假单状态常量（前端提示文案用）。 */
    @GetMapping("/leave/meta")
    public ApiResponse<Map<String, Object>> leaveMeta() {
        guard.requireOrgUser();
        return ApiResponse.ok(Map.of(
                "statuses", List.of(
                        Map.of("code", LeaveRequest.PENDING, "name", "待审批"),
                        Map.of("code", LeaveRequest.APPROVED, "name", "已通过"),
                        Map.of("code", LeaveRequest.REJECTED, "name", "已驳回"),
                        Map.of("code", LeaveRequest.CANCELED, "name", "已撤销"))));
    }
}
