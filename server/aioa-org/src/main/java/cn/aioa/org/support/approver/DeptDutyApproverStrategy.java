package cn.aioa.org.support.approver;

import cn.aioa.org.entity.ApprovalTask;
import org.springframework.stereotype.Component;

/**
 * {@code DEPT_DUTY} —— 「申请人<b>所在部门</b>的某职务」（四期）。
 *
 * <p>节点配置：{@code {"approver_type":"DEPT_DUTY","duty_code":"DEPT_PRINCIPAL"}}；
 * {@code duty_code} 缺省 = 部门正职（与改造前 {@code DEPT_LEADER} 同口径）。</p>
 *
 * <p><b>与 DEPT_LEADER 的关系</b>：DEPT_LEADER 是「部门正职」这一个具体职务的历史别名；
 * DEPT_DUTY 把职务作为参数。保留了 DEPT_LEADER 是为了向后兼容既有流程定义，
 * 但它已改为「先职务、后回落 leader_user_id」——两者在正职口径下结果一致。</p>
 */
@Component
public class DeptDutyApproverStrategy extends DutyApproverStrategy {

    @Override
    public String type() {
        return ApprovalTask.TYPE_DEPT_DUTY;
    }

    @Override
    protected boolean departmentScoped() {
        return true;
    }

    @Override
    protected String requiredScope() {
        return SCOPE_DEPT;
    }
}
