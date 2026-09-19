package cn.aioa.bridge.service;

import cn.aioa.bridge.entity.ToolPermission;
import cn.aioa.bridge.mapper.ToolPermissionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 工具权限闸门：{@code tool_permission} 的角色级 ALLOW / DENY 判定。
 *
 * <p><b>为什么需要它</b>：{@code aioa-resource} 的 {@code ToolGatewayService} 只校验
 * 「所需角色」（工具自报的门槛），没有任何一处读取过 {@code tool_permission} 表 ——
 * 也就是说这张表从 V1 建好起就是死数据，管理端配的授权/禁用对运行时完全无效。
 * 桥接把这张表接进执行链，让「配置即生效」成立。</p>
 *
 * <p><b>判定口径</b>（显式且可解释，避免「配了就全禁」或「配了等于没配」两种极端）：</p>
 * <ol>
 *   <li>命中本角色的 {@code DENY} → 拒绝（DENY 永远优先，便于对个别角色开例外）；</li>
 *   <li>否则命中本角色的 {@code ALLOW} → 放行；</li>
 *   <li>否则该工具<b>存在 ALLOW 行</b> → 拒绝。存在 ALLOW 行说明这个工具被刻意
 *       「按名单开放」，名单外的人不该因为没写 DENY 而默认可调用；</li>
 *   <li>否则该工具只配了 DENY 行（黑名单模式）或<b>完全没有任何行</b>（默认开放）→ 放行。</li>
 * </ol>
 *
 * <p>作用域：本租户行 ∪ 平台级行（{@code tenant_id=0}），与注册表口径一致。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolPermissionService {

    public static final String EFFECT_ALLOW = "ALLOW";
    public static final String EFFECT_DENY = "DENY";

    private final ToolPermissionMapper permissionMapper;

    /** 判定结论：放行 / 拒绝 + 可读原因（原因会写进调用日志与响应，便于自查）。 */
    public record Decision(boolean allowed, String reason) {

        public static Decision allow(String reason) {
            return new Decision(true, reason);
        }

        public static Decision deny(String reason) {
            return new Decision(false, reason);
        }
    }

    /**
     * 判定某角色集合能否调用某工具。
     *
     * @param roles 调用者角色码集合（可能为空 = 无角色，此时仅在「工具无任何授权行」时放行）
     */
    public Decision check(Long tenantId, String toolCode, Collection<String> roles) {
        if (toolCode == null || toolCode.isBlank()) {
            return Decision.deny("工具编码为空");
        }
        Set<String> myRoles = new LinkedHashSet<>();
        if (roles != null) {
            for (String r : roles) {
                if (r != null && !r.isBlank()) {
                    myRoles.add(r);
                }
            }
        }
        List<ToolPermission> rows = permissionMapper.selectList(new LambdaQueryWrapper<ToolPermission>()
                .eq(ToolPermission::getToolCode, toolCode)
                .isNull(ToolPermission::getDeletedAt));
        if (rows.isEmpty()) {
            // 未配置任何授权行 = 默认开放给任意已认证调用方（保持既有工具「免配置即可用」）
            return Decision.allow("工具未配置角色授权，默认放行");
        }
        long tid = tenantId == null ? ToolRegistryService.GLOBAL_TENANT_ID : tenantId;
        List<ToolPermission> scoped = new ArrayList<>();
        for (ToolPermission p : rows) {
            long t = p.getTenantId() == null ? ToolRegistryService.GLOBAL_TENANT_ID : p.getTenantId();
            if (t == ToolRegistryService.GLOBAL_TENANT_ID || t == tid) {
                scoped.add(p);
            }
        }
        if (scoped.isEmpty()) {
            return Decision.allow("本租户未配置该工具的角色授权，默认放行");
        }
        boolean hasAllowRow = false;
        for (ToolPermission p : scoped) {
            if (EFFECT_ALLOW.equalsIgnoreCase(p.getEffect())) {
                hasAllowRow = true;
                break;
            }
        }
        // 1) DENY 优先
        for (ToolPermission p : scoped) {
            if (p.getRoleCode() != null && myRoles.contains(p.getRoleCode())
                    && EFFECT_DENY.equalsIgnoreCase(p.getEffect())) {
                log.info("工具权限拒绝：tool={}, tenant={}, role={}", toolCode, tid, p.getRoleCode());
                return Decision.deny("角色 " + p.getRoleCode() + " 已被显式禁止调用该工具");
            }
        }
        // 2) ALLOW 命中
        for (ToolPermission p : scoped) {
            if (p.getRoleCode() != null && myRoles.contains(p.getRoleCode())
                    && EFFECT_ALLOW.equalsIgnoreCase(p.getEffect())) {
                return Decision.allow("角色 " + p.getRoleCode() + " 已获授权");
            }
        }
        // 3) 白名单模式：存在 ALLOW 行但都不是我
        if (hasAllowRow) {
            log.info("工具权限拒绝（白名单模式）：tool={}, tenant={}, roles={}", toolCode, tid, myRoles);
            return Decision.deny("该工具仅对已授权角色开放，当前角色（"
                    + (myRoles.isEmpty() ? "无" : String.join("/", myRoles)) + "）不在授权名单内");
        }
        // 4) 仅 DENY 行 = 黑名单模式，非黑即白
        return Decision.allow("工具为黑名单模式，当前角色不在禁止名单内");
    }
}
