-- V99: 企业微信连接器新增 get_my_profile 工具（docs/58 §3.3 网页授权 snsapi_privateinfo 链路的产物）。
-- 授权升级后 callback 经 auth/getuserinfo 拿 user_ticket → auth/getuserdetail 拿 biz_mail，
-- credential_json 存 {userid, biz_mail}；本工具把「我是谁」暴露给 agent（只读、无参数）。
-- 纪律：工具名必须与 cn.aios.resource.connector.wecom.WeComMcpHandler.supports() 逐字一致，
--       且与 mcp-hub/mcp_hub/specs.py 的 wechat_work 工具目录逐字对齐。
INSERT INTO mcp_server_tool (tenant_id, server_id, name, description, input_schema, read_only, sort)
VALUES
  (0, 2, 'get_my_profile', '获取当前用户的企业微信身份（userid / 企业邮箱 biz_mail），来自 OAuth 网页授权 snsapi_privateinfo 授权后的 getuserdetail',
   '{"type":"object","properties":{}}', 1, 3);
