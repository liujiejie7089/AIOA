package cn.aioa.org.support;

import cn.aioa.common.exception.BizException;
import cn.aioa.org.mapper.OrgStatMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * 账号供给：企业入驻场景下按需开户（企业管理员交接 / 员工新增 / 批量导入）。
 *
 * <p>统一口令 User@123 的 BCrypt 哈希与 V6 种子一致，避免依赖 PasswordEncoder Bean，
 * 也保证演示环境可确定性复现。</p>
 */
@Component
@RequiredArgsConstructor
public class AccountProvisioner {

    /** 入驻演示统一口令 User@123（与 V6 zhangsan 同哈希）。 */
    public static final String DEMO_PASSWORD_HASH =
            "$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS";

    private final OrgStatMapper statMapper;

    /** 按 userId 或 username 解析账号；都不存在且给了 username 则开户。 */
    public Map<String, Object> resolveOrCreate(Long tenantId, Long userId, String username,
                                               String name, String mobile, String email,
                                               Long operatorId) {
        Map<String, Object> target = null;
        if (userId != null) {
            target = statMapper.selectUser(userId);
            if (target == null) {
                throw BizException.notFound("用户不存在：" + userId);
            }
        } else if (username != null) {
            target = statMapper.selectUserByUsername(username);
        }
        if (target != null) {
            return target;
        }
        if (username == null) {
            throw BizException.badRequest("请提供账号（username 或 userId）");
        }
        Map<String, Object> row = new HashMap<>();
        row.put("tenantId", tenantId == null ? 0L : tenantId);
        row.put("username", username);
        row.put("passwordHash", DEMO_PASSWORD_HASH);
        row.put("nickname", name == null || name.isBlank() ? username : name);
        row.put("mobile", mobile);
        row.put("email", email);
        row.put("createdBy", operatorId);
        statMapper.insertUser(row);
        Map<String, Object> created = statMapper.selectUserByUsername(username);
        if (created == null) {
            throw BizException.badRequest("账号创建失败：" + username);
        }
        return created;
    }

    public Long grantRole(Long userId, String roleCode, Long operatorId) {
        Long roleId = statMapper.selectRoleIdByCode(roleCode);
        if (roleId == null) {
            throw BizException.badRequest("角色未初始化：" + roleCode);
        }
        if (statMapper.selectUserRole(userId, roleId) == null) {
            statMapper.insertUserRole(0L, userId, roleId, operatorId);
        }
        return roleId;
    }

    public void revokeRole(Long userId, String roleCode) {
        Long roleId = statMapper.selectRoleIdByCode(roleCode);
        if (roleId != null) {
            statMapper.deleteUserRole(userId, roleId);
        }
    }

    public static Long idOf(Map<String, Object> userRow) {
        Object v = userRow == null ? null : userRow.get("id");
        return v instanceof Number n ? n.longValue() : null;
    }

    public static String nicknameOf(Map<String, Object> userRow, String fallback) {
        Object v = userRow == null ? null : userRow.get("nickname");
        String s = v == null ? null : String.valueOf(v);
        return s == null || s.isBlank() ? fallback : s;
    }
}
