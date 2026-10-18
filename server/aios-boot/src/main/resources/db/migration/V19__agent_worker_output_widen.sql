-- V19 数字员工产出字段扩容 + 创建/编辑闭环补充
--
-- 背景：V15 建表时 agent_worker.last_output 为 varchar(256)，但
-- WorkerScheduleService.summarize() 会写入「[MM-dd HH:mm] + 最多 300 字产出」，
-- 实际可达约 290 字符，导致中文场景下写库报
--   Data truncation: Data too long for column 'last_output'
-- 使「立即执行 / 定时执行」在成功调用模型后仍然整体失败并回滚。此处扩容。
--
-- 同时补充：executor 记录最近一次失败原因，便于「待配置/执行失败」在用户端可见。

ALTER TABLE `agent_worker`
    MODIFY COLUMN `last_output` TEXT NULL COMMENT '最近产出摘要（模型真实生成，截断展示）';

ALTER TABLE `agent_worker`
    MODIFY COLUMN `schedule_text` VARCHAR(255) NULL COMMENT '运行计划说明';
