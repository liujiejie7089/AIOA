CREATE TABLE connector_def (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  group_name VARCHAR(64) NOT NULL,
  icon VARCHAR(64) NOT NULL,
  summary VARCHAR(255) NOT NULL,
  auth_mode VARCHAR(32) NOT NULL,
  config_keys TEXT,
  help_text VARCHAR(1024),
  help_url VARCHAR(512),
  sort INT NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_connector_def_tenant_code (tenant_id, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE connector_tenant_config (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  connector_code VARCHAR(64) NOT NULL,
  secret_json TEXT,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  updated_by BIGINT,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_tenant_config (tenant_id, connector_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE connector_connection (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  user_id BIGINT NOT NULL,
  connector_code VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'NEED_AUTH',
  account_label VARCHAR(255),
  credential_json TEXT,
  expires_at DATETIME(6),
  last_error VARCHAR(1024),
  connected_at DATETIME(6),
  last_checked_at DATETIME(6),
  disconnected_at DATETIME(6),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_connection (tenant_id, user_id, connector_code),
  KEY idx_connection_code (tenant_id, connector_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE connector_oauth_state (
  state VARCHAR(64) NOT NULL,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  user_id BIGINT NOT NULL,
  connector_code VARCHAR(64) NOT NULL,
  return_path VARCHAR(512) NOT NULL,
  origin VARCHAR(512) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  used_at DATETIME(6),
  PRIMARY KEY (state),
  KEY idx_oauth_state_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO connector_def (tenant_id, code, name, group_name, icon, summary, auth_mode, config_keys, help_text, help_url, sort, status)
VALUES (0, 'qq_mail', 'QQ邮箱', '邮箱', 'mail', '接收与发送邮件', 'CREDENTIAL', '[]', 'QQ邮箱→设置→账户→开启 IMAP/SMTP 服务→生成授权码', '', 10, 'ACTIVE');

INSERT INTO connector_def (tenant_id, code, name, group_name, icon, summary, auth_mode, config_keys, help_text, help_url, sort, status)
VALUES (0, 'wechat_work', '企业微信', '协作与办公', 'people', '接收消息、以我的身份发送消息', 'OAUTH2', '["corpId","agentId","corpSecret"]', '需在企业管理后台创建自建应用（corpId / agentId / corpSecret）后发起授权', '', 20, 'ACTIVE');
