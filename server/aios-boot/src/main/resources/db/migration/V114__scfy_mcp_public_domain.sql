-- 四川非遗 MCP：工具目录扩到 69 个只读接口，且默认直连官网域名。
--
-- 背景：docs/90 从公网 swagger（964 条定义 / 115 个 GET /show/*）筛出 14 个
-- 公网确有数据的接口（影像展统计、文化遗产日、舆情热词/城市榜、中医药基地、
-- 项目与传承人分等级计数），已在 Java 契约里标为 MCP_ONLY 并导出到 hub。
--
-- 这里只改展示文案，不动 V113 已应用的种子（改历史迁移会造成 Flyway checksum 漂移）。
-- 工具快照仍由 POST /api/v1/mcp/servers/scfy/trust 探测 hub 后覆盖写入。

UPDATE connector_def
   SET summary   = '查四川非遗的传承人、项目、工坊、文化生态保护区、旅游线路、影像展与舆情（69 个只读接口，免登录）',
       help_text = '无需配置凭据：查询接口免登录，默认直连 https://szbhpt.tsichuan.com/scfy。点「信任」后即可在对话中查询四川非遗数据；本机 16060 仅排障时由 AIOS_SCFY_BASE_URL 显式覆盖。',
       updated_at = NOW(6)
 WHERE tenant_id = 0
   AND code = 'scfy'
   AND (summary <> '查四川非遗的传承人、项目、工坊、文化生态保护区、旅游线路、影像展与舆情（69 个只读接口，免登录）'
        OR help_text <> '无需配置凭据：查询接口免登录，默认直连 https://szbhpt.tsichuan.com/scfy。点「信任」后即可在对话中查询四川非遗数据；本机 16060 仅排障时由 AIOS_SCFY_BASE_URL 显式覆盖。');
