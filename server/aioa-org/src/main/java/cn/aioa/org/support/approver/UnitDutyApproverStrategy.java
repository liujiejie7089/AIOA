package cn.aioa.org.support.approver;

import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDuty;
import org.springframework.stereotype.Component;

/**
 * {@code UNIT_DUTY} —— 「<b>指定机构</b>的某职务」（四期，对标 O2OA 的「职务 + 组织参数」）。
 *
 * <p>节点配置：{@code {"approver_type":"UNIT_DUTY","duty_code":"ORG_LEADER"}}，
 * 可用 {@code institution_id} 显式指定机构；不写则取申请人所属机构。</p>
 *
 * <p>与 {@code DEPT_DUTY} 的分工：部门职务回答「这个人所属部门的领导是谁」，
 * 机构职务回答「这个单位的领导是谁」——后者不随申请人换部门而变，
 * 适合「单位负责人终审」这类与个人归属无关的节点。</p>
 */
@Component
public class UnitDutyApproverStrategy extends DutyApproverStrategy {

    /** 职务未指定时的默认值：机构负责人（机构维度最自然的「领导」）。 */
    private static final String DEFAULT_UNIT_DUTY = OrgDuty.ORG_LEADER;

    @Override
    public String type() {
        return ApprovalTask.TYPE_UNIT_DUTY;
    }

    @Override
    protected boolean departmentScoped() {
        return false;
    }

    @Override
    protected String requiredScope() {
        return SCOPE_ORG;
    }

    @Override
    protected String defaultDuty() {
        return DEFAULT_UNIT_DUTY;
    }
}
