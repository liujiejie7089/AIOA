-- 清掉两个已下线连接器的 MCP 工具快照（2026-10-30，承接 V103）。
--
-- 背景：V103 只把 connector_def.status / mcp_server.trusted 关掉，工具快照仍留在库里。
-- 结果是有两个「看不见但打得通」的接口：
--   GET /api/v1/mcp/servers/wechat_work/tools  → 仍回 13 个工具
--   GET /api/v1/mcp/servers/wecom_group/tools  → 仍回 2 个
-- 用户端/管理端里 mcp_server 的 toolCount 也是从这张表 count 出来的，于是界面会对着一台
-- 「代码已经删干净、探测必然失败」的服务器报「13 个工具」—— 这是在骗用户。
--
-- 为什么现在可以删：V103 注释里说「保留快照是为了一键回滚」，而代码已经物理删除
-- （hub 侧 wecom/ 包与 Java 侧 WeComOAuthService 都已移出仓库，见 docs/64 §9.7）。
-- 回滚现在只能靠 git revert + 重新部署，那时 trust 会从 hub 重新拉一份快照；
-- 留着这份旧快照既不能用于回滚，又会让上面两个接口继续给出错误答案。
--
-- 保留：mcp_server 行本身（按 V103 的约定留痕）。工具计数没有独立列，是列表时对
-- mcp_server_tool 现 count 的，所以删完快照后 toolCount 自然变 0，无需再改其它列。

DELETE FROM mcp_server_tool
 WHERE server_id IN (
     SELECT id FROM mcp_server
      WHERE tenant_id = 0
        AND code IN ('wechat_work', 'wecom_group')
 );
