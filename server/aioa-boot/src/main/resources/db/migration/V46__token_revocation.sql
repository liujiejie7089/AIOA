-- ===========================================================================
-- V46 · 令牌吊销表（已知缺口 D-1：无状态 JWT 无服务端吊销）
-- ===========================================================================
-- 问题：本系统用无状态 JWT，登出只在客户端丢弃令牌 —— 令牌在 TTL 内始终有效。
--   实测可复现：登出后用同一 token 继续调受保护接口，仍返回 200。
--   「退出登录」在用户认知里是安全动作，必须让旧令牌立刻失效。
--
-- 方案：给 access / refresh 令牌加 JWT 标准声明 `jti`（唯一标识），
--   登出时把该 jti 写入本表；认证过滤器在校验签名/有效期之后**额外**查一次吊销表。
--
-- 为什么按 jti 而不是「用户级失效水位」：
--   jti 方案只让**本次登出的那个令牌**失效，用户在另一台设备上的会话不受影响；
--   水位方案会把该用户所有设备的会话一起踢下线，属行为放大。
--
-- 过期清理：expires_at 记录原令牌的过期时间，过期后本行失去意义，可被清理
--   （服务端在写入时顺手清理，无需外部定时任务，见 DbTokenRevocationChecker）。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V45，故本文件为 V46。
-- ===========================================================================
CREATE TABLE IF NOT EXISTS `revoked_token` (
    `id`         BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `jti`        VARCHAR(64) NOT NULL COMMENT '被吊销令牌的 JWT jti 声明（唯一）',
    `user_id`    BIGINT      NULL COMMENT '归属用户（便于按人排查；令牌无 uid 时为 NULL）',
    `token_type` VARCHAR(16) NOT NULL DEFAULT 'access' COMMENT 'access / refresh',
    `expires_at` DATETIME(6) NULL COMMENT '原令牌的过期时间：到期后本行可清理',
    `revoked_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '吊销时间',
    `reason`     VARCHAR(64) NULL COMMENT '吊销原因，如 LOGOUT',
    UNIQUE KEY `uk_revoked_token_jti` (`jti`),
    KEY `idx_revoked_token_exp` (`expires_at`),
    KEY `idx_revoked_token_user` (`user_id`, `revoked_at`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT '已吊销的 JWT（D-1 服务端登出即失效）';
