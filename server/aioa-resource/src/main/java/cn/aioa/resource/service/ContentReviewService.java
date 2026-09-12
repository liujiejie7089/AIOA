package cn.aioa.resource.service;

import cn.aioa.resource.entity.SysConfig;
import cn.aioa.resource.mapper.SysConfigMapper;
import cn.aioa.resource.support.PermissionCatalog;
import cn.aioa.security.AuthUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * 内容审核态判定（V34）：租户管理员创建的内容需上一级（平台管理员）审核。
 *
 * <p>为什么是「开关 + 角色」两层判定，而不是写死：</p>
 * <ul>
 *   <li><b>角色</b>：平台管理员自己是最高级，再要求他审自己没有意义，故豁免；
 *       企业管理员 / 部门负责人创建的是机构内部资产，其上级是租户管理员，
 *       若一并纳入会牵出「租户管理员审核台」这一整套新界面，本期只按需求覆盖租户管理员这一级。</li>
 *   <li><b>开关</b>：灰度期或紧急放行时，运维改一条 sys_config 即可，不必重新发版。</li>
 * </ul>
 *
 * <p>审核态与运行态正交：待审内容不被调度、不对普通成员可见，
 * 但创建者本人与平台管理员始终可见，否则会出现「提交了却消失」的困惑。</p>
 */
@Service
@RequiredArgsConstructor
public class ContentReviewService {

    /** 平台开关键：开启后租户管理员创建的内容进入待审。 */
    public static final String KEY_APPROVAL_TENANT_CONTENT = "approval.tenant.content";

    public static final String PENDING = "PENDING";
    public static final String APPROVED = "APPROVED";
    public static final String REJECTED = "REJECTED";

    private final SysConfigMapper configMapper;

    /** 开关是否开启（默认 true：缺省即按「需审核」处理，安全侧优先）。 */
    public boolean enabled() {
        SysConfig row = configMapper.selectOne(new LambdaQueryWrapper<SysConfig>()
                .eq(SysConfig::getTenantId, 0L)
                .eq(SysConfig::getConfigKey, KEY_APPROVAL_TENANT_CONTENT)
                .last("LIMIT 1"));
        if (row == null) {
            return true;
        }
        String v = row.getConfigValue() != null && !row.getConfigValue().isBlank()
                ? row.getConfigValue() : row.getDefaultValue();
        return v == null || v.isBlank() || Boolean.parseBoolean(v.trim());
    }

    /**
     * 该用户创建的内容是否需送审。
     *
     * <p>口径：开关开启 且 是租户管理员 且 不是平台管理员。</p>
     */
    public boolean needsReview(AuthUser user) {
        if (user == null || !enabled()) {
            return false;
        }
        if (PermissionCatalog.isPlatformAdmin(user)) {
            return false;
        }
        return PermissionCatalog.hasRole(user, PermissionCatalog.ROLE_TENANT_ADMIN);
    }

    /** 创建时按判定结果给出初始审核态。 */
    public String initialStatus(AuthUser user) {
        return needsReview(user) ? PENDING : APPROVED;
    }

    /**
     * 该内容对当前用户是否可见。
     *
     * <p>待审内容不对外可见，但对「创建者本人 + 平台管理员 + 本租户管理员」可见 ——
     * 否则创建者提交后看不到自己的东西，会以为创建失败。</p>
     */
    public boolean visible(String auditStatus, AuthUser viewer, Long createdBy) {
        if (auditStatus == null || auditStatus.isBlank() || APPROVED.equalsIgnoreCase(auditStatus)) {
            return true;
        }
        if (viewer == null) {
            return false;
        }
        if (PermissionCatalog.isPlatformAdmin(viewer) || PermissionCatalog.isAdmin(viewer)) {
            return true;
        }
        return PermissionCatalog.isCreator(viewer, createdBy);
    }
}
