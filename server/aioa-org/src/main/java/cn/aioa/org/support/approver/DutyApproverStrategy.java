package cn.aioa.org.support.approver;

import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDutyMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * 职务型审批人解析的公共实现（四期）—— 「按职务 + 所属组织动态求值处理人」。
 *
 * <p>这是对标 O2OA「Duty」的核心收益所在：流程模板只写「我要部门正职」，
 * 具体是谁由 {@code org_member.duty_code} 在<b>提交时</b>求值。于是</p>
 * <ul>
 *   <li><b>人员变动不改流程</b>：换部门负责人只改变成员职务，已配好的流程模板原样生效；</li>
 *   <li><b>模板跨部门复用</b>：一条模板自动适配全公司所有部门，不必每部门配一遍；</li>
 *   <li><b>多正职可表达</b>：返回全部持职务者（有序），由节点 mode 决定单人 / 会签 / 抢占。</li>
 * </ul>
 *
 * <p><b>安全边界</b>：所有查人动作都带 {@code tenant_id} 条件；
 * {@code UNIT_DUTY} 显式指定机构时必须校验该机构属于同一租户 ——
 * 否则一条配置就能把别的租户的人拉进自己的审批链。</p>
 *
 * <p><b>不在这里做兜底</b>：解析不到人 → 返回空列表。兜底（顺延到机构管理员 / 租户管理员）
 * 是引擎的职责，且必须写进单据的流程提示里 —— 让「本部门没设这个职务」这个配置缺陷可见，
 * 而不是把别的部门的人悄悄拉进来假装正常审批。</p>
 */
@Slf4j
public abstract class DutyApproverStrategy implements ApproverStrategy {

    /** 职务未指定时的默认值：部门正职（与改造前 DEPT_LEADER 的口径一致）。 */
    protected static final String DEFAULT_DUTY = OrgDuty.DEPT_PRINCIPAL;

    protected static final String SCOPE_DEPT = "DEPT";
    protected static final String SCOPE_ORG = "ORG";

    @Autowired
    protected OrgMemberMapper memberMapper;
    @Autowired
    protected OrgDutyMapper dutyMapper;
    @Autowired
    protected OrgInstitutionMapper institutionMapper;

    /** 目标组织维度：true = 申请人所属部门（DEPT_DUTY），false = 机构（UNIT_DUTY）。 */
    protected abstract boolean departmentScoped();

    /** 本策略要求的职务作用域（DEPT / ORG）—— 与字典里的 {@code scope} 对不上即视为配置错误。 */
    protected abstract String requiredScope();

    /** {@code duty_code} 未指定时用的默认职务：部门维度 = 部门正职，机构维度 = 机构负责人。 */
    protected String defaultDuty() {
        return DEFAULT_DUTY;
    }

    @Override
    public List<Candidate> resolve(Context ctx) {
        String code = ctx.dutyCode() == null || ctx.dutyCode().isBlank()
                ? defaultDuty() : ctx.dutyCode().trim();

        Boolean canApprove = null;
        String scope = null;
        OrgDuty duty = dutyMapper.selectOne(new LambdaQueryWrapper<OrgDuty>()
                .eq(OrgDuty::getTenantId, ctx.tenantId() == null ? 0L : ctx.tenantId())
                .eq(OrgDuty::getCode, code)
                .last("limit 1"));
        if (duty != null) {
            canApprove = duty.getCanApprove();
            scope = duty.getScope();
        } else {
            // 字典缺失（如新租户在播种器生效前提交）时按内置四职务的已知语义判断，
            // 否则一次字典缺口就会让所有职务型流程集体失效。
            canApprove = !OrgDuty.STAFF.equals(code);
            scope = OrgDuty.ORG_LEADER.equals(code) ? SCOPE_ORG : SCOPE_DEPT;
        }
        if (!Boolean.TRUE.equals(canApprove)) {
            log.warn("职务「{}」标记为不可审批（can_approve=0），节点按「解析不到」处理", code);
            return List.of();
        }
        if (scope != null && !scope.isBlank() && !requiredScope().equalsIgnoreCase(scope)) {
            // 例：DEPT_DUTY 配了 ORG_LEADER（机构级职务）。这不是「查不到人」而是配置错误，
            // 必须留下可定位的日志 —— 否则现象只是「流程莫名其妙顺延了」。
            log.warn("{}.{} 要求职务作用域 {}，但职务「{}」的作用域是 {}，按「解析不到」处理",
                    getClass().getSimpleName(), type(), requiredScope(), code, scope);
            return List.of();
        }

        if (departmentScoped()) {
            if (ctx.departmentId() == null || ctx.departmentId() <= 0L) {
                log.warn("{}：申请人未归属部门（departmentId={}），无法按部门职务求值",
                        getClass().getSimpleName(), ctx.departmentId());
                return List.of();
            }
            return membersOf(ctx.tenantId(), code, ctx.departmentId(), null);
        }

        Long instId = ctx.targetInstitutionId() != null && ctx.targetInstitutionId() > 0L
                ? ctx.targetInstitutionId() : ctx.institutionId();
        if (instId == null || instId <= 0L) {
            log.warn("{}：未指定机构且申请人无所属机构，无法按机构职务求值", getClass().getSimpleName());
            return List.of();
        }
        OrgInstitution inst = institutionMapper.selectById(instId);
        if (inst == null || !Objects.equals(inst.getTenantId(),
                ctx.tenantId() == null ? 0L : ctx.tenantId())) {
            // 跨租户机构一律按「不存在」处理：不能把别租户的人拉进本租户审批链，
            // 也不能用「解析不到」与「越权访问」的差异泄露机构是否存在。
            log.warn("{}：机构 {} 不属于租户 {}（或不存在），按「解析不到」处理",
                    getClass().getSimpleName(), instId, ctx.tenantId());
            return List.of();
        }
        return membersOf(ctx.tenantId(), code, null, instId);
    }

    /**
     * 取「持指定职务的成员」。
     *
     * @param departmentId 非空 → 限本部门（DEPT_DUTY）
     * @param institutionId 非空 → 限本机构（UNIT_DUTY）
     * @return 按成员 id 升序（结果稳定，便于断言与「谁先被指派」可复现）
     */
    private List<Candidate> membersOf(Long tenantId, String dutyCode, Long departmentId, Long institutionId) {
        LambdaQueryWrapper<OrgMember> w = new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getTenantId, tenantId == null ? 0L : tenantId)
                .eq(OrgMember::getDutyCode, dutyCode)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE);
        if (departmentId != null) {
            w.eq(OrgMember::getDepartmentId, departmentId);
        }
        if (institutionId != null) {
            w.eq(OrgMember::getInstitutionId, institutionId);
        }
        List<OrgMember> rows = memberMapper.selectList(w.orderByAsc(OrgMember::getId));
        List<Candidate> out = new ArrayList<>(rows.size());
        for (OrgMember m : rows) {
            // name 留空：由 ApproverResolver 统一填（避免策略依赖解析门面造成循环依赖）
            out.add(new Candidate(m.getUserId(), null, type(), dutyCode));
        }
        return out;
    }
}
