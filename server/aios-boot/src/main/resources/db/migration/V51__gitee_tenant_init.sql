-- ===========================================================================
-- V51 · 企业主动发起 Gitee 初始化（组织级企业令牌）
-- ===========================================================================
-- 需求：「企业主动发起 Gitee 初始化」—— 企业提供自己的**访问令牌**与**组织名**
--   （不再依赖个人 OAuth），让组织级操作能回落到这个**企业令牌**。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V50，故本文件为 V51。
--
-- 设计要点：
--   · 这是 V50 `gitee_tenant_config`（每租户单行）的**列追加**，不新建表、不播种租户行。
--   · `access_token` 与 `gitee_account.access_token` **同规格**：AES-GCM 密文、带 `enc:` 前缀
--     （见 GiteeCrypto）；任何接口都**不得回传明文或令牌前缀**，status 仅回 `tokenConfigured`。
--   · `init_status` 状态机：PENDING（未初始化）/ ACTIVE / FAILED；初始化是一次性的明确动作，
--     硬校验失败即中止，绝不静默成功。
--   · `org_name` 与 `enabled` 仍由 V50 的 tenant-config 接口管辖（职责分离），本迁移只加令牌相关列。
--
-- 安全：本文件只追加列，不写任何租户行；`access_token` 入库即加密。
-- 风格严格沿用 V48 / V50：反引号、列 COMMENT、逐列 ADD COLUMN 便于失败定位。
-- ===========================================================================

-- 企业访问令牌（AES-GCM 密文，enc: 前缀；与 gitee_account.access_token 同规格）
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `access_token` VARCHAR(1024) NULL COMMENT '企业访问令牌（AES-GCM 密文，enc: 前缀；与 gitee_account.access_token 同规格）';

-- 令牌所属 Gitee 登录名（校验时回填）
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `token_owner` VARCHAR(128) NULL COMMENT '令牌所属 Gitee 登录名（校验时回填）';

-- 令牌授权范围
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `token_scope` VARCHAR(255) NULL COMMENT '企业令牌授权 scope';

-- 初始化状态：PENDING（未初始化）/ ACTIVE / FAILED
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `init_status` VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT '初始化状态：PENDING/ACTIVE/FAILED';

-- 最近一次初始化时间
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `init_at` DATETIME(6) NULL COMMENT '最近一次成功初始化时间';

-- 最近一次初始化操作人（sys_user.id）
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `init_by` BIGINT NULL COMMENT '最近一次初始化操作人（sys_user.id）';

-- 最近一次失败原因（供界面提示）
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `last_error` VARCHAR(512) NULL COMMENT '最近一次初始化/校验失败原因';

-- 组织可见性校验结果（初始化硬校验通过置 true）
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `org_verified` TINYINT(1) NULL COMMENT '组织可见性校验结果（1=已验证可用）';

-- 最近一次校验（含可见性探测）时间
ALTER TABLE `gitee_tenant_config`
    ADD COLUMN `last_check_at` DATETIME(6) NULL COMMENT '最近一次校验（含可见性探测）时间';
