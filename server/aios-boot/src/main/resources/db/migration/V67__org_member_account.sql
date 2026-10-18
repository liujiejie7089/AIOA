-- =============================================================================
-- V67 员工 ↔ 用户账号 多对多（docs/38 批次 C）
--
-- 规格（用户）：「理论上，用户和员工存在多对多的关系。每个员工都有一个用户帐号，
--                有些管理员用户帐号是虚拟的，没有对应的员工，一个员工也可以有多个用户帐号。」
--
-- 现状：`org_member.user_id` 是**单向单值**外键 ⇒ 「一个员工多账号」无法表达
--       （只能靠多建一行员工来近似，那会把「一个人」拆成「多个人」，
--        连带把部门人数、审批人、统计口径全带偏）。
--
-- 设计（docs/38 §5 批次 C）：新增中间表 `org_member_account`；
--   **保留 `org_member.user_id` 作为「主账号」** —— 既有代码（通知、审批、鉴权、
--   OrgGuard.resolveInstitutionId 等 20+ 处）全部读它，不动它是本批"零回归"的前提。
--   中间表的 `is_primary=1` 那一行与 `org_member.user_id` 同源，
--   由服务层在开户/改绑时同步维护（**不允许**只写一边）。
--
-- 唯一性：沿用本项目既有的软删防重模式（`alive` 生成列 + 唯一键含 alive）——
--   否则「解绑后重新绑定同一个账号」会直接撞唯一键（同族坑：软删复用）。
--
-- 回填：既有 53 行 org_member 全部有 user_id，回填后中间表即与现状一致，
--   因此本迁移**不改变任何既有行为**，C 组功能是在此之上新增。
-- =============================================================================

CREATE TABLE org_member_account (
    id         BIGINT       NOT NULL AUTO_INCREMENT,
    tenant_id  BIGINT       NOT NULL COMMENT '冗余租户维度，便于按租户过滤',
    member_id  BIGINT       NOT NULL COMMENT 'org_member.id',
    user_id    BIGINT       NOT NULL COMMENT 'sys_user.id',
    is_primary TINYINT(1)   NOT NULL DEFAULT 0
               COMMENT '是否员工主账号：与 org_member.user_id 同源，由服务层同步维护',
    created_at DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6)  DEFAULT NULL,
    created_by BIGINT       DEFAULT NULL,
    deleted_at DATETIME(6)  DEFAULT NULL,
    alive      TINYINT      GENERATED ALWAYS AS (IF(deleted_at IS NULL, 1, NULL)) VIRTUAL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_member_account (member_id, user_id, alive),
    KEY idx_member_account_user (user_id),
    KEY idx_member_account_member (member_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_0900_ai_ci
  COMMENT = '员工与用户账号的多对多关系（含主账号标记）';

-- 回填：既有 org_member.user_id 即主账号（表为新建、必为空，无需 NOT EXISTS 去重）
INSERT INTO org_member_account (tenant_id, member_id, user_id, is_primary, created_at, created_by)
SELECT tenant_id, id, user_id, 1, NOW(6), created_by
FROM org_member
WHERE deleted_at IS NULL
  AND user_id IS NOT NULL;
