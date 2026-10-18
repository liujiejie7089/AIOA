-- ===========================================================================
-- V45 · 四期/五期：审批节点「职务口径 + 处理模式」
-- ===========================================================================
-- 背景（docs/23 §7 分期计划）：
--   四期 = 解析器策略化 + DEPT_DUTY / UNIT_DUTY（流程模板可跨部门复用，人员变动不改流程）；
--   五期 = 处理模式（single / parallel / grab）与条件路由（复杂审批拓扑，如按金额分流）。
--
-- 纪律：本迁移**只加列**，不改任何既有列；两个新列均带默认值，
--   使历史行与改造前**逐字等价**（node_mode 默认 'single' = 一个节点一条任务，与既有实现一致）。
--
-- ⚠️ 落地前先 `ls server/aioa-boot/src/main/resources/db/migration | sort -V | tail -3`
--    取实际最大版本 +1；本仓当前最大为 V44，故本文件为 V45。
-- ⚠️ alive 约定沿用 V24：alive TINYINT GENERATED ALWAYS AS (IF(deleted_at IS NULL,1,NULL)) VIRTUAL，
--    仅用于配合唯一键；本次加列**不新建唯一键**，也不新增 alive。
-- ===========================================================================

-- ① node_mode：节点处理模式 —— 决定「一个节点解析出多个候选审批人」时怎么用他们。
--    single  （默认）只取第 1 个候选，1 条任务 —— 与改造前**完全一致**；
--    parallel（会签）每个候选各 1 条任务、同 seq 并列；全部通过才推进，任一驳回即整单驳回；
--    grab    （抢占/或签）每个候选各 1 条任务、同 seq 并列；任一通过 → 同组其余 SKIPPED → 立即推进。
--    默认 'single' 是向后兼容的关键：历史行的行为不因本迁移发生任何变化。
ALTER TABLE `approval_task`
    ADD COLUMN `node_mode` VARCHAR(16) NOT NULL DEFAULT 'single'
        COMMENT '节点处理模式：single 单人 / parallel 会签 / grab 抢占' AFTER `cc_read_at`;

-- ② node_duty：节点绑定的职务码 —— 仅 approver_type ∈ (DEPT_DUTY, UNIT_DUTY) 时有值。
--    为什么不在 approver_type 里编码职务：DEPT_DUTY 只说明「按职务求值」，
--    具体是正职还是副职由 duty_code 决定；拆成两列才能让同一条流程模板换职务而不换类型，
--    也才能让 timeline 直接显示「部门副职」而不是笼统的「职务审批」。
--    NULL = 非职务型节点（历史行全部为 NULL，等价于改造前）。
ALTER TABLE `approval_task`
    ADD COLUMN `node_duty` VARCHAR(32) NULL
        COMMENT '职务码（仅 DEPT_DUTY / UNIT_DUTY 节点有值，对应 org_duty.code）' AFTER `node_mode`;

-- ③ 节点组推进要按 (order_id, seq) 聚合，补一个覆盖索引。
--    既有 idx_approval_task_role 以 approver_id 打头，服务不了「同组还有谁没审」这类查询。
ALTER TABLE `approval_task`
    ADD KEY `idx_approval_task_order_seq` (`order_id`, `seq`, `status`);
