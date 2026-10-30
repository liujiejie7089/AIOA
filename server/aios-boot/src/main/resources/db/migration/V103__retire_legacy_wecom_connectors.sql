-- 下线两个旧的企业微信连接器：wechat_work（自建应用 OAuth2）与 wecom_group（群机器人 Webhook）。
-- 只保留 wecom_cli（扫码，docs/64）—— 用户要求「协作与办公」里不再出现三个企微入口。
--
-- 为什么是「下线」不是「删行」：
--   1. connector_connection / mcp_server_tool 里还有历史数据（连接态、工具快照），
--      物理删行会让留痕与审计断掉，也让「回滚」变成重新造数据；
--   2. 判据只认 status / trusted 两个开关 —— 界面列表只查 connector_def.status='ACTIVE'，
--      agent 的 manifest 只查 mcp_server.trusted=1。置为 DISABLED / 0 之后，
--      这两个连接器对「用户」与「模型」同时不可见，效果等同于删除，但可一键回滚。
--
-- 回滚（真机多用户联调需要 A 模式时）：
--   UPDATE connector_def SET status='ACTIVE' WHERE code IN ('wechat_work','wecom_group');
--   然后对需要的那个重新 trust（POST /api/v1/mcp/servers/{code}/trust）刷新工具快照。
--
-- 注意：mcp_server.status 的合法值是 UNKNOWN/OK/ERROR（McpServer 常量），没有 DISABLED，
-- 所以这里写成 UNKNOWN（含义：未探测/不可用），真正的「不生效」由 trusted=0 保证。

UPDATE connector_def
   SET status = 'DISABLED'
 WHERE tenant_id = 0
   AND code IN ('wechat_work', 'wecom_group');

UPDATE mcp_server
   SET trusted = 0,
       status  = 'UNKNOWN',
       last_error = '已于 2026-10-30 下线：企业微信统一改用「企业微信（扫码）」连接器（docs/64）'
 WHERE tenant_id = 0
   AND code IN ('wechat_work', 'wecom_group');

-- 顺带把这两个连接器的用户连接态置为 NEED_AUTH：
-- 连接器已经不在目录里了，若库里还留着 CONNECTED，就会出现「看不见却算已连接」的脏状态
-- （将来若回滚 A 模式，用户会看到「莫名其妙已连接」）。
UPDATE connector_connection
   SET status = 'NEED_AUTH',
       credential_json = NULL,
       account_label = NULL,
       disconnected_at = CURRENT_TIMESTAMP(6)
 WHERE connector_code IN ('wechat_work', 'wecom_group')
   AND status <> 'NEED_AUTH';
