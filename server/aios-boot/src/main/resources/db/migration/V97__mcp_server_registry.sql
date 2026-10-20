-- docs/59 §10.3 MCP 服务器注册表 + 信任闸门 + 内置工具桥接
-- 仅新增三张表与种子；不改动 V96 及 connector_* 既有表。

CREATE TABLE mcp_server (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  code VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  source VARCHAR(16) NOT NULL,
  transport VARCHAR(16) NOT NULL,
  command VARCHAR(255) NULL,
  args_json TEXT NULL,
  env_enc TEXT NULL,
  url VARCHAR(512) NULL,
  headers_enc TEXT NULL,
  trusted TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN',
  last_error VARCHAR(1024) NULL,
  last_probe_at DATETIME(6) NULL,
  connector_code VARCHAR(64) NULL,
  sort INT NOT NULL DEFAULT 100,
  created_by BIGINT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_mcp_server (tenant_id, code),
  KEY idx_mcp_server_trusted (tenant_id, trusted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE mcp_server_tool (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  server_id BIGINT NOT NULL,
  name VARCHAR(128) NOT NULL,
  description VARCHAR(1024) NULL,
  input_schema MEDIUMTEXT NULL,
  read_only TINYINT(1) NOT NULL DEFAULT 0,
  sort INT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_mcp_tool (server_id, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE mcp_tool_audit (
  id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL DEFAULT 0,
  user_id BIGINT NULL,
  server_code VARCHAR(64) NOT NULL,
  tool_name VARCHAR(128) NOT NULL,
  args_digest VARCHAR(64) NULL,
  ok TINYINT(1) NOT NULL DEFAULT 0,
  error VARCHAR(512) NULL,
  duration_ms BIGINT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_mcp_audit (tenant_id, server_code, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 内置服务器种子（均为 BUILTIN，trusted=0，需经信任闸门探测后才对 agent 可见）
INSERT INTO mcp_server (id, tenant_id, code, name, source, transport, trusted, status, connector_code, sort, created_by)
VALUES
  (1, 0, 'qq_mail', 'QQ邮箱', 'BUILTIN', 'STREAMABLE_HTTP', 0, 'UNKNOWN', 'qq_mail', 10, 0),
  (2, 0, 'wechat_work', '企业微信', 'BUILTIN', 'STREAMABLE_HTTP', 0, 'UNKNOWN', 'wechat_work', 20, 0);

-- qq_mail 内置工具目录（6 个，严格对齐 docs/59 §10.3；前 4 个只读）
-- 纪律：工具名/参数名必须与 cn.aios.resource.connector.mail.MailMcpHandler 逐字一致，
--       否则「信任」写入的目录会让模型调出 handler 不认识的工具（supports() 返回 false）。
INSERT INTO mcp_server_tool (tenant_id, server_id, name, description, input_schema, read_only, sort)
VALUES
  (0, 1, 'list_folders', '列出邮箱的文件夹（收件箱、已发送等），用于确认 folder 参数取值',
   '{"type":"object","properties":{}}', 1, 1),
  (0, 1, 'list_messages', '列出指定文件夹最近的邮件摘要（发件人/主题/时间/是否未读）',
   '{"type":"object","properties":{"folder":{"type":"string","description":"文件夹名，默认 INBOX"},"limit":{"type":"integer","description":"返回条数，默认 10，最大 30"},"unreadOnly":{"type":"boolean","description":"只返回未读邮件，默认 false"}},"required":[]}', 1, 2),
  (0, 1, 'read_message', '读取单封邮件的正文（只读；不会把邮件标记为已读）',
   '{"type":"object","properties":{"uid":{"type":"integer","description":"邮件 UID，来自 list_messages / search_messages 的返回"},"folder":{"type":"string","description":"文件夹名，默认 INBOX"}},"required":["uid"]}', 1, 3),
  (0, 1, 'search_messages', '按关键词搜索邮件（IMAP TEXT 搜索，匹配主题与正文）',
   '{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"},"folder":{"type":"string","description":"文件夹名，默认 INBOX"},"limit":{"type":"integer","description":"返回条数，默认 10，最大 30"}},"required":["query"]}', 1, 4),
  (0, 1, 'create_draft', '创建邮件草稿（不发送）。用户确认后必须再调 send_draft 才真正发出',
   '{"type":"object","properties":{"to":{"type":"string","description":"收件人邮箱，多个用逗号分隔"},"subject":{"type":"string","description":"主题"},"body":{"type":"string","description":"正文纯文本"},"cc":{"type":"string","description":"抄送，可空"}},"required":["to","subject","body"]}', 0, 5),
  (0, 1, 'send_draft', '发送已创建的草稿。同一 requestId 重复调用只会发出一封（幂等）',
   '{"type":"object","properties":{"draftId":{"type":"integer","description":"create_draft 返回的 draftId"},"requestId":{"type":"string","description":"调用方生成的唯一串（如 run_id+时间戳），用于幂等"}},"required":["draftId","requestId"]}', 0, 6);

-- wechat_work 内置工具目录（2 个；check_connection 只读）
INSERT INTO mcp_server_tool (tenant_id, server_id, name, description, input_schema, read_only, sort)
VALUES
  (0, 2, 'check_connection', '检查企业微信应用凭据是否有效（不返回 token 本身）',
   '{"type":"object","properties":{}}', 1, 1),
  (0, 2, 'send_text_message', '以企业微信自建应用身份向指定成员发送文本消息',
   '{"type":"object","properties":{"touser":{"type":"string","description":"成员 UserID，多个用 | 分隔"},"content":{"type":"string","description":"消息正文"}},"required":["touser","content"]}', 0, 2);
