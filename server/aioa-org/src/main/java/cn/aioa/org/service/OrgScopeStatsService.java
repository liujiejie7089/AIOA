package cn.aioa.org.service;

import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgFeedbackMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.security.AuthUser;
import cn.aioa.security.AuthUserContext;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 「本组织数据」——用户端首页按<b>登录人角色</b>决定能看到多大范围的数据。
 *
 * <h3>范围裁决（唯一判定点）</h3>
 * <table border="1">
 *   <tr><th>角色</th><th>scope</th><th>看到什么</th></tr>
 *   <tr><td>平台管理员 / 租户管理员</td><td>{@code TENANT}</td><td>本租户全量</td></tr>
 *   <tr><td>企业（机构）管理员</td><td>{@code INSTITUTION}</td><td>本人所属机构</td></tr>
 *   <tr><td>部门负责人</td><td>{@code DEPARTMENT}</td><td>本人负责的部门</td></tr>
 *   <tr><td>普通成员</td><td>{@code NONE}</td><td>不展示该卡</td></tr>
 * </table>
 *
 * <p><b>为什么普通成员是 NONE 而不是「本部门（只读）」</b>：部门词元消耗、会话量属于
 * 组织运营数据，不是成员完成本职工作所必需。用户本次的需求也明确是
 * 「机构、部门的管理员在用户端首页可显示本组织的数据」。<b>可见面按需求取最小</b>，
 * 不做「反正无害就都给」的扩大——扩大容易，收回很难。</p>
 *
 * <h3>为什么范围由后端裁决而不是前端传参</h3>
 * <p>前端传什么都能被伪造。范围必须由服务端依据登录身份推导，前端只负责渲染
 * 「后端说你能看什么」。这与 {@code OrgGuard.resolveScopeInstitution} 是同一条纪律。</p>
 */
@Service
@RequiredArgsConstructor
public class OrgScopeStatsService {

    public static final String SCOPE_TENANT = "TENANT";
    public static final String SCOPE_INSTITUTION = "INSTITUTION";
    public static final String SCOPE_DEPARTMENT = "DEPARTMENT";
    public static final String SCOPE_NONE = "NONE";

    private final OrgGuard guard;
    private final OrgStatMapper statMapper;
    private final OrgFeedbackMapper feedbackMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgDepartmentMapper deptMapper;
    private final OrgInstitutionMapper institutionMapper;

    /** 首页「本组织数据」卡的数据源。 */
    public Map<String, Object> orgScope() {
        AuthUser u = AuthUserContext.require();
        long tenantId = u.getTenantId() == null ? 0L : u.getTenantId();
        OrgMember me = primaryMemberOf(u.getUserId());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("generatedAt", LocalDateTime.now().toString());

        // ---- 1) 平台/租户管理员：全租户 ----
        if (OrgGuard.hasRole(u, OrgGuard.ROLE_ADMIN) || OrgGuard.hasRole(u, OrgGuard.ROLE_TENANT_ADMIN)) {
            out.put("scope", SCOPE_TENANT);
            out.put("scopeLabel", "本租户");
            out.put("roleLabel", OrgGuard.hasRole(u, OrgGuard.ROLE_ADMIN) ? "平台管理员" : "租户管理员");
            out.put("scopeName", tenantName(tenantId));
            out.put("canSeeOrg", true);
            out.put("metrics", List.of(
                    metric("employees", "在职员工", feedbackMapper.countMembersOfTenant(tenantId), "人"),
                    metric("institutions", "启用机构", feedbackMapper.countInstitutionsOfTenant(tenantId), "家"),
                    metric("departments", "启用部门", feedbackMapper.countDeptsOfTenant(tenantId), "个"),
                    metric("myTodos", "待我处理", statMapper.countMyTodoTasks(u.getUserId()), "件"),
                    metric("conversations", "本月会话", statMapper.countConversationsOfTenant(tenantId), "次"),
                    metric("tokens", "本月词元", statMapper.sumLedgerTokens(tenantId, period()), "")));
            return out;
        }

        // ---- 2) 机构管理员：本机构 ----
        if (OrgGuard.hasRole(u, OrgGuard.ROLE_ORG_ADMIN) && me != null && me.getInstitutionId() != null
                && me.getInstitutionId() > 0) {
            Long iid = me.getInstitutionId();
            out.put("scope", SCOPE_INSTITUTION);
            out.put("scopeLabel", "本机构");
            out.put("roleLabel", "机构管理员");
            out.put("scopeName", institutionName(iid));
            out.put("institutionId", iid);
            out.put("canSeeOrg", true);
            out.put("metrics", List.of(
                    metric("employees", "机构成员", statMapper.countActiveMembers(iid), "人"),
                    metric("departments", "下属部门", statMapper.countActiveDepts(iid), "个"),
                    metric("myTodos", "待我处理", statMapper.countMyTodoTasks(u.getUserId()), "件"),
                    metric("conversations", "本月会话",
                            feedbackMapper.countConversationsOfInstitution(tenantId, iid), "次"),
                    metric("tokens", "本月词元",
                            statMapper.sumLedgerTokensOfInstitution(tenantId, iid, period()), ""),
                    metric("kbDocs", "机构知识库", statMapper.countKbOfInstitution(iid), "份")));
            return out;
        }

        // ---- 3) 部门负责人：本部门（我负责的那个，而不是我所在的）----
        List<OrgDepartment> led = guard.ledDepartments(u.getUserId());
        if (!led.isEmpty()) {
            OrgDepartment dept = pickLedDept(led, me);
            Long did = dept.getId();
            out.put("scope", SCOPE_DEPARTMENT);
            out.put("scopeLabel", "本部门");
            out.put("roleLabel", "部门负责人");
            out.put("scopeName", dept.getName());
            out.put("departmentId", did);
            out.put("institutionId", dept.getInstitutionId());
            out.put("ledDepartments", led.stream().map(OrgDepartment::getName).toList());
            out.put("canSeeOrg", true);
            out.put("metrics", List.of(
                    metric("employees", "部门成员", feedbackMapper.countMembersOfDept(did), "人"),
                    metric("departments", "下级部门", feedbackMapper.countChildDepts(did), "个"),
                    metric("myTodos", "待我处理", statMapper.countMyTodoTasks(u.getUserId()), "件"),
                    metric("conversations", "本月会话",
                            feedbackMapper.countConversationsOfDept(tenantId, did), "次"),
                    metric("tokens", "本月词元",
                            feedbackMapper.sumLedgerTokensOfDept(tenantId, did, period()), ""),
                    metric("kbDocs", "部门知识库", feedbackMapper.countKbOfDept(did), "份")));
            return out;
        }

        // ---- 4) 其余（普通成员 / 未纳管账号）：不展示 ----
        out.put("scope", SCOPE_NONE);
        out.put("scopeLabel", "个人");
        out.put("roleLabel", me == null ? "未纳管账号" : "企业成员");
        out.put("scopeName", null);
        out.put("canSeeOrg", false);
        out.put("metrics", List.of());
        out.put("note", "「本组织数据」仅对机构管理员与部门负责人展示（可见面按需求取最小）。"
                + "你可以在「我的 → 我的数据」查看个人的实时统计。");
        return out;
    }

    /**
     * 一人负责多个部门时选哪个作默认。
     *
     * <p>优先选「本人主身份所在的那个」（同一份数据两处口径一致）；否则取 id 最小的，
     * 保证同一账号每次得到同一结果 —— 可复现比「随机挑一个」重要得多。
     * 其余负责的部门通过 {@code ledDepartments} 一并返回，前端可做切换。</p>
     */
    private static OrgDepartment pickLedDept(List<OrgDepartment> led, OrgMember me) {
        if (me != null && me.getDepartmentId() != null) {
            for (OrgDepartment d : led) {
                if (me.getDepartmentId().equals(d.getId())) {
                    return d;
                }
            }
        }
        return led.get(0);
    }

    private OrgMember primaryMemberOf(Long userId) {
        if (userId == null) {
            return null;
        }
        List<OrgMember> rows = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getUserId, userId)
                .eq(OrgMember::getStatus, OrgMember.STATUS_ACTIVE)
                .orderByDesc(OrgMember::getIsPrimary)
                .orderByAsc(OrgMember::getId)
                .last("limit 1"));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private String institutionName(Long institutionId) {
        var ins = institutionMapper.selectById(institutionId);
        return ins == null ? null : ins.getName();
    }

    private String tenantName(Long tenantId) {
        Map<String, Object> t = statMapper.selectTenant(tenantId);
        return t == null ? null : String.valueOf(t.get("name"));
    }

    private static String period() {
        LocalDateTime now = LocalDateTime.now();
        return String.format("%04d-%02d", now.getYear(), now.getMonthValue());
    }

    private static Map<String, Object> metric(String key, String label, long value, String unit) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("key", key);
        m.put("label", label);
        m.put("value", value);
        m.put("unit", unit);
        return m;
    }

    /** 供控制器直接复用：把「可读范围」清单化（便于用户端做范围说明）。 */
    public List<Map<String, Object>> scopeCatalog() {
        List<Map<String, Object>> out = new ArrayList<>();
        out.add(scopeRow(SCOPE_TENANT, "本租户", "平台管理员 / 租户管理员"));
        out.add(scopeRow(SCOPE_INSTITUTION, "本机构", "机构管理员"));
        out.add(scopeRow(SCOPE_DEPARTMENT, "本部门", "部门负责人"));
        return out;
    }

    private static Map<String, Object> scopeRow(String scope, String label, String who) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("scope", scope);
        m.put("label", label);
        m.put("who", who);
        return m;
    }
}
