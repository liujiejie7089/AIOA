-- ===========================================================================
-- V44 · 各业务默认知会回填（只补空、不覆盖）
-- ===========================================================================
-- 背景（docs/25 PRD §3.3 / C-10，docs/26 架构 §3.2）：
--   三期「知会通用化」后，任一业务的 steps_json[0].cc 均生效。
--   本迁移为**租户级默认流**（institution_id=0）补齐默认知会对象，
--   使老租户也拿到与播种器 DEFAULTS 一致的口径。
--
-- 纪律（与 V26 / V39 / V42 播种器一致）：
--   · 只处理租户级默认流（institution_id=0）；机构级显式配置一律不动；
--   · 仅当该流程 steps_json[0] **尚无 cc 键**时才补（JSON_CONTAINS_PATH=0）；
--   · JSON_TYPE(...)='ARRAY' 守卫 —— 若某租户流程被配成非数组则跳过（宁可漏补，不可改坏）。
-- 注：MySQL 8 中 lead / rank 等为窗口函数保留字，本文件无子查询别名，无此风险。
-- ===========================================================================

-- PERMISSION_GRANT 已由 V42 配 cc:[ORG_ADMIN]；此处仅防「曾被手工清空」的漏网行。
UPDATE `approval_flow_def`
SET `steps_json` = JSON_SET(`steps_json`, '$[0].cc', JSON_ARRAY('ORG_ADMIN')),
    `updated_at` = NOW(6)
WHERE `institution_id` = 0 AND `biz_type` = 'PERMISSION_GRANT'
  AND `status` = 'ACTIVE' AND `deleted_at` IS NULL
  AND JSON_TYPE(`steps_json`) = 'ARRAY'
  AND JSON_CONTAINS_PATH(`steps_json`, 'one', '$[0].cc') = 0;

-- LEAVE：跳级时机构管理员仍应知情 → cc:[ORG_ADMIN]
UPDATE `approval_flow_def`
SET `steps_json` = JSON_SET(`steps_json`, '$[0].cc', JSON_ARRAY('ORG_ADMIN')),
    `updated_at` = NOW(6)
WHERE `institution_id` = 0 AND `biz_type` = 'LEAVE'
  AND `status` = 'ACTIVE' AND `deleted_at` IS NULL
  AND JSON_TYPE(`steps_json`) = 'ARRAY'
  AND JSON_CONTAINS_PATH(`steps_json`, 'one', '$[0].cc') = 0;

-- QUOTA_EXPAND / RESOURCE_OPEN：末级为租户管理员 → cc:[TENANT_ADMIN]
UPDATE `approval_flow_def`
SET `steps_json` = JSON_SET(`steps_json`, '$[0].cc', JSON_ARRAY('TENANT_ADMIN')),
    `updated_at` = NOW(6)
WHERE `institution_id` = 0 AND `biz_type` IN ('QUOTA_EXPAND', 'RESOURCE_OPEN')
  AND `status` = 'ACTIVE' AND `deleted_at` IS NULL
  AND JSON_TYPE(`steps_json`) = 'ARRAY'
  AND JSON_CONTAINS_PATH(`steps_json`, 'one', '$[0].cc') = 0;

-- 说明：对外发文 / 成果类（ApprovalService 单级）的 bizType 字面值未在 PRD 明确（N-4），
--       本迁移**不回填**该类，由租户管理员显式配置。
