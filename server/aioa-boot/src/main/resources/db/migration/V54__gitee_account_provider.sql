-- ===========================================================================
-- V54 · gitee_account 增加托管方维度（provider-scoped 身份绑定）
-- ===========================================================================
-- 背景（真机实测，非推断）：
--   V48 建表时只有 Gitee 一个实现，于是「一个用户在本租户内只有一条绑定」这条
--   假设被写进了唯一键：uk_gitee_account_user(tenant_id, user_id, alive)。
--
--   但 gitee_account 存的其实是**托管方身份**：access_token 由 Gitee 签发、
--   gitee_uid 是 Gitee 的 id、gitee_username 是 Gitee 的登录名。切到 Gitea 后：
--     ① 同一 user_id 想再绑一个 Gitea 身份 → 撞 uk_gitee_account_user（旧行仍 alive）→ 500；
--     ② 旧行的密文是用 **Gitee** 的 token-enc-key 写的，用 Gitea 的密钥解密必然
--        AEADBadTagException(Tag mismatch) → GiteeTokenService.validToken 抛
--        IllegalStateException → 创建项目直接 500「服务内部错误」；
--     ③ 更隐蔽的是：即使不炸，gitee_username='liu-yang20'（Gitee 的登录名）会被拿去
--        Gitea 的协作者接口 → 404，成员同步静默失败。
--
--   实测症状：provider=gitea 且租户2用户3 存在真实 Gitee 绑定时，
--   POST /api/v1/gitee/projects → code=500，日志
--   `IllegalStateException: Gitee 令牌解密失败` / `Caused by: AEADBadTagException: Tag mismatch`。
--
-- 语义修正：
--   绑定行属于**某个托管方**，不是「属于某个用户」。因此
--     · 新增 provider 列（回填 'gitee'：此前唯一实现就是 Gitee，这是确定事实而非猜测）；
--     · 唯一键并入 provider —— 同一租户同一用户可**并存** Gitee 与 Gitea 两个身份；
--       gitee_uid 也必须并入，因为两个平台的数字 id 空间无关，数值可能相撞。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V53，故本文件为 V54。
-- ===========================================================================

-- ① 新增 provider 列。NOT NULL + DEFAULT 'gitee' ⇒ 存量行一次性回填为 'gitee'，
--    不需要额外的 UPDATE（MySQL 8 对 ADD COLUMN ... NOT NULL DEFAULT 会填充既有行）。
ALTER TABLE `gitee_account`
    ADD COLUMN `provider` VARCHAR(16) NOT NULL DEFAULT 'gitee'
        COMMENT '托管方：gitee / gitea（V54 起；历史行必为 gitee）'
        AFTER `user_id`;

-- ② 重建唯一键：把 provider 并入。
--    先删后加 —— 旧键不含 provider，会把「同一用户先绑 Gitee 再绑 Gitea」判为冲突。
ALTER TABLE `gitee_account`
    DROP INDEX `uk_gitee_account_user`,
    DROP INDEX `uk_gitee_account_gitee`;

ALTER TABLE `gitee_account`
    ADD UNIQUE KEY `uk_gitee_account_user` (`tenant_id`, `user_id`, `provider`, `alive`)
        COMMENT '同一租户同一用户在同一托管方下只允许一条有效绑定',
    ADD UNIQUE KEY `uk_gitee_account_gitee` (`tenant_id`, `gitee_uid`, `provider`, `alive`)
        COMMENT '同一托管方账号在同一租户内只能绑定一个平台用户';

-- ③ 按托管方反查的辅助索引（Webhook 身份映射按 (tenant, provider, uid) 查）。
ALTER TABLE `gitee_account`
    ADD KEY `idx_gitee_account_provider_uid` (`tenant_id`, `provider`, `gitee_uid`);
