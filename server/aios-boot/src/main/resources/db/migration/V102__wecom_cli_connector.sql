-- 企业微信（扫码）连接器：用官方 wecom-cli 的「机器人 + 真人扫码」通道接入。
-- 背景（docs/64）：自建应用那条路要求备案域名（可信域名 → 才能配可信 IP），
--   wecom-cli 扫码授权不需要域名/IP，且天然「一人一份授权」。
--
-- 与前三个连接器的差别：
--   auth_mode = QR    ⇒ 前端弹二维码，不是跳转页、也不是填表；
--   config_keys = []  ⇒ 管理员**无需**配置任何应用凭据（这是它最大的价值）；
--   provider = none   ⇒ hub 侧没有应用级凭证，授权凭据按文件目录隔离在每个用户下。
--
-- 工具目录**不在此写入**：由 `POST /api/v1/mcp/servers/wecom_cli/trust` 探测 hub 后覆盖写，
-- 避免「SQL 里抄一份 schema」与 mcp_hub/wecom_cli/catalog.py 漂移（V101 之后就踩过这种漂移）。

INSERT INTO connector_def (tenant_id, code, name, group_name, icon, summary, auth_mode, config_keys, help_text, help_url, sort, status)
VALUES (0, 'wecom_cli', '企业微信（扫码）', '协作与办公', 'people',
        '扫码绑定你自己的企业微信：查通讯录、看群消息、搜企业邮箱；不需要备案域名',
        'QR', '[]',
        '点「连接」后用手机企业微信扫码即完成绑定；一个账号只绑定一个人的企微，互不可见',
        'https://github.com/WecomTeam/wecom-cli', 25, 'ACTIVE');

INSERT INTO mcp_server (id, tenant_id, code, name, source, transport, trusted, status, connector_code, sort, created_by)
VALUES (4, 0, 'wecom_cli', '企业微信（扫码）', 'BUILTIN', 'STREAMABLE_HTTP', 0, 'UNKNOWN', 'wecom_cli', 25, 0);
