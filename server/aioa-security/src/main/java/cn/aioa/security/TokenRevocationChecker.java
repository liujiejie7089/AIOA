package cn.aioa.security;

/**
 * 令牌吊销校验（D-1）—— 由<b>具备数据访问能力</b>的模块实现，安全模块只依赖这个契约。
 *
 * <p>为什么定义成接口而不在 security 模块直接查库：{@code aioa-security} 刻意不依赖
 * 持久层（它只依赖 common + spring-security + jjwt），这样它才能被任何模块复用而不
 * 把数据源拖进去。这与 {@link RoleResolver} / {@link PermissionResolver} 是同一套做法 ——
 * 安全模块声明「我需要什么」，业务模块提供实现。</p>
 *
 * <p><b>失败方向</b>：实现方在数据库异常时应当<b>返回 false（视为未吊销）</b>并留 warn 日志。
 * 理由是 DB 不可用时整个系统的业务查询已经全部失败，此时把所有请求判为 401 只会
 * 让「数据库故障」额外伪装成「认证故障」，把排查方向带偏；而吊销校验失去作用的那几秒
 * 里，请求本身也到不了任何业务逻辑。</p>
 */
public interface TokenRevocationChecker {

    /**
     * 该令牌是否已被吊销。
     *
     * @param jti 令牌的 {@code jti} 声明；为 null（V46 之前签发的旧令牌）时一律返回 false
     */
    boolean isRevoked(String jti);
}
