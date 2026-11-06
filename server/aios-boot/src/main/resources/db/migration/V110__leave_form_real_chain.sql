-- V110 · 请假表单接真链路：假种选项改字典引用、天数改系统派生字段
--
-- 背景（2026-11-06 实测）：
--   ① V86 把 leave_type 写死成静态 enum（ANNUAL/SICK/PERSONAL/COMPENSATORY/MARRIAGE/MATERNITY），
--      而 leave_type 字典表里的真值是 ANNUAL/SICK/CASUAL/COMP/MARRIAGE/MATERNITY ——
--      PERSONAL（事假）与 COMPENSATORY（调休）在字典里根本不存在，
--      用户选了这两个必然在 LeaveService.submit 里报「假种不存在」。
--      改用 x-options-ref 由后端在渲染时内联字典（FormTemplateService.resolveOptions 已支持）。
--   ② days 原先 required 且由用户填，后端起止日期算出来的天数并不参与，
--      用户可以填 1 天实休 5 天、余额只扣 1 天。改为 x-system 派生字段：
--      不进必填校验、前端不渲染，值由 LeaveService.calcDays 按假种 unit 计算。
--
-- 为什么改这里而不是改 V86：
--   V86 已在所有环境执行过，改它会让 flyway_schema_history 的 checksum 与库里记录不一致，
--   只有带 -Dspring.flyway.validate-on-migrate=false 才能启动 —— 启动脚本确实带了，
--   但那是「根因已在库里修好、只为两处入口一致」而存在的开关，不该被当成改历史迁移的许可。
--   新库按 V86 → V110 顺序执行，结果与旧库升级后完全一致。
--
-- 幂等：JSON_SET 直接赋值，重复执行结果不变（version 会重复自增，故只在 schema 仍是旧形状时更新）。
UPDATE `form_template`
   SET `schema_json` = JSON_SET(
           `schema_json`,
           -- 假种：去掉写死枚举，改引用字典（CASUAL/COMP 等真码随之正确）
           '$.properties.leave_type', JSON_OBJECT(
               'type', 'string',
               'title', '假种',
               'x-type', 'select',
               'x-options-ref', 'leave_types'),
           -- 天数：派生字段，后端算，前端不渲染、不校验
           '$.properties.days', JSON_OBJECT(
               'type', 'number',
               'title', '请假天数',
               'x-type', 'number',
               'x-system', 'days'),
           -- required 顺序即业务渲染顺序；days 移出后剩余四项保持原序
           '$.required', JSON_ARRAY('leave_type', 'start_date', 'end_date', 'reason')),
       `version` = `version` + 1,
       `updated_at` = NOW(6)
 WHERE `tenant_id` = 0
   AND `code` = 'leave_request'
   -- 只在还是旧形状时更新：已经带 x-options-ref 就不再动，保证可重复执行
   -- ★ 键名里有连字符，JSON path 必须写成带双引号的 "x-options-ref"，
   --   否则 MySQL 直接报 Invalid JSON path expression（实测踩过，Flyway 会让后端起不来）。
   AND JSON_EXTRACT(`schema_json`, '$.properties.leave_type."x-options-ref"') IS NULL;
