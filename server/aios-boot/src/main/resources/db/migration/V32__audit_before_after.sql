-- V32 操作审计补齐变更前后值
--
-- 背景：数字员工的管理动作（创建/修改/启停/删除/分发）此前只记录「谁在何时做了什么事」，
-- 缺少 before/after 快照，无法回答「改之前是什么、改之后是什么」，不满足审计可追溯要求。
--
-- 方案：在既有的 client_activity_log 上追加两列 JSON 文本快照。
--   * 不写 audit_log —— 那张表带 hash 链，跨模块直接插会破坏链校验（沿用既有约定）。
--   * 列可空：历史行与不产生变更的动作为 NULL，前端按「无变更」展示，不做回填。
--
-- 变更前后值用 JSON 文本承载（MySQL 8 下 TEXT 足够，避免 JSON 类型的兼容性开销）。

ALTER TABLE `client_activity_log`
    ADD COLUMN `before_value` TEXT NULL COMMENT '变更前快照（JSON）' AFTER `label`,
    ADD COLUMN `after_value`  TEXT NULL COMMENT '变更后快照（JSON）' AFTER `before_value`;
