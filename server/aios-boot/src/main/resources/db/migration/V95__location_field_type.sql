-- V95 · 新增 location 定位字段类型（考勤/签到定位权限，缺陷2）
--
-- 背景：前后端控件白名单原本不认 location；移动签到(mobile_checkin)表单的 location
-- 字段被当作普通 text 处理，考勤申诉(attendance_appeal)表单缺定位字段。
-- 本迁移补齐：
--   1) mobile_checkin：把 properties.location.x-type 从 text 改为 location
--      （12 行 = 12 个租户/机构，全部 alive 行统一处理，幂等）
--   2) attendance_appeal：追加非必填 location 字段「打卡/申诉地点」
-- 配套改动（同仓）：
--   · 前端 renderFormHtml 新增 location 分支（只读框 + 「获取定位」按钮 + 用途/错误引导）
--   · 前端 FORM_FIELD_TYPES、collectFormValues、validateForm 加入 location（按文本处理）
--   · 后端 FormFieldMeta.CONTROL_TYPES 与 FormSchemaValidator.WHITELIST 加入 location
--     （值按字符串处理，非空即可；兼容「纬度,经度」与地址文本）
--
-- 幂等：JSON_SET 仅改/补目标路径，重复执行结果一致。

UPDATE `form_template`
SET `schema_json` = JSON_SET(`schema_json`, '$.properties.location."x-type"', 'location')
WHERE `code` = 'mobile_checkin' AND `alive` = 1 AND `deleted_at` IS NULL;

UPDATE `form_template`
SET `schema_json` = JSON_SET(
    `schema_json`,
    '$.properties.location',
    CAST('{"type":"string","title":"打卡/申诉地点","x-type":"location","description":"定位地址"}' AS JSON)
)
WHERE `code` = 'attendance_appeal' AND `alive` = 1 AND `deleted_at` IS NULL;
