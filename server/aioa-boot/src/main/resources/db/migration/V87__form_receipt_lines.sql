-- V87 · 修复 43 张 OA 模块表单的「声明式回执」结构（docs/52 P4 收口）
--
-- 缺陷：V86 种子的 receipt_json 写的是 {"title","display_fields","buttons"}，
-- 而 FormSubmissionService.renderReceipt 只认 {"title","lines":[{"label","value"}]}
-- ⇒ lines 恒空 ⇒ 每张表单都退化兜底回执「提交单号」，声明式结果卡形同未配置。
--
-- 判据（可复跑）：scripts/_verify_form_flow.py F 组断言 receipt.lines 的 label
-- 全部来自该表单库字段 title，且不再是「提交单号」兜底。
--
-- 注意：本文件通篇不出现「美元符号 + 左花括号」这个序列（含注释也不行）——
-- 回执的值模板需要它，但 Flyway 会把它当成自己的占位符，启动期直接失败
-- （报错「No value provided for placeholder」，且不告诉你是哪个文件）。
-- 生成器 scripts/_gen_oa_form_seed.py 的处理：值模板里先写段落符号 §，
-- 落库时再用 REPLACE(..., '§', CHAR(36)) 还原成真正的符号。
--
-- 幂等：WHERE receipt_json LIKE '%display_fields%' 只修「仍是旧形状」的活行，
-- 不覆盖管理员在设计器里改过的回执；重复执行影响 0 行。

UPDATE form_template SET receipt_json=REPLACE('{"title": "公文助手提交成功", "lines": [{"label": "公文种类", "value": "§{doc_kind}"}, {"label": "公文标题", "value": "§{title}"}, {"label": "紧急程度", "value": "§{urgency}"}, {"label": "涉密等级", "value": "§{secret_level}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='doc_draft' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "档案助手提交成功", "lines": [{"label": "档案类别", "value": "§{archive_type}"}, {"label": "档号", "value": "§{archive_no}"}, {"label": "档案题名", "value": "§{title}"}, {"label": "借阅用途", "value": "§{borrow_use}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='archive_borrow' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "会议助手提交成功", "lines": [{"label": "会议主题", "value": "§{title}"}, {"label": "会议类型", "value": "§{meeting_type}"}, {"label": "开始时间", "value": "§{start_time}"}, {"label": "结束时间", "value": "§{end_time}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='meeting_book' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "通讯录提交成功", "lines": [{"label": "姓名", "value": "§{person_name}"}, {"label": "部门", "value": "§{dept}"}, {"label": "职务", "value": "§{title}"}, {"label": "手机号", "value": "§{phone}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='contact_add' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工作日志提交成功", "lines": [{"label": "日期", "value": "§{log_date}"}, {"label": "今日工作", "value": "§{today_work}"}, {"label": "明日计划", "value": "§{tomorrow_plan}"}, {"label": "关联项目", "value": "§{project_tag}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='worklog_submit' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工作计划提交成功", "lines": [{"label": "计划名称", "value": "§{plan_name}"}, {"label": "计划周期", "value": "§{cycle}"}, {"label": "目标", "value": "§{goal}"}, {"label": "责任人", "value": "§{owner}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='workplan_submit' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工作周报提交成功", "lines": [{"label": "周次", "value": "§{week_no}"}, {"label": "本周完成", "value": "§{done}"}, {"label": "下周计划", "value": "§{next_plan}"}, {"label": "需协调事项", "value": "§{blockers}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='weekly_submit' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "费用报销提交成功", "lines": [{"label": "费用类型", "value": "§{expense_type}"}, {"label": "金额", "value": "§{amount}"}, {"label": "发生日期", "value": "§{occur_date}"}, {"label": "费用说明", "value": "§{reason}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='expense_form' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "出差助手提交成功", "lines": [{"label": "出差地点", "value": "§{destination}"}, {"label": "出发日期", "value": "§{start_date}"}, {"label": "返回日期", "value": "§{end_date}"}, {"label": "出差事由", "value": "§{reason}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='travel_form' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "印章助手提交成功", "lines": [{"label": "印章类型", "value": "§{seal_type}"}, {"label": "用印文件标题", "value": "§{file_title}"}, {"label": "用印事由", "value": "§{reason}"}, {"label": "用印日期", "value": "§{use_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='seal_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "项目助手提交成功", "lines": [{"label": "项目名称", "value": "§{project_name}"}, {"label": "项目目标", "value": "§{goal}"}, {"label": "开始日期", "value": "§{start_date}"}, {"label": "结束日期", "value": "§{end_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='project_create' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "收藏夹提交成功", "lines": [{"label": "收藏类型", "value": "§{fav_type}"}, {"label": "标题", "value": "§{title}"}, {"label": "链接或内容", "value": "§{content}"}, {"label": "标签", "value": "§{tags}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='favorite_add' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "大事记提交成功", "lines": [{"label": "事件标题", "value": "§{event_title}"}, {"label": "事件日期", "value": "§{event_date}"}, {"label": "事件分类", "value": "§{category}"}, {"label": "事件描述", "value": "§{description}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='milestone_add' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工作日历提交成功", "lines": [{"label": "日程标题", "value": "§{event_title}"}, {"label": "开始时间", "value": "§{start_time}"}, {"label": "结束时间", "value": "§{end_time}"}, {"label": "是否全天", "value": "§{all_day}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='calendar_event' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "通知公告提交成功", "lines": [{"label": "标题", "value": "§{title}"}, {"label": "公告分类", "value": "§{category}"}, {"label": "发布范围", "value": "§{scope}"}, {"label": "正文", "value": "§{body}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='notice_publish' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "信息发布提交成功", "lines": [{"label": "栏目", "value": "§{column}"}, {"label": "标题", "value": "§{title}"}, {"label": "正文", "value": "§{body}"}, {"label": "作者", "value": "§{author}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='publish_article' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工作安排提交成功", "lines": [{"label": "任务标题", "value": "§{task_title}"}, {"label": "责任人", "value": "§{owner}"}, {"label": "任务要求", "value": "§{requirement}"}, {"label": "截止日期", "value": "§{due_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='assign_task' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "重要提醒提交成功", "lines": [{"label": "提醒事项", "value": "§{matter}"}, {"label": "提醒类型", "value": "§{remind_type}"}, {"label": "提醒时间", "value": "§{remind_time}"}, {"label": "紧急程度", "value": "§{urgency}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='remind_rule' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "用车助手提交成功", "lines": [{"label": "用车事由", "value": "§{reason}"}, {"label": "出发地", "value": "§{from_addr}"}, {"label": "目的地", "value": "§{to_addr}"}, {"label": "用车开始", "value": "§{start_time}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='vehicle_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "请假助手提交成功", "lines": [{"label": "假种", "value": "§{leave_type}"}, {"label": "开始日期", "value": "§{start_date}"}, {"label": "结束日期", "value": "§{end_date}"}, {"label": "请假天数", "value": "§{days}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='leave_request' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "考勤管理提交成功", "lines": [{"label": "申诉类型", "value": "§{appeal_type}"}, {"label": "申诉日期", "value": "§{appeal_date}"}, {"label": "说明", "value": "§{description}"}, {"label": "证明材料", "value": "§{proof}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='attendance_appeal' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "文档管理提交成功", "lines": [{"label": "文档标题", "value": "§{doc_title}"}, {"label": "文档分类", "value": "§{doc_category}"}, {"label": "共享范围", "value": "§{share_scope}"}, {"label": "有效期至", "value": "§{expire_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='doc_upload' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "党务助手提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "姓名", "value": "§{person_name}"}, {"label": "金额", "value": "§{amount}"}, {"label": "说明", "value": "§{description}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='party_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "工会工作提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "申请人", "value": "§{applicant}"}, {"label": "说明", "value": "§{description}"}, {"label": "附件", "value": "§{attachments}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='union_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "待办助手提交成功", "lines": [{"label": "待办标题", "value": "§{todo_title}"}, {"label": "负责范围", "value": "§{scope}"}, {"label": "截止时间", "value": "§{due_time}"}, {"label": "优先级", "value": "§{priority}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='todo_add' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "委托管理提交成功", "lines": [{"label": "受托人", "value": "§{delegatee}"}, {"label": "委托开始", "value": "§{start_date}"}, {"label": "委托结束", "value": "§{end_date}"}, {"label": "委托事项", "value": "§{matters}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='delegate_rule' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "门户首页提交成功", "lines": [{"label": "工作台名称", "value": "§{workbench_name}"}, {"label": "卡片配置", "value": "§{cards}"}, {"label": "主题", "value": "§{theme}"}, {"label": "备注", "value": "§{remark}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='portal_layout' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "审批中心提交成功", "lines": [{"label": "审批事项", "value": "§{matter}"}, {"label": "审批类型", "value": "§{approval_type}"}, {"label": "紧急程度", "value": "§{urgency}"}, {"label": "说明", "value": "§{description}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='approval_launch' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "人事管理提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "员工姓名", "value": "§{emp_name}"}, {"label": "部门", "value": "§{dept}"}, {"label": "岗位", "value": "§{position}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='hr_register' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "招聘管理提交成功", "lines": [{"label": "需求岗位", "value": "§{position}"}, {"label": "编制数", "value": "§{headcount}"}, {"label": "需求部门", "value": "§{dept}"}, {"label": "期望到岗", "value": "§{expect_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='recruit_req' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "培训管理提交成功", "lines": [{"label": "培训名称", "value": "§{train_name}"}, {"label": "课程类型", "value": "§{course_type}"}, {"label": "讲师", "value": "§{lecturer}"}, {"label": "开始日期", "value": "§{start_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='train_signup' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "知识管理提交成功", "lines": [{"label": "知识标题", "value": "§{knowledge_title}"}, {"label": "知识分类", "value": "§{category}"}, {"label": "标签", "value": "§{tags}"}, {"label": "摘要", "value": "§{summary}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='knowledge_upload' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "资产管理提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "资产名称", "value": "§{asset_name}"}, {"label": "数量", "value": "§{quantity}"}, {"label": "使用部门", "value": "§{dept}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='asset_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "合同管理提交成功", "lines": [{"label": "合同名称", "value": "§{contract_name}"}, {"label": "相对方", "value": "§{counterparty}"}, {"label": "合同金额", "value": "§{amount}"}, {"label": "开始日期", "value": "§{start_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='contract_draft' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "任务督办提交成功", "lines": [{"label": "督办事项", "value": "§{matter}"}, {"label": "责任单位", "value": "§{org_unit}"}, {"label": "责任人", "value": "§{owner}"}, {"label": "截止日期", "value": "§{due_date}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='task_supervise' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "客户管理提交成功", "lines": [{"label": "客户名称", "value": "§{customer_name}"}, {"label": "客户分层", "value": "§{tier}"}, {"label": "联系人", "value": "§{contact}"}, {"label": "联系电话", "value": "§{contact_phone}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='crm_add' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "财务管理提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "金额", "value": "§{amount}"}, {"label": "说明", "value": "§{description}"}, {"label": "关联项目", "value": "§{project}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='finance_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "采购管理提交成功", "lines": [{"label": "采购物品", "value": "§{item}"}, {"label": "数量", "value": "§{quantity}"}, {"label": "预算金额", "value": "§{budget}"}, {"label": "期望到货", "value": "§{expect_arrive}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='purchase_req' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "问卷调查提交成功", "lines": [{"label": "问卷标题", "value": "§{survey_title}"}, {"label": "调研目的", "value": "§{purpose}"}, {"label": "发放范围", "value": "§{scope}"}, {"label": "匿名方式", "value": "§{anonymous}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='survey_launch' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "安全与权限提交成功", "lines": [{"label": "申请类型", "value": "§{apply_type}"}, {"label": "申请对象", "value": "§{target}"}, {"label": "权限范围", "value": "§{scope}"}, {"label": "理由", "value": "§{reason}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='security_apply' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "系统集成提交成功", "lines": [{"label": "集成类型", "value": "§{integration_type}"}, {"label": "系统名称", "value": "§{system_name}"}, {"label": "说明", "value": "§{description}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='integration_req' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "数据分析提交成功", "lines": [{"label": "看板名称", "value": "§{board_name}"}, {"label": "指标范围", "value": "§{metrics}"}, {"label": "推送角色", "value": "§{push_role}"}, {"label": "备注", "value": "§{remark}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='analytics_board' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
UPDATE form_template SET receipt_json=REPLACE('{"title": "移动办公提交成功", "lines": [{"label": "事项类型", "value": "§{matter}"}, {"label": "位置", "value": "§{location}"}, {"label": "说明", "value": "§{description}"}, {"label": "附件", "value": "§{attachments}"}], "buttons": ["查看详情", "返回"]}', '§', CHAR(36))
 WHERE code='mobile_checkin' AND deleted_at IS NULL AND receipt_json LIKE '%display_fields%';
