-- ============================================================================
-- AIOA V63 投诉与建议（用户端「我的」页 → 反馈给本部门管理员）
--
-- 业务口径：用户在用户端提交投诉/建议，系统把内容派给「本部门的管理员」。
-- 现实里部门不一定配了管理员，因此接收人是**逐级上溯**解析出来的：
--     本部门管理员 → 本机构管理员 → 租户管理员
-- 并把「实际派给了谁、为什么是他」写进 assignee_*/assignee_reason 三列。
--
-- 为什么必须落库记录接收层级，而不是只发一条通知：
--   1) 通知是「一次性投递」，读没读、处理没处理无法追溯；用户需要能看到答复；
--   2) 逐级上溯是一次**有分支的判定**，不记录就永远说不清「这条为什么没人管」；
--   3) 管理员可能换人/离职，接收人需可重新指派（改 assignee_* 即可），
--      而提交内容与状态必须独立存活。
--
-- 匿名（anonymous=1）只对「上级查看时是否显示姓名」生效，
-- submitter_user_id 仍然保留：否则无法把答复送还给提交人，也无法防刷。
-- ============================================================================

CREATE TABLE `org_feedback` (
    `id`                  BIGINT        NOT NULL AUTO_INCREMENT PRIMARY KEY,
    `tenant_id`           BIGINT        NOT NULL DEFAULT 0,
    `institution_id`      BIGINT        NOT NULL DEFAULT 0 COMMENT '提交人所属机构（0=未归属）',
    `department_id`       BIGINT        NOT NULL DEFAULT 0 COMMENT '提交人所属部门（0=未归属）',
    `category`            VARCHAR(32)   NOT NULL DEFAULT 'ADVICE'
        COMMENT 'COMPLAINT 投诉 / ADVICE 建议 / BUG 功能异常 / SERVICE 服务态度 / OTHER 其他',
    `content`             VARCHAR(2000) NOT NULL COMMENT '用户输入内容',
    `contact`             VARCHAR(128)  COMMENT '可选联系方式（便于线下回复）',
    `anonymous`           TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '1=对上级匿名（提交人身份仍保留）',
    `status`              VARCHAR(16)   NOT NULL DEFAULT 'PENDING'
        COMMENT 'PENDING 待处理 / REPLIED 已回复 / CLOSED 已关闭（不可再回复）',

    `submitter_user_id`   BIGINT        NOT NULL COMMENT '提交人（匿名时仍保留，用于送还答复）',
    `submitter_name`      VARCHAR(64)   COMMENT '提交人姓名快照（离职后仍可读）',
    `submitter_dept_name` VARCHAR(128)  COMMENT '提交时部门名快照（部门改名/删除后仍可读）',

    `assignee_user_id`    BIGINT        COMMENT '实际接收人；为 NULL = 上溯到租户级仍无管理员（待人工指派）',
    `assignee_name`       VARCHAR(64)   COMMENT '接收人姓名快照',
    `assignee_scope`      VARCHAR(16)   COMMENT '实际命中的层级：DEPT / INSTITUTION / TENANT / NONE',
    `assignee_reason`     VARCHAR(256)  COMMENT '为什么派给他（逐级上溯的判定说明，便于追责）',

    `reply_content`       VARCHAR(2000) COMMENT '管理员答复（可直接被提交人看到）',
    `replied_by`          BIGINT,
    `replied_by_name`     VARCHAR(64),
    `replied_at`          DATETIME(6),

    `created_at`          DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `updated_at`          DATETIME(6),
    `created_by`          BIGINT,
    `deleted_at`          DATETIME(6)
);

-- 管理员「收到的建议」列表：按接收人 + 状态 + 时间倒序
CREATE INDEX `idx_org_feedback_assignee` ON `org_feedback` (`tenant_id`, `assignee_user_id`, `status`, `created_at`);
-- 用户「我的提交」列表
CREATE INDEX `idx_org_feedback_submitter` ON `org_feedback` (`tenant_id`, `submitter_user_id`, `created_at`);
-- 组织维度汇总/审计（本部门、本机构各有多少条）
CREATE INDEX `idx_org_feedback_org` ON `org_feedback` (`tenant_id`, `institution_id`, `department_id`, `created_at`);
