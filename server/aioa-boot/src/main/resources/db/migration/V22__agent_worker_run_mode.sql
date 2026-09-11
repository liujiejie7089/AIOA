-- V22 数字员工运行模式（run_mode）：让「待配置」只对定时型生效
--
-- 背景（走查发现 D-2）：WorkerView.from() 原判定是「enabled 且 scheduleTime 为空 → 待配置」，
-- 于是「触发式（有申请即审）」的请假助手、「随时唤起」的办文助手都被打上「待配置 ·
-- 缺少执行时刻」的告警，且对普通成员给出其无权限执行的指引（请联系租户管理员）。
--
-- 运行模式取值（与 cn.aioa.resource.entity.AgentWorker.RUN_MODE_* 一一对应）：
--   SCHEDULED 定时型：必须配置执行时刻，缺时刻才判「待配置」
--   EVENT     事件驱动：由业务事件触发（如请假申请到达），不需要执行时刻
--   ON_DEMAND 按需唤起：用户随时发起，不需要执行时刻

ALTER TABLE `agent_worker`
    ADD COLUMN `run_mode` VARCHAR(16) NOT NULL DEFAULT 'SCHEDULED'
        COMMENT '运行模式：SCHEDULED 定时 / EVENT 事件驱动 / ON_DEMAND 按需唤起';

-- 存量回填 1：请假审批类数字员工本质由「有申请即审」驱动，非定时
UPDATE `agent_worker`
SET `run_mode` = 'EVENT'
WHERE `worker_type` = 'LEAVE_APPROVER';

-- 存量回填 2：运行计划文案已明示「触发式 / 随时唤起 / 按需」的，归为对应非定时模式
UPDATE `agent_worker`
SET `run_mode` = 'EVENT'
WHERE `run_mode` = 'SCHEDULED'
  AND (`schedule_text` LIKE '%触发式%' OR `schedule_text` LIKE '%有申请即审%');

UPDATE `agent_worker`
SET `run_mode` = 'ON_DEMAND'
WHERE `run_mode` = 'SCHEDULED'
  AND (`schedule_text` LIKE '%随时唤起%' OR `schedule_text` LIKE '%按需%');

-- 存量修正 3（走查发现 D-1 数据侧）：政策快讯员任务内容过于笼统（「重新汇总这项工作」），
-- 模型无从下手只能反问「请把材料发给我…」，导致该次运行结果被当成「产出」展示。
-- 改为可执行、自足的任务指令，不向用户索要材料。
UPDATE `agent_worker`
SET `task_prompt` = '汇总近 7 天行业政策动态，按「政策名称 / 发布主体 / 核心要点 / 影响对象 / 建议动作」五段输出。信息不足时按已知内容给出结论，不要向用户索要补充材料。'
WHERE `deleted_at` IS NULL
  AND `name` = '政策快讯员'
  AND (`task_prompt` IS NULL OR `task_prompt` IN ('重新汇总这项工作', '重新汇总这项工作。'));
