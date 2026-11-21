-- 四川非遗（scfy）连接器：把非遗系统的 55 个只读查询接口以标准 MCP 协议接入。
--
-- 与既有连接器的差别：
--   · 数据源在非遗系统（16060 / 生产西昌），工具逻辑在 mcp-hub 的原生连接器 scfy/；
--   · /show/* 免登录 ⇒ 无应用凭据、无用户凭据（config_keys=[]、provider=none）；
--   · 工具目录**不在此写入**：由 POST /api/v1/mcp/servers/scfy/trust 探测 hub 后覆盖写，
--     目录事实源是 mcp_hub/scfy/catalog.json（由 Java ScfyCatalog 导出），避免手抄漂移（V97 教训）。
--
-- 生效两步：① 本迁移建目录项（trusted=0，对模型不可见）；
--          ② 部署后调一次 trust：`POST /api/v1/mcp/servers/scfy/trust`（管理员 token），
--             探测通过后写工具快照、trusted=1，agent 的 manifest 才出现 mcp__scfy__*。
-- 这是与 qq_mail / wecom_cli 完全一致的「站点统一授权 + 信任闸门」流程（docs/59 §10）。

INSERT INTO connector_def (tenant_id, code, name, group_name, icon, summary, auth_mode, config_keys, help_text, help_url, sort, status)
VALUES (0, 'scfy', '四川非遗（scfy）', '数据与知识', 'data',
        '查四川非遗的传承人、项目、工坊、文化生态保护区、旅游线路（55 个只读接口，免登录）',
        'API_KEY', '[]',
        '无需配置凭据：非遗查询接口免登录。点「信任」后即可在对话中查询四川非遗数据；服务地址由 AIOS_SCFY_BASE_URL 配置。',
        '', 35, 'ACTIVE');

INSERT INTO mcp_server (id, tenant_id, code, name, source, transport, trusted, status, connector_code, sort, created_by)
VALUES (5, 0, 'scfy', '四川非遗（scfy）', 'BUILTIN', 'STREAMABLE_HTTP', 0, 'UNKNOWN', 'scfy', 35, 0);
