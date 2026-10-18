-- V36 权限申请授权 + 专家配置审核列
--
-- ① 权限申请与审批：
--    permission_grant 记录「用户申请的细粒度权限」。status=ACTIVE 只能由审批终态回调写入，
--    因此授权链路强制过审；institution_id 满足「数据存档至所在单位」。
--    PermissionCatalog.holds() 已是「先查 AuthUser.permissions 再查角色」，
--    本表是 permissions 的真实来源（此前恒空，细粒度授权链路实际是断的）。
--
-- ⑤ 专家配置审核：
--    expert_config（V27）此前没有审核列，租户管理员改配置即时生效、无人复核。
--    加四列与 V34（agent_worker / ai_expert）同名同语义；默认 APPROVED 保证历史行行为不变。
--    生效解析必须过滤 audit_status='APPROVED'，否则「审核」形同虚设。

-- ---------- ① permission_grant ----------
CREATE TABLE IF NOT EXISTS permission_grant (
    id                BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    tenant_id         BIGINT       NOT NULL DEFAULT 0 COMMENT '租户ID',
    institution_id    BIGINT       NOT NULL DEFAULT 0 COMMENT '存档单位（org_institution.id，需求①「存档至所在单位」）',
    department_id     BIGINT       NOT NULL DEFAULT 0 COMMENT '申请时所属部门（审批链路锚点）',
    user_id           BIGINT       NOT NULL COMMENT '被授权人（sys_user.id）',
    applicant_name    VARCHAR(64)  NULL COMMENT '申请人姓名快照',
    permission_code   VARCHAR(64)  NOT NULL COMMENT '申请的权限码（approval:leave 等）',
    target_worker_type VARCHAR(32) NULL COMMENT '目的数字员工类型（LEAVE_APPROVER 等）',
    reason            VARCHAR(512) NULL COMMENT '申请理由',
    status            VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/ACTIVE/REJECTED/REVOKED',
    order_id          BIGINT       NULL COMMENT '关联 approval_order.id',
    audit_note        VARCHAR(512) NULL COMMENT '审批意见快照',
    granted_by        BIGINT       NULL COMMENT '终审通过人',
    granted_at        DATETIME(6)  NULL COMMENT '生效时间',
    expire_at         DATETIME(6)  NULL COMMENT '到期时间（空=永久）',
    revoked_at        DATETIME(6)  NULL COMMENT '回收时间',
    created_by        BIGINT       NULL,
    created_at        DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at        DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    deleted_at        DATETIME(6)  NULL,
    PRIMARY KEY (id),
    KEY idx_grant_user (tenant_id, user_id, status),
    KEY idx_grant_order (order_id),
    KEY idx_grant_inst (tenant_id, institution_id, status)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '细粒度权限授权单（V36）';

-- ---------- ⑤ expert_config 审核列 ----------
ALTER TABLE expert_config
    ADD COLUMN audit_status VARCHAR(16) NOT NULL DEFAULT 'APPROVED' COMMENT '审核态：PENDING/APPROVED/REJECTED（V36）',
    ADD COLUMN audit_note   VARCHAR(512) NULL COMMENT '审核意见（V36）',
    ADD COLUMN reviewed_by  BIGINT       NULL COMMENT '审核人（V36）',
    ADD COLUMN reviewed_at  DATETIME(6)  NULL COMMENT '审核时间（V36）';
