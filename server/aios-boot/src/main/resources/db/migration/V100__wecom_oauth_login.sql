-- V100: 企业微信 OAuth 网页授权「静默登录」两表（用户零填写企微配置）
-- 链路：/api/v1/auth/wecom/start 生成一次性 state → 授权页 → callback 用 code 换
-- userid+user_ticket→getuserdetail(biz_mail) → 命中 wecom_login_binding 直接签发本地令牌；
-- 未命中 → 身份暂存 wecom_login_pending，H5 引导本地登录后 bind 建立绑定。
-- 纪律：state 一次性（used_at 即废）+ 10 分钟 TTL；wecom_userid 全局唯一（tenant+userid）。

CREATE TABLE wecom_login_binding (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  wecom_userid VARCHAR(64) NOT NULL COMMENT '企业微信 userid',
  biz_mail VARCHAR(256) DEFAULT NULL COMMENT '授权时拿到的企业邮箱（可能为空）',
  name VARCHAR(128) DEFAULT NULL COMMENT '授权时拿到的姓名',
  user_id BIGINT NOT NULL COMMENT '绑定的本地账号 id',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_wecom_login_userid (tenant_id, wecom_userid),
  KEY idx_wecom_login_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 待绑定态：start 时建行（identity 为空），callback 换到身份后回填；
-- 本地登录完成后 /bind 消费（used_at 即废）。10 分钟 TTL，过期行由清理任务/后续迁移处理。
CREATE TABLE wecom_login_pending (
  state VARCHAR(64) NOT NULL,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  wecom_userid VARCHAR(64) DEFAULT NULL,
  biz_mail VARCHAR(256) DEFAULT NULL,
  name VARCHAR(128) DEFAULT NULL,
  origin VARCHAR(512) NOT NULL,
  return_path VARCHAR(512) NOT NULL DEFAULT '/',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  used_at DATETIME(6) DEFAULT NULL,
  PRIMARY KEY (state),
  KEY idx_wecom_pending_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
