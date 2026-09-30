package cn.aioa.org.service;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.support.ApprovalCallback;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 租户删除（需求：级联前置校验 + 上一级审核）。
 *
 * <p><b>为什么是「租户管理员申请、平台管理员审批」</b>：需求要求「任何一层级的首次删除操作都需要
 * 经过上一级审核」。四层为 员工 → 部门 → 机构 → 租户，租户的上一级即平台管理员。
 * 于是申请人必须是<b>该租户自己的管理员</b>（{@code ROLE_TENANT_ADMIN}），
 * 平台管理员是<b>审批人</b>而非发起人 —— 若让平台管理员发起，流程节点「申请人的上一级」
 * 会因为平台管理员已在最顶端而无级可取（{@code superiorLadder} 会退到部门负责人，把审批人静默指错）。</p>
 *
 * <p><b>审批通过后为什么要冻结该租户全部账号</b>：删掉 {@code sys_tenant} 行并不会让
 * 已经签发的访问令牌失效 —— {@code JwtAuthenticationFilter} 不回查租户表。但它会走
 * {@code RoleResolver.rolesOf(userId)}，该方法对「不存在 / DISABLED」的账号返回 {@code null}，
 * 过滤器据此拒绝本次认证（401）。所以把该租户账号置为 DISABLED 就能<b>即刻</b>作废存量令牌，
 * 否则会出现「租户已删除、其管理员仍能调接口」——不可逆动作不能留下这种口子。
 * （与 {@code TenantController.changeStatus} 停用租户同一手法。）</p>
 *
 * <p><b>为什么账号还要「软删」而不只是 DISABLED</b>（2026-09-30 修复）：平台管理员的
 * 「人员管理」按租户分组渲染，它取的是 {@code sys_user}（<b>跨租户全集</b>），而
 * {@code org_member} 只是成员关系 —— 于是只清 {@code org_member} 会留下
 * 「员工没了、账号还在」的残影：租户在列表里消失，它的账号却仍挂成一个分组继续展示。
 * 用户反馈「我已经删除了 test 租户，但组织与员工里的人员管理还能看到 test」即此。
 * 这与 {@code onApproved} 里 2026-09-24 修的机构/部门/员工级联是<b>同一类缺陷</b>——
 * 该次只覆盖了 {@code org_*}，漏了 {@code sys_user}。故此处一并软删账号与其角色行。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TenantDeleteService implements ApprovalCallback {

    public static final String BIZ_TYPE = "TENANT_DELETE";
    /** 默认租户（平台自身）不可删除，与「默认租户不可停用」同一口径。 */
    private static final long DEFAULT_TENANT_ID = 1L;

    private final OrgGuard guard;
    private final AuditRecorder audit;
    private final JdbcTemplate jdbc;
    /** 惰性取用，避免与 {@link ApprovalFlowService} 形成构造器循环依赖。 */
    private final ObjectProvider<ApprovalFlowService> flowService;

    @Override
    public String bizType() {
        return BIZ_TYPE;
    }

    /**
     * 级联前置校验：按四层由外向内逐级定位「还差哪一级」，返回 {@code null} 表示可删。
     *
     * <p>逐级判断而不是只查最外层，是为了让文案精确到「先做什么」——
     * 需求原文是「删除租户前必须先删除该租户下的所有部门」，但机构是部门的上一层，
     * 只报部门数会让用户不知道机构也要先清掉。</p>
     *
     * <p><b>「已注销（CLOSED）机构」及其下级行不构成阻塞</b>（2026-09-24 修复）：
     * 机构「注销」是不可逆终态（管理端原文「注销后机构不可恢复」），它只保留法人档案、
     * 不再对外提供任何服务，其下的部门与员工也随之一并失去业务意义。此前本方法对所有表
     * 一律按 {@code deleted_at IS NULL} 计数，于是「已注销但未软删」的机构会<b>永久</b>卡死租户删除：
     * 用户把机构全部注销后仍被告知「仍有 1 个机构」，且无论怎么操作都消不掉
     * （已注销机构里若还留着企业管理员，连机构本身都删不掉 —— 机构删除要求 0 员工，
     * 而企业管理员默认不可直删，形成死锁）。故此处把「已注销机构」整条子树排除在阻塞面之外。
     *
     * <p>排除后不会留下「租户已删、机构仍可查」的缝：真正的删除由 {@link #onApproved}
     * 级联软删这些残留行（见该方法注释）。</p>
     */
    public String blockedReason(Long tenantId) {
        long insts = countLiveInstitutions(tenantId);
        if (insts > 0) {
            return "该租户下仍有 " + insts + " 个未注销的机构，请先注销或删除全部机构"
                    + "（机构删除需先在「机构管理」中申请，经上一级审核）";
        }
        long depts = countOutsideClosedInstitutions("org_department", tenantId);
        if (depts > 0) {
            return "该租户下仍有 " + depts + " 个在用部门，请先删除全部部门";
        }
        long members = countOutsideClosedInstitutions("org_member", tenantId);
        if (members > 0) {
            return "该租户下仍有 " + members + " 名在用员工，请先移除全部员工";
        }
        return null;
    }

    /** 提交删除申请：前置校验 → 落审批单 → 等平台管理员批准。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> apply(String reason, AuthUser actor) {
        if (actor.getTenantId() == null || actor.getTenantId() == 0L) {
            throw BizException.forbidden("平台管理员不能发起「删除租户」：本流程的审批人是"
                    + "「申请人的上一级（平台管理员）」，平台管理员自己就是最高一级。"
                    + "请由该租户的租户管理员发起");
        }
        if (!OrgGuard.hasRole(actor, OrgGuard.ROLE_TENANT_ADMIN)) {
            throw BizException.forbidden("仅租户管理员可申请删除本租户");
        }
        Long tenantId = actor.getTenantId();
        if (tenantId == DEFAULT_TENANT_ID) {
            throw BizException.badRequest("默认租户不可删除");
        }
        Map<String, Object> t = tenantRow(tenantId);
        if (t == null) {
            throw BizException.notFound("租户不存在：" + tenantId);
        }
        String blocked = blockedReason(tenantId);
        if (blocked != null) {
            throw BizException.badRequest(blocked);
        }
        Long pending = jdbc.queryForObject(
                "SELECT COUNT(*) FROM approval_order WHERE biz_type = ? AND status = 'PENDING' "
                        + "AND deleted_at IS NULL AND form_data = ?",
                Long.class, BIZ_TYPE, formData(tenantId));
        if (pending != null && pending > 0) {
            throw BizException.badRequest("本租户已有一条待审批的删除申请，请等待审批结果");
        }

        ApprovalFlowService flow = flowService.getObject();
        if (flow == null) {
            throw BizException.badRequest("审批引擎未就绪，暂时无法提交申请");
        }
        String name = String.valueOf(t.get("name"));
        Map<String, Object> submitted = flow.submit(tenantId, actor,
                new ApprovalFlowService.SubmitReq(
                        BIZ_TYPE,
                        "删除租户：" + name,
                        "申请删除租户「" + name + "」（编码 " + t.get("code") + "）"
                                + (reason == null || reason.isBlank() ? "" : "；理由：" + reason),
                        formData(tenantId),
                        0L,
                        null,
                        null,
                        actor.getUserId(),
                        AuditRecorder.displayName(actor),
                        null,
                        "USER",
                        null));

        audit.record(tenantId, 0L, actor, "TENANT_DELETE_APPLY", "SYS_TENANT", tenantId,
                "申请删除租户「" + name + "」"
                        + (reason == null || reason.isBlank() ? "" : "（理由：" + reason + "）"),
                null, Map.of("tenantId", tenantId, "orderId", String.valueOf(submitted.get("orderId"))));

        Map<String, Object> out = new LinkedHashMap<>(submitted);
        out.put("tenantId", tenantId);
        out.put("tenantName", name);
        out.put("pendingApproval", true);
        out.put("hint", "已提交，需经平台管理员审核；批准后才会真正删除（含冻结本租户全部账号）");
        return out;
    }

    /**
     * 审批通过：重新校验前置条件 → 冻结该租户全部账号 → <b>级联终止全部组织数据</b> → 软删租户行。
     *
     * <p>顺序不能反：先冻结账号再删租户行。若先删行、冻结失败，就会留下
     * 「租户查不到、账号仍可登录」的状态，且没有任何地方能再发现它。</p>
     *
     * <p><b>为什么必须级联终止下级行</b>（2026-09-24 修复）：删除 {@code sys_tenant} 并不会让
     * {@code org_institution / org_department / org_member} 跟着消失 —— 它们各有自己的
     * {@code deleted_at}，且<b>平台管理员的机构列表是跨租户全集</b>（{@code selectableInstitutions}）。
     * 只软删租户行的结果是：租户在列表里没了，但它名下的机构/部门/员工<b>照旧出现在管理端</b>，
     * 正是用户反馈的「通过平台管理员删除后，相关数据仍继续展示」。故此处按由内向外的顺序
     * 把整条子树一并软删：
     * <b>账号与角色 → 员工账号绑定 → 员工 → 部门 → 机构（含已注销的）→ 租户行</b>。
     * 租户行放最后：前面任何一步失败都会回滚，租户仍在，流程可重试；反过来则会留下
     * 「租户已删、下级数据还在」的不可逆脏状态。</p>
     *
     * <p><b>账号为什么也在级联里</b>（2026-09-30 修复）：平台「人员管理」渲染的是 {@code sys_user}
     * 而非 {@code org_member}，2026-09-24 那次只清了 {@code org_*}，于是「已删租户的账号」
     * 仍以一个分组继续展示（用户反馈「删了 test 租户，人员管理还能看到 test」）。
     * 账号**同时置 DISABLED 并写 {@code deleted_at}**：前者作废存量令牌，后者让全集视图不再展示它。</p>
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void onApproved(Map<String, Object> order) {
        Long tenantId = idOf(order);
        if (tenantId == null) {
            throw BizException.badRequest("租户删除审批通过，但审批单里没有租户标识（form_data 缺 tenantId），"
                    + "拒绝静默跳过：orderId=" + order.get("id"));
        }
        Map<String, Object> t = tenantRow(tenantId);
        if (t == null) {
            throw BizException.badRequest("待删除的租户已不存在： " + tenantId);
        }
        String blocked = blockedReason(tenantId);
        if (blocked != null) {
            throw BizException.badRequest("审批期间该租户已不再满足删除条件，本次不执行删除：" + blocked);
        }
        // ① 冻结**并软删**全部账号与角色：
        //    · DISABLED —— 让该租户已签发的令牌立刻失效（见类注释）；
        //    · deleted_at —— 「人员管理」渲染的是 sys_user（跨租户全集），只冻结不软删的话，
        //      租户在列表里没了、它的账号仍挂成一个分组继续展示。
        int users = jdbc.update("UPDATE sys_user SET status = 'DISABLED', deleted_at = NOW(6), "
                + "updated_at = NOW(6) WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        int userRoles = jdbc.update("UPDATE sys_user_role SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        // ② 级联终止组织数据：员工账号绑定 → 员工 → 部门 → 机构（含已注销的）
        int bindings = jdbc.update("UPDATE org_member_account SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        int members = jdbc.update("UPDATE org_member SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        int depts = jdbc.update("UPDATE org_department SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        int insts = jdbc.update("UPDATE org_institution SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE tenant_id = ? AND deleted_at IS NULL", tenantId);
        // ③ 软删租户行（最后一步：上面的失败都会整体回滚，租户仍可重试）
        int rows = jdbc.update("UPDATE sys_tenant SET deleted_at = NOW(6), updated_at = NOW(6) "
                + "WHERE id = ? AND deleted_at IS NULL", tenantId);
        if (rows == 0) {
            throw BizException.badRequest("删除未生效：租户行未更新（可能已被并发删除）：" + tenantId);
        }
        audit.record(tenantId, 0L, null, "TENANT_DELETE_APPROVE", "SYS_TENANT", tenantId,
                "租户删除审核通过并执行：删除租户「" + t.get("name") + "」，同步冻结并清理账号 " + users
                        + " 个 / 角色 " + userRoles + " 条、清理机构 " + insts + " 个 / 部门 " + depts
                        + " 个 / 员工 " + members + " 名 / 账号绑定 " + bindings + " 条",
                t, Map.of("orderId", String.valueOf(order.get("id")), "frozenUsers", users,
                        "cascadedUserRoles", userRoles,
                        "cascadedInstitutions", insts, "cascadedDepartments", depts,
                        "cascadedMembers", members, "cascadedBindings", bindings));
        log.info("tenant deleted by approval: id={} name={} users={} userRoles={} insts={} depts={} members={} bindings={} orderId={}",
                tenantId, t.get("name"), users, userRoles, insts, depts, members, bindings, order.get("id"));
    }

    /** 审批驳回：租户与账号<b>保持原状</b>（不冻结、不软删），可再次申请。 */
    @Override
    public void onRejected(Map<String, Object> order) {
        log.info("tenant delete rejected, tenant kept as-is: tenantId={} orderId={}",
                idOf(order), order.get("id"));
    }

    // ------------------------------------------------------------------ helpers

    /**
     * 未「注销」的机构数。
     *
     * <p>{@code status} 允许为 NULL 时按「未注销」处理：历史行可能没写状态，
     * 把 NULL 当成 CLOSED 会<b>漏拦</b>（真机构被当作已注销放行），宁可多拦。</p>
     */
    private long countLiveInstitutions(Long tenantId) {
        Long n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM org_institution WHERE tenant_id = ? AND deleted_at IS NULL "
                        + "AND (status IS NULL OR status <> 'CLOSED')",
                Long.class, tenantId);
        return n == null ? 0L : n;
    }

    /**
     * 统计「不属于已注销机构」的存活行（部门 / 员工）。
     *
     * <p>部门与员工都带 {@code institution_id}；其机构一旦注销，这一行就随机构一起失效，
     * 不能再算作「租户还在运营的下级数据」—— 否则已注销机构里的残留员工会永久卡死租户删除。</p>
     */
    private long countOutsideClosedInstitutions(String table, Long tenantId) {
        Long n = jdbc.queryForObject(
                "SELECT COUNT(*) FROM " + table + " t WHERE t.tenant_id = ? AND t.deleted_at IS NULL "
                        + "AND NOT EXISTS (SELECT 1 FROM org_institution i WHERE i.id = t.institution_id "
                        + "AND i.status = 'CLOSED' AND i.deleted_at IS NULL)",
                Long.class, tenantId);
        return n == null ? 0L : n;
    }

    private Map<String, Object> tenantRow(Long tenantId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, code, name, status FROM sys_tenant WHERE id = ? AND deleted_at IS NULL",
                tenantId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private static String formData(Long tenantId) {
        return "{\"tenantId\":" + tenantId + "}";
    }

    private static Long idOf(Map<String, Object> order) {
        Object fd = order.get("formData");
        if (fd == null) {
            fd = order.get("form_data");
        }
        if (fd == null) {
            return null;
        }
        try {
            com.fasterxml.jackson.databind.JsonNode n =
                    new com.fasterxml.jackson.databind.ObjectMapper().readTree(String.valueOf(fd));
            com.fasterxml.jackson.databind.JsonNode v = n.get("tenantId");
            return v == null || v.isNull() ? null : v.asLong();
        } catch (Exception e) {
            log.warn("解析审批单 form_data 失败：{}", fd, e);
            return null;
        }
    }
}
