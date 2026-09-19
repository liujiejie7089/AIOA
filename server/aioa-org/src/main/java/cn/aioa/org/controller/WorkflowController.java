package cn.aioa.org.controller;

import cn.aioa.common.exception.BizException;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.entity.LeaveRequest;
import cn.aioa.org.mapper.OrgStatMapper;
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

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
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
    private final OrgStatMapper statMapper;

    // ================================================================== 审批

    /**
     * 待办计数 —— 管理端菜单红点的唯一数据源。
     *
     * <p>与 {@code /workflow/tasks?scope=todo} <b>同口径</b>（见
     * {@code OrgStatMapper.countMyTodoTasks} 的四个条件），只是不下发明细：
     * 红点会被每 60 秒轮询一次，回整棵待办树（含每单 timeline）代价过高。</p>
     *
     * <p>返回 {@code todo} = 待我处理（点亮红点），{@code mine} = 我发起且仍在途，
     * {@code cc} = 抄送我的（知会 / 待阅，<b>不点亮待办红点</b> —— 它不阻塞流转，
     * 单独一档避免与「要我动手」混淆）。</p>
     */
    @GetMapping("/workflow/tasks/summary")
    public ApiResponse<Map<String, Object>> taskSummary() {
        AuthUser u = guard.requireApprover();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("todo", statMapper.countMyTodoTasks(u.getUserId()));
        out.put("mine", statMapper.countMyPendingOrders(u.getUserId()));
        // cc = 抄送我的**总条数**（一期语义，硬约束：不得因已读而减少）；
        // ccUnread = 未读知会数（三期 C-06，随标记已读递减）。
        out.put("cc", statMapper.countMyCcTasks(u.getUserId()));
        out.put("ccUnread", statMapper.countMyUnreadCcTasks(u.getUserId()));
        out.put("generatedAt", LocalDateTime.now().toString());
        return ApiResponse.ok(out);
    }

    /** 待我审批（scope=todo 默认）、我发起的（scope=mine）或抄送我的（scope=cc）。 */
    @GetMapping("/workflow/tasks")
    public ApiResponse<List<Map<String, Object>>> tasks(
            @RequestParam(name = "scope", defaultValue = "todo") String scope) {
        AuthUser u = guard.requireApprover();
        if ("mine".equalsIgnoreCase(scope)) {
            return ApiResponse.ok(flowService.mine(u));
        }
        if ("cc".equalsIgnoreCase(scope)) {
            return ApiResponse.ok(flowService.cc(u));
        }
        return ApiResponse.ok(flowService.todo(u));
    }

    /**
     * 我发起的审批（含请假 / 额度扩容 / 成果 / 公文，带流转路径）。
     *
     * <p>与 {@code /workflow/tasks?scope=mine} 的区别：本入口只要求「已登录」，
     * 不要求审批人角色 —— 任何员工都要能查看自己提交的申请进度，这是自助能力，
     * 不该被审批人角色门槛挡住。</p>
     */
    @GetMapping("/workflow/mine")
    public ApiResponse<List<Map<String, Object>>> myApplications() {
        return ApiResponse.ok(flowService.mine(cn.aioa.security.AuthUserContext.require()));
    }

    /**
     * 「本部门名义发起的申请」（E-10）—— 部门成员的只读视角。
     *
     * <p>只要求「已登录」：查看本部门提过什么是成员的自助能力，不该被审批人角色挡住。
     * 无部门归属的账号（平台 / 租户管理员）返回空列表而非 403 —— 那是「这个视角对你
     * 没有内容」，不是越权。</p>
     *
     * <p>为什么单开端点而不并进 {@code /workflow/mine}：后者与「我的数据 · 我的申请」
     * 统计口径同源（既有套件有一致性断言），混入部门单据会让统计数字与实际含义脱节。</p>
     */
    @GetMapping("/workflow/dept-subject")
    public ApiResponse<List<Map<String, Object>>> deptSubjectOrders() {
        return ApiResponse.ok(flowService.deptSubjectOrders(cn.aioa.security.AuthUserContext.require()));
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

    // ================================================================== 六期：加签 / 子流程（V60）

    /**
     * 加签：审批过程中临时插入一个审批人。
     *
     * <p>body：{@code {type: "BEFORE"|"AFTER", userId: 123, reason: "…"}}。
     * BEFORE = 加签人先批（前加签）；AFTER = 当前人批完再交给加签人（后加签）。</p>
     */
    @PostMapping("/workflow/tasks/{id}/add-sign")
    public ApiResponse<Map<String, Object>> addSign(@PathVariable Long id,
                                                    @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireApprover();
        Map<String, Object> b = body == null ? Map.of() : body;
        Long userId = b.get("userId") instanceof Number n ? n.longValue() : null;
        String type = b.get("type") == null ? "AFTER" : String.valueOf(b.get("type"));
        String reason = b.get("reason") == null ? null : String.valueOf(b.get("reason"));
        return ApiResponse.ok(flowService.addSign(id, u, type, userId, reason));
    }

    /**
     * 发起子流程：由当前节点派生一张子单据，父节点等子单据出结论后自动推进。
     *
     * <p>body：{@code {bizType, title, content, approverId?}}。</p>
     */
    @PostMapping("/workflow/tasks/{id}/sub-flow")
    public ApiResponse<Map<String, Object>> startSubFlow(@PathVariable Long id,
                                                         @RequestBody Map<String, Object> body) {
        AuthUser u = guard.requireApprover();
        Map<String, Object> b = body == null ? Map.of() : body;
        Long approverId = b.get("approverId") instanceof Number n ? n.longValue() : null;
        return ApiResponse.ok(flowService.startSubFlow(id, u,
                new ApprovalFlowService.SubFlowReq(
                        b.get("bizType") == null ? null : String.valueOf(b.get("bizType")),
                        b.get("title") == null ? null : String.valueOf(b.get("title")),
                        b.get("content") == null ? null : String.valueOf(b.get("content")),
                        approverId)));
    }

    // ================================================================== 六期：流程模板版本（V60）

    /** 某流程定义的全部版本快照（含各版步骤内容）。 */
    @GetMapping("/workflow/defs/{id}/versions")
    public ApiResponse<List<Map<String, Object>>> defVersions(@PathVariable Long id) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(flowService.listDefVersions(id, u.getTenantId()));
    }

    /**
     * 对比同一流程定义的两个版本。
     *
     * @return {@code {added, removed, changed, summary}}；按节点 seq 对齐，
     *         而不是按下标 —— 否则「中间插了一级」会把后面所有节点都报成变更。
     */
    @GetMapping("/workflow/defs/{id}/versions/diff")
    public ApiResponse<Map<String, Object>> diffDefVersions(@PathVariable Long id,
                                                            @RequestParam int from,
                                                            @RequestParam int to) {
        AuthUser u = guard.requireOrgUser();
        return ApiResponse.ok(flowService.diffDefVersions(id, u.getTenantId(), from, to));
    }

    /**
     * 标记知会（抄送）条目为已读 —— 三期 C-04。
     *
     * <p>幂等：重复调用成功且 {@code readAt} 不倒退；非本人任务 404（不泄露存在性）；
     * {@code task_role='APPROVE'} 的审批任务返回业务错误。点开知会详情即调用本接口，
     * 并联动置该单推给本人的站内通知已读（C-09）。</p>
     */
    @PostMapping("/workflow/cc/{taskId}/read")
    public ApiResponse<Map<String, Object>> markCcRead(@PathVariable Long taskId) {
        AuthUser u = guard.requireApprover();
        return ApiResponse.ok(flowService.markCcRead(taskId, u));
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
