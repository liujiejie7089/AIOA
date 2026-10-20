CREATE TABLE connector_mail_draft (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  user_id BIGINT NOT NULL,
  to_addr VARCHAR(512),
  cc_addr VARCHAR(512),
  subject VARCHAR(512),
  body MEDIUMTEXT,
  request_id VARCHAR(128),
  status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
  sent_at DATETIME(6),
  message_id VARCHAR(255),
  last_error VARCHAR(1024),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  PRIMARY KEY (id),
  UNIQUE KEY uk_mail_draft_req (tenant_id, user_id, request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
