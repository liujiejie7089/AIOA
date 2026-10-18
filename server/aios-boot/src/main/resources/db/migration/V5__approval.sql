-- ============================================================================
-- AIOA V5 审批工作流（打通 FR-D6 审批卡点）
--   approval_order：用户端发起的对外发布类审批单。
--   status: PENDING 待审 / APPROVED 通过 / REJECTED 驳回
--   前端「提交审批」→ 落 PENDING 单；审批中心（租户视角）可 通过/驳回。
-- ============================================================================

CREATE TABLE `approval_order` (
                               `id`             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                               `tenant_id`      BIGINT       NOT NULL DEFAULT 0,
                               `user_id`        BIGINT       NOT NULL DEFAULT 0 COMMENT '发起人',
                               `run_id`         VARCHAR(64)  COMMENT '来源会话 run（可空）',
                               `conversation_id` BIGINT      COMMENT '来源会话（可空）',
                               `biz_type`       VARCHAR(32)  NOT NULL DEFAULT '对外发文',
                               `title`          VARCHAR(256),
                               `content`        TEXT,
                               `status`         VARCHAR(16)  NOT NULL DEFAULT 'PENDING',
                               `approver`       VARCHAR(64)  COMMENT '审批人昵称',
                               `decision_note`  VARCHAR(512),
                               `decided_at`     DATETIME(6),
                               `created_at`     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                               `updated_at`     DATETIME(6),
                               `created_by`     BIGINT,
                               `deleted_at`     DATETIME(6),
                               CONSTRAINT `uk_approval_order` UNIQUE (`tenant_id`, `id`)
);

CREATE INDEX `idx_approval_tenant_status` ON `approval_order` (`tenant_id`, `status`, `created_at`);

-- 预置 1 条待审 + 1 条已通过，便于审批中心 / 我的审批 直接看到演示数据
INSERT INTO approval_order (tenant_id, user_id, biz_type, title, content, status, approver, decided_at, created_at)
VALUES
    (0, 0, '对外发文', '关于组织企业参加全市人工智能应用供需对接会的通知', '拟以公司名义对外发布，按平台规范需经审批。', 'PENDING', NULL, NULL, '2026-09-06 10:30:00'),
    (0, 0, '对外发文', '2026 年第三季度产业政策申报指引（对外版）', '已通过审批，可对外发布。', 'APPROVED', '租户管理员', '2026-09-05 16:10:00', '2026-09-05 15:40:00');
