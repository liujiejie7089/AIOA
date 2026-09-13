package cn.aioa.chat.controller;

import cn.aioa.chat.entity.AgentRun;
import cn.aioa.chat.entity.ChatConversation;
import cn.aioa.chat.mapper.AgentRunMapper;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.common.resp.ApiResponse;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.service.ApprovalFlowService;
import cn.aioa.resource.entity.AgentWorker;
import cn.aioa.resource.entity.ApprovalOrder;
import cn.aioa.resource.entity.UserResult;
import cn.aioa.resource.mapper.AgentWorkerMapper;
import cn.aioa.resource.mapper.UserResultMapper;
import cn.aioa.resource.service.ApprovalService;
import cn.aioa.resource.service.BillingService;
import cn.aioa.resource.service.KbService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 统计接口。
 *
 * <p>两条口径，都要求「真实准确、来源可靠」——不在前端拼装、不预置常量：</p>
 * <ul>
 *   <li>{@code GET /api/v1/stats/home} —— 管理端首页 4 张卡（保留原有返回结构）。</li>
 *   <li>{@code GET /api/v1/stats/me}   —— 用户端「我的数据」：一次性返回本人全量真实计数，
 *       每一项都复用对应业务列表/服务的同一口径（避免同一件事在两个页面显示不同数字）。</li>
 * </ul>
 */
@Tag(name = "首页统计")
@RestController
@RequestMapping("/api/v1/stats")
@RequiredArgsConstructor
public class StatsController {

    private final ApprovalService approvalService;
    private final ApprovalFlowService approvalFlowService;
    private final OrgStatMapper orgStatMapper;
    private final ChatConversationMapper conversationMapper;
    private final AgentRunMapper agentRunMapper;
    private final UserResultMapper userResultMapper;
    private final AgentWorkerMapper agentWorkerMapper;
    private final KbService kbService;
    private final BillingService billingService;

    @Operation(summary = "管理端首页统计卡片")
    @GetMapping("/home")
    public ApiResponse<Map<String, Object>> home() {
        AuthUser user = AuthUserContext.require();
        long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        List<ApprovalOrder> mine = approvalService.listMine(tenantId, user.getUserId());
        List<ApprovalOrder> todo = isTenantLevelAdmin(user)
                ? approvalService.listTodo(tenantId) : List.of();
        Long conversations = conversationMapper.selectCount(new LambdaQueryWrapper<ChatConversation>()
                .eq(ChatConversation::getUserId, user.getUserId())
                .eq(ChatConversation::getTenantId, tenantId));
        Long runs = agentRunMapper.selectCount(new LambdaQueryWrapper<AgentRun>()
                .eq(AgentRun::getUserId, user.getUserId())
                .eq(AgentRun::getTenantId, tenantId));
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("todoApprovals", todo == null ? 0 : todo.size());
        data.put("myApprovals", mine == null ? 0 : mine.size());
        data.put("aiConversations", conversations == null ? 0 : conversations);
        data.put("aiRuns", runs == null ? 0 : runs);
        return ApiResponse.ok(data);
    }

    /**
     * 用户端「我的数据」统计：每一项都来自库表实时计数，口径与对应业务列表完全一致。
     *
     * <p>关键点：</p>
     * <ol>
     *   <li><b>待我处理</b>：多级审批引擎当前节点指派给我的待办（机构管理员/部门负责人/租户管理员）
     *       + 单级审批池（仅租户级管理员可读）。与用户端「待办」页的合并口径一致。</li>
     *   <li><b>我的申请</b>：直接对 approval_order 计数，不构建流转路径（只取数量，避免 N+1）。</li>
     *   <li><b>词元</b>：复用 {@link BillingService#current}——与 {@code GET /api/v1/quota} 同一数据源。</li>
     *   <li><b>知识库</b>：复用 {@link KbService#list}——与 {@code GET /api/v1/kb/documents} 同一口径。</li>
     *   <li>返回 {@code generatedAt}，前端据此标注统计生成时刻，避免把缓存当成实时。</li>
     * </ol>
     */
    @Operation(summary = "我的数据统计（用户端）")
    @GetMapping("/me")
    public ApiResponse<Map<String, Object>> me() {
        AuthUser user = AuthUserContext.require();
        long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        long userId = user.getUserId();

        // 1) 待我处理：多级引擎（按当前节点指派人）+ 单级池（仅租户级管理员）
        int todoFromFlow = approvalFlowService.todo(user).size();
        int todoFromLegacy = isTenantLevelAdmin(user) ? approvalService.listTodo(tenantId).size() : 0;

        // 2) 我的申请：approval_order 中发起人为本人的全部单据（含请假/扩容/成果/公文）
        List<Map<String, Object>> myOrders = orgStatMapper.selectApprovalOrdersOfUser(tenantId, userId);
        int myApplications = myOrders == null ? 0 : myOrders.size();

        // 3) 会话 / AI 运行（显式排除已删行：这两个实体没挂 @TableLogic，
        //    删除是手写 deleted_at，不过滤就会把删掉的也算进来）
        Long conversations = conversationMapper.selectCount(new LambdaQueryWrapper<ChatConversation>()
                .eq(ChatConversation::getUserId, userId)
                .eq(ChatConversation::getTenantId, tenantId)
                .isNull(ChatConversation::getDeletedAt));
        Long aiRuns = agentRunMapper.selectCount(new LambdaQueryWrapper<AgentRun>()
                .eq(AgentRun::getUserId, userId)
                .eq(AgentRun::getTenantId, tenantId)
                .isNull(AgentRun::getDeletedAt));

        // 4) 我的成果（口径同 ResultController#list）
        Long results = userResultMapper.selectCount(new LambdaQueryWrapper<UserResult>()
                .eq(UserResult::getTenantId, tenantId)
                .eq(UserResult::getUserId, userId));

        // 5) 我创建的数字员工（口径：created_by = 本人；不含他人创建但对我可见的）
        Long myWorkers = agentWorkerMapper.selectCount(new LambdaQueryWrapper<AgentWorker>()
                .eq(AgentWorker::getTenantId, tenantId)
                .eq(AgentWorker::getCreatedBy, userId));

        // 6) 我的知识库文档（口径同 KbController#list 的个人视角）
        int kbDocs = kbService.list(tenantId, userId).size();

        // 7) 本月词元额度（口径同 BillingController#quota，同源不重算）
        BillingService.QuotaView quota = billingService.current(tenantId, userId);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("todoApprovals", todoFromFlow + todoFromLegacy);
        data.put("todoFromFlow", todoFromFlow);
        data.put("todoFromLegacy", todoFromLegacy);
        data.put("myApplications", myApplications);
        data.put("conversations", conversations == null ? 0L : conversations);
        data.put("aiRuns", aiRuns == null ? 0L : aiRuns);
        data.put("results", results == null ? 0L : results);
        data.put("myWorkers", myWorkers == null ? 0L : myWorkers);
        data.put("kbDocs", kbDocs);
        data.put("quota", quota.quota());
        data.put("quotaUsed", quota.used());
        data.put("quotaFree", quota.free());
        data.put("quotaLeft", quota.left());
        data.put("generatedAt", LocalDateTime.now().toString());
        return ApiResponse.ok(data);
    }

    /** 与 ApprovalController 的 403 口径保持一致：单级审批池只有租户级管理员可读。 */
    private static boolean isTenantLevelAdmin(AuthUser user) {
        return user.getRoles() != null
                && (user.getRoles().contains("ROLE_ADMIN") || user.getRoles().contains("ROLE_TENANT_ADMIN"));
    }
}
