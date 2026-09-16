package cn.aioa.org.support.approver;

import cn.aioa.org.entity.ApprovalTask;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.approver.ApproverStrategy.Candidate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/**
 * 固定口径策略族的装配（四期）。
 *
 * <p>这几种类型的求值口径都是「一个确定的来源、最多一个人」，没有可参数化的空间，
 * 因此不各写一个类，而以 Bean 的形式声明 —— 类型 → 口径 的映射集中在一处，
 * 新增口径仍是「加一个 Bean」，主流程与既有策略均不受影响。</p>
 *
 * <p><b>注意 ORG_ADMIN 的口径</b>：取的是 {@code org_institution.admin_user_id}
 * （机构记录上指定的企业管理员），而不是「持有 ROLE_ORG_ADMIN 角色的第一个人」。
 * 二者在有多个企业管理员时结果不同；既有回归套件锁定的是前者，不要改。</p>
 */
@Configuration
public class ApproverStrategyConfig {

    /** 把类型与求值函数绑成一个策略 Bean。 */
    private static ApproverStrategy fixed(String type,
                                          java.util.function.Function<ApproverStrategy.Context,
                                                  List<ApproverStrategy.Candidate>> fn) {
        return new ApproverStrategy() {
            @Override
            public String type() {
                return type;
            }

            @Override
            public List<Candidate> resolve(Context ctx) {
                return fn.apply(ctx);
            }
        };
    }

    /** 企业管理员：机构记录上指定的 admin_user_id。 */
    @Bean
    public ApproverStrategy orgAdminApproverStrategy(OrgInstitutionMapper institutionMapper) {
        return fixed(ApprovalTask.TYPE_ORG_ADMIN, ctx -> {
            Long instId = ctx.institutionId();
            if (instId == null || instId <= 0L) {
                return List.of();
            }
            OrgInstitution inst = institutionMapper.selectById(instId);
            if (inst == null || inst.getAdminUserId() == null) {
                return List.of();
            }
            return List.of(new Candidate(inst.getAdminUserId(), null, ApprovalTask.TYPE_ORG_ADMIN, null));
        });
    }

    /** 租户管理员：本租户内第一个持有 ROLE_TENANT_ADMIN 的账号。 */
    @Bean
    public ApproverStrategy tenantAdminApproverStrategy(OrgStatMapper statMapper) {
        return fixed(ApprovalTask.TYPE_TENANT_ADMIN, ctx -> {
            Long id = statMapper.selectFirstUserIdOfRole(
                    ctx.tenantId() == null ? 0L : ctx.tenantId(), OrgGuard.ROLE_TENANT_ADMIN);
            return id == null ? List.of()
                    : List.of(new Candidate(id, null, ApprovalTask.TYPE_TENANT_ADMIN, null));
        });
    }

    /** 平台管理员：租户 0 下第一个持有 ROLE_ADMIN 的账号（租户管理员之上的唯一终审）。 */
    @Bean
    public ApproverStrategy platformAdminApproverStrategy(OrgStatMapper statMapper) {
        return fixed(ApprovalTask.TYPE_PLATFORM_ADMIN, ctx -> {
            Long id = statMapper.selectFirstUserIdOfRole(0L, OrgGuard.ROLE_ADMIN);
            return id == null ? List.of()
                    : List.of(new Candidate(id, null, ApprovalTask.TYPE_PLATFORM_ADMIN, null));
        });
    }

    /**
     * 指定审批人：step 里写死的 {@code approver_id} 优先，
     * 其次用提交请求携带的人选（如「由发起人指定会签人」的场景）。
     */
    @Bean
    public ApproverStrategy specificApproverStrategy() {
        return fixed(ApprovalTask.TYPE_SPECIFIC, ctx -> {
            Long id = ctx.stepApproverId() != null ? ctx.stepApproverId() : ctx.specificApproverId();
            return id == null ? List.of()
                    : List.of(new Candidate(id, null, ApprovalTask.TYPE_SPECIFIC, null));
        });
    }
}
