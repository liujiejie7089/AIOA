package cn.aioa.org.service;

import cn.aioa.common.event.TenantProvisionedEvent;
import cn.aioa.common.exception.BizException;
import cn.aioa.org.entity.OrgDepartment;
import cn.aioa.org.entity.OrgInstitution;
import cn.aioa.org.entity.OrgMember;
import cn.aioa.org.mapper.OrgDepartmentMapper;
import cn.aioa.org.mapper.OrgInstitutionMapper;
import cn.aioa.org.mapper.OrgMemberMapper;
import cn.aioa.org.mapper.OrgStatMapper;
import cn.aioa.org.support.AccountProvisioner;
import cn.aioa.org.support.AuditRecorder;
import cn.aioa.org.support.CreditCode;
import cn.aioa.org.support.OrgGuard;
import cn.aioa.org.support.Vals;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 机构生命周期（FR-B）：
 *   B1 机构建档（新建 / 编辑 / 停用 / 恢复 / 注销）
 *   B2 企业管理员指定与交接（唯一边界）
 *   B3 机构建档模板（二期，暂以「上次配置复制」占位）
 *
 * 范围纪律：本服务仅租户管理员可用；不提供机构内部组织管理（FR-G 属企业端）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InstitutionService {

    private final OrgInstitutionMapper institutionMapper;
    private final OrgDepartmentMapper departmentMapper;
    private final OrgMemberMapper memberMapper;
    private final OrgStatMapper statMapper;
    private final OrgGuard guard;
    private final AuditRecorder audit;
    private final AccountProvisioner accounts;
    private final ApplicationEventPublisher events;

    // ------------------------------------------------------------------ 查询

    /**
     * 机构清单（运营面默认口径：**已注销机构不出现**）。
     *
     * <p>用户报障：「注销了机构，机构管理 / 入驻进度 / 资源授权 / 人员管理都还能看到」。
     * 根因是这里只按 {@code tenant_id} 过滤、不设状态默认值 ⇒ 已是不可逆终态的 CLOSED 行
     * 照旧排在清单里。口径现在收敛为：</p>
     * <ul>
     *   <li>默认（{@code includeClosed=false} 且未显式给 {@code status}）→ 排除 CLOSED
     *       （停用 SUSPENDED 仍展示：得能看见才谈得上「恢复」）；</li>
     *   <li>显式 {@code status=CLOSED} → 以调用方的显式请求为准，不叠加默认排除；</li>
     *   <li>{@code includeClosed=true} → 完全不做默认排除，用于「档案 / 归档」视角。</li>
     * </ul>
     *
     * <p>为什么留 {@code includeClosed} 而不是彻底删掉这条路径：注销是<b>不可逆的法人档案终态</b>，
     * 档案行必须保留，而级联删除（删租户）与历史回查都需要能取到它 ——
     * 详见 {@code InstitutionStatus} 与 {@code _check_delete_guards.py} 的 D15。
     * 换句话说：不是「删掉已注销机构」，而是「让它退出运营面、只留档案入口」。</p>
     */
    public List<Map<String, Object>> list(Long tenantId, String keyword, String status, String orgType,
                                          boolean includeClosed) {
        LambdaQueryWrapper<OrgInstitution> w = new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .eq(status != null && !status.isBlank(), OrgInstitution::getStatus, status)
                .eq(orgType != null && !orgType.isBlank(), OrgInstitution::getOrgType, orgType)
                .like(keyword != null && !keyword.isBlank(), OrgInstitution::getName, keyword)
                .orderByAsc(OrgInstitution::getId);
        // 显式指定了状态就尊重它：`status=CLOSED` 本身就是「我要看档案」的声明，
        // 此时再叠加默认排除会得到一张恒空的表（调用方无从判断是「没有」还是「被过滤了」）。
        if (!includeClosed && (status == null || status.isBlank())) {
            OrgInstitution.excludeClosed(w);
        }
        List<OrgInstitution> rows = institutionMapper.selectList(w);
        List<Map<String, Object>> out = new ArrayList<>(rows.size());
        for (OrgInstitution it : rows) {
            out.add(toView(it));
        }
        return out;
    }

    public Map<String, Object> detail(Long tenantId, Long id) {
        OrgInstitution it = require(tenantId, id);
        return toView(it);
    }

    private Map<String, Object> toView(OrgInstitution it) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", it.getId());
        m.put("tenantId", it.getTenantId());
        m.put("name", it.getName());
        m.put("code", it.getCode());
        m.put("orgType", it.getOrgType());
        m.put("creditCode", it.getCreditCode());
        m.put("legalPerson", it.getLegalPerson());
        m.put("contactMobile", it.getContactMobile());
        m.put("contactEmail", it.getContactEmail());
        m.put("adminUserId", it.getAdminUserId());
        m.put("adminName", it.getAdminName());
        m.put("status", it.getStatus());
        m.put("establishedAt", it.getEstablishedAt() == null ? null : it.getEstablishedAt().toString());
        m.put("onboardStep", it.getOnboardStep());
        m.put("remark", it.getRemark());
        m.put("createdAt", it.getCreatedAt() == null ? null : it.getCreatedAt().toString());
        m.put("departmentCount", departmentMapper.selectCount(new LambdaQueryWrapper<OrgDepartment>()
                .eq(OrgDepartment::getInstitutionId, it.getId())));
        m.put("memberCount", memberMapper.selectCount(new LambdaQueryWrapper<OrgMember>()
                .eq(OrgMember::getInstitutionId, it.getId())));
        // 管理员账号名（交接页展示）
        if (it.getAdminUserId() != null) {
            Map<String, Object> u = statMapper.selectUser(it.getAdminUserId());
            if (u != null && u.get("username") != null) {
                m.put("adminUsername", u.get("username"));
            }
        }
        return m;
    }

    public OrgInstitution require(Long tenantId, Long id) {
        OrgInstitution it = institutionMapper.selectById(id);
        if (it == null || !it.getTenantId().equals(tenantId)) {
            throw BizException.notFound("机构不存在：" + id);
        }
        return it;
    }

    /**
     * 机构类型字典（**唯一权威来源**）：管理端下拉的选项与列表的标签都从这里取。
     *
     * <p>端点：{@code GET /api/v1/tenant/institution-types}。前端不得再自建第二份枚举 ——
     * 之前那样做的后果见 {@link OrgInstitution#TYPE_GOVERNMENT} 的类注释。</p>
     */
    public List<Map<String, Object>> typeOptions() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map.Entry<String, String> e : OrgInstitution.types().entrySet()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("code", e.getKey());
            m.put("label", e.getValue());
            out.add(m);
        }
        return out;
    }

    /**
     * 信用代码归一化 + 格式校验 + **唯一性**；未填写返回 {@code null}。
     *
     * <p>唯一性按**全局**判定：统一社会信用代码是法人唯一标识，不因租户而重复。
     * 查询走 MyBatis-Plus 的 {@code @TableLogic}（自动附加 {@code deleted_at IS NULL}）⇒
     * 软删机构不会永久占号，不需要（也不应该）加库级唯一索引 ——
     * 那会让软删后重建同一机构直接撞唯一键。</p>
     */
    private String creditCodeOf(String raw, Long excludeInstitutionId) {
        String cc = CreditCode.normalize(raw);
        if (cc == null) {
            return null;
        }
        cc = CreditCode.require(cc);
        LambdaQueryWrapper<OrgInstitution> w = new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getCreditCode, cc);
        if (excludeInstitutionId != null) {
            w.ne(OrgInstitution::getId, excludeInstitutionId);
        }
        if (institutionMapper.selectCount(w) > 0) {
            throw BizException.badRequest("统一社会信用代码已被其它机构使用：" + cc);
        }
        return cc;
    }

    // ------------------------------------------------------------------ B1 建档

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> create(AuthUser actor, Map<String, Object> body) {
        // 作用租户必须与**列表/详情**同一口径（resolveRequestTenant），否则平台管理员
        // （tenantId 恒为 0）建出来的机构会落到 tenant_id=0，任何租户的列表都查不到它
        // —— 实测缺陷「admin 新增机构后不显示」的根因（留痕：org_institution id=87 code=ttt）。
        Long tenantId = guard.resolveRequestTenant(actor);
        String name = Vals.require(body, "name", "机构名称");
        String code = Vals.require(body, "code", "机构编码");
        // 机构类型：未知取值直接 400（带可选清单），不做静默降级 —— 猜错类型会把统计口径悄悄改掉。
        String orgType = OrgInstitution.requireOrgType(
                Vals.str(body, "orgType", OrgInstitution.TYPE_ENTERPRISE));

        if (institutionMapper.selectCount(new LambdaQueryWrapper<OrgInstitution>()
                .eq(OrgInstitution::getTenantId, tenantId)
                .eq(OrgInstitution::getCode, code)) > 0) {
            throw BizException.badRequest("机构编码已存在：" + code);
        }

        OrgInstitution it = new OrgInstitution();
        it.setTenantId(tenantId);
        it.setName(name);
        it.setCode(code);
        it.setOrgType(orgType);
        it.setCreditCode(creditCodeOf(Vals.str(body, "creditCode"), null));
        it.setLegalPerson(Vals.str(body, "legalPerson"));
        it.setContactMobile(Vals.str(body, "contactMobile"));
        it.setContactEmail(Vals.str(body, "contactEmail"));
        it.setStatus(OrgInstitution.STATUS_ACTIVE);
        it.setEstablishedAt(Vals.date(body, "establishedAt"));
        it.setRemark(Vals.str(body, "remark"));
        it.setOnboardStep(1);
        it.setCreatedAt(LocalDateTime.now());
        it.setCreatedBy(actor.getUserId());
        institutionMapper.insert(it);

        // FR-B2：同一事务内指定企业管理员（可空，后续通过交接接口补）
        Long adminUserId = Vals.lngObj(body, "adminUserId");
        String adminUsername = Vals.str(body, "adminUsername");
        String adminName = Vals.str(body, "adminName");
        if (adminUserId != null || adminUsername != null) {
            bindAdmin(actor, it, adminUserId, adminUsername, adminName, true);
            it.setOnboardStep(2);
            it.setUpdatedAt(LocalDateTime.now());
            institutionMapper.updateById(it);
        }

        audit.record(tenantId, it.getId(), actor, "INSTITUTION_CREATE", "INSTITUTION", it.getId(),
                "新建机构「" + name + "」（编码 " + code + "）", null, toView(it));
        // 新机构入驻完成 → 通知能力域做租户级初始化（数字员工预置）。
        // 监听方幂等且自行吞异常，故此处失败不会影响入驻主流程。
        events.publishEvent(new TenantProvisionedEvent(tenantId, it.getId(), name));
        return toView(it);
    }

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> update(AuthUser actor, Long id, Map<String, Object> body) {
        Long tenantId = guard.resolveRequestTenant(actor);
        OrgInstitution it = require(tenantId, id);
        Map<String, Object> before = toView(it);

        String newCode = Vals.str(body, "code");
        if (newCode != null && !newCode.equals(it.getCode())) {
            if (institutionMapper.selectCount(new LambdaQueryWrapper<OrgInstitution>()
                    .eq(OrgInstitution::getTenantId, tenantId)
                    .eq(OrgInstitution::getCode, newCode)
                    .ne(OrgInstitution::getId, id)) > 0) {
                throw BizException.badRequest("机构编码已存在：" + newCode);
            }
            it.setCode(newCode);
        }
        if (Vals.str(body, "name") != null) {
            it.setName(Vals.str(body, "name"));
        }
        if (Vals.str(body, "orgType") != null) {
            it.setOrgType(OrgInstitution.requireOrgType(Vals.str(body, "orgType")));
        }
        if (body != null && body.containsKey("creditCode")) {
            it.setCreditCode(creditCodeOf(Vals.str(body, "creditCode"), id));
        }
        if (body != null && body.containsKey("legalPerson")) {
            it.setLegalPerson(Vals.str(body, "legalPerson"));
        }
        if (body != null && body.containsKey("contactMobile")) {
            it.setContactMobile(Vals.str(body, "contactMobile"));
        }
        if (body != null && body.containsKey("contactEmail")) {
            it.setContactEmail(Vals.str(body, "contactEmail"));
        }
        if (body != null && body.containsKey("remark")) {
            it.setRemark(Vals.str(body, "remark"));
        }
        if (Vals.date(body, "establishedAt") != null) {
            it.setEstablishedAt(Vals.date(body, "establishedAt"));
        }
        it.setUpdatedAt(LocalDateTime.now());
        institutionMapper.updateById(it);

        audit.record(tenantId, id, actor, "INSTITUTION_UPDATE", "INSTITUTION", id,
                "编辑机构「" + it.getName() + "」信息", before, toView(it));
        return toView(it);
    }

    /** FR-B1：停用 / 恢复 / 注销（敏感操作，前后值全量留痕）。 */
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> changeStatus(AuthUser actor, Long id, String action, String reason) {
        Long tenantId = guard.resolveRequestTenant(actor);
        OrgInstitution it = require(tenantId, id);
        Map<String, Object> before = toView(it);

        String target = switch (action == null ? "" : action.toUpperCase()) {
            case "SUSPEND", "DISABLE" -> OrgInstitution.STATUS_SUSPENDED;
            case "RESUME", "ENABLE" -> OrgInstitution.STATUS_ACTIVE;
            case "CLOSE", "CANCEL" -> OrgInstitution.STATUS_CLOSED;
            default -> throw BizException.badRequest("不支持的状态动作：" + action);
        };
        if (target.equals(it.getStatus())) {
            throw BizException.badRequest("机构当前已是「" + target + "」状态");
        }
        it.setStatus(target);
        it.setUpdatedAt(LocalDateTime.now());
        institutionMapper.updateById(it);

        String label = switch (target) {
            case OrgInstitution.STATUS_SUSPENDED -> "停用";
            case OrgInstitution.STATUS_ACTIVE -> "恢复";
            default -> "注销";
        };
        audit.record(tenantId, id, actor, "INSTITUTION_" + action.toUpperCase(), "INSTITUTION", id,
                label + "机构「" + it.getName() + "」"
                        + (reason == null || reason.isBlank() ? "" : "，原因：" + reason),
                before, toView(it));
        return toView(it);
    }

    // ------------------------------------------------------------------ B2 管理员指定 / 交接

    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> assignAdmin(AuthUser actor, Long institutionId,
                                           Map<String, Object> body) {
        Long tenantId = guard.resolveRequestTenant(actor);
        OrgInstitution it = require(tenantId, institutionId);
        Map<String, Object> before = toView(it);
        Long adminUserId = Vals.lngObj(body, "userId");
        String adminUsername = Vals.str(body, "username");
        String adminName = Vals.str(body, "name");
        Long newAdminId = bindAdmin(actor, it, adminUserId, adminUsername, adminName, true);

        // 交接：原管理员如仍绑定且非新管理员 → 解除企业管理员角色，避免双管理员
        Long oldAdmin = it.getAdminUserId();
        if (oldAdmin != null && !oldAdmin.equals(newAdminId)) {
            Long roleId = statMapper.selectRoleIdByCode(OrgGuard.ROLE_ORG_ADMIN);
            if (roleId != null) {
                statMapper.deleteUserRole(oldAdmin, roleId);
                memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                                .eq(OrgMember::getInstitutionId, institutionId)
                                .eq(OrgMember::getUserId, oldAdmin))
                        .forEach(m -> {
                            OrgMember patch = new OrgMember();
                            patch.setId(m.getId());
                            patch.setIsOrgAdmin(false);
                            patch.setUpdatedAt(LocalDateTime.now());
                            memberMapper.updateById(patch);
                        });
            }
        }
        it.setOnboardStep(Math.max(it.getOnboardStep() == null ? 0 : it.getOnboardStep(), 2));
        it.setUpdatedAt(LocalDateTime.now());
        institutionMapper.updateById(it);

        audit.record(tenantId, institutionId, actor, "INSTITUTION_ADMIN_HANDOVER", "INSTITUTION", institutionId,
                "指定 / 交接企业管理员 → " + it.getAdminName(), before, toView(it));
        return toView(it);
    }

    /** 绑定企业管理员：解析 / 创建账号 → 授予 ROLE_ORG_ADMIN → 建立（或更新）成员关系。 */
    private Long bindAdmin(AuthUser actor, OrgInstitution it, Long userId, String username,
                           String name, boolean asMember) {
        Long tenantId = it.getTenantId();
        Map<String, Object> target = accounts.resolveOrCreate(tenantId, userId, username, name,
                null, null, actor.getUserId());
        Long uid = AccountProvisioner.idOf(target);
        if (uid == null) {
            throw BizException.badRequest("企业管理员账号解析失败");
        }
        String nick = name != null && !name.isBlank()
                ? name : AccountProvisioner.nicknameOf(target, "用户#" + uid);
        accounts.grantRole(uid, OrgGuard.ROLE_ORG_ADMIN, actor.getUserId());

        if (asMember) {
            List<OrgMember> existing = memberMapper.selectList(new LambdaQueryWrapper<OrgMember>()
                    .eq(OrgMember::getInstitutionId, it.getId())
                    .eq(OrgMember::getUserId, uid));
            OrgMember m = existing.isEmpty() ? new OrgMember() : existing.get(0);
            m.setTenantId(tenantId);
            m.setInstitutionId(it.getId());
            if (m.getDepartmentId() == null) {
                m.setDepartmentId(0L);
            }
            m.setUserId(uid);
            m.setName(nick);
            m.setIsOrgAdmin(true);
            m.setStatus(OrgMember.STATUS_ACTIVE);
            m.setUpdatedAt(LocalDateTime.now());
            if (m.getId() == null) {
                m.setJoinedAt(LocalDate.now());
                m.setCreatedAt(LocalDateTime.now());
                m.setCreatedBy(actor.getUserId());
                memberMapper.insert(m);
            } else {
                memberMapper.updateById(m);
            }
        }

        it.setAdminUserId(uid);
        it.setAdminName(nick);
        return uid;
    }

    /** 供其它服务使用：机构管理员 userId → 姓名。 */
    public OrgInstitution requireByInstitution(Long institutionId) {
        OrgInstitution it = institutionMapper.selectById(institutionId);
        if (it == null) {
            throw BizException.notFound("机构不存在：" + institutionId);
        }
        return it;
    }
}
