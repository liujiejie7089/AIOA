package cn.aioa.org.support;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 权限与机构硬边界守卫（规格书第七章「范围纪律」的代码落地）。
 *
 * <p>纪律：租户管理员端管资源与规则，企业管理员端管组织与执行；
 * 企业管理员跨机构访问必须为 0 成功 —— 越界统一返回 404（不泄露存在性）。</p>
 */
@Component
@RequiredArgsConstructor
public class OrgGuard {

    public static final String ROLE_ADMIN = "ROLE_ADMIN";
    public static final String ROLE_TENANT_ADMIN = "ROLE_TENANT_ADMIN";
    public static final String ROLE_ORG_ADMIN = "ROLE_ORG_ADMIN";
    public static final String ROLE_DEPT_LEADER = "ROLE_DEPT_LEADER";
    public static final String ROLE_MEMBER = "ROLE_MEMBER";

    private final OrgMemberMapper memberMapper;

    public AuthUser user() {
        return AuthUserContext.require();
    }

    public Long tenantId() {
        Long t = AuthUserContext.require().getTenantId();
        return t == null ? 0L : t;
    }

    /** 平台侧管理员（默认租户管理员 / 超管）—— 可操作租户端全部能力。 */
    public AuthUser requireTenantAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!hasRole(u, ROLE_ADMIN) && !hasRole(u, ROLE_TENANT_ADMIN)) {
            throw BizException.forbidden("仅租户管理员可执行该操作");
        }
        return u;
    }

    /**
     * 企业管理员：必须显式持有 ROLE_ORG_ADMIN 且能在 org_member 中解析出所属机构。
     * 注意 —— 租户管理员**不**继承企业端权限（范围纪律）。
     */
    public AuthUser requireOrgAdmin() {
        AuthUser u = AuthUserContext.require();
        if (!hasRole(u, ROLE_ORG_ADMIN)) {
            throw BizException.forbidden("仅企业管理员可执行该操作");
        }
        if (resolveInstitutionId(u.getUserId()) == null) {
            throw BizException.forbidden("企业管理员未绑定机构");
        }
        return u;
    }

    /** 机构成员（含企业管理员 / 部门负责人）：任何机构内用户角色。 */
    public AuthUser requireOrgUser() {
        AuthUser u = AuthUserContext.require();
        if (!hasRole(u, ROLE_ORG_ADMIN) && !hasRole(u, ROLE_DEPT_LEADER) && !hasRole(u, ROLE_MEMBER)) {
            throw BizException.forbidden("仅机构成员可执行该操作");
        }
        return u;
    }

    /**
     * 审批人：机构成员（企业管理员 / 部门负责人 / 成员）<b>或</b>租户管理员。
     *
     * <p>额度扩容、资源开通的末级审批节点是租户管理员，而租户管理员不属于任何机构的成员。
     * 若沿用 {@link #requireOrgUser()}，租户管理员既看不到待办也无法决策，
     * 该类单据会永久卡在二级节点 —— 故审批相关入口必须放行租户管理员。</p>
     */
    public AuthUser requireApprover() {
        AuthUser u = AuthUserContext.require();
        if (hasRole(u, ROLE_TENANT_ADMIN) || hasRole(u, ROLE_ORG_ADMIN)
                || hasRole(u, ROLE_DEPT_LEADER) || hasRole(u, ROLE_MEMBER)) {
            return u;
        }
        throw BizException.forbidden("仅机构成员或租户管理员可执行该操作");
    }

    public static boolean hasRole(AuthUser u, String role) {
        return u != null && u.getRoles() != null && u.getRoles().contains(role);
    }

    /** 由 org_member 解析登录用户所属机构；未绑定返回 null。 */
    public Long resolveInstitutionId(Long userId) {
        if (userId == null) {
            return null;
        }
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getUserId, userId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByAsc(OrgMember::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0).getInstitutionId();
    }

    /** 由 org_member 解析登录用户所属机构（不存在则 403）。 */
    public Long requireInstitutionId() {
        Long id = resolveInstitutionId(AuthUserContext.require().getUserId());
        if (id == null) {
            throw BizException.forbidden("当前账号未绑定任何机构，无法访问企业端数据");
        }
        return id;
    }

    /** 取该机构管理员成员行（用于姓名 / 部门等展示）。 */
    public OrgMember memberOf(Long institutionId, Long userId) {
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, institutionId)
                .eq(OrgMember::getUserId, userId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    /**
     * 机构硬边界断言：请求的资源必须属于当前登录企业管理员所属机构。
     * 越界统一 404（不泄露存在性），满足验收门禁「跨机构访问 0 成功」。
     */
    public void assertInstitution(Long institutionId) {
        Long mine = requireInstitutionId();
        if (institutionId == null || !mine.equals(institutionId)) {
            throw BizException.notFound("机构不存在或无权访问");
        }
    }
}
