-- ============================================================================
-- T21：清理演示/测试数据（走查发现 G-5）
--
-- ⚠️ 破坏性操作，但为「逻辑删除」（置 deleted_at），可通过
--    UPDATE ... SET deleted_at = NULL WHERE id IN (...) 回滚。
--
-- 执行前置：先跑 scripts/cleanup_demo_data.py，它会导出被影响行的完整快照到
--           cleanup_backup_<timestamp>.json，再执行本脚本。
--
-- 清理范围（保持克制，只清「明显是测试/重复」的，保留可用的业务演示数据）：
--   A. agent_worker —— 保留 政策快讯员 / 请假助手 / 办文助手 / 晨报员(1 条)；
--      清除重复晨报员、按「一句话创建」测试留下的句子碎片命名员工。
--   B. approval_order —— 清除 E2E/冒烟/回归/curl 造单与批次二验证造单。
-- ============================================================================

-- ---------- A. 数字员工 ----------
-- A1. 重复的「晨报员」只保留 id 最小的一条
UPDATE `agent_worker`
SET `deleted_at` = NOW()
WHERE `deleted_at` IS NULL
  AND `name` = '晨报员'
  AND `id` NOT IN (
      SELECT `keep_id` FROM (
          SELECT MIN(`id`) AS `keep_id` FROM `agent_worker`
          WHERE `deleted_at` IS NULL AND `name` = '晨报员'
      ) t
  );

-- A2. 「一句话创建」端到端测试留下的句子碎片命名员工 + 重复生成物
UPDATE `agent_worker`
SET `deleted_at` = NOW()
WHERE `deleted_at` IS NULL
  AND (
      `name` LIKE '按当前配置重新生成%'
   OR `name` LIKE '合同到期前 7 天%助手'
   OR `name` LIKE '每天 8 点推送行%助手'
   OR `name` LIKE 'E2E-%'
   OR `name` LIKE '冒烟%'
   OR `name` = '临时通用助手'
  );

-- ---------- B. 审批单 ----------
UPDATE `approval_order`
SET `deleted_at` = NOW()
WHERE `deleted_at` IS NULL
  AND (
      -- 明确的测试/冒烟/联调造单
      `title` IN (
          '测试审批单-发起人', 'e2e 审批流转单', 'e2e权限测试单', 'test',
          '多角色冒烟-提交', 'curl测试', '通知链路验证单', '意见流验证单',
          '对外发布审批（总测试）'
      )
   OR `title` LIKE '回归-%'
      -- 早期端到端脚本用 bizType=LEAVE 造的单：既无 formData 也无标题区间，
      -- 在列表里只能显示成「请假 · 提交人：…」，属无效数据
   OR `biz_type` = 'LEAVE'
      -- 本轮体验改进验证过程产生的造单（事由里带了验证说明）
   OR `content` LIKE '%批次二验证%'
   OR `content` LIKE '%截图用%'
  );
