package cn.aioa.chat.tool;

import cn.aioa.bridge.service.ToolInvocationService;
import cn.aioa.org.support.ApprovalCallback;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 工具调用审批的终态回调：把审批结果接回桥接层的挂起调用。
 *
 * <p>这是 HITL 闭环的后半段 —— {@link BridgeToolApprovalGateway} 负责「提交审批并挂起」，
 * 本类负责「批完了把挂起的那次调用接着跑完」。两者都不需要对方知道自己的存在，
 * 只通过 {@code aioa-bridge} 与 {@code aioa-org} 的既有扩展点通信。</p>
 *
 * <p><b>驳回也要处理</b>：驳回时把挂起行标记为 {@code APPROVAL_REJECTED}。
 * 若不处理，那一行会永远停在 {@code PENDING_APPROVAL}，
 * 事后排查时会看起来像「还在等审批」。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ToolInvocationApprovalCallback implements ApprovalCallback {

    private final ToolInvocationService toolInvocationService;

    @Override
    public String bizType() {
        return BridgeToolApprovalGateway.BIZ_TYPE;
    }

    @Override
    public void onApproved(Map<String, Object> order) {
        String approvalId = orderId(order);
        if (approvalId == null) {
            log.warn("工具调用审批通过回调缺少单据 id，已跳过恢复执行：{}", order);
            return;
        }
        try {
            Map<String, Object> out = toolInvocationService.resume(approvalId);
            log.info("工具调用审批通过，恢复执行结果：orderId={}, result={}", approvalId, out);
        } catch (RuntimeException e) {
            // 不让恢复执行的异常冒泡回审批事务：审批结论已经成立，
            // 回滚审批只会让用户看到「通过了但状态没变」这种更糟的结果。
            log.error("审批通过后恢复工具调用失败：orderId={}", approvalId, e);
        }
    }

    @Override
    public void onRejected(Map<String, Object> order) {
        String approvalId = orderId(order);
        if (approvalId == null) {
            return;
        }
        try {
            Map<String, Object> out = toolInvocationService.abort(approvalId, "审批未通过");
            log.info("工具调用审批驳回，挂起调用已终止：orderId={}, result={}", approvalId, out);
        } catch (RuntimeException e) {
            log.error("审批驳回后终止工具调用失败：orderId={}", approvalId, e);
        }
    }

    private static String orderId(Map<String, Object> order) {
        if (order == null) {
            return null;
        }
        Object id = order.get("id");
        if (id == null) {
            id = order.get("orderId");
        }
        return id == null ? null : String.valueOf(id);
    }
}
