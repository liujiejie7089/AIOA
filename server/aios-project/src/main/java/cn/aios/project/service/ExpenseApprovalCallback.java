package cn.aios.project.service;

import cn.aios.org.support.ApprovalCallback;
import cn.aios.project.entity.PmExpense;
import cn.aios.project.mapper.PmExpenseMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 费用报销审批回调（docs/57 阶段一 A3，配套 V91）。
 *
 * <p>此前报销**完全没有审批**：{@code PmExpenseService} 只有 list / create / reverse，
 * 钱直接入账，而 43 个模块里 {@code expense_form} 表单和 EXPENSE 审批流都已存在 ——
 * 缺的就是「审批终态 → 回写业务表」这最后一段。本类把它接上。</p>
 *
 * <p>驳回后可重新提交（{@code PmExpenseService.resubmit}）：驳回只改状态，
 * 不删除流水，申请人改完再提即可，符合「驳回 ≠ 终止」的通用 OA 语义。</p>
 *
 * <p>注册方式：实现 {@link ApprovalCallback} 并由 Spring 托管即可，
 * {@code ApprovalFlowService} 通过 {@code ObjectProvider} 按 {@link #bizType()} 取用，
 * 不需要手工登记。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ExpenseApprovalCallback implements ApprovalCallback {

    /** 与 V89 播种的租户默认报销审批流、以及 worker_capability.approval_biz_type 一致。 */
    public static final String BIZ_TYPE = "EXPENSE";

    private final PmExpenseMapper expenseMapper;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        PmExpense e = findByOrder(order);
        if (e == null || !PmExpense.APPR_PENDING.equals(e.getApprovalStatus())) {
            return;
        }
        e.setApprovalStatus(PmExpense.APPR_APPROVED);
        e.setUpdatedAt(LocalDateTime.now());
        expenseMapper.updateById(e);
        log.info("expense approved: expenseId={} amount={} orderId={}",
                e.getId(), e.getAmount(), e.getOrderId());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onRejected(Map<String, Object> order) {
        PmExpense e = findByOrder(order);
        if (e == null || !PmExpense.APPR_PENDING.equals(e.getApprovalStatus())) {
            return;
        }
        e.setApprovalStatus(PmExpense.APPR_REJECTED);
        e.setUpdatedAt(LocalDateTime.now());
        expenseMapper.updateById(e);
        log.info("expense rejected: expenseId={} orderId={}", e.getId(), e.getOrderId());
    }

    private PmExpense findByOrder(Map<String, Object> order) {
        Object id = order.get("id");
        if (!(id instanceof Number n)) {
            return null;
        }
        List<PmExpense> rows = expenseMapper.selectList(new LambdaQueryWrapper<PmExpense>()
                .eq(PmExpense::getOrderId, n.longValue())
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }
}
