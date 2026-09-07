package cn.aioa.security;

import cn.aioa.common.exception.BizException;

/**
 * 登录用户上下文（ThreadLocal）。
 */
public final class AuthUserContext {

    private static final ThreadLocal<AuthUser> HOLDER = new ThreadLocal<>();

    private AuthUserContext() {
    }

    public static void set(AuthUser user) {
        HOLDER.set(user);
    }

    public static AuthUser get() {
        return HOLDER.get();
    }

    public static AuthUser require() {
        AuthUser user = HOLDER.get();
        if (user == null) {
            throw BizException.unauthorized("登录状态缺失");
        }
        return user;
    }

    public static Long requireUserId() {
        return require().getUserId();
    }

    public static Long tenantIdOrDefault() {
        AuthUser user = HOLDER.get();
        return user == null || user.getTenantId() == null ? 0L : user.getTenantId();
    }

    public static void clear() {
        HOLDER.remove();
    }
}
