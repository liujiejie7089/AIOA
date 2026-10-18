-- V84 模块数字人补齐来源模板 id（排序与追溯）
--
-- 问题：V83 的回填是 `sys_tenant CROSS JOIN 模板`，MySQL 返回被驱动表的顺序不受控
-- （实测租户行 id 顺序是**反的**：OA_MOBILE 在前、OA_DOC 在后）⇒ 前端按 id 排序时，
-- 平台租户看到的是清单顺序，各租户看到的却是倒序，同一份「43 个模块」在不同账号下顺序不一致。
--
-- 修法：把 `source_template_id` 补齐（该列本就是「由哪个模板复制而来」的追溯字段），
-- 前端按它排序即可得到与《OA系统功能清单》一致的稳定顺序。
-- 幂等：只更新 source_template_id IS NULL 的行。
UPDATE `agent_worker` w
JOIN `agent_worker` t
  ON t.`tenant_id` = 0 AND t.`is_template` = 1 AND t.`worker_type` = w.`worker_type`
SET w.`source_template_id` = t.`id`
WHERE w.`tenant_id` > 0
  AND w.`worker_type` LIKE 'OA%'
  AND w.`source_template_id` IS NULL;
