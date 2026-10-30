-- 企业微信群机器人连接器（唯一不要求「可信 IP / 可信域名」的企微通道）
-- 背景：自建应用的业务接口要求企业可信 IP，而企微硬规则是「配置可信 IP 前必须先设置
--       可信域名或接收消息服务器 URL」，两者都要求备案域名。群机器人只认 webhook key。
-- 工具逻辑在 mcp-hub 的 wecom/group_server.py（原生实现），不转发 Java。

INSERT INTO connector_def (tenant_id, code, name, group_name, icon, summary, auth_mode, config_keys, help_text, help_url, sort, status)
VALUES (0, 'wecom_group', '企业微信群机器人', '协作与办公', 'chat',
        '往企业微信群发消息（群机器人 Webhook）；不要求可信 IP、域名、企业认证',
        'API_KEY', '["webhookKey"]',
        '企微群 → 右上角 … → 消息推送/群机器人 → 复制 Webhook 地址，取 key= 之后那段（36 位 UUID）',
        'https://developer.work.weixin.qq.com/document/path/91770', 30, 'ACTIVE');

-- 内置 MCP 服务器（BUILTIN，trusted=0：仍需经信任闸门探测后才对 agent 可见）
INSERT INTO mcp_server (id, tenant_id, code, name, source, transport, trusted, status, connector_code, sort, created_by)
VALUES (3, 0, 'wecom_group', '企业微信群机器人', 'BUILTIN', 'STREAMABLE_HTTP', 0, 'UNKNOWN', 'wecom_group', 30, 0);

-- 工具目录必须与 mcp-hub/mcp_hub/wecom/group_server.py 的 TOOLS 逐字一致，
-- 否则「信任」写入的目录会让模型调出 hub 不认识的工具。
INSERT INTO mcp_server_tool (tenant_id, server_id, name, description, input_schema, read_only, sort)
VALUES
  (0, 3, 'send_group_text', '往企业微信群发送纯文本消息（走群机器人 Webhook，不需要可信 IP）',
   '{"type":"object","properties":{"content":{"type":"string","description":"消息正文，UTF-8 最长 2048 字节"},"atMobiles":{"type":"string","description":"要 @ 的手机号，多个用逗号分隔；填 @all 提醒所有人；可空"}},"required":["content"]}', 0, 1),
  (0, 3, 'send_group_markdown', '往企业微信群发送 markdown 消息（支持 **加粗**、> 引用、[链接](url)、彩色字）',
   '{"type":"object","properties":{"content":{"type":"string","description":"markdown 正文"},"atMobiles":{"type":"string","description":"要 @ 的手机号，多个用逗号分隔；可空"}},"required":["content"]}', 0, 2);
