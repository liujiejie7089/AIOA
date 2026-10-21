-- V90 · 审批催办与超时扫描所需的字段
--
-- docs/57 体检结论：审批引擎具备会签/抢占/加签/子流程/抄送，但**时效治理为空白**——
-- 单据挂在那里没人知道，也没有任何自动提醒。本迁移补上催办所需的两个记账字段：
--   · remind_count    ：已被催办次数（同时也用于前端展示「已催办 N 次」）
--   · last_remind_at  ：上次催办时间（超时扫描据此做「同一单 24 小时内只催一次」的节流）
--
-- 两者都允许为空/默认值 0，老数据无需回写（未催办过即为 0/NULL）。

ALTER TABLE approval_task
    ADD COLUMN remind_count   INT          NOT NULL DEFAULT 0 COMMENT '已被催办次数' AFTER note,
    ADD COLUMN last_remind_at DATETIME(6)  NULL               COMMENT '上次催办时间（超时扫描节流用）' AFTER remind_count;
