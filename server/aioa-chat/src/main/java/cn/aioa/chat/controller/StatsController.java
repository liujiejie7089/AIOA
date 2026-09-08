package cn.aioa.chat.controller;

import cn.aioa.common.resp.ApiResponse;
import cn.aioa.chat.entity.AgentRun;
import cn.aioa.chat.mapper.AgentRunMapper;
import cn.aioa.chat.mapper.ChatConversationMapper;
import cn.aioa.resource.entity.ApprovalOrder;
import cn.aioa.resource.service.ApprovalService;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 管理端首页真实统计（替换 M1 占位数据）：
 * 待我审批 / 我的申请 / AI 会话数 / AI 运行数（含 SUCCEEDED/FAILED/RUNNING 全量）。
 */
@Tag(name = "首页统计")
@RestController
@RequestMapping("/api/v1/stats")
@RequiredArgsConstructor
public class StatsController {

    private final ApprovalService approvalService;
    private final ChatConversationMapper conversationMapper;
    private final AgentRunMapper agentRunMapper;

    @Operation(summary = "首页统计卡片")
    @GetMapping("/home")
    public ApiResponse<Map<String, Object>> home() {
        AuthUser user = AuthUserContext.require();
        long tenantId = user.getTenantId() == null ? 0L : user.getTenantId();
        List<ApprovalOrder> mine = approvalService.listMine(tenantId, user.getUserId());
        List<ApprovalOrder> todo = user.getRoles() != null && user.getRoles().contains("ROLE_ADMIN")
                ? approvalService.listTodo(tenantId) : List.of();
        Long conversations = conversationMapper.selectCount(new LambdaQueryWrapper<cn.aioa.chat.entity.ChatConversation>()
                .eq(cn.aioa.chat.entity.ChatConversation::getUserId, user.getUserId())
                .eq(cn.aioa.chat.entity.ChatConversation::getTenantId, tenantId));
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
}
