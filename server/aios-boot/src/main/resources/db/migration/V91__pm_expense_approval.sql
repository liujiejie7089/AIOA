-- V91 · 项目费用报销接入审批（docs/57 阶段一 A3）
--
-- 背景：费用报销此前**完全没有审批**——PmExpenseService 只有 list / create / reverse，
-- 钱直接入账。43 个模块里 `expense_form` 表单存在、EXPENSE 审批流已由 V89 补建，
-- 但业务表和审批单之间没有关联字段，导致「填了表单 → 走审批 → 回写业务表」最后一段接不上。
--
-- 本迁移只加两个字段，不动既有流水语义：
--   · approval_status：NONE（直接入账，无需审批）/ PENDING（审批中）/ APPROVED / REJECTED
--   · order_id       ：关联的审批单 id（回调据此回写）
--
-- 老数据全部为 NONE（原本就是直接入账），不受影响。

ALTER TABLE pm_expense
    ADD COLUMN approval_status VARCHAR(16) NOT NULL DEFAULT 'NONE'
        COMMENT '审批状态：NONE 无需审批 / PENDING 审批中 / APPROVED 已通过 / REJECTED 已驳回' AFTER remark,
    ADD COLUMN order_id BIGINT NULL COMMENT '关联的审批单 id（EXPENSE）' AFTER approval_status,
    ADD KEY idx_pm_expense_order (order_id);
