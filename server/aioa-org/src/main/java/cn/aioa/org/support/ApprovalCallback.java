package cn.aioa.org.support;

import java.util.Map;

/**
 * 审批终态回调：多级审批流转到终态时驱动业务后置动作。
 *
 * <p>实现方按 {@link #bizType()} 注册；{@code ApprovalFlowService} 在审批通过 / 驳回时
 * 通过 {@code ObjectProvider} 惰性取出全部实现（避免与提交方形成构造器循环依赖）。</p>
 */
public interface ApprovalCallback {

    /** 业务类型：LEAVE / QUOTA_EXPAND / RESOURCE_OPEN … */
    String bizType();

    /** 终审通过（所有节点均已通过）。 */
    void onApproved(Map<String, Object> order);

    /** 任一节点驳回，流程终止。 */
    void onRejected(Map<String, Object> order);
}
