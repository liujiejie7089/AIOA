-- V77 仓库联动「平台级参数」动态配置（管理端 系统配置 → 仓库配置）
--
-- 背景：V50 的 gitee_tenant_config 解决了「每租户各自的组织/企业令牌」，但平台级参数
-- （OAuth 应用的 client-id / client-secret / redirect-uri、webhook 公网基址、授权跳转域、
--  scope、平台默认组织、回跳地址、总开关）此前**只能由环境变量注入**。
--  在生产（服务器在隧道机之后）改一次这些值要改 deploy/.env + docker compose up -d 重建容器，
--  运维成本高且必须动服务器；本表把其中「可运维」的 9 项收敛到管理端页面，保存即生效、无需重启。
--
-- ★ 语义（务必遵守，前端与后端同口径）：**逐字段**
--   某列为 NULL  ⇒ 该字段回落 application.yml / 环境变量；
--   某列非 NULL  ⇒ 该字段以本表为准，**空串也是有效值**（表示「管理端显式清空」）。
--   刻意逐字段而非整体覆盖：整体覆盖会让「首次保存时没填的密钥把环境变量的值静默遮蔽」，
--   那是一种用户完全看不见的数据丢失（表现为「昨天还能用，今天突然授权失败」）。
--
-- ★ 刻意**不纳入**本表的参数（仍只由环境变量/yml 提供），理由必须写清楚，否则后人会「顺手补上」：
--   token-enc-key  —— 它是既有密文（gitee_account / gitee_tenant_config）的解密根；改它会让
--                     所有已存令牌解不开（报「令牌解密失败」）。放进 UI 等于给运维一个自毁按钮。
--   base-url / web-base-url —— 定义「这是哪个托管平台」，属部署身份，不是运行期参数。
--   webhook-secret —— 留空即「每仓库随机生成」（推荐做法），无需平台级固定值。
--   调优项（max-attempts / task-batch-size / min-request-interval-ms / http-timeout-seconds /
--          list-page-size / list-max-pages / repo-name-max-length）—— 改这些要重启进程才生效，
--          放进「保存即生效」的页面会造成「保存了但没生效」的误会。
--
-- 本迁移**不插入任何种子行**：空表 ⇒ 全字段回落 env ⇒ 部署前后行为完全一致（零回归）。

CREATE TABLE IF NOT EXISTS `gitee_platform_config` (
    `id`                       BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `provider`                 VARCHAR(16)  NOT NULL COMMENT '托管方标识：gitee / gitea（与 aioa.repo.provider 同口径）',
    `enabled`                  TINYINT(1)   NULL COMMENT '平台总开关；NULL=回落环境变量（刻意可空，避免「插行即静默关闭」）',
    `client_id`                VARCHAR(128) NULL COMMENT 'OAuth 应用 Client ID',
    `client_secret`            VARCHAR(512) NULL COMMENT 'OAuth 应用 Client Secret（AES-GCM 密文，enc: 前缀）',
    `redirect_uri`             VARCHAR(512) NULL COMMENT 'OAuth 回调地址，须与第三方应用登记页逐字符一致',
    `oauth_authorize_base_url` VARCHAR(255) NULL COMMENT '用户浏览器授权页基址（默认与 web-base-url 同值）',
    `scope`                    VARCHAR(255) NULL COMMENT '授权 scope；必须同时含 projects 与 hook',
    `org`                      VARCHAR(128) NULL COMMENT '平台默认组织 login（租户未自配时的回落值）',
    `webhook_base_url`         VARCHAR(512) NULL COMMENT 'Webhook 回调公网基址，须为托管方可达地址',
    `bind_return_url`          VARCHAR(512) NULL COMMENT '授权完成后前端回跳地址',
    `updated_by`               BIGINT       NULL COMMENT '最后操作人（sys_user.id）',
    `created_at`               DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`               DATETIME(6)  NULL,
    UNIQUE KEY `uk_gitee_platform_provider` (`provider`)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '仓库联动平台级参数（管理端动态配置，整体覆盖 env）';
