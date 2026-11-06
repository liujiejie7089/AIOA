-- V111 · 请假表单修正同步到各租户副本
--
-- 为什么还需要这一条：
--   V110 只修了平台默认行（tenant_id=0）。但租户建号时会把平台表单**复制一份**到本租户，
--   `FormTemplateService.getByCode` 又是「本租户优先、没有才回退平台」——
--   于是登录进来读到的其实是租户那份旧定义：假种还是 PERSONAL/COMPENSATORY，
--   days 还是用户必填。实测：tenant=56 的 id=259 就是 V86 的原样副本。
--   （2026-11-06 第一次跑 V110 后跑回归，V2d/V2c'' 两条判据原样报红才发现的。）
--
-- 判据不按「code 等于 leave_request」一把梭：
--   只修**还带着无效假种码**（PERSONAL / COMPENSATORY，leave_type 字典表里不存在）的行 ——
--   这几行必然是从 V86 复制来、没人改过。租户自己维护过枚举的行不动。
--   已经修过的行（x-options-ref 已存在）也跳过，可重复执行。
UPDATE `form_template`
   SET `schema_json` = JSON_SET(
           `schema_json`,
           '$.properties.leave_type', JSON_OBJECT(
               'type', 'string',
               'title', '假种',
               'x-type', 'select',
               'x-options-ref', 'leave_types'),
           '$.properties.days', JSON_OBJECT(
               'type', 'number',
               'title', '请假天数',
               'x-type', 'number',
               'x-system', 'days'),
           '$.required', JSON_ARRAY('leave_type', 'start_date', 'end_date', 'reason')),
       `version` = `version` + 1,
       `updated_at` = NOW(6)
 WHERE `code` = 'leave_request'
   AND `deleted_at` IS NULL
   AND JSON_EXTRACT(`schema_json`, '$.properties.leave_type."x-options-ref"') IS NULL
   AND (JSON_SEARCH(`schema_json`, 'one', 'COMPENSATORY', NULL, '$.properties.leave_type.enum') IS NOT NULL
        OR JSON_SEARCH(`schema_json`, 'one', 'PERSONAL', NULL, '$.properties.leave_type.enum') IS NOT NULL);
