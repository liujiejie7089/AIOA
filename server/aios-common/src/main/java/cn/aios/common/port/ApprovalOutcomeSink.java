package cn.aios.common.port;

/**
 * 审批终态回调端口：审批单进入终态（APPROVED / REJECTED）时，表单域据此把
 * {@code form_submission} 落成一致的终态（docs/52 P4 铁律 2：终态失败必须回写，不可静默成功）。
 *
 * <p>本接口定义在 {@code aios-common}，由表单域（{@code aios-resource} 的
 * {@code FormSubmissionService}）实现，审批引擎（{@code aios-org} 的
 * {@code ApprovalFlowService}）通过 {@code ObjectProvider} 惰性取出。这样审批引擎
 * 不反向依赖表单域，无实现方时 {@code getIfAvailable()} 为 null，直接跳过，绝不报错。</p>
 */
public interface ApprovalOutcomeSink {

    /**
     * 审批单进入终态后的回调。
     *
     * @param approvalOrderId 审批单 id（即 {@code form_submission.approval_order_id}）
     * @param decision        终态判定，取值 {@code APPROVED} 或 {@code REJECTED}
     */
    void onApprovalFinished(Long approvalOrderId, String decision);
}
