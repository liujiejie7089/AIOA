-- V33 词元包「适用场景」可配置化 + 系统参数值放宽
--
-- 需求（V33 批次 · 功能项五）：词元包购买页下方新增「适用场景」展示区，内容由后端自定义配置，
-- 不得写死在 H5 里。落地方式沿用既有 sys_config 体系：
--   · platform 默认行（tenant_id=0）作为模板与兜底；
--   · 已存在租户各插一行，保证租户管理员在「系统参数」页可直接编辑；
--   · 未插行的租户由读取接口回落到 tenant_id=0，不会看不到。
--
-- 另：场景内容是多条结构化文案，JSON 很容易超过 VARCHAR(512)，
-- 故把 config_value / default_value 放宽为 TEXT，消除「编辑长文案被截断/报错」的隐患。

ALTER TABLE `sys_config`
    MODIFY COLUMN `config_value` TEXT NOT NULL COMMENT '参数值（统一以字符串存储）',
    MODIFY COLUMN `default_value` TEXT NOT NULL COMMENT '出厂默认值（用于恢复默认）';

-- 平台默认模板（tenant_id = 0）
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `editable`, `sort_no`)
VALUES
    (0, 'billing.package.scenes',
     '[{"icon":"user","title":"个人试用","desc":"想先用起来再决定：日常问答、材料随手处理。","points":["体验词元包 · 10 万词元","购买即到账，无需审批"]},{"icon":"spark","title":"团队协作","desc":"3–10 人小组共享额度：周报整理、会议纪要、材料起草。","points":["团队词元包 · 60 万词元","按项目/人头分摊消耗"]},{"icon":"bank","title":"企业规模化","desc":"全单位推广、多机构统一结算与配额下钻。","points":["企业词元包 · 130 万词元","支持机构与部门额度分发"]}]',
     'JSON', 'QUOTA', '词元包适用场景',
     '用户端「购买词元包」页底部的适用场景卡片；JSON 数组，每项 {icon,title,desc,points[]}，icon 取 sprite 图标名（user/spark/bank 等）',
     '', 
     '[{"icon":"user","title":"个人试用","desc":"想先用起来再决定：日常问答、材料随手处理。","points":["体验词元包 · 10 万词元","购买即到账，无需审批"]},{"icon":"spark","title":"团队协作","desc":"3–10 人小组共享额度：周报整理、会议纪要、材料起草。","points":["团队词元包 · 60 万词元","按项目/人头分摊消耗"]},{"icon":"bank","title":"企业规模化","desc":"全单位推广、多机构统一结算与配额下钻。","points":["企业词元包 · 130 万词元","支持机构与部门额度分发"]}]',
     1, 40)
ON DUPLICATE KEY UPDATE `updated_at` = NOW(6);

-- 已存在的租户各补一行（已访问过「系统参数」的租户不会自动克隆新键，需在此补齐）
INSERT INTO `sys_config`
    (`tenant_id`, `config_key`, `config_value`, `value_type`, `group_code`, `config_name`,
     `description`, `unit`, `default_value`, `editable`, `sort_no`)
SELECT t.id, p.config_key, p.default_value, p.value_type, p.group_code, p.config_name,
       p.description, p.unit, p.default_value, p.editable, p.sort_no
FROM `sys_tenant` t
CROSS JOIN `sys_config` p
WHERE p.tenant_id = 0
  AND p.config_key = 'billing.package.scenes'
  AND t.id <> 0
  AND t.deleted_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM `sys_config` x
      WHERE x.tenant_id = t.id AND x.config_key = p.config_key
  );
