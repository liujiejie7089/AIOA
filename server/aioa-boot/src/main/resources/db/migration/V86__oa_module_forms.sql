-- V86 · OA 43 个功能模块表单定义种子（docs/52 P5 首批铺开）
--
-- 由 scripts/_gen_oa_form_seed.py 生成，**勿手改**；复跑：
--     python scripts/_gen_oa_form_seed.py
-- 幂等：所有 INSERT 均带 WHERE NOT EXISTS / NOT EXISTS 子查询，可重复执行。
-- 不改 V85（form_template 等四表结构以此文件为准），不 DELETE 任何业务数据。
--
-- 约定：biz_type 仅请假=LEAVE，其余空；submit_policy 仅请假=APPROVAL+RESUME，其余=LEDGER。
-- schema_json 用 x-type 承载白名单控件类型（text/textarea/number/amount/date/datetime/
-- select/multiselect/file/boolean），select/multiselect 用 enum+enumNames 内联静态选项。

-- ── 1) form_template：43 个模块平台默认定义（tenant_id=0, created_by=0）──
INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'doc_draft', '公文助手', 'doc', NULL, '{"type": "object", "properties": {"doc_kind": {"type": "string", "title": "公文种类", "x-type": "select", "enum": ["OUT", "IN"], "enumNames": ["发文", "收文"]}, "title": {"type": "string", "title": "公文标题", "x-type": "text", "description": "请输入公文标题"}, "urgency": {"type": "string", "title": "紧急程度", "x-type": "select", "enum": ["NORMAL", "URGENT", "FLASH"], "enumNames": ["普通", "紧急", "特急"]}, "secret_level": {"type": "string", "title": "涉密等级", "x-type": "select", "enum": ["PUBLIC", "INTERNAL", "SECRET", "CONFIDENTIAL"], "enumNames": ["非涉密", "内部", "秘密", "机密"]}, "summary": {"type": "string", "title": "正文摘要", "x-type": "textarea", "description": "请填写公文正文要点"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["doc_kind", "title", "urgency", "summary"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "公文助手提交成功", "display_fields": ["doc_kind", "title", "urgency", "secret_level"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'doc_draft');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'archive_borrow', '档案助手', 'archive', NULL, '{"type": "object", "properties": {"archive_type": {"type": "string", "title": "档案类别", "x-type": "select", "enum": ["DOC", "TECH", "ACCT", "AV"], "enumNames": ["文书档案", "科技档案", "会计档案", "声像档案"]}, "archive_no": {"type": "string", "title": "档号", "x-type": "text", "description": "已知档号可填，便于调阅"}, "title": {"type": "string", "title": "档案题名", "x-type": "text", "description": "请输入档案题名"}, "borrow_use": {"type": "string", "title": "借阅用途", "x-type": "textarea", "description": "说明借阅用途"}, "return_date": {"type": "string", "title": "预计归还日期", "x-type": "date"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["archive_type", "title", "borrow_use", "return_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "档案助手提交成功", "display_fields": ["archive_type", "archive_no", "title", "borrow_use"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'archive_borrow');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'meeting_book', '会议助手', 'meeting', NULL, '{"type": "object", "properties": {"title": {"type": "string", "title": "会议主题", "x-type": "text", "description": "请输入会议主题"}, "meeting_type": {"type": "string", "title": "会议类型", "x-type": "select", "enum": ["REGULAR", "THEME", "DECISION", "TRAIN"], "enumNames": ["例会", "专题会", "决策会", "培训会"]}, "start_time": {"type": "string", "title": "开始时间", "x-type": "datetime"}, "end_time": {"type": "string", "title": "结束时间", "x-type": "datetime"}, "attendees": {"type": "string", "title": "参会人", "x-type": "textarea", "description": "列明参会人员/部门"}, "agenda": {"type": "string", "title": "议程", "x-type": "textarea"}}, "required": ["title", "meeting_type", "start_time", "end_time", "attendees"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "会议助手提交成功", "display_fields": ["title", "meeting_type", "start_time", "end_time"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'meeting_book');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'contact_add', '通讯录', 'contact', NULL, '{"type": "object", "properties": {"person_name": {"type": "string", "title": "姓名", "x-type": "text"}, "dept": {"type": "string", "title": "部门", "x-type": "text"}, "title": {"type": "string", "title": "职务", "x-type": "text"}, "phone": {"type": "string", "title": "手机号", "x-type": "text", "description": "联系电话"}, "email": {"type": "string", "title": "邮箱", "x-type": "text"}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["person_name", "dept", "phone"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "通讯录提交成功", "display_fields": ["person_name", "dept", "title", "phone"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'contact_add');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'worklog_submit', '工作日志', 'worklog', NULL, '{"type": "object", "properties": {"log_date": {"type": "string", "title": "日期", "x-type": "date"}, "today_work": {"type": "string", "title": "今日工作", "x-type": "textarea", "description": "记录当日完成工作"}, "tomorrow_plan": {"type": "string", "title": "明日计划", "x-type": "textarea"}, "project_tag": {"type": "string", "title": "关联项目", "x-type": "text", "description": "可选关联项目"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["log_date", "today_work"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工作日志提交成功", "display_fields": ["log_date", "today_work", "tomorrow_plan", "project_tag"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'worklog_submit');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'workplan_submit', '工作计划', 'workplan', NULL, '{"type": "object", "properties": {"plan_name": {"type": "string", "title": "计划名称", "x-type": "text"}, "cycle": {"type": "string", "title": "计划周期", "x-type": "select", "enum": ["YEAR", "MONTH", "WEEK"], "enumNames": ["年度", "月度", "周"]}, "goal": {"type": "string", "title": "目标", "x-type": "textarea"}, "owner": {"type": "string", "title": "责任人", "x-type": "text"}, "start_date": {"type": "string", "title": "开始日期", "x-type": "date"}, "end_date": {"type": "string", "title": "结束日期", "x-type": "date"}}, "required": ["plan_name", "cycle", "goal", "owner", "start_date", "end_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工作计划提交成功", "display_fields": ["plan_name", "cycle", "goal", "owner"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'workplan_submit');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'weekly_submit', '工作周报', 'weekly', NULL, '{"type": "object", "properties": {"week_no": {"type": "string", "title": "周次", "x-type": "text", "description": "如 2026-W42"}, "done": {"type": "string", "title": "本周完成", "x-type": "textarea"}, "next_plan": {"type": "string", "title": "下周计划", "x-type": "textarea"}, "blockers": {"type": "string", "title": "需协调事项", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["week_no", "done", "next_plan"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工作周报提交成功", "display_fields": ["week_no", "done", "next_plan", "blockers"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'weekly_submit');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'expense_form', '费用报销', 'expense', NULL, '{"type": "object", "properties": {"expense_type": {"type": "string", "title": "费用类型", "x-type": "select", "enum": ["TRAVEL", "ENTERTAIN", "OFFICE", "OTHER"], "enumNames": ["差旅", "招待", "办公", "其他"]}, "amount": {"type": "number", "title": "金额", "x-type": "amount"}, "occur_date": {"type": "string", "title": "发生日期", "x-type": "date"}, "reason": {"type": "string", "title": "费用说明", "x-type": "textarea"}, "invoice": {"type": "string", "title": "发票", "x-type": "file"}, "project": {"type": "string", "title": "所属项目", "x-type": "text"}}, "required": ["expense_type", "amount", "occur_date", "reason", "invoice"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "费用报销提交成功", "display_fields": ["expense_type", "amount", "occur_date", "reason"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'expense_form');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'travel_form', '出差助手', 'travel', NULL, '{"type": "object", "properties": {"destination": {"type": "string", "title": "出差地点", "x-type": "text"}, "start_date": {"type": "string", "title": "出发日期", "x-type": "date"}, "end_date": {"type": "string", "title": "返回日期", "x-type": "date"}, "reason": {"type": "string", "title": "出差事由", "x-type": "textarea"}, "transport": {"type": "string", "title": "交通工具", "x-type": "select", "enum": ["FLIGHT", "RAIL", "BUS", "CAR"], "enumNames": ["飞机", "高铁", "汽车", "自驾"]}, "est_amount": {"type": "number", "title": "预计费用", "x-type": "amount"}}, "required": ["destination", "start_date", "end_date", "reason", "transport"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "出差助手提交成功", "display_fields": ["destination", "start_date", "end_date", "reason"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'travel_form');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'seal_apply', '印章助手', 'seal', NULL, '{"type": "object", "properties": {"seal_type": {"type": "string", "title": "印章类型", "x-type": "select", "enum": ["OFFICIAL", "CONTRACT", "FINANCE", "LEGAL"], "enumNames": ["公章", "合同章", "财务章", "法人章"]}, "file_title": {"type": "string", "title": "用印文件标题", "x-type": "text"}, "reason": {"type": "string", "title": "用印事由", "x-type": "textarea"}, "use_date": {"type": "string", "title": "用印日期", "x-type": "date"}, "copies": {"type": "number", "title": "用印份数", "x-type": "number"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["seal_type", "file_title", "reason", "use_date", "copies"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "印章助手提交成功", "display_fields": ["seal_type", "file_title", "reason", "use_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'seal_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'project_create', '项目助手', 'project', NULL, '{"type": "object", "properties": {"project_name": {"type": "string", "title": "项目名称", "x-type": "text"}, "goal": {"type": "string", "title": "项目目标", "x-type": "textarea"}, "start_date": {"type": "string", "title": "开始日期", "x-type": "date"}, "end_date": {"type": "string", "title": "结束日期", "x-type": "date"}, "budget": {"type": "number", "title": "预算金额", "x-type": "amount"}, "risk": {"type": "string", "title": "风险说明", "x-type": "textarea"}}, "required": ["project_name", "goal", "start_date", "end_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "项目助手提交成功", "display_fields": ["project_name", "goal", "start_date", "end_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'project_create');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'favorite_add', '收藏夹', 'favorite', NULL, '{"type": "object", "properties": {"fav_type": {"type": "string", "title": "收藏类型", "x-type": "select", "enum": ["URL", "FILE", "IMAGE", "NOTE"], "enumNames": ["网址", "文件", "图片", "笔记"]}, "title": {"type": "string", "title": "标题", "x-type": "text"}, "content": {"type": "string", "title": "链接或内容", "x-type": "textarea"}, "tags": {"type": "string", "title": "标签", "x-type": "text", "description": "逗号分隔"}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["fav_type", "title", "content"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "收藏夹提交成功", "display_fields": ["fav_type", "title", "content", "tags"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'favorite_add');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'milestone_add', '大事记', 'milestone', NULL, '{"type": "object", "properties": {"event_title": {"type": "string", "title": "事件标题", "x-type": "text"}, "event_date": {"type": "string", "title": "事件日期", "x-type": "date"}, "category": {"type": "string", "title": "事件分类", "x-type": "select", "enum": ["HONOR", "MILESTONE", "ACTIVITY", "CHANGE"], "enumNames": ["荣誉", "里程碑", "重大活动", "变更"]}, "description": {"type": "string", "title": "事件描述", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["event_title", "event_date", "category", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "大事记提交成功", "display_fields": ["event_title", "event_date", "category", "description"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'milestone_add');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'calendar_event', '工作日历', 'calendar', NULL, '{"type": "object", "properties": {"event_title": {"type": "string", "title": "日程标题", "x-type": "text"}, "start_time": {"type": "string", "title": "开始时间", "x-type": "datetime"}, "end_time": {"type": "string", "title": "结束时间", "x-type": "datetime"}, "all_day": {"type": "boolean", "title": "是否全天", "x-type": "boolean"}, "remind_way": {"type": "string", "title": "提醒方式", "x-type": "select", "enum": ["POP", "SMS", "MAIL"], "enumNames": ["弹窗", "短信", "邮件"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["event_title", "start_time", "end_time"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工作日历提交成功", "display_fields": ["event_title", "start_time", "end_time", "all_day"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'calendar_event');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'notice_publish', '通知公告', 'notice', NULL, '{"type": "object", "properties": {"title": {"type": "string", "title": "标题", "x-type": "text"}, "category": {"type": "string", "title": "公告分类", "x-type": "select", "enum": ["NOTICE", "BULLETIN", "RULE", "HR"], "enumNames": ["通知", "公告", "制度", "人事"]}, "scope": {"type": "string", "title": "发布范围", "x-type": "textarea", "description": "指定部门/人员或全员"}, "body": {"type": "string", "title": "正文", "x-type": "textarea"}, "pinned": {"type": "boolean", "title": "是否置顶", "x-type": "boolean"}, "expire_date": {"type": "string", "title": "有效期至", "x-type": "date"}}, "required": ["title", "category", "scope", "body"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "通知公告提交成功", "display_fields": ["title", "category", "scope", "body"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'notice_publish');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'publish_article', '信息发布', 'publish', NULL, '{"type": "object", "properties": {"column": {"type": "string", "title": "栏目", "x-type": "select", "enum": ["NEWS", "SPECIAL", "HR", "CULTURE"], "enumNames": ["新闻动态", "专题", "人事风采", "企业文化"]}, "title": {"type": "string", "title": "标题", "x-type": "text"}, "body": {"type": "string", "title": "正文", "x-type": "textarea"}, "author": {"type": "string", "title": "作者", "x-type": "text"}, "schedule_at": {"type": "string", "title": "定时发布", "x-type": "datetime"}}, "required": ["column", "title", "body"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "信息发布提交成功", "display_fields": ["column", "title", "body", "author"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'publish_article');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'assign_task', '工作安排', 'assign', NULL, '{"type": "object", "properties": {"task_title": {"type": "string", "title": "任务标题", "x-type": "text"}, "owner": {"type": "string", "title": "责任人", "x-type": "text"}, "requirement": {"type": "string", "title": "任务要求", "x-type": "textarea"}, "due_date": {"type": "string", "title": "截止日期", "x-type": "date"}, "priority": {"type": "string", "title": "优先级", "x-type": "select", "enum": ["HIGH", "MID", "LOW"], "enumNames": ["高", "中", "低"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["task_title", "owner", "requirement", "due_date", "priority"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工作安排提交成功", "display_fields": ["task_title", "owner", "requirement", "due_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'assign_task');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'remind_rule', '重要提醒', 'remind', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "提醒事项", "x-type": "text"}, "remind_type": {"type": "string", "title": "提醒类型", "x-type": "select", "enum": ["APPROVAL", "TASK", "SCHEDULE", "CONTRACT", "LICENSE", "DEVICE"], "enumNames": ["审批", "任务", "日程", "合同到期", "证照到期", "设备维保"]}, "remind_time": {"type": "string", "title": "提醒时间", "x-type": "datetime"}, "urgency": {"type": "string", "title": "紧急程度", "x-type": "select", "enum": ["URGENT", "NORMAL"], "enumNames": ["紧急", "普通"]}, "channels": {"type": "array", "title": "提醒渠道", "x-type": "multiselect", "items": {"type": "string"}, "enum": ["POP", "SMS", "MAIL"], "enumNames": ["弹窗", "短信", "邮件"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["matter", "remind_type", "remind_time", "urgency"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "重要提醒提交成功", "display_fields": ["matter", "remind_type", "remind_time", "urgency"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'remind_rule');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'vehicle_apply', '用车助手', 'vehicle', NULL, '{"type": "object", "properties": {"reason": {"type": "string", "title": "用车事由", "x-type": "textarea"}, "from_addr": {"type": "string", "title": "出发地", "x-type": "text"}, "to_addr": {"type": "string", "title": "目的地", "x-type": "text"}, "start_time": {"type": "string", "title": "用车开始", "x-type": "datetime"}, "end_time": {"type": "string", "title": "用车结束", "x-type": "datetime"}, "passengers": {"type": "number", "title": "乘车人数", "x-type": "number"}}, "required": ["reason", "from_addr", "to_addr", "start_time", "end_time", "passengers"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "用车助手提交成功", "display_fields": ["reason", "from_addr", "to_addr", "start_time"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'vehicle_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'leave_request', '请假助手', 'leave', 'LEAVE', '{"type": "object", "properties": {"leave_type": {"type": "string", "title": "假种", "x-type": "select", "enum": ["ANNUAL", "SICK", "PERSONAL", "COMPENSATORY", "MARRIAGE", "MATERNITY"], "enumNames": ["年休假", "病假", "事假", "调休", "婚假", "产假"]}, "start_date": {"type": "string", "title": "开始日期", "x-type": "date"}, "end_date": {"type": "string", "title": "结束日期", "x-type": "date"}, "days": {"type": "number", "title": "请假天数", "x-type": "number"}, "reason": {"type": "string", "title": "请假事由", "x-type": "textarea"}, "proof": {"type": "string", "title": "证明材料", "x-type": "file"}}, "required": ["leave_type", "start_date", "end_date", "days", "reason"], "additionalProperties": false}', NULL, 'APPROVAL+RESUME', '{"title": "请假助手提交成功", "display_fields": ["leave_type", "start_date", "end_date", "days"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'leave_request');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'attendance_appeal', '考勤管理', 'attendance', NULL, '{"type": "object", "properties": {"appeal_type": {"type": "string", "title": "申诉类型", "x-type": "select", "enum": ["MISS", "LATE", "EARLY", "OUT"], "enumNames": ["漏打卡", "迟到", "早退", "外勤"]}, "appeal_date": {"type": "string", "title": "申诉日期", "x-type": "date"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}, "proof": {"type": "string", "title": "证明材料", "x-type": "file"}}, "required": ["appeal_type", "appeal_date", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "考勤管理提交成功", "display_fields": ["appeal_type", "appeal_date", "description", "proof"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'attendance_appeal');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'doc_upload', '文档管理', 'docmgr', NULL, '{"type": "object", "properties": {"doc_title": {"type": "string", "title": "文档标题", "x-type": "text"}, "doc_category": {"type": "string", "title": "文档分类", "x-type": "select", "enum": ["POLICY", "TECH", "REPORT", "TEMP"], "enumNames": ["制度", "技术", "报告", "模板"]}, "share_scope": {"type": "string", "title": "共享范围", "x-type": "textarea", "description": "指定部门/人员"}, "expire_date": {"type": "string", "title": "有效期至", "x-type": "date"}, "file": {"type": "string", "title": "文件", "x-type": "file"}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["doc_title", "doc_category", "share_scope", "file"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "文档管理提交成功", "display_fields": ["doc_title", "doc_category", "share_scope", "expire_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'doc_upload');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'party_apply', '党务助手', 'party', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["FEE", "LIFESTUDY", "DEV"], "enumNames": ["党费缴纳", "组织生活报名", "发展流程申报"]}, "person_name": {"type": "string", "title": "姓名", "x-type": "text"}, "amount": {"type": "number", "title": "金额", "x-type": "amount"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}}, "required": ["matter", "person_name"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "党务助手提交成功", "display_fields": ["matter", "person_name", "amount", "description"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'party_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'union_apply', '工会工作', 'union', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["HELP", "ACTIVITY", "PROPOSAL", "MODEL"], "enumNames": ["困难帮扶", "活动报名", "提案征集", "劳模评选"]}, "applicant": {"type": "string", "title": "申请人", "x-type": "text"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["matter", "applicant", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "工会工作提交成功", "display_fields": ["matter", "applicant", "description", "attachments"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'union_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'todo_add', '待办助手', 'todo', NULL, '{"type": "object", "properties": {"todo_title": {"type": "string", "title": "待办标题", "x-type": "text"}, "scope": {"type": "string", "title": "负责范围", "x-type": "text"}, "due_time": {"type": "string", "title": "截止时间", "x-type": "datetime"}, "priority": {"type": "string", "title": "优先级", "x-type": "select", "enum": ["HIGH", "MID", "LOW"], "enumNames": ["高", "中", "低"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["todo_title", "due_time", "priority"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "待办助手提交成功", "display_fields": ["todo_title", "scope", "due_time", "priority"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'todo_add');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'delegate_rule', '委托管理', 'delegate', NULL, '{"type": "object", "properties": {"delegatee": {"type": "string", "title": "受托人", "x-type": "text"}, "start_date": {"type": "string", "title": "委托开始", "x-type": "date"}, "end_date": {"type": "string", "title": "委托结束", "x-type": "date"}, "matters": {"type": "string", "title": "委托事项", "x-type": "textarea"}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["delegatee", "start_date", "end_date", "matters"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "委托管理提交成功", "display_fields": ["delegatee", "start_date", "end_date", "matters"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'delegate_rule');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'portal_layout', '门户首页', 'portal', NULL, '{"type": "object", "properties": {"workbench_name": {"type": "string", "title": "工作台名称", "x-type": "text"}, "cards": {"type": "string", "title": "卡片配置", "x-type": "textarea", "description": "JSON/文本描述卡片组合"}, "theme": {"type": "string", "title": "主题", "x-type": "select", "enum": ["DEFAULT", "DARK", "LIGHT"], "enumNames": ["默认", "暗色", "浅色"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["workbench_name", "cards"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "门户首页提交成功", "display_fields": ["workbench_name", "cards", "theme", "remark"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'portal_layout');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'approval_launch', '审批中心', 'approval', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "审批事项", "x-type": "text"}, "approval_type": {"type": "string", "title": "审批类型", "x-type": "select", "enum": ["GENERAL", "CONTRACT", "BUDGET", "HR"], "enumNames": ["一般审批", "合同", "预算", "人事"]}, "urgency": {"type": "string", "title": "紧急程度", "x-type": "select", "enum": ["HIGH", "MID", "LOW"], "enumNames": ["高", "中", "低"]}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["matter", "approval_type", "urgency", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "审批中心提交成功", "display_fields": ["matter", "approval_type", "urgency", "description"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'approval_launch');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'hr_register', '人事管理', 'hr', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["ONBOARD", "TRANSFER", "OFFBOARD"], "enumNames": ["入职登记", "异动转岗", "离职交接"]}, "emp_name": {"type": "string", "title": "员工姓名", "x-type": "text"}, "dept": {"type": "string", "title": "部门", "x-type": "text"}, "position": {"type": "string", "title": "岗位", "x-type": "text"}, "effective_date": {"type": "string", "title": "生效日期", "x-type": "date"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}}, "required": ["matter", "emp_name", "dept", "position", "effective_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "人事管理提交成功", "display_fields": ["matter", "emp_name", "dept", "position"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'hr_register');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'recruit_req', '招聘管理', 'recruit', NULL, '{"type": "object", "properties": {"position": {"type": "string", "title": "需求岗位", "x-type": "text"}, "headcount": {"type": "number", "title": "编制数", "x-type": "number"}, "dept": {"type": "string", "title": "需求部门", "x-type": "text"}, "expect_date": {"type": "string", "title": "期望到岗", "x-type": "date"}, "duty": {"type": "string", "title": "岗位职责", "x-type": "textarea"}}, "required": ["position", "headcount", "dept", "duty"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "招聘管理提交成功", "display_fields": ["position", "headcount", "dept", "expect_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'recruit_req');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'train_signup', '培训管理', 'train', NULL, '{"type": "object", "properties": {"train_name": {"type": "string", "title": "培训名称", "x-type": "text"}, "course_type": {"type": "string", "title": "课程类型", "x-type": "select", "enum": ["ONLINE", "OFFLINE", "MIXED"], "enumNames": ["线上", "线下", "混合"]}, "lecturer": {"type": "string", "title": "讲师", "x-type": "text"}, "start_date": {"type": "string", "title": "开始日期", "x-type": "date"}, "signup_note": {"type": "string", "title": "报名说明", "x-type": "textarea"}}, "required": ["train_name", "course_type", "start_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "培训管理提交成功", "display_fields": ["train_name", "course_type", "lecturer", "start_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'train_signup');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'knowledge_upload', '知识管理', 'knowledge', NULL, '{"type": "object", "properties": {"knowledge_title": {"type": "string", "title": "知识标题", "x-type": "text"}, "category": {"type": "string", "title": "知识分类", "x-type": "select", "enum": ["CASE", "POLICY", "SKILL", "FAQ"], "enumNames": ["经验案例", "制度", "技能", "问答"]}, "tags": {"type": "string", "title": "标签", "x-type": "text", "description": "逗号分隔"}, "summary": {"type": "string", "title": "摘要", "x-type": "textarea"}, "file": {"type": "string", "title": "文件", "x-type": "file"}}, "required": ["knowledge_title", "category", "summary", "file"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "知识管理提交成功", "display_fields": ["knowledge_title", "category", "tags", "summary"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'knowledge_upload');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'asset_apply', '资产管理', 'asset', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["STOCK", "USE", "REPAIR", "SCRAP"], "enumNames": ["入库登记", "领用", "维修", "报废"]}, "asset_name": {"type": "string", "title": "资产名称", "x-type": "text"}, "quantity": {"type": "number", "title": "数量", "x-type": "number"}, "dept": {"type": "string", "title": "使用部门", "x-type": "text"}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["matter", "asset_name", "quantity"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "资产管理提交成功", "display_fields": ["matter", "asset_name", "quantity", "dept"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'asset_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'contract_draft', '合同管理', 'contract', NULL, '{"type": "object", "properties": {"contract_name": {"type": "string", "title": "合同名称", "x-type": "text"}, "counterparty": {"type": "string", "title": "相对方", "x-type": "text"}, "amount": {"type": "number", "title": "合同金额", "x-type": "amount"}, "start_date": {"type": "string", "title": "开始日期", "x-type": "date"}, "end_date": {"type": "string", "title": "结束日期", "x-type": "date"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}}, "required": ["contract_name", "counterparty", "amount", "start_date", "end_date"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "合同管理提交成功", "display_fields": ["contract_name", "counterparty", "amount", "start_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'contract_draft');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'task_supervise', '任务督办', 'task', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "督办事项", "x-type": "text"}, "org_unit": {"type": "string", "title": "责任单位", "x-type": "text"}, "owner": {"type": "string", "title": "责任人", "x-type": "text"}, "due_date": {"type": "string", "title": "截止日期", "x-type": "date"}, "level": {"type": "string", "title": "紧急程度", "x-type": "select", "enum": ["RED", "YELLOW", "GREEN"], "enumNames": ["红", "黄", "绿"]}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}}, "required": ["matter", "org_unit", "owner", "due_date", "level"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "任务督办提交成功", "display_fields": ["matter", "org_unit", "owner", "due_date"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'task_supervise');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'crm_add', '客户管理', 'crm', NULL, '{"type": "object", "properties": {"customer_name": {"type": "string", "title": "客户名称", "x-type": "text"}, "tier": {"type": "string", "title": "客户分层", "x-type": "select", "enum": ["STRATEGIC", "KEY", "NORMAL"], "enumNames": ["战略", "重要", "普通"]}, "contact": {"type": "string", "title": "联系人", "x-type": "text"}, "contact_phone": {"type": "string", "title": "联系电话", "x-type": "text"}, "stage": {"type": "string", "title": "商机阶段", "x-type": "select", "enum": ["LEAD", "TALK", "WON", "LOST"], "enumNames": ["线索", "洽谈", "成交", "流失"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["customer_name", "tier"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "客户管理提交成功", "display_fields": ["customer_name", "tier", "contact", "contact_phone"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'crm_add');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'finance_apply', '财务管理', 'finance', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["BUDGET", "PAY", "RECON"], "enumNames": ["预算编制", "付款申请", "对账"]}, "amount": {"type": "number", "title": "金额", "x-type": "amount"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}, "project": {"type": "string", "title": "关联项目", "x-type": "text"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["matter", "amount", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "财务管理提交成功", "display_fields": ["matter", "amount", "description", "project"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'finance_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'purchase_req', '采购管理', 'purchase', NULL, '{"type": "object", "properties": {"item": {"type": "string", "title": "采购物品", "x-type": "text"}, "quantity": {"type": "number", "title": "数量", "x-type": "number"}, "budget": {"type": "number", "title": "预算金额", "x-type": "amount"}, "expect_arrive": {"type": "string", "title": "期望到货", "x-type": "date"}, "purchase_note": {"type": "string", "title": "采购说明", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["item", "quantity", "budget", "purchase_note"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "采购管理提交成功", "display_fields": ["item", "quantity", "budget", "expect_arrive"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'purchase_req');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'survey_launch', '问卷调查', 'survey', NULL, '{"type": "object", "properties": {"survey_title": {"type": "string", "title": "问卷标题", "x-type": "text"}, "purpose": {"type": "string", "title": "调研目的", "x-type": "textarea"}, "scope": {"type": "string", "title": "发放范围", "x-type": "textarea", "description": "指定部门/人员"}, "anonymous": {"type": "string", "title": "匿名方式", "x-type": "select", "enum": ["ANON", "REALNAME"], "enumNames": ["匿名", "实名"]}, "due_date": {"type": "string", "title": "截止日期", "x-type": "date"}}, "required": ["survey_title", "purpose", "scope", "anonymous"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "问卷调查提交成功", "display_fields": ["survey_title", "purpose", "scope", "anonymous"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'survey_launch');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'security_apply', '安全与权限', 'security', NULL, '{"type": "object", "properties": {"apply_type": {"type": "string", "title": "申请类型", "x-type": "select", "enum": ["ROLE", "DATA", "ACCOUNT"], "enumNames": ["角色授权", "数据权限", "账号开通"]}, "target": {"type": "string", "title": "申请对象", "x-type": "text"}, "scope": {"type": "string", "title": "权限范围", "x-type": "textarea"}, "reason": {"type": "string", "title": "理由", "x-type": "textarea"}}, "required": ["apply_type", "target", "scope", "reason"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "安全与权限提交成功", "display_fields": ["apply_type", "target", "scope", "reason"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'security_apply');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'integration_req', '系统集成', 'integration', NULL, '{"type": "object", "properties": {"integration_type": {"type": "string", "title": "集成类型", "x-type": "select", "enum": ["SSO", "SYNC", "SIGN", "MSG"], "enumNames": ["单点登录", "组织同步", "电子签章", "消息推送"]}, "system_name": {"type": "string", "title": "系统名称", "x-type": "text"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}}, "required": ["integration_type", "system_name", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "系统集成提交成功", "display_fields": ["integration_type", "system_name", "description"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'integration_req');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'analytics_board', '数据分析', 'analytics', NULL, '{"type": "object", "properties": {"board_name": {"type": "string", "title": "看板名称", "x-type": "text"}, "metrics": {"type": "string", "title": "指标范围", "x-type": "textarea", "description": "描述关注指标"}, "push_role": {"type": "string", "title": "推送角色", "x-type": "select", "enum": ["LEADER", "MANAGER", "STAFF"], "enumNames": ["领导", "中层", "全员"]}, "remark": {"type": "string", "title": "备注", "x-type": "textarea"}}, "required": ["board_name", "metrics"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "数据分析提交成功", "display_fields": ["board_name", "metrics", "push_role", "remark"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'analytics_board');

INSERT INTO `form_template` (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT 0, 'mobile_checkin', '移动办公', 'mobile', NULL, '{"type": "object", "properties": {"matter": {"type": "string", "title": "事项类型", "x-type": "select", "enum": ["CHECKIN", "FEEDBACK", "SUGGEST"], "enumNames": ["移动签到", "问题反馈", "功能建议"]}, "location": {"type": "string", "title": "位置", "x-type": "text", "description": "定位地址"}, "description": {"type": "string", "title": "说明", "x-type": "textarea"}, "attachments": {"type": "string", "title": "附件", "x-type": "file"}}, "required": ["matter", "description"], "additionalProperties": false}', NULL, 'LEDGER', '{"title": "移动办公提交成功", "display_fields": ["matter", "location", "description", "attachments"], "buttons": ["查看详情", "返回"]}', 1, 'ACTIVE', 0, NOW(6), NOW(6)
WHERE NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = 0 AND x.`code` = 'mobile_checkin');

-- ── 2) 按租户回填 form_template：以平台定义为唯一数据源，逐租户复制 ──
INSERT INTO `form_template`
    (`tenant_id`, `code`, `name`, `module_code`, `biz_type`, `schema_json`,
     `layout_json`, `submit_policy`, `receipt_json`, `version`, `status`, `created_by`, `created_at`, `updated_at`)
SELECT t.`id`, m.`code`, m.`name`, m.`module_code`, m.`biz_type`, m.`schema_json`,
       m.`layout_json`, m.`submit_policy`, m.`receipt_json`, 1, 'ACTIVE', 0, NOW(6), NOW(6)
FROM `sys_tenant` t
CROSS JOIN (
    SELECT `code`, `name`, `module_code`, `biz_type`, `schema_json`, `layout_json`, `submit_policy`, `receipt_json`
    FROM `form_template` WHERE `tenant_id` = 0 AND `code` IN ('doc_draft', 'archive_borrow', 'meeting_book', 'contact_add', 'worklog_submit', 'workplan_submit', 'weekly_submit', 'expense_form', 'travel_form', 'seal_apply', 'project_create', 'favorite_add', 'milestone_add', 'calendar_event', 'notice_publish', 'publish_article', 'assign_task', 'remind_rule', 'vehicle_apply', 'leave_request', 'attendance_appeal', 'doc_upload', 'party_apply', 'union_apply', 'todo_add', 'delegate_rule', 'portal_layout', 'approval_launch', 'hr_register', 'recruit_req', 'train_signup', 'knowledge_upload', 'asset_apply', 'contract_draft', 'task_supervise', 'crm_add', 'finance_apply', 'purchase_req', 'survey_launch', 'security_apply', 'integration_req', 'analytics_board', 'mobile_checkin')
) m
WHERE t.`id` > 0
  AND NOT EXISTS (SELECT 1 FROM `form_template` x WHERE x.`tenant_id` = t.`id` AND x.`code` = m.`code`);

-- ── 3) form_template_version：每个定义（平台+租户回填）各一条 version=1 快照 ──
INSERT INTO `form_template_version` (`template_id`, `version`, `schema_json`, `layout_json`, `receipt_json`, `created_by`)
SELECT f.`id`, 1, f.`schema_json`, f.`layout_json`, f.`receipt_json`, 0
FROM `form_template` f
WHERE f.`code` IN ('doc_draft', 'archive_borrow', 'meeting_book', 'contact_add', 'worklog_submit', 'workplan_submit', 'weekly_submit', 'expense_form', 'travel_form', 'seal_apply', 'project_create', 'favorite_add', 'milestone_add', 'calendar_event', 'notice_publish', 'publish_article', 'assign_task', 'remind_rule', 'vehicle_apply', 'leave_request', 'attendance_appeal', 'doc_upload', 'party_apply', 'union_apply', 'todo_add', 'delegate_rule', 'portal_layout', 'approval_launch', 'hr_register', 'recruit_req', 'train_signup', 'knowledge_upload', 'asset_apply', 'contract_draft', 'task_supervise', 'crm_add', 'finance_apply', 'purchase_req', 'survey_launch', 'security_apply', 'integration_req', 'analytics_board', 'mobile_checkin')
  AND NOT EXISTS (SELECT 1 FROM `form_template_version` v WHERE v.`template_id` = f.`id` AND v.`version` = 1);

-- ── 4) worker_capability：43 模块各 1 条能力声明，从 agent_worker 派生（模板+实例）──
--    JOIN 条件 t.tenant_id = w.tenant_id AND t.module_code = <稳定码>，保证同租户匹配；
--    worker_type→module_code 映射固化于下方 CASE/WHERE；全部 WHERE NOT EXISTS 幂等。
-- 1 公文助手 (OA_DOC → doc)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'doc_draft', '公文起草', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'doc'
WHERE w.`worker_type` = 'OA_DOC'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'doc_draft');

-- 2 档案助手 (OA_ARCHIVE → archive)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'archive_borrow', '档案借阅', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'archive'
WHERE w.`worker_type` = 'OA_ARCHIVE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'archive_borrow');

-- 3 会议助手 (OA_MEETING → meeting)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'meeting_book', '会议预约', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'meeting'
WHERE w.`worker_type` = 'OA_MEETING'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'meeting_book');

-- 4 通讯录 (OA_CONTACT → contact)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'contact_add', '联系人维护', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'contact'
WHERE w.`worker_type` = 'OA_CONTACT'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'contact_add');

-- 5 工作日志 (OA_WORKLOG → worklog)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'worklog_submit', '工作日志填报', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'worklog'
WHERE w.`worker_type` = 'OA_WORKLOG'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'worklog_submit');

-- 6 工作计划 (OA_WORKPLAN → workplan)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'workplan_submit', '工作计划填报', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'workplan'
WHERE w.`worker_type` = 'OA_WORKPLAN'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'workplan_submit');

-- 7 工作周报 (OA_WEEKLY → weekly)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'weekly_submit', '工作周报填报', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'weekly'
WHERE w.`worker_type` = 'OA_WEEKLY'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'weekly_submit');

-- 8 费用报销 (OA_EXPENSE → expense)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'expense_form', '费用报销申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'expense'
WHERE w.`worker_type` = 'OA_EXPENSE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'expense_form');

-- 9 出差助手 (OA_TRAVEL → travel)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'travel_form', '出差申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'travel'
WHERE w.`worker_type` = 'OA_TRAVEL'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'travel_form');

-- 10 印章助手 (OA_SEAL → seal)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'seal_apply', '用印申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'seal'
WHERE w.`worker_type` = 'OA_SEAL'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'seal_apply');

-- 11 项目助手 (OA_PROJECT → project)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'project_create', '项目立项', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'project'
WHERE w.`worker_type` = 'OA_PROJECT'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'project_create');

-- 12 收藏夹 (OA_FAVORITE → favorite)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'favorite_add', '收藏添加', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'favorite'
WHERE w.`worker_type` = 'OA_FAVORITE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'favorite_add');

-- 13 大事记 (OA_MILESTONE → milestone)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'milestone_add', '大事记录入', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'milestone'
WHERE w.`worker_type` = 'OA_MILESTONE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'milestone_add');

-- 14 工作日历 (OA_CALENDAR → calendar)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'calendar_event', '日程新建', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'calendar'
WHERE w.`worker_type` = 'OA_CALENDAR'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'calendar_event');

-- 15 通知公告 (OA_NOTICE → notice)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'notice_publish', '通知公告发布', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'notice'
WHERE w.`worker_type` = 'OA_NOTICE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'notice_publish');

-- 16 信息发布 (OA_PUBLISH → publish)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'publish_article', '信息发布', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'publish'
WHERE w.`worker_type` = 'OA_PUBLISH'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'publish_article');

-- 17 工作安排 (OA_ASSIGN → assign)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'assign_task', '工作安排下发', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'assign'
WHERE w.`worker_type` = 'OA_ASSIGN'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'assign_task');

-- 18 重要提醒 (OA_REMIND → remind)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'remind_rule', '提醒规则设置', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'remind'
WHERE w.`worker_type` = 'OA_REMIND'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'remind_rule');

-- 19 用车助手 (OA_VEHICLE → vehicle)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'vehicle_apply', '用车申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'vehicle'
WHERE w.`worker_type` = 'OA_VEHICLE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'vehicle_apply');

-- 20 请假助手 (OA_LEAVE → leave)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'leave_request', '请假申请', t.`code`, NULL, 'LEAVE', 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'leave'
WHERE w.`worker_type` = 'OA_LEAVE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'leave_request');

-- 21 考勤管理 (OA_ATTENDANCE → attendance)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'attendance_appeal', '考勤异常申诉', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'attendance'
WHERE w.`worker_type` = 'OA_ATTENDANCE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'attendance_appeal');

-- 22 文档管理 (OA_DOCMGR → docmgr)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'doc_upload', '文档上传', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'docmgr'
WHERE w.`worker_type` = 'OA_DOCMGR'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'doc_upload');

-- 23 党务助手 (OA_PARTY → party)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'party_apply', '党务事项办理', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'party'
WHERE w.`worker_type` = 'OA_PARTY'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'party_apply');

-- 24 工会工作 (OA_UNION → union)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'union_apply', '工会事项办理', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'union'
WHERE w.`worker_type` = 'OA_UNION'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'union_apply');

-- 25 待办助手 (OA_TODO → todo)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'todo_add', '待办创建', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'todo'
WHERE w.`worker_type` = 'OA_TODO'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'todo_add');

-- 26 委托管理 (OA_DELEGATE → delegate)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'delegate_rule', '委托设置', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'delegate'
WHERE w.`worker_type` = 'OA_DELEGATE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'delegate_rule');

-- 27 门户首页 (OA_PORTAL → portal)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'portal_layout', '门户布局配置', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'portal'
WHERE w.`worker_type` = 'OA_PORTAL'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'portal_layout');

-- 28 审批中心 (OA_APPROVAL → approval)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'approval_launch', '审批发起', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'approval'
WHERE w.`worker_type` = 'OA_APPROVAL'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'approval_launch');

-- 29 人事管理 (OA_HR → hr)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'hr_register', '人事登记', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'hr'
WHERE w.`worker_type` = 'OA_HR'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'hr_register');

-- 30 招聘管理 (OA_RECRUIT → recruit)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'recruit_req', '招聘需求', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'recruit'
WHERE w.`worker_type` = 'OA_RECRUIT'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'recruit_req');

-- 31 培训管理 (OA_TRAIN → train)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'train_signup', '培训报名', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'train'
WHERE w.`worker_type` = 'OA_TRAIN'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'train_signup');

-- 32 知识管理 (OA_KNOWLEDGE → knowledge)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'knowledge_upload', '知识上传', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'knowledge'
WHERE w.`worker_type` = 'OA_KNOWLEDGE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'knowledge_upload');

-- 33 资产管理 (OA_ASSET → asset)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'asset_apply', '资产办理', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'asset'
WHERE w.`worker_type` = 'OA_ASSET'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'asset_apply');

-- 34 合同管理 (OA_CONTRACT → contract)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'contract_draft', '合同起草', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'contract'
WHERE w.`worker_type` = 'OA_CONTRACT'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'contract_draft');

-- 35 任务督办 (OA_TASK → task)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'task_supervise', '督办立项', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'task'
WHERE w.`worker_type` = 'OA_TASK'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'task_supervise');

-- 36 客户管理 (OA_CRM → crm)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'crm_add', '客户建档', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'crm'
WHERE w.`worker_type` = 'OA_CRM'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'crm_add');

-- 37 财务管理 (OA_FINANCE → finance)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'finance_apply', '财务事项申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'finance'
WHERE w.`worker_type` = 'OA_FINANCE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'finance_apply');

-- 38 采购管理 (OA_PURCHASE → purchase)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'purchase_req', '采购申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'purchase'
WHERE w.`worker_type` = 'OA_PURCHASE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'purchase_req');

-- 39 问卷调查 (OA_SURVEY → survey)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'survey_launch', '问卷发起', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'survey'
WHERE w.`worker_type` = 'OA_SURVEY'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'survey_launch');

-- 40 安全与权限 (OA_SECURITY → security)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'security_apply', '权限申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'security'
WHERE w.`worker_type` = 'OA_SECURITY'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'security_apply');

-- 41 系统集成 (OA_INTEGRATION → integration)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'integration_req', '集成申请', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'integration'
WHERE w.`worker_type` = 'OA_INTEGRATION'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'integration_req');

-- 42 数据分析 (OA_ANALYTICS → analytics)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'analytics_board', '看板配置', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'analytics'
WHERE w.`worker_type` = 'OA_ANALYTICS'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'analytics_board');

-- 43 移动办公 (OA_MOBILE → mobile)
INSERT INTO `worker_capability`
    (`tenant_id`, `worker_id`, `task_code`, `task_name`, `form_code`, `tool_names_json`, `approval_biz_type`, `sort`, `enabled`)
SELECT w.`tenant_id`, w.`id`, 'mobile_checkin', '移动签到', t.`code`, NULL, NULL, 0, 1
FROM `agent_worker` w
JOIN `form_template` t ON t.`tenant_id` = w.`tenant_id` AND t.`module_code` = 'mobile'
WHERE w.`worker_type` = 'OA_MOBILE'
  AND NOT EXISTS (SELECT 1 FROM `worker_capability` c WHERE c.`tenant_id` = w.`tenant_id` AND c.`worker_id` = w.`id` AND c.`task_code` = 'mobile_checkin');

