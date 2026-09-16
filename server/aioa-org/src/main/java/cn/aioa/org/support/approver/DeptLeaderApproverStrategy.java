package cn.aioa.org.support.approver;

import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code DEPT_LEADER} —— 「部门负责人」，<b>先职务、后回落</b>（四期把原写在引擎里的逻辑搬进来）。
 *
 * <p>解析顺序（与改造前逐字一致，既有回归套件覆盖）：</p>
 * <ol>
 *   <li>该部门内 {@code duty_code='DEPT_PRINCIPAL'} 的成员（按 id 升序取第一个 ——
 *       多正职时结果稳定可复现）；</li>
 *   <li>回落 {@code org_department.leader_user_id}（兼容只配了该列的部门）；</li>
 *   <li>末级回落「该机构第一个有负责人的部门」—— <b>仅当</b>
 *       {@code allowCrossDeptFallback=true}（固定模板语义）时启用。</li>
 * </ol>
 *
 * <p><b>为什么「申请人的上级链」必须传 false</b>：那道链里「部门负责人」的语义是
 * 「申请人<b>本部门</b>的负责人」；跨部门兜底会让 A 部门的申请被 B 部门负责人审批，
 * 并把「本部门没配负责人」这个配置缺陷伪装成「正常一级审批」。缺位时返回空列表，
 * 由上级链顺延到机构管理员并在单据上写明缺位原因。</p>
 */
@Component
@RequiredArgsConstructor
public class DeptLeaderApproverStrategy implements ApproverStrategy {

    private final OrgMemberMapper memberMapper;
    private final OrgDepartmentMapper deptMapper;

    @Override
    public String type() {
        return ApprovalTask.TYPE_DEPT_LEADER;
    }

    @Override
    public List<Candidate> resolve(Context ctx) {
        Long deptId = ctx.departmentId();
        if (deptId != null && deptId > 0L) {
            Long byDuty = firstPrincipalOfDept(deptId);
            if (byDuty != null) {
                return List.of(new Candidate(byDuty, null, type(), OrgDuty.DEPT_PRINCIPAL));
            }
            OrgDepartment d = deptMapper.selectById(deptId);
            if (d != null && d.getLeaderUserId() != null) {
                return List.of(new Candidate(d.getLeaderUserId(), null, type(), null));
            }
        }
        if (!ctx.allowCrossDeptFallback()) {
            return List.of();
        }
        Long fallback = firstDeptLeaderOfInstitution(ctx.institutionId());
        return fallback == null ? List.of() : List.of(new Candidate(fallback, null, type(), null));
    }

    /** 兜底：该机构第一个部门负责人（按部门层级 / 排序取，保证结果确定）。 */
    private Long firstDeptLeaderOfInstitution(Long institutionId) {
        if (institutionId == null || institutionId <= 0L) {
            return null;
        }
        List<OrgDepartment> list = deptMapper.selectList(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, institutionId)
                .isNotNull(OrgDepartment::getLeaderUserId)
                .orderByAsc(OrgDepartment::getLevel)
                .orderByAsc(OrgDepartment::getSort)
                .last("limit 1"));
        return list.isEmpty() ? null : list.get(0).getLeaderUserId();
    }

    /** 部门内持「部门正职」职务的第一个成员（按 id 升序，保证多正职时结果稳定）。 */
    private Long firstPrincipalOfDept(Long departmentId) {
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getDepartmentId, departmentId)
                .eq(OrgMember::getDutyCode, OrgDuty.DEPT_PRINCIPAL)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByAsc(OrgMember::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0).getUserId();
    }
}
