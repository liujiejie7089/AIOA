-- V21 数字员工职责边界与权限规则 + 会话绑定数字员工
-- 1) agent_worker.worker_type：数字员工角色类型（职责边界与所需权限的落库锚点）
-- 2) chat_conversation.worker_id：会话绑定的数字员工；非空 = 该会话仅在该员工职责范围内作答
--
-- 类型取值（与 cn.aioa.resource.support.WorkerRole 一一对应）：
--   GENERAL / LEAVE_APPROVER / KB_ASSISTANT / DOC_DRAFTER

ALTER TABLE `agent_worker`
    ADD COLUMN `worker_type` VARCHAR(32) NOT NULL DEFAULT 'GENERAL'
        COMMENT '数字员工角色类型：GENERAL 通用 / LEAVE_APPROVER 请假审批 / KB_ASSISTANT 知识库问答 / DOC_DRAFTER 公文起草';

-- 存量回填：名称或职责描述含「请假」→ 请假审批类（历史数据自动归位，避免全部落到 GENERAL）
UPDATE `agent_worker`
SET `worker_type` = 'LEAVE_APPROVER'
WHERE `deleted_at` IS NULL
  AND (`name` LIKE '%请假%' OR `description` LIKE '%请假%');

ALTER TABLE `chat_conversation`
    ADD COLUMN `worker_id` BIGINT NULL
        COMMENT '绑定的数字员工ID；非空=该会话受该员工职责边界约束',
    ADD KEY `idx_chat_conv_worker` (`worker_id`);
