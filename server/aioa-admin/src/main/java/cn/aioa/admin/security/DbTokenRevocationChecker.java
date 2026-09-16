package cn.aioa.admin.security;

import cn.aioa.security.JwtTokenProvider;
import cn.aioa.security.TokenRevocationChecker;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 令牌吊销的持久化实现（D-1）。
 *
 * <p>表 {@code revoked_token}（V46）按 {@code jti} 唯一，查询走唯一索引 ——
 * 一次认证多一条索引命中，代价可接受，换来的是「登出即刻失效」这个
 * 用户视为理所当然的语义。</p>
 *
 * <p><b>为什么不做内存缓存</b>：缓存会引入「吊销生效延迟」，
 * 而登出是安全动作，延迟生效等于给了攻击者一个可观测的窗口。
 * 唯一索引命中的开销远小于这个风险。</p>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DbTokenRevocationChecker implements TokenRevocationChecker {

    private final JdbcTemplate jdbc;

    @Override
    public boolean isRevoked(String jti) {
        if (jti == null || jti.isBlank()) {
            return false;
        }
        try {
            Long n = jdbc.queryForObject("SELECT COUNT(*) FROM revoked_token WHERE jti = ?",
                    Long.class, jti);
            return n != null && n > 0;
        } catch (Exception e) {
            // 失败方向：DB 异常时视为「未吊销」。此时业务查询本身已全部失败，
            // 若再返回 401，会把「数据库故障」伪装成「认证故障」。
            log.warn("吊销校验失败（按未吊销处理）：jti={} err={}", jti, e.getMessage());
            return false;
        }
    }

    /**
     * 写入一条吊销记录（登出时调用）。
     *
     * <p>幂等：同一 jti 重复登出不报错（唯一键冲突用 {@code INSERT IGNORE} 吸收）。
     * 顺手清理已过期记录，避免依赖外部定时任务。</p>
     *
     * @return 是否新写入（false = 之前已吊销过）
     */
    public boolean revoke(String jti, Long userId, String tokenType,
                          LocalDateTime expiresAt, String reason) {
        if (jti == null || jti.isBlank()) {
            return false;
        }
        try {
            purgeExpired();
            int n = jdbc.update("INSERT IGNORE INTO revoked_token "
                            + "(jti, user_id, token_type, expires_at, revoked_at, reason) "
                            + "VALUES (?, ?, ?, ?, NOW(6), ?)",
                    jti, userId,
                    tokenType == null ? JwtTokenProvider.TYPE_ACCESS : tokenType,
                    expiresAt == null ? null : java.sql.Timestamp.valueOf(expiresAt),
                    reason);
            return n > 0;
        } catch (Exception e) {
            // 登出写入失败不影响登出本身（接口必须幂等且永不失败），但要留下痕迹：
            // 这条日志意味着「该令牌仍将有效到自然过期」，是需要被看见的异常。
            log.warn("吊销写入失败：jti={} userId={} err={}", jti, userId, e.getMessage());
            return false;
        }
    }

    /** 清理已过期记录（过期令牌本就无效，再留着只是占空间）。 */
    public int purgeExpired() {
        try {
            return jdbc.update("DELETE FROM revoked_token WHERE expires_at IS NOT NULL "
                    + "AND expires_at < DATE_SUB(NOW(6), INTERVAL 1 DAY)");
        } catch (Exception e) {
            log.warn("清理过期吊销记录失败：{}", e.getMessage());
            return 0;
        }
    }
}
