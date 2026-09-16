package cn.aioa.org.support;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgDuty;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 权限与机构硬边界守卫（规格书第七章「范围纪律」的代码落地）。
 *
 * <p>纪律：租户管理员端管资源与规则，企业管理员端管组织与执行；
 * 企业管理员跨机构访问必须为 0 成功 —— 越界统一返回 404（不泄露存在性）。</p>
 *
 * <h3>三级作用域模型（V32 修订）</h3>
 * <p>此前只区分「机构成员」与「非机构成员」，导致租户管理员和平台管理员
 * 在组织与员工页全员 403（菜单/路由对它们开放，接口却拒之门外——三层口径打架）。
 * 现按数据的<b>作用域</b>分三档：</p>
 * <table>
 *   <tr><th>角色</th><th>可读范围</th><th>可写范围</th></tr>
 *   <tr><td>机构成员（企业管理员 / 部门负责人 / 成员）</td><td>本机构（硬绑定）</td><td>企业管理员可写本机构</td></tr>
 *   <tr><td>租户管理员</td><td>本租户全部机构（可切换）</td><td>本租户全部机构</td></tr>
 *   <tr><td>平台管理员</td><td>跨租户（可切换，运维视角）</td><td>只读</td></tr>
 * </table>
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
    private final OrgInstitutionMapper institutionMapper;
    private final OrgDepartmentMapper deptMapper;
    private final JdbcTemplate jdbc;

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

    /**
     * 部门负责人闸门（二期 E-03/E-05）—— 「仅部门负责人可代表部门发起申请」。
     *
     * <p>判定顺序（<b>不可颠倒</b>）：</p>
     * <ol>
     *   <li><b>机构归属</b>：跨机构 / 跨租户 / 平台账号（无 org_member）→ <b>404</b>（不泄露存在性）；</li>
     *   <li><b>职务</b>：同机构但非本部门负责人 → <b>403</b>。</li>
     * </ol>
     *
     * <p>判定口径<b>只认</b> {@code org_member.duty_code='DEPT_PRINCIPAL'}（同部门任一正职即可），
     * 其次回落 {@code org_department.leader_user_id}。<b>绝不使用 {@code job_title}</b>
     * —— 它是自由文本展示字段，历史上正是它制造了 27/8/3 三口径分裂（见 docs/23）。</p>
     */
    public void requireDeptLeader(Long departmentId) {
        AuthUser u = AuthUserContext.require();
        if (departmentId == null || departmentId <= 0) {
            throw BizException.notFound("部门不存在或无权访问");
        }
        OrgDepartment dept = deptMapper.selectById(departmentId);
        if (dept == null || dept.getDeletedAt() != null) {
            throw BizException.notFound("部门不存在或无权访问");
        }
        Long ownInst = resolveInstitutionId(u.getUserId());
        if (ownInst == null || !ownInst.equals(dept.getInstitutionId())) {
            // 跨机构 / 跨租户 / 平台账号：一律 404，不泄露部门是否存在
            throw BizException.notFound("部门不存在或无权访问");
        }
        if (isPrincipalOf(u.getUserId(), departmentId)) {
            return;
        }
        if (dept.getLeaderUserId() != null && dept.getLeaderUserId().equals(u.getUserId())) {
            return;
        }
        throw BizException.forbidden("仅部门负责人可代表部门申请");
    }

    /**
     * 我负责的部门清单（部门申请开关的数据源，口径与 {@link #requireDeptLeader} 一致）。
     *
     * <p>判定：① 我在该部门持 {@code duty_code='DEPT_PRINCIPAL'}（同部门任一正职）；
     * ② 回落 {@code org_department.leader_user_id} 指向我。{@code job_title} 不作依据。</p>
     */
    public List<OrgDepartment> ledDepartments(Long userId) {
        if (userId == null) {
            return List.of();
        }
        List<Long> dutyDeptIds = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                        .eq(OrgMember::getUserId, userId)
                        .eq(OrgMember::getDutyCode, OrgDuty.DEPT_PRINCIPAL)
                        .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE))
                .stream().map(OrgMember::getDepartmentId)
                .filter(id -> id != null && id > 0)
                .distinct()
                .toList();
        LambdaQueryWrapper<OrgDepartment> q = new LambdaQueryWrapper<OrgDepartment>()
                .orderByAsc(OrgDepartment::getId);
        if (dutyDeptIds.isEmpty()) {
            q.eq(OrgDepartment::getLeaderUserId, userId);
        } else {
            q.and(w -> w.eq(OrgDepartment::getLeaderUserId, userId)
                    .or().in(OrgDepartment::getId, dutyDeptIds));
        }
        return deptMapper.selectList(q);
    }

    /** 我在该部门是否持「部门正职」职务（{@code duty_code='DEPT_PRINCIPAL'}）。 */
    private boolean isPrincipalOf(Long userId, Long departmentId) {
        if (userId == null || departmentId == null) {
            return false;
        }
        return memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getUserId, userId)
                .eq(OrgMember::getDepartmentId, departmentId)
                .eq(OrgMember::getDutyCode, OrgDuty.DEPT_PRINCIPAL)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)) > 0;
    }

    /**
     * 组织数据读取者：机构成员（企业管理员 / 部门负责人 / 成员）+ 租户管理员 + 平台管理员。
     *
     * <p><b>为何租户管理员与平台管理员也放行</b>：组织与员工页的菜单与路由对这两类角色开放，
     * 且数字员工的「按部门分发」（{@code visible_scope=DEPT}）必须先读得到部门树。
     * 若接口只认机构成员，就会出现「进得去页面、接口全 403」的三层口径不一致
     * （用户实测报错「部门加载失败 / 员工加载失败 403」即源于此）。
     * 读权限放开的同时，写权限由 {@link #requireOrgWriter()} 收紧，越界由
     * {@link #resolveScopeInstitution(Long)} 兜底。</p>
     */
    public AuthUser requireOrgUser() {
        AuthUser u = AuthUserContext.require();
        if (hasRole(u, ROLE_ADMIN) || hasRole(u, ROLE_TENANT_ADMIN) || hasRole(u, ROLE_ORG_ADMIN)
                || hasRole(u, ROLE_DEPT_LEADER) || hasRole(u, ROLE_MEMBER)) {
            return u;
        }
        throw BizException.forbidden("仅机构成员、租户管理员或平台管理员可查看组织与员工数据");
    }

    /**
     * 组织数据写入者：企业管理员（限本机构）或租户管理员（限本租户）。
     *
     * <p>平台管理员为<b>只读</b>运维视角，不参与企业组织的日常维护。</p>
     */
    public AuthUser requireOrgWriter() {
        AuthUser u = AuthUserContext.require();
        if (hasRole(u, ROLE_TENANT_ADMIN) || hasRole(u, ROLE_ORG_ADMIN)) {
            return u;
        }
        throw BizException.forbidden("仅企业管理员或租户管理员可维护组织与员工；平台管理员为只读视角");
    }

    /**
     * 审批人：机构成员（企业管理员 / 部门负责人 / 成员）<b>或</b>租户管理员 / 平台管理员。
     *
     * <p>额度扩容、资源开通的末级审批节点是租户管理员，而租户管理员不属于任何机构的成员。
     * 若沿用 {@link #requireOrgUser()}，租户管理员既看不到待办也无法决策，
     * 该类单据会永久卡在二级节点 —— 故审批相关入口必须放行租户管理员。</p>
     *
     * <p>平台管理员同样必须放行：它是「申请人的上一级」链的<b>终极一级</b>
     * （{@code ApprovalTask.TYPE_PLATFORM_ADMIN}）。租户管理员之上再无本租户的上级，
     * 若平台管理员进不来，租户管理员发起的申请就无人能批。</p>
     */
    public AuthUser requireApprover() {
        AuthUser u = AuthUserContext.require();
        if (hasRole(u, ROLE_ADMIN) || hasRole(u, ROLE_TENANT_ADMIN) || hasRole(u, ROLE_ORG_ADMIN)
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

    /**
     * 解析本次请求应作用的机构——组织数据作用域的唯一判定点。
     *
     * <ol>
     *   <li><b>机构成员</b>（企业管理员 / 部门负责人 / 成员）：硬绑定本机构，
     *       忽略入参（防止通过 {@code ?institutionId=} 探测他机构）；</li>
     *   <li><b>租户管理员</b>：可在本租户内指定机构；未指定取本租户首个启用机构；</li>
     *   <li><b>平台管理员</b>：可跨租户指定机构；未指定取全局首个启用机构（运维视角）。</li>
     * </ol>
     *
     * @param requested 显式请求的机构 id（可空）
     * @return 本次请求实际作用的机构 id
     */
    public Long resolveScopeInstitution(Long requested) {
        AuthUser u = AuthUserContext.require();
        Long own = resolveInstitutionId(u.getUserId());
        if (own != null) {
            // 机构成员：机构是硬边界，不接受任何入参覆盖；
            // 显式指向他机构一律 404（不泄露存在性，满足「跨机构访问 0 成功」门禁），
            // 而不是静默回退本机构——静默回退会让调用方误以为操作作用在目标机构上。
            if (requested != null && !requested.equals(own)) {
                throw BizException.notFound("机构不存在或无权访问：" + requested);
            }
            return own;
        }
        if (hasRole(u, ROLE_ADMIN)) {
            return requested == null ? firstActiveInstitution(null) : requireActiveInstitution(requested, null);
        }
        if (hasRole(u, ROLE_TENANT_ADMIN)) {
            Long tenant = u.getTenantId();
            return requested == null ? firstActiveInstitution(tenant) : requireActiveInstitution(requested, tenant);
        }
        throw BizException.forbidden("当前账号未绑定任何机构，无法访问企业端数据");
    }

    /** 由 org_member 解析登录用户所属机构（不存在则 403）。 */
    public Long requireInstitutionId() {
        return resolveScopeInstitution(null);
    }

    /** 解析机构（支持显式指定，供租户管理员 / 平台管理员切换机构）。 */
    public Long requireInstitutionId(Long requested) {
        return resolveScopeInstitution(requested);
    }

    /**
     * 当前登录用户可查看的机构清单 + 写入能力，供前端渲染机构选择器与按钮显隐。
     *
     * <p>机构成员只返回自己那一家（选择器自动隐藏）；租户管理员返回本租户全部启用机构；
     * 平台管理员返回全局全部启用机构。</p>
     */
    public Map<String, Object> selectableInstitutions() {
        AuthUser u = AuthUserContext.require();
        requireOrgUser();
        Long own = resolveInstitutionId(u.getUserId());

        LambdaQueryWrapper<OrgInstitution> q = new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getStatus, OrgInstitution.STATUS_ACTIVE)
                .orderByAsc(OrgInstitution::getId);
        if (own != null) {
            q.eq(OrgInstitution::getId, own);
        } else if (hasRole(u, ROLE_TENANT_ADMIN) && !hasRole(u, ROLE_ADMIN)) {
            q.eq(OrgInstitution::getTenantId, u.getTenantId());
        }

        List<Map<String, Object>> items = new ArrayList<>();
        for (OrgInstitution ins : institutionMapper.selectList(q)) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", ins.getId());
            row.put("name", ins.getName());
            row.put("code", ins.getCode());
            row.put("tenantId", ins.getTenantId());
            row.put("status", ins.getStatus());
            items.add(row);
        }

        boolean canWrite = hasRole(u, ROLE_TENANT_ADMIN) || hasRole(u, ROLE_ORG_ADMIN);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("canWrite", canWrite);
        out.put("boundInstitutionId", own);
        out.put("scope", own != null ? "ORG"
                : (hasRole(u, ROLE_ADMIN) ? "PLATFORM" : "TENANT"));
        return out;
    }

    // ================================================================== 租户端作用域（V33）

    /**
     * 解析本次请求应作用的<b>租户</b>——租户端（{@code /api/v1/tenant/*}）数据作用域的唯一判定点。
     *
     * <p><b>为何需要</b>：租户端此前一律取 {@code AuthUser.tenantId}。平台管理员的 tenantId 恒为 0
     * （平台自身租户），而机构、配额、授权、成本分摊数据全部挂在 2..N 号业务租户下，
     * 于是平台管理员打开「机构管理 / 入驻进度 / 资源授权 / 成本分摊」时四个页面全是空态
     * ——「菜单能进、数据全空」的锚点缺陷（用户实测反馈「租户、机构模块显示无数据」）。</p>
     *
     * <ol>
     *   <li><b>租户管理员</b>：租户是硬边界，入参必须等于本租户，否则 404（不泄露存在性）；</li>
     *   <li><b>平台管理员</b>：可跨租户指定；未指定时取「机构最多的启用租户」作默认，
     *       避免默认落回 tenant 0 再次空态。</li>
     * </ol>
     *
     * @param requested 显式请求的租户 id（可空）
     * @return 本次请求实际作用的租户 id
     */
    public Long resolveScopeTenant(AuthUser u, Long requested) {
        if (hasRole(u, ROLE_TENANT_ADMIN) && !hasRole(u, ROLE_ADMIN)) {
            Long own = u.getTenantId() == null ? 0L : u.getTenantId();
            if (requested != null && !requested.equals(own)) {
                throw BizException.notFound("租户不存在或无权访问：" + requested);
            }
            return own;
        }
        if (hasRole(u, ROLE_ADMIN)) {
            return requested == null ? defaultTenantId() : requireActiveTenant(requested);
        }
        throw BizException.forbidden("仅租户管理员或平台管理员可访问租户端数据");
    }

    /** 便捷重载：作用对象取当前登录用户。 */
    public Long resolveScopeTenant(Long requested) {
        return resolveScopeTenant(AuthUserContext.require(), requested);
    }

    /**
     * 便捷入口：作用租户 = 当前请求的 {@code ?tenantId=}（可选）经作用域校验后的结果。
     *
     * <p>租户端各控制器（机构/配额/授权/分摊/入驻/假种/审批流）统一走这一个入口，
     * 避免每个控制器各写一份取参逻辑——上一版就是因为只有部分控制器做了作用域解析，
     * 才出现「机构管理修好了、入驻进度还是空」的半修复状态。</p>
     */
    public Long resolveRequestTenant(AuthUser u) {
        return resolveScopeTenant(u, requestedTenantId());
    }

    /** 从当前请求读取 {@code ?tenantId=}（平台管理员切换租户用）。 */
    private static Long requestedTenantId() {
        RequestAttributes attrs = RequestContextHolder.getRequestAttributes();
        if (!(attrs instanceof ServletRequestAttributes sra)) {
            return null;
        }
        String raw = sra.getRequest().getParameter("tenantId");
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return Long.valueOf(raw.trim());
        } catch (NumberFormatException e) {
            throw BizException.badRequest("tenantId 必须为数字：" + raw);
        }
    }

    /**
     * 当前账号可操作的租户清单 + 默认租户，供前端渲染租户选择器。
     *
     * <p>平台管理员拿到全部启用租户（可切换）；租户管理员只拿到自己那一家（选择器自动隐藏）。</p>
     */
    public Map<String, Object> selectableTenants() {
        AuthUser u = AuthUserContext.require();
        if (!hasRole(u, ROLE_ADMIN) && !hasRole(u, ROLE_TENANT_ADMIN)) {
            throw BizException.forbidden("仅租户管理员可执行该操作");
        }
        boolean platform = hasRole(u, ROLE_ADMIN);
        String base = "SELECT t.id AS id, t.code AS code, t.name AS name, t.status AS status, "
                + "(SELECT COUNT(*) FROM org_institution i "
                + " WHERE i.tenant_id = t.id AND i.deleted_at IS NULL) AS institutionCount "
                + "FROM sys_tenant t WHERE t.deleted_at IS NULL ";
        List<Map<String, Object>> items = platform
                ? jdbc.queryForList(base + "AND t.status = 'ENABLED' ORDER BY t.id")
                : jdbc.queryForList(base + "AND t.id = ?", u.getTenantId());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("total", items.size());
        out.put("canSwitch", platform);
        out.put("boundTenantId", platform ? null : (u.getTenantId() == null ? 0L : u.getTenantId()));
        out.put("defaultTenantId", platform ? defaultTenantId() : (u.getTenantId() == null ? 0L : u.getTenantId()));
        out.put("scope", platform ? "PLATFORM" : "TENANT");
        return out;
    }

    /**
     * 平台视角的默认租户：机构最多的启用租户。
     *
     * <p>刻意不按 id 取最小——id=1 的「默认租户」名下 0 家机构，取它会立刻回到空态，
     * 让「已修复」看起来仍然没修好。</p>
     */
    private Long defaultTenantId() {
        List<Long> ids = jdbc.queryForList(
                "SELECT t.id FROM sys_tenant t WHERE t.status = 'ENABLED' AND t.deleted_at IS NULL "
                        + "ORDER BY (SELECT COUNT(*) FROM org_institution i "
                        + " WHERE i.tenant_id = t.id AND i.deleted_at IS NULL) DESC, t.id ASC LIMIT 1",
                Long.class);
        if (ids.isEmpty()) {
            throw BizException.notFound("平台下暂无启用租户");
        }
        return ids.get(0);
    }

    /** 校验租户存在且启用；不存在/停用一律 404（不泄露存在性）。 */
    private Long requireActiveTenant(Long tenantId) {
        List<Long> ids = jdbc.queryForList(
                "SELECT id FROM sys_tenant WHERE id = ? AND status = 'ENABLED' AND deleted_at IS NULL",
                Long.class, tenantId);
        if (ids.isEmpty()) {
            throw BizException.notFound("租户不存在或已停用：" + tenantId);
        }
        return ids.get(0);
    }

    /** 校验机构存在、启用，且（可选的）租户归属匹配；跨租户一律 404（不泄露存在性）。 */
    private Long requireActiveInstitution(Long institutionId, Long tenantId) {
        OrgInstitution ins = institutionMapper.selectById(institutionId);
        if (ins == null || !OrgInstitution.STATUS_ACTIVE.equals(ins.getStatus())) {
            throw BizException.notFound("机构不存在或已停用：" + institutionId);
        }
        if (tenantId != null && !tenantId.equals(ins.getTenantId())) {
            throw BizException.notFound("机构不存在或已停用：" + institutionId);
        }
        return ins.getId();
    }

    /** 取（某租户或全局）首个启用机构；一家都没有时给出可读的提示。 */
    private Long firstActiveInstitution(Long tenantId) {
        List<OrgInstitution> rows = institutionMapper.selectList(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getStatus, OrgInstitution.STATUS_ACTIVE)
                .eq(tenantId != null, OrgInstitution::getTenantId, tenantId)
                .orderByAsc(OrgInstitution::getId)
                .last("limit 1"));
        if (rows.isEmpty()) {
            throw BizException.notFound(tenantId == null ? "平台下暂无启用机构" : "本租户暂无启用机构");
        }
        return rows.get(0).getId();
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
