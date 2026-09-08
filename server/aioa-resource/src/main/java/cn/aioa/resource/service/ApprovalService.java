package cn.aioa.resource.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.resource.entity.ApprovalOrder;
import cn.aioa.resource.mapper.ApprovalOrderMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 审批工作流（FR-D6）：
 *   · submit   —— 用户端「提交审批」落 PENDING 单，并通知租户管理员
 *   · listMine —— 「我的审批」：我发起的
 *   · listTodo —— 审批中心待办：同租户下 PENDING（M1 租户内可见可审）
 *   · decide  —— 通过 / 驳回，幂等（已决单据不可重复处理），并把结果通知发起人
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalService {

    private final ApprovalOrderMapper approvalMapper;
    private final ActivityLogService activityLogService;
    private final NotificationService notificationService;

    public record SubmitReq(String bizType, String title, String content, String runId, Long conversationId) {
    }

    public ApprovalOrder submit(Long tenantId, Long userId, String nickname,
                                 String bizType, String title, String content, String runId, Long conversationId) {
        ApprovalOrder order = new ApprovalOrder();
        order.setTenantId(tenantId == null ? 0L : tenantId);
        order.setUserId(userId == null ? 0L : userId);
        order.setBizType(bizType == null || bizType.isBlank() ? "对外发文" : bizType);
        order.setTitle(title);
        order.setContent(content);
        order.setRunId(runId);
        order.setConversationId(conversationId);
        order.setStatus(ApprovalOrder.STATUS_PENDING);
        order.setCreatedAt(LocalDateTime.now());
        order.setCreatedBy(userId);
        approvalMapper.insert(order);
        activityLogService.record(tenantId, userId, "提交审批（" + order.getBizType() + "）", "wait", "待审批");
        // 站内通知：租户全部管理员（排除提交人自己）
        notificationService.notifyAdmins(order.getTenantId(), order.getUserId(),
                "新审批待处理",
                (nickname == null || nickname.isBlank() ? "有用户" : nickname)
                        + " 提交了审批单《" + (order.getTitle() == null ? order.getBizType() : order.getTitle())
                        + "》，待你审批",
                order.getId());
        return order;
    }

    public List<ApprovalOrder> listMine(Long tenantId, Long userId) {
        return approvalMapper.selectList(new LambdaQueryWrapper<ApprovalOrder>()
                .in(ApprovalOrder::getTenantId, tenantId == null ? 0L : tenantId)
                .in(ApprovalOrder::getUserId, BillingService.scopeUsers(userId))
                .orderByDesc(ApprovalOrder::getCreatedAt));
    }

    public List<ApprovalOrder> listTodo(Long tenantId) {
        return approvalMapper.selectList(new LambdaQueryWrapper<ApprovalOrder>()
                .eq(ApprovalOrder::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(ApprovalOrder::getStatus, ApprovalOrder.STATUS_PENDING)
                .orderByDesc(ApprovalOrder::getCreatedAt));
    }

    @Transactional(rollbackFor = Exception.class)
    public ApprovalOrder decide(Long id, Long tenantId, Long userId, String nickname,
                                 String decision, String note) {
        ApprovalOrder order = approvalMapper.selectById(id);
        if (order == null) {
            throw BizException.notFound("审批单不存在：" + id);
        }
        if (order.getTenantId() != null && tenantId != null && !order.getTenantId().equals(tenantId)) {
            throw BizException.forbidden("无权审批其他租户的审批单");
        }
        if (!ApprovalOrder.STATUS_PENDING.equals(order.getStatus())) {
            throw BizException.badRequest("该审批单已处理（" + order.getStatus() + "），不可重复审批");
        }
        boolean approve = "APPROVE".equalsIgnoreCase(decision) || "APPROVED".equalsIgnoreCase(decision);
        order.setStatus(approve ? ApprovalOrder.STATUS_APPROVED : ApprovalOrder.STATUS_REJECTED);
        order.setApprover(nickname);
        order.setDecisionNote(note);
        order.setDecidedAt(LocalDateTime.now());
        order.setUpdatedAt(LocalDateTime.now());
        approvalMapper.updateById(order);

        String logLabel = approve ? "已通过" : "已驳回";
        activityLogService.record(tenantId, userId, "审批" + order.getBizType() + "（" + order.getTitle() + "）",
                approve ? "ok" : "fail", logLabel);
        // 站内通知：结果 + 审批意见 发给审批单发起人（管理员审自己的单则不通知）
        notificationService.notifyUser(order.getTenantId(), order.getUserId(), userId,
                cn.aioa.resource.entity.Notification.TYPE_APPROVAL,
                approve ? "审批已通过" : "审批被驳回",
                "你的审批单《" + (order.getTitle() == null ? order.getBizType() : order.getTitle())
                        + "》" + logLabel
                        + (note == null || note.isBlank() ? "" : "，意见：" + note),
                order.getId());
        return order;
    }
}
