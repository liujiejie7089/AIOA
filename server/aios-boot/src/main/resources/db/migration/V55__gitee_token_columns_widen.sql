-- ===========================================================================
-- V55 · 令牌列放宽：新托管方发的是 JWT，不是短随机串（真机实测，非推断）
-- ===========================================================================
-- 症状（2026-09-18 真机：用户在浏览器完成授权之后）：
--   GET /api/v1/gitee/bind/callback → 绑定失败页
--   ### Error updating database.  Cause: com.mysql.cj.jdbc.exceptions.MysqlDataTruncation:
--       Data truncation: Data too long for column 'access_token' at row 1
--   ### The error may involve cn.aioa.gitee.mapper.GiteeAccountMapper.insert-Inline
--   注意报错发生在 **INSERT** —— 即令牌**已经换回来了**，倒在写库这一步。
--
-- 根因：Gitea 的 OAuth2 access_token / refresh_token 是 **JWT**，不是短随机串。
--   Gitea 源码 services/oauth2_provider/token.go：
--     type Token struct { GrantID int64; Kind TokenKind; Counter int64; jwt.RegisteredClaims }
--   默认 JWT_SIGNING_ALGORITHM=RS256 ⇒ 仅签名段就 256 字节（base64url ≈ 342 字符），
--   整枚 JWT 量级 600~1000 字符。
--   而 Gitee 的令牌只有 32~40 字符 ⇒ V48 建表给的 VARCHAR(1024) 对 Gitee 绰绰有余、
--   对 JWT 却不够。GiteeCrypto 的密文是 "enc:" + Base64(12B IV ‖ 密文 ‖ 16B Tag)，
--   即 (明文长度 + 28) × 4/3 + 4：明文到 740 字符时密文就已 1024，正好卡在边界外。
--
-- 为什么 Gitee 路径一直没暴露：Gitee 令牌比 JWT 短 20 倍以上，1024 从未被触碰。
--   本质是「按旧托管方的数据形态定列宽」留下的隐性耦合，换托管方后由真机首次触发。
--   （同类：V54 的 provider 列 —— 也是「按单一托管方假设建模」的产物。）
--
-- 定宽依据（不拍脑袋）：
--   · 令牌列 → TEXT（65,535 字节）：Gitea 自身配置项 MAX_TOKEN_LENGTH 默认 32767，
--     32767 字符明文的密文约 43,730 字节 < 65,535 ⇒ 即使托管方把令牌调到它自己的上限也装得下。
--   · scope → VARCHAR(1024)：Gitea **返回应用登记时勾选的全部权限**，不按授权 URL 上的
--     scope 收窄（见 .env.gitea-real 注释），实测明显长于 Gitee 的短 scope 串。
--   · 这些列**都没有索引**（uk_/idx_ 只建在 tenant_id / user_id / gitee_uid / provider 上），
--     因此改成 TEXT 不需要前缀索引，也不会让唯一键失效。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1。本仓当前最大为 V54（flyway_schema_history 亦为 54），故本文件为 V55。
-- ===========================================================================

ALTER TABLE `gitee_account`
    MODIFY COLUMN `access_token` TEXT NOT NULL
        COMMENT 'OAuth2 access_token（AES-GCM 密文，enc: 前缀）。V55 起由 VARCHAR(1024) 放宽为 TEXT：Gitea 签发 JWT，密文可超 1024',
    MODIFY COLUMN `refresh_token` TEXT NULL
        COMMENT 'OAuth2 refresh_token（密文）；用于自动续期。V55 起放宽为 TEXT（同为 JWT）',
    MODIFY COLUMN `scope` VARCHAR(1024) NULL
        COMMENT '授权 scope（须含 repo）。V55 起由 VARCHAR(255) 放宽：Gitea 返回应用登记的全部权限';

ALTER TABLE `gitee_tenant_config`
    MODIFY COLUMN `access_token` TEXT NULL
        COMMENT '企业访问令牌（AES-GCM 密文，enc: 前缀；与 gitee_account.access_token 同规格）。V55 起放宽为 TEXT',
    MODIFY COLUMN `token_scope` VARCHAR(1024) NULL
        COMMENT '企业令牌授权 scope。V55 起由 VARCHAR(255) 放宽';
