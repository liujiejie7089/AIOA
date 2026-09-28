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
 *
 * <p><b>2026-09-28 补：开户口令可由调用方指定</b>。此前开户一律写死 {@link #DEMO_PASSWORD_HASH}，
 * 而管理端「新增员工（自动开户）」表单既没有密码输入、成功后也不回显口令 ——
 * 操作员**无从得知**新员工的登录口令，现象就是用户反馈的「新增的员工无法登录用户端」。
 * 现支持传明文 {@code password}（留空仍走默认哈希，保持既有可复现性）。</p>
 */
@Component
@RequiredArgsConstructor
public class AccountProvisioner {

    /** 入驻演示统一口令 User@123（与 V6 zhangsan 同哈希）。 */
    public static final String DEMO_PASSWORD_HASH =
            "$2a$10$im/HCvwBC3ILW2QMG.ZAEOK5LlQonpQy2MSeWYNznDHFDLZ3v2hsS";

    /** 演示统一明文口令（回显给操作员用，与 {@link #DEMO_PASSWORD_HASH} 必须一致）。 */
    public static final String DEMO_PASSWORD = "User@123";

    private final OrgStatMapper statMapper;
    private final org.springframework.security.crypto.password.PasswordEncoder passwordEncoder;

    /** 按 userId 或 username 解析账号；都不存在且给了 username 则开户（口令 = 演示默认）。 */
    public Map<String, Object> resolveOrCreate(Long tenantId, Long userId, String username,
                                               String name, String mobile, String email,
                                               Long operatorId) {
        return resolveOrCreate(tenantId, userId, username, name, mobile, email, operatorId, null);
    }

    /**
     * 同上，但可指定初始口令。
     *
     * @param plainPassword 明文初始口令；{@code null}/空白 ⇒ 用演示默认 {@link #DEMO_PASSWORD}
     */
    public Map<String, Object> resolveOrCreate(Long tenantId, Long userId, String username,
                                               String name, String mobile, String email,
                                               Long operatorId, String plainPassword) {
        String hash = hashOf(plainPassword);
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
        // username 上有唯一键且覆盖软删行：若存在同名「已软删」账号，复活它而不是再插一条。
        // 否则重复建机构 / 换绑同名管理员会撞唯一键，直接 500（原缺陷）。
        Map<String, Object> deleted = statMapper.selectDeletedUserByUsername(username);
        if (deleted != null) {
            Long deletedId = idOf(deleted);
            String reviveNick = name == null || name.isBlank() ? username : name;
            statMapper.reviveUser(deletedId, tenantId == null ? 0L : tenantId, reviveNick,
                    mobile, email, hash);
            Map<String, Object> revived = statMapper.selectUserByUsername(username);
            if (revived == null) {
                throw BizException.badRequest("账号恢复失败：" + username);
            }
            return revived;
        }
        Map<String, Object> row = new HashMap<>();
        row.put("tenantId", tenantId == null ? 0L : tenantId);
        row.put("username", username);
        row.put("passwordHash", hash);
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

    /** 明文口令 → BCrypt 哈希；空白 ⇒ 演示默认哈希（与 V6 种子同值，不走编码器）。 */
    public String hashOf(String plainPassword) {
        if (plainPassword == null || plainPassword.isBlank()) {
            return DEMO_PASSWORD_HASH;
        }
        return passwordEncoder.encode(plainPassword);
    }

    /**
     * 本次开户实际生效的**明文**口令（供调用方回显给操作员）。
     *
     * <p>与 {@link #hashOf} 同源：这里判空的分支必须与那里一致，否则回显的口令会和真正写入的哈希对不上 ——
     * 那是比"不回显"更坏的结果（操作员拿着一个错的凭据去试）。</p>
     */
    public static String effectivePassword(String plainPassword) {
        return plainPassword == null || plainPassword.isBlank() ? DEMO_PASSWORD : plainPassword;
    }

    /**
     * 该账号是否已存在（含软删行 —— 软删行同样占 username 唯一键，复活时口令会被本次下发覆盖）。
     *
     * <p>调用方据此决定「要不要告诉操作员初始口令」：账号本来就存在时口令**不会**被改动，
     * 此时回显一个"初始口令"就是假话。</p>
     */
    public boolean usernameExists(String username) {
        if (username == null || username.isBlank()) {
            return false;
        }
        return statMapper.selectUserByUsername(username) != null
                || statMapper.selectDeletedUserByUsername(username) != null;
    }

    /** 重置某账号的登录口令（明文空白 ⇒ 复位为演示默认）。 */
    public void resetPassword(Long userId, String plainPassword) {
        if (statMapper.updateUserPassword(userId, hashOf(plainPassword)) == 0) {
            throw BizException.notFound("账号不存在：" + userId);
        }
    }

    /**
     * 批量取账号（{@code userId → 账号行}）—— 员工名册列表补「账号」列用。
     *
     * <p>放在本类而非调用方：跨域读 {@code sys_user} 的口径只应有这一个出口，
     * 否则「账号」会在多处各查一次、字段各异。</p>
     */
    public Map<Long, Map<String, Object>> usersByIds(java.util.List<Long> ids) {
        Map<Long, Map<String, Object>> out = new HashMap<>();
        if (ids == null || ids.isEmpty()) {
            return out;
        }
        for (Map<String, Object> row : statMapper.selectUsersByIds(ids)) {
            Long id = idOf(row);
            if (id != null) {
                out.put(id, row);
            }
        }
        return out;
    }

    public Long grantRole(Long userId, String roleCode, Long operatorId) {
        Long roleId = statMapper.selectRoleIdByCode(roleCode);
        if (roleId == null) {
            throw BizException.badRequest("角色未初始化：" + roleCode);
        }
        if (statMapper.selectUserRole(userId, roleId) == null) {
            // 与 sys_user.username 同型：uk_sys_user_role 覆盖软删行，直接 INSERT 会撞唯一键 500。
            // 现场：移除员工（deleteMember 会 revokeRole 软删该行）后，用**同一账号**再新增员工 ⇒ 500。
            if (statMapper.reviveUserRole(userId, roleId, operatorId) == 0) {
                statMapper.insertUserRole(0L, userId, roleId, operatorId);
            }
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
